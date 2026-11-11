#!/usr/bin/env python3
"""Market-stats pages never show a single sale's price (STRICT 2956, sites 2026-11-10, B-1110-03).

Mike (2026-11-10): "remove the highest-sale line from the market stats pages". The monthly
spotlight no longer prints "Highest sale this month: $X" and the milestone list no longer
claims "highest_sale_record" (the month's top sale is the same single-sale price). Median,
average, count, days on market and sale-to-list stay.

Feeds the real generator a crafted region whose current month has BOTH the highest median
and the highest single sale in a 21-month record, so the record claim would fire if the code
were still there. Offline. Exits 1 on any failure.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
FAILS: list[str] = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


spec = importlib.util.spec_from_file_location("ms_gen", TOOLS / "build-market-stats-page.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)


def bucket(median, top):
    return {"count": 12, "avg_price": median + 5000.0, "median_price": median, "avg_dom": 30,
            "median_dom": 30, "avg_sa": 98.5, "total_volume": median * 12, "at_100_plus": 0,
            "max_price": top}


bym = {}
for y in (2025, 2026):
    for m in range(1, 13):
        if y == 2026 and m > 9:
            break
        bym[f"{y}-{m:02d}"] = bucket(300000.0, 400000.0)
bym["2026-09"] = bucket(350000.0, 987654.0)  # record median AND record single sale
region = {"by_year_month": bym, "label": "x"}
agg = {"latest_close_date": "2026-10-15", "regions": {"Testtown": region}}
cfg = {"region_key": "Testtown", "label": "Testtown", "geo_description": "Testtown", "baseline_year": 2025}

spot = gen._spotlight_context(region, agg)
check("spotlight context resolves", bool(spot))
claims = gen.compute_record_claims(region, cfg, spot) or []
kinds = [c.get("kind") for c in claims]
check("no highest_sale_record claim", "highest_sale_record" not in kinds, str(kinds))
check("no claim text quotes the top sale", not any("987,654" in (c.get("text") or "") for c in claims))
check("the median record claim is still made", "monthly_median_record" in kinds, str(kinds))

sp = gen.build_monthly_spotlight_section(cfg, region, agg, spot)
check("spotlight renders", bool(sp))
check("spotlight has no 'Highest sale this month'", "Highest sale" not in sp)
check("spotlight has no ms-spotlight-highest", "ms-spotlight-highest" not in sp)
check("spotlight does not print the top sale price", "987,654" not in sp)
check("spotlight keeps median, average, DOM and sale-to-list",
      all(w in sp for w in ("Median Sale Price", "Avg Sale Price", "Avg Days on Market", "Sale-to-List Ratio")))
check("spotlight keeps the 'reported through' note", "closings reported" in sp)

css = (TOOLS / "market-stats-config" / "_base.css").read_text()
check("no dead .ms-spotlight-highest CSS", "ms-spotlight-highest" not in css)

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    sys.exit(1)
print("\nall passed")
