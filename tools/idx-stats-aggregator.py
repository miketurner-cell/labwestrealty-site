#!/usr/bin/env python3
"""
Turner Realty — IDX Stats Aggregator
=====================================

Walks `tools/idx-cache/sold-listings-full.json` (the all-history sold cache
populated by `idx-ingest.py --pull sold --backfill`) and emits aggregated
per-region per-year/month statistics to `tools/idx-cache/live-aggregates.json`.

This is the data source that powers the 19 market-stats pages — replaces
the existing Matrix .txt export workflow (~30 min/month manual) with a
fully-automated daily refresh.

Pipeline position:
    idx-ingest.py --pull sold --incremental
        ↓
    sold-listings-full.json     ← 22-year all-history sold cache
        ↓
    idx-stats-aggregator.py     ← THIS FILE
        ↓
    live-aggregates.json        ← per-region × per-period stats
        ↓
    update-market-stats-from-cache.py   ← (Phase 3) ports update-market-stats.py
        ↓
    19 market-stats pages refresh

Output schema:
    {
      "fetched_at":           "2026-05-07T...Z",
      "source_cache_md5":     "...",
      "source_cache_count":   77234,
      "year_range":           [2004, 2026],
      "regions": {
        "Gander and Area": {
          "by_year": {
            "2026": {count, avg_price, median_price, avg_dom, avg_sa,
                     total_volume, at_100_plus, ...},
            "2025": {...},
            ...
          },
          "by_year_month": {
            "2026-05": {...},
            ...
          },
          "by_municipality": {
            "Gander":   {by_year: {...}, ...},
            "Appleton": {by_year: {...}, ...},
            ...
          },
          "ytd": {...},          # current YTD through last completed month
          "prior_ytd": {...},    # same period prior year
          "yoy": {...},          # delta strip (Convention #21 small-sample guard)
        },
        ...
      }
    }

Convention compliance:
- Convention #21: small-sample threshold (skip YoY if prior_count < 5)
- Convention #32: every metric traceable to a sold record (no fabricated)
- Convention #15: aggregator ports byte-symmetric to stjohns + goosebay
- Convention #19: WARN-only on data quality issues; never blocks the run

Usage:
    python3 tools/idx-stats-aggregator.py
    python3 tools/idx-stats-aggregator.py --json     # machine-readable
    python3 tools/idx-stats-aggregator.py --region "Gander and Area"   # one region
    python3 tools/idx-stats-aggregator.py --verbose
"""

import argparse
import hashlib
import json
import re
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SITE_ROOT = SCRIPT_DIR.parent
CACHE_DIR = SCRIPT_DIR / "idx-cache"

# Property types excluded from residential aggregations (mirrors current parser).
EXCLUDE_TYPES = {"Commercial", "Lots"}

# Small-sample threshold for YoY comparisons (Convention #21).
def _record_mls(r):
    """MLS number off a sold record, tolerant of field-name variants."""
    return str(r.get("MLSNumber") or r.get("mls") or r.get("ListingId") or "").strip()

# Small-sample threshold for YoY comparisons (Convention #21).

SMALL_SAMPLE_THRESHOLD = 5

# ── Small-market flag (Mike 2026-09-07) ─────────────────────────────────
# Months-of-supply on a handful of active listings is noise: Gambo read
# "Seller's Market · 2.5 months of supply" on 12 sales / 78 days on market,
# Fogo Island "Seller's Market" on 2 sales / 217 DOM. Mike's rule: withhold the
# market-type verdict below 15 sales year-to-date. Flagged HERE, once, so every
# consumer (site page, PDF, FB/IG card, newsletter, SMS route) reads one flag
# and none of them re-classifies. Early in the year (fewer than 3 complete
# months) the year-to-date count is meaningless for every market, so the
# trailing-12-month count stands in until March.
SMALL_MARKET_YTD_MIN = 15
SMALL_MARKET_MIN_MONTHS = 3



# ── Resale vs new construction (Mike 2026-09-07) ────────────────────────────
# Every surface said "residential resale" and the disclaimer said new homes are
# excluded, but nothing ever filtered them: in 2026 new builds were 26% of
# Paradise sales and 14% of Gander's, at a $517K median vs $346K resale. Rule
# (Mike's pick): a sale is NEW CONSTRUCTION when YearBuilt is within one year
# of the sale (spec homes closing the year after completion, pre-sales) OR the
# agent-typed YearBuiltDesc says New / Under Construction / To Be Built.
# Headline stats are computed on RESALE only; new builds get their own block
# (region_block["new_construction"]) so consumers can show them side by side.
NEW_CONSTRUCTION_DESC = {"new", "under construction", "to be built"}


def _is_new_construction(r, close_year=None):
    desc = str(r.get("YearBuiltDesc") or r.get("year_built_desc") or "").strip().lower()
    if desc in NEW_CONSTRUCTION_DESC:
        return True
    yb = _safe_int(r.get("YearBuilt") or r.get("year_built"))
    if not yb or yb < 1800:
        return False
    if close_year is None:
        cd = str(r.get("CloseDate") or r.get("close_date") or "")[:4]
        close_year = int(cd) if cd.isdigit() else datetime.now(timezone.utc).year
    return yb >= close_year - 1


def build_new_construction_block(new_records, *, resale_ytd_count, label, latest_close_date=None):
    """The new-construction segment for one region: the same YTD / complete-month /
    by-month shape as the headline block, computed on the new-build sales only,
    plus its share of all residential sales. Conv #74: an empty segment is an
    explicit zero, never an absent key."""
    if not new_records:
        return {"ytd": {"count": 0}, "ytd_complete": None, "yoy_complete": None, "by_year": {},
                "by_year_month": {}, "share_pct_ytd": 0.0 if resale_ytd_count else None,
                "ppsf": build_ppsf_block([], latest_close_date=latest_close_date),
                "rule": "YearBuilt within one year of the sale, or YearBuiltDesc New / Under Construction / To Be Built"}
    blk = build_region_aggregates(new_records, label=f"{label} (new construction)",
                                  latest_close_date=latest_close_date)
    keep = {k: blk.get(k) for k in ("ytd", "prior_ytd", "yoy", "ytd_complete", "prior_ytd_complete",
                                    "yoy_complete", "by_year", "by_year_month", "ytd_anchor_year",
                                    "ytd_complete_through_year", "ytd_complete_through_month")}
    n_new = int(((keep.get("ytd_complete") or keep.get("ytd") or {}).get("count")) or 0)
    total = n_new + int(resale_ytd_count or 0)
    keep["share_pct_ytd"] = round(100.0 * n_new / total, 1) if total else None
    keep["rule"] = "YearBuilt within one year of the sale, or YearBuiltDesc New / Under Construction / To Be Built"
    # New-build $/sq ft, Mike 2026-09-18: "we should have both what the new
    # construction price per foot is and what the resale price per foot is."
    # Same rolling-12-month window + tier system as the resale figure
    # (region_block["ppsf"]) so the two numbers are directly comparable, not
    # two different measurement periods that happen to look alike.
    keep["ppsf"] = build_ppsf_block(new_records, latest_close_date=latest_close_date)
    return keep


def _flag_small_market(block):
    """Set market_balance.small_market (+ a one-sentence reason) on a region block.
    Convention #74: no-op when the block has no market_balance at all."""
    mb = block.get("market_balance")
    if not mb:
        return
    ytd = block.get("ytd_complete") or block.get("ytd") or {}
    n = int(ytd.get("count") or 0)
    months_in = int(block.get("ytd_complete_through_month") or block.get("ytd_through_month") or 0)
    t12 = int(mb.get("trailing_12mo_sold") or 0)
    if months_in >= SMALL_MARKET_MIN_MONTHS:
        small, basis = n < SMALL_MARKET_YTD_MIN, f"{n} sales year-to-date"
    else:
        small, basis = t12 < SMALL_MARKET_YTD_MIN, f"{t12} sales in the last 12 months"
    mb["small_market"] = small
    mb["small_market_reason"] = (
        f"With only {basis}, months of supply is not a reliable read here — a couple of "
        f"listings coming or going swings it. Use the year-to-date price and "
        f"days-on-market figures, and read them as direction, not precision.") if small else ""

# ── Market-condition thresholds: ONE definition, emitted in the payload ──────
# Months of supply (NAR / Realtor.com): <5 seller's · 5-7 balanced · 7+ buyer's.
# These had drifted into three different sets across the tools — the aggregator
# said 5/7, build-agent-market.py printed "under 3 / 3-6 / 6+" beside a label
# computed here, and golden-letter-gen.py gated a seller's-market claim on <6.
# Consumers must render market_type_label / mos_thresholds, never re-classify.
MOS_SELLER_MAX = 5.0
MOS_BALANCED_MAX = 7.0

# Sales-to-new-listings ratio (CREA convention): <40% buyer's · 40-60 balanced
# · >60% seller's. Applied only in build_snlr.
SNLR_BUYER_MAX = 40.0
SNLR_SELLER_MIN = 60.0

# A month needs this many sales AND this many new listings before its ratio is
# published — Gander runs 15-40 sales/month and sub-regions hit single digits,
# where a ratio is arithmetic noise dressed up as a market signal.
SNLR_MIN_SALES = 5
SNLR_MIN_NEW_LISTINGS = 5

# How old the active-listings pull may be before flow measures derived from it
# (new listings this month) stop being published. Two days absorbs a single
# failed nightly; beyond that the count is a truncated month, not a late one.
FEED_STALE_DAYS = 2

# Days after a month ends before its new-listing count is frozen in the ledger.
# List dates do not lag the way close dates do (a listing is in the system the
# day it goes live), but late data entry happens; 5 days is the grace period.
NEW_LISTINGS_LOCK_GRACE_DAYS = 5

# Municipality typo fixes (mirrors current parser at MUNICIPALITY_TYPO_FIXES).
# Phase 4 Decision B = (b) — explicit typo fixes scale to <50 entries; comma-
# suffix handling per Convention #45 belongs in the dict for grep-ability.
# Add new entries here as variants surface in the IDX/VOW cache.
MUNICIPALITY_TYPO_FIXES = {
    "APPELTON": "APPLETON",
    # Comma-suffix variants observed in CityText 2026-05-07
    # (NLAR Matrix CityText is more variable than the legacy parser's
    # Municipality field — agents enter free-text city names that include
    # the regional anchor as a comma-suffix).
    "GANDER, NL":           "GANDER",
    "BUTT'S POND, GANDER":  "GANDER",
    # Add more entries as they surface; loud failure mode is "0 records in
    # municipality breakout" surfacing in the per-region rollup output.
}

# Subdistrict prefix-code regex (Phase 4 Decision A = α).
# NLAR Matrix sub-districts come in two formats coexisting in the same cache:
#   long-coded:  'WC147 - Corner Brook/ Mount Moriah/ Massey Drive', 'SJ01 - East'
#   short-label: 'Gander and Area', 'Lewisporte', 'Gander Loop'
# Active cache uses long-coded consistently; sold cache mixes both. The
# aggregator's REGION_CONFIG stores short-label subdistricts. To match
# records across both formats, we strip the prefix code at lookup time.
# Pattern: 2-3 uppercase letters + 2-3 digits + optional whitespace + dash
# + optional whitespace, anchored at start of string.
_SUBDISTRICT_PREFIX_RE = re.compile(r'^[A-Z]{2,3}\d{2,3}\s*-\s*')


def _strip_subdistrict_code(sub):
    """Strip NLAR Matrix prefix code from a sub-district name.

    Returns the post-strip suffix unchanged if no prefix matches (so
    short-label entries like 'Gander and Area' pass through verbatim).

    Examples:
        'WC147 - Corner Brook/ Mount Moriah/ Massey Drive'
            -> 'Corner Brook/ Mount Moriah/ Massey Drive'
        'SJ01 - East'           -> 'East'
        'Gander and Area'       -> 'Gander and Area'   (no prefix; unchanged)
        'Gander Loop'           -> 'Gander Loop'       (no prefix; unchanged)
    """
    if not sub:
        return ""
    return _SUBDISTRICT_PREFIX_RE.sub("", sub).strip()

# Region configuration — what subdistricts roll up where, and what
# municipality breakouts each region supports.
#
# This intentionally mirrors AREA_CONFIG in update-market-stats.py so the
# downstream `update-market-stats-from-cache.py` can ingest the same shape.
# Per Convention #15, when this changes, both files change in lockstep.
# Regions where build_market_balance()'s active-inventory count is known
# unreliable (2026-07-29 finding, Avalon "St. John's Metro" master config
# comment): these 7 St. John's neighbourhoods are distinguished from each
# other ONLY by subdistrict (SJ01-SJ09), but the active-listings feed
# (listings-projected.json) carries no subdistrict field at all -- only
# city_slug, and every one of them shares "st-johns". _make_scope_matcher
# tries city before subdistrict, so each neighbourhood's "active inventory"
# silently becomes ALL 300+ St. John's-proper active listings divided by
# that neighbourhood's own small sold rate -- e.g. Downtown showing 12+
# months of supply and "Buyer's Market" while genuinely selling in ~36 days
# inside a metro running at ~2.7 months. Not fixable by matcher-priority
# reordering alone; the data the fix would need (per-listing subdistrict on
# the active feed) doesn't exist yet. Suppressed at the source (2026-07-31)
# so every consumer of market_balance -- not just one table -- shows
# nothing instead of a wrong buyer's/seller's verdict for these 7. Sales
# count / price / DOM for these regions are unaffected (sourced from the
# region's own sold records, not this city-matching bug).
UNRELIABLE_MARKET_BALANCE_REGIONS = {
    "Downtown St. John's",
    "East End St. John's",
    "West End St. John's",
    "North End St. John's",
    "Galway St. John's",
    "Kenmount St. John's",
    "South St. John's",
}

