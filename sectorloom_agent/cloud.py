"""
Talking to Supabase.

Only the standard library is used, so the packaged .exe stays small and
there is one less thing to go wrong on someone else's machine.

The agent signs in as an ordinary SectorLoom user. It holds a refresh token,
never the password, and it can only ever touch that account's own rows —
the database's security rules see to that, not this code.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

TIMEOUT = 60
BUCKET = "telemetry"


class CloudError(Exception):
    """Something the user may need to act on. The message is shown."""


class AuthExpired(CloudError):
    """The stored session is no longer good; they must sign in again."""


def _request(method: str, url: str, headers: Dict[str, str],
             body: Optional[bytes] = None) -> Any:
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            if not raw:
                return None
            ctype = resp.headers.get("Content-Type", "")
            return json.loads(raw) if "json" in ctype else raw
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            payload = json.loads(e.read() or b"{}")
            detail = (payload.get("message") or payload.get("msg")
                      or payload.get("error_description") or payload.get("error") or "")
        except Exception:
            pass
        if e.code in (401, 403):
            raise AuthExpired(detail or "Your sign-in is no longer valid.")
        raise CloudError(f"{e.code} {e.reason}{': ' + detail if detail else ''}")
    except urllib.error.URLError as e:
        raise CloudError(f"Could not reach the server ({e.reason}).")


class Cloud:
    def __init__(self, url: str, key: str):
        self.url = _clean_url(url)
        self.key = key.strip()
        self.token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.uid: Optional[str] = None
        self.email: str = ""
        self.expires_at: float = 0.0

    # ---- authentication -------------------------------------------------
    def _store(self, data: Dict[str, Any]) -> None:
        self.token = data.get("access_token")
        self.refresh_token = data.get("refresh_token")
        self.expires_at = time.time() + float(data.get("expires_in") or 3600)
        user = data.get("user") or {}
        self.uid = user.get("id")
        self.email = user.get("email") or self.email
        if not self.token or not self.uid:
            raise CloudError("The server did not return a usable session.")

    def sign_in(self, email: str, password: str) -> None:
        body = json.dumps({"email": email.strip(), "password": password}).encode()
        data = _request("POST", f"{self.url}/auth/v1/token?grant_type=password",
                        {"apikey": self.key, "Content-Type": "application/json"}, body)
        self._store(data)

    def sign_in_with_refresh(self, refresh_token: str) -> None:
        body = json.dumps({"refresh_token": refresh_token}).encode()
        data = _request("POST", f"{self.url}/auth/v1/token?grant_type=refresh_token",
                        {"apikey": self.key, "Content-Type": "application/json"}, body)
        self._store(data)

    def _fresh(self) -> None:
        """Renew a minute before expiry so a long upload cannot fall off."""
        if not self.token:
            raise AuthExpired("Not signed in.")
        if time.time() > self.expires_at - 60 and self.refresh_token:
            self.sign_in_with_refresh(self.refresh_token)

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        h = {"apikey": self.key, "Authorization": f"Bearer {self.token}"}
        if extra:
            h.update(extra)
        return h

    # ---- what is already up there ---------------------------------------
    def existing_session_ids(self) -> List[str]:
        self._fresh()
        rows = _request("GET", f"{self.url}/rest/v1/telemetry_sessions?select=id",
                        self._headers({"Accept": "application/json"})) or []
        return [r["id"] for r in rows if isinstance(r, dict) and "id" in r]

    def display_name(self) -> str:
        self._fresh()
        rows = _request(
            "GET",
            f"{self.url}/rest/v1/profiles?select=display_name&id=eq.{self.uid}",
            self._headers({"Accept": "application/json"})) or []
        return rows[0].get("display_name", "") if rows else ""

    # ---- putting a session up -------------------------------------------
    def upload_session(self, session: Dict[str, Any], encoded: str) -> None:
        """Storage first, then the row — so a row never points at nothing."""
        self._fresh()
        sid = session["id"]
        path = f"{self.uid}/{sid}.json"
        payload = encoded.encode("utf-8")

        _request("POST", f"{self.url}/storage/v1/object/{BUCKET}/{urllib.parse.quote(path)}",
                 self._headers({"Content-Type": "application/json", "x-upsert": "true"}),
                 payload)

        clean = [l for l in session["laps"] if l.get("clean")]
        row = {
            "id": sid,
            "user_id": self.uid,
            "file": session.get("file") or "",
            "recorded_at": session.get("date"),
            "track_key": session.get("trackKey") or "",
            "track_name": (session.get("track") or {}).get("name") or "",
            "track_config": (session.get("track") or {}).get("config") or "",
            "car_name": (session.get("car") or {}).get("name") or "",
            "lap_count": len(clean),
            "best_lap": min((l["time"] for l in clean), default=None),
            "bytes": len(payload),
            "storage_path": path,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _request("POST", f"{self.url}/rest/v1/telemetry_sessions",
                 self._headers({"Content-Type": "application/json",
                                "Prefer": "resolution=merge-duplicates,return=minimal"}),
                 json.dumps(row).encode())


# --------------------------------------------------------------------------
#  Finding the project settings from the site itself
#
#  A driver should not have to know what Supabase is. The site already
#  publishes the two values the agent needs, in config.js, which is public
#  by design — the anon key is meant to sit in every visitor's browser.
#  So the agent asks for the site address and reads the rest from there.
#
#  config.js is a file Shawn edits by hand and will keep adding to (Stripe
#  links, support address, and whatever comes next), so the parsing here
#  has one rule: find the two keys it needs and be completely indifferent
#  to everything else in the file.
# --------------------------------------------------------------------------
def _strip_js_comments(src: str) -> str:
    """Blank out /* */ and // comments, leaving string literals alone.

    Needed because config.js is mostly comments explaining each setting,
    and a commented-out example assignment would otherwise be read as the
    real one. Characters are replaced with spaces rather than deleted so
    that nothing shifts position.
    """
    out = list(src)
    i, n = 0, len(src)
    quote = None
    while i < n:
        c = src[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'`":
            quote = c
            i += 1
            continue
        if c == "/" and i + 1 < n:
            if src[i + 1] == "/":
                while i < n and src[i] != "\n":
                    out[i] = " "
                    i += 1
                continue
            if src[i + 1] == "*":
                end = src.find("*/", i + 2)
                end = n if end < 0 else end + 2
                for j in range(i, end):
                    if out[j] != "\n":
                        out[j] = " "
                i = end
                continue
        i += 1
    return "".join(out)


_PLACEHOLDERS = ("", "YOUR_SUPABASE_URL", "YOUR_ANON_KEY", "PASTE_", "xxxxx",
                 "https://xxxxx.supabase.co", "your-project")


def _find_setting(src: str, name: str) -> str:
    """Pull one "NAME": "value" out of a config.js, whatever else is in it."""
    import re
    pattern = re.compile(
        r"""['"]?\b%s\b['"]?\s*:\s*(['"])(.*?)\1""" % re.escape(name),
        re.DOTALL)
    found = [m.group(2).strip() for m in pattern.finditer(src)]
    found = [v for v in found if v and not any(
        p and p.lower() in v.lower() for p in _PLACEHOLDERS if p)]
    return found[-1] if found else ""


def discover(site: str) -> Dict[str, str]:
    """Read SUPABASE_URL and SUPABASE_ANON_KEY out of a site's config.js.

    Raises CloudError with something the person can act on. Never raises
    anything else, so a caller can offer the manual boxes instead.
    """
    s = (site or "").strip().strip('"').strip("'")
    if not s:
        raise CloudError("Type the address of your SectorLoom site first.")
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    parts = urllib.parse.urlsplit(s)
    if not parts.netloc:
        raise CloudError("That is not a valid web address.")
    # tolerate someone pasting the full page address, or the config itself
    path = parts.path.rsplit("/", 1)[0] if "." in parts.path.rsplit("/", 1)[-1] else parts.path
    base = f"{parts.scheme}://{parts.netloc}{path}".rstrip("/")
    target = base + "/config.js"

    try:
        req = urllib.request.Request(target, method="GET")
        req.add_header("Accept", "application/javascript, text/plain, */*")
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read(512 * 1024)
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except urllib.error.HTTPError as e:
        raise CloudError(f"{target} answered {e.code}. Check the site address.")
    except Exception as e:
        raise CloudError(f"Could not reach {target} ({e}). Check the address "
                         "and your connection.")

    text = raw.decode("utf-8", "replace")
    if "html" in ctype or text.lstrip()[:15].lower().startswith("<!doctype"):
        raise CloudError(f"{target} gave back a web page rather than the "
                         "settings file. The site may not have config.js on it.")

    clean = _strip_js_comments(text)
    url = _find_setting(clean, "SUPABASE_URL")
    key = (_find_setting(clean, "SUPABASE_ANON_KEY")
           or _find_setting(clean, "SUPABASE_KEY"))
    if not url or not key:
        missing = " and ".join(
            n for n, v in (("the project URL", url), ("the public key", key)) if not v)
        raise CloudError(f"Found {target} but could not read {missing} from it.")
    # Deliberately no "must contain supabase" check here: a self-hosted
    # Supabase is a legitimate thing to point at. _clean_url still catches
    # the common mistake of giving the dashboard address, and a wrong
    # project announces itself clearly at sign-in anyway.
    return {"url": _clean_url(url), "key": key, "site": base}


def _clean_url(raw: str) -> str:
    """Tolerate a trailing slash or a stray /rest/v1, same as the web app."""
    u = (raw or "").strip().strip('"').strip("'")
    if not u:
        raise CloudError("No project URL was given.")
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    parts = urllib.parse.urlsplit(u)
    # urlsplit is happy to call "not a url at all" a host, so check that
    # what came back could actually be one
    if not parts.netloc or any(ch.isspace() for ch in parts.netloc):
        raise CloudError(f"That project URL is not a valid web address: {raw}")
    if parts.netloc.lower().endswith("supabase.com"):
        raise CloudError("That is the Supabase dashboard address. You want the "
                         "Project URL from Settings → API, ending in .supabase.co")
    return f"{parts.scheme}://{parts.netloc}"


# --------------------------------------------------------------------------
#  Settings on disk
# --------------------------------------------------------------------------
def config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    path = os.path.join(base, "SectorLoom")
    os.makedirs(path, exist_ok=True)
    return path


def _old_config_file() -> str:
    """Where the settings lived when this was called Lapwise."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    return os.path.join(base, "Lapwise", "agent.json")


