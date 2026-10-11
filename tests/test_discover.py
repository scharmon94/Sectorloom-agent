"""
Reading the project settings out of a site's config.js.

The point of these: config.js is a file Shawn edits by hand and keeps
adding to — Stripe links went in after the agent was written, and more
will follow. The agent must find the two values it needs and be entirely
indifferent to everything else in the file, including comments that talk
*about* those values.

Run:  python3 tests/test_discover.py
"""
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sectorloom_agent.cloud import CloudError, discover, _find_setting, _strip_js_comments  # noqa: E402

PASS, FAIL = [], []
URL = "https://abcdefghijklm.supabase.co"
KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test.signature"


def check(label, got, want):
    if got == want:
        PASS.append(label); print(f"  ok    {label}")
    else:
        FAIL.append(label); print(f"  FAIL  {label}\n          got  {got!r}\n          want {want!r}")


def check_raises(label, fn, fragment):
    try:
        fn()
    except CloudError as e:
        if fragment.lower() in str(e).lower():
            PASS.append(label); print(f"  ok    {label}")
        else:
            FAIL.append(label); print(f"  FAIL  {label}: wrong message {str(e)!r}")
    except Exception as e:
        FAIL.append(label); print(f"  FAIL  {label}: raised {type(e).__name__} {e}")
    else:
        FAIL.append(label); print(f"  FAIL  {label}: did not raise")


# --------------------------------------------------------------- the parser
print("\n1. the shape config.js is in today")
TODAY = '''/* SectorLoom configuration.
   SUPABASE_URL: paste your project URL here, from Settings -> API.
   NEVER put the Secret key (sb_secret_...) in this file. */
window.SECTORLOOM_CONFIG = {
  SUPABASE_URL: "%s",
  SUPABASE_ANON_KEY: "%s",
  SITE_NAME: "SectorLoom",
  ALLOW_SIGNUP: true,
};''' % (URL, KEY)
c = _strip_js_comments(TODAY)
check("url from a normal file", _find_setting(c, "SUPABASE_URL"), URL)
check("key from a normal file", _find_setting(c, "SUPABASE_ANON_KEY"), KEY)

print("\n2. a comment that names the keys is not mistaken for the setting")
# this is the real trap: the file explains each setting above it
TRAP = '''/* ---- Supabase -----------------------------------
   SUPABASE_URL: "https://PASTE-YOURS-HERE.supabase.co"
   SUPABASE_ANON_KEY: "PASTE_YOUR_ANON_KEY"
   Both come from Settings -> API.                   */
window.SECTORLOOM_CONFIG = {
  // SUPABASE_URL: "https://old-dead-project.supabase.co",
  SUPABASE_URL: "%s",
  SUPABASE_ANON_KEY: "%s",
};''' % (URL, KEY)
c = _strip_js_comments(TRAP)
check("block comment ignored", _find_setting(c, "SUPABASE_URL"), URL)
check("commented-out old value ignored", "old-dead-project" in _find_setting(c, "SUPABASE_URL"), False)
check("key still found", _find_setting(c, "SUPABASE_ANON_KEY"), KEY)

print("\n3. Stripe and the rest added later change nothing")
LATER = '''window.SECTORLOOM_CONFIG = {
  SITE_NAME: "SectorLoom",
  TAGLINE: "Sim racing telemetry, teams and coaching",
  SUPABASE_URL: "%s",
  SUPABASE_ANON_KEY: "%s",
  /* ---- Stripe ---- */
  PAY_LINK_MONTHLY: "https://buy.stripe.com/test_aEU00",
  PAY_LINK_YEARLY:  "https://buy.stripe.com/test_bFG11",
  PRICE_MONTHLY: "$6",
  PRICE_YEARLY: "$60",
  SUPPORT_EMAIL: "help@sectorloom.com",
  AGENT_DOWNLOAD: "https://downloads.sectorloom.com/SectorLoomSetup.exe",
  STRIPE_PUBLISHABLE_KEY: "pk_live_notasecret",
  ALLOW_SIGNUP: true,
  SHOW_LANDING: true,
};''' % (URL, KEY)
c = _strip_js_comments(LATER)
check("url found among new settings", _find_setting(c, "SUPABASE_URL"), URL)
check("key found among new settings", _find_setting(c, "SUPABASE_ANON_KEY"), KEY)
check("a Stripe key is not mistaken for the anon key",
      _find_setting(c, "SUPABASE_ANON_KEY").startswith("pk_"), False)

