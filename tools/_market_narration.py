"""Region market-narration payload + plain-English meaning lines, shared
between fb-post.py (the FB/IG/GBP market-report carousel) and
emit-market-audio.py (the spoken Market Minute clip). Both need the SAME
payload so every surface -- card, caption, PDF, and now audio -- quotes the
same count / median / days-on-market / verdict for a region (Conv #32).

Canonical home for `_market_region_payload` / `market_meaning_lines` (and
their four small helpers): fb-post.py imports these names directly
(2026-09-12 refactor) instead of carrying its own copy, which eliminates
the drift risk of two hand-maintained versions. This file is fleet-canonical
(tier 1) because emit-market-audio.py runs standalone on every site's own
nightly and Avalon/Goose Bay have never had a fb-post.py at all (posting
for all 3 sites is centralized on Gander); fb-post.py itself stays
Gander-only, importing this module the same way every other site does.

Fixed 2026-09-12: emit-market-audio.py's original `_load_fb_post()` dynamic-
imported fb-post.py from its own SCRIPT_DIR, which only resolves on Gander --
Avalon and Goose Bay have never had a fb-post.py at all, so the Market Minute
nightly step FileNotFoundError'd on both sites the first time it ran for
real (masked by continue-on-error and never exercised by --self-check).
"""
from __future__ import annotations  # py3.9: defer X|None annotation eval (matches fb-post.py)

import datetime as _dt
import re

MARKET_MIN_YTD = 5   # a region needs >= this many YTD sales to earn a slide (accuracy floor)
MARKET_STABLE_YTD_MIN = 15   # below this, verdict/YoY framing is suppressed as noise
MARKET_NO_BALANCE = {"East End St. John's", "West End St. John's",
                     "Downtown St. John's", "North End St. John's",
                     "Kenmount St. John's", "South St. John's"}