def config_file() -> str:
    """SECTORLOOM_AGENT_CONFIG overrides the location — used by the tests, and
    handy if you want the settings to live beside a portable copy.

    On the first run after the rename the settings are carried over from
    the old folder, so nobody has to sign in again. The old file is left
    where it is: copying is reversible, moving is not."""
    override = os.environ.get("SECTORLOOM_AGENT_CONFIG")
    if override:
        os.makedirs(os.path.dirname(os.path.abspath(override)), exist_ok=True)
        return override
    new = os.path.join(config_dir(), "agent.json")
    if not os.path.exists(new):
        old = _old_config_file()
        if os.path.exists(old):
            try:
                with open(old, "r", encoding="utf-8") as fh:
                    carried = fh.read()
                with open(new, "w", encoding="utf-8") as fh:
                    fh.write(carried)
            except OSError:
                pass                      # a fresh sign-in is the fallback
    return new


DEFAULTS: Dict[str, Any] = {
    "site": "https://sectorloom.com",   # what the driver types
    "url": "",                          # both of these are read from the
    "key": "",                          # site's config.js, never typed
    "email": "",
    "refresh_token": "",
    "watch_iracing": True,
    "watch_lmu": True,
    "iracing_dir": "",
    "lmu_dir": "",
    "scan_seconds": 20,
    "start_with_windows": False,
    "uploaded": [],          # session ids already dealt with
}


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    try:
        with open(config_file(), encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except FileNotFoundError:
        pass
    except Exception:
        pass  # a corrupt file should not stop the agent starting
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    tmp = config_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=1)
    os.replace(tmp, config_file())
