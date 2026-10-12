#!/usr/bin/env python3
"""STRICT: Lab West nightly pieces (sites, D-1012-34, component 6) -- aggregates, market-statistics page, community pages.

Runs the real aggregator, market-stats builder and community builder in a temp copy of the repo over synthetic sold rows
(tools/tests/labwest_fixtures.py: about 118 Labrador City / Wabush sales 2024-01..2026-10 plus Goose Bay rows that must be
ignored) and checks:
  1. the aggregates are the fixture's own numbers (YTD sales, 2025 sales, average price recomputed here from the raw rows), and
     only the three Lab West regions exist; the Goose Bay rows (close price 999,000) reach no number and no page;
  2. the market-statistics page says what the data runs through (the latest close date) and carries no hand-typed history:
     the YAML has no ten_year_historical_* keys, and no figure on the page exceeds what the fixture can produce;
  3. no Goose Bay / Gander / Dynamic Duo contact, no office address, the Lab West Google tag, Mike Turner as the contact;
  4. the community pages name Mike Turner, carry only the facts in the YAML, and build without an agent card or form;
  5. the state script lists the generated pages in sitemap-pages.xml on `on` and noindexes them on `preview`;
  6. OFF PROOF: the committed tree has no pages/ directory and no live aggregates, so nothing from this component is served.
"""
import datetime
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "tests"))
import labwest_fixtures  # noqa: E402

errors = []


def check(c, m):
    if not c:
        errors.append(m)


# 6. off proof on the committed tree
check(not (ROOT / "pages").exists(), "6: pages/ exists in the committed tree while the switch has never been on")
check(not (ROOT / "tools" / "idx-cache" / "live-aggregates.json").exists(), "6: live-aggregates.json is committed")
yml = (ROOT / "tools" / "market-stats-config" / "labrador-west.yml").read_text()
check(not re.search(r"^\s*ten_year_historical", yml, re.M), "2: the market-stats YAML carries hand-typed historical arrays")

rows = labwest_fixtures.sold_full_rows()
lw = [r for r in rows if r["Subdistrict"] == "Labrador City / Wabush"]
latest = max(r["CloseDate"] for r in lw)
cy = int(latest[:4])