_MONTHS = ["", "January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]


def _fmt_money_short(v) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if n >= 1_000_000:
        s = f"${n/1_000_000:.2f}M"
        return s.replace(".00M", "M")
    if n >= 1000:
        return f"${n/1000:.0f}K"
    return f"${n:,.0f}"


def _agg_through(agg: dict) -> str:
    """Data-through date for the §15.e source line. Falls back to the pull
    date (fetched_at) when an aggregator doesn't emit latest_close_date."""
    return agg.get("latest_close_date") or str(agg.get("fetched_at") or "")[:10]


def _stats_notice(start_iso: str, end_iso: str) -> str:
    """NLAR MLS Policies & Rules §15(e) (reviewed 2026-09-15, see CLAUDE.md
    nlar-advertising-rules): any advertising that uses statistics based on
    MLS System data must clearly indicate the period covered and include
    this notice, or one substantially similar: 'Based on MLS® System data
    owned by the Newfoundland and Labrador Association of REALTORS® covering
    the period 'date' through 'date'.'"""
    def _fmt(d):
        s = str(d or "")[:10]
        try:
            return _dt.datetime.strptime(s, "%Y-%m-%d").strftime("%b %-d, %Y")
        except ValueError:
            return s
    a, b = _fmt(start_iso), _fmt(end_iso)
    period = f"{a} through {b}" if a and b else (b or a or "the reporting period")
    return (f"Based on MLS® System data owned by the Newfoundland and Labrador "
            f"Association of REALTORS® covering the period {period}.")


def _month_is_complete(agg: dict, year: int, month: int) -> bool:
    """Is <year>-<month> done filing, or still catching up on sold notices?
    A month is only "done" once the board's own latest-reported date has
    moved into a LATER calendar month than the one being checked."""
    through = _agg_through(agg)
    if not through or len(through) < 7:
        return False
    try:
        ty, tm = int(through[:4]), int(through[5:7])
    except ValueError:
        return False
    return (ty, tm) > (year, month)


def _market_region_payload(agg: dict, region_key: str, label: str) -> dict | None:
    """One region's stat-card payload from live-aggregates, or None if the data is
    too thin to post honestly (accuracy guard, Convention #21). Lag-robust metrics
    only (median price / sale-to-list / market type); count shown YTD, never a raw
    lag-skewed single-month headline.

    ONE YTD RULE: the card, the newsletter, the seller report and the spoken clip
    all read the COMPLETE-MONTH window the aggregator already computes
    (ytd_complete / yoy_complete) -- the same window the PDF's "so far vs last
    year" table uses -- so every surface quotes the same count / median / days-
    on-market for a region. The partial-through-today `ytd` is the fallback only
    when no complete month exists yet. Days on market is the AVERAGE."""
    r = (agg.get("regions") or {}).get(region_key)
    if not r:
        return None
    ytd_c = r.get("ytd_complete") or {}
    use_complete = bool(ytd_c.get("count"))
    ytd = ytd_c if use_complete else (r.get("ytd") or {})
    n_ytd = int(ytd.get("count") or 0)
    if n_ytd < MARKET_MIN_YTD:
        return None
    yoy = (r.get("yoy_complete") if use_complete else r.get("yoy")) or {}
    mb = r.get("market_balance") or {}
    mt = (mb.get("market_type") or "").lower()          # seller / buyer / balanced
    mos = mb.get("months_of_supply")
    mtl = (mb.get("market_type_label") or "").strip()
    is_stable = n_ytd >= MARKET_STABLE_YTD_MIN
    small_market = bool(mb.get("small_market")) or not is_stable
    no_balance = region_key in MARKET_NO_BALANCE   # neighbourhood supply-scope unreliable
    if no_balance or small_market:
        mt, mos, mtl = "", None, ""
    if small_market and not no_balance:
        market_line, market_kind = "Small market · year-to-date view", "small"
    else:
        market_line = f"{mtl} · {mos:.1f} months of supply" if (mtl and mos) else mtl
        market_kind = mt if mt in ("seller", "buyer", "balanced") else "balanced"
    med = ytd.get("median_price")
    med_pct = yoy.get("median_price_pct")
    med_delta, med_up = "", False
    if med_pct is not None and not yoy.get("small_sample") and is_stable:
        med_up = med_pct >= 0
        med_delta = f"{abs(med_pct):.0f}% YoY"
    sa = ytd.get("avg_sa")
    cnt_pct = yoy.get("count_pct")
    cnt_delta, cnt_up = "", False
    if cnt_pct is not None and not yoy.get("small_sample") and is_stable:
        cnt_up = cnt_pct >= 0
        cnt_delta = f"{abs(cnt_pct):.0f}% YoY"
    tiles = [
        {"label": "Median price", "value": _fmt_money_short(med), "delta": med_delta, "up": med_up},
        {"label": "Sale-to-list", "value": (f"{sa:.1f}%" if sa is not None else "—")},
        {"label": "Homes sold YTD", "value": str(n_ytd), "delta": cnt_delta, "up": cnt_up},
    ]
    snlr = r.get("snlr") or {}
    roll = snlr.get("rolling_3mo") or {}
    absorption_line, snlr_pct, snlr_label, snlr_prior_pct = "", None, "", None
    if roll.get("ratio_pct") is not None and not small_market and not no_balance:
        snlr_pct = float(roll["ratio_pct"])
        ms_ = roll.get("months") or []
        if ms_:
            snlr_label = f"{_MONTHS[int(ms_[0][5:7])][:3]}–{_MONTHS[int(ms_[-1][5:7])][:3]}"
        pr_ = ((snlr.get("prior_year") or {}).get("rolling_3mo") or {})
        snlr_prior_pct = pr_.get("ratio_pct")
        absorption_line = f"Sales-to-new-listings {snlr_pct:.0f}%" + (f" ({snlr_label})" if snlr_label else "")
        if snlr_prior_pct is not None:
            absorption_line += f" · {float(snlr_prior_pct):.0f}% a year ago"
        elif roll.get("condition_label"):
            absorption_line += f" · {roll['condition_label'].lower()} range"
    dom = ytd.get("avg_dom")
    if dom:
        tiles.append({"label": "Avg days on market", "value": f"{float(dom):.0f} days"})
    latest_line = ""
    bym = r.get("by_year_month") or {}
    months = sorted((k for k, v in bym.items() if (v or {}).get("count")), reverse=True)
    complete_key = None
    for k in months:
        ky, km = int(k[:4]), int(k[5:7])
        if _month_is_complete(agg, ky, km):
            complete_key = k
            break
    if complete_key and is_stable:
        mv = bym[complete_key]
        yy, mm = complete_key.split("-")
        n = int(mv.get("count") or 0)
        latest_line = (f"Latest reported — {_MONTHS[int(mm)]} {yy}: "
                       f"{n} sale{'s' if n != 1 else ''}, median {_fmt_money_short(mv.get('median_price'))}")
    thru_m = r.get("ytd_complete_through_month") if use_complete else None
    if use_complete and r.get("ytd_complete_through_year"):
        year = int(r["ytd_complete_through_year"])
    else:
        year = r.get("ytd_anchor_year") or _dt.datetime.now(_dt.timezone.utc).year
    if thru_m:
        abbr = _MONTHS[int(thru_m)][:3]
        period_label = f"{year} Snapshot · Jan–{abbr}"
        window_label = f"January–{_MONTHS[int(thru_m)]} {year}"
    else:
        period_label = f"{year} Market Snapshot"
        window_label = f"{year} year to date"
    return {
        "kind": "region",
        "region_key": region_key,
        "region_label": label,
        "slug": re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-"),
        "period_label": period_label,
        "window_label": window_label,
        "market_line": market_line,
        "market_kind": market_kind,
        "tiles": tiles,
        "latest_line": latest_line,
        "source_line": _stats_notice(f"{year}-01-01", _agg_through(agg)),
        "n_ytd": n_ytd, "median": med, "market_type_label": mtl, "year": year,
        "small_market": small_market, "avg_dom": dom, "sale_to_list": sa,
        "months_of_supply": mos, "market_type": mt,
        "count_pct": cnt_pct, "absorption_line": absorption_line,
        "snlr_pct": snlr_pct, "snlr_label": snlr_label, "snlr_prior_pct": snlr_prior_pct,
    }


# ---------------------------------------------------------------------------
# Days-on-market story (D-1008-22 fix 1, 2026-10-08). ONE function turns the
# aggregator's dom_sa block (the same lists the by-week table is drawn from)
# into every number quoted in prose: the market-stats hero line, the Pricing
# Strategy section, the seller/buyer fragments, the social card and the audio.
# The old copy quoted dom_sa["worst_late_sa"], the single lowest week from
# week 6 on, as the price of waiting and then called it a percentage "below
# asking" that was not 100 minus any figure in the table, while the table's
# weeks 6 to 8 were above 100%.
# Nothing here is a hand-written constant: change the data and the prose moves
# (tools/tests/test_market_copy_matches_table.py proves it).
# ---------------------------------------------------------------------------
DOM_STORY_BASE = 400000      # the "$400,000 home" the dollar figure is quoted on
DOM_EARLY_MAX_WEEK = 4       # "first four weeks" = table rows 1 to 4
DOM_STORY_MIN_N = 10         # sales needed in each group before we compare them
DOM_STORY_MIN_GAP = 2.0      # percentage points; a smaller gap is not a story


# The by-week table's third column (D-1008-42 item 1, Mike 2026-10-08): a NEUTRAL label read from
# that row's own number and nothing else. The old words ("Best possible", "Erosion begins",
# "Significant loss") judged a week against a fixed idea of a good sale and contradicted the
# neighbouring rows. Fixed thresholds, the same on every site; tools/market_copy_check.py repeats
# them on purpose (it does not import this file) and tools/tests/market-copy-matches-table-test.py
# proves the two agree. Compared on the value as shown (two decimals).
DOM_SA_SIGNAL_HEADER = "Vs asking"
DOM_SA_ABOVE_MIN = 100.5     # >= this: "Above asking"
DOM_SA_NEAR_MIN = 97.0       # >= this and below ABOVE_MIN: "Near asking"; below: "Below asking"


def dom_sa_signal(v) -> str:
    """Neutral label for one by-week sale-to-list ratio (a percent, e.g. 94.18)."""
    v = round(float(v), 2)
    if v >= DOM_SA_ABOVE_MIN:
        return "Above asking"
    if v >= DOM_SA_NEAR_MIN:
        return "Near asking"
    return "Below asking"


def dom_sa_story(ds: dict | None) -> dict | None:
    """Two groups of sold homes from the dom_sa table: those that sold in weeks
    1 to 4 and those in the table's last "N+" row. Returns None (callers fall
    back to copy with no numbers) when the groups are too small or the gap is
    not real. Averages are weighted by the number of sales in each week row."""
    ds = ds or {}
    weeks, sa, ns, labels = ds.get("weeks"), ds.get("sa"), ds.get("n"), ds.get("labels")
    if not (weeks and sa and ns and labels) or not (len(weeks) == len(sa) == len(ns) == len(labels)):
        return None
    early = [(v, c) for w, v, c in zip(weeks, sa, ns) if w <= DOM_EARLY_MAX_WEEK and c]
    tail = [(v, c, lab) for v, c, lab in zip(sa, ns, labels) if str(lab).endswith("+") and c]
    if not early or not tail:
        return None
    early_n = sum(c for _, c in early)
    late_n = sum(c for _, c, _ in tail)
    if early_n < DOM_STORY_MIN_N or late_n < DOM_STORY_MIN_N:
        return None
    early_avg = round(sum(v * c for v, c in early) / early_n, 1)
    late_avg = round(sum(v * c for v, c, _ in tail) / late_n, 1)
    gap = round(early_avg - late_avg, 1)
    if gap < DOM_STORY_MIN_GAP or late_avg >= 100:
        return None
    weeks_n = re.sub(r"\D", "", str(tail[0][2])) or "13"
    return {
        "early_label": "the first four weeks",
        "early_avg": early_avg, "early_n": early_n,
        "late_label": f"{weeks_n} weeks or more", "late_avg": late_avg, "late_n": late_n,
        "gap_pts": gap,
        "gap_dollars": int(round(gap / 100.0 * DOM_STORY_BASE, -3)),
        "late_below_asking": round(100.0 - late_avg, 1),
        "window_text": _dom_window_text(ds.get("window_days")),
    }


def _dom_window_text(days) -> str:
    try:
        months = round(int(days) / 30.4)
    except (TypeError, ValueError):
        return ""
    return f"in the last {months} months" if months >= 1 else ""


def dom_sa_seller_sentence(st: dict) -> str:
    lead = (st["window_text"][0].upper() + st["window_text"][1:] + ", homes") if st["window_text"] else "Homes"
    return (f"{lead} that sold in {st['early_label']} averaged {st['early_avg']:.1f}% of asking "
            f"({st['early_n']:,} sales). Homes that took {st['late_label']} averaged {st['late_avg']:.1f}% "
            f"({st['late_n']:,} sales). The difference is {st['gap_pts']:.1f} percentage points, about "
            f"${st['gap_dollars']:,.0f} on a $400K home. These are different groups of homes, "
            f"so it is not a loss to any one seller.")


def dom_sa_buyer_sentence(st: dict) -> str:
    return (f"Homes that took {st['late_label']} to sell averaged {st['late_avg']:.1f}% of asking "
            f"({st['late_n']:,} sales). Long-listed homes are where buyers often have the most room to negotiate. "
            f"Every home is different, so ask us for its comparable sales.")


def meaning_lines(kind: str, small: bool, region_block: dict | None) -> tuple[str, str]:
    """(seller_line, buyer_line) -- plain-English "what this means" from the
    market kind plus dom_sa_story(). Conv #74: a sentence whose inputs are
    missing degrades to copy with no numbers, never a fabricated number."""
    r = region_block or {}
    st = dom_sa_story(r.get("dom_sa"))
    if small:
        return ("Too few sales this year to call a trend — every home stands on its own "
                "comparables. Ask us for a free evaluation before you set a price.",
                "With so few sales, recent comparables matter more than any market label. "
                "We'll pull them for any home you're considering.")
    if kind == "seller":
        seller = (dom_sa_seller_sentence(st) if st else
                  "Price it right on day one — well-priced homes here are selling quickly and "
                  "close to asking; overpricing costs time and money.")
        buyer = (dom_sa_buyer_sentence(st) if st else
                 "Well-priced homes move fast, so be ready to act. Ask us for the comparable "
                 "sales on any home you like.")
        return seller, buyer
    if kind == "buyer":
        return ("Buyers have choice. Sharp pricing and presentation matter most — the homes that "
                "sell are priced to today's market, not last year's.",
                "Inventory is on your side: compare, take your time, and negotiate — price and "
                "conditions are both in play.")
    return ("Neither side holds all the cards. A realistic price sells; an optimistic one sits.",
            "Fair conditions — a well-priced home still draws interest, so move decisively on "
            "the right one.")


def market_meaning_lines(hero: dict, region_block: dict | None) -> tuple[str, str]:
    """Wrapper kept for fb-post.py / emit-market-audio.py (hero payload form)."""
    return meaning_lines(hero.get("market_kind"), bool(hero.get("small_market")), region_block)