REGION_CONFIG = {
    # Lab West (sites, D-1012-34): only the Labrador City + Wabush markets. Every other region Goose Bay carried is gone, so
    # live-aggregates.json holds exactly the numbers this site publishes. The feed's Subdistrict is "Labrador City / Wabush"
    # (checked against the 2026-10-12 feed: 191 sold rows); the two towns split on the municipality (CityText).
    "Labrador City / Wabush": {
        "label": "Labrador West",
        "subdistricts": ["Labrador City / Wabush"],
        "municipality_breakouts": {},
    },
    "Labrador City": {
        "label": "Labrador City",
        "subdistricts": ["Labrador City / Wabush"],
        "municipality_breakouts": {},
        "municipality_filter": {"LABRADOR CITY"},
    },
    "Wabush": {
        "label": "Wabush",
        "subdistricts": ["Labrador City / Wabush"],
        "municipality_breakouts": {},
        "municipality_filter": {"WABUSH"},
    },
}


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_municipality(raw):
    if not raw:
        return ""
    key = raw.strip().upper()
    return MUNICIPALITY_TYPO_FIXES.get(key, key)


def _safe_float(v):
    """Parse to float, return None if missing/invalid."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v):
    """Parse to int, return None if missing/invalid."""
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _close_year_month(record):
    """Extract (year, month) from CloseDate. Returns (None, None) if missing/invalid."""
    cd = record.get("CloseDate") or record.get("close_date")
    if not cd:
        return (None, None)
    # Matrix typically returns YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS
    try:
        return (int(cd[:4]), int(cd[5:7]))
    except (ValueError, TypeError, IndexError):
        return (None, None)


# ─────────────────────────────────────────────────────────────────
#  CORE AGGREGATION
# ─────────────────────────────────────────────────────────────────

def aggregate_records(records, *, label="<unnamed>"):
    """Compute aggregate stats for a list of sold records.

    Returns a dict with: count, avg_price, median_price, avg_dom, avg_sa,
    total_volume, at_100_plus.

    Defensive: skips records missing required fields (close_price, list_price,
    dom). Returns count=0 stats for empty input.
    """
    prices = []
    list_prices = []
    doms = []
    sa_ratios = []  # sale-to-ask ratio (close/list)
    at_100_plus = 0

    for r in records:
        cp = _safe_float(r.get("ClosePrice") or r.get("close_price"))
        lp = _safe_float(r.get("ListPrice") or r.get("list_price"))
        # DOM field: NLAR Matrix returns "DOM" (uppercase, no 's'); legacy
        # parsers used "DaysOnMarket" or lowercase "dom". Try all three so
        # this aggregator works against IDX/VOW cache + any legacy export.
        # Pre-2026-05-07 this only checked DaysOnMarket/dom and produced
        # avg_dom=null on every region. Convention #18 silent-degraded fix.
        dom = _safe_int(r.get("DOM") or r.get("DaysOnMarket") or r.get("dom"))

        if cp is None or cp <= 0:
            continue  # required field; skip silent-degraded record
        prices.append(cp)
        if lp is not None and lp > 0:
            list_prices.append(lp)
            ratio = cp / lp
            sa_ratios.append(ratio)
            if cp >= lp:
                at_100_plus += 1
        if dom is not None and dom >= 0:
            doms.append(dom)

    count = len(prices)
    if count == 0:
        return {
            "count": 0,
            "avg_price": None,
            "median_price": None,
            "avg_dom": None,
            "median_dom": None,
            "avg_sa": None,
            "total_volume": 0,
            "at_100_plus": 0,
            "label": label,
        }

    return {
        "count":         count,
        "avg_price":     round(statistics.mean(prices), 2),
        "median_price":  round(statistics.median(prices), 2),
        "avg_dom":       round(statistics.mean(doms), 1) if doms else None,
        "median_dom":    round(statistics.median(doms), 1) if doms else None,
        "avg_sa":        round(statistics.mean(sa_ratios) * 100, 2) if sa_ratios else None,
        "total_volume":  round(sum(prices), 2),
        "at_100_plus":   at_100_plus,
        "label":         label,
    }


def calc_yoy(current, prior):
    """Compute YoY% deltas between two aggregate dicts.

    Returns None for any metric where prior count < SMALL_SAMPLE_THRESHOLD
    (Convention #21). Returns dict of pct deltas + pts deltas (S/A in pts).
    """
    if prior.get("count", 0) < SMALL_SAMPLE_THRESHOLD:
        return {"small_sample": True}

    out = {"small_sample": False}

    if current.get("count") and prior.get("count"):
        out["count_pct"] = round(
            (current["count"] - prior["count"]) / prior["count"] * 100, 1
        )
    if current.get("avg_price") and prior.get("avg_price"):
        out["avg_price_pct"] = round(
            (current["avg_price"] - prior["avg_price"]) / prior["avg_price"] * 100, 1
        )
    if current.get("median_price") and prior.get("median_price"):
        out["median_price_pct"] = round(
            (current["median_price"] - prior["median_price"]) / prior["median_price"] * 100, 1
        )
    if current.get("avg_dom") and prior.get("avg_dom"):
        out["avg_dom_pct"] = round(
            (current["avg_dom"] - prior["avg_dom"]) / prior["avg_dom"] * 100, 1
        )
    if current.get("avg_sa") is not None and prior.get("avg_sa") is not None:
        out["avg_sa_pts"] = round(current["avg_sa"] - prior["avg_sa"], 1)

    return out


# ─────────────────────────────────────────────────────────────────
#  REGION-LEVEL ROLLUP
# ─────────────────────────────────────────────────────────────────

def filter_records_for_region(all_records, region_cfg):
    """Filter all_records to those matching a region's subdistrict + property type rules.

    Phase 4 Decision A = α: matches against BOTH the raw Subdistrict field
    AND the prefix-stripped form, so REGION_CONFIG using short-labels (e.g.
    'Gander and Area') matches both short-label cache records and any future
    long-coded NLAR Matrix records (e.g. 'GA147 - Gander and Area' if NLAR
    ever migrates short-label entries to coded form).
    """
    target_subs = set(region_cfg.get("subdistricts", []))
    excluded_ptypes = EXCLUDE_TYPES

    out = []
    for r in all_records:
        sub = r.get("Subdistrict") or r.get("subdistrict") or ""
        # Phase 4 Decision A = α: match against raw OR prefix-stripped form
        sub_stripped = _strip_subdistrict_code(sub)
        if sub not in target_subs and sub_stripped not in target_subs:
            continue
        ptype = r.get("PropertyType") or r.get("property_type") or ""
        if ptype in excluded_ptypes:
            continue
        out.append(r)
    return out


def filter_records_for_municipality(records, allowed_munis):
    """Sub-filter to a specific set of municipalities (e.g., Appleton + Glenwood).

    Phase 4 Decision B = (b): field-name lookup chain is
    Municipality | CityText | city_text | city. The IDX/VOW sold cache has
    NO `Municipality` field — data lives in `CityText` per smoke test
    2026-05-07. Pre-fix the function returned 0 records for every
    municipality breakout; post-fix Appleton & Glenwood populates with
    ~26 records over the 2yr window (verified against cache 2026-05-07).
    """
    norm_allowed = {m.upper() for m in allowed_munis}
    return [
        r for r in records
        if _normalize_municipality(
            r.get("Municipality") or r.get("CityText")
            or r.get("city_text") or r.get("city") or ""
        ) in norm_allowed
    ]


def build_region_aggregates(region_records, *, label, latest_close_date=None):
    """Build by_year + by_year_month aggregates for a region.

    latest_close_date (added 2026-07-31): the honest "sold data through"
    horizon computed once in build_full_dump from the real CloseDate max
    across the whole feed. Optional/default-None so every OTHER call site
    (municipality breakouts, etc.) keeps working unchanged -- only the main
    REGION_CONFIG call site passes it, which is the only one this function's
    ytd_complete/prior_ytd_complete/yoy_complete fields are built for today."""
    by_year = defaultdict(list)
    by_year_month = defaultdict(list)

    for r in region_records:
        y, m = _close_year_month(r)
        if y is None:
            continue
        by_year[y].append(r)
        if m is not None:
            by_year_month[f"{y}-{m:02d}"].append(r)

    result = {
        "by_year":       {str(y): aggregate_records(rs, label=f"{label} {y}")
                          for y, rs in sorted(by_year.items())},
        "by_year_month": {ym: aggregate_records(rs, label=f"{label} {ym}")
                          for ym, rs in sorted(by_year_month.items())},
    }

    # YTD: current year through last completed month.
    today = datetime.now(timezone.utc).date()
    last_completed_month = today.month - 1 if today.day < 15 else today.month
    if last_completed_month < 1:
        last_completed_month = 12
        anchor_year = today.year - 1
    else:
        anchor_year = today.year

    ytd_records = [
        r for r in region_records
        if (lambda y, m: y == anchor_year and m is not None and m <= last_completed_month)(*_close_year_month(r))
    ]
    prior_ytd_records = [
        r for r in region_records
        if (lambda y, m: y == anchor_year - 1 and m is not None and m <= last_completed_month)(*_close_year_month(r))
    ]

    ytd_agg = aggregate_records(ytd_records,
                                 label=f"{label} YTD {anchor_year} through {last_completed_month:02d}")
    prior_ytd_agg = aggregate_records(prior_ytd_records,
                                       label=f"{label} YTD {anchor_year - 1} through {last_completed_month:02d}")

    result["ytd"] = ytd_agg
    result["prior_ytd"] = prior_ytd_agg
    result["yoy"] = calc_yoy(ytd_agg, prior_ytd_agg)
    result["ytd_anchor_year"] = anchor_year
    result["ytd_through_month"] = last_completed_month

    # YTD-THROUGH-LAST-COMPLETE-MONTH (2026-07-31, ported from
    # realestategander-site). The ytd/prior_ytd above already attempt
    # "through last completed month" via last_completed_month -- a CALENDAR
    # heuristic (today.day < 15), not data-driven, wrong exactly when NLAR
    # is running behind (on the 31st it assumes that month is done even if
    # the real reported data only extends a few weeks in). This field uses
    # latest_close_date -- the honest "sold data through" horizon -- as the
    # completeness signal instead. Additive: existing ytd/prior_ytd/
    # ytd_through_month are untouched, so nothing else reading them is
    # disturbed.
    ytd_complete = prior_ytd_complete = yoy_complete = None
    ytd_complete_through_year = ytd_complete_through_month = None
    ytd_complete_through_date_iso = None
    if latest_close_date and len(str(latest_close_date)) >= 7:
        import calendar
        _lcd_y, _lcd_m = int(str(latest_close_date)[:4]), int(str(latest_close_date)[5:7])
        _complete_months = sorted(
            {k for k in by_year_month if (int(k[:4]), int(k[5:7])) < (_lcd_y, _lcd_m)},
            reverse=True,
        )
        if _complete_months:
            _ay, _am = int(_complete_months[0][:4]), int(_complete_months[0][5:7])
            _last_day = calendar.monthrange(_ay, _am)[1]
            ytd_complete_through_year = _ay
            ytd_complete_through_month = _am
            ytd_complete_through_date_iso = f"{_ay}-{_am:02d}-{_last_day:02d}"

            def _in_complete_window(r, yr, month_limit=_am):
                ry, rm = _close_year_month(r)
                return ry == yr and rm is not None and rm <= month_limit

            ytd_complete_records = [r for r in region_records if _in_complete_window(r, _ay)]
            prior_ytd_complete_records = [r for r in region_records if _in_complete_window(r, _ay - 1)]
            ytd_complete = aggregate_records(
                ytd_complete_records,
                label=f"{label} YTD {_ay} through {ytd_complete_through_date_iso}")
            prior_ytd_complete = aggregate_records(
                prior_ytd_complete_records,
                label=f"{label} YTD {_ay - 1} through {_ay - 1}-{_am:02d}-{_last_day:02d}")
            yoy_complete = calc_yoy(ytd_complete, prior_ytd_complete)

    result["ytd_complete"] = ytd_complete
    result["prior_ytd_complete"] = prior_ytd_complete
    result["yoy_complete"] = yoy_complete
    result["ytd_complete_through_year"] = ytd_complete_through_year
    result["ytd_complete_through_month"] = ytd_complete_through_month
    result["ytd_complete_through_date_iso"] = ytd_complete_through_date_iso

    return result



def _norm_sub(v):
    """Subdistrict, comparable across feeds.

    Drops "GA147 - " style prefix codes so the sold-cache subdistrict and the
    raw active-feed subdistrict compare cleanly."""
    s = str(v or "").strip()
    if " - " in s:
        s = s.split(" - ", 1)[1]
    return s.strip().lower()


def _ncity(r):
    """Normalised city name off any record shape."""
    c = str(r.get("CityText") or r.get("City") or r.get("city_text") or r.get("city") or "")
    return c.strip().upper().replace(", NL", "").strip()


def _region_scope(region_records):
    """(sub_set, city_set, slug_set) — a region's geographic identity, derived
    from its OWN sold records.

    Extracted from build_market_balance so every supply-side measure (active
    inventory, months of supply, new listings, sales-to-new-listings) covers the
    SAME towns. A numerator and denominator drawn from different geographies is
    the classic way to publish a confident, wrong ratio.

    Core cities are those with >=2 sales AND >=2% of the region's sales. The 2%
    floor drops cross-tagged outliers (e.g. a handful of Gambo sales filed under
    "Gander and Area") so inventory reflects the region's real towns — and so a
    municipality-filtered region (Gambo) matches only its own city."""
    sub_set = {s for s in (_norm_sub(r.get("Subdistrict") or r.get("subdistrict"))
                           for r in region_records) if s}
    ccount = {}
    for r in region_records:
        c = _ncity(r)
        if c:
            ccount[c] = ccount.get(c, 0) + 1
    _total_sold = sum(ccount.values()) or 1
    city_set = {c for c, n in ccount.items() if n >= 2 and n / _total_sold >= 0.02}
    slug_set = {c.lower().replace(" ", "-").replace("'", "") for c in city_set}
    return sub_set, city_set, slug_set


def _make_scope_matcher(sub_set, slug_set):
    """Closure testing whether a listing row falls inside a region's scope.

    City is the primary key (handles the municipality-filter case correctly):
    city_slug (projected feed) → else CityText (raw feed). Subdistrict is the
    last-resort fallback for feeds that carry no city at all."""
    def _matches(r):
        slug = str(r.get("city_slug") or "").strip().lower()
        if slug:
            return slug in slug_set
        cslug = _ncity(r).lower().replace(" ", "-").replace("'", "")
        if cslug:
            return cslug in slug_set
        sub = _norm_sub(r.get("Subdistrict") or r.get("subdistrict"))
        return bool(sub and sub in sub_set)
    return _matches


def _is_res_record(r):
    """Residential — excludes commercial and bare land, and rows with no type."""
    return str(r.get("PropertyType") or r.get("property_type") or "").strip().lower() \
        not in ("commercial", "lots", "")


def _list_month(r):
    """YYYY-MM the listing came to market, tolerant of field-name variants.
    Populated on 100% of both the sold cache and the active feed."""
    return str(r.get("list_date") or r.get("ListDate") or r.get("ListingContractDate")
               or r.get("OriginalEntryTimestamp") or "")[:7]


def _listing_status(r):
    return str(r.get("Status") or r.get("status") or r.get("LastStatus")
               or r.get("StandardStatus") or "").strip().lower()


def build_market_balance(region_records, listings, *, today=None):
    """Supply-side market balance for a region: active inventory, months of
    supply (absorption), new listings, and the buyer's-vs-seller's read.

    Scope-aligned: the active-inventory geography is derived from the region's
    OWN sold-city set (see _region_scope), so the months-of-supply numerator
    (active) and denominator (sold pace) cover the same towns. Reads the active
    feed (listings-projected.json shape: status, city_slug, list_date,
    property_type). Returns None if no city set / no feed.

    Months of supply = active inventory / (trailing-12-month residential sold / 12).
    Thresholds are the module constants MOS_SELLER_MAX / MOS_BALANCED_MAX and are
    emitted in the payload so consumers display them rather than re-deciding
    them — three different threshold sets had drifted into the tools otherwise."""
    if not region_records:
        return None
    if today is None:
        today = datetime.now(timezone.utc).date()
    cut_iso = (today - timedelta(days=365)).isoformat()
    cm = today.strftime("%Y-%m")

    sub_set, city_set, slug_set = _region_scope(region_records)
    if not slug_set and not sub_set:
        return None

    def _is_active(r):
        return _listing_status(r).startswith("active")

    _matches = _make_scope_matcher(sub_set, slug_set)

    # Resale-only on BOTH legs of months-of-supply (2026-09-07): the sold rate
    # already comes from the resale list, so active inventory must drop new
    # builds as well or the ratio silently inflates.
    active = [r for r in (listings or []) if _is_active(r) and _matches(r)
              and not _is_new_construction(r, close_year=today.year)]
    active_count = len(active)

    def _cd_iso(r):
        return str(r.get("CloseDate") or r.get("close_date") or "")[:10]

    t12 = [r for r in region_records if _is_res_record(r) and _cd_iso(r) and _cd_iso(r) >= cut_iso]
    rate = len(t12) / 12.0
    mos = round(active_count / rate, 1) if rate > 0 else None

    # NOTE: this counts new listings among rows that are STILL ACTIVE, so it
    # undercounts badly (anything listed this month that already went pending or
    # sold is invisible) and decays as the month ages. compute_new_listings_by_month
    # supersedes it; build_full_dump overwrites this key with that value. Kept
    # here only so build_market_balance remains correct when called standalone.
    new_listings = sum(1 for r in active if _list_month(r) == cm)

    if mos is None or active_count == 0:
        mtype = mtype_label = None
    elif mos < MOS_SELLER_MAX:
        mtype, mtype_label = "seller", "Seller's Market"
    elif mos < MOS_BALANCED_MAX:
        mtype, mtype_label = "balanced", "Balanced Market"
    else:
        mtype, mtype_label = "buyer", "Buyer's Market"

    return {
        "active_inventory":         active_count,
        "months_of_supply":         mos,
        "monthly_sold_rate":        round(rate, 1),
        "trailing_12mo_sold":       len(t12),
        "new_listings_month":       new_listings,
        "new_listings_month_label": today.strftime("%B"),
        "market_type":              mtype,
        "market_type_label":        mtype_label,
        "mos_thresholds":           {"seller_max": MOS_SELLER_MAX,
                                     "balanced_max": MOS_BALANCED_MAX},
        "scope_subdistricts":       sorted(sub_set),
        "scope_cities":             sorted(city_set),
    }


def _month_key(year, month):
    return f"{year:04d}-{month:02d}"


def _prev_month(year, month):
    """Calendar month before (year, month) — December/January rollover."""
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _recent_month_keys(today, months):
    """The `months` most recent calendar month keys, oldest first, ending with
    the month `today` falls in."""
    y, m = today.year, today.month
    keys = []
    for _ in range(months):
        keys.append(_month_key(y, m))
        y, m = _prev_month(y, m)
    return list(reversed(keys))


def compute_new_listings_by_month(region_records, listings, *, today=None, months=3):
    """New listings per calendar month for a region — the denominator of the
    sales-to-new-listings ratio.

    A listing that came to market in month M is visible in exactly one of three
    places today, so the count is the UNION of:
      1. sold rows listed in M (listed and already closed),
      2. active rows listed in M (listed and still for sale),
      3. pending rows listed in M — carried explicitly because the active feed's
         "Cond Pending - Under Contract" status does NOT start with "active",
         so build_market_balance's _is_active predicate drops all 398 of them.

    Deduped by MLS number: a listing can appear in both the active feed and the
    sold cache when a pull straddles its closing.

    WHY ONLY RECENT MONTHS: expired and cancelled listings leave both feeds
    entirely (the sold cache holds 5 Expired rows out of 12,707). So this union
    is near-complete for the current and immediately preceding months and decays
    silently for older ones — which is precisely why the results are frozen into
    a ledger as each month completes rather than recomputed forever."""
    if today is None:
        today = datetime.now(timezone.utc).date()
    sub_set, city_set, slug_set = _region_scope(region_records)
    if not slug_set and not sub_set:
        return {}
    _matches = _make_scope_matcher(sub_set, slug_set)
    wanted = set(_recent_month_keys(today, months))

    # month -> source -> set of MLS keys (sets dedupe within a source; the
    # union across sources dedupes at the end).
    seen = {k: {"sold": set(), "active": set(), "pending": set()} for k in wanted}

    for r in region_records:
        if not _is_res_record(r):
            continue
        lm = _list_month(r)
        if lm in wanted:
            seen[lm]["sold"].add(_record_mls(r) or id(r))

    for r in (listings or []):
        if not _is_res_record(r) or not _matches(r):
            continue
        lm = _list_month(r)
        if lm not in wanted:
            continue
        status = _listing_status(r)
        if status.startswith("active"):
            bucket = "active"
        elif status.startswith("cond pending") or status.startswith("pending"):
            bucket = "pending"
        else:
            continue
        seen[lm][bucket].add(_record_mls(r) or id(r))

    out = {}
    for k in sorted(wanted):
        b = seen[k]
        union = b["sold"] | b["active"] | b["pending"]
        out[k] = {
            "new_listings": len(union),
            "sources": {"sold": len(b["sold"]), "active": len(b["active"]),
                        "pending": len(b["pending"])},
            "method": "live-union",
        }
    return out


def _month_lock_date(month_key):
    """The date on which `month_key` becomes eligible to freeze, or None."""
    try:
        y, m = (int(x) for x in month_key.split("-")[:2])
    except (ValueError, AttributeError):
        return None
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return date(ny, nm, 1) + timedelta(days=NEW_LISTINGS_LOCK_GRACE_DAYS)


def _month_is_locked(month_key, today, feed_date=None):
    """True once `month_key` may be frozen permanently.

    TWO conditions, not one. The calendar must have passed the month's end plus
    grace, AND the active feed must itself be recent enough to have seen that
    whole window. Locking on the calendar alone would freeze an undercount
    forever the first time the listing pull was stale — and a frozen wrong
    number is worse than a missing one, because nothing later corrects it.
    (Observed 2026-07-28: the local feed was 25 days old.)"""
    lock_date = _month_lock_date(month_key)
    if lock_date is None or today < lock_date:
        return False
    if feed_date is not None and feed_date < lock_date:
        return False
    return True


def load_new_listings_ledger(path):
    """Load the ledger, or an empty one.

    Returns (ledger_dict, writable). writable is False when the file exists but
    could not be parsed — in that case the caller uses live values for this run
    and MUST NOT write, because overwriting an unreadable ledger would destroy
    however many months of accrued history it holds. A corrupt ledger is a
    recoverable situation; a truncated one is not."""
    p = Path(path)
    if not p.exists():
        return {"version": 1, "regions": {}}, True
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[aggregator] NEW-LISTINGS LEDGER: {p} exists but could not be "
              f"read ({exc}). Using live counts for this run and leaving the "
              f"file untouched so no history is lost. Fix or delete it.",
              file=sys.stderr)
        return {"version": 1, "regions": {}}, False
    if not isinstance(data, dict) or "regions" not in data:
        print(f"[aggregator] NEW-LISTINGS LEDGER: {p} has an unexpected shape "
              f"— using live counts and leaving it untouched.", file=sys.stderr)
        return {"version": 1, "regions": {}}, False
    data.setdefault("version", 1)
    data.setdefault("regions", {})
    return data, True


def merge_new_listings_ledger(ledger, region_name, computed, today, *, feed_date=None):
    """Fold this run's computed months into the ledger and return the region's
    merged month map.

    Two rules keep the series honest:
      * A LOCKED month is read-only. Its count was correct when the month was
        fresh; recomputing it later would only shrink it as expired listings
        drop out of the feeds.
      * An UNLOCKED month takes max(computed, stored). The active feed is a live
        pull — a transient NLAR 403 that returns few or no rows must not crater
        a month that was previously counted higher."""
    region = ledger.setdefault("regions", {}).setdefault(region_name, {})
    months = region.setdefault("months", {})

    for key, val in sorted(computed.items()):
        n = val.get("new_listings", 0)
        prev = months.get(key)
        if prev and prev.get("locked"):
            continue
        if prev:
            prev_n = prev.get("new_listings", 0)
            if n < prev_n:
                if prev_n and (prev_n - n) / prev_n > 0.10:
                    print(f"[aggregator] NEW-LISTINGS: {region_name} {key} "
                          f"computed {n} but ledger holds {prev_n} — feed may be "
                          f"short. Keeping the higher figure.", file=sys.stderr)
                n = prev_n
                val = dict(val, sources=prev.get("sources", val.get("sources")))
        entry = {
            "new_listings": n,
            "sources": val.get("sources", {}),
            "method": val.get("method", "live-union"),
        }
        if _month_is_locked(key, today, feed_date):
            entry["locked"] = True
            entry["locked_at"] = today.isoformat()
        else:
            entry["locked"] = False
            entry["as_of"] = today.isoformat()
            lock_date = _month_lock_date(key)
            if feed_date is not None and lock_date is not None \
                    and today >= lock_date > feed_date:
                entry["lock_deferred_stale_feed"] = True
                print(f"[aggregator] NEW-LISTINGS: {region_name} {key} is past "
                      f"its lock date but the active feed is from {feed_date} — "
                      f"leaving it unlocked so a stale count is never frozen.",
                      file=sys.stderr)
        months[key] = entry

    return months


def build_snlr(by_year_month, ledger_months, *, latest_close_date=None, today=None):
    """Sales-to-new-listings ratio: sales in a month / new listings in that month.

    The CREA measure of market balance, and a more responsive one than months of
    supply because it reads the current month's flow rather than a stock against
    a trailing-12-month pace.

    A month qualifies only when every leg is trustworthy:
      * SALES COMPLETE — the board must have reported past the month's end, the
        same test the page's spotlight guard applies. Closings are filed weeks
        late, so an unguarded ratio divides a partial numerator by a full
        denominator and manufactures a buyer's market that does not exist. This
        is the failure mode that matters most: it reads as a market call.
      * LISTINGS SETTLED — the month is locked in the ledger, or is recent enough
        that the live union is still near-complete.
      * BOTH SIDES ABOVE THE FLOOR — see SNLR_MIN_SALES / SNLR_MIN_NEW_LISTINGS.

    Returns None when nothing qualifies; callers render nothing rather than
    something hedged."""
    if not by_year_month or not ledger_months:
        return None
    if today is None:
        today = datetime.now(timezone.utc).date()

    def _sales_complete(key):
        if not latest_close_date:
            return False
        return str(latest_close_date)[:7] > key

    by_month = {}
    for key in sorted(ledger_months):
        bucket = by_year_month.get(key) or {}
        sales = bucket.get("count") or 0
        entry = ledger_months.get(key) or {}
        new_listings = entry.get("new_listings") or 0
        # LOCKED IS REQUIRED, not "locked or recent". Closings lag ~3 weeks, so
        # by the time a month's sales are complete it is always past its lock
        # date — which means the only unlocked months reaching this test are ones
        # the lock deliberately withheld (stale feed). Publishing those is the
        # exact failure the lock exists to prevent, so fail closed: a healthy
        # feed locks on schedule and the ratio appears; a stale one stays silent.
        eligible = (
            _sales_complete(key)
            and bool(entry.get("locked"))
            and sales >= SNLR_MIN_SALES
            and new_listings >= SNLR_MIN_NEW_LISTINGS
        )
        rec = {"sales": sales, "new_listings": new_listings, "eligible": eligible}
        if eligible:
            rec["ratio_pct"] = round(sales / new_listings * 100, 1)
            rec.update(_snlr_condition(rec["ratio_pct"]))
        by_month[key] = rec

    eligible_keys = [k for k in sorted(by_month) if by_month[k]["eligible"]]
    if not eligible_keys:
        return None

    latest_key = eligible_keys[-1]
    latest = dict(by_month[latest_key], month=latest_key)

    rolling = None
    # Only when the three most recent eligible months are also CONSECUTIVE —
    # averaging across a gap would silently span a month we deliberately withheld.
    if len(eligible_keys) >= 3:
        tail = eligible_keys[-3:]
        expected = []
        y, m = (int(x) for x in tail[-1].split("-")[:2])
        for _ in range(3):
            expected.append(_month_key(y, m))
            y, m = _prev_month(y, m)
        if list(reversed(expected)) == tail:
            s = sum(by_month[k]["sales"] for k in tail)
            n = sum(by_month[k]["new_listings"] for k in tail)
            if n:
                pct = round(s / n * 100, 1)
                rolling = {"months": tail, "sales": s, "new_listings": n,
                           "ratio_pct": pct, **_snlr_condition(pct)}

    # Year-over-year absorption (Mike 2026-09-07): the same ratio twelve months
    # earlier -- the latest month's year-ago twin, and the rolling window shifted
    # back a year -- ONLY when every year-ago month is itself eligible (ledger-
    # locked, sales complete, above the floors). The ledger began 2026-05, so
    # this stays None until it holds the year-ago months and then lights up on
    # its own; consumers render nothing for None (Conv #74), never a guess.
    def _year_ago(key):
        y, m = (int(x) for x in key.split("-")[:2])
        return _month_key(y - 1, m)
    prior_year = None
    pk = _year_ago(latest_key)
    if (by_month.get(pk) or {}).get("eligible"):
        prior_year = {"latest": dict(by_month[pk], month=pk)}
    if rolling:
        p_tail = [_year_ago(k) for k in rolling["months"]]
        if all((by_month.get(k) or {}).get("eligible") for k in p_tail):
            ps = sum(by_month[k]["sales"] for k in p_tail)
            pn = sum(by_month[k]["new_listings"] for k in p_tail)
            if pn:
                ppct = round(ps / pn * 100, 1)
                prior_year = prior_year or {}
                prior_year["rolling_3mo"] = {"months": p_tail, "sales": ps, "new_listings": pn,
                                             "ratio_pct": ppct, **_snlr_condition(ppct)}
    return {
        "latest": latest,
        "rolling_3mo": rolling,
        "prior_year": prior_year,
        "by_month": by_month,
        "thresholds": {"buyer_max": SNLR_BUYER_MAX, "seller_min": SNLR_SELLER_MIN},
    }


def _snlr_condition(pct):
    """CREA market-condition labels. The ONLY place a ratio becomes a verdict."""
    if pct < SNLR_BUYER_MAX:
        return {"condition": "buyer", "condition_label": "Buyer's Market"}
    if pct <= SNLR_SELLER_MIN:
        return {"condition": "balanced", "condition_label": "Balanced Market"}
    return {"condition": "seller", "condition_label": "Seller's Market"}

def build_dom_sa_buckets(region_records, *, today=None, max_weeks=13,
                         window_days=730, min_per_week=2, min_total=20):
    """Pricing-strategy curve: how sale-to-ask ratio erodes the longer a home
    sits on market. Buckets residential sales by week-on-market (DOM) over a
    trailing window and computes the average sale-to-ask % per week.

    The story this tells: homes that sell in the first week or two close at or
    near 100% of asking; homes that sit accumulate days-on-market and close
    further below asking -- overpricing actively reduces what a seller walks
    away with. This is the single most important seller-education chart.

    Sale-to-ask uses ClosePrice / LastListPrice (the last asking price the home
    actually sold against -- NOT ListPrice, which for sold records is often
    overwritten to equal ClosePrice). Falls back to OriginalListPrice then
    ListPrice. Outlier guard: ratio kept to [50, 130]%.

    Convention #74: returns None on thin data (< min_total qualifying sales or
    < 4 distinct populated weeks) so small/seasonal markets omit the section
    rather than publish a noisy curve."""
    if not region_records:
        return None
    if today is None:
        today = datetime.now(timezone.utc).date()
    cut_iso = (today - timedelta(days=window_days)).isoformat()

    def _is_res(r):
        return str(r.get("PropertyType") or r.get("property_type") or "").strip().lower() \
            not in ("commercial", "lots", "")

    def _cd_iso(r):
        return str(r.get("CloseDate") or r.get("close_date") or "")[:10]

    sums = {}   # week -> sum of sa%
    counts = {} # week -> n
    for r in region_records:
        if not _is_res(r):
            continue
        cd = _cd_iso(r)
        if not cd or cd < cut_iso:
            continue
        dom = _safe_int(r.get("DOM") or r.get("DaysOnMarket") or r.get("dom"))
        if dom is None or dom < 0:
            continue
        cp = _safe_float(r.get("ClosePrice") or r.get("close_price"))
        lp = (_safe_float(r.get("LastListPrice"))
              or _safe_float(r.get("OriginalListPrice"))
              or _safe_float(r.get("ListPrice") or r.get("list_price")))
        if not cp or cp <= 0 or not lp or lp <= 0:
            continue
        sa = cp / lp * 100.0
        if sa < 50 or sa > 130:
            continue  # data-quality outlier
        wk = dom // 7 + 1
        if wk > max_weeks:
            wk = max_weeks  # tail bucket: "13+ weeks"
        sums[wk] = sums.get(wk, 0.0) + sa
        counts[wk] = counts.get(wk, 0) + 1

    # Keep only weeks with enough sample to be credible.
    weeks = sorted(w for w in counts if counts[w] >= min_per_week)
    n_total = sum(counts[w] for w in weeks)
    if n_total < min_total or len(weeks) < 4:
        return None

    def _signal(v):
        # Neutral label from the row's own number (D-1008-42); one definition in _market_narration.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _market_narration import dom_sa_signal  # noqa: E402
        return dom_sa_signal(v)

    sa_vals = [round(sums[w] / counts[w], 2) for w in weeks]
    ns = [counts[w] for w in weeks]
    signals = [_signal(v) for v in sa_vals]
    labels = [("13+" if w == max_weeks else str(w)) for w in weeks]

    # "Fresh listing" ceiling = the peak of the first month (weeks 1-4). Week 1
    # alone is a thin/noisy bucket (quick distressed/underpriced deals pull it
    # down), so the honest comparison is early-market PEAK vs stale-market floor.
    early = [v for w, v in zip(weeks, sa_vals) if w <= 4]
    best_sa = max(early) if early else max(sa_vals)
    late = [v for w, v in zip(weeks, sa_vals) if w >= 6]
    worst_late = min(late) if late else min(sa_vals)
    drop_pts = round(best_sa - worst_late, 1)
    dollar_impact_400k = int(round((best_sa - worst_late) / 100.0 * 400000 / 1000.0)) * 1000

    return {
        "weeks":              weeks,
        "labels":             labels,
        "sa":                 sa_vals,
        "n":                  ns,
        "signals":            signals,
        "n_total":            n_total,
        "best_sa":            best_sa,
        "worst_late_sa":      worst_late,
        "drop_pts":           drop_pts,
        "dollar_impact_400k": dollar_impact_400k,
        "window_days":        window_days,
    }


PRICE_BAND_EDGES = [
    ("Under $200K",    0,       200000),
    ("$200K – $300K",  200000,  300000),
    ("$300K – $400K",  300000,  400000),
    ("$400K – $500K",  400000,  500000),
    ("$500K+",         500000,  None),
]


def _residential_closes_in_window(region_records, *, start_iso, end_iso):
    """Residential sold records with a CloseDate in [start_iso, end_iso).
    Same residential scope as build_dom_sa_buckets (Commercial/Lots excluded)."""
    out = []
    for r in region_records:
        pt = str(r.get("PropertyType") or r.get("property_type") or "").strip().lower()
        if pt in ("commercial", "lots", ""):
            continue
        cd = str(r.get("CloseDate") or r.get("close_date") or "")[:10]
        if not cd or cd < start_iso or cd >= end_iso:
            continue
        out.append(r)
    return out


def _last_complete_month_end(latest_close_date):
    """The last calendar day of the most recent month confirmed complete by
    latest_close_date (the honest "sold data through" date, NOT "today").
    Shared by build_price_bands/build_property_type_mix so their trailing-
    12-month windows anchor on the SAME boundary build_region_aggregates's
    ytd_complete does (2026-07-31, Mike: fix the mismatch between this
    day-window figure and the region's own month-anchored trailing-12 --
    both claimed "trailing 12 months" while disagreeing, 167 vs 201).
    Returns None when latest_close_date is absent/unparseable, letting
    callers fall back to the real calendar "today" unchanged."""
    if not latest_close_date:
        return None
    s = str(latest_close_date)
    try:
        y, m, d = int(s[:4]), int(s[5:7]), int(s[8:10])
    except (ValueError, IndexError):
        return None
    import calendar
    last_day = calendar.monthrange(y, m)[1]
    if d >= last_day:
        return date(y, m, last_day)
    if m == 1:
        y, m = y - 1, 12
    else:
        m -= 1
    return date(y, m, calendar.monthrange(y, m)[1])


def _month_aligned_trailing12(anchor_date, offset_months=0):
    """[start_iso, end_iso) for the 12 FULL CALENDAR MONTHS ending at
    anchor_date's own month, shifted `offset_months` months further back
    (0 = ending at anchor_date's month; 12 = the prior 12-month window,
    exactly one year earlier -- its end lands exactly on this window's
    start, so the two tile cleanly with no gap or overlap).

    Matches by_year_month's own bucket-sum exactly, unlike a raw day-count
    window (timedelta(days=365)), which doesn't align with calendar months
    (28-31 days each) and can silently straddle a month boundary
    asymmetrically between two different years. Caught live 2026-08-02 on
    Avalon's St. John's Metro region: THE LAST 12 MONTHS tile (by_year_month
    sum) read 2974 for the identical trailing-12 claim build_price_bands'
    OLD day-window read as 2969 -- a 5-record gap traced to June 30 landing
    inside the window in one year and outside it in the other. (An earlier
    hypothesis blamed a blank PropertyType filter; disproven by directly
    comparing all-types vs residential-only within the SAME day-window,
    which matched exactly -- the day/month misalignment was the whole gap.)
    """
    import calendar
    end_year, end_month = anchor_date.year, anchor_date.month - offset_months
    while end_month <= 0:
        end_month += 12
        end_year -= 1
    end_day = calendar.monthrange(end_year, end_month)[1]
    end_dt = date(end_year, end_month, end_day)
    end_iso = (end_dt + timedelta(days=1)).isoformat()
    start_year, start_month = end_year - 1, end_month + 1
    if start_month > 12:
        start_month -= 12
        start_year += 1
    start_iso = f"{start_year}-{start_month:02d}-01"
    return start_iso, end_iso


def build_price_bands(region_records, *, today=None, latest_close_date=None,
                      window_days=365, min_total=30):
    """Where the market's activity sits by price point — trailing-12-month
    residential closings bucketed into fixed price bands, with the preceding
    12 months alongside so the shift is visible.

    Monthly bands would be far too thin in a market this size (15-40 sales a
    month), so this is deliberately a 12-month window.

    latest_close_date (2026-07-31): anchors the window's END at the last
    COMPLETE month instead of "today", matching build_region_aggregates's
    ytd_complete -- otherwise this trailing-12 figure and THE LAST 12
    MONTHS tile (trailing_12mo, month-bucket-anchored) silently disagree
    on what "trailing 12 months" means. `today` stays available as an
    explicit override for tests/callers that want a specific date; it
    takes precedence whenever passed.

    Convention #74: returns None below min_total qualifying sales rather than
    publishing bands built on a handful of records."""
    if not region_records:
        return None
    _month_align = today is None and latest_close_date and window_days == 365
    if today is None:
        today = _last_complete_month_end(latest_close_date) or datetime.now(timezone.utc).date()
    if _month_align:
        cut_iso, end_iso = _month_aligned_trailing12(today, offset_months=0)
        prior_cut_iso, _ = _month_aligned_trailing12(today, offset_months=12)
    else:
        end_iso = today.isoformat()
        cut_iso = (today - timedelta(days=window_days)).isoformat()
        prior_cut_iso = (today - timedelta(days=window_days * 2)).isoformat()

    current = _residential_closes_in_window(region_records, start_iso=cut_iso, end_iso=end_iso)
    prior = _residential_closes_in_window(region_records, start_iso=prior_cut_iso, end_iso=cut_iso)

    def _bucket(records):
        buckets = {label: [] for label, _, _ in PRICE_BAND_EDGES}
        n = 0
        for r in records:
            cp = _safe_float(r.get("ClosePrice") or r.get("close_price"))
            if cp is None or cp <= 0:
                continue
            for label, lo, hi in PRICE_BAND_EDGES:
                if cp >= lo and (hi is None or cp < hi):
                    buckets[label].append(r)
                    n += 1
                    break
        return buckets, n

    cur_buckets, cur_n = _bucket(current)
    if cur_n < min_total:
        return None
    prior_buckets, prior_n = _bucket(prior)

    def _rows(buckets, n_total):
        rows = []
        for label, _, _ in PRICE_BAND_EDGES:
            recs = buckets[label]
            doms = [d for d in (_safe_int(r.get("DOM") or r.get("DaysOnMarket") or r.get("dom"))
                                for r in recs) if d is not None and d >= 0]
            rows.append({
                "label":      label,
                "count":      len(recs),
                "share_pct":  round(len(recs) / n_total * 100, 1) if n_total else 0.0,
                "median_dom": round(statistics.median(doms), 1) if doms else None,
            })
        return rows

    return {
        "window_days": window_days,
        "n_total":     cur_n,
        "bands":       _rows(cur_buckets, cur_n),
        "prior": {
            "n_total": prior_n,
            "bands":   _rows(prior_buckets, prior_n) if prior_n else [],
        },
    }


def _property_type_bucket(record):
    """Map a sold record to a coarse property-type bucket for the Segments
    view. Cache taxonomy (verified 2026-06-20): PropertyType Residential/Lots/
    Commercial/Farm; PropertySubType Single Family / 2-Apartment / Condominiums
    / Cottage-Rec / Multi Family / Mobile-Mini / Other. Commercial excluded
    (not residential scope); Lots -> Land."""
    pt = str(record.get("PropertyType") or record.get("property_type") or "").strip()
    if pt == "Commercial":
        return None
    if pt == "Lots":
        return "Land"
    pst = str(record.get("PropertySubType") or record.get("property_sub_type") or "").strip().lower()
    if "condo" in pst:
        return "Condo"
    if "apartment" in pst or "multi" in pst:
        return "Multi-Family"
    if "cottage" in pst or "rec" in pst:
        return "Cottage / Rec"
    if "mobile" in pst or "mini" in pst:
        return "Mobile"
    if "single" in pst:
        return "Single-Family"
    return "Other"  # Residential/Farm with unknown subtype


def build_property_type_mix(region_records, *, today=None, latest_close_date=None,
                            window_days=365, min_per_bucket=5):
    """What kind of homes are actually trading — trailing-12-month residential
    closings split by coarse property-type bucket. Reuses _property_type_bucket
    (the same taxonomy the agent Market Stats tab uses).

    latest_close_date (2026-07-31): same last-complete-month anchoring as
    build_price_bands, for the identical reason -- see that function's
    docstring.

    Buckets below min_per_bucket are dropped rather than published as a
    one-or-two-sale 'median' (Convention #21). Returns None if nothing clears
    the floor."""
    if not region_records:
        return None
    _month_align = today is None and latest_close_date and window_days == 365
    if today is None:
        today = _last_complete_month_end(latest_close_date) or datetime.now(timezone.utc).date()
    if _month_align:
        cut_iso, end_iso = _month_aligned_trailing12(today, offset_months=0)
    else:
        end_iso = today.isoformat()
        cut_iso = (today - timedelta(days=window_days)).isoformat()

    recent = _residential_closes_in_window(region_records, start_iso=cut_iso, end_iso=end_iso)
    if not recent:
        return None

    grouped = {}
    for r in recent:
        bucket = _property_type_bucket(r)
        if not bucket:
            continue
        grouped.setdefault(bucket, []).append(r)

    return _build_mix(recent, _property_type_bucket, window_days=window_days,
                      min_per_bucket=min_per_bucket, rows_key="types")


def _sqft(record):
    """Finished living area, when the listing agent filled it in. Only ~54% do,
    which is why price-per-square-foot is gated on per-bucket coverage rather
    than published as though every sale had it."""
    raw = str(record.get("TotalLivingAreaSqFt") or record.get("sqft") or "").strip()
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if 200 <= v <= 20000 else None


def _median(vals):
    return round(statistics.median(vals), 1) if vals else None


# Price-per-square-foot sample tiers (Mike, 2026-09-18). Floor area is recorded
# on roughly half of listings, so a figure is judged on how many sized sales it
# rests on, not on what share of the bucket recorded a size: the old 60%
# coverage gate hid the column on every Gander table. Consumers render the
# tier; they never re-derive it.
PPSF_OK_MIN = 10
PPSF_LIMITED_MIN = 5
PPSF_MIN, PPSF_MAX = 20.0, 2000.0   # same outlier guard as _ppsf_stats


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _ppsf_summary(recs):
    """Median sold $/sq ft for a record set, with the sample it rests on.

    tier: "ok" (>= PPSF_OK_MIN sized sales), "limited" (PPSF_LIMITED_MIN to
    PPSF_OK_MIN - 1: published, flagged) or "withheld" (fewer: every value
    None). The interquartile range is only emitted at "ok" -- the middle half
    of six sales is two houses."""
    pairs = []
    for x in recs:
        cp = _safe_float(x.get("ClosePrice") or x.get("close_price"))
        sf = _sqft(x)
        if not cp or cp <= 0 or not sf:
            continue
        v = cp / sf
        if PPSF_MIN <= v <= PPSF_MAX:
            pairs.append((v, sf))
    n = len(pairs)
    out = {"n_sales": len(recs), "n_sized": n, "median_ppsf": None,
           "median_sqft": None, "p25": None, "p75": None, "tier": "withheld"}
    if n < PPSF_LIMITED_MIN:
        return out
    vals = sorted(v for v, _ in pairs)
    out["median_ppsf"] = _median(vals)
    out["median_sqft"] = round(statistics.median([sf for _, sf in pairs]))
    out["tier"] = "ok" if n >= PPSF_OK_MIN else "limited"
    if out["tier"] == "ok":
        out["p25"] = round(_quantile(vals, 0.25), 1)
        out["p75"] = round(_quantile(vals, 0.75), 1)
    return out


def _trailing12_residential(region_records, latest_close_date):
    """Residential closings in the 12 full calendar months ending at the last
    complete month -- the same window build_property_type_mix uses, so every
    "last 12 months" figure on a page counts the same sales. Returns
    (records, start_iso, end_iso)."""
    anchor = _last_complete_month_end(latest_close_date)
    if anchor:
        start_iso, end_iso = _month_aligned_trailing12(anchor, offset_months=0)
    else:
        today = datetime.now(timezone.utc).date()
        start_iso, end_iso = (today - timedelta(days=365)).isoformat(), today.isoformat()
    return (_residential_closes_in_window(region_records or [], start_iso=start_iso,
                                          end_iso=end_iso), start_iso, end_iso)


def build_ppsf_block(region_records, *, latest_close_date=None):
    """Region-level price per square foot, trailing 12 months, plus the change
    against the 12 months before (only when BOTH windows reach the "ok" tier).
    Always returns a dict, so a consumer can tell "withheld" from "the
    aggregator never ran this" (Convention #190)."""
    recent, start_iso, end_iso = _trailing12_residential(region_records, latest_close_date)
    block = _ppsf_summary(recent)
    block["window_start"], block["window_end"] = start_iso, end_iso
    block["prior_median_ppsf"] = None
    block["yoy_pct"] = None
    anchor = _last_complete_month_end(latest_close_date)
    if anchor and block["tier"] == "ok":
        p_start, p_end = _month_aligned_trailing12(anchor, offset_months=12)
        prior = _ppsf_summary(_residential_closes_in_window(
            region_records or [], start_iso=p_start, end_iso=p_end))
        if prior["tier"] == "ok" and prior["median_ppsf"]:
            block["prior_median_ppsf"] = prior["median_ppsf"]
            block["yoy_pct"] = round(
                (block["median_ppsf"] - prior["median_ppsf"]) / prior["median_ppsf"] * 100, 1)
    return block



def _shift_ym(year, month, months_back):
    """(year, month) shifted `months_back` months earlier. Pure calendar
    arithmetic, no date object -- used to label each point of a rolling
    window series without re-deriving the month from a half-open end_iso."""
    total = year * 12 + (month - 1) - months_back
    return total // 12, total % 12 + 1


PPSF_TREND_MONTHS = 36
PPSF_TREND_MIN_POINTS = 6


def build_ppsf_trend(region_records, *, latest_close_date=None, months=PPSF_TREND_MONTHS):
    """Median $/sq ft, one point per month, each point a ROLLING trailing-12-
    month window ending that month -- the same window build_ppsf_block uses
    for its single latest figure, swept back `months` times. This smooths the
    month-to-month noise a raw monthly median would show (one expensive sale
    can swing a single month's figure hard in a market this size) while still
    tracking real movement, since each window only shares 11 of its 12 months
    with its neighbour.

    Each point carries its own tier (same PPSF_OK_MIN/LIMITED_MIN as every
    other $/sq ft figure on the site); a withheld point's median_ppsf is None
    so a chart draws a genuine gap instead of interpolating through missing
    data. The withheld PREFIX (the early months before this region had 5+
    sized sales trailing) is trimmed so the series opens on real data rather
    than a flat run of nothing; an INTERIOR gap is kept, because that is a
    real reporting hole a reader should see, not smooth over.

    Returns None under PPSF_TREND_MIN_POINTS non-withheld points (Convention
    #74/#21) -- a handful of scattered dots is not a trend."""
    anchor = _last_complete_month_end(latest_close_date) or datetime.now(timezone.utc).date()
    points = []
    for i in range(months - 1, -1, -1):
        y, m = _shift_ym(anchor.year, anchor.month, i)
        start_iso, end_iso = _month_aligned_trailing12(anchor, offset_months=i)
        recs = _residential_closes_in_window(region_records or [], start_iso=start_iso, end_iso=end_iso)
        ppsf = _ppsf_summary(recs)
        points.append({"month": f"{y}-{m:02d}", "tier": ppsf["tier"],
                       "median_ppsf": ppsf["median_ppsf"], "n_sized": ppsf["n_sized"]})
    first_real = next((i for i, pt in enumerate(points) if pt["tier"] != "withheld"), None)
    if first_real is None:
        return None
    points = points[first_real:]
    if sum(1 for pt in points if pt["tier"] != "withheld") < PPSF_TREND_MIN_POINTS:
        return None
    return {"months": len(points), "points": points}

SALE_OUTCOMES_MIN = 20
SPEED_BUCKETS = [("2 weeks or less", 0, 14), ("15 to 30 days", 15, 30),
                 ("31 to 60 days", 31, 60), ("Over 60 days", 61, None)]


def build_sale_outcomes(region_records, *, latest_close_date=None):
    """Two seller questions the averages hide, over the trailing 12 months:
    how FAST homes sell (share of sales by time to sell, with each group's
    sale-to-asking) and whether sellers GET their price (share sold over / at /
    under the last asking price, and how many cut their price first).

    Aggregates only -- no per-listing price leaves this function, so the
    ungated page stays inside the VOW rule. Sale-to-asking uses LastListPrice
    with the same fallbacks and [50, 130]% guard as build_dom_sa_buckets.
    Price cuts need BOTH OriginalListPrice and LastListPrice; when too few
    records carry both, that sub-block is None rather than a guess. Returns
    None under SALE_OUTCOMES_MIN qualifying sales (Convention #74)."""
    recent, start_iso, end_iso = _trailing12_residential(region_records, latest_close_date)
    rows = []
    for r in recent:
        dom = _safe_int(r.get("DOM") or r.get("DaysOnMarket") or r.get("dom"))
        cp = _safe_float(r.get("ClosePrice") or r.get("close_price"))
        last = _safe_float(r.get("LastListPrice"))
        orig = _safe_float(r.get("OriginalListPrice"))
        lp = last or orig or _safe_float(r.get("ListPrice") or r.get("list_price"))
        if dom is None or dom < 0 or not cp or cp <= 0 or not lp or lp <= 0:
            continue
        sa = cp / lp * 100.0
        if sa < 50 or sa > 130:
            continue
        rows.append({"dom": dom, "sa": sa, "orig": orig, "last": last})
    n = len(rows)
    if n < SALE_OUTCOMES_MIN:
        return None

    def pct(k, of=n):
        return round(k / of * 100, 1)

    speed = []
    for label, lo, hi in SPEED_BUCKETS:
        grp = [x for x in rows if x["dom"] >= lo and (hi is None or x["dom"] <= hi)]
        speed.append({"label": label, "count": len(grp), "share_pct": pct(len(grp)),
                      "avg_sa": (round(statistics.mean([x["sa"] for x in grp]), 1)
                                 if len(grp) >= PPSF_LIMITED_MIN else None)})

    over = sum(1 for x in rows if x["sa"] > 100.25)
    under = sum(1 for x in rows if x["sa"] < 99.75)
    asking = {"over_pct": pct(over), "at_pct": pct(n - over - under), "under_pct": pct(under)}

    cuts = None
    both = [x for x in rows if x["orig"] and x["last"]]
    if len(both) >= SALE_OUTCOMES_MIN:
        cut = [x for x in both if x["orig"] - x["last"] > 1]
        held = [x for x in both if x["orig"] - x["last"] <= 1]
        cuts = {"n": len(both), "cut_pct": pct(len(cut), len(both)),
                "median_cut": None, "extra_days": None}
        if len(cut) >= PPSF_LIMITED_MIN:
            cuts["median_cut"] = round(statistics.median([x["orig"] - x["last"] for x in cut]))
            if len(held) >= PPSF_LIMITED_MIN:
                cuts["extra_days"] = round(statistics.median([x["dom"] for x in cut])
                                           - statistics.median([x["dom"] for x in held]))
    return {"n": n, "window_start": start_iso, "window_end": end_iso,
            "speed": speed, "asking": asking, "price_cuts": cuts}


def _build_mix(recent, keyfn, *, window_days, min_per_bucket, rows_key):
    """Group closings by whatever `keyfn` returns and describe each bucket.

    Price per square foot is judged per bucket on its sized-sale count, not on
    a coverage share (see _ppsf_summary).

    Shared by every "what's selling" cut — property type, built form, bedroom
    count — so a new dimension is a key function, not another copy of this.

    Two honesty rules travel with it:
      * Buckets under min_per_bucket are dropped, not published as a median
        built on two houses (Convention #21).
      * `unclassified` is reported rather than quietly folded away: built form
        is blank on roughly a fifth of Gander sales, and a share computed as if
        those did not exist would overstate every bucket. Shares are explicitly
        of the CLASSIFIED total, and the page says so."""
    grouped = {}
    unclassified = 0
    for r in recent:
        bucket = keyfn(r)
        if not bucket:
            unclassified += 1
            continue
        grouped.setdefault(bucket, []).append(r)

    rows = []
    below_floor = 0
    for bucket, recs in grouped.items():
        if len(recs) < min_per_bucket:
            below_floor += len(recs)
            continue
        stats = aggregate_records(recs, label=bucket)
        if not stats["count"]:
            below_floor += len(recs)
            continue
        # Published at 10+ sized sales, flagged "limited" at 5-9, withheld
        # under 5. The count travels with the value so the page can say what
        # the figure is built on.
        ppsf = _ppsf_summary(recs)
        rows.append({
            "label":        bucket,
            "count":        stats["count"],
            "median_price": stats["median_price"],
            "avg_dom":      stats["avg_dom"],
            "avg_sa":       stats["avg_sa"],
            "median_beds":  _median([float(x["BedsTotal"]) for x in recs
                                     if str(x.get("BedsTotal") or "").strip()
                                     not in ("", "0")]),
            "median_ppsf":  ppsf["median_ppsf"],
            "ppsf_n":       ppsf["n_sized"],
            "ppsf_tier":    ppsf["tier"],      # ok | limited | withheld
            "median_sqft":  ppsf["median_sqft"],
            "ppsf_p25":     ppsf["p25"],
            "ppsf_p75":     ppsf["p75"],
        })
    if not rows:
        return None

    rows.sort(key=lambda x: x["count"], reverse=True)
    n_total = sum(r["count"] for r in rows)
    for r in rows:
        r["share_pct"] = round(r["count"] / n_total * 100, 1) if n_total else 0.0

    # These four reconcile exactly: considered = shown + unclassified + below_floor.
    # Kept separate because they mean different things to a reader — one is a
    # blank field, the other is a bucket too small to describe honestly.
    return {
        "window_days":  window_days,
        "n_total":      n_total,
        "unclassified": unclassified,
        "below_floor":  below_floor,
        "n_considered": len(recent),
        rows_key:       rows,
    }


# Built form, read off StyleOfDwelling — a comma-joined field that mixes
# attachment ("Detached", "Semi Detached") with form ("Bungalow", "2 Storey").
# Ordered longest-needle-first so "1.5 storey" is not swallowed by "storey".
_STYLE_FORMS = [
    ("1.5 storey", "1.5-Storey"), ("2.5 storey", "2.5-Storey"),
    ("2 storey", "2-Storey"), ("3 storey", "3-Storey"),
    ("split entry", "Split Entry"), ("split level", "Split Level"),
    ("multi level", "Multi-Level"), ("bungalow", "Bungalow"),
    ("mobile", "Mobile / Mini"), ("mini", "Mobile / Mini"),
]


def _style_bucket(record):
    """The home's built form, or None when the field is blank/unrecognised."""
    s = str(record.get("StyleOfDwelling") or "").strip().lower()
    if not s:
        return None
    for needle, label in _STYLE_FORMS:
        if needle in s:
            return label
    return None


def _beds_bucket(record):
    """Bedroom count, capped at a 5+ bucket. The most-asked consumer question
    on any market page, and BedsTotal is populated on ~96% of closings."""
    raw = str(record.get("BedsTotal") or "").strip()
    try:
        n = int(float(raw))
    except ValueError:
        return None
    if n <= 0:
        return None
    return "5+ Bedroom" if n >= 5 else f"{n} Bedroom"


def build_home_style_mix(region_records, *, today=None, window_days=365,
                         min_per_bucket=5):
    """Trailing-12-month closings split by built form (bungalow, split entry,
    two-storey...). The drill-down under "Single Family", which is 80%+ of
    Gander's market and tells a seller nothing on its own."""
    recent = _recent_residential(region_records, today, window_days)
    if not recent:
        return None
    return _build_mix(recent, _style_bucket, window_days=window_days,
                      min_per_bucket=min_per_bucket, rows_key="styles")


def build_bedroom_mix(region_records, *, today=None, window_days=365,
                      min_per_bucket=5):
    """Trailing-12-month closings split by bedroom count."""
    recent = _recent_residential(region_records, today, window_days)
    if not recent:
        return None
    return _build_mix(recent, _beds_bucket, window_days=window_days,
                      min_per_bucket=min_per_bucket, rows_key="beds")


def _recent_residential(region_records, today, window_days):
    if not region_records:
        return []
    if today is None:
        today = datetime.now(timezone.utc).date()
    return _residential_closes_in_window(
        region_records,
        start_iso=(today - timedelta(days=window_days)).isoformat(),
        end_iso=today.isoformat())


def build_notable_sales(region_records, cy, cm, *, limit=3):
    """A handful of REAL, named recent closings for the spotlight month —
    address, style, beds/baths, days-on-market. Gives the monthly video a
    human-interest beat instead of pure aggregates.

    VOW COMPLIANCE (Mike, 2026-07-18 policy): the ONLY field CREA Rule 5(k)
    requires gating is the sold price (ClosePrice) and anything derived from
    it (a sale-to-list ratio). This page is UNGATED, so ClosePrice must never
    appear here, directly or as a ratio — list price is fine, address is
    fine, DOM is fine. Every field below is deliberately drawn from that safe
    set; do not add ClosePrice or a computed sale-to-list % to this function.

    (cy, cm) should be the same last-fully-reported month the spotlight/
    summary sections use, so the callout can never describe a different
    month than the numbers above it. Freshest-first within the month.

    Returns [] when the month has no qualifying closings (Convention #74) —
    the page builder omits the whole section rather than showing nothing."""
    if not region_records:
        return []
    key = f"{cy}-{cm:02d}"
    month_sales = [r for r in region_records
                   if str(r.get("CloseDate") or "")[:7] == key
                   and str(r.get("PropertyType") or "").strip().lower()
                       not in ("commercial", "lots", "")]
    if not month_sales:
        return []
    month_sales.sort(key=lambda r: str(r.get("CloseDate") or ""), reverse=True)

    def _addr(r):
        street = " ".join(str(r.get(k) or "").strip()
                          for k in ("StreetNumber", "StreetName", "StreetSuffix")).strip()
        city = (r.get("CityText") or r.get("City") or "").strip()
        if street and city:
            return f"{street}, {city}"
        return street or city or "Address on request"

    def _style(r):
        return (str(r.get("StyleOfDwelling") or "").strip()
                or str(r.get("PropertySubType") or "").strip()
                or str(r.get("PropertyType") or "").strip()
                or "Home")

    out = []
    for r in month_sales[:limit]:
        list_price = _safe_float(r.get("LastListPrice") or r.get("ListPrice")
                                  or r.get("OriginalListPrice"))
        dom = _safe_int(r.get("DOM") or r.get("DaysOnMarket") or r.get("dom"))
        beds = _safe_int(r.get("BedsTotal") or r.get("BdrmAboveGrade"))
        baths_full = _safe_int(r.get("BathsFull")) or 0
        baths_half = _safe_int(r.get("BathsHalf")) or 0
        baths = (baths_full + baths_half * 0.5) or None
        out.append({
            "address":    _addr(r),
            "style":      _style(r),
            "beds":       beds,
            "baths":      baths,
            "dom":        dom,
            "list_price": list_price,
            "close_date": str(r.get("CloseDate") or "")[:10],
            # MLS number only — used by the page builder to look up a synced
            # hero photo (2026-07-30, Mike). Not a VOW-sensitive field on its
            # own; it's already public on every listing detail page/URL.
            "mls":        str(r.get("MLSNumber") or "").strip(),
        })
    return out


def build_full_dump(records, *, source_path, listings=None, ledger=None,
                    listings_fetched_at=None):
    """Build the full live-aggregates.json dump structure.

    `ledger` is the mutable new-listings ledger (see load_new_listings_ledger);
    it is updated in place as regions are processed and written once by the
    caller. Passing None disables the new-listings/SNLR work entirely, which is
    what happens when the ledger file could not be parsed."""
    # Determine year range present in cache (for trend chart bounds).
    years_seen = set()
    for r in records:
        y, _ = _close_year_month(r)
        if y is not None:
            years_seen.add(y)
    year_range = [min(years_seen), max(years_seen)] if years_seen else [None, None]

    # Data horizon: the most recent CloseDate present = the honest "sold data
    # through" date. NLAR posts closings weeks after the sale, so this trails
    # the pull date. Everything that compares a month against a finished one
    # gates on it — without it the page cannot tell a complete month from a
    # month that is still being filed.
    _today_iso = _now_iso()[:10]
    _close_iso = [str(r.get("CloseDate") or r.get("close_date") or "")[:10] for r in records]
    latest_close_date = max((d for d in _close_iso if len(d) == 10 and d <= _today_iso),
                            default=None)

    # Ledger clock + the active feed's own age. The feed date gates month
    # locking: a pull that predates a month's close cannot be trusted to have
    # counted that month's listings, and a frozen undercount never self-corrects.
    _ledger_today = datetime.now(timezone.utc).date()
    _feed_date = None
    if listings_fetched_at:
        try:
            _feed_date = date.fromisoformat(str(listings_fetched_at)[:10])
        except ValueError:
            _feed_date = None
    _feed_stale = (_feed_date is not None
                   and (_ledger_today - _feed_date).days > FEED_STALE_DAYS)
    if _feed_stale:
        print(f"[aggregator] NEW-LISTINGS: active feed is from {_feed_date} "
              f"({(_ledger_today - _feed_date).days} days old). Month locking is "
              f"deferred and the current month's new-listing count is WITHHELD "
              f"while it is stale — a partial pull would report a fraction of "
              f"the month as if it were the whole. Check the IDX active pull.",
              file=sys.stderr)

    out = {
        "fetched_at":          _now_iso(),
        "latest_close_date":   latest_close_date,   # honest "sold data through" horizon
        "source_cache_md5":    _md5(source_path) if source_path.exists() else None,
        "source_cache_count":  len(records),
        "year_range":          year_range,
        "regions":             {},
    }

    for region_name, cfg in REGION_CONFIG.items():
        region_records = filter_records_for_region(records, cfg)
        # Optional top-level municipality filter (used by Gambo which spans
        # multiple subdistricts — filter_records_for_region finds all records
        # in those subdistricts, then this narrows to the specific municipality).
        if cfg.get("municipality_filter"):
            region_records = filter_records_for_municipality(
                region_records, cfg["municipality_filter"]
            )
        # Municipality-level exclusion guard (2026-07-31) -- catches records
        # that matched this region's subdistrict but whose CityText names a
        # town that does NOT belong here (e.g., a Labrador City sale
        # mistagged with the HVGB subdistrict). Applied after subdistrict +
        # any narrowing filters, before this region's stats are ever built,
        # so the whole region (spotlight, price bands, SNLR, notable sales)
        # is protected -- not just the named-closings section.
        if cfg.get("exclude_municipalities"):
            _excl_munis = {m.upper() for m in cfg["exclude_municipalities"]}
            region_records = [
                r for r in region_records
                if _normalize_municipality(
                    r.get("Municipality") or r.get("CityText")
                    or r.get("city_text") or r.get("city") or ""
                ) not in _excl_munis
            ]
        if not region_records:
            # Some regions only apply to other sites (e.g., HVGB on goosebay
            # cache, not Gander cache). Empty is fine — record it for visibility.
            out["regions"][region_name] = {
                "label": cfg.get("label", region_name),
                "by_year": {},
                "by_year_month": {},
                "ytd": aggregate_records([], label=f"{cfg.get('label', region_name)} YTD"),
                "prior_ytd": aggregate_records([], label=f"{cfg.get('label', region_name)} prior YTD"),
                "yoy": {"small_sample": True},
                # ytd_complete family (2026-07-31) -- kept present-but-None so
                # every consumer of this shape can read it unconditionally,
                # whether or not the region has any records at all.
                "ytd_complete": None,
                "prior_ytd_complete": None,
                "yoy_complete": None,
                "ytd_complete_through_year": None,
                "ytd_complete_through_month": None,
                "ytd_complete_through_date_iso": None,
                "by_municipality": {},
                "_note": "No records matched this region in source cache (correct for cross-site filtering)",
            }
            continue

        # Headline = RESALE ONLY (Mike 2026-09-07); new builds are aggregated
        # separately below and every later section reads the resale list.
        new_records = [r for r in region_records if _is_new_construction(r)]
        region_records = [r for r in region_records if not _is_new_construction(r)]
        region_block = build_region_aggregates(region_records,
                                                label=cfg.get("label", region_name),
                                                latest_close_date=latest_close_date)
        region_block["label"] = cfg.get("label", region_name)
        region_block["new_construction"] = build_new_construction_block(
            new_records, label=cfg.get("label", region_name), latest_close_date=latest_close_date,
            resale_ytd_count=((region_block.get("ytd_complete") or region_block.get("ytd") or {}).get("count") or 0))
        region_block["market_balance"] = build_market_balance(region_records, listings)
        if region_name in UNRELIABLE_MARKET_BALANCE_REGIONS:
            region_block["market_balance"] = None
            # Emitted so a consumer can SAY why the gauge is missing instead of
            # dropping the section silently (2026-09-07; consumers render, never
            # re-classify -- the reason text lives here, once).
            region_block["market_balance_withheld_reason"] = (
                "Active-listing counts are only reliable city-wide, so a neighbourhood "
                "months-of-supply figure would mislead. For the buyer's-vs-seller's read, "
                "see the St. John's Metro page; the sold-side numbers on this page "
                "(price, days on market, sale-to-list) are this neighbourhood's own.")
        _flag_small_market(region_block)
        region_block["dom_sa"] = build_dom_sa_buckets(region_records)
        # Consumer market-stats page sections. All None on thin data — the
        # generator omits the section rather than publishing noise, which is the
        # expected outcome for the smaller Labrador markets.
        region_block["price_bands"] = build_price_bands(
            region_records, latest_close_date=latest_close_date)
        region_block["property_type_mix"] = build_property_type_mix(
            region_records, latest_close_date=latest_close_date)
        region_block["home_style_mix"] = build_home_style_mix(region_records)
        region_block["bedroom_mix"] = build_bedroom_mix(region_records)
        # Region-level $/sq ft (feeds the community comparison table) and the
        # speed / asking-price outcome shares.
        region_block["ppsf"] = build_ppsf_block(
            region_records, latest_close_date=latest_close_date)
        region_block["ppsf_trend"] = build_ppsf_trend(
            region_records, latest_close_date=latest_close_date)
        region_block["sale_outcomes"] = build_sale_outcomes(
            region_records, latest_close_date=latest_close_date)
        # A few named recent closings for the spotlight month (2026-07-30).
        # Same "last completed calendar month" the page builder's own
        # _last_completed_month resolves — computed identically here (pure
        # date arithmetic, no shared state needed) so the two can never name
        # a different month for the same nightly run.
        #
        # EXCLUDE this region's own municipality_breakouts (2026-07-31, Mike:
        # "Appleton is not Gander, there should not be an Appleton sale showing
        # up on the Gander tracker report" — Convention #15 port; the fix is
        # generic and applies to whichever of THIS site's own regions has a
        # real municipality_breakouts entry, not just the Gander example).
        # region_records legitimately includes breakout towns for region-wide
        # STATS (spotlight, price bands, property mix, etc.) — that rollup is
        # correct. But this section's own copy promises named closings "in
        # {label}", so a breakout-town address under that headline is a real
        # mismatch, not a stats question.
        _breakout_towns = {
            m.upper() for muni_set in cfg.get("municipality_breakouts", {}).values()
            for m in muni_set
        }
        _notable_records = region_records
        if _breakout_towns:
            _notable_records = [
                r for r in region_records
                if _normalize_municipality(
                    r.get("Municipality") or r.get("CityText")
                    or r.get("city_text") or r.get("city") or ""
                ) not in _breakout_towns
            ]
        # Walk back through this region's OWN by_year_month buckets to the
        # newest one strictly before latest_close_date's month -- the same
        # rule build-market-stats-page.py's _spotlight_context uses to pick
        # the spotlight month (Mike 2026-08-03). A calendar "previous month"
        # pick here disagreed with that page whenever a NEWER month was
        # already fully reported by build time.
        _nc_bym = region_block.get("by_year_month") or {}
        _nc_key = None
        if latest_close_date and len(str(latest_close_date)) >= 7:
            _lcd_y = int(str(latest_close_date)[:4])
            _lcd_m = int(str(latest_close_date)[5:7])
            _nc_candidates = sorted(
                (k for k, v in _nc_bym.items() if (v or {}).get("count")
                 and (int(k[:4]), int(k[5:7])) < (_lcd_y, _lcd_m)),
                reverse=True)
            if _nc_candidates:
                _nc_key = _nc_candidates[0]
        if _nc_key is not None:
            _nc_y, _nc_m = int(_nc_key[:4]), int(_nc_key[5:7])
        else:
            _nc_y, _nc_m = (_ledger_today.year, _ledger_today.month)
            _nc_y, _nc_m = (_nc_y - 1, 12) if _nc_m == 1 else (_nc_y, _nc_m - 1)
        region_block["notable_sales"] = build_notable_sales(_notable_records, _nc_y, _nc_m)

        # New listings per month + the sales-to-new-listings ratio. The ledger
        # is the persistence layer: counts are frozen as each month completes,
        # because expired/cancelled listings leave the feeds and an
        # always-recomputed series would shrink retroactively.
        region_block["snlr"] = None
        if ledger is not None and listings:
            computed = compute_new_listings_by_month(
                region_records, listings, today=_ledger_today, months=3)
            if computed:
                months = merge_new_listings_ledger(
                    ledger, region_name, computed, _ledger_today,
                    feed_date=_feed_date)
                region_block["snlr"] = build_snlr(
                    region_block.get("by_year_month") or {}, months,
                    latest_close_date=latest_close_date, today=_ledger_today)
                # Replace the still-active-only undercount with the real union
                # for the current month (see build_market_balance's note).
                mb = region_block.get("market_balance")
                cur_key = _month_key(_ledger_today.year, _ledger_today.month)
                if mb and cur_key in computed:
                    mb["new_listings_month"] = computed[cur_key]["new_listings"]
                    mb["new_listings_month_partial"] = True
                    # A stale pull truncates a flow measure rather than merely
                    # aging it, so it is withheld outright and the page shows a
                    # dash. Inventory is a stock and degrades gracefully.
                    if _feed_stale:
                        mb["new_listings_month"] = None
                        mb["new_listings_month_stale"] = True
                    if _feed_date is not None:
                        mb["listings_feed_date"] = _feed_date.isoformat()

        # Municipality breakouts (Appleton & Glenwood, Gambo, etc.)
        muni_blocks = {}
        for muni_label, allowed_munis in cfg.get("municipality_breakouts", {}).items():
            muni_records = filter_records_for_municipality(region_records, allowed_munis)
            muni_block = build_region_aggregates(muni_records, label=muni_label)
            muni_block["label"] = muni_label
            muni_block["municipality_filter"] = sorted(allowed_munis)
            muni_block["market_balance"] = build_market_balance(muni_records, listings)
            muni_block["dom_sa"] = build_dom_sa_buckets(muni_records)
            muni_block["price_bands"] = build_price_bands(muni_records)
            muni_block["property_type_mix"] = build_property_type_mix(muni_records)
            muni_block["home_style_mix"] = build_home_style_mix(muni_records)
            muni_block["bedroom_mix"] = build_bedroom_mix(muni_records)
            # Breakout towns appear as rows in the community table too.
            muni_block["ppsf"] = build_ppsf_block(
                muni_records, latest_close_date=latest_close_date)
            muni_block["ppsf_trend"] = build_ppsf_trend(
                muni_records, latest_close_date=latest_close_date)
            muni_block["sale_outcomes"] = build_sale_outcomes(
                muni_records, latest_close_date=latest_close_date)
            muni_block["notable_sales"] = build_notable_sales(muni_records, _nc_y, _nc_m)
            # SNLR is region-level in v1: a breakout's monthly sales sit far
            # below SNLR_MIN_SALES, so the ratio would be withheld anyway.
            muni_block["snlr"] = None
            muni_blocks[muni_label] = muni_block
        region_block["by_municipality"] = muni_blocks

        out["regions"][region_name] = region_block

        # Hoist municipality breakouts as top-level region keys so the
        # generator's region_key lookup resolves directly. Convention #74.
        for muni_label, muni_block in muni_blocks.items():
            out["regions"][muni_label] = muni_block

    return out


# ─────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
#  Per-agent listing-detail widget (Strategic Vision Rec #2, Avalon)
#  Convention #15 port from realestategander-site/tools/idx-stats-aggregator.py
#  (lines 472-845 canonical). Ported 2026-05-22 morning.
#
#  Avalon-specific roster (Mike's 2026-05-22 sign-off):
#    - Team label: "Turner Realty Team" (network brand)
#    - Per-agent copy: "across the Avalon Peninsula"
#    - Threshold: 5 sales (Convention #21 small-sample discipline)
#
#  Chris Morrison is the only Turner agent on Avalon today (just relicensed
#  2026-05). Widget will show empty until Chris closes 5+ on Avalon. Team-
#  level stats roll up any sale by a Turner-team agent in Avalon scope.
# ─────────────────────────────────────────────────────────────────

# Agent registries loaded from the canonical tools/agent_roster.json via load_registries()
# (Convention #148/#174 — same roster the generator uses; no separate hardcoded copy).
# TURNER_AGENTS (membership) derives from TEAM_BY_AGENT's keys, upper-cased for the
# case-insensitive feed-name match.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from agent_roster_loader import load_registries
_card, _aliases, TEAM_BY_AGENT, _slug = load_registries()
TURNER_AGENTS = {name.upper() for name in TEAM_BY_AGENT}


def _is_turner_agent(name):
    """Case-insensitive membership check against Turner Realty roster."""
    if not name:
        return False
    return str(name).strip().upper() in TURNER_AGENTS


def _normalize_agent_name(name):
    """Title-case agent name for grouping consistency. Convention #77 —
    feed emits same agent under two casings; title-case-normalize so the
    aggregator doesn't split a single agent into 2 buckets."""
    if not name:
        return ""
    return str(name).strip().title()


_WIDGET_CITY_SLUG_STRIP = re.compile(r"['’]")
_WIDGET_CITY_SLUG_NONALNUM = re.compile(r"[^a-z0-9]+")
_WIDGET_CITY_SLUG_DASHES = re.compile(r"-+")


def _city_slug_widget(city):
    """Slugify city for widget dict keys. 'St. John\\'s' → 'st-johns',
    'Conception Bay South' → 'conception-bay-south'. Empty → ''."""
    if not city:
        return ""
    s = str(city).strip().lower()
    s = _WIDGET_CITY_SLUG_STRIP.sub("", s)
    s = _WIDGET_CITY_SLUG_NONALNUM.sub("-", s)
    s = _WIDGET_CITY_SLUG_DASHES.sub("-", s).strip("-")
    return s


def _widget_bucket_stats(records):
    """Compute count + median price + median DOM + median sold-to-list for
    a bucket of sold records. Returns None for any metric missing across
    the bucket — renderer handles by showing '—'."""
    prices = []
    doms = []
    ratios = []
    for r in records:
        cp = _safe_float(r.get("ClosePrice"))
        if cp:
            prices.append(cp)
        d = _safe_int(r.get("DOM"))
        if d is not None and d >= 0:
            doms.append(d)
        olp = _safe_float(r.get("OriginalListPrice")) or _safe_float(r.get("LastListPrice"))
        if cp and olp and olp > 0:
            ratios.append(cp / olp)
    return {
        "n": len(records),
        "median_price": int(statistics.median(prices)) if prices else None,
        "median_dom": int(statistics.median(doms)) if doms else None,
        "median_sold_to_list": round(statistics.median(ratios), 4) if ratios else None,
    }


# Avalon scope filter — fleet sold cache contains 12K+ rows fleet-wide;
# widget aggregates must scope to Avalon-jurisdictional sales only so the
# widget on Avalon listings doesn't show "Turner sold 121 homes" when 0 of
# those were on the Avalon. Mirrors POSTAL_PREFIXES from
# tools/idx-project-to-ddf-shape.py: A1A-A1Z (excluding A1V Gander) + A0A/A0B.
_AVALON_SCOPE_POSTAL_PREFIXES = frozenset((
    "A1A", "A1B", "A1C", "A1E", "A1G", "A1H", "A1K",
    "A1L", "A1M", "A1N", "A1S", "A1W", "A1X", "A1Y", "A1Z",
    "A0A", "A0B",
))
_AVALON_SCOPE_DROP_PREFIXES = frozenset(("A1V",))  # Gander — belt-and-braces


def _record_in_avalon_scope(record):
    """Filter sold record to Avalon Peninsula scope via PostalCode prefix.
    Same shape as in_scope() in idx-project-to-ddf-shape.py. No-postal rows
    fall back to permissive (CityText alone is ambiguous for outport towns)."""
    postal = (record.get("PostalCode") or "").strip().upper().replace(" ", "")
    if len(postal) >= 3:
        prefix = postal[:3]
        if prefix in _AVALON_SCOPE_DROP_PREFIXES:
            return False
        return prefix in _AVALON_SCOPE_POSTAL_PREFIXES
    return False  # No postal → exclude (widget needs city anyway)


def build_per_agent_widget_stats(records, *, window_months=24,
                                  n_city_threshold=5, n_region_threshold=5):
    """Per-agent + per-team sales aggregates for the listing-detail widget.

    Mike's 2026-05-22 decisions:
      - n_city_threshold = 5 (Convention #21 small-sample discipline)
      - n_region_threshold = 5 (same — Avalon Turner volume is thin until
        Chris ramps up; matching thresholds keeps widget logic uniform)

    Avalon-specific note: until Chris closes deals, by_agent will likely
    be empty for him. by_team["Turner Realty Team"] aggregates any
    Turner-roster sale in Avalon scope (cross-fleet agents occasionally
    close Avalon deals). Convention #74 fail-safe: empty stats → renderer
    skips section cleanly.

    Scope filter — records pre-filtered to Avalon scope via
    _record_in_avalon_scope(). The fleet sold cache contains 12K+ rows
    fleet-wide; we filter down to Avalon-jurisdictional ones so the
    widget on Avalon listings doesn't surface Gander/HVGB sales.

    Returns the shape consumed by build_per_agent_widget_section() in
    ddf-generate-pages.py.
    """
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_months * 30)

    # Pre-filter to Avalon scope
    records = [r for r in records if _record_in_avalon_scope(r)]

    by_agent_city = defaultdict(list)
    by_agent_all = defaultdict(list)
    by_team_city = defaultdict(list)
    by_team_all = defaultdict(list)

    for r in records:
        cd = r.get("CloseDate")
        if not cd:
            continue
        try:
            if "T" in str(cd):
                cd_dt = datetime.fromisoformat(str(cd).replace("Z", "+00:00"))
            else:
                cd_dt = datetime.fromisoformat(str(cd) + "T00:00:00+00:00")
        except (ValueError, AttributeError):
            continue
        if cd_dt < cutoff:
            continue

        raw_agent = r.get("ListAgentFullName") or ""
        agent = _normalize_agent_name(raw_agent)
        if not agent:
            continue
        if agent.upper() not in TURNER_AGENTS:
            continue

        city = r.get("CityText") or r.get("City") or ""
        city_slug = _city_slug_widget(city)
        if not city_slug:
            continue

        by_agent_city[(agent, city_slug)].append(r)
        by_agent_all[agent].append(r)

        team = TEAM_BY_AGENT.get(agent)
        if team:
            by_team_city[(team, city_slug)].append(r)
            by_team_all[team].append(r)

    by_agent = {}
    for agent, all_records in by_agent_all.items():
        city_stats = {}
        for (a, cs), rs in by_agent_city.items():
            if a == agent and len(rs) >= n_city_threshold:
                city_stats[cs] = _widget_bucket_stats(rs)
        region_stats = (_widget_bucket_stats(all_records)
                        if len(all_records) >= n_region_threshold else None)
        by_agent[agent] = {
            "team": TEAM_BY_AGENT.get(agent),
            "total_in_window": len(all_records),
            "city_stats": city_stats,
            "region_stats": region_stats,
        }

    by_team = {}
    for team, all_records in by_team_all.items():
        city_stats = {}
        for (t, cs), rs in by_team_city.items():
            if t == team and len(rs) >= n_city_threshold:
                city_stats[cs] = _widget_bucket_stats(rs)
        region_stats = (_widget_bucket_stats(all_records)
                        if len(all_records) >= n_region_threshold else None)
        members = sorted(a for a, t in TEAM_BY_AGENT.items() if t == team)
        by_team[team] = {
            "agent_members": members,
            "total_in_window": len(all_records),
            "city_stats": city_stats,
            "region_stats": region_stats,
        }

    return {
        "fetched_at": _now_iso(),
        "window_months": window_months,
        "region_label": "Avalon Peninsula",
        "thresholds": {
            "n_city": n_city_threshold,
            "n_region": n_region_threshold,
        },
        "by_agent": by_agent,
        "by_team": by_team,
    }


