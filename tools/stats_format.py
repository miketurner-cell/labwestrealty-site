"""
stats_format.py — shared pure formatting helpers for the market-stats + community
page generators. Extracted verbatim from build-market-stats-page.py so both
build-market-stats-page.py and build-community-pages.py format every figure
identically (one source of truth → the community snapshot can never disagree with
the market-stats page). Pure string helpers only — no I/O, no module constants.
"""


def fmt_price_k(val):
    """Format price as '$<em>341</em>K' style."""
    if val is None:
        return "N/A"
    k = round(val / 1000)
    return f"$<em>{k}</em>K"


def fmt_price_full(val):
    """Format price as '$341,091' with comma separator."""
    if val is None:
        return "N/A"
    return f"${val:,.0f}"


def fmt_pct(val, decimals=1):
    """Format percentage as '95.8<em>%</em>'."""
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}<em>%</em>"


def fmt_pct_plain(val, decimals=1):
    """Format percentage as '95.8%' (no HTML)."""
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}%"


def fmt_dom(val):
    """Format DOM as '73.3' (one decimal)."""
    if val is None:
        return "N/A"
    return f"{val:.1f}"


def fmt_int(val):
    """Format integer."""
    if val is None:
        return "N/A"
    return str(int(val))


def fmt_volume(val):
    """Format total volume as '$66.2M' or '$13.9M'."""
    if val is None:
        return "N/A"
    m = val / 1_000_000
    if m >= 10:
        return f"${m:.1f}M"
    return f"${m:.1f}M"


def fmt_delta(pct_change, suffix="", is_pts=False):
    """Format YoY delta as '\\u25b2 5% vs YTD 2025' with CSS class."""
    if pct_change is None:
        return ""
    if is_pts:
        abs_val = abs(pct_change)
        val_str = f"{abs_val:.1f} pts"
    else:
        abs_val = abs(round(pct_change))
        val_str = f"{abs_val}%"

    if pct_change > 0:
        arrow = "▲"
        css = "ms-delta"
    elif pct_change < 0:
        arrow = "▼"
        css = "ms-delta down"
    else:
        arrow = "▲"
        css = "ms-delta"
        val_str = "0%"

    text = f"{arrow} {val_str}"
    if suffix:
        text += f" {suffix}"
    return f'<div class="{css}">{text}</div>'


def price_change_class(pct):
    """Return CSS class for price-change direction."""
    if pct is None or pct == 0:
        return ""
    return "ms-ratio-high" if pct > 0 else "ms-ratio-low"


def price_change_str(pct):
    """Format price change percentage for the 10-year table."""
    if pct is None:
        return "—"
    sign = "+" if pct > 0 else ""
    cls = price_change_class(pct)
    return f'<span class="ms-ratio {cls}">{sign}{pct:.1f}%</span>'
