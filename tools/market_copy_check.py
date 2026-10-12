#!/usr/bin/env python3
"""Fail when a market-stats page's days-on-market commentary disagrees with its own table.

Why (D-1008-22 fix 1, 2026-10-08): the Avalon St. John's page said homes past six weeks close
"about 94%" of asking and "roughly 14%+ below asking" (94% is 6% below) while its table showed
weeks 6 to 8 above 100%. The prose came from one constant, the table from another.

How: the check reads ONLY the page. It re-computes the story from the page's own by-week table
(each <tr> carries data-n, the number of sales behind the row), independently of the generator
(it does not import _market_narration), then verifies every figure in the commentary:

  - "X% of asking"          must be the first-four-weeks average or the last-row ("13+") average
  - "X% below asking"       must be 100 minus the last-row average
  - "N percentage points"   must be the gap between the two averages
  - "$N" (not the $400,000 base)  must be that gap on a $400,000 home, rounded to $1,000
  - "N weeks or more"       must be the last row's label
  - a dollar figure must sit next to wording that says the groups are different homes
  - when the table has no usable comparison, the commentary may carry no percentage at all
  - an outcome line with two percentages must say which dates it covers (it uses a different
    window from the by-week table)
  - the by-week table's third column (D-1008-42 item 1) is headed "Vs asking" and each cell is the
    neutral label that row's own number implies: >= 100.5 "Above asking", 97.0 to under 100.5
    "Near asking", under 97.0 "Below asking"; none of the retired words ("Best possible", "Strong",
    "Still solid", "Softening", "Erosion begins", "Significant loss") may appear in that column

Also (D-1008-22 follow-up, 2026-10-09): the same checks run on pages/sell-your-home.html (its Pricing Strategy
table is built from the same dom_sa lists by tools/emit-sell-your-home-market.py), and the agent explainer
(agent/explaining-the-market.html, pages/agent-explaining-the-market.html) may not carry any hand-typed
percentage or dollar figure, "six weeks", or loss wording in its days-on-market section.

Run: python3 tools/market_copy_check.py [--root DIR] [pages/foo-market-stats.html ...]
Exit 1 on any disagreement. Offline.
"""
from __future__ import annotations

import html as _html
import re
import sys
from pathlib import Path

BASE = 400000
MIN_N = 10
MIN_GAP = 2.0
EARLY_MAX_WEEK = 4
# Repeated on purpose (this check never imports the generator); the test proves they agree with
# _market_narration.dom_sa_signal.
SIGNAL_HEADER = "Vs asking"
SIGNAL_ABOVE_MIN = 100.5
SIGNAL_NEAR_MIN = 97.0
RETIRED_SIGNAL_WORDS = ("Best possible", "Strong", "Still solid", "Softening", "Erosion begins", "Significant loss")

ROW_RX = re.compile(
    r'<tr(?P<attrs>[^>]*)>\s*<td>Week\s+(?P<label>[0-9]+\+?)</td>\s*<td><span class="ms-ratio[^"]*">(?P<val>[0-9.]+)%</span></td>',
    re.S)
SIGNAL_ROW_RX = re.compile(
    r'<tr[^>]*>\s*<td>Week\s+(?P<label>[0-9]+\+?)</td>\s*<td><span class="ms-ratio[^"]*">(?P<val>[0-9.]+)%</span></td>'
    r'\s*<td>(?P<sig>[^<]*)</td>', re.S)
DOM_TABLE_RX = re.compile(r'<table class="[^"]*\bms-dom-table\b[^"]*">.*?</table>', re.S)
DOM_TH_RX = re.compile(r'<th>([^<]*)</th>')
HERO_RX = re.compile(r'<p class="ms-hero-say">(?P<t>.*?)</p>', re.S)
PRICING_RX = re.compile(r'(<h2>Days on Market and.*?)(?=<div class="ms-chart-wrap")', re.S)
SY_INSIGHT_RX = re.compile(r'<div class="sy-pricing-insight">(?P<t>.*?)</div>', re.S)
EXPLAINER_RX = re.compile(r'(Days on market and what it costs.*?)(?=<div class="sec">)', re.S)
INSIGHT_RX = re.compile(r'<div class="ms-insight">\s*<div class="ms-insight-label">(?P<l>[^<]*)</div>\s*<p>(?P<t>.*?)</p>', re.S)
OUTCOME_RX = re.compile(r'<p class="ms-outcome-line">(?P<t>(?:From|Homes) .*?)</p>', re.S)
PCT_RX = re.compile(r'(\d+(?:\.\d+)?)%')
USD_RX = re.compile(r'\$\s?(\d[\d,]*)(K?)')


