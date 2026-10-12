#!/usr/bin/env python3
"""STRICT: no development wording in the VISIBLE text of built pages.

2026-10-08 (sites; D-1008-22 fix 2, D-1008-25). avalonrealestate.ca/listings/ showed
"Range slider lands in Wave 2.", "NL moat" and "no regex per #170 lesson" to visitors.

What counts as visible: text nodes outside <script>/<style>/<noscript>/<template>/<head>
and HTML comments, plus the title, placeholder, aria-label, alt and value attributes
anywhere in the page. Text inside <code>/<pre> is still visible text and is scanned.

Scope: every built .html page in the repo (skips .git, node_modules, _archive, tools,
fleet, .claude, .github, _ops, _research and other non-served folders).

Usage:
  python3 tools/tests/dev-wording-visible-test.py            # fail on any hit
  python3 tools/tests/dev-wording-visible-test.py --report   # print hits, exit 0
This file is identical in the three listing-site repos (no per-site edits).
"""
import os
import re
import sys
from html.parser import HTMLParser

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SKIP_DIRS = {".git", "node_modules", "_archive", "tools", "fleet", ".claude", ".github",
             "_ops", "_research", "_drafts", "netlify", "supabase", "scripts", "docs",
             "_scratch", "venv", ".venv"}
SKIP_TAGS = {"script", "style", "noscript", "template", "head"}
ATTRS = {"title", "placeholder", "aria-label", "alt", "value", "aria-description"}

# (label, regex). Case-insensitive unless noted. Patterns are deliberately specific.
PATTERNS = [
    ("Wave N", re.compile(r"\bwave\s*\d", re.I)),
    ("slice N", re.compile(r"\bslice\s*\d", re.I)),
    ("moat", re.compile(r"\bmoat\b", re.I)),
    ("lands in", re.compile(r"\blands?\s+in\s+(wave|slice|phase|v\d|the next|a future)", re.I)),
    ("coming in wave", re.compile(r"\b(coming|arrives|ships)\s+in\s+(wave|slice|phase)", re.I)),
    ("lesson/convention ref", re.compile(r"(#\s?\d{2,4}\s+(lesson|convention|semantics)|\b(lesson|convention|decision|task)\s*#\s?\d{2,4}|\bper\s+#\s?\d{2,4}\b|post-#\d{2,4})", re.I)),
    ("TODO/FIXME", re.compile(r"\b(TODO|FIXME)\b")),
    ("internal tool name", re.compile(r"(\bagainst DDF\b|structured-field check|\b_is_new_construction\b)", re.I)),
    ("DDF", re.compile(r"\bDDF\b")),
    ("lorem ipsum", re.compile(r"lorem ipsum", re.I)),
]


class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.items = []  # (kind, text)

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ATTRS and v:
                if k == "value" and tag not in ("input", "button", "option"):
                    continue
                self.items.append((f"{tag}[{k}]", v))
        if tag in SKIP_TAGS:
            self.skip += 1

    def handle_startendtag(self, tag, attrs):
        for k, v in attrs:
            if k in ATTRS and v:
                self.items.append((f"{tag}[{k}]", v))

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if self.skip:
            return
        t = " ".join(data.split())
        if t:
            self.items.append(("text", t))


def head_title(src):
    m = re.search(r"<title[^>]*>(.*?)</title>", src, re.S | re.I)
    return " ".join(m.group(1).split()) if m else ""


def pages():
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in fns:
            if fn.endswith(".html"):
                yield os.path.join(dp, fn)


def scan_file(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        src = f.read()
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    # Internal tools that tell search engines to stay away are not visitor pages.
    if re.search(r'<meta[^>]+name=["\']robots["\'][^>]+noindex', src[:6000], re.I):
        return []
    p = Visible()
    p.feed(src)
    items = list(p.items)
    t = head_title(src)
    if t:
        items.append(("title", t))
    hits = []
    for kind, text in items:
        for label, rx in PATTERNS:
            if rx.search(text):
                hits.append((label, kind, text[:160]))
    return hits


def main():
    report = "--report" in sys.argv
    total = 0
    files = 0
    n = 0
    for path in sorted(pages()):
        n += 1
        hits = scan_file(path)
        if hits:
            files += 1
            rel = os.path.relpath(path, ROOT)
            for label, kind, text in hits:
                total += 1
                print(f"{rel}: [{label}] <{kind}> {text}")
    print(f"dev-wording scan: {n} pages, {total} hit(s) in {files} page(s)")
    if total and not report:
        print("FAIL: development wording in visible text. Rewrite in visitor-facing words or drop it "
              "(HTML/code comments may keep it).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
