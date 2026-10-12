#!/usr/bin/env python3
"""recruiting-block-test.py -- the recruiting pages after the D-1012-35 refresh: the shared technology block matches its fragment, carries the
8 cards and only live images, and no recruiting page shows a dollar sign, a star glyph, a retired tool name, a Deal Desk mention or the
removed claims. Byte-identical on the four sites that hold it."""
import re, subprocess, sys
from pathlib import Path
R = Path(__file__).resolve().parent.parent.parent
PAGES = [p for p in ("join-our-team.html", "pages/join-our-team.html", "index.html", "why-join.html") if (R / p).exists()]
fails = []
def need(c, m):
    if not c: fails.append(m)
r = subprocess.run([sys.executable, str(R / "tools/sync-recruiting-tech.py"), "--check"], capture_output=True, text=True)
need(r.returncode == 0, "block differs from fragment: " + r.stdout + r.stderr)
frag = (R / "fragments/recruiting-tech-for-agents.html").read_text(encoding="utf-8")
need(frag.count('class="tg-card"') == 8, "expected 8 technology cards")
for want in ("Deposits and paperwork handled by the office",
             "Deposits that reach the office are recorded in trust against your deal, and your paperwork is filed and tracked on it.",
             "is in pilot with four agents"):
    need(want in frag, "missing in fragment: " + want)
for src in re.findall(r'src="(/images/recruiting/[^"]+)"', frag):
    need((R / src.lstrip("/")).exists(), "missing image " + src)
for rel in PAGES:
    page = (R / rel).read_text(encoding="utf-8")
    if "RECRUIT-TECH-BLOCK START" not in page:
        continue
    body = re.sub(r"<!--[\s\S]*?-->", "", re.sub(r"<(script|style)\b[\s\S]*?</\1>", "", page))
    text = re.sub(r"<[^>]+>", " ", body)
    need("$" not in text, rel + ": dollar sign in visible text")
    for bad in ("★", "BoldTrail", "SkySlope", "rlpSPHERE", "kvCORE", "Deal Desk", "Smart Leads"):
        need(bad not in text, rel + ": removed copy back: " + bad)
    need(not re.search(r"\d+K\+|\d{2},\d{3}\+", text), rel + ": a corporate statistic (20K+ / 20,000+) is back")
    need("Smart Leads" not in page, rel + ": Smart Leads in the meta copy")
if fails:
    print("FAIL"); [print(" -", f) for f in fails]; sys.exit(1)
print("ok: recruiting-block-test (%s)" % ", ".join(PAGES))
