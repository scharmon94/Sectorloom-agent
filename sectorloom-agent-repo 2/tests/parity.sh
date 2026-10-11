#!/bin/sh
# Hand the same synthetic .ibt to the browser's parser and the agent's, and
# diff the answers. The browser's functions are lifted verbatim out of the
# working site file, so this catches the web app changing underneath us.
set -e
SITE=${1:-/home/claude/lapwise/site.html}
OUT=${TMPDIR:-/tmp}
cd "$(dirname "$0")/.."
python3 tests/make_ibt.py "$OUT/synthetic.ibt"
python3 tests/extract_js_parser.py "$SITE" tests/js_parser.mjs
node tests/js_summary.mjs "$OUT/synthetic.ibt" > "$OUT/js.json"
python3 tests/py_summary.py "$OUT/synthetic.ibt" > "$OUT/py.json"
python3 tests/compare.py