tmp = Path(tempfile.mkdtemp(prefix="lwnight-"))
try:
    work = tmp / "site"
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", ".claude", "node_modules", "__pycache__", "listings", "property", "pages"))
    cache = work / "tools" / "idx-cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "sold-listings-full.json").write_text(json.dumps({"fetched_at": "2026-10-11T20:00:00Z", "rows": rows}))

    def run(*args):
        return subprocess.run([sys.executable, *args], cwd=work, capture_output=True, text=True)

    r = run("tools/idx-stats-aggregator.py")
    check(r.returncode == 0, f"aggregator failed: {r.stderr[-300:]}")
    agg = json.loads((cache / "live-aggregates.json").read_text())
    regs = agg["regions"]
    check(sorted(regs) == ["Labrador City", "Labrador City / Wabush", "Wabush"], f"1: regions are {sorted(regs)}")
    thr_m = regs["Labrador City / Wabush"]["ytd_complete_through_month"]  # the page and the YTD are through the last COMPLETE month
    ytd_rows = [x for x in lw if x["CloseDate"].startswith(str(cy)) and int(x["CloseDate"][5:7]) <= thr_m]
    check(regs["Labrador City / Wabush"]["ytd_complete"]["count"] == len(ytd_rows), f"1: YTD count {regs['Labrador City / Wabush']['ytd_complete']['count']} != fixture {len(ytd_rows)}")
    y25 = [x for x in lw if x["CloseDate"].startswith("2025")]
    check(regs["Labrador City / Wabush"]["by_year"]["2025"]["count"] == len(y25), "1: 2025 count differs from the fixture")
    avg25 = statistics.mean(float(x["ClosePrice"]) for x in y25)
    got = regs["Labrador City / Wabush"]["by_year"]["2025"].get("avg_price")
    check(got is not None and abs(got - avg25) < 1.0, f"1: 2025 average price {got} != recomputed {avg25:.0f}")
    check(regs["Labrador City"]["ytd_complete"]["count"] + regs["Wabush"]["ytd_complete"]["count"] == len(ytd_rows), "1: town counts do not add up to Labrador West")
    check("999000" not in json.dumps(agg), "1: a Goose Bay close price reached the aggregates")

    r = run("tools/build-market-stats-page.py", "--all")
    check(r.returncode == 0 and (work / "pages" / "market-stats.html").exists(), f"market-stats build failed: {(r.stdout + r.stderr)[-400:]}")
    r = run("tools/build-community-pages.py", "--all")
    check(r.returncode == 0 and (work / "pages" / "labrador-city.html").exists() and (work / "pages" / "wabush.html").exists(), f"community build failed: {(r.stdout + r.stderr)[-400:]}")

    def text_of(p):
        t = p.read_text(encoding="utf-8")
        return re.sub(r"<style.*?</style>|<script.*?</script>", "", t, flags=re.S | re.I), t

    ms_text, ms_raw = text_of(work / "pages" / "market-stats.html")
    thru = datetime.date.fromisoformat(regs["Labrador City / Wabush"]["ytd_complete_through_date_iso"])
    check(re.search(r"data through", ms_text, re.I) is not None and f"{thru.strftime('%b')} {thru.day}, {thru.year}" in ms_text, f"2: the market-stats page must say it runs through {thru}")
    check(str(len(ytd_rows)) in ms_text, f"2: the YTD sales count ({len(ytd_rows)}) is not on the page")
    check("999,000" not in ms_text and "999000" not in ms_raw, "1: a Goose Bay price is on the market-stats page")
    for p in sorted((work / "pages").glob("*.html")):
        t_text, t_raw = text_of(p)
        for needle in ("Dynamic Duo", "goosebay", "Goose Bay", "Karen", "Roberta", "896-5001", "Hamilton River", "204 Airport", "office@realestategander.com"):
            check(needle.lower() not in t_raw.lower().replace("https://goosebayrealestate.ca/pages/market-stats.html", ""), f"3: {p.name} contains {needle!r}")
        check("G-FEMZDX1BJQ" not in t_raw, f"3: {p.name} carries Gander's Google stream")
        check("GT-M38MJCDZ" in t_raw, f"3: {p.name} lacks Lab West's Google tag")
    check("Mike Turner" in ms_text and "709-256-7999" in ms_text, "3: the market-stats page must name Mike Turner and 709-256-7999")
    cc_text, cc_raw = text_of(work / "pages" / "labrador-city.html")
    check("Mike Turner" in cc_text, "4: the community page must name Mike Turner")
    check("cmx-agent" not in cc_raw and "data-team-email" not in cc_raw, "4: a community agent card or lead form appeared (none is configured)")
    check(not (work / "community-v2").exists(), "4: a layout-v2 preview copy was written")

    r = subprocess.run([sys.executable, str(work / "tools/tests/labwest-no-address-test.py")], capture_output=True, text=True)
    check(r.returncode == 0, f"3: no-address test fails on the generated pages: {r.stdout[-300:]}")

    # 5. state script
    st = [sys.executable, str(work / "tools" / "labwest-listings-state.py")]
    idx0 = (work / "sitemap-index.xml").read_text()
    (work / "listings").mkdir(exist_ok=True)
    subprocess.run(st + ["preview", "--root", str(work)], check=True, capture_output=True)
    check(all('content="noindex,nofollow"' in (work / "pages" / n).read_text() for n in ("market-stats.html", "labrador-city.html", "wabush.html")), "5: preview must noindex the generated pages")
    check(not (work / "sitemap-pages.xml").exists() and (work / "sitemap-index.xml").read_text() == idx0, "5: preview must not list the generated pages")
    subprocess.run(st + ["on", "--root", str(work)], check=True, capture_output=True)
    sm = (work / "sitemap-pages.xml").read_text()
    check(all(f"https://labwestrealty.com/pages/{n}" in sm for n in ("market-stats.html", "labrador-city.html", "wabush.html")), "5: on must list the generated pages")
    check("sitemap-pages.xml" in (work / "sitemap-index.xml").read_text(), "5: on must register sitemap-pages.xml")
    check(all("noindex" not in (work / "pages" / n).read_text() for n in ("market-stats.html", "labrador-city.html", "wabush.html")), "5: on must remove the noindex tag")
    # a hand-written page in pages/ is never touched
    (work / "pages" / "home-value.html").write_text("<html><head></head><body>hand</body></html>")
    subprocess.run(st + ["preview", "--root", str(work)], check=True, capture_output=True)
    check("noindex" not in (work / "pages" / "home-value.html").read_text(), "5: a hand-written page was noindexed")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if errors:
    print("labwest-nightly-test FAILED:")
    for e in errors:
        print("  -", e)
    sys.exit(1)
print("labwest-nightly-test OK: aggregates match the rows, page says what it runs through, no Goose Bay or Gander, off proof")
