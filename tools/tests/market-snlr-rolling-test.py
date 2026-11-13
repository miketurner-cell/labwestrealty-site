#!/usr/bin/env python3
"""Sales-to-new-listings chart: leave-out note + rolling 3-month series for small
areas (sites B-1110-03, Mike 2026-11-11). STRICT 2958. Offline, fabricated counts only.

Pins (aggregator build_snlr + page builder build_supply_trend_section):
  * a monthly area keeps its monthly series, and its chart carries the plain
    "thin months are left out" note with the floors read from the constants;
  * a small area (fewer than half of its sales-complete, locked months clear the
    single-month floors) plots the rolling 3-month series: sums THEN one division
    (never an average of ratios), a gap / unlocked / still-reporting month breaks
    the window, the floors apply to the 3-month sums, the points are labelled by
    their last month, and the title and note say "rolling 3 months";
  * rolling_3mo (stat cell, summary, PDF) is the point the chart ends on, and the
    single `latest` month is withheld in rolling mode.
Counts only: no sold price appears anywhere.

Run: python3 tools/tests/market-snlr-rolling-test.py
"""
import importlib.util
import sys
from datetime import date
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))


def load(name, fname):
    sp = importlib.util.spec_from_file_location(name, TOOLS / fname)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


agg = load("agg", "idx-stats-aggregator.py")
pagem = load("pagem", "build-market-stats-page.py")

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


TODAY = date(2026, 11, 5)
CLOSE = "2026-10-20"        # sales complete through September


def inputs(rows, locked=None):
    """rows: {month: (sales, new_listings)}; locked: months NOT locked."""
    unlocked = set(locked or ())
    byym = {k: {"count": s} for k, (s, n) in rows.items()}
    led = {k: {"new_listings": n, "locked": k not in unlocked} for k, (s, n) in rows.items()}
    return byym, led


def build(rows, locked=None, close=CLOSE):
    byym, led = inputs(rows, locked)
    return agg.build_snlr(byym, led, latest_close_date=close, today=TODAY)


# ── monthly (big) area ──────────────────────────────────────────
big = {"2026-05": (10, 20), "2026-06": (12, 22), "2026-07": (14, 20),
       "2026-08": (16, 24), "2026-09": (3, 4)}           # Sep is thin: 3 sales
b = build(big)
check("big area: series_basis monthly", b and b["series_basis"] == "monthly", str(b and b["series_basis"]))
check("big area: thin Sep not eligible, others are",
      [k for k, v in b["by_month"].items() if v["eligible"]] == ["2026-05", "2026-06", "2026-07", "2026-08"])
check("thresholds carry the floors from the constants",
      b["thresholds"]["min_sales"] == agg.SNLR_MIN_SALES and b["thresholds"]["min_new_listings"] == agg.SNLR_MIN_NEW_LISTINGS)
check("monthly rolling_3mo unchanged (last three eligible consecutive months)",
      b["rolling_3mo"]["months"] == ["2026-06", "2026-07", "2026-08"] and b["rolling_3mo"]["sales"] == 42)

cfg = {"label": "Big Area", "geo_description": "Big Area MLS"}
html, chart = pagem.build_supply_trend_section(cfg, {"snlr": b})
want = (f"Months with fewer than {agg.SNLR_MIN_SALES} sales or {agg.SNLR_MIN_NEW_LISTINGS} new listings, "
        "or whose sales are still being reported, are left out, so a thin month doesn't read as a market shift.")
check("monthly page: leave-out note under the chart, floors from the constants", want in html, html[-400:])
check("monthly page: note sits after the canvas inside the chart wrap",
      html.index("chartSupplyTrend") < html.index(want) < html.index("</div>\n    </div>\n  </div>"))
check("monthly page: only eligible months plotted",
      chart["labels"] == ["May 2026", "Jun 2026", "Jul 2026", "Aug 2026"], str(chart["labels"]))
check("monthly page: plain title, month by month", "Sales-to-New-Listings Ratio</div>" in html and "month by month" in html)

# ── small-area rule: fewer than half of complete+locked months pass ──
def mix(passing, total):
    months = [f"2026-{m:02d}" for m in range(5, 5 + total)]
    return {k: ((10, 12) if i < passing else (1, 1)) for i, k in enumerate(months)}

check("3 of 6 pass -> not small (half is enough)", build(mix(3, 6), close="2026-12-20")["series_basis"] == "monthly")
r = build(mix(2, 6), close="2026-12-20")
check("2 of 6 pass -> small", r is not None and r["series_basis"] == "rolling_3mo", str(r and r["series_basis"]))

