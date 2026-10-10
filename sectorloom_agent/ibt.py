"""
Reading iRacing .ibt telemetry files.

This is a faithful port of the parser inside SectorLoom's web app. The two
must agree, because a session built here is stored in exactly the same
shape as one the browser built — same lap detection, same 1000-point
resampling, same stint boundaries. tests/test_parity.py runs one file
through both and compares them.
"""
from __future__ import annotations

import base64
import math
import re
import struct
from typing import Any, Dict, List, Optional

import json as _json
import numpy as np

GRID = 1000  # samples per lap, matching the web app's G

WANT = [
    "SessionTime", "Lap", "LapDistPct", "Speed", "Throttle", "Brake",
    "SteeringWheelAngle", "Gear", "RPM", "Lat", "Lon", "LatAccel",
    "OnPitRoad", "PlayerTrackSurface", "FuelLevel",
    # fuel and tyre loading, added with the web app's seventh update.
    # Wheel speeds are not logged by every car; everything here is
    # optional and simply absent when the car does not record it.
    "LongAccel", "FuelLevelPct", "FuelUsePerHour",
    "LFspeed", "RFspeed", "LRspeed", "RRspeed",
    # how the car is sitting, the driver aids, and the tyre readings —
    # all optional, and all absent on plenty of cars
    "Yaw", "YawRate", "VelocityX", "VelocityY", "SessionNum",
    "BrakeABSactive", "dcABS", "dcTractionControl", "dcTractionControlToggle",
    "LFwearL", "LFwearM", "LFwearR", "RFwearL", "RFwearM", "RFwearR",
    "LRwearL", "LRwearM", "LRwearR", "RRwearL", "RRwearM", "RRwearR",
    "LFtempCL", "LFtempCM", "LFtempCR", "RFtempCL", "RFtempCM", "RFtempCR",
    "LRtempCL", "LRtempCM", "LRtempCR", "RRtempCL", "RRtempCM", "RRtempCR",
    "TrackTempCrew", "TrackTemp", "AirTemp", "RelativeHumidity",
    "WindVel", "WindDir", "TrackWetness", "Precipitation",
    "AirPressure", "SolarAltitude",
]

# .ibt variable type codes -> (struct format, width)
_TYPES = {0: ("b", 1), 1: ("b", 1), 2: ("i", 4), 3: ("i", 4), 4: ("f", 4), 5: ("d", 8)}


class IbtError(Exception):
    """A file we could not read. The message is shown to the user."""


def _cstr(buf: bytes, off: int, length: int) -> str:
    end = buf.find(b"\0", off, off + length)
    if end < 0:
        end = off + length
    return buf[off:end].decode("latin-1", "replace").strip()


