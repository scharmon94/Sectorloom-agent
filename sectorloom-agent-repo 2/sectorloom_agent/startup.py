"""Start-with-Windows, via the per-user Run key. No admin rights needed."""
from __future__ import annotations

import os
import sys
from typing import Tuple

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "SectorLoomTelemetryAgent"
OLD_VALUE_NAME = "LapwiseTelemetryAgent"    # before the rename


def _command() -> str:
    if getattr(sys, "frozen", False):          # packaged .exe
        return f'"{sys.executable}"'
    script = os.path.abspath(sys.argv[0])
    return f'"{sys.executable}" "{script}"'


def set_start_with_windows(enabled: bool) -> Tuple[bool, str]:
    if sys.platform != "win32":
        return (False, "only available on Windows")
    try:
        import winreg
    except ImportError:
        return (False, "the Windows registry is not reachable")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            # whichever way this goes, the entry under the old name has to
            # come out, or an upgraded machine starts the agent twice
            try:
                winreg.DeleteValue(key, OLD_VALUE_NAME)
            except FileNotFoundError:
                pass
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return (True, "")
    except OSError as e:
        return (False, str(e))


def is_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            for name in (VALUE_NAME, OLD_VALUE_NAME):
                try:
                    winreg.QueryValueEx(key, name)
                    return True
                except FileNotFoundError:
                    continue
        return False
    except Exception:
        return False