# ── small area, rolling series ───────────────────────────────────
small = {"2026-05": (2, 3), "2026-06": (3, 4), "2026-07": (2, 3), "2026-08": (4, 5), "2026-09": (3, 4)}
s = build(small)
check("small area: rolling_3mo basis", s["series_basis"] == "rolling_3mo")
rb = s["rolling_by_month"]
check("small area: first point is May-Jul, labelled by Jul",
      sorted(rb) == ["2026-07", "2026-08", "2026-09"] and rb["2026-07"]["months"] == ["2026-05", "2026-06", "2026-07"])
check("sums then divide: Sep = 9/12 = 75.0, not the average of 3 ratios (73.9)",
      rb["2026-09"]["sales"] == 9 and rb["2026-09"]["new_listings"] == 12 and rb["2026-09"]["ratio_pct"] == 75.0,
      str(rb["2026-09"]))
check("rolling_3mo is the latest rolling point; latest single month withheld",
      s["rolling_3mo"]["months"] == ["2026-07", "2026-08", "2026-09"] and s["rolling_3mo"]["ratio_pct"] == 75.0
      and s["latest"] is None)
check("rolling condition label set", s["rolling_3mo"]["condition"] == "seller")

# gap in the ledger breaks every window that spans it
gap = dict(small); del gap["2026-08"]
g = build(gap)
check("missing August: no window spans it (only May-Jul survives, <2 points)",
      g is not None and sorted(k for k, v in g["rolling_by_month"].items()) == ["2026-07"])
# unlocked month
u = build(small, locked=["2026-06"])
check("unlocked June breaks windows containing it", sorted(u["rolling_by_month"]) == ["2026-09"], str(sorted(u["rolling_by_month"])))
# sales still being reported
c = build(small, close="2026-09-10")
check("September not sales-complete: its window and any later one are gone",
      sorted(c["rolling_by_month"]) == ["2026-07", "2026-08"], str(sorted(c["rolling_by_month"])))
# floors on the sums
low = {"2026-05": (1, 1), "2026-06": (1, 1), "2026-07": (1, 1), "2026-08": (1, 2), "2026-09": (2, 3)}
l = build(low)
check("sums below the floors -> nothing qualifies, block withheld", l is None, str(l))
edge = {"2026-05": (1, 1), "2026-06": (2, 2), "2026-07": (2, 2)}      # sums 5 and 5: exactly the floor
e = build(edge)
check("sums exactly at the floors qualify", e is not None and e["rolling_by_month"]["2026-07"]["eligible"])
edge2 = {"2026-05": (1, 1), "2026-06": (2, 2), "2026-07": (1, 2)}     # 4 sales
check("one short on sales -> not eligible", build(edge2) is None)

# year-ago rolling point
yago = {**{f"2025-{m:02d}": (3, 4) for m in (7, 8, 9)}, **small}
y = build(yago)
check("prior-year rolling point read from the series",
      y["prior_year"] and y["prior_year"]["rolling_3mo"]["months"] == ["2025-07", "2025-08", "2025-09"], str(y["prior_year"]))

# ── page in rolling mode ─────────────────────────────────────────
cfg2 = {"label": "Small Area", "geo_description": "Small Area MLS"}
html2, chart2 = pagem.build_supply_trend_section(cfg2, {"snlr": s})
check("rolling page: title says rolling 3 months", "Sales-to-New-Listings Ratio (rolling 3 months)</div>" in html2)
want2 = ("Each point covers that month and the two before it, because single months here are too small to read on "
         f"their own. Three-month windows with fewer than {agg.SNLR_MIN_SALES} sales or {agg.SNLR_MIN_NEW_LISTINGS} "
         "new listings, or with sales still being reported, are left out.")
check("rolling page: rolling note text", want2 in html2, html2[-500:])
check("rolling page: intro does not say month by month", "month by month" not in html2 and "rolling three-month windows" in html2)
check("rolling page: points labelled by last month, sum-based values",
      chart2["labels"] == ["Jul 2026", "Aug 2026", "Sep 2026"] and chart2["data"][-1] == 75.0, str(chart2))
check("rolling page: colours follow the condition", len(chart2["colors"]) == 3)
one = build({"2026-05": (2, 3), "2026-06": (3, 4), "2026-07": (2, 3), "2026-08": (1, 1)}, close="2026-08-20")
h3, c3 = pagem.build_supply_trend_section(cfg2, {"snlr": one})
check("fewer than 2 rolling points -> no section (>=2 rule kept)", (h3, c3) == ("", None), str(c3))

# page fallback floors equal the constants (so the literal fallback cannot drift)
old = {"by_month": b["by_month"], "thresholds": {"buyer_max": 40, "seller_min": 60}}
h4, _ = pagem.build_supply_trend_section(cfg, {"snlr": old})
check("aggregate without floors still shows the note with the constants' numbers", want in h4)
check("no price anywhere in the section", "$" not in html2.replace("&mdash;", "") and "price" not in html2.lower())

print()
if FAILS:
    print(f"{len(FAILS)} FAILED"); sys.exit(1)
print("all passed")
