"""
Runs the agent against a stand-in Supabase and a real folder of files.

Covers the things that actually go wrong in the field: a file still being
written, the same file seen twice, a corrupt file, the upload failing and
being retried, the sign-in expiring, and a restart picking up where it
left off.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fake_supabase  # noqa: E402
from sectorloom_agent import cloud as cloud_mod  # noqa: E402

PASS, FAIL = [], []


def check(label, got, want):
    if got == want:
        PASS.append(label)
        print(f"  ok    {label}")
    else:
        FAIL.append(label)
        print(f"  FAIL  {label}: got {got!r}, wanted {want!r}")


def check_true(label, got):
    check(label, bool(got), True)


HERE = os.path.dirname(os.path.abspath(__file__))


def fixtures(work):
    """An .ibt and an LMU database, made here rather than found on disk.

    These used to be read from a scratch directory that only existed on
    the machine they were first built on, which meant the suite could
    not run anywhere else — including on the Windows runner that builds
    the installer, where it matters most.
    """
    ibt = os.path.join(work, "synthetic.ibt")
    lmu = os.path.join(work, "lmu.duckdb")
    env = dict(os.environ, IBT_LAPS="9")
    subprocess.run([sys.executable, os.path.join(HERE, "make_ibt.py"), ibt],
                   check=True, env=env, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, os.path.join(HERE, "make_lmu.py"), lmu],
                   check=True, stdout=subprocess.DEVNULL)
    return ibt, lmu


def main():
    work = tempfile.mkdtemp(prefix="sectorloom-e2e-")
    watch_ir = os.path.join(work, "iRacing", "telemetry")
    watch_lmu = os.path.join(work, "LMU", "Telemetry")
    os.makedirs(watch_ir); os.makedirs(watch_lmu)
    IBT, LMU = fixtures(work)

    server, url = fake_supabase.start()
    cfg_path = os.path.join(work, "agent.json")
    os.environ["SECTORLOOM_AGENT_CONFIG"] = cfg_path

    base = {
        "url": url, "key": "sb_publishable_test",
        "email": fake_supabase.STATE["email"], "refresh_token": "",
        "watch_iracing": True, "watch_lmu": True,
        "iracing_dir": watch_ir, "lmu_dir": watch_lmu,
        "scan_seconds": 5,
    }
    json.dump(base, open(cfg_path, "w"))

    # reload so the module picks up the new config path
    for mod in [m for m in list(sys.modules) if m.startswith("sectorloom_agent")]:
        del sys.modules[mod]
    from sectorloom_agent.app import Agent  # noqa: E402

    print("\n1. sign in with a password")
    agent = Agent()
    agent.connect(password=fake_supabase.STATE["password"])
    check_true("signed in", agent.cloud and agent.cloud.uid == fake_supabase.STATE["uid"])
    check_true("refresh token stored", json.load(open(cfg_path)).get("refresh_token"))

    print("\n2. a file still being written is left alone")
    shutil.copy(IBT, os.path.join(watch_ir, "fresh.ibt"))
    agent.watcher.scan_once()
    check("nothing uploaded yet", len(fake_supabase.STATE["rows"]), 0)

    print("\n3. once it settles, it goes up")
    old = time.time() - 600
    for f in os.listdir(watch_ir):
        os.utime(os.path.join(watch_ir, f), (old, old))
    shutil.copy(LMU, os.path.join(watch_lmu, "race.duckdb"))
    os.utime(os.path.join(watch_lmu, "race.duckdb"), (old, old))
    agent.watcher.scan_once()
    check("two sessions uploaded", len(fake_supabase.STATE["rows"]), 2)
    check("two blobs stored", len(fake_supabase.STATE["objects"]), 2)
    check("counter agrees", agent.watcher.counts["uploaded"], 2)

    rows = list(fake_supabase.STATE["rows"].values())
    ir_row = next(r for r in rows if r["file"] == "fresh.ibt")
    lmu_row = next(r for r in rows if r["file"] == "race.duckdb")
    check("iRacing track recorded", ir_row["track_name"], "Synthetic Park")
    check("iRacing clean laps", ir_row["lap_count"], 4)
    check_true("iRacing best lap sane", 73 < ir_row["best_lap"] < 74)
    check("LMU track recorded", lmu_row["track_name"], "Circuit de la Sarthe")
    check("LMU clean laps", lmu_row["lap_count"], 5)
    check_true("blob stored under the user's own folder",
               all(k.startswith(fake_supabase.STATE["uid"] + "/")
                   for k in fake_supabase.STATE["objects"]))

    print("\n4. the stored blob is what the website expects")
    blob = list(fake_supabase.STATE["objects"].values())[0]
    parsed = json.loads(blob)
    check("schema version", parsed["v"], 2)
    check_true("laps present", isinstance(parsed["laps"], list) and parsed["laps"])
    grid = next(l["g"] for l in parsed["laps"] if l.get("g"))
    check_true("channels encoded as $f32", isinstance(grid["t"], dict) and "$f32" in grid["t"])

    print("\n5. scanning again changes nothing")
    before = len(fake_supabase.STATE["rows"])
    agent.watcher.scan_once()
    check("no duplicates", len(fake_supabase.STATE["rows"]), before)
    check("upload counter unchanged", agent.watcher.counts["uploaded"], 2)

    print("\n6. a corrupt file is reported, not fatal")
    bad = os.path.join(watch_ir, "corrupt.ibt")
    open(bad, "wb").write(b"this is not telemetry" * 50)
    os.utime(bad, (old, old))
    agent.watcher.scan_once()
    check("corrupt file counted as failed", agent.watcher.counts["failed"], 1)
    check("still only two sessions", len(fake_supabase.STATE["rows"]), 2)
    check_true("agent still usable", agent.watcher is not None)

    print("\n7. an upload that fails is retried next pass")
    fake_supabase.STATE["fail_uploads"] = 1
    second = os.path.join(watch_ir, "another.ibt")
    shutil.copy(IBT, second)
    os.utime(second, (old, old))
    agent.watcher.scan_once()
    check("not uploaded on the failing pass", len(fake_supabase.STATE["rows"]), 2)
    agent.watcher.scan_once()
    check("uploaded on the retry", len(fake_supabase.STATE["rows"]), 3)

    print("\n8. a restart remembers what was done")
    agent.save()
    for mod in [m for m in list(sys.modules) if m.startswith("sectorloom_agent")]:
        del sys.modules[mod]
    from sectorloom_agent.app import Agent as Agent2
    again = Agent2()
    again.connect()                      # refresh token, no password
    check_true("signed in from the stored token", again.cloud and again.cloud.uid)
    again.watcher.scan_once()
    check("nothing re-uploaded after restart", again.watcher.counts["uploaded"], 0)
    check("still three sessions", len(fake_supabase.STATE["rows"]), 3)

    print("\n9. an expired sign-in is reported clearly")
    fake_supabase.STATE["reject_auth"] = True
    for mod in [m for m in list(sys.modules) if m.startswith("sectorloom_agent")]:
        del sys.modules[mod]
    from sectorloom_agent.app import Agent as Agent3
    from sectorloom_agent.cloud import AuthExpired, CloudError
    third = Agent3()
    try:
        third.connect()
        check("rejected sign-in raises", "no error", "an error")
    except (AuthExpired, CloudError) as e:
        check_true("rejected sign-in explained", "Invalid login credentials" in str(e))
    fake_supabase.STATE["reject_auth"] = False

    print("\n10. the project is found from the site address alone")
    # What a driver actually does: types the site, email and password.
    # The Supabase URL and key are read out of the site's own config.js.
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    class Site(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/config.js":
                self.send_response(404); self.end_headers(); return
            body = ('window.SECTORLOOM_CONFIG={\n'
                    '  /* SUPABASE_URL: "https://PASTE-YOURS.supabase.co" */\n'
                    '  SUPABASE_URL: "%s",\n'
                    '  SUPABASE_ANON_KEY: "sb_publishable_test",\n'
                    '  PAY_LINK_MONTHLY: "https://buy.stripe.com/x",\n'
                    '  SUPPORT_EMAIL: "help@example.com"\n};' % url).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def log_message(self, *a): pass

    site_srv = HTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=site_srv.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{site_srv.server_port}"

    fresh = os.path.join(work, "fresh.json")
    os.environ["SECTORLOOM_AGENT_CONFIG"] = fresh
    json.dump({"site": site, "email": fake_supabase.STATE["email"],
               "watch_iracing": False, "watch_lmu": False}, open(fresh, "w"))
    for mod in [m for m in list(sys.modules) if m.startswith("sectorloom_agent")]:
        del sys.modules[mod]
    from sectorloom_agent.app import Agent as Agent4
    blank = Agent4()
    check("starts with no project settings", bool(blank.cfg.get("url")), False)
    blank.connect(password=fake_supabase.STATE["password"])
    check_true("signed in knowing only the site", blank.cloud and blank.cloud.uid)
    check("found the project url", json.load(open(fresh))["url"], url)
    check("found the key", json.load(open(fresh))["key"], "sb_publishable_test")

    # and a bad site address says so rather than blaming the password.
    # The real sectorloom.com is deliberately kept out of this: the agent
    # falls back to it when a stored address fails, and a test that
    # depends on the live site would pass here and behave differently on
    # a build runner that can actually reach it.
    json.dump({"site": "http://127.0.0.1:1", "email": "x@example.com"}, open(fresh, "w"))
    for mod in [m for m in list(sys.modules) if m.startswith("sectorloom_agent")]:
        del sys.modules[mod]
    import sectorloom_agent.cloud as cloud5
    import sectorloom_agent.app as app5
    cloud5.DEFAULT_SITE = app5.DEFAULT_SITE = "http://127.0.0.1:2"
    from sectorloom_agent.cloud import CloudError as CE
    try:
        app5.Agent().connect(password="whatever")
        check("unreachable site explained", "no error", "an error")
    except CE as e:
        check_true("unreachable site explained", "could not reach" in str(e).lower())

    # a stored address that has gone stale falls back to the real one
    json.dump({"site": "http://127.0.0.1:1", "email": fake_supabase.STATE["email"],
               "watch_iracing": False, "watch_lmu": False}, open(fresh, "w"))
    for mod in [m for m in list(sys.modules) if m.startswith("sectorloom_agent")]:
        del sys.modules[mod]
    import sectorloom_agent.cloud as cloud6
    import sectorloom_agent.app as app6
    cloud6.DEFAULT_SITE = app6.DEFAULT_SITE = site
    recovered = app6.Agent()
    recovered.connect(password=fake_supabase.STATE["password"])
    check_true("a stale site address recovers on its own",
               recovered.cloud and recovered.cloud.uid)
    site_srv.shutdown()

    server.shutdown()
    shutil.rmtree(work, ignore_errors=True)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
