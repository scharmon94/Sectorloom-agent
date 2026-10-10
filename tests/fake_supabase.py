"""
A stand-in Supabase, enough of it to run the agent against for real:
password and refresh-token sign-in, the telemetry_sessions table, the
storage bucket, and the profiles row.

Started by test_end_to_end.py; also runnable on its own for poking at.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

STATE = {
    "password": "a-good-password",
    "email": "shawn@example.com",
    "uid": "11111111-2222-3333-4444-555555555555",
    "rows": {},        # session id -> row
    "objects": {},     # storage path -> bytes
    "refresh": "refresh-token-1",
    "fail_uploads": 0,   # make this many uploads fail, to test retries
    "reject_auth": False,
    "requests": [],
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):   # keep the test output clean
        pass

    # -- helpers --
    def _send(self, code: int, payload=None, ctype="application/json"):
        body = b"" if payload is None else (
            payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _authed(self) -> bool:
        return (self.headers.get("Authorization") or "").startswith("Bearer access-")

    # -- routes --
    def do_GET(self):
        path, _, query = self.path.partition("?")
        STATE["requests"].append(("GET", path))
        if path == "/rest/v1/telemetry_sessions":
            if not self._authed():
                return self._send(401, {"message": "no session"})
            return self._send(200, [{"id": k} for k in STATE["rows"]])
        if path == "/rest/v1/profiles":
            if not self._authed():
                return self._send(401, {"message": "no session"})
            return self._send(200, [{"display_name": "Shawn Harmon"}])
        return self._send(404, {"message": "not found"})

    def do_POST(self):
        path, _, query = self.path.partition("?")
        params = urllib.parse.parse_qs(query)
        body = self._body()
        STATE["requests"].append(("POST", path))

        if path == "/auth/v1/token":
            if STATE["reject_auth"]:
                return self._send(400, {"error_description": "Invalid login credentials"})
            data = json.loads(body or b"{}")
            grant = (params.get("grant_type") or [""])[0]
            if grant == "password":
                if (data.get("email") != STATE["email"]
                        or data.get("password") != STATE["password"]):
                    return self._send(400, {"error_description": "Invalid login credentials"})
            elif grant == "refresh_token":
                if data.get("refresh_token") != STATE["refresh"]:
                    return self._send(401, {"message": "Invalid Refresh Token"})
            else:
                return self._send(400, {"error_description": "unsupported grant"})
            return self._send(200, {
                "access_token": "access-abc", "refresh_token": STATE["refresh"],
                "expires_in": 3600,
                "user": {"id": STATE["uid"], "email": STATE["email"]},
            })

        if path == "/rest/v1/telemetry_sessions":
            if not self._authed():
                return self._send(401, {"message": "no session"})
            row = json.loads(body)
            if row.get("user_id") != STATE["uid"]:
                return self._send(403, {"message": "row level security"})
            STATE["rows"][row["id"]] = row
            return self._send(201, None)

        m = re.match(r"^/storage/v1/object/telemetry/(.+)$", path)
        if m:
            if not self._authed():
                return self._send(401, {"message": "no session"})
            if STATE["fail_uploads"] > 0:
                STATE["fail_uploads"] -= 1
                return self._send(500, {"message": "storage hiccup"})
            key = urllib.parse.unquote(m.group(1))
            if not key.startswith(STATE["uid"] + "/"):
                return self._send(403, {"message": "not your folder"})
            STATE["objects"][key] = body
            return self._send(200, {"Key": key})

        return self._send(404, {"message": "not found"})


def start() -> tuple:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


if __name__ == "__main__":
    s, url = start()
    print("fake supabase on", url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        s.shutdown()