def parse_ibt(data: bytes) -> Dict[str, Any]:
    """Pull the channels and session YAML out of a .ibt file."""
    if len(data) < 144:
        raise IbtError("File is too small to be an iRacing .ibt file.")

    tick_rate = struct.unpack_from("<i", data, 8)[0]
    info_len = struct.unpack_from("<i", data, 16)[0]
    info_off = struct.unpack_from("<i", data, 20)[0]
    num_vars = struct.unpack_from("<i", data, 24)[0]
    var_off = struct.unpack_from("<i", data, 28)[0]
    buf_len = struct.unpack_from("<i", data, 36)[0]
    data_off = struct.unpack_from("<i", data, 52)[0]
    rec_count = struct.unpack_from("<i", data, 140)[0]

    if (num_vars <= 0 or num_vars > 10000 or buf_len <= 0 or var_off <= 0
            or var_off + num_vars * 144 > len(data)
            or data_off <= 0 or data_off > len(data)):
        raise IbtError(
            "That isn't an iRacing .ibt file. iRacing writes them into "
            "Documents/iRacing/telemetry while telemetry logging is on."
        )

    variables: Dict[str, Dict[str, int]] = {}
    for i in range(num_vars):
        o = var_off + i * 144
        vtype = struct.unpack_from("<i", data, o)[0]
        voff = struct.unpack_from("<i", data, o + 4)[0]
        name = _cstr(data, o + 16, 32)
        if name:
            variables[name] = {"type": vtype, "offset": voff}

    max_rec = (len(data) - data_off) // buf_len
    n = min(rec_count, max_rec) if rec_count > 0 else max_rec
    if n < 10:
        raise IbtError("The file has no recorded samples.")

    # One strided read per channel beats looping in Python by a wide margin.
    raw = np.frombuffer(data, dtype=np.uint8, count=n * buf_len, offset=data_off)
    raw = raw.reshape(n, buf_len)

    channels: Dict[str, np.ndarray] = {}
    for name in WANT:
        v = variables.get(name)
        if not v or v["type"] not in _TYPES:
            continue
        fmt, width = _TYPES[v["type"]]
        off = v["offset"]
        if off < 0 or off + width > buf_len:
            continue
        col = raw[:, off:off + width].tobytes()
        if v["type"] in (0, 1):
            arr = np.frombuffer(col, dtype=np.uint8)
        elif v["type"] in (2, 3):
            arr = np.frombuffer(col, dtype="<i4")
        elif v["type"] == 4:
            arr = np.frombuffer(col, dtype="<f4")
        else:
            arr = np.frombuffer(col, dtype="<f8")
        channels[name] = arr.astype(np.float64)

    for required in ("SessionTime", "Lap", "LapDistPct", "Speed"):
        if required not in channels:
            raise IbtError(
                f"The file is missing the {required} channel, so laps cannot be built."
            )

    yaml = ""
    if info_off > 0 and info_len > 0 and info_off + info_len <= len(data):
        blob = data[info_off:info_off + info_len]
        z = blob.find(b"\0")
        if z >= 0:
            blob = blob[:z]
        yaml = blob.decode("latin-1", "replace")

    return {
        "n": n,
        "tickRate": tick_rate or 60,
        "ch": channels,
        "info": read_info(yaml),
        "setup": parse_setup(yaml),
    }


# --------------------------------------------------------------------------
#  Session YAML
# --------------------------------------------------------------------------
def _field(yaml: str, key: str, src: Optional[str] = None) -> str:
    m = re.search(r"\n\s*" + re.escape(key) + r":[ \t]*([^\n]*)", src if src is not None else yaml)
    return m.group(1).strip() if m else ""


def _num(text: str) -> Optional[float]:
    m = re.search(r"(-?[\d.]+)", str(text))
    return float(m.group(1)) if m else None


def _to_c(value: Optional[float], raw: str) -> Optional[float]:
    if value is None:
        return None
    return (value - 32) * 5 / 9 if re.search(r"F\b|deg F", str(raw)) else value


