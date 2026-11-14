#!/usr/bin/env python3
"""recruiting-block-test.py -- the recruiting pages after the 2026-11-14 benefits rewrite (Mike: "Approve the rewrite, keep the card,
301 the training page"): the shared block matches its fragment, carries the 6 benefit cards and only live images, names no internal
tool or mechanism (protect the competitive edge), and no recruiting page shows a dollar sign, a star glyph, a retired tool name or the
removed claims. Byte-identical on the four sites that hold it (Goose Bay, Avalon, Lab West, hub)."""
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
need(frag.count('class="tg-card"') == 6, "expected 6 benefit cards")
for want in ("How we back you", "An office line that&rsquo;s always answered", "Listing Text Alerts and Listing Email Alerts",
             "There&rsquo;s more we&rsquo;re building."):
    need(want in frag, "missing in fragment: " + want)
ftext = re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)\b[\s\S]*?</\1>", "", frag))
# 2026-11-14: benefits, not systems -- no internal tool names, mechanics or internal screens in the shared block
for bad in ("Follow Up Boss", "office@", "pilot", "Turner Agent", "Turner Deals", "in trust", "within the hour", "first-call",
            "response times", "sample data"):
    need(bad not in ftext, "system detail back in the block: " + bad)
for img in ("lead-assigned", "deal-file", "done-automatically", "share-text", "just-sold-letter", "pending-card"):
    need(img not in frag, "internal or illustration picture back: " + img)
for src in re.findall(r'src="(/images/recruiting/[^"]+)"', frag):
    need((R / src.lstrip("/")).exists(), "missing image " + src)
for rel in PAGES:
    page = (R / rel).read_text(encoding="utf-8")
    if "RECRUIT-TECH-BLOCK START" not in page:
        continue
    body = re.sub(r"<!--[\s\S]*?-->", "", re.sub(r"<(script|style)\b[\s\S]*?</\1>", "", page))
    text = re.sub(r"<[^>]+>", " ", body)
    # D-1027-43 (design 2, "Not licensed yet?"): the NLAR join and dues figures are the only dollar amounts allowed (D-1026-31, sources in tools/brokerage-facts.json)
    need("$" not in text.replace("about $1,918 + HST", "").replace("about $253 a month", ""), rel + ": dollar sign in visible text")
    for bad in ("★", "BoldTrail", "SkySlope", "rlpSPHERE", "kvCORE", "Deal Desk", "Smart Leads", "Follow Up Boss", "Turner Deals", "in pilot"):
        need(bad not in text, rel + ": removed copy back: " + bad)
    need("Follow Up Boss" not in page, rel + ": Follow Up Boss in the meta or structured data")
    need(not re.search(r"\d+K\+|\d{2},\d{3}\+", text), rel + ": a corporate statistic (20K+ / 20,000+) is back")
    need("Smart Leads" not in page, rel + ": Smart Leads in the meta copy")
if fails:
    print("FAIL"); [print(" -", f) for f in fails]; sys.exit(1)
print("ok: recruiting-block-test (%s)" % ", ".join(PAGES))
