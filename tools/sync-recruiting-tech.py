#!/usr/bin/env python3
"""sync-recruiting-tech.py -- keep the shared "What our technology does for you" block identical to
fragments/recruiting-tech-for-agents.html (D-1012-35). The fragment is the fleet-canonical source for this block: every site holds the same
file and this same script, byte for byte. Default = inject into each recruiting page that carries the markers; --check = exit 1 if any
page's block differs (or no page carries the block). Pages looked at: join-our-team.html, pages/join-our-team.html, index.html, why-join.html."""
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
PAGES = ["join-our-team.html", "pages/join-our-team.html", "index.html", "why-join.html"]
FRAG = ROOT / "fragments" / "recruiting-tech-for-agents.html"
START, END = "<!-- RECRUIT-TECH-BLOCK START -->\n", "<!-- RECRUIT-TECH-BLOCK END -->"
frag = FRAG.read_text(encoding="utf-8")
found, bad = 0, 0
for rel in PAGES:
    path = ROOT / rel
    if not path.exists():
        continue
    page = path.read_text(encoding="utf-8")
    m = re.search(re.escape(START) + r"([\s\S]*?)" + re.escape(END), page)
    if not m:
        continue
    found += 1
    if "--check" in sys.argv:
        if m.group(1) != frag:
            print("ERROR: " + rel + " block differs from fragments/recruiting-tech-for-agents.html; run tools/sync-recruiting-tech.py"); bad += 1
    else:
        path.write_text(page[:m.start(1)] + frag + page[m.end(1):], encoding="utf-8"); print("injected " + rel)
if found == 0:
    sys.exit("ERROR: no page carries the RECRUIT-TECH-BLOCK markers")
if bad:
    sys.exit(1)
if "--check" in sys.argv:
    print("ok: %d page(s) match the fragment" % found)