# ── Sold prices never leave this script (sites, D-1021-12) ────────────────────────────────────────────────────────
# The aggregates are committed to a PUBLIC repo and feed public pages, and the sold price is VOW data: Lab West shows
# counts and days on market only. Everything computed from ClosePrice (averages, medians, volume, sale-to-list, price
# bands, price per square foot, notable sales) is dropped from the output; the totals are still computed upstream, so a
# future signed-in surface can add them back here, deliberately.
_SOLD_SECTIONS = {"dom_sa", "price_bands", "property_type_mix", "home_style_mix", "bedroom_mix", "ppsf", "ppsf_trend",
                  "sale_outcomes", "notable_sales", "snlr"}
_SOLD_KEY_RE = re.compile(r"price|volume|ppsf|(^|_)sa($|_)|at_100|dollar|sale_to|ratio", re.I)


def strip_sold_prices(node):
    """Return a copy of the aggregates with every sold-price-derived key removed (counts and days on market stay)."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in _SOLD_SECTIONS or _SOLD_KEY_RE.search(str(k)):
                continue
            out[k] = strip_sold_prices(v)
        return out
    if isinstance(node, list):
        return [strip_sold_prices(v) for v in node]
    return node


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("--source", default=str(CACHE_DIR / "sold-listings-full.json"),
                    help="Source sold-listings cache (default: tools/idx-cache/sold-listings-full.json)")
    ap.add_argument("--new-listings-ledger",
                    default=str(CACHE_DIR / "new-listings-ledger.json"),
                    help="Persisted per-month new-listing counts. Frozen once a "
                         "month completes, because expired/cancelled listings "
                         "leave the feeds and a recomputed series would shrink "
                         "retroactively (default: tools/idx-cache/new-listings-ledger.json)")
    ap.add_argument("--out", default=str(CACHE_DIR / "live-aggregates.json"),
                    help="Output aggregates JSON (default: tools/idx-cache/live-aggregates.json)")
    ap.add_argument("--per-agent-out", default=str(CACHE_DIR / "per-agent-widget-stats.json"),
                    help="Output per-agent widget stats JSON (default: tools/idx-cache/per-agent-widget-stats.json)")
    ap.add_argument("--region",
                    help="Limit to one region (debug). Example: 'Gander and Area'")
    ap.add_argument("--json", action="store_true",
                    help="Print full JSON dump to stdout in addition to writing to --out.")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="Verbose progress logging.")
    args = ap.parse_args(argv)

    source = Path(args.source)
    out = Path(args.out)

    if not source.exists():
        print(f"ERROR: source cache not found: {source}", file=sys.stderr)
        print(f"  Run: python3 tools/idx-ingest.py --pull sold --backfill", file=sys.stderr)
        return 2

    if args.verbose:
        print(f"[aggregator] loading {source} ({source.stat().st_size:,} bytes)",
              file=sys.stderr)

    with open(source, encoding="utf-8") as f:
        cache_data = json.load(f)

    # Cache file shape: {fetched_at, count, rows: [...]}
    records = cache_data.get("rows", cache_data) if isinstance(cache_data, dict) else cache_data
    if not isinstance(records, list):
        print(f"ERROR: source cache rows are not a list", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"[aggregator] {len(records)} records loaded", file=sys.stderr)

    if args.region:
        # Debug mode — single region
        cfg = REGION_CONFIG.get(args.region)
        if not cfg:
            print(f"ERROR: unknown region {args.region!r}", file=sys.stderr)
            print(f"  Known: {sorted(REGION_CONFIG.keys())}", file=sys.stderr)
            return 2
        region_records = filter_records_for_region(records, cfg)
        if cfg.get("exclude_municipalities"):  # same guard as the main loop
            _excl_munis = {m.upper() for m in cfg["exclude_municipalities"]}
            region_records = [
                r for r in region_records
                if _normalize_municipality(
                    r.get("Municipality") or r.get("CityText")
                    or r.get("city_text") or r.get("city") or ""
                ) not in _excl_munis
            ]
        block = build_region_aggregates(region_records, label=cfg["label"])
        print(json.dumps(block, indent=2, default=str))
        return 0

    # Active feed. Prefer the RAW pull (listings.json): it is the only one
    # carrying a fetched_at, which the stale-feed guard needs, and it is the
    # complete feed rather than the consumer subset. Falls back to the
    # projected feed so a site without a raw pull keeps working exactly as
    # before (Convention #74).
    listings_records = []
    listings_fetched_at = None
    for cand in (source.parent / "listings.json",
                 source.parent / "listings-projected.json"):
        if not cand.exists():
            continue
        try:
            ldata = json.load(open(cand, encoding="utf-8"))
            rows = (ldata.get("rows") or ldata.get("listings") or []) \
                if isinstance(ldata, dict) else ldata
            if not isinstance(rows, list) or not rows:
                continue
            listings_records = rows
            listings_fetched_at = ldata.get("fetched_at") if isinstance(ldata, dict) else None
            break
        except Exception as e:
            print(f"[aggregator] WARN active feed {cand.name}: {e}", file=sys.stderr)
    if args.verbose:
        print(f"[aggregator] {len(listings_records)} active-listing records "
              f"(fetched_at={listings_fetched_at})", file=sys.stderr)

    # New-listings ledger. Loaded before the region loop, mutated in place as
    # regions are processed, written once after. `writable` is False when the
    # file exists but could not be parsed — we then run on live counts and leave
    # the file alone rather than overwriting accrued history with a fresh start.
    ledger_path = Path(args.new_listings_ledger)
    ledger, ledger_writable = load_new_listings_ledger(ledger_path)

    dump = build_full_dump(records, source_path=source, listings=listings_records,
                           ledger=ledger, listings_fetched_at=listings_fetched_at)
    dump = strip_sold_prices(dump)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dump, indent=2, default=str), encoding="utf-8")

    if ledger_writable:
        ledger["updated_at"] = _now_iso()
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True,
                                          default=str), encoding="utf-8")

    def _disp(p):
        """Path for display. relative_to() raises on anything outside the site
        root — including an ordinary relative --out — which crashed this summary
        AFTER every file had been written successfully. A cosmetic line must
        never be able to fail a run that worked."""
        try:
            return p.resolve().relative_to(SITE_ROOT)
        except ValueError:
            return p

    # Per-agent widget stats: not built on Lab West (sites, D-1012-34). There is one contact, Mike Turner, no agent
    # sales widget, and nothing may be written under listings/sold/ by the aggregator (that tree is the sold gate's).

    # Human-readable summary
    print(f"")
    print(f"IDX Stats Aggregator")
    print(f"Source:       {_disp(source)} ({len(records):,} records)")
    print(f"Year range:   {dump['year_range'][0]}–{dump['year_range'][1]}")
    print(f"Output:       {_disp(out)} ({out.stat().st_size:,} bytes)")
    print(f"")
    print(f"Region rollups:")
    for region_name, block in dump["regions"].items():
        ytd = block.get("ytd", {})
        ytd_count = ytd.get("count", 0)
        ytd_dom = ytd.get("avg_dom")
        ytd_avg_str = f"{ytd_dom:.0f} days" if ytd_dom else "—"
        muni_count = len(block.get("by_municipality", {}))
        muni_str = f", {muni_count} muni breakouts" if muni_count else ""
        print(f"  {block.get('label', region_name):25s} "
              f"YTD: {ytd_count:4d} sales / {ytd_avg_str:>9s} avg on market{muni_str}")

    if args.json:
        print(f"")
        print(json.dumps(dump, indent=2, default=str))

    return 0


if __name__ == "__main__":
    sys.exit(main())
