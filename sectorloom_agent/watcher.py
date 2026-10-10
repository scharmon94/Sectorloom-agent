"""
Finding new telemetry files and getting them uploaded.

Deliberately a polling scan rather than a filesystem event hook: a sim
writes a telemetry file gradually and finishes it when you leave the
session, so what matters is noticing when a file has STOPPED changing.
Polling makes that simple, and it behaves on network and cloud-synced
folders where event hooks often do not.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from . import lmu
from .cloud import AuthExpired, Cloud, CloudError
from .ibt import IbtError, encode_session, read_ibt_file

SETTLE_SECONDS = 15      # a file must be untouched this long before we read it
MAX_REMEMBERED = 4000


def default_dirs() -> Dict[str, str]:
    """Where each sim puts its telemetry on a normal Windows install."""
    home = os.path.expanduser("~")
    docs = os.path.join(home, "Documents")
    one = os.path.join(home, "OneDrive", "Documents")   # very common nowadays
    base = docs if os.path.isdir(docs) else (one if os.path.isdir(one) else docs)
    return {
        "iracing": os.path.join(base, "iRacing", "telemetry"),
        "lmu": os.path.join(base, "Le Mans Ultimate", "UserData", "Telemetry"),
    }


def _date_from_name(name: str, fallback_mtime: float) -> str:
    """iRacing names files '<car> <track> 2026-10-01 19-30-00.ibt'."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})[ _](\d{2})[-.](\d{2})[-.](\d{2})", name)
    if m:
        return f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}"
    return datetime.fromtimestamp(fallback_mtime, timezone.utc).isoformat(timespec="seconds")


def _scan(folder: str, extensions: tuple) -> List[str]:
    found: List[str] = []
    if not folder or not os.path.isdir(folder):
        return found
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(extensions):
                found.append(os.path.join(root, f))
    return found


