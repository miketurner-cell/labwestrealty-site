#!/usr/bin/env python3
"""STRICT: Lab West market-stats refresh from a sibling's committed aggregates (sites, D-1021-31).

In a temp copy of the repo: run the real aggregator over the synthetic rows (labwest_fixtures), make a "sibling" file that carries the
three Lab West regions WITH sold-price keys (as Avalon's would), then run tools/labwest-stats-refresh.py and the page builder with
--output-root, and check:
  1. no sold-price key survives into Lab West's aggregates; 2024 (a part-year in the real feed) is dropped; the towns add up;
  2. the page is at /market-stats.html with that canonical, says "Data through <complete-month end>", names the dates in the current-year
     heading, never says "so far" or "Updated Monthly", and has no row for the partial current month;
  3. the refresh fails loud (exit 1, nothing written) on a stale source, a missing region, a missing source and a towns-do-not-add-up source.
"""
import copy
import datetime
import json
import re
import shutil
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


rows = labwest_fixtures.sold_full_rows()
tmp = Path(tempfile.mkdtemp(prefix="lwrefresh-"))
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
    (cache / "live-aggregates.json").unlink()

    # the sibling file: every region carries price keys, as another site's aggregates do
    sib = copy.deepcopy(agg)
    sib["fetched_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def add_prices(node):
        if isinstance(node, dict):
            if "count" in node:
                node.update({"avg_price": 123456.0, "median_price": 120000.0, "total_volume": 9999999.0, "avg_sa": 98.7})
            for v in node.values():
                add_prices(v)
    for blk in sib["regions"].values():
        add_prices(blk)
        blk["price_bands"] = {"x": 1}
    sibp = tmp / "sibling.json"
    sibp.write_text(json.dumps(sib))
    out = tmp / "out.json"

    def refresh(src, *extra):
        return run("tools/labwest-stats-refresh.py", "--sibling", str(src), "--out", str(out), *extra)

    out.unlink(missing_ok=True)
    r = refresh(sibp)
    check(r.returncode == 0, f"1: refresh failed: {r.stdout[-300:]} {r.stderr[-300:]}")
    res = json.loads(out.read_text()) if out.exists() else {}
    blob = json.dumps(res)
    check(not re.search(r"avg_price|median_price|total_volume|avg_sa|price_bands|123456", blob), "1: a sold-price figure reached Lab West's aggregates (D-1021-12)")
    lw = res.get("regions", {}).get("Labrador City / Wabush", {})
    check(sorted(res.get("regions", {})) == ["Labrador City", "Labrador City / Wabush", "Wabush"], "1: regions are not the three Lab West regions")
    check("2024" not in lw.get("by_year", {}) and "2025" in lw.get("by_year", {}), "1: 2024 (a part-year in the feed) must be dropped, 2025 kept")
    check(all(k >= "2025" for k in lw.get("by_year_month", {})), "1: a month before 2025 survived")
    check(res.get("latest_close_date") is None, "1: the whole-board latest close date must not be published as Lab West's")
    check(lw["by_year"]["2025"]["count"] == agg["regions"]["Labrador City / Wabush"]["by_year"]["2025"]["count"], "1: the 2025 count changed in transit")

    # 2. the page
    (cache / "live-aggregates.json").write_text(out.read_text())
    r = run("tools/build-market-stats-page.py", "--all", "--output-root")
    page_p = work / "market-stats.html"
    check(r.returncode == 0 and page_p.exists(), f"2: build failed: {(r.stdout + r.stderr)[-300:]}")
    raw = page_p.read_text(encoding="utf-8") if page_p.exists() else ""
    text = re.sub(r"<style.*?</style>|<script.*?</script>", "", raw, flags=re.S | re.I)
    check('rel="canonical" href="https://labwestrealty.com/market-stats.html"' in raw, "2: canonical is not /market-stats.html")
    thru = datetime.date.fromisoformat(lw["ytd_complete_through_date_iso"])
    stamp = f"{thru.strftime('%b')} {thru.day}, {thru.year}"
    check(f"Data through {stamp}" in text, f"2: the page must say 'Data through {stamp}'")
    check(f"January 1 to {stamp}" in text, "2: the current-year heading must name January 1 to the through date")
    check(not re.search(r"so far|updated monthly", text, re.I), "2: 'so far' or 'Updated Monthly' on the page")
    partial = max(lw["by_year_month"])
    pm = datetime.date.fromisoformat(partial + "-01")
    if partial > lw["ytd_complete_through_date_iso"][:7]:
        check(f"{pm.strftime('%B')} {pm.year}</td>" not in text, f"2: the partial month {partial} is a row on the page")
    check("2024</td>" not in text, "2: 2024 (a part-year) is a row on the page")
    check("first full year" in text, "2: the page must say 2025 is the first full year shown")

    # 3. fail loud
    def bad(label, mutate, *extra):
        s = copy.deepcopy(sib)
        mutate(s)
        p = tmp / "bad.json"
        p.write_text(json.dumps(s))
        out.unlink(missing_ok=True)
        r = refresh(p, *extra)
        check(r.returncode == 1 and not out.exists(), f"3: {label}: expected exit 1 and no file, got {r.returncode} (out exists: {out.exists()})")

    bad("stale source", lambda s: s.update(fetched_at="2026-01-01T00:00:00Z"))
    bad("missing region", lambda s: s["regions"].pop("Wabush"))
    bad("towns do not add up", lambda s: s["regions"]["Wabush"]["by_year"]["2025"].update(count=999))
    bad("no fetched_at", lambda s: s.pop("fetched_at"))
    out.unlink(missing_ok=True)
    r = refresh(tmp / "nope.json")
    check(r.returncode == 1 and not out.exists(), "3: a missing source file must exit 1")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if errors:
    print("labwest-stats-refresh-test FAILED:")
    for e in errors:
        print("  -", e)
    sys.exit(1)
print("labwest-stats-refresh-test OK: no price, part-year dropped, complete months only, dates named, fails loud")
