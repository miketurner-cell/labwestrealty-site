#!/usr/bin/env python3
"""Lab West market-statistics refresh from a sibling site's committed aggregates (sites, D-1021-31).

Why this exists: Lab West has no listings feed of its own and no NLAR login (the one-login rule: a second RETS session fails with
ReplyCode 20022). Avalon's nightly already reads the whole-board sold cache and commits tools/idx-cache/live-aggregates.json; its
REGION_CONFIG carries the three Lab West regions ("Labrador City / Wabush", "Labrador City", "Wabush"). This script takes those three
regions from that file and writes Lab West's own tools/idx-cache/live-aggregates.json, which build-market-stats-page.py renders.

Counts and days on market only (D-1021-12): every sold-price-derived key is stripped (idx-stats-aggregator.strip_sold_prices), so
a price in the sibling file never reaches this repo, which is public.

Fails loud (always-on #7, #16): missing or unreadable source, source older than --max-age-days, a Lab West region missing or empty,
the two towns not adding up to the combined region, or no complete month. Nothing is written in those cases.

Usage: labwest-stats-refresh.py --sibling <path to live-aggregates.json> [--out FILE] [--first-year 2025] [--max-age-days 3]
"""
import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGIONS = ("Labrador City / Wabush", "Labrador City", "Wabush")


def _load_strip():
    spec = importlib.util.spec_from_file_location("lw_idx_agg", HERE / "idx-stats-aggregator.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.strip_sold_prices


def fail(msg):
    print(f"labwest-stats-refresh: FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _parse_ts(s):
    s = str(s or "").replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def refresh(src, first_year, max_age_days, now=None):
    now = now or datetime.now(timezone.utc)
    strip = _load_strip()
    fetched = _parse_ts(src.get("fetched_at"))
    if fetched is None:
        fail("the source has no fetched_at; refusing to say how fresh it is")
    if now - fetched > timedelta(days=max_age_days):
        fail(f"the source was fetched {fetched.isoformat()}, older than {max_age_days} days; not publishing stale figures")
    have = src.get("regions") or {}
    missing = [r for r in REGIONS if r not in have]
    if missing:
        fail(f"the source has no region {missing}; Avalon's REGION_CONFIG must carry them")
    out_regions = {}
    for r in REGIONS:
        blk = strip(have[r])
        for k in ("by_year", "by_year_month"):
            d = blk.get(k) or {}
            blk[k] = {key: v for key, v in d.items() if int(str(key)[:4]) >= first_year}
        # the by-town blocks are not rendered; keep the file to what the page uses
        blk.pop("by_municipality", None)
        out_regions[r] = blk
    comb = out_regions["Labrador City / Wabush"]
    if not comb["by_year"] or not any(v.get("count") for v in comb["by_year"].values()):
        fail("the combined region has no sales from the first full year on")
    # completeness: the two towns must add up to the combined region, year by year (a town whose rows were dropped shows here)
    for yr, v in comb["by_year"].items():
        parts = sum(int((out_regions[t]["by_year"].get(yr) or {}).get("count") or 0) for t in ("Labrador City", "Wabush"))
        if parts != int(v.get("count") or 0):
            fail(f"{yr}: Labrador City + Wabush = {parts} but the combined region says {v.get('count')}")
    if not comb.get("ytd_complete_through_date_iso") or not comb.get("ytd_complete"):
        fail("no complete month in the current year yet; nothing to publish")
    years = sorted(int(y) for y in comb["by_year"])
    return {
        "fetched_at": src.get("fetched_at"),
        "source": "avalonrealestate-site tools/idx-cache/live-aggregates.json (NLAR sold cache, whole board)",
        "source_cache_count": src.get("source_cache_count"),
        # the whole-board latest close is NOT Lab West's; the page reads the complete-month date from the region instead
        "latest_close_date": None,
        "year_range": [years[0], years[-1]],
        "regions": out_regions,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sibling", required=True)
    ap.add_argument("--out", default=str(HERE / "idx-cache" / "live-aggregates.json"))
    ap.add_argument("--first-year", type=int, default=2025)
    ap.add_argument("--max-age-days", type=int, default=3)
    a = ap.parse_args(argv)
    p = Path(a.sibling)
    if not p.is_file():
        fail(f"{p} not found")
    try:
        src = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        fail(f"{p} unreadable: {e}")
    dump = refresh(src, a.first_year, a.max_age_days)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dump, indent=2, default=str))
    c = dump["regions"]["Labrador City / Wabush"]
    y = c["ytd_complete"]
    print(f"labwest-stats-refresh: wrote {out}: {dump['year_range'][0]}-{dump['year_range'][1]}, complete months through "
          f"{c['ytd_complete_through_date_iso']}, {y.get('count')} sales in the complete part of the year")
    return 0


if __name__ == "__main__":
    sys.exit(main())