class Watcher:
    """
    Owns the scan loop. `log` receives one short line per event and `status`
    a single phrase for the tray tooltip.
    """

    def __init__(self, cfg: Dict[str, Any], cloud: Cloud,
                 log: Callable[[str], None],
                 status: Callable[[str], None],
                 save: Callable[[], None]):
        self.cfg = cfg
        self.cloud = cloud
        self.log = log
        self.status = status
        self.save = save
        self.remote_ids: Optional[set] = None
        self.uploaded = set(cfg.get("uploaded") or [])
        self.seen: Dict[str, Dict[str, Any]] = cfg.get("seen") or {}
        self.counts = {"uploaded": 0, "skipped": 0, "failed": 0}

    # ---- helpers --------------------------------------------------------
    def _folders(self) -> List[tuple]:
        d = default_dirs()
        out = []
        if self.cfg.get("watch_iracing", True):
            out.append(("iracing", self.cfg.get("iracing_dir") or d["iracing"], (".ibt",)))
        if self.cfg.get("watch_lmu", True):
            out.append(("lmu", self.cfg.get("lmu_dir") or d["lmu"], (".duckdb", ".db")))
        return out

    def _remember(self, path: str, stat: os.stat_result, **extra) -> None:
        self.seen[path] = {"size": stat.st_size, "mtime": int(stat.st_mtime), **extra}
        if len(self.seen) > MAX_REMEMBERED:
            for key in list(self.seen)[:len(self.seen) - MAX_REMEMBERED]:
                self.seen.pop(key, None)
        self.cfg["seen"] = self.seen
        self.cfg["uploaded"] = list(self.uploaded)[-MAX_REMEMBERED:]
        self.save()

    def _already_handled(self, path: str, stat: os.stat_result) -> bool:
        """
        A file is done with if it has not changed since we last looked.
        That includes ones we could not read: a corrupt file will still be
        corrupt next minute, and re-reporting it every scan buries the log.
        "Retry failed files" clears those.
        """
        prev = self.seen.get(path)
        return bool(prev and prev.get("size") == stat.st_size
                    and prev.get("mtime") == int(stat.st_mtime)
                    and prev.get("status") in ("done", "skipped", "error"))

    def retry_failed(self) -> int:
        """Forget past failures so the next pass has another go."""
        failed = [p for p, v in self.seen.items() if v.get("status") == "error"]
        for p in failed:
            self.seen.pop(p, None)
        self.counts["failed"] = 0
        self.cfg["seen"] = self.seen
        self.save()
        return len(failed)

    def failed_files(self) -> List[str]:
        return [os.path.basename(p) for p, v in self.seen.items()
                if v.get("status") == "error"]

    def _load_remote_ids(self) -> None:
        if self.remote_ids is None:
            try:
                self.remote_ids = set(self.cloud.existing_session_ids())
            except CloudError as e:
                self.log(f"Could not list what is already uploaded: {e}")
                self.remote_ids = set()

    # ---- one file -------------------------------------------------------
    def process(self, sim: str, path: str) -> None:
        name = os.path.basename(path)
        try:
            stat = os.stat(path)
        except OSError:
            return

        self.status(f"Reading {name}")
        meta = {"file": name, "date": _date_from_name(name, stat.st_mtime)}

        try:
            if sim == "iracing":
                session = read_ibt_file(path, meta)
                session["sim"] = "iracing"
            else:
                session = lmu.read(path, meta)
        except (IbtError, lmu.LmuError) as e:
            self.counts["failed"] += 1
            first = str(e).split("\n")[0]
            self.log(f"Skipped {name}: {first}")
            self._remember(path, stat, status="error", msg=str(e)[:4000])
            return
        except Exception as e:  # a malformed file must never stop the agent
            self.counts["failed"] += 1
            self.log(f"Could not read {name}: {e}")
            self._remember(path, stat, status="error", msg=str(e)[:2000])
            return

        complete = [l for l in session["laps"] if l.get("complete")]
        if not complete:
            self.counts["skipped"] += 1
            self.log(f"Skipped {name}: no complete laps in it")
            self._remember(path, stat, status="skipped", id=session["id"])
            return

        sid = session["id"]
        self._load_remote_ids()
        if sid in self.uploaded or sid in (self.remote_ids or set()):
            self.counts["skipped"] += 1
            self.log(f"Already in your library: {name}")
            self._remember(path, stat, status="done", id=sid)
            return

        clean = [l for l in session["laps"] if l.get("clean")]
        best = min((l["time"] for l in clean), default=None)
        self.status(f"Uploading {name}")
        try:
            self.cloud.upload_session(session, encode_session(session))
        except AuthExpired:
            raise
        except CloudError as e:
            self.counts["failed"] += 1
            self.log(f"Upload failed for {name}: {e}")
            return      # not remembered, so it is retried on the next pass

        self.uploaded.add(sid)
        if self.remote_ids is not None:
            self.remote_ids.add(sid)
        self.counts["uploaded"] += 1
        where = session["track"]["name"]
        lap_text = f"{len(clean)} clean lap{'s' if len(clean) != 1 else ''}"
        best_text = f", best {_lap_time(best)}" if best else ""
        self.log(f"Uploaded {name} — {where}, {lap_text}{best_text}")
        self._remember(path, stat, status="done", id=sid)

    # ---- one pass over everything --------------------------------------
    def scan_once(self) -> int:
        handled = 0
        now = time.time()
        for sim, folder, exts in self._folders():
            if not folder or not os.path.isdir(folder):
                continue
            for path in sorted(_scan(folder, exts)):
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                if self._already_handled(path, stat):
                    continue
                if now - stat.st_mtime < SETTLE_SECONDS:
                    continue          # still being written; catch it next time
                self.process(sim, path)
                handled += 1
        return handled

    def missing_folders(self) -> List[str]:
        return [f"{sim}: {folder}" for sim, folder, _ in self._folders()
                if not folder or not os.path.isdir(folder)]


def _lap_time(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    m = int(seconds // 60)
    r = seconds - m * 60
    return f"{m}:{r:06.3f}" if m else f"{r:.3f}"
