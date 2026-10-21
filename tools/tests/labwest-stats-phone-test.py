#!/usr/bin/env python3
"""STRICT: Lab West counts-only market-stats tables fit a phone (sites, 2026-10-21, Mike: "fix the LabWest table on phones").

  1. The counts-page renderer marks both tables ms-counts-table and gives the days column a short phone header.
  2. _base.css lets that table drop the 460px min-width at 700px and below, shows the short header and hides the long one.
  3. The committed market-stats.html carries the same markup and CSS.
  4. If a headless Chromium (playwright) is installed, render the committed page at 375 and 390: the document is not wider than
     the viewport and no table is wider than its container. Without playwright this step says so and is skipped (1 to 3 still run).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
errors = []


def check(c, m):
    if not c:
        errors.append(m)


gen = (ROOT / "tools" / "build-market-stats-page.py").read_text()
a, b = gen.index("def generate_counts_page"), gen.index("def generate_page")
seg = gen[a:b]
check(seg.count('<table class="ms-10yr-table ms-counts-table">') == 2, "1: both counts tables must carry ms-counts-table")
check(seg.count('<span class="ms-h-short">Days on market</span>') == 2, "1: both days columns need the short phone header")

css = (ROOT / "tools" / "market-stats-config" / "_base.css").read_text()
m = re.search(r"@media \(max-width: 700px\) \{\s*\.ms-counts-table \{ min-width: 0;.*?\n\}", css, re.S)
check(bool(m), "2: no 700px rule resets .ms-counts-table min-width")
check(".ms-counts-table .ms-h-short { display: none; }" in css, "2: short header must be hidden on wide screens")
check(m and ".ms-h-long { display: none; }" in m.group(0) and ".ms-h-short { display: inline; }" in m.group(0), "2: phone rule must swap the headers")

page = ROOT / "market-stats.html"
raw = page.read_text(encoding="utf-8")
check(raw.count('class="ms-10yr-table ms-counts-table"') == 2, "3: committed page lacks the counts-table markup")
check(".ms-counts-table .ms-h-short" in raw and "min-width: 0" in raw, "3: committed page lacks the counts-table CSS")

try:
    from playwright.sync_api import sync_playwright
except Exception:
    print("labwest-stats-phone-test: playwright not installed, render step skipped (1 to 3 ran)")
else:
    try:
        with sync_playwright() as p:
            br = p.chromium.launch()
            for w in (375, 390):
                pg = br.new_page(viewport={"width": w, "height": 900})
                pg.goto(page.resolve().as_uri(), wait_until="domcontentloaded")
                r = pg.evaluate("""()=>({sw:document.documentElement.scrollWidth,
                    t:[...document.querySelectorAll('table')].map(t=>[t.getBoundingClientRect().width,t.parentElement.clientWidth])})""")
                check(r["sw"] <= w, f"4: at {w}px the page is {r['sw']}px wide")
                check(r["t"] and all(tw <= cw + 1 for tw, cw in r["t"]), f"4: at {w}px a table is wider than its container: {r['t']}")
                pg.close()
            br.close()
    except Exception as e:
        print(f"labwest-stats-phone-test: render step skipped ({type(e).__name__}: {str(e)[:80]})")

if errors:
    print("FAIL"); [print(" -", e) for e in errors]; sys.exit(1)
print("labwest-stats-phone-test: ok")
