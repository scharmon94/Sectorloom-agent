"""
Reading Le Mans Ultimate telemetry.

Since version 1.2 LMU records to a DuckDB file under UserData\\Telemetry.
Studio 397 has not published the table layout, and nothing I could find
documents it, so this module does two things:

  probe()  — opens the file and describes exactly what is inside it, in a
             form you can paste to someone who can finish the mapping.
  read()   — makes a best effort at the mapping using column names, and
             says plainly what it could not find rather than inventing it.

Once a real file has been seen, CHANNEL_HINTS below is the only thing
that should need changing.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .ibt import build_session

# SectorLoom channel  ->  column names to look for, best candidate first.
# Matching is case-insensitive and ignores spaces and underscores.
CHANNEL_HINTS: Dict[str, List[str]] = {
    "SessionTime":        ["sessiontime", "time", "elapsedtime", "currenttime", "timestamp", "t"],
    "Lap":                ["lap", "lapnumber", "lapindex", "currentlap", "lapcount"],
    "LapDistPct":         ["lapdistpct", "lapdistancepct", "normalizedlapdistance", "lapdistnorm", "trackposition", "pathlateralposition"],
    "LapDist":            ["lapdist", "lapdistance", "distance", "distancetraveled", "lapdistm"],
    "Speed":              ["speed", "velocity", "groundspeed", "speedms", "carspeed"],
    "Throttle":           ["throttle", "throttleinput", "unfilteredthrottle", "gas"],
    "Brake":              ["brake", "brakeinput", "unfilteredbrake"],
    "SteeringWheelAngle": ["steering", "steeringangle", "steerangle", "unfilteredsteering", "steeringinput"],
    "Gear":               ["gear", "currentgear"],
    "RPM":                ["rpm", "enginerpm", "enginespeed"],
    "Lat":                ["lat", "latitude", "posy", "positiony", "worldpositiony"],
    "Lon":                ["lon", "long", "longitude", "posx", "positionx", "worldpositionx"],
    "LatAccel":           ["lataccel", "lateralacceleration", "accely", "gforcelateral"],
    "FuelLevel":          ["fuel", "fuellevel", "fuelremaining"],
    "OnPitRoad":          ["inpits", "onpitroad", "pitlane", "inpitlane"],
    "TrackTempCrew":      ["tracktemp", "tracktemperature", "surfacetemp"],
    "AirTemp":            ["airtemp", "ambienttemp", "airtemperature"],
}

# Columns that would make a table the channel log rather than metadata.
CORE = ("SessionTime", "Lap", "Speed")


class LmuError(Exception):
    pass


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _connect(path: str):
    try:
        import duckdb
    except ImportError:  # pragma: no cover - packaged builds always have it
        raise LmuError("DuckDB support is not installed in this build.")
    try:
        return duckdb.connect(path, read_only=True)
    except Exception as e:
        raise LmuError(f"Could not open that telemetry file: {e}")


def _tables(con) -> List[str]:
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema NOT IN ('information_schema','pg_catalog') ORDER BY table_name"
    ).fetchall()
    return [r[0] for r in rows]


def _columns(con, table: str) -> List[Tuple[str, str]]:
    rows = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = ? ORDER BY ordinal_position", [table]).fetchall()
    return [(r[0], r[1]) for r in rows]


def probe(path: str, max_sample_cols: int = 12) -> str:
    """Describe the file. Output is meant to be read by a person."""
    con = _connect(path)
    out: List[str] = []
    out.append(f"File     : {os.path.basename(path)}")
    out.append(f"Size     : {os.path.getsize(path):,} bytes")
    try:
        tables = _tables(con)
        out.append(f"Tables   : {len(tables)}")
        for t in tables:
            try:
                n = con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
            except Exception:
                n = "?"
            cols = _columns(con, t)
            out.append("")
            out.append(f'--- table "{t}"  ({n} rows, {len(cols)} columns) ---')
            for name, dtype in cols:
                out.append(f"    {name}  :  {dtype}")
            if cols and isinstance(n, int) and n:
                picks = [c[0] for c in cols[:max_sample_cols]]
                quoted = ", ".join(f'"{c}"' for c in picks)
                try:
                    rows = con.execute(f'SELECT {quoted} FROM "{t}" LIMIT 3').fetchall()
                    out.append(f"    first rows ({', '.join(picks)}):")
                    for r in rows:
                        out.append("      " + ", ".join(str(v)[:28] for v in r))
                except Exception as e:
                    out.append(f"    (could not sample: {e})")
    finally:
        con.close()
    return "\n".join(out)


def _pick_columns(cols: List[str]) -> Dict[str, str]:
    """Map SectorLoom channel names onto whatever this file calls them."""
    by_norm: Dict[str, str] = {}
    for c in cols:
        by_norm.setdefault(_norm(c), c)
    found: Dict[str, str] = {}
    for channel, hints in CHANNEL_HINTS.items():
        for hint in hints:
            if hint in by_norm:
                found[channel] = by_norm[hint]
                break
        else:
            # fall back to a column that contains the hint
            for hint in hints:
                match = next((orig for norm, orig in by_norm.items()
                              if hint in norm and orig not in found.values()), None)
                if match:
                    found[channel] = match
                    break
    return found


META_HINTS = {
    "track": ["track", "trackname", "circuit", "venue", "trackdisplayname"],
    "car": ["car", "carname", "vehicle", "vehiclename", "carmodel"],
    "driver": ["driver", "drivername", "playername", "username"],
    "trackLen": ["tracklength", "circuitlength", "lapdistance", "tracklen"],
}


def _metadata(con, tables: List[str], channel_table: str) -> Dict[str, Any]:
    """
    Scrape track/car/driver out of whichever small table holds them.
    Handles both a key/value table and a one-row table of named columns.
    """
    found: Dict[str, Any] = {}

    def take(field: str, value: Any) -> None:
        if field in found or value in (None, ""):
            return
        if field == "trackLen":
            try:
                v = float(value)
            except (TypeError, ValueError):
                return
            if v > 100:              # metres, not kilometres
                found[field] = v
        else:
            text = str(value).strip()
            if text and text.lower() not in ("null", "none", "unknown"):
                found[field] = text

    for t in tables:
        if t == channel_table:
            continue
        cols = _columns(con, t)
        if not cols:
            continue
        try:
            n = con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
        except Exception:
            continue
        if not n or n > 200:
            continue
        names = [c[0] for c in cols]
        try:
            rows = con.execute(
                f'SELECT {", ".join(chr(34) + c + chr(34) for c in names)} '
                f'FROM "{t}" LIMIT 200').fetchall()
        except Exception:
            continue

        # key/value shape
        if len(names) == 2:
            for key, value in rows:
                k = _norm(key)
                for field, hints in META_HINTS.items():
                    if k in hints or any(h == k for h in hints):
                        take(field, value)
        # named-column shape
        for row in rows[:1]:
            for name, value in zip(names, row):
                k = _norm(name)
                for field, hints in META_HINTS.items():
                    if k in hints:
                        take(field, value)
    return found


def _best_table(con, tables: List[str]) -> Optional[Tuple[str, Dict[str, str], int]]:
    best = None
    for t in tables:
        cols = [c[0] for c in _columns(con, t)]
        if not cols:
            continue
        mapping = _pick_columns(cols)
        if not all(k in mapping for k in CORE):
            continue
        try:
            n = con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
        except Exception:
            continue
        if n < 100:
            continue
        score = len(mapping) * 1000 + min(n, 10 ** 7) // 1000
        if best is None or score > best[0]:
            best = (score, t, mapping, n)
    return (best[1], best[2], best[3]) if best else None


def read(path: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a SectorLoom session from an LMU file.

    Raises LmuError with the probe output attached when the layout is not
    what this mapping expects — that report is what makes it fixable.
    """
    con = _connect(path)
    try:
        tables = _tables(con)
        if not tables:
            raise LmuError("That telemetry file has no tables in it.")

        chosen = _best_table(con, tables)
        if not chosen:
            raise LmuError(
                "Could not find a channel table in this file — no table has "
                "recognisable time, lap and speed columns.\n\n"
                "Here is what the file actually contains:\n\n" + probe(path)
            )
        table, mapping, n_rows = chosen
        meta_found = _metadata(con, tables, table)

        order = mapping["SessionTime"]
        select = ", ".join(f'"{col}" AS "{chan}"' for chan, col in mapping.items())
        data = con.execute(f'SELECT {select} FROM "{table}" ORDER BY "{order}"').fetchnumpy()
    finally:
        con.close()

    channels: Dict[str, np.ndarray] = {}
    for chan, arr in data.items():
        a = np.asarray(arr)
        if a.dtype.kind == "b":
            a = a.astype(np.float64)
        elif a.dtype.kind not in "fiu":
            continue  # text or timestamps we cannot use as a channel
        channels[chan] = a.astype(np.float64)

    if "SessionTime" not in channels:
        raise LmuError("The time column in this file is not numeric, so laps cannot be built.")

    n = len(channels["SessionTime"])
    if n < 100:
        raise LmuError("That telemetry file has too few samples to analyse.")

    # Lap distance may arrive as metres rather than a 0..1 fraction.
    if "LapDistPct" not in channels and "LapDist" in channels:
        dist = channels.pop("LapDist")
        span = float(np.nanmax(dist)) if len(dist) else 0.0
        if span > 1.5:
            channels["LapDistPct"] = np.clip(dist / span, 0.0, 1.0)
        else:
            channels["LapDistPct"] = np.clip(dist, 0.0, 1.0)
    channels.pop("LapDist", None)

    if "LapDistPct" not in channels:
        raise LmuError(
            "No lap-distance column found, so laps cannot be split.\n\n"
            "Here is what the file contains:\n\n" + probe(path))

    # Speed is sometimes km/h; the rest of SectorLoom works in metres per second.
    spd = channels.get("Speed")
    if spd is not None and len(spd) and float(np.nanpercentile(spd, 95)) > 140:
        channels["Speed"] = spd / 3.6

    # Throttle and brake as percentages rather than 0..1.
    for pedal in ("Throttle", "Brake"):
        a = channels.get(pedal)
        if a is not None and len(a) and float(np.nanmax(a)) > 1.5:
            channels[pedal] = a / 100.0

    t = channels["SessionTime"]
    dt = np.diff(t)
    positive = dt[dt > 0]
    tick = float(1.0 / np.median(positive)) if len(positive) else 60.0
    tick = min(max(tick, 1.0), 1000.0)

    stem = os.path.splitext(os.path.basename(path))[0]
    info = {
        "trackId": "",
        "trackName": meta.get("track") or meta_found.get("track") or stem,
        "config": "", "city": "", "country": "", "turns": "", "type": "",
        "trackLen": float(meta.get("trackLen") or meta_found.get("trackLen") or 0),
        "carId": "",
        "car": meta.get("car") or meta_found.get("car") or "Le Mans Ultimate car",
        "carClass": "",
        "driver": meta.get("driver") or meta_found.get("driver") or "",
        "sessionType": "LMU",
        "cond": {k: None for k in (
            "surfaceC", "airC", "humidity", "windKph", "windDir", "skies", "fog",
            "precip", "cleanup", "dynamic", "usage", "weatherType", "timeOfDay",
            "fixedSetup", "altitudeM")},
    }

    parsed = {"n": n, "tickRate": tick, "ch": channels, "info": info, "setup": None}
    session = build_session(parsed, meta)
    session["sim"] = "lmu"
    return session


def read_lmu_file(path: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    return read(path, meta)
