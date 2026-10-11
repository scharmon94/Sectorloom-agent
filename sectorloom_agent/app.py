"""
The agent itself: sign in, watch the folders, upload what turns up.

Run with no arguments for the normal windowed/tray version. The flags are
there for testing and for people who would rather run it from a scheduled
task than leave something in the tray.

  --once         sign in, do one pass, print what happened, exit
  --no-gui       run the loop in a console window instead of the tray
  --probe FILE   describe a Le Mans Ultimate telemetry file and exit
  --where        print the folders it would watch and exit
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

from .cloud import (AuthExpired, Cloud, CloudError, discover, load_config,
                     save_config)
from .watcher import Watcher, default_dirs

APP_NAME = "SectorLoom Telemetry Agent"
POLL_FLOOR = 5


class Agent:
    def __init__(self) -> None:
        self.cfg: Dict[str, Any] = load_config()
        self.cloud: Optional[Cloud] = None
        self.watcher: Optional[Watcher] = None
        self.window = None
        self.tray = None
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.paused = False
        self.state = "Starting"
        self.lines: list = []

    # ---- plumbing -------------------------------------------------------
    def save(self) -> None:
        if self.cloud and self.cloud.refresh_token:
            self.cfg["refresh_token"] = self.cloud.refresh_token
            self.cfg["email"] = self.cloud.email or self.cfg.get("email", "")
        save_config(self.cfg)

    def log(self, line: str) -> None:
        stamped = f"{datetime.now().strftime('%H:%M:%S')}  {line}"
        self.lines.append(stamped)
        del self.lines[:-500]
        if self.window:
            self.window.log(stamped)
        else:
            print(stamped, flush=True)

    def set_state(self, text: str) -> None:
        self.state = text
        if self.window:
            self.window.set_foot(text)
        if self.tray:
            try:
                self.tray.title = f"{APP_NAME} — {text}"
            except Exception:
                pass

    # ---- account --------------------------------------------------------
    def resolve_project(self, force: bool = False) -> None:
        """Work out which Supabase project to talk to, from the site address.

        Drivers should not have to know what Supabase is, so the two
        values are read from the site's own config.js rather than typed.
        They are cached, so a later start does not depend on the site
        being up; `force` re-reads them, which is what to do when a
        sign-in is refused because the key has changed.
        """
        url = (self.cfg.get("url") or "").strip()
        key = (self.cfg.get("key") or "").strip()
        if url and key and not force:
            return
        site = (self.cfg.get("site") or "").strip()
        if not site:
            raise CloudError("Type the address of your SectorLoom site first.")
        found = discover(site)
        if found["url"] != url or found["key"] != key:
            self.log(f"Read the connection settings from {found['site']}/config.js")
        self.cfg["url"], self.cfg["key"] = found["url"], found["key"]
        self.cfg["site"] = found["site"]
        save_config(self.cfg)

    def connect(self, password: Optional[str] = None) -> None:
        """Sign in, with the stored refresh token unless a password is given."""
        self.resolve_project()
        url = (self.cfg.get("url") or "").strip()
        key = (self.cfg.get("key") or "").strip()
        if not url or not key:
            raise CloudError("Could not work out which project to connect to.")
        cloud = Cloud(url, key)
        if password:
            try:
                cloud.sign_in(self.cfg.get("email", ""), password)
            except CloudError:
                # the project may have been moved or its key rotated; the
                # site always knows the current answer, so ask it once
                # before telling the driver their password is wrong
                self.resolve_project(force=True)
                cloud = Cloud(self.cfg["url"], self.cfg["key"])
                cloud.sign_in(self.cfg.get("email", ""), password)
        else:
            token = self.cfg.get("refresh_token")
            if not token:
                raise AuthExpired("Sign in to get started.")
            cloud.sign_in_with_refresh(token)

        self.cloud = cloud
        self.save()
        self.watcher = Watcher(self.cfg, cloud, self.log, self.set_state, self.save)
        who = ""
        try:
            who = cloud.display_name()
        except CloudError:
            pass
        self.log(f"Signed in as {who or cloud.email}.")
        for missing in self.watcher.missing_folders():
            self.log(f"Folder not found — nothing to watch for {missing}")
        self.wake.set()

    # ---- the loop -------------------------------------------------------
    def scan_now(self) -> None:
        self.wake.set()

    def loop(self) -> None:
        while not self.stop.is_set():
            interval = max(POLL_FLOOR, int(self.cfg.get("scan_seconds") or 20))
            self.wake.wait(timeout=interval)
            self.wake.clear()
            if self.stop.is_set():
                break
            if self.paused or not self.watcher:
                continue
            try:
                self.watcher.scan_once()
                c = self.watcher.counts
                self.set_state(
                    f"Watching · {c['uploaded']} uploaded"
                    + (f", {c['failed']} failed" if c["failed"] else ""))
            except AuthExpired as e:
                self.log(f"Signed out: {e} Open the window and sign in again.")
                self.set_state("Signed out")
                self.watcher = None
                if self.window:
                    self.window.show()
                    self.window.set_status("Your sign-in expired. Enter your password again.", "#b00")
            except Exception as e:
                self.log(f"Scan problem: {e}")
                self.set_state("Problem — see Activity")

    # ---- tray -----------------------------------------------------------
    def start_tray(self) -> None:
        try:
            import pystray
            from PIL import Image, ImageDraw
        except Exception as e:
            self.log(f"No tray icon available ({e}). The window still works.")
            return

        def icon_image():
            """A wheel in the site's colours. Kept to big flat shapes
            because a tray icon is often drawn at sixteen pixels."""
            GOLD, BLUE, RED, WHITE = ((217, 165, 40, 255), (11, 87, 196, 255),
                                      (226, 20, 27, 255), (255, 255, 255, 255))
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse((0, 0, 63, 63), fill=GOLD)
            d.ellipse((5, 5, 58, 58), fill=BLUE)
            d.ellipse((21, 21, 42, 42), fill=WHITE)
            d.rectangle((29, 3, 34, 21), fill=RED)      # the valve stem
            return img

        def toggle_pause(_icon=None, _item=None):
            self.paused = not self.paused
            self.set_state("Paused" if self.paused else "Watching")
            self.log("Paused." if self.paused else "Resumed.")

        menu = pystray.Menu(
            pystray.MenuItem("Open", lambda *_: self.window and self.window.show(), default=True),
            pystray.MenuItem("Check now", lambda *_: self.scan_now()),
            pystray.MenuItem(lambda item: "Resume" if self.paused else "Pause", toggle_pause),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda *_: self.quit()),
        )
        self.tray = pystray.Icon("sectorloom", icon_image(), f"{APP_NAME}", menu)
        threading.Thread(target=self._run_tray, daemon=True).start()

    def _run_tray(self) -> None:
        try:
            self.tray.run()
        except Exception as e:
            self.log(f"Tray icon stopped ({e}). The window still works.")
            self.tray = None

    # ---- lifecycle ------------------------------------------------------
    def quit(self) -> None:
        self.stop.set()
        self.wake.set()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        if self.window:
            try:
                self.window.root.quit()
                self.window.root.destroy()
            except Exception:
                pass

    def run_windowed(self) -> None:
        from .gui import AgentWindow

        def on_sign_in(email: str, password: str) -> None:
            self.cfg["email"] = email
            self.connect(password)

        def on_retry() -> None:
            if not self.watcher:
                return
            n = self.watcher.retry_failed()
            self.log(f"Will try {n} failed file{'s' if n != 1 else ''} again."
                     if n else "No failed files to retry.")
            self.scan_now()

        self.window = AgentWindow(self.cfg, self.save, on_sign_in,
                                  self.scan_now, self.quit, on_retry)
        for line in self.lines:
            self.window.log(line)

        threading.Thread(target=self.loop, daemon=True).start()
        self.start_tray()

        try:
            self.connect()
            self.window.set_status(f"Signed in as {self.cfg.get('email','')}.", "#070")
            self.window.hide()          # straight to the tray when already set up
            self.set_state("Watching")
        except (CloudError, AuthExpired) as e:
            self.window.set_status(str(e), "#b00")
            self.set_state("Not signed in")
            self.window.show()

        self.window.root.mainloop()

    def run_headless(self) -> None:
        self.connect()
        self.set_state("Watching")
        self.log("Running without a window. Press Ctrl+C to stop.")
        try:
            self.loop()
        except KeyboardInterrupt:
            self.quit()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sectorloom-agent", add_help=True)
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    parser.add_argument("--no-gui", action="store_true", help="run in the console")
    parser.add_argument("--probe", metavar="FILE", help="describe an LMU telemetry file")
    parser.add_argument("--where", action="store_true", help="show the folders watched")
    args = parser.parse_args(argv)

    if args.probe:
        from .lmu import LmuError, probe
        try:
            print(probe(args.probe))
        except LmuError as e:
            print(f"Cannot read that file: {e}")
            return 2
        except OSError as e:
            print(f"Cannot open that file: {e}")
            return 2
        return 0

    agent = Agent()

    if args.where:
        d = default_dirs()
        print("Settings file :", os.path.join(
            os.environ.get("APPDATA") or os.path.expanduser("~/.config"), "SectorLoom", "agent.json"))
        for sim in ("iracing", "lmu"):
            folder = agent.cfg.get(f"{sim}_dir") or d[sim]
            print(f"{sim:<14}: {folder}  {'(found)' if os.path.isdir(folder) else '(not found)'}")
        return 0

    if args.once:
        try:
            agent.connect()
        except (CloudError, AuthExpired) as e:
            print(f"Cannot run: {e}")
            return 2
        assert agent.watcher
        agent.watcher.scan_once()
        c = agent.watcher.counts
        print(f"Done. uploaded {c['uploaded']}, skipped {c['skipped']}, failed {c['failed']}.")
        return 0 if not c["failed"] else 1

    if args.no_gui:
        try:
            agent.run_headless()
        except (CloudError, AuthExpired) as e:
            print(f"Cannot run: {e}")
            return 2
        return 0

    agent.run_windowed()
    return 0


if __name__ == "__main__":
    sys.exit(main())