def read_info(yaml: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "trackId": _field(yaml, "TrackID"),
        "trackName": _field(yaml, "TrackDisplayName") or _field(yaml, "TrackName"),
        "config": _field(yaml, "TrackConfigName"),
        "city": _field(yaml, "TrackCity"),
        "country": _field(yaml, "TrackCountry"),
        "turns": _field(yaml, "TrackNumTurns"),
        "type": _field(yaml, "TrackType"),
        "trackLen": 0.0,
        "carId": "", "car": "", "carClass": "", "driver": "", "sessionType": "",
    }
    if info["config"] == "null":
        info["config"] = ""

    m = re.search(r"TrackLength:[ \t]*([\d.]+)[ \t]*(km|mi)", yaml)
    if m:
        info["trackLen"] = float(m.group(1)) * (1609.344 if m.group(2) == "mi" else 1000)

    idx = _field(yaml, "DriverCarIdx")
    if idx:
        parts = re.split(r"\n\s*-\s*CarIdx:[ \t]*", yaml)
        for part in parts[1:]:
            lead = re.match(r"\s*(\d+)", part)
            if lead and int(lead.group(1)) == int(float(idx)):
                info["car"] = _field(yaml, "CarScreenName", part)
                info["carId"] = _field(yaml, "CarID", part)
                info["carClass"] = _field(yaml, "CarClassShortName", part)
                info["driver"] = _field(yaml, "UserName", part)
                break

    # ---- iRacing's own sector boundaries ----
    info["sectors"] = None
    at = yaml.find("\nSplitTimeInfo:")
    if at >= 0:
        block = yaml[at:at + 4000]
        vals = [float(v) for v in re.findall(r"SectorStartPct:[ \t]*([\d.]+)", block)]
        uniq = sorted({v for v in vals if 0 <= v < 1})
        if len(uniq) >= 2:
            if uniq[0] > 0.0001:
                uniq.insert(0, 0.0)
            info["sectors"] = uniq[:12]

    # ---- which session this was, and what the driver's entry says ----
    info["subSessionId"] = _field(yaml, "SubSessionID") or ""
    info["seriesId"] = _field(yaml, "SeriesID") or ""
    info["eventType"] = _field(yaml, "EventType") or ""
    info["official"] = _field(yaml, "Official") == "1"
    pit_raw = _field(yaml, "TrackPitSpeedLimit")
    pit = _num(pit_raw)
    info["pitSpeedKph"] = (pit * 1.609344 if re.search(r"mph", pit_raw or "", re.I) else pit) if pit is not None else None
    info["me"] = None
    if idx:
        parts = re.split(r"\n\s*-\s*CarIdx:[ \t]*", yaml)
        for part in parts[1:]:
            lead = re.match(r"\s*(\d+)", part)
            if lead and int(lead.group(1)) == int(float(idx)):
                sub = _num(_field(yaml, "LicSubLevel", part))
                me = {
                    "iRating": _num(_field(yaml, "IRating", part)),
                    "licence": (_field(yaml, "LicString", part) or "").strip('"'),
                    "licLevel": _num(_field(yaml, "LicLevel", part)),
                    "safety": None if sub is None else (sub / 100 if sub > 20 else sub),
                    "number": (_field(yaml, "CarNumber", part) or "").strip('"'),
                    "team": (_field(yaml, "TeamName", part) or "").strip('"'),
                }
                if me["iRating"] or me["licence"] or me["number"] or me["team"]:
                    info["me"] = me
                break

    types = [t.strip() for t in re.findall(r"SessionType:[ \t]*([^\n]+)", yaml)]
    seen: List[str] = []
    for t in types:
        if t not in seen:
            seen.append(t)
    info["sessionType"] = " / ".join(seen)

    wind_raw = _field(yaml, "TrackWindVel")
    wind = _num(wind_raw)
    if wind is not None:
        if re.search(r"mph", wind_raw, re.I):
            wind *= 1.609344
        elif re.search(r"m/s", wind_raw, re.I):
            wind *= 3.6

    alt_raw = _field(yaml, "TrackAltitude")
    alt = _num(alt_raw)
    if alt is not None and re.search(r"ft", alt_raw, re.I):
        alt *= 0.3048

    info["cond"] = {
        "surfaceC": _to_c(_num(_field(yaml, "TrackSurfaceTemp")), _field(yaml, "TrackSurfaceTemp")),
        "airC": _to_c(_num(_field(yaml, "TrackAirTemp")), _field(yaml, "TrackAirTemp")),
        "humidity": _num(_field(yaml, "TrackRelativeHumidity")),
        "windKph": wind,
        "windDir": _field(yaml, "TrackWindDir"),
        "skies": _field(yaml, "TrackSkies") or _field(yaml, "Skies"),
        "fog": _num(_field(yaml, "TrackFogLevel")),
        "precip": _num(_field(yaml, "TrackPrecipitation")),
        "cleanup": _field(yaml, "TrackCleanup"),
        "dynamic": _field(yaml, "TrackDynamicTrackState"),
        "usage": _field(yaml, "TrackUsage"),
        "weatherType": _field(yaml, "WeatherType") or _field(yaml, "TrackWeatherType"),
        "timeOfDay": _field(yaml, "TimeOfDay"),
        "fixedSetup": _field(yaml, "IsFixedSetup") == "1",
        "altitudeM": alt,
    }
    return info