def _text(frag: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", frag)).replace(" ", " ")


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()


def table_story(page: str) -> dict | None:
    """Independent re-computation from the page's own table. None = no usable comparison."""
    rows = []
    for m in ROW_RX.finditer(page):
        n = re.search(r'data-n="(\d+)"', m.group("attrs"))
        rows.append((m.group("label"), float(m.group("val")), int(n.group(1)) if n else None))
    if not rows:
        return None
    if any(r[2] is None for r in rows):
        return {"error": "table rows carry no data-n (page predates the check; regenerate it)"}
    early = [(v, n) for lab, v, n in rows if not lab.endswith("+") and int(lab) <= EARLY_MAX_WEEK]
    tail = [(v, n, lab) for lab, v, n in rows if lab.endswith("+")]
    if not early or not tail:
        return None
    en, ln = sum(n for _, n in early), sum(n for _, n, _ in tail)
    if en < MIN_N or ln < MIN_N:
        return None
    e = round(sum(v * n for v, n in early) / en, 1)
    l = round(sum(v * n for v, n, _ in tail) / ln, 1)
    gap = round(e - l, 1)
    if gap < MIN_GAP or l >= 100:
        return None
    return {"early": e, "late": l, "gap": gap, "below": round(100 - l, 1),
            "dollars": int(round(gap / 100.0 * BASE, -3)), "tail_label": re.sub(r"\D", "", tail[0][2]),
            "early_n": en, "late_n": ln}


def narrative_blocks(page: str) -> list[tuple[str, str]]:
    blocks = []
    for m in HERO_RX.finditer(page):
        blocks.append(("hero", _norm(_text(m.group("t")))))
    m = PRICING_RX.search(page)
    if m:
        for p in re.finditer(r"<p>(.*?)</p>", m.group(1), re.S):
            blocks.append(("pricing", _norm(_text(p.group(1)))))
    for m in INSIGHT_RX.finditer(page):
        blocks.append(("insight", _norm(_text(m.group("t")))))
    for m in SY_INSIGHT_RX.finditer(page):
        for p in re.finditer(r"<p[^>]*>(.*?)</p>", m.group("t"), re.S):
            blocks.append(("sell-your-home", _norm(_text(p.group(1)))))
    return blocks


def check_text(where: str, text: str, st: dict | None) -> list[str]:
    errs = []
    pcts = [(float(m.group(1)), m.start(), m.end()) for m in PCT_RX.finditer(text)]
    usd = [(m.group(1), m.group(2), m.start()) for m in USD_RX.finditer(text)]
    if st is None:
        if pcts:
            errs.append(f"{where}: carries percentage figures {[p[0] for p in pcts]} but the table has no usable comparison: {text[:90]}")
        for amt, k, _ in usd:
            if not (amt.replace(",", "") == "400000" or (amt == "400" and k == "K")):
                errs.append(f"{where}: dollar figure ${amt}{k} with no comparison in the table")
        return errs
    if "error" in st:
        return [f"{where}: {st['error']}"]
    for v, a, b in pcts:
        tail = text[b:b + 22].lower()
        if tail.startswith(" below asking"):
            if abs(v - st["below"]) > 0.051:
                errs.append(f"{where}: says {v}% below asking; the table's last row is {100 - st['below']:.1f}% of asking, "
                            f"which is {st['below']}% below")
        elif tail.startswith(" of asking") or tail.startswith(" of their"):
            if abs(v - st["early"]) > 0.051 and abs(v - st["late"]) > 0.051:
                errs.append(f"{where}: says {v}% of asking; the table gives {st['early']}% (first four weeks) and {st['late']}% (last row)")
        elif tail.startswith(" and") or tail.startswith(",") or tail.startswith(".") or tail.startswith(" ("):
            if abs(v - st["early"]) > 0.051 and abs(v - st["late"]) > 0.051 and abs(v - st["below"]) > 0.051:
                errs.append(f"{where}: says {v}%, which matches nothing the table supports ({st['early']}, {st['late']}, {st['below']})")
        else:
            errs.append(f"{where}: percentage {v}% in a form the check cannot tie to the table: ...{text[max(0, a - 30):b + 15]}")
    for m in re.finditer(r"(\d+(?:\.\d+)?) percentage points(?! under asking)", text):
        if abs(float(m.group(1)) - st["gap"]) > 0.051:
            errs.append(f"{where}: says a gap of {m.group(1)} points; the table's gap is {st['gap']}")
    for amt, k, _ in usd:
        if amt.replace(",", "") == "400000" or (amt == "400" and k == "K"):
            continue
        val = int(amt.replace(",", "")) * (1000 if k == "K" else 1)
        if abs(val - st["dollars"]) > 500:
            errs.append(f"{where}: says ${val:,}; the table's gap on a $400,000 home is ${st['dollars']:,}")
    for m in re.finditer(r"(\d+(?:\.\d+)?) percentage points under asking", text):
        if abs(float(m.group(1)) - st["below"]) > 0.051:
            errs.append(f"{where}: says {m.group(1)} points under asking; the table's last row is {st['below']} under")
    for m in re.finditer(r"(\d+) weeks or more", text):
        if m.group(1) != st["tail_label"]:
            errs.append(f"{where}: says {m.group(1)} weeks or more; the table's last row is Week {st['tail_label']}+")
    if re.search(r"six weeks", text, re.I):
        errs.append(f"{where}: still says 'six weeks'; the comparison is first four weeks vs the last row")
    if re.search(r"discount from asking|costs? you|lost on", text, re.I):
        errs.append(f"{where}: causal or discount wording: {text[:90]}")
    if re.search(r"left on the table|\d+%\+", text, re.I):
        errs.append(f"{where}: loss wording the table does not support: {text[:90]}")
    return errs


def expected_signal(v: float) -> str:
    v = round(v, 2)
    if v >= SIGNAL_ABOVE_MIN:
        return "Above asking"
    if v >= SIGNAL_NEAR_MIN:
        return "Near asking"
    return "Below asking"


def check_signal_column(page: str, name: str) -> list[str]:
    """Third column of the by-week table: right header, and each cell the label its number implies."""
    errs = []
    for tm in DOM_TABLE_RX.finditer(page):
        tbl = tm.group(0)
        heads = DOM_TH_RX.findall(tbl)
        if len(heads) < 3 or heads[2] != SIGNAL_HEADER:
            errs.append(f"{name} [signal]: third column header is {heads[2:3]!r}, expected {SIGNAL_HEADER!r}")
        rows = list(SIGNAL_ROW_RX.finditer(tbl))
        if not rows:
            errs.append(f"{name} [signal]: the by-week table has no readable rows with a signal cell")
        n_tr = len(re.findall(r"<tr[^>]*>\s*<td>Week", tbl))
        if rows and len(rows) != n_tr:
            errs.append(f"{name} [signal]: {n_tr} week rows but only {len(rows)} carry a ratio and a signal cell")
        for m in rows:
            sig, want = _norm(_html.unescape(m.group("sig"))), expected_signal(float(m.group("val")))
            if sig in RETIRED_SIGNAL_WORDS:
                errs.append(f"{name} [signal]: Week {m.group('label')} ({m.group('val')}%) says retired word {sig!r}; expected {want!r}")
            elif sig != want:
                errs.append(f"{name} [signal]: Week {m.group('label')} ({m.group('val')}%) says {sig!r}; its number implies {want!r}")
    return errs


def check_explainer(page: str, name: str) -> list[str]:
    """The agent explainer is a script, not a data page: its days-on-market section carries brackets,
    never a typed figure, and none of the retired wording."""
    errs = []
    m = EXPLAINER_RX.search(page)
    if not m:
        return [f"{name} [explainer]: days-on-market section not found"]
    t = _norm(_text(m.group(1)))
    for pm in PCT_RX.finditer(t):
        if not re.search(r"\[[A-Z0-9]+\]%$", t[:pm.end()]):
            errs.append(f"{name} [explainer]: typed percentage {pm.group(0)} (use a bracket the agent fills from the page): ...{t[max(0, pm.start() - 40):pm.end() + 15]}")
    for um in USD_RX.finditer(t):
        if not (um.group(1).replace(",", "") == "400000" or (um.group(1) == "400" and um.group(2) == "K")):
            errs.append(f"{name} [explainer]: typed dollar figure ${um.group(1)}{um.group(2)}")
    if re.search(r"six weeks|left on the table|slips to|well below their last asking|costs? you|discount from asking", t, re.I):
        errs.append(f"{name} [explainer]: retired days-on-market wording: {t[:90]}")
    if "different groups of homes" not in t:
        errs.append(f"{name} [explainer]: the script does not say the two groups are different homes")
    for bm in re.finditer(r"To a buyer.*?(?=Small market|</div>)", _text(page), re.S):
        if re.search(r"six weeks", bm.group(0), re.I):
            errs.append(f"{name} [explainer]: buyer script still says 'six weeks'")
    return errs


def check_page(page: str, name: str = "page") -> list[str]:
    errs = check_signal_column(page, name)
    st = table_story(page)
    blocks = narrative_blocks(page)
    for kind, text in blocks:
        errs += check_text(f"{name} [{kind}]", text, st)
    def _non_base_usd(t):
        return [1 for m in USD_RX.finditer(t)
                if not (m.group(1).replace(",", "") == "400000" or (m.group(1) == "400" and m.group(2) == "K"))]
    has_usd = any(_non_base_usd(t) for _, t in blocks)
    if st and "error" not in st and has_usd:
        joined = " ".join(t for _, t in blocks).lower()
        if "different homes" not in joined and "different groups" not in joined:
            errs.append(f"{name}: a dollar gap is quoted without saying it compares different homes")
    # Long-history headings must name the years they cover (D-1008-38): no "10-Year" / "A Decade of Growth".
    if "ten-year-history" in page:
        if re.search(r"10-Year (History|Market Trend)|Decade of Growth", page):
            errs.append(f"{name} [history]: heading says '10-Year' or 'A Decade of Growth' instead of naming the years")
        if not re.search(r'ms-accordion-title">\d{4}&ndash;\d{4} History<', page):
            errs.append(f"{name} [history]: accordion title does not name its years")
    for m in OUTCOME_RX.finditer(page):
        t = _norm(_text(m.group("t")))
        if len(PCT_RX.findall(t)) >= 2 and not re.match(r"From \w+ \d+, \d{4} to \w+ \d+, \d{4}", t):
            errs.append(f"{name} [outcome]: two percentages with no date range: {t[:90]}")
    return errs


def main(argv: list[str]) -> int:
    root = Path(".")
    files = []
    i = 0
    while i < len(argv):
        if argv[i] == "--root":
            root = Path(argv[i + 1]); i += 2
        else:
            files.append(argv[i]); i += 1
    extra = [root / "pages" / "sell-your-home.html", root / "agent" / "explaining-the-market.html",
             root / "pages" / "agent-explaining-the-market.html"]
    paths = [Path(f) for f in files] or (sorted((root / "pages").glob("*market-stats*.html")) + [e for e in extra if e.exists()])
    errs, checked, with_story = [], 0, 0
    for p in paths:
        page = p.read_text(encoding="utf-8", errors="replace")
        if p.name.endswith("explaining-the-market.html"):
            checked += 1
            errs += check_explainer(page, p.name)
            continue
        if "ms-dom-table" not in page and "ms-hero-say" not in page:
            continue
        checked += 1
        if table_story(page) and "error" not in (table_story(page) or {}):
            with_story += 1
        errs += check_page(page, p.name)
    for e in errs:
        print("FAIL  " + e)
    print(f"market-copy-check: {checked} market-stats pages, {with_story} with a table comparison, {len(errs)} disagreement(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