print("\n4. formatting the agent must not care about")
VARIANTS = {
    "single quotes":      "{SUPABASE_URL:'%s',SUPABASE_ANON_KEY:'%s'}" % (URL, KEY),
    "quoted key names":   '{"SUPABASE_URL": "%s", "SUPABASE_ANON_KEY": "%s"}' % (URL, KEY),
    "minified":           'window.SECTORLOOM_CONFIG={SUPABASE_URL:"%s",SUPABASE_ANON_KEY:"%s",X:1}' % (URL, KEY),
    "odd whitespace":     '{\n  SUPABASE_URL   :    "%s"  ,\n\tSUPABASE_ANON_KEY\t:\t"%s"\n}' % (URL, KEY),
    "reordered":          '{SUPABASE_ANON_KEY: "%s", SUPABASE_URL: "%s"}' % (KEY, URL),
    "legacy window name": 'window.LAPWISE_CONFIG = {SUPABASE_URL:"%s",SUPABASE_ANON_KEY:"%s"};' % (URL, KEY),
}
for label, src in VARIANTS.items():
    c = _strip_js_comments(src)
    check(label, (_find_setting(c, "SUPABASE_URL"), _find_setting(c, "SUPABASE_ANON_KEY")), (URL, KEY))

print("\n5. a key named the older way")
c = _strip_js_comments('{SUPABASE_URL:"%s", SUPABASE_KEY:"%s"}' % (URL, KEY))
check("SUPABASE_KEY accepted as a fallback",
      _find_setting(c, "SUPABASE_ANON_KEY") or _find_setting(c, "SUPABASE_KEY"), KEY)

print("\n6. placeholders are treated as not filled in")
c = _strip_js_comments('{SUPABASE_URL:"", SUPABASE_ANON_KEY:"PASTE_YOUR_ANON_KEY"}')
check("empty url rejected", _find_setting(c, "SUPABASE_URL"), "")
check("placeholder key rejected", _find_setting(c, "SUPABASE_ANON_KEY"), "")

print("\n7. a url with // in it survives the comment stripper")
c = _strip_js_comments('{SUPABASE_URL:"%s", NOTE:"see https://example.com/x"}' % URL)
check("url inside a string kept", _find_setting(c, "SUPABASE_URL"), URL)


# ------------------------------------------------------------- over the wire
class Serve(BaseHTTPRequestHandler):
    body = TODAY
    ctype = "application/javascript"
    code = 200
    seen_agent = None

    def do_GET(self):
        Serve.seen_agent = self.headers.get("User-Agent")
        if self.path != "/config.js":
            self.send_response(404); self.end_headers(); self.wfile.write(b"no"); return
        payload = Serve.body.encode()
        self.send_response(Serve.code)
        self.send_header("Content-Type", Serve.ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), Serve)
threading.Thread(target=srv.serve_forever, daemon=True).start()
site = f"http://127.0.0.1:{srv.server_port}"

print("\n8. fetching it from a site")
got = discover(site)
check("url", got["url"], URL)
check("key", got["key"], KEY)
check("site remembered", got["site"], site)
# a bare domain must become https — proved by what the failure names,
# since a plain-http test server cannot answer an https request
try:
    discover("sectorloom.example")
except CloudError as e:
    check("a bare domain is treated as https", "https://sectorloom.example/config.js" in str(e), True)
check("works with a trailing slash", discover(site + "/")["url"], URL)
check("works if they paste the page address",
      discover(site + "/index.html")["url"], URL)

# The agent used to go out as "Python-urllib/3.x", which Cloudflare's bot
# protection turns away with a 403 — a browser could read config.js and
# the agent could not. It has to say who it is.
say_agent = Serve.seen_agent or ""
check("does not identify as urllib", "urllib" in say_agent.lower(), False)
check("identifies itself", say_agent.startswith("SectorLoomAgent/"), True)

print("\n9. what the driver is told when it does not work")
check_raises("nothing typed", lambda: discover(""), "type the address")
check_raises("no such site", lambda: discover("http://127.0.0.1:1/"), "could not reach")

Serve.code = 404
check_raises("site has no config.js", lambda: discover(site), "answered 404")

Serve.code = 403
check_raises("turned away by bot protection", lambda: discover(site), "refused the agent")
check_raises("and says where to look", lambda: discover(site), "cloudflare")

Serve.code = 200
Serve.ctype = "text/html"
Serve.body = "<!doctype html><html><body>not found</body></html>"
check_raises("host serves the app instead", lambda: discover(site), "web page")

Serve.ctype = "application/javascript"
Serve.body = '{SITE_NAME:"SectorLoom"}'
check_raises("config with neither value", lambda: discover(site), "could not read")

Serve.body = '{SUPABASE_URL:"%s"}' % URL
check_raises("config missing only the key", lambda: discover(site), "public key")

# A self-hosted Supabase is a real thing, so the project URL is not
# required to say "supabase" anywhere. Only a genuinely unusable address
# is refused.
Serve.body = '{SUPABASE_URL:"https://supabase.mysimteam.org", SUPABASE_ANON_KEY:"%s"}' % KEY
check("a self-hosted project is accepted",
      discover(site)["url"], "https://supabase.mysimteam.org")

Serve.body = '{SUPABASE_URL:"not a url at all", SUPABASE_ANON_KEY:"%s"}' % KEY
check_raises("unusable project url", lambda: discover(site), "not a valid web address")

Serve.body = '{SUPABASE_URL:"https://app.supabase.com", SUPABASE_ANON_KEY:"%s"}' % KEY
check_raises("the dashboard address is caught", lambda: discover(site), "dashboard")

srv.shutdown()
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