def parse_setup(yaml: str) -> Optional[Dict[str, Any]]:
    """The CarSetup block: indentation-nested values, units included."""
    at = yaml.find("\nCarSetup:")
    if at < 0:
        return None
    lines = yaml[at + 1:].split("\n")
    root: Dict[str, Any] = {}
    stack: List[Dict[str, Any]] = [{"ind": -1, "obj": root}]
    for line in lines[1:]:
        if line.startswith("..."):
            break
        if not line.strip():
            continue
        ind = len(line) - len(line.lstrip(" "))
        if ind == 0:
            break
        m = re.match(r"^\s*([^:]+):[ \t]*(.*)$", line)
        if not m:
            continue
        while len(stack) > 1 and stack[-1]["ind"] >= ind:
            stack.pop()
        parent = stack[-1]["obj"]
        key, val = m.group(1).strip(), m.group(2).strip()
        if val == "":
            child: Dict[str, Any] = {}
            parent[key] = child
            stack.append({"ind": ind, "obj": child})
        else:
            parent[key] = val
    return root or None


def live_cond(parsed: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """What the track actually did while you were on it."""
    ch, n = parsed["ch"], parsed["n"]

    def avg(key: str) -> Optional[float]:
        a = ch.get(key)
        if a is None or not len(a):
            return None
        return float(np.mean(a[::7]))

    out: Dict[str, Optional[float]] = {}
    out["surfaceC"] = avg("TrackTempCrew")
    if out["surfaceC"] is None:
        out["surfaceC"] = avg("TrackTemp")
    out["airC"] = avg("AirTemp")
    h = avg("RelativeHumidity")
    out["humidity"] = None if h is None else (h * 100 if h <= 1.5 else h)
    w = avg("WindVel")
    out["windKph"] = None if w is None else w * 3.6
    out["wetness"] = avg("TrackWetness")
    p = avg("Precipitation")
    out["precip"] = None if p is None else (p * 100 if p <= 1.5 else p)
    return out


# --------------------------------------------------------------------------
#  Building a session
# --------------------------------------------------------------------------
def _js_number(x: float) -> str:
    """
    Stringify a float the way JavaScript does.

    The session id is a hash of "<file>|<samples>|<first timestamp>", and it
    has to come out identical to the browser's, or the same .ibt imported
    both ways would land twice. JavaScript writes a whole number as "300";
    Python would write "300.0". Both use shortest-round-trip for the rest.
    """
    f = float(x)
    if math.isnan(f):
        return "NaN"
    if math.isinf(f):
        return "Infinity" if f > 0 else "-Infinity"
    if f == int(f) and abs(f) < 1e21:
        return str(int(f))
    return repr(f)


def _hash(text: str) -> str:
    h = 5381
    for c in text:
        h = ((h << 5) + h + ord(c)) & 0xFFFFFFFF
    return format(h, "x")


def _make_grid(parsed, lap, origin) -> Dict[str, np.ndarray]:
    ch = parsed["ch"]
    t, pct = ch["SessionTime"], ch["LapDistPct"]
    lo = lap["i0"] - 1 if lap["contigPrev"] else lap["i0"]
    hi = lap["i1"] + 1 if lap["contigNext"] else lap["i1"]

    idx: List[int] = []
    pcts: List[float] = []
    last = -math.inf
    for k in range(lo, hi + 1):
        p = float(pct[k])
        if k < lap["i0"]:
            if p > 0.5:
                p -= 1
        elif k > lap["i1"]:
            if p < 0.5:
                p += 1
        else:
            if k - lap["i0"] < 40 and p > 0.9:
                p -= 1
            if lap["i1"] - k < 40 and p < 0.1:
                p += 1
        if p > last:
            idx.append(k)
            pcts.append(p)
            last = p

    names = {"spd": "Speed", "thr": "Throttle", "brk": "Brake",
             "str": "SteeringWheelAngle", "gear": "Gear", "rpm": "RPM", "latg": "LatAccel",
             "longg": "LongAccel",
             "yawr": "YawRate", "abs": "BrakeABSactive",
             "wLF": "LFspeed", "wRF": "RFspeed", "wLR": "LRspeed", "wRR": "RRspeed",
             "vX": "VelocityX", "vY": "VelocityY"}
    keys = [k for k, src in names.items() if src in ch]
    gps = origin is not None and "Lat" in ch and "Lon" in ch

    out: Dict[str, np.ndarray] = {"t": np.zeros(GRID, dtype=np.float32)}
    for k in keys:
        out[k] = np.zeros(GRID, dtype=np.float32)
    if gps:
        out["x"] = np.zeros(GRID, dtype=np.float32)
        out["y"] = np.zeros(GRID, dtype=np.float32)

    t0 = lap["start"] if lap["start"] is not None else float(t[lap["i0"]])
    cosl = math.cos(origin[0] * math.pi / 180) if gps else 1.0

    j = 0
    for g in range(GRID):
        p = g / (GRID - 1)
        while j < len(pcts) - 2 and pcts[j + 1] < p:
            j += 1
        a = idx[j]
        b = idx[min(j + 1, len(idx) - 1)]
        pa = pcts[j]
        pb = pcts[min(j + 1, len(pcts) - 1)]
        f = (p - pa) / (pb - pa) if pb > pa else 0.0
        f = 0.0 if f < 0 else (1.0 if f > 1 else f)

        out["t"][g] = t[a] + f * (t[b] - t[a]) - t0
        for k in keys:
            arr = ch[names[k]]
            if k == "gear":
                out[k][g] = arr[a] if f < 0.5 else arr[b]
            else:
                out[k][g] = arr[a] + f * (arr[b] - arr[a])
        if gps:
            la = ch["Lat"][a] + f * (ch["Lat"][b] - ch["Lat"][a])
            lo2 = ch["Lon"][a] + f * (ch["Lon"][b] - ch["Lon"][a])
            out["x"][g] = (lo2 - origin[1]) * cosl * 111320
            out["y"][g] = (la - origin[0]) * 110540

    # The four wheel speeds collapse into one signed slip trace — the wheel
    # furthest from the car's own speed at that moment. Negative is a wheel
    # turning slower than the car (locking), positive is faster (spinning).
    # Mirrors the web app exactly, including doing the arithmetic in double
    # precision and storing the result as float32, so the two agree.
    # The angle between where the car is pointing and where it is going.
    # iRacing gives the velocity in the car's own frame, so it falls
    # straight out of the arctangent. Degrees.
    if "vX" in out and "vY" in out:
        sa = np.zeros(GRID, dtype=np.float32)
        for g in range(GRID):
            vx = float(out["vX"][g])
            sa[g] = 0.0 if abs(vx) < 2 else math.atan2(float(out["vY"][g]), vx) * 57.2957795
        out["slipa"] = sa
    out.pop("vX", None)
    out.pop("vY", None)
    ws = [k for k in ("wLF", "wRF", "wLR", "wRR") if k in out]
    if ws:
        slip = np.zeros(GRID, dtype=np.float32)
        for g in range(GRID):
            v = float(out["spd"][g])
            if v < 6:
                continue                       # at a crawl the ratio is noise
            worst = 0.0
            for k in ws:
                r = (float(out[k][g]) - v) / v
                if abs(r) > abs(worst):
                    worst = r
            slip[g] = worst
        out["slip"] = slip
    for k in ws:
        del out[k]
    return out


TYRE_CORNERS = ["LF", "RF", "LR", "RR"]


def tyre_reads(parsed) -> Any:
    """iRacing refreshes tread and carcass temperature only when a tyre
    comes off the car, so these are a few snapshots, not a trace."""
    ch, n = parsed["ch"], parsed["n"]
    wear = lambda co: [ch.get(co + "wear" + p) for p in ("L", "M", "R")]
    temp = lambda co: [ch.get(co + "tempC" + p) for p in ("L", "M", "R")]
    have_w = all(all(a is not None for a in wear(co)) for co in TYRE_CORNERS)
    have_t = all(all(a is not None for a in temp(co)) for co in TYRE_CORNERS)
    if not have_w and not have_t:
        return None

    def pct(v):
        return round(float(v) * 100 if float(v) <= 1.5 else float(v), 1)

    def snap(i):
        o = {}
        for co in TYRE_CORNERS:
            o[co] = {
                "wear": [pct(a[i]) for a in wear(co)] if have_w else None,
                "temp": [round(float(a[i]), 1) for a in temp(co)] if have_t else None,
            }
        return o

    step = max(1, round(parsed["tickRate"] / 4))
    out, last = [], ""
    for i in range(0, n, step):
        o = snap(i)
        k = _json.dumps(o, sort_keys=False)
        if k == last:
            continue
        out.append({"at": float(ch["SessionTime"][i]) if "SessionTime" in ch else None,
                    "lap": int(ch["Lap"][i]) if "Lap" in ch else None,
                    "t": o})
        last = k
        if len(out) >= 40:
            break
    return out or None


def _stint_stats(laps: List[dict]) -> Dict[str, Any]:
    clean = [l for l in laps if l["clean"]]
    times = [l["time"] for l in clean]
    avg = sum(times) / len(times) if times else None
    sd = None
    if len(times) > 1:
        sd = math.sqrt(sum((x - avg) ** 2 for x in times) / (len(times) - 1))
    fuels = [l["fuel"] for l in laps if l.get("fuel") and l["clean"]]
    return {
        "total": len(laps),
        "cleanN": len(clean),
        "best": min(times) if times else None,
        "avg": avg,
        "sd": sd,
        "fuel": (sum(fuels) / len(fuels)) if fuels else None,
    }


def build_session(parsed: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a parsed file into the session record SectorLoom stores."""
    ch = parsed["ch"]
    t, lap_no, pct = ch["SessionTime"], ch["Lap"], ch["LapDistPct"]
    n = parsed["n"]
    gap = 2.5 / parsed["tickRate"] + 0.05
    info = parsed["info"]

    sid = meta.get("id") or ("s" + _hash(f"{meta['file']}|{n}|{_js_number(t[0])}"))
    track_len = info["trackLen"] or 4000

    # ---- group samples into laps ----
    groups: List[dict] = []
    s0 = 0
    for i in range(1, n + 1):
        if i == n or lap_no[i] != lap_no[i - 1] or t[i] - t[i - 1] > gap:
            groups.append({
                "num": int(lap_no[s0]), "i0": s0, "i1": i - 1,
                "gapAfter": bool(i < n and t[i] - t[i - 1] > gap),
            })
            s0 = i

    for k, g in enumerate(groups):
        prev = groups[k - 1] if k > 0 else None
        g["contigPrev"] = bool(prev and not prev["gapAfter"] and g["num"] == prev["num"] + 1)
        if g["contigPrev"]:
            a, b = g["i0"] - 1, g["i0"]
            pa, pb = float(pct[a]), float(pct[b])
            fr = 1.0
            if pa > 0.5 > pb:
                fr = (1 - pa) / ((1 - pa) + pb)
            g["start"] = float(t[a] + fr * (t[b] - t[a]))
        else:
            g["start"] = None

    # ---- stint boundaries: pit exits and gaps in the recording ----
    cuts: List[int] = []
    on_pit = ch.get("OnPitRoad")
    for i in range(1, n):
        if on_pit is not None and on_pit[i - 1] and not on_pit[i]:
            cuts.append(i)
        if t[i] - t[i - 1] > gap:
            cuts.append(i)

    origin = None
    if "Lat" in ch and "Lon" in ch:
        for i in range(0, n, 10):
            if ch["Lat"][i] != 0 and ch["Lon"][i] != 0:
                origin = (float(ch["Lat"][i]), float(ch["Lon"][i]))
                break

    surface = ch.get("PlayerTrackSurface")
    sectors = info.get("sectors") if (info.get("sectors") and len(info["sectors"]) > 1) else None
    fuel_ch = ch.get("FuelLevel")
    fuel_max = None
    if fuel_ch is not None and len(fuel_ch):
        m = float(np.max(fuel_ch))
        fuel_max = m if m > 0.5 else None

    laps: List[dict] = []
    for k, g in enumerate(groups):
        nxt = groups[k + 1] if k + 1 < len(groups) else None
        g["contigNext"] = bool(nxt and nxt["contigPrev"] and not g["gapAfter"])
        time = (nxt["start"] - g["start"]) if (g["start"] is not None and g["contigNext"]) else None
        if g["i1"] - g["i0"] + 1 < 20:
            continue

        pit = False
        off = 0
        if on_pit is not None and on_pit[g["i0"]:g["i1"] + 1].any():
            pit = True
        if surface is not None:
            off = int((surface[g["i0"]:g["i1"] + 1] == 0).sum())

        raw_stint = sum(1 for x in cuts if x <= g["i1"])
        lap: Dict[str, Any] = {
            "id": f"{sid}:{len(laps)}",
            "sid": sid,
            "num": g["num"],
            "time": time,
            "pit": pit,
            "off": off > parsed["tickRate"] * 0.25,
            "complete": time is not None and time > 8,
            "rawStint": raw_stint,
        }
        lap["clean"] = bool(lap["complete"] and not lap["pit"] and not lap["off"])
        if fuel_ch is not None and g["contigNext"]:
            used = float(fuel_ch[g["i0"]] - fuel_ch[nxt["i0"]])
            if 0 < used < 50:
                lap["fuel"] = used
        if lap["complete"]:
            lap["g"] = _make_grid(parsed, g, origin)
        # sector times, cut at iRacing's own boundaries
        if lap.get("g") is not None and sectors:
            sec = []
            for i, s0 in enumerate(sectors):
                s1 = sectors[i + 1] if i + 1 < len(sectors) else 1.0
                a0 = round(s0 * (GRID - 1))
                b0 = round(s1 * (GRID - 1))
                d = float(lap["g"]["t"][b0] - lap["g"]["t"][a0])
                sec.append(d if d > 0 and math.isfinite(d) else None)
            lap["sec"] = sec
        laps.append(lap)

    # ---- stints ----
    raw_ids: List[int] = []
    for l in laps:
        if l["rawStint"] not in raw_ids:
            raw_ids.append(l["rawStint"])
    stints: List[dict] = [{"no": i + 1, "lapIds": []} for i in range(len(raw_ids))]
    for l in laps:
        l["stint"] = raw_ids.index(l.pop("rawStint")) + 1
        stints[l["stint"] - 1]["lapIds"].append(l["id"])

    clean = [l for l in laps if l["clean"]]
    best = min(clean, key=lambda l: l["time"]) if clean else None
    for l in laps:
        l["best"] = (best is not None and l["id"] == best["id"])

    by_id = {l["id"]: l for l in laps}
    for st in stints:
        members = [by_id[i] for i in st["lapIds"]]
        st.update(_stint_stats(members))
        st["firstLap"] = members[0]["num"]
        st["lastLap"] = members[-1]["num"]

    # ---- outline for the library thumbnail ----
    track_map = None
    map_lap = best if (best and "g" in best and "x" in best["g"]) else next(
        (l for l in laps if "g" in l and "x" in l["g"]), None)
    if map_lap is not None:
        gx, gy = map_lap["g"]["x"], map_lap["g"]["y"]
        track_map = {
            "x": [round(float(gx[i]) * 10) / 10 for i in range(0, GRID, 4)],
            "y": [round(float(gy[i]) * 10) / 10 for i in range(0, GRID, 4)],
        }

    track_key = ("id" + info["trackId"]) if info["trackId"] else ("n" + info["trackName"] + "|" + info["config"])

    declared = info.get("cond") or {}
    live = live_cond(parsed)
    cond: Dict[str, Any] = {}
    for key in ("surfaceC", "airC", "humidity", "windKph", "precip", "wetness"):
        v = live.get(key)
        if v is None or not math.isfinite(v):
            v = declared.get(key)
            if v is not None and not math.isfinite(v):
                v = None
        cond[key] = v
    for key in ("windDir", "skies", "cleanup", "dynamic", "usage",
                "weatherType", "timeOfDay", "fog", "altitudeM", "fixedSetup"):
        cond[key] = declared.get(key) or None

    return {
        "id": sid,
        "v": 2,
        "file": meta["file"],
        "date": meta.get("date"),
        "sample": False,
        "trackKey": track_key,
        "track": {
            "id": info["trackId"], "name": info["trackName"] or "Unknown track",
            "config": info["config"], "city": info["city"], "country": info["country"],
            "turns": info["turns"], "type": info["type"], "len": track_len,
        },
        "car": {"id": info["carId"], "name": info["car"] or "Unknown car", "cls": info["carClass"]},
        "driver": info["driver"],
        "sessionType": info["sessionType"],
        "cond": cond,
        "laps": laps,
        "stints": stints,
        "bestId": best["id"] if best else None,
        "map": track_map,
        "setup": parsed.get("setup"),
        # the most fuel seen aboard: a real observation, and a better
        # default tank size than guessing at the car's capacity
        "fuelMax": fuel_max,
        "sectors": sectors,
        "entry": info.get("me"),
        "sub": ({"id": info["subSessionId"],
                 "num": int(ch["SessionNum"][0]) if "SessionNum" in ch else None,
                 "series": info.get("seriesId") or "",
                 "event": info.get("eventType") or "",
                 "official": bool(info.get("official"))}
                if info.get("subSessionId") else None),
        "tyres": tyre_reads(parsed),
        "aids": (lambda: (
            {k: v for k, v in (
                ("tc", round(float(ch["dcTractionControl"][0]) * 100) / 100 if "dcTractionControl" in ch else None),
                ("absSetting", round(float(ch["dcABS"][0]) * 100) / 100 if "dcABS" in ch else None),
                ("absLogged", True if "BrakeABSactive" in ch else None),
            ) if v is not None} or None))(),
    }


# --------------------------------------------------------------------------
#  Encoding, byte-for-byte compatible with the web app's encode()
# --------------------------------------------------------------------------
class _F32Encoder:
    """Float32 arrays travel as {"$f32": "<base64 little-endian>"}."""

    @staticmethod
    def default(obj):
        if isinstance(obj, np.ndarray):
            return {"$f32": base64.b64encode(obj.astype("<f4").tobytes()).decode("ascii")}
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        raise TypeError(f"cannot encode {type(obj)!r}")


def encode_session(session: Dict[str, Any]) -> str:
    import json
    return json.dumps(session, default=_F32Encoder.default, allow_nan=False, separators=(",", ":"))


def read_ibt_file(path: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    with open(path, "rb") as fh:
        return build_session(parse_ibt(fh.read()), meta)
