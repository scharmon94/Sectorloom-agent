"""
Lifts the parsing functions out of the shipped index.html into a plain ES
module, so the browser's parser can be run head-to-head against the
Python one on the same bytes. Nothing is rewritten — the function bodies
are copied verbatim.
"""
import re
import sys

NEEDED = ["cstr", "parseIBT", "parseSetup", "readInfo", "liveCond",
          "hash", "tyreReads", "buildSession", "stintStats", "makeGrid"]


def grab(src: str, name: str) -> str:
    m = re.search(r"^function " + re.escape(name) + r"\s*\(", src, re.M)
    if not m:
        raise SystemExit(f"could not find function {name}")
    i = src.index("{", m.end() - 1)
    depth, j = 0, i
    in_str = None
    while j < len(src):
        c = src[j]
        if in_str:
            if c == "\\":
                j += 2
                continue
            if c == in_str:
                in_str = None
        # comments first: an apostrophe inside one (a car's own speed)
        # used to look like the start of a string and swallow the rest of
        # the function, which showed up as "unbalanced braces"
        elif c == "/" and j + 1 < len(src) and src[j + 1] == "/":
            j = src.find("\n", j)
            if j < 0:
                break
            continue
        elif c == "/" and j + 1 < len(src) and src[j + 1] == "*":
            end = src.find("*/", j + 2)
            if end < 0:
                break
            j = end + 2
            continue
        elif c in "\"'`":
            in_str = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
        j += 1
    raise SystemExit(f"unbalanced braces in {name}")


def main(html_path: str, out_path: str) -> None:
    html = open(html_path, encoding="utf-8").read()
    script = re.search(r"<script>\n(.*)\n</script>", html, re.S).group(1)

    parts = ["const G=1000, SECTORS=20;\n",
             "const TYRE_CORNERS=['LF','RF','LR','RR'];\n"]
    for name in NEEDED:
        parts.append(grab(script, name) + "\n")
    parts.append("export { parseIBT, buildSession };\n")

    open(out_path, "w", encoding="utf-8").write("\n".join(parts))
    print(f"extracted {len(NEEDED)} functions -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
