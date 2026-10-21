#!/usr/bin/env python3
"""
build-market-stats-page.py — Generate market-statistics HTML pages from YAML
configs + live aggregator data.

Usage:
  python3 tools/build-market-stats-page.py --config tools/market-stats-config/gander-and-area.yml
  python3 tools/build-market-stats-page.py --all
  python3 tools/build-market-stats-page.py --all --dry-run --verbose

Conventions:
  #74  fail-safe — missing aggregator data skips the page, never crashes
  #18  sanity floor — refuse to write a page with 0 YTD sales
  #32  no fabricated content — all numbers from aggregator or YAML baselines
  #91  CSS in _base.css, not inline scattered through the generator
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml required. Install via: pip3 install --user pyyaml", file=sys.stderr)
    sys.exit(1)

# ── Resolve paths relative to this script ──
SCRIPT_DIR = Path(__file__).resolve().parent
SITE_ROOT = SCRIPT_DIR.parent
DEFAULT_AGG = SITE_ROOT / "tools" / "idx-cache" / "live-aggregates.json"
CONFIG_DIR = SCRIPT_DIR / "market-stats-config"
CSS_BASE = CONFIG_DIR / "_base.css"
PAGES_DIR = SITE_ROOT / "pages"
OUTPUT_ROOT = [False]   # set by --output-root

# R2 vs disk photo-URL resolution for Notable Sales cards (2026-07-30,
# Mike). Mirrors ddf-generate-pages.py's sold-detail photo resolution
# exactly — same R2_BASE_URL/R2_SITE_SLUG env + config, same
# images/listings-sold/<MLS>/ path, same .meta.json existence check as the
# "have photo in R2" signal (the bytes live in R2, not on local disk, so a
# local Path.exists() on the jpg itself would always be False in R2 mode).
from _fleet_config import load_site_config  # noqa: E402
from _fleet_genutils import cross_region_data  # noqa: E402
# Every number in the days-on-market prose comes from dom_sa_story() over the same
# lists the by-week table is drawn from (D-1008-22; test: tools/tests/test_market_copy_matches_table.py).
from _market_narration import DOM_SA_SIGNAL_HEADER, dom_sa_signal, dom_sa_story, meaning_lines  # noqa: E402
import market_copy_check  # noqa: E402
_SITE_CFG = load_site_config()
R2_BASE_URL = os.environ.get("R2_BASE_URL", "").strip().rstrip("/")
R2_SITE_SLUG = _SITE_CFG["r2_site_slug"]

# Per-site chrome partials (Convention #64 leak fix). If a site ships these,
# they override the hardcoded Gander default in build_nav/build_footer. Gander
# ships none → falls back to the hardcoded blocks (zero change). Avalon ships
# all three (empty nav shells + footer shell + js/nav.js+footer.js scripts —
# its nav/footer are JS-built); Goosebay ships nav+footer (hardcoded, no nav.js).
NAV_PARTIAL = CONFIG_DIR / "_nav.html"
FOOTER_PARTIAL = CONFIG_DIR / "_footer.html"
SCRIPTS_PARTIAL = CONFIG_DIR / "_scripts.html"

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ═══════════════════════════════════════════════════════════════════════════
# Formatting helpers
# ═══════════════════════════════════════════════════════════════════════════

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


def fmt_delta(pct_change, suffix="", is_pts=False, lower_is_better=False):
    """Format YoY delta as '\\u25b2 5% vs YTD 2025' with CSS class.

    The arrow always points the way the number actually moved.
    `lower_is_better` only flips the COLOUR, for metrics where falling is
    the good outcome — days on market above all. Without it a market where
    homes sell 55% faster renders that win in red, which on a screen-shared
    video reads as bad news."""
    if pct_change is None:
        return ""
    if is_pts:
        abs_val = abs(pct_change)
        val_str = f"{abs_val:.1f} pts"
    else:
        abs_val = abs(round(pct_change))
        val_str = f"{abs_val}%"

    good = "ms-delta"
    bad = "ms-delta down"
    if pct_change > 0:
        arrow = "▲"
        css = bad if lower_is_better else good
    elif pct_change < 0:
        arrow = "▼"
        css = good if lower_is_better else bad
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


def period_label(through_month, through_day, current_month_partial, year):
    """Build the period label for the update badge."""
    if through_month is None:
        return f"{year} Data"
    month_name = MONTH_NAMES[through_month - 1]
    if current_month_partial:
        start_month = MONTH_NAMES[0]
        return (f"Includes {start_month} 1 — {month_name} {through_day}, "
                f"{year} (partial month) Data")
    else:
        if through_month == 1:
            return f"Includes {month_name} {year} Data"
        return f"Includes {MONTH_NAMES[0]} through {month_name} {year} Data"


def build_period_through(through_month, through_day=None, partial=False):
    """Build text like 'January through May' -- or, on a partial month
    (Mike 2026-08-03), 'January 1 – August 3' rather than silently claiming
    the whole current month is done. Mirrors period_label()'s existing
    partial-month phrasing so the hero and the YTD strips never disagree."""
    if through_month is None or through_month < 1:
        return ""
    if partial and through_day:
        month_name = MONTH_NAMES[through_month - 1]
        return f"{MONTH_NAMES[0]} 1 \u2013 {month_name} {through_day}"
    if through_month == 1:
        return MONTH_NAMES[0]
    return f"{MONTH_NAMES[0]} through {MONTH_NAMES[through_month - 1]}"


# ═══════════════════════════════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════════════════════════════

def load_aggregates(path):
    """Load live-aggregates.json. Returns None on missing/corrupt file."""
    p = Path(path)
    if not p.exists():
        print(f"WARNING: Aggregates file not found at {p}", file=sys.stderr)
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: Failed to read aggregates: {e}", file=sys.stderr)
        return None


def load_config(path):
    """Load a YAML config file."""
    p = Path(path)
    if not p.exists():
        print(f"ERROR: Config not found: {p}", file=sys.stderr)
        return None
    with open(p) as f:
        return yaml.safe_load(f)


def load_css():
    """Load base CSS from _base.css."""
    if CSS_BASE.exists():
        return CSS_BASE.read_text()
    print(f"WARNING: Base CSS not found at {CSS_BASE}", file=sys.stderr)
    return ""


def get_region_data(agg, region_key):
    """Extract region block from aggregates. Returns None if missing."""
    if agg is None:
        return None
    regions = agg.get("regions", {})
    if region_key in regions:
        return regions[region_key]
    # Try case-insensitive match
    for k, v in regions.items():
        if k.lower() == region_key.lower():
            return v
    return None


def extract_monthly_arrays(region, baseline_year):
    """
    Extract monthly data arrays for prior year and current year from
    by_year_month.  Returns dict with keys for each metric and each year.
    """
    bym = region.get("by_year_month", {}) if region else {}
    current_year = baseline_year + 1

    result = {
        "prior_price": [],
        "prior_units": [],
        "prior_dom": [],
        "prior_sa": [],
        "prior_at100": [],
        "current_price": [],
        "current_units": [],
        "current_dom": [],
        "current_sa": [],
        "current_at100": [],
    }

    for m in range(1, 13):
        # Prior year
        key_prior = f"{baseline_year}-{m:02d}"
        pd = bym.get(key_prior, {})
        result["prior_price"].append(
            round(pd["avg_price"] / 1000) if pd.get("avg_price") else None
        )
        result["prior_units"].append(pd.get("count"))
        result["prior_dom"].append(
            round(pd["avg_dom"], 1) if pd.get("avg_dom") is not None else None
        )
        result["prior_sa"].append(
            round(pd["avg_sa"], 1) if pd.get("avg_sa") is not None else None
        )
        result["prior_at100"].append(pd.get("at_100_plus"))

        # Current year
        key_curr = f"{current_year}-{m:02d}"
        cd = bym.get(key_curr, {})
        result["current_price"].append(
            round(cd["avg_price"] / 1000) if cd.get("avg_price") else None
        )
        result["current_units"].append(cd.get("count"))
        result["current_dom"].append(
            round(cd["avg_dom"], 1) if cd.get("avg_dom") is not None else None
        )
        result["current_sa"].append(
            round(cd["avg_sa"], 1) if cd.get("avg_sa") is not None else None
        )
        result["current_at100"].append(cd.get("at_100_plus"))

    return result


# ═══════════════════════════════════════════════════════════════════════════
# HTML section builders
# ═══════════════════════════════════════════════════════════════════════════

# Follow Up Boss visitor-tracking pixel (account: royallepage545). Fleet-wide --
# same literal script on all 5 sites. fleet/canonical/tools/inject-fub-pixel.py
# puts this on every already-generated page; this constant keeps it on every
# page this generator produces going forward. Sentinel-gated (`fub-pixel:v1`).
FUB_PIXEL_HEAD = (
    '<!-- fub-pixel:v1 -->\n'
    '<!-- begin Widget Tracker Code -->\n'
    '<script>\n'
    '(function(w,i,d,g,e,t){w["WidgetTrackerObject"]=g;(w[g]=w[g]||function() '
    '{(w[g].q=w[g].q||[]).push(arguments);}),(w[g].ds=1*new Date());(e="script"), '
    '(t=d.createElement(e)),(e=d.getElementsByTagName(e)[0]);t.async=1;t.src=i; '
    'e.parentNode.insertBefore(t,e);}) (window,"https://widgetbe.com/agent",document,"widgetTracker"); '
    'window.widgetTracker("create", "WT-ZOUGZFEJ"); window.widgetTracker("send", "pageview");\n'
    '</script>\n'
    '<!-- end Widget Tracker Code -->\n'
    '<!-- /fub-pixel:v1 -->'
)


DEFAULT_OG_IMAGE = "/images/og/index-og.jpg"


def _resolve_og_image(og_image, slug):
    """Resolve a configured og_image path against the site root on disk.

    Falls back to the site default share image (loud, not silent) when the
    configured path is empty or the file doesn't actually exist — a 404'ing
    og:image is worse than a generic one. Cross-origin (e.g. R2 photos.*)
    values are passed through untouched. See CLAUDE.md "share images" ship,
    2026-09-19: hvgb.yml's og_image was pointing at a filename that had
    never existed, and no check caught it.
    """
    if not og_image:
        print(f"[OG-IMAGE] MISSING og_image for {slug} -> fallback to {DEFAULT_OG_IMAGE}")
        return DEFAULT_OG_IMAGE
    if og_image.startswith("http://") or og_image.startswith("https://"):
        return og_image
    # Ship 2 (2026-09-19): a live-numbers card, when this run wrote one for
    # this slug, wins over the static branded photo Ship 1 falls back to --
    # both are real, resolvable images, this one just says more.
    market_card = SITE_ROOT / "images" / "og" / "market" / f"{slug}.jpg"
    if market_card.is_file():
        return f"/images/og/market/{slug}.jpg"
    if og_image.startswith("/"):
        on_disk = SITE_ROOT / og_image.lstrip("/")
        if not on_disk.is_file():
            print(f"[OG-IMAGE] MISSING {og_image} for {slug} (no file on disk) -> "
                  f"fallback to {DEFAULT_OG_IMAGE}")
            return DEFAULT_OG_IMAGE
    return og_image


_OG_CARD_STATS = {"written": 0, "kept_photo": 0, "failed": 0}


def _write_og_market_card(cfg, region, *, dry_run=False):
    """Render + write this slug's live-numbers og:image card (Ship 2), or
    remove a stale one when the region no longer has enough data (n<5) for
    an honest card. Conv #74: any failure here must never break the page
    build -- the existing/static og:image (Ship 1) is left exactly as is."""
    # Lab West (sites, D-1012-34): no live-numbers og:image card (og_market_card.py and its fonts are not ported); the
    # static og_image from the YAML is used as is.
    return
    slug = cfg.get("slug", "")
    card_path = SITE_ROOT / "images" / "og" / "market" / f"{slug}.jpg"
    try:
        data = _og_card_data(cfg, region)
    except Exception as e:  # noqa: BLE001
        print(f"[OG-CARD] FAILED {slug}: {type(e).__name__}: {e} (computing data)",
              file=sys.stderr)
        _OG_CARD_STATS["failed"] += 1
        return

    if data is None:
        _OG_CARD_STATS["kept_photo"] += 1
        if card_path.is_file() and not dry_run:
            card_path.unlink()  # stale: this region no longer qualifies
        return

    if dry_run:
        _OG_CARD_STATS["written"] += 1
        return

    try:
        og_market_card = _import_sibling("og_market_card")
        blob = og_market_card.render(data)
        card_path.parent.mkdir(parents=True, exist_ok=True)
        card_path.write_bytes(blob)
        _OG_CARD_STATS["written"] += 1
    except Exception as e:  # noqa: BLE001
        print(f"[OG-CARD] FAILED {slug}: {type(e).__name__}: {e} (rendering) "
              f"-- existing og:image left untouched", file=sys.stderr)
        _OG_CARD_STATS["failed"] += 1


def _import_sibling(name):
    """Import a same-directory module by filename stem, without requiring
    tools/ to already be on sys.path (mirrors build-og-testimonials.py's
    _load() pattern)."""
    import importlib.util
    mod_path = SCRIPT_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, str(mod_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_head(cfg, css_text, current_year):
    """Build the <head> block."""
    domain = cfg.get("domain", "realestategander.com")
    slug = cfg["slug"]
    title = cfg.get("title", f"{cfg['label']} Market Statistics")
    meta_desc = cfg.get("meta_description", "")
    og_image = _resolve_og_image(cfg.get("og_image", ""), slug)
    canonical = (f"https://{domain}/{slug}.html" if OUTPUT_ROOT[0] else f"https://{domain}/pages/{slug}.html")
    og_img_full = f"https://{domain}{og_image}"

    # Determine gtag ID from domain
    gtag_map = {
        "realestategander.com": "G-FEMZDX1BJQ",
        "avalonrealestate.ca": "G-M3VNK9T9ZZ",
        "goosebayrealestate.ca": "G-BGYHM2FYPP",
        "labwestrealty.com": "GT-M38MJCDZ",   # Lab West's own Google tag (never fall through to Gander's stream)
    }
    gtag_id = gtag_map.get(domain, "G-FEMZDX1BJQ")
    # gtag.js loads by the Google tag where Google 404s the G- ID (Mike, B-1007-21).
    gtag_src = {"goosebayrealestate.ca": "GT-KVJZ77ZD", "labwestrealty.com": "GT-M38MJCDZ"}.get(domain, gtag_id)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id={gtag_src}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{gtag_src}');
</script>
{FUB_PIXEL_HEAD}
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <meta name="description" content="{meta_desc}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{meta_desc}">
  <meta property="og:image" content="{og_img_full}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="{title}">
  <meta property="og:site_name" content="Royal LePage Turner Realty">
  <meta property="og:type" content="website">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{meta_desc}">
  <meta name="twitter:image" content="{og_img_full}">
  <title>{title}</title>
  <link rel="canonical" href="{canonical}">
  <link rel="icon" type="image/x-icon" href="../favicon.ico">
  <link rel="icon" type="image/png" sizes="32x32" href="../favicon-32x32.png">
  <link rel="apple-touch-icon" sizes="180x180" href="../apple-touch-icon.png">
  <link rel="manifest" href="/app.webmanifest" data-baked>
  <meta name="theme-color" content="#EA002A">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <meta name="apple-mobile-web-app-title" content="Lab West Realty">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Raleway:wght@800;900&family=Roboto:wght@300;400&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="../css/main.css?v=20260916-mobile-a">
  <link rel="stylesheet" href="../css/mobile-fixes.css?v=20260916-mobile-a">
  <script src="../js/boldtrail-forms.js"></script>
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "{cfg['label']} Market Stats",
  "description": "{meta_desc}",
  "url": "{canonical}",
  "publisher": {{
    "@type": "Organization",
    "name": "Royal LePage Turner Realty",
    "url": "https://{domain}/"
  }}
}}
</script>
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Dataset",
  "name": "{cfg['label']} Real Estate Market Statistics",
  "description": "Monthly real estate market statistics for {cfg['geo_description']}. Sourced from the Newfoundland and Labrador Association of REALTORS (NLAR) MLS system.",
  "url": "{canonical}",
  "license": "https://creativecommons.org/licenses/by-nc/4.0/",
  "keywords": ["real estate", "MLS", "Newfoundland and Labrador", "market statistics", "home prices"],
  "spatialCoverage": {{
    "@type": "Place",
    "name": "{cfg['geo_description']}"
  }},
  "temporalCoverage": "{cfg.get('ten_year_start', 2016)}/..",
  "creator": {{
    "@type": "Organization",
    "name": "Royal LePage Turner Realty (2014) Inc.",
    "url": "https://{domain}/"
  }},
  "sourceOrganization": {{
    "@type": "Organization",
    "name": "Newfoundland and Labrador Association of REALTORS",
    "url": "https://www.nlar.ca/"
  }},
  "isAccessibleForFree": true
}}
</script>
  <script src="../js/analytics-events.js" defer></script>
  <link rel="stylesheet" href="../css/turner-network.css">
<style>
{css_text}
</style>
</head>
<body>'''


def build_nav(cfg):
    """Build the site nav. Per-site _nav.html partial if present (Avalon/Goosebay,
    Conv #64); otherwise the hardcoded Gander default below."""
    if NAV_PARTIAL.exists():
        return NAV_PARTIAL.read_text()
    return '''<!-- ═══ TOP BAR ═══ -->
<div class="nav-top-bar">
  <div style="display:flex;align-items:center">
    <a href="../index.html" class="nav-brand"><span class="nav-brand-name">Turner <span>Realty</span></span></a>
    <span class="nav-brand-rlp">Royal LePage</span>
  </div>
  <div class="nav-top-right">
    <a href="contact.html" class="nav-top-info">204 Airport Blvd, Gander</a>
    <div class="nav-top-divider"></div>
    <a href="mailto:office@realestategander.com" class="nav-top-info">office@realestategander.com</a>
    <div class="nav-top-divider"></div>
    <div class="nav-top-social">
      <a href="https://www.facebook.com/realestategander" target="_blank" rel="noopener" aria-label="Facebook"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"/></svg></a>
      <a href="https://www.youtube.com/playlist?list=PLr4XcQLT7UeO_8OZSgtx6h2N6dvsmsY_Y" target="_blank" rel="noopener" aria-label="YouTube"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 12a29 29 0 0 0 .46 5.58A2.78 2.78 0 0 0 3.4 19.6C5.12 20 12 20 12 20s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2A29 29 0 0 0 23 12a29 29 0 0 0-.46-5.58zM9.75 15.02V8.98L15.5 12l-5.75 3.02z"/></svg></a>
    </div>
  </div>
</div>
<!-- ═══ MAIN NAV ═══ -->
<nav class="nav-main-bar">
  <button class="nav-toggle" aria-label="Toggle navigation" onclick="var L=document.querySelector('.nav-main-links');L.classList.toggle('open');this.classList.toggle('active');document.body.classList.toggle('nav-menu-open',L.classList.contains('open'))"><span></span><span></span><span></span></button>
  <ul class="nav-main-links">
    <li class="nav-dropdown"><a href="#" aria-expanded="false" role="button">Listings</a><div class="nav-dropdown-content">
      <a href="gander-mls-market-stats.html">Market Stats</a>
      <a href="/listings/">MLS Listing Search</a>
      <a href="/listings/new-construction/">New Construction</a>
      <a href="../listings/sold/">Sold Listings</a>
      <a href="/listings/commercial/">Commercial</a>
    </div></li>
    <li><a href="sell-your-home.html">Sell Your Home</a></li>
    <li class="nav-dropdown"><a href="#" aria-expanded="false" role="button">Communities</a><div class="nav-dropdown-content">
      <a href="gander.html">Gander</a>
      <a href="gambo.html">Gambo</a>
      <a href="gander-loop.html">The Gander Loop</a>
      <a href="eastport-peninsula.html">Eastport Peninsula</a>
      <a href="appleton-glenwood.html">Appleton &amp; Glenwood</a>
      <a href="lewisporte.html">Lewisporte &amp; Notre Dame Bay</a>
      <a href="glovertown.html">Glovertown, Traytown &amp; Cull&#39;s Harbour</a>
      <a href="twillingate.html">Twillingate, Fogo Island &amp; Change Islands</a>
    </div></li>
    <li class="nav-dropdown"><a href="#" aria-expanded="false" role="button">Services</a><div class="nav-dropdown-content">
      <a href="relocation.html">Relocation</a>
      <a href="investorsedge.html">RLP InvestorsEdge&trade;</a>
      <a href="property-management.html">Property Management</a>
      <a href="first-time-buyers.html">First-Time Buyers</a>
      <a href="home-inspections.html">Home Inspections</a>
      <a href="mortgage-calculator.html">Mortgage Calculator</a>
      <a href="photography.html">Photography</a>
      <a href="iguide.html">iGuide</a>
      <a href="video.html">Video</a>
      <a href="local-resources.html">Local Resources</a>
    </div></li>
    <li class="nav-dropdown"><a href="#" aria-expanded="false" role="button">Company</a><div class="nav-dropdown-content">
      <div class="nav-submenu"><a href="about.html">Meet the Team</a><div class="nav-submenu-content">
        <a href="mike-turner.html">Mike Turner</a>
        <a href="gaye-turner.html">Gaye Turner</a>
        <a href="dwayne-kean.html">Dwayne Kean</a>
        <a href="ashley-bullen.html">Ashley Bullen</a>
        <a href="danielle-pike.html">Danielle Pike</a>
        <a href="matt-wheaton.html">Matt Wheaton</a>
        <a href="kayla-tulk.html">Kayla Tulk</a>
        <a href="crystal-hynes.html">Crystal Hynes</a>
      </div></div>
      <a href="awards.html">Awards</a>
      <a href="testimonials.html">Testimonials</a>
      <a href="market-insights.html">Market Insights</a>
      <a href="shelter-foundation.html">Shelter Foundation</a>
      <a href="join-our-team.html">Join Our Team</a>
      <a href="contact.html">Contact</a>
    </div></li>
  </ul>
  <div class="nav-main-right">
    <a href="home-value.html" class="nav-cta-outline">Free Evaluation</a>
    <a href="tel:7092567999" class="nav-phone-pill">
      <svg viewBox="0 0 24 24"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.88.37 1.73.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c1.08.33 1.93.57 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
      <span class="nav-phone-num">709-256-7999</span>
    </a>
  </div>
</nav>'''


# ── Direction D hero (Mike 2026-09-07, "go with D"): the market verdict as the
# headline with the numbers in one lede sentence (real, crawlable copy -- the
# SEO value), the plain-English read, the seller line, the territory agent
# card and the actions on the left, and a "report cover" that mirrors the
# month's Facebook slide on the right (below the lede on a phone). ONE data
# window everywhere: the complete-month resale window (ytd_complete /
# yoy_complete), the same one the social card, PDF, newsletter and homepage
# quote. Gates as the card: no deltas below 15 sales or on a small sample; a
# small market gets "too few sales to call a trend" instead of a verdict.
_HERO_MONTHS = ["", "January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]
_COMMUNITY_SLUG_FOR_STEM = {"gander-and-area": "gander", "eastport": "eastport-peninsula",
                            "stjohns-avalon": "_default", "hvgb": "happy-valley-goose-bay"}
_SITE_TEAM_FALLBACK = {
    "realestategander.com": {"name": "The Turner Realty Team", "photo": "/images/team-photo.jpg",
                             "phone": "709-256-7999", "email": "office@realestategander.com",
                             "line": "Central Newfoundland’s #1 real estate team since 1998."},
    "avalonrealestate.ca": {"name": "Chris Morrison", "photo": "/images/chris-morrison.jpg",
                            "phone": "709-725-6520", "email": "cmorrison@royallepage.ca",
                            "line": "Royal LePage Turner Realty · St. John’s & the Avalon."},
    "goosebayrealestate.ca": {"name": "Karen Pomeroy & Roberta Primmer", "photo": "/images/karen-pomeroy.jpg",
                              "phone": "709-896-5001", "email": "goosebay@royallepage.ca",
                              "line": "The Dynamic Duo · Royal LePage Turner Realty, Happy Valley-Goose Bay."},
    # Lab West (D-1012-28/33): Mike Turner, Broker of Record, is the contact. No office address.
    "labwestrealty.com": {"name": "Mike Turner", "photo": "/images/mike-turner.jpg",
                          "phone": "709-256-7999", "email": "miketurner@royallepage.ca",
                          "line": "Broker of Record · Royal LePage Turner Realty."},
}


def _hero_market_meaning_lines(kind, small, region):
    """(seller_line, buyer_line): one shared source, _market_narration.meaning_lines."""
    return meaning_lines(kind, small, region)


def _hero_money(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    return f"${v / 1e6:.2f}M" if v >= 1e6 else f"${round(v / 1000):,}K"


def _hero_delta(pct, *, lower_is_better=False, pts=False):
    if pct is None:
        return ""
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return ""
    if (abs(pct) < 0.05) if pts else (abs(pct) < 0.5):
        return '<span class="ms-delta flat">flat YoY</span>'
    up = pct >= 0
    good = (not up) if lower_is_better else up
    num = f"{abs(pct):.1f} pts" if pts else f"{abs(pct):.0f}%"
    return f'<span class="ms-delta{"" if good else " down"}">{"&#9650;" if up else "&#9660;"} {num} YoY</span>'


# ── Market Minute audio player (Ship 2, 2026-09-12 port) ─────────────────
# tools/idx-cache/market-audio.json is written by emit-market-audio.py,
# keyed by region_key, {"url", "live", "period_label", ...}. Loaded once
# per process (module-level cache -- generate_page() is called once per
# region per --all run, so this avoids re-reading the manifest N times).
_MARKET_AUDIO_MANIFEST = None


def _market_audio_manifest() -> dict:
    global _MARKET_AUDIO_MANIFEST
    if _MARKET_AUDIO_MANIFEST is not None:
        return _MARKET_AUDIO_MANIFEST
    path = SCRIPT_DIR / "idx-cache" / "market-audio.json"
    if not path.exists():
        _MARKET_AUDIO_MANIFEST = {}
        return _MARKET_AUDIO_MANIFEST
    try:
        _MARKET_AUDIO_MANIFEST = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        _MARKET_AUDIO_MANIFEST = {}
    return _MARKET_AUDIO_MANIFEST


def _market_audio_player(cfg: dict) -> str:
    """The 'Hear this month's read' player -- renders ONLY when
    emit-market-audio.py has marked this region's clip live (MARKET_AUDIO=on
    at generation time). Conv #74: a missing/empty manifest, a region with
    no entry, or a preview-only (not-yet-live) entry all render nothing --
    never a broken player pointing at a URL that may not exist."""
    entry = _market_audio_manifest().get(cfg.get("region_key", ""))
    if not entry or not entry.get("live") or not entry.get("url"):
        return ""
    url = html.escape(entry["url"], quote=True)
    region = html.escape(cfg.get("region_key", ""), quote=True)
    # GA4 audio_play event, matching js/listing-audio.js's trackPlay() shape
    # (surface/region instead of surface/mls) so plays reach the weekly
    # digest (Conv #209). Inline, not a shared JS file, since this player has
    # no dedicated script -- same Conv #74 fail-safe (silently no-ops if
    # gtag isn't loaded, analytics must never break the player).
    onplay = (
        "if(window.gtag){try{gtag('event','audio_play',"
        "{surface:'market',region:'" + region + "'})}catch(e){}}"
    )
    return (
        '<div class="ms-audio">'
        '<audio controls preload="none" src="' + url + '" onplay="' + onplay + '"></audio>'
        '<p class="ms-audio-label">AI-generated narration of the numbers above &middot; '
        'Royal LePage Turner Realty</p>'
        '</div>'
    )


def _hero_agent(cfg):
    """The territory agent card: community-agent-map.json for the region's
    community (team / individual / duo), else the site's team. '' only when
    nothing at all resolves (Conv #74)."""
    try:
        cmap = (json.loads((SCRIPT_DIR / "community-agent-map.json").read_text(encoding="utf-8")) or {}).get("communities") or {}
    except Exception:  # noqa: BLE001
        cmap = {}
    stem = str(cfg.get("slug") or "").replace("-market-stats", "")
    stem = {"gander-mls": "gander-and-area", "stjohns-mls": "stjohns-avalon", "market-stats": "hvgb"}.get(stem, stem)
    entry = cmap.get(_COMMUNITY_SLUG_FOR_STEM.get(stem, stem)) or cmap.get("_default") or {}
    fb = _SITE_TEAM_FALLBACK.get(cfg.get("domain", ""), _SITE_TEAM_FALLBACK["realestategander.com"])
    name = entry.get("agent_name") or fb["name"]
    photos = [entry.get("photo") or fb["photo"]]
    if entry.get("variant") == "duo" and not entry.get("photo"):
        photos = ["/images/karen-pomeroy.jpg", "/images/roberta-primmer.jpg"]
    phone = entry.get("phone") or fb["phone"]
    email = entry.get("email") or fb["email"]
    line = entry.get("tagline") or fb["line"]
    label = html.escape(cfg.get("label", ""))
    digits = re.sub(r"\D", "", phone)
    subject = html.escape(f"The {cfg.get('label', '')} market", quote=True)
    imgs = "".join(f'<img src="{html.escape(p, quote=True)}" alt="{html.escape(name, quote=True)}" width="72" height="72" loading="lazy">' for p in photos)
    return (f'<div class="ms-agent"><div class="ms-agent-photos">{imgs}</div>'
            f'<div class="ms-agent-body"><h3>{html.escape(name)}</h3><p>{html.escape(line)}</p>'
            f'<p><a class="ms-agent-tel" href="tel:{digits}">{html.escape(phone)}</a> <span class="ms-agent-dot">&middot;</span> '
            f'<a href="mailto:{html.escape(email, quote=True)}?subject={subject}">Ask about the {label} market &rarr;</a></p></div></div>')


def _hero_share(cfg):
    url = (f"https://{cfg.get('domain', 'realestategander.com')}/{cfg.get('slug', '')}.html" if OUTPUT_ROOT[0]
           else f"https://{cfg.get('domain', 'realestategander.com')}/pages/{cfg.get('slug', '')}.html")
    u = html.escape(url, quote=True)
    return (f'<div class="ms-share"><span>Share this report</span>'
            f'<a href="https://www.facebook.com/sharer/sharer.php?u={u}" target="_blank" rel="noopener">'
            f'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"></path></svg>Facebook</a>'
            f'<a href="{u}" data-copy-link="{u}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"></path><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"></path></svg><span>Copy link</span></a></div>')


def _og_card_data(cfg, region):
    """Plain-value twin of build_hero_cover(), for the live-numbers og:image
    card (og_market_card.py) instead of the HTML report cover. Deliberately
    NOT derived by parsing build_hero_cover's HTML back apart -- same source
    reads, same gates (n<5 -> no card), plain text/bools a renderer can draw.

    Returns None when there isn't enough data for an honest card (n<5) --
    the caller keeps whatever og:image Ship 1 already resolved (the static
    branded photo) rather than showing an empty or misleading card.
    """
    yc = (region or {}).get("ytd_complete") or {}
    use_complete = bool(yc.get("count"))
    ytd = yc if use_complete else ((region or {}).get("ytd") or {})
    yoy = ((region or {}).get("yoy_complete") if use_complete else (region or {}).get("yoy")) or {}
    n = int(ytd.get("count") or 0)
    if n < 5:
        return None
    stable = n >= 15 and not yoy.get("small_sample")
    mb = (region or {}).get("market_balance") or {}
    year = region.get("ytd_complete_through_year") if use_complete else region.get("ytd_anchor_year")
    thru = int(region.get("ytd_complete_through_month") or 0) if use_complete else 0
    period_label = (f"{year} Snapshot \u00b7 Jan\u2013{_HERO_MONTHS[thru][:3]}" if thru
                    else f"{year} Snapshot")
    small_market = bool(mb.get("small_market")) or not stable
    if small_market:
        market_kind, market_line = "small", "Small market \u00b7 year-to-date view"
    elif mb.get("market_type_label"):
        market_kind = (mb.get("market_type") or "balanced").lower()
        mos = mb.get("months_of_supply")
        market_line = str(mb["market_type_label"])
        if mos:
            market_line += f" \u00b7 {float(mos):.1f} months of supply"
    else:
        market_kind, market_line = "balanced", ""

    def _delta(pct, *, lower_is_better=False, pts=False):
        if pct is None:
            return "", False
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            return "", False
        if (abs(pct) < 0.05) if pts else (abs(pct) < 0.5):
            return "flat", True
        up = pct >= 0
        good = (not up) if lower_is_better else up
        num = f"{abs(pct):.1f} pts" if pts else f"{abs(pct):.0f}%"
        return num, good

    tiles = []
    if ytd.get("median_price"):
        d, up = _delta(yoy.get("median_price_pct")) if (stable and use_complete) else ("", False)
        tiles.append({"label": "Median price", "value": _hero_money(ytd["median_price"]),
                      "delta": d, "up": up})
    if ytd.get("avg_sa") is not None:
        d, up = _delta(yoy.get("avg_sa_pts"), pts=True) if (stable and use_complete) else ("", False)
        tiles.append({"label": "Sale-to-list", "value": f"{float(ytd['avg_sa']):.1f}%",
                      "delta": d, "up": up})
    d, up = _delta(yoy.get("count_pct")) if stable else ("", False)
    tiles.append({"label": "Homes sold YTD", "value": f"{n:,}", "delta": d, "up": up})
    if ytd.get("avg_dom"):
        d, up = _delta(yoy.get("avg_dom_pct"), lower_is_better=True) if (stable and use_complete) else ("", False)
        tiles.append({"label": "Avg days on market", "value": f"{float(ytd['avg_dom']):.0f} days",
                      "delta": d, "up": up})

    thru_date = region.get("ytd_complete_through_date_iso") if use_complete else region.get("ytd_through_date_iso")
    source_line = (f"Source: NLAR MLS\u00ae \u00b7 data through "
                   f"{thru_date if thru_date else 'today'}")
    if thru_date:
        try:
            d_ = datetime.strptime(str(thru_date)[:10], "%Y-%m-%d")
            source_line = f"Source: NLAR MLS\u00ae \u00b7 data through {_HERO_MONTHS[d_.month][:3]} {d_.day}, {d_.year}"
        except ValueError:
            pass

    return {
        "region_label": cfg.get("label", ""),
        "period_label": period_label,
        "market_line": market_line,
        "market_kind": market_kind,
        "tiles": tiles,
        "source_line": source_line,
        "small_market": small_market,
    }


def build_hero_cover(cfg, region, spot):
    """The report cover: the month's Facebook slide as HTML (badge, region,
    verdict bar, 2x2 tiles with YoY, latest reported month, source)."""
    yc = (region or {}).get("ytd_complete") or {}
    use_complete = bool(yc.get("count"))
    ytd = yc if use_complete else ((region or {}).get("ytd") or {})
    yoy = ((region or {}).get("yoy_complete") if use_complete else (region or {}).get("yoy")) or {}
    n = int(ytd.get("count") or 0)
    if n < 5:
        return ""
    stable = n >= 15 and not yoy.get("small_sample")
    mb = (region or {}).get("market_balance") or {}
    year = region.get("ytd_complete_through_year") if use_complete else region.get("ytd_anchor_year")
    thru = int(region.get("ytd_complete_through_month") or 0) if use_complete else 0
    period = f"{year} Snapshot &middot; Jan&ndash;{_HERO_MONTHS[thru][:3]}" if thru else f"{year} Snapshot"
    if mb.get("small_market") or not stable:
        bar = '<span class="ms-cover-bar ms-cover-bar--small">Small market &middot; year-to-date view</span>'
    elif mb.get("market_type_label"):
        kind = (mb.get("market_type") or "balanced").lower()
        mos = mb.get("months_of_supply")
        bar = (f'<span class="ms-cover-bar ms-cover-bar--{kind}">{html.escape(mb["market_type_label"])}'
               + (f' &middot; {float(mos):.1f} months of supply' if mos else "") + "</span>")
    else:
        bar = ""
    tiles = []
    if ytd.get("median_price"):
        tiles.append(("Median price", _hero_money(ytd["median_price"]), _hero_delta(yoy.get("median_price_pct")) if (stable and use_complete) else ""))
    if ytd.get("avg_sa") is not None:
        tiles.append(("Sale-to-list", f"{float(ytd['avg_sa']):.1f}%", _hero_delta(yoy.get("avg_sa_pts"), pts=True) if (stable and use_complete) else ""))
    tiles.append(("Homes sold YTD", f"{n:,}", _hero_delta(yoy.get("count_pct")) if stable else ""))
    if ytd.get("avg_dom"):
        tiles.append(("Avg days on market", f"{float(ytd['avg_dom']):.0f} days", _hero_delta(yoy.get("avg_dom_pct"), lower_is_better=True) if (stable and use_complete) else ""))
    grid = "".join(f'<div class="ms-cover-tile"><span class="ms-cover-lbl">{l}</span><span class="ms-cover-num">{v}</span>{d}</div>' for l, v, d in tiles)
    cur = (spot or {}).get("current") or {}
    latest = ""
    if stable and cur.get("count") and (spot or {}).get("complete") and spot.get("cm"):
        latest = (f'<p class="ms-cover-latest">Latest reported &mdash; {_HERO_MONTHS[int(spot["cm"])]} {spot.get("cy")}: '
                  f'{int(cur["count"])} sale{"s" if int(cur["count"]) != 1 else ""}'
                  + (f', median {_hero_money(cur.get("median_price"))}' if cur.get("median_price") else "") + '.</p>')
    thru_date = region.get("ytd_complete_through_date_iso") if use_complete else region.get("ytd_through_date_iso")
    # NLAR §15(e) (2026-09-15 review): state the covered period + ownership notice.
    src = f"Based on MLS&reg; System data owned by the Newfoundland and Labrador Association of REALTORS&reg; covering the period Jan 1, {year} through "
    if thru_date:
        try:
            d = datetime.strptime(str(thru_date)[:10], "%Y-%m-%d")
            src += f"{_HERO_MONTHS[d.month][:3]} {d.day}, {d.year}."
        except ValueError:
            src += f"{thru_date}."
    else:
        src += "today."
    return (f'<div class="ms-cover"><span class="ms-cover-badge">MARKET UPDATE</span>'
            f'<p class="ms-cover-title">{html.escape(cfg.get("label", ""))}</p><p class="ms-cover-period">{period} &middot; resale</p>'
            + (f'<div>{bar}</div>' if bar else "") + f'<div class="ms-cover-grid">{grid}</div>' + latest
            + f'<p class="ms-cover-src">{src}</p></div>')


def build_hero(cfg, region, now, agg=None):
    """Direction D hero (see the block comment above)."""
    label = cfg.get("label", "This market")
    lab = html.escape(label)
    region = region or {}
    yc = region.get("ytd_complete") or {}
    use_complete = bool(yc.get("count"))
    ytd = yc if use_complete else (region.get("ytd") or {})
    yoy = (region.get("yoy_complete") if use_complete else region.get("yoy")) or {}
    n = int(ytd.get("count") or 0)
    stable = n >= 15 and not yoy.get("small_sample")
    mb = region.get("market_balance") or {}
    small = bool(mb.get("small_market")) or (n < 15)
    withheld = bool(mb.get("market_balance_withheld_reason")) or not mb
    year = region.get("ytd_complete_through_year") if use_complete else region.get("ytd_anchor_year")
    year = int(year or now.year)
    thru = int(region.get("ytd_complete_through_month") or 0) if use_complete else int(region.get("ytd_through_month") or 0)
    month = _HERO_MONTHS[thru] if thru else ""
    thru_iso = region.get("ytd_complete_through_date_iso") if use_complete else region.get("ytd_through_date_iso")

    # badge: ONE window
    try:
        d = datetime.strptime(str(thru_iso)[:10], "%Y-%m-%d")
        badge = (f'<span>Data through</span> {_HERO_MONTHS[d.month][:3]} {d.day}, {d.year} &middot; '
                 f'{"complete months" if use_complete else "year to date"} &middot; refreshed {now.strftime("%b")} {now.day}')
    except (ValueError, TypeError):
        badge = f'<span>Refreshed</span> {now.strftime("%B")} {now.day}, {now.year}'

    # headline by verdict
    kind = (mb.get("market_type") or "").lower()
    if n < 5:
        h1 = f"{lab} market,<br><em>{html.escape(month) if month else year}.</em>"
    elif small or withheld or kind not in ("seller", "buyer", "balanced"):
        h1 = (f"{lab}: <em>too few sales to call a trend.</em>" if small
              else f"{lab} market,<br><em>through {html.escape(month)}.</em>")
    else:
        word = {"seller": "seller&rsquo;s market.", "buyer": "buyer&rsquo;s market.", "balanced": "balanced market."}[kind]
        h1 = f"{lab} is a<br><em>{word}</em>"

    # lede: the numbers in one sentence
    med = ytd.get("median_price")
    dom = ytd.get("avg_dom")
    parts = []
    if n:
        parts.append(f"{n:,} home{'s' if n != 1 else ''} sold in {lab} through {html.escape(month)}" if month else f"{n:,} home{'s' if n != 1 else ''} sold in {lab} this year")
        if med:
            parts[-1] += f" at a median ${int(round(float(med))):,}"
    tail = []
    if stable:
        cp = yoy.get("count_pct")
        if cp is not None:
            tail.append("about the same number of sales as last year" if abs(float(cp)) < 0.5
                        else f"{abs(float(cp)):.0f}% {'more' if float(cp) >= 0 else 'fewer'} sales than last year")
        pp = yoy.get("median_price_pct") if use_complete else yoy.get("avg_price_pct")
        if pp is not None:
            tail.append("prices flat" if abs(float(pp)) < 0.5
                        else f"prices {'up' if float(pp) >= 0 else 'down'} {abs(float(pp)):.0f}%")
    if dom:
        tail.append(f"about {float(dom):.0f} days to sell")
    lede = ""
    if parts:
        lede = parts[0] + (" &mdash; " + ", ".join(tail) if tail else "") + "."
        mos = mb.get("months_of_supply")
        if not small and not withheld and mos and kind in ("seller", "buyer", "balanced"):
            lede += {"seller": f" With {float(mos):.1f} months of supply, well-priced homes are moving.",
                     "buyer": f" With {float(mos):.1f} months of supply, buyers have room to choose and negotiate.",
                     "balanced": f" With {float(mos):.1f} months of supply, neither side holds all the cards."}[kind]
        elif small:
            lede += " With so few sales, read these figures as direction, not precision."

    # plain-English read + seller line + caption
    read = ""
    try:
        spot = _spotlight_context(region, agg) if agg else None
        sents = [s_ for s_ in market_summary_sentences(cfg, region, agg, spot, complete_only=True) if s_][:2] if agg else []
        read = "".join(f'<p class="ms-hero-read">{s_}</p>' for s_ in sents)
    except Exception:  # noqa: BLE001
        spot, read = None, ""
    if n < 5:
        seller_line = ""
    elif withheld and not small:
        # St. John's neighbourhoods: balance is withheld because active counts
        # are only reliable city-wide -- say that, never "too few sales".
        seller_line = (f"Buyer's-or-seller's balance is measured city-wide, not for {label} on its own; "
                       f"the sold figures here are {label}'s own. Price to recent {label} comparables "
                       "— ask us for a free evaluation.")
    else:
        seller_line, _buyer = _hero_market_meaning_lines(kind, small, region)
    say = f'<p class="ms-hero-say"><strong>If you&rsquo;re selling:</strong> {html.escape(seller_line)}</p>' if seller_line else ""
    avg = ytd.get("avg_price")
    nc = (region.get("new_construction") or {})
    ncy = nc.get("ytd_complete") or nc.get("ytd") or {}
    cap = []
    if med and avg:
        cap.append(f"Median = the middle sale; the average (${int(round(float(avg))):,}) is pulled up by the biggest sales.")
    cap.append("Resale only" + (f" &mdash; {int(ncy.get('count') or 0)} new-build sale{'s' if int(ncy.get('count') or 0) != 1 else ''} counted separately below." if int(ncy.get("count") or 0) else "."))
    caption = f'<p class="ms-hero-caption">{" ".join(cap)}</p>'

    pages_dir = Path(__file__).resolve().parent.parent / "pages"
    ctas = [f'<a class="ms-btn" href="#ms-cta">Download the {lab} report (PDF)</a>',
            '<a class="ms-btn-sec" href="#ms-cta">Get this report monthly</a>']
    if (pages_dir / "home-value.html").exists():
        ctas.append('<a class="ms-btn-sec" href="home-value.html">What&rsquo;s my home worth?</a>')
    cover = build_hero_cover(cfg, region, spot)

    return f'''
<div class="ms">

  <!-- ═══════ HERO (Direction D, 2026-09-07) ═══════ -->
  <div class="ms-hero">
    <div class="ms-hero-inner ms-hero-inner--wide">
      <div class="ms-update-badge">{badge}</div>
      <div class="ms-eyebrow">{lab} real estate market &middot; statistics through {html.escape(month) + " " if month else ""}{year}</div>
      <h1>{h1}</h1>
      {f'<p class="ms-hero-lede">{lede}</p>' if lede else ''}
      <div class="ms-hero-grid2">
        <div class="ms-hero-left">
          {read}
          {say}
          {caption}
          {_market_audio_player(cfg)}
          <div class="ms-hero-ctas">{"".join(ctas)}</div>
          {_hero_agent(cfg)}
          {_hero_share(cfg)}
        </div>
        {f'<div class="ms-hero-cover">{cover}</div>' if cover else ''}
      </div>
    </div>
  </div>'''


def build_stat_cell(value_html, label, delta_html="", delta_html2=None):
    """Build a single stat cell in a strip.

    `delta_html2` opts the cell into the two-row WOWA layout (month-over-month
    above year-over-year). Passing it AT ALL — even as an empty string — emits
    the stack wrapper, which is what keeps a strip's numbers and labels on one
    baseline when only some cells have a comparison to show. The three existing
    single-delta call sites omit it and are unaffected."""
    if delta_html2 is None:
        delta_line = f"\n          {delta_html}" if delta_html else ""
    else:
        rows = "".join(f"\n            {d}" for d in (delta_html, delta_html2) if d)
        delta_line = f'\n          <div class="ms-delta-stack">{rows}\n          </div>'
    return f'''        <div class="ms-annual-stat">
          <div class="ms-annual-num">{value_html}</div>{delta_line}
          <div class="ms-stat-lbl">{label}</div>
        </div>'''


def build_full_year_strip(cfg, region):
    """Build the prior full-year results strip."""
    baseline_year = cfg.get("baseline_year", 2025)
    by_year = region.get("by_year", {}) if region else {}
    yr_data = by_year.get(str(baseline_year), {})

    if not yr_data:
        return ""

    count = yr_data.get("count")
    avg_price = yr_data.get("avg_price")
    avg_sa = yr_data.get("avg_sa")
    avg_dom = yr_data.get("avg_dom")
    total_vol = yr_data.get("total_volume")

    explainers = cfg.get("explainers", {})

    cells = "\n".join([
        build_stat_cell(fmt_int(count), "Units Sold"),
        build_stat_cell(fmt_price_k(avg_price), "Avg Sale Price"),
        build_stat_cell(fmt_pct(avg_sa), "Sale-to-List Ratio"),
        build_stat_cell(fmt_dom(avg_dom), "Avg Days on Market"),
        build_stat_cell(fmt_volume(total_vol), "Total Volume"),
    ])

    return f'''
  <!-- ═══════ {baseline_year} FULL YEAR ═══════ -->
  <div class="ms-annual">
    <div class="ms-annual-inner">
      <div class="ms-strip-label">{baseline_year} Full Year Results</div>
      <div class="ms-annual-grid">
{cells}
      </div>
    </div>
  </div>
  <p class="ms-explainer" style="padding:12px 24px; max-width:1000px; margin:0 auto;">{explainers.get("units_sold", "")}</p>'''


def build_prior_ytd_strip(cfg, region):
    """Build the prior-year same-period comparison strip."""
    baseline_year = cfg.get("baseline_year", 2025)
    prior_ytd = region.get("prior_ytd", {}) if region else {}
    through_month = region.get("ytd_through_month") if region else None

    if not prior_ytd:
        return ""

    period_text = build_period_through(
        through_month, region.get("ytd_through_day") if region else None,
        region.get("current_month_partial", False) if region else False)

    cells = "\n".join([
        build_stat_cell(fmt_int(prior_ytd.get("count")), "Units Sold"),
        build_stat_cell(fmt_price_k(prior_ytd.get("avg_price")), "Avg Sale Price"),
        build_stat_cell(fmt_pct(prior_ytd.get("avg_sa")), "Sale-to-List Ratio"),
        build_stat_cell(fmt_dom(prior_ytd.get("avg_dom")), "Avg Days on Market"),
        build_stat_cell(fmt_int(prior_ytd.get("at_100_plus")),
                        "Sold at 100%+ Asking"),
    ])

    return f'''
  <!-- ═══════ {baseline_year} YTD ANCHOR ═══════ -->
  <div class="ms-ytd">
    <div class="ms-ytd-inner">
      <div class="ms-strip-label">{baseline_year} Year to Date — {period_text}</div>
      <div class="ms-annual-grid">
{cells}
      </div>
    </div>
  </div>'''


def build_current_ytd_strip(cfg, region):
    """Build the current-year YTD strip with YoY deltas."""
    baseline_year = cfg.get("baseline_year", 2025)
    current_year = baseline_year + 1
    ytd = region.get("ytd", {}) if region else {}
    yoy = region.get("yoy", {}) if region else {}
    through_month = region.get("ytd_through_month") if region else None

    if not ytd:
        return ""

    period_text = build_period_through(
        through_month, region.get("ytd_through_day") if region else None,
        region.get("current_month_partial", False) if region else False)
    suffix = f"vs YTD {baseline_year}"

    explainers = cfg.get("explainers", {})

    cells = "\n".join([
        build_stat_cell(
            fmt_int(ytd.get("count")), "Units Sold",
            fmt_delta(yoy.get("count_pct"), suffix)),
        build_stat_cell(
            fmt_price_k(ytd.get("avg_price")), "Avg Sale Price",
            fmt_delta(yoy.get("avg_price_pct"), suffix)),
        build_stat_cell(
            fmt_pct(ytd.get("avg_sa")), "Sale-to-List Ratio",
            fmt_delta(yoy.get("avg_sa_pts"), suffix, is_pts=True)),
        build_stat_cell(
            fmt_dom(ytd.get("avg_dom")), "Avg Days on Market",
            fmt_delta(yoy.get("avg_dom_pct"), suffix)),
        build_stat_cell(
            fmt_int(ytd.get("at_100_plus")), "Sold at 100%+ Asking",
            fmt_delta(yoy.get("at100_pct"), suffix) if yoy.get("at100_pct") is not None else ""),
    ])

    return f'''
  <!-- ═══════ {current_year} YTD ═══════ -->
  <div class="ms-ytd">
    <div class="ms-ytd-inner">
      <div class="ms-strip-label red">{current_year} Year to Date — {period_text}</div>
      <div class="ms-annual-grid">
{cells}
      </div>
    </div>
  </div>
  <p class="ms-explainer" style="padding:12px 24px; max-width:1000px; margin:0 auto;">{explainers.get("yoy_comparison", "")}</p>'''


def _ppsf_howto():
    """Three things a reader needs before quoting a $/sq ft figure back to an
    agent. Sits under the community table, where the number first appears."""
    return '''
      <div class="ms-ppsf-howto">
        <h3 class="ms-mix-head" style="margin-top:0;">How to read price per square foot</h3>
        <div class="ms-ppsf-howto-grid">
          <p><strong>It levels out size.</strong> A large home and a small home can be compared on the same footing, which a median price alone cannot do.</p>
          <p><strong>It counts finished floor area only.</strong> Land, water frontage, garages and unfinished basements are in the price but not the square footage, so acreage and waterfront homes read high.</p>
          <p><strong>It is not a pricing formula.</strong> Smaller homes sell for more per square foot than larger ones. Use it to compare communities, then <a href="/pages/home-value.html">ask for a proper evaluation</a>.</p>
        </div>
      </div>'''


def build_sale_outcomes_section(cfg, region):
    """How fast homes really sell, and whether sellers get their asking price --
    the two things an average days-on-market and an average sale-to-list hide.
    Reads the aggregator's sale_outcomes block. Convention #74: '' when the
    block is absent (under 20 qualifying sales); the price-cut sentence drops
    out on its own when too few records carry both list prices."""
    so = (region or {}).get("sale_outcomes") or {}
    speed = [s for s in (so.get("speed") or []) if s.get("count")]
    asking = so.get("asking") or {}
    if not so or len(speed) < 2 or not asking:
        return ""
    label = html.escape(cfg.get("label", "this market"))
    tones = ["fast", "quick", "slow", "stale"]
    all_speed = so.get("speed") or []
    segs = "".join(
        f'<span class="ms-speed-seg ms-speed-seg--{tones[min(i, 3)]}" style="flex:{max(s["share_pct"], 7)} 1 0;">'
        f'<b>{s["share_pct"]:.0f}%</b></span>'
        for i, s in enumerate(all_speed) if s.get("count"))
    keys = "".join(
        f'<span><i class="ms-speed-key ms-speed-seg--{tones[min(i, 3)]}"></i>{html.escape(s["label"])}'
        f' &middot; {s["count"]:,} sales</span>'
        for i, s in enumerate(all_speed) if s.get("count"))
    first, last = all_speed[0], all_speed[-1]
    speed_line = ""
    if first.get("avg_sa") and last.get("avg_sa"):
        try:
            _ws = datetime.strptime(so["window_start"], "%Y-%m-%d")
            _we = datetime.strptime(so["window_end"], "%Y-%m-%d")
            _win = f"From {_ws.strftime('%b')} {_ws.day}, {_ws.year} to {_we.strftime('%b')} {_we.day}, {_we.year}, homes"
        except (KeyError, ValueError, TypeError):
            _win = "Homes"
        speed_line = (f'<p class="ms-outcome-line">{_win} that sold in {html.escape(first["label"].lower())} went for '
                      f'<strong>{first["avg_sa"]:.1f}%</strong> of asking. Homes that took '
                      f'{html.escape(last["label"].lower())} to sell went for '
                      f'<strong>{last["avg_sa"]:.1f}%</strong>.</p>')

    cuts = so.get("price_cuts") or {}
    cuts_line = ""
    if cuts.get("cut_pct") is not None:
        cuts_line = f'<strong>{cuts["cut_pct"]:.0f}%</strong> of sellers lowered their price before selling'
        if cuts.get("median_cut"):
            cuts_line += f', by a median of <strong>${cuts["median_cut"]:,.0f}</strong>'
        cuts_line += "."
        if cuts.get("extra_days") and cuts["extra_days"] > 0:
            cuts_line += f' Those homes took <strong>{cuts["extra_days"]:.0f} days</strong> longer to sell.'
        cuts_line = f'<p class="ms-outcome-line">{cuts_line}</p>'

    return f'''
  <!-- ═══════ SALE OUTCOMES (speed + asking price) ═══════ -->
  <div class="ms-section ms-section--dark2">
    <div class="ms-section-inner">
      <div class="ms-section-head">
        <div class="ms-eyebrow">Speed &amp; Asking Price</div>
        <h2>How Fast Homes Sell, <em>and For How Much.</em></h2>
        <p>An average hides two very different groups: the homes that sell in days and the ones that sit. {so.get("n", 0):,} {label} resale homes sold in the last twelve months, split by how long they took and how the sold price compared with the asking price.</p>
      </div>
      <div class="ms-outcome-grid">
        <div class="ms-outcome-card">
          <h3 class="ms-mix-head" style="margin-top:0;">How fast do homes really sell?</h3>
          <div class="ms-speed-bar" role="img" aria-label="Share of sales by time to sell">{segs}</div>
          <div class="ms-speed-keys">{keys}</div>
          {speed_line}
        </div>
        <div class="ms-outcome-card">
          <h3 class="ms-mix-head" style="margin-top:0;">Are sellers getting their asking price?</h3>
          <div class="ms-ask-tiles">
            <div><b class="ms-ask--over">{asking.get("over_pct", 0):.0f}%</b><span>sold over asking</span></div>
            <div><b>{asking.get("at_pct", 0):.0f}%</b><span>sold at asking</span></div>
            <div><b class="ms-ask--under">{asking.get("under_pct", 0):.0f}%</b><span>sold under asking</span></div>
          </div>
          {cuts_line}
        </div>
      </div>
      <p class="ms-chart-sub" style="margin-top:14px;">Trailing 12 months &middot; residential resale &middot; sold price against the last asking price &middot; shares only, no individual sale prices</p>
    </div>
  </div>'''


# Fleet glossary (pages/real-estate-glossary-nl.html on every site) -- the
# "How to Read These Numbers" block links each term to its anchor there, and
# these defaults define the three measures the market pages use that no YAML
# ever defined (2026-09-07). A YAML `explainers:` entry overrides any of them.
GLOSSARY_URL = "/pages/real-estate-glossary-nl.html"
GLOSSARY_DEFAULT_EXPLAINERS = {
    "price_per_sqft": ("The sold price divided by the home's finished floor area, shown as the median across "
                       "recent resale homes. It lets you compare communities and styles of house without size "
                       "getting in the way. Only about half of listings record a floor area, so every figure "
                       "says how many sales it is built on; 5 to 9 sales is flagged as limited, and under 5 is "
                       "not shown. Land, waterfront and garages are in the price but not the square footage."),
    "months_of_supply": ("How long it would take to sell every home currently listed at the recent "
                         "pace of sales — active listings divided by average monthly sales over the last "
                         "12 months. Under 5 months is a seller's market, 5–7 balanced, 7 or more a "
                         "buyer's market. In small communities a couple of listings can swing it, so the "
                         "verdict is withheld below 15 sales a year."),
    "snlr": ("Homes sold in a month as a share of homes newly listed that month — the CREA measure of "
             "whether demand is keeping up with fresh supply. Under 40% favours buyers, over 60% "
             "favours sellers. Shown as a rolling three-month figure because a single month swings on "
             "a handful of sales."),
    "new_construction": ("Every headline figure here is a resale. A sale counts as new construction when the home "
                         "sold within a year of being built, or was listed as new, under construction or to be built; "
                         "those sales are shown on their own in the What's Selling section so a new-build premium "
                         "never inflates the resale median."),
    "median_vs_average": ("The median is the middle sale — half sold for more, half for less — and it "
                          "shrugs off one unusually expensive home. The average adds every sale and "
                          "divides, so a single high sale in a small community can pull it up sharply. "
                          "In small markets, trust the median."),
}



# ── FAQ (visible Q&A + FAQPage JSON-LD), 2026-09-07 ─────────────────────────
# Mike: "build the FAQ schema on the market pages." Every answer is assembled
# from numbers already on the page (same region/spot/market_balance inputs the
# sections use), regenerates daily with the page, and is only emitted when its
# inputs exist (Conv #74). Google requires FAQ content to be VISIBLE, so the
# same list renders as a "Quick answers" block in the Reference tab.
def _faq_money(v):
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return None


def build_market_faqs(cfg, region, agg, spot):
    """[(question, answer)] for this region, plain text (no markup)."""
    if not region:
        return []
    label = cfg.get("label", "This market")
    mb = region.get("market_balance") or {}
    ytd = region.get("ytd_complete") or region.get("ytd") or {}
    prior = region.get("prior_ytd_complete") or region.get("prior_ytd") or {}
    thru_m = region.get("ytd_complete_through_month")
    year = region.get("ytd_complete_through_year") or region.get("ytd_year") or region.get("ytd_anchor_year")
    window = (f"January through {MONTH_NAMES[int(thru_m) - 1]} {year}" if thru_m and year else f"{year} year to date")
    faqs = []
    # 1. buyer's or seller's?
    thr = mb.get("mos_thresholds") or {}
    smax, bmax = thr.get("seller_max", 5), thr.get("balanced_max", 7)
    if mb.get("small_market"):
        n = int(ytd.get("count") or 0)
        faqs.append((f"Is {label} a buyer's or seller's market right now?",
                     f"{label} is too small a market to call: with {n} sales {window}, a couple of listings "
                     f"coming or going swings the months-of-supply figure, so we don't publish a verdict. Read the "
                     f"year-to-date price and days-on-market figures as direction, not precision."))
    elif mb.get("market_type_label") and mb.get("months_of_supply") is not None and mb.get("active_inventory"):
        rate = mb.get("monthly_sold_rate")
        faqs.append((f"Is {label} a buyer's or seller's market right now?",
                     f"{label} is currently a {mb['market_type_label'].lower()}: {mb['active_inventory']} homes are for "
                     f"sale and the market has been absorbing about {rate:.0f} a month, which is roughly "
                     f"{mb['months_of_supply']} months of supply. Under {smax:g} months of supply favours sellers; "
                     f"{bmax:g} or more favours buyers."))
    elif region.get("market_balance_withheld_reason"):
        faqs.append((f"Is {label} a buyer's or seller's market right now?",
                     f"Market balance isn't published for {label}. {region['market_balance_withheld_reason']}"))
    # 2. median price
    med, avg = _faq_money(ytd.get("median_price")), _faq_money(ytd.get("avg_price"))
    if med and (ytd.get("count") or 0) >= 5:
        a = f"The median sale price in {label} is {med} ({window}, NLAR MLS® residential sales)"
        a += f", and the average sale price is {avg}." if avg else "."
        a += " The median is the middle sale, so one unusually expensive home doesn't distort it."
        faqs.append((f"What is the median home price in {label}?", a))
    # 3. days on market
    dom = ytd.get("avg_dom")
    if dom is not None and (ytd.get("count") or 0) >= 5:
        a = f"Homes in {label} have averaged {float(dom):.0f} days on the market before selling ({window})."
        if spot and spot.get("complete") and (spot.get("current") or {}).get("avg_dom") is not None:
            a += (f" In {MONTH_NAMES[spot['cm'] - 1]} {spot['cy']} alone the average was "
                  f"{float(spot['current']['avg_dom']):.0f} days.")
        faqs.append((f"How long does it take to sell a home in {label}?", a))
    # 4. how many sold
    n, pn = int(ytd.get("count") or 0), int(prior.get("count") or 0)
    if n >= 5:
        a = f"{n} homes sold in {label} {window} on the MLS® System"
        a += f", compared with {pn} over the same window a year earlier." if pn else "."
        faqs.append((f"How many homes have sold in {label} this year?", a))
    # 4b. new construction (Mike 2026-09-07: separated from resale)
    nc = region.get("new_construction") or {}
    ncy = nc.get("ytd_complete") or nc.get("ytd") or {}
    n_new = int(ncy.get("count") or 0)
    if n_new >= 3 and nc.get("share_pct_ytd") is not None:
        a = (f"{n_new} newly built homes sold in {label} {window} — about {nc['share_pct_ytd']:.0f}% of all "
             f"residential sales there")
        ncm = _faq_money(ncy.get("median_price"))
        a += f", at a median price of {ncm}" if ncm else ""
        a += (". The headline statistics on this page are resale only; new construction (homes sold within a year "
              "of being built, or listed as new, under construction or to be built) is counted separately.")
        faqs.append((f"How much new construction is selling in {label}?", a))
    # 5. source
    faqs.append((f"Where do the {label} market statistics come from?",
                 "Every figure on this page is computed from the Newfoundland and Labrador Association of REALTORS® "
                 "MLS® System (residential sales), refreshed daily by Royal LePage Turner Realty. Recent months keep "
                 "filling in as sold notices are processed, so the latest month is always shown as 'reported so far'."))
    return faqs


def build_faq_jsonld(faqs):
    if not faqs:
        return ""
    data = {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q,
                            "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faqs]}
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False) + '</script>'


_FAQ_WORDS = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}


def build_faq_section(cfg, faqs):
    """Visible 'Quick answers' block (the FAQPage schema's on-page counterpart)."""
    if not faqs:
        return ""
    items = "".join(
        f'''
        <details class="ms-faq-item" style="border-bottom:1px solid rgba(255,255,255,.08);padding:12px 0;">
          <summary style="cursor:pointer;font-family:'Raleway',sans-serif;font-weight:700;font-size:15px;color:#fff;">{html.escape(q)}</summary>
          <p class="ms-explainer" style="padding:10px 0 0;margin:0;">{html.escape(a)}</p>
        </details>''' for q, a in faqs)
    return f'''
  <!-- ═══════ QUICK ANSWERS (FAQPage) ═══════ -->
  <div class="ms-section ms-section--dark2">
    <div class="ms-section-inner">
      <div class="ms-eyebrow">Quick answers</div>
      <h2>{html.escape(cfg.get("label", "This market"))} <em>in {_FAQ_WORDS.get(len(faqs), str(len(faqs)))} questions.</em></h2>
      <div class="ms-faq">{items}
      </div>
    </div>
  </div>'''


def build_stat_glossary_section(cfg):
    """Consumer-education glossary — 'How to Read These Numbers'.

    Surfaces the per-stat explainer copy that's defined per-region in the YAML
    `explainers:` block but otherwise has NO home on the page: avg_sale_price,
    sale_to_list, days_on_market, sold_at_100. (units_sold + yoy_comparison
    already render as inline paragraph explainers under their strips, so they're
    deliberately excluded here to avoid duplication.) Defines the jargon a
    consumer just met in the headline stat strips. Convention #74: renders only
    the terms that have copy; returns '' if none — so community pages that omit
    sold_at_100 simply show the 3 terms they define, and a page with no
    explainers shows nothing. Convention #32: copy is factual/educational, no
    fabricated benchmarks (lives in the reviewed YAML, same as the other slots)."""
    explainers = dict(GLOSSARY_DEFAULT_EXPLAINERS)
    explainers.update(cfg.get("explainers", {}) or {})   # YAML copy wins
    terms = [
        ("avg_sale_price", "Average Sale Price", "median-vs-average-price"),
        ("median_vs_average", "Median vs. Average", "median-vs-average-price"),
        ("sale_to_list", "Sale-to-List Ratio", "sale-to-list-ratio"),
        ("days_on_market", "Days on Market", "days-on-market"),
        ("sold_at_100", "Sold at 100%+ Asking", "sale-to-list-ratio"),
        ("months_of_supply", "Months of Supply", "months-of-supply"),
        ("snlr", "Sales-to-New-Listings Ratio", "sales-to-new-listings-ratio"),
        ("new_construction", "New Construction vs. Resale", "new-construction"),
        ("price_per_sqft", "Price per Square Foot", "price-per-square-foot"),   # anchor added to the glossary page 2026-09-18
    ]
    items = "".join(
        f'''
        <div class="ms-gloss-item">
          <dt class="ms-gloss-term"><a href="{GLOSSARY_URL}#{anchor}">{label}</a></dt>
          <dd class="ms-gloss-def">{explainers[key]}</dd>
        </div>'''
        for key, label, anchor in terms if explainers.get(key)
    )
    if not items:
        return ""
    items += (f'''
        <div class="ms-gloss-item">
          <dt class="ms-gloss-term"><a href="{GLOSSARY_URL}">Full real estate glossary &rarr;</a></dt>
          <dd class="ms-gloss-def">100+ plain-English terms for buying, selling and reading the market in Newfoundland &amp; Labrador.</dd>
        </div>''')
    return f'''
  <!-- ═══════ STAT GLOSSARY (consumer education) ═══════ -->
  <div class="ms-section ms-section--dark2">
    <div class="ms-section-inner">
      <div class="ms-eyebrow">How to Read These Numbers</div>
      <dl class="ms-glossary">{items}
      </dl>
    </div>
  </div>'''


def build_ten_year_section(cfg, region):
    """Build the 10-year trend table + chart placeholder."""
    baseline_year = cfg.get("baseline_year", 2025)
    current_year = baseline_year + 1
    start_year = cfg.get("ten_year_start", 2016)
    hist_sales = cfg.get("ten_year_historical_sales", [])
    hist_prices = cfg.get("ten_year_historical_prices", [])
    label = cfg.get("label", "")
    explainers = cfg.get("explainers", {})

    # Get current-year data from aggregator
    ytd = region.get("ytd", {}) if region else {}
    by_year = region.get("by_year", {}) if region else {}

    # Build combined data: historical + baseline_year from by_year + current YTD
    years = []
    prices = []
    sales = []

    for i, yr in enumerate(range(start_year, baseline_year)):
        if i < len(hist_prices) and i < len(hist_sales):
            years.append(str(yr))
            prices.append(hist_prices[i])
            sales.append(hist_sales[i])

    # Baseline year from aggregator (or last historical entry)
    by_data = by_year.get(str(baseline_year), {})
    if by_data:
        years.append(str(baseline_year))
        prices.append(by_data.get("avg_price", 0))
        sales.append(by_data.get("count", 0))
    elif len(hist_prices) > (baseline_year - start_year):
        idx = baseline_year - start_year
        years.append(str(baseline_year))
        prices.append(hist_prices[idx])
        sales.append(hist_sales[idx])

    # Current YTD
    if ytd.get("avg_price"):
        years.append(f"{current_year} YTD")
        prices.append(ytd["avg_price"])
        sales.append(ytd.get("count", 0))

    # Build table rows
    rows = []
    prev_price = None
    for i, yr in enumerate(years):
        p = prices[i]
        s = sales[i]
        if prev_price and prev_price > 0:
            pct = ((p - prev_price) / prev_price) * 100
            change_html = price_change_str(pct)
        else:
            change_html = "—"
        prev_price = p

        rows.append(f'''          <tr>
            <td>{yr}</td>
            <td>{fmt_price_full(p)}</td>
            <td>{fmt_int(s)}</td>
            <td>{change_html}</td>
          </tr>''')

    table_html = "\n".join(rows)

    # Chart data as JS arrays
    chart_labels = json.dumps(years)
    chart_prices = json.dumps([round(p) for p in prices])
    chart_sales = json.dumps([int(s) for s in sales])

    price_max = cfg.get("chart_price_max", 400000)
    units_max = cfg.get("chart_units_max", 250)

    # Count total listings approx
    total_listings = sum(int(s) for s in sales)

    return f'''
  <!-- ═══════ 10-YEAR MARKET TREND ═══════ -->
  <div class="ms-section ms-section--dark2">
    <div class="ms-section-inner">
      <div class="ms-section-head">
        <div class="ms-eyebrow">{start_year}&ndash;{current_year} Market Trend</div>
        <h2>Sale Prices and Sales<br><em>in {label}.</em></h2>
        <p>Average sale price and total residential sales from {start_year} through early {current_year} ({current_year} is year to date, a partial year).</p>
      </div>

      <div class="ms-chart-wrap">
        <div class="ms-chart-title">Average Sale Price vs. Number of Sales</div>
        <div class="ms-chart-sub">{cfg['geo_description']} &middot; {start_year}–{current_year} YTD &middot; Based on MLS&reg; System data owned by the Newfoundland and Labrador Association of REALTORS&reg; covering the period Jan 1, {start_year} through {current_year} year-to-date (~{total_listings:,} listings)</div>
        <div class="ms-chart-legend">
          <span><span class="ms-legend-dot" style="background:#22c55e;"></span> Avg Sale Price</span>
          <span><span class="ms-legend-dot" style="background:rgba(234,0,42,0.7);"></span> Number of Sales</span>
          <button type="button" class="ms-chart-reset-zoom" data-reset-zoom="chart10Year">Scroll or pinch to zoom &middot; Reset</button>
        </div>
        <div class="ms-chart-canvas-wrap">
          <canvas id="chart10Year" height="300"></canvas>
        </div>
      </div>

      <div class="ms-table-scroll">
        <table class="ms-10yr-table">
          <thead>
            <tr>
              <th>Year</th>
              <th>Avg Sale Price</th>
              <th>Sales</th>
              <th>Price Change</th>
            </tr>
          </thead>
          <tbody>
  {table_html}
          </tbody>
        </table>
      </div>

      <p class="ms-explainer" style="margin-top:20px;">{explainers.get("ten_year_table", "")}</p>
    </div>
  </div>''', {
        "labels": chart_labels,
        "prices": chart_prices,
        "sales": chart_sales,
        "price_max": price_max,
        "units_max": units_max,
    }


def to_quarterly(monthly):
    """Aggregate the 12-month arrays into 4 quarters for SMALL markets
    (Conv #21 small-sample discipline, Mike-flagged 2026-06-12: with ~1
    sale/month, monthly trend lines mislead — clipped spikes, floating
    points, mostly-zero count charts). Units/at100 = sums; price/dom/sa =
    units-weighted means. None-months are skipped; an empty quarter is None."""
    def q_chunks(arr):
        return [arr[0:3], arr[3:6], arr[6:9], arr[9:12]]
    out = {}
    for yr in ("prior", "current"):
        units_q = []
        for chunk in q_chunks(monthly[f"{yr}_units"]):
            vals = [u for u in chunk if u]
            units_q.append(sum(vals) if vals else None)
        out[f"{yr}_units"] = units_q
        out[f"{yr}_at100"] = [
            (sum(a for a in chunk if a) if any(a is not None for a in chunk) else None)
            for chunk in q_chunks(monthly[f"{yr}_at100"])]
        for metric in ("price", "dom", "sa"):
            vals_q = []
            for mchunk, uchunk in zip(q_chunks(monthly[f"{yr}_{metric}"]),
                                      q_chunks(monthly[f"{yr}_units"])):
                pairs = [(v, u or 1) for v, u in zip(mchunk, uchunk) if v is not None]
                if pairs:
                    tot_u = sum(u for _, u in pairs)
                    vals_q.append(round(sum(v * u for v, u in pairs) / tot_u, 1))
                else:
                    vals_q.append(None)
            out[f"{yr}_{metric}"] = vals_q
    return out


def build_monthly_charts_section(cfg, region):
    """Build the monthly breakdown section with chart canvases."""
    baseline_year = cfg.get("baseline_year", 2025)
    current_year = baseline_year + 1
    label = cfg.get("label", "")
    geo = cfg.get("geo_description", "")
    explainers = cfg.get("explainers", {})

    monthly = extract_monthly_arrays(region, baseline_year)

    # Small-market mode (Conv #21): median monthly sales < 3 across both years
    # → quarterly buckets. Monthly lines at this volume produce clipped spikes
    # + floating points (Appleton & Glenwood precedent, Mike 2026-06-12).
    _unit_vals = sorted(u for u in (monthly["prior_units"] + monthly["current_units"]) if u is not None)
    _median_units = _unit_vals[len(_unit_vals) // 2] if _unit_vals else 0
    small_market = bool(_unit_vals) and _median_units < 3
    if small_market:
        monthly = to_quarterly(monthly)
        monthly["_labels"] = ["Q1", "Q2", "Q3", "Q4"]
        monthly["_small_market"] = True

    def js_arr(arr):
        return json.dumps(arr)

    return f'''
  <!-- ═══════ MONTHLY BREAKDOWN ═══════ -->
  <div class="ms-section">
    <div class="ms-section-inner">
      <div class="ms-section-head">
        <div class="ms-eyebrow">{"Quarterly Breakdown" if small_market else "Monthly Breakdown"}</div>
        <h2>{baseline_year} vs. {current_year}<br><em>By the Numbers.</em></h2>
        <p>{f"Quarter-by-quarter comparison for {label}. In a market this size (a handful of sales per month), quarterly groupings give a truthful read — monthly lines would mislead." if small_market else f"Month-by-month comparison across all key metrics for {label}."}</p>
      </div>

      <!-- Chart: Average Sale Price (full width) -->
      <div class="ms-chart-wrap">
        <div class="ms-chart-title">Average Sale Price — Homes Sold</div>
        <div class="ms-chart-sub">{geo} &middot; {baseline_year} vs. {current_year}</div>
        <div class="ms-chart-legend">
          <span class="ms-legend-toggle" data-chart="chartPrice" data-dataset="0"><span class="ms-legend-dot" style="background:#22c55e;"></span> {baseline_year}</span>
          <span class="ms-legend-toggle" data-chart="chartPrice" data-dataset="1"><span class="ms-legend-diamond" style="background:#fff;"></span> {current_year}</span>
        </div>
        <div class="ms-chart-canvas-wrap">
          <canvas id="chartPrice" height="260"></canvas>
        </div>
      </div>

      <!-- Charts: Units Sold + DOM -->
      <div class="ms-charts-2col">
        <div class="ms-chart-wrap">
          <div class="ms-chart-title">Units Sold</div>
          <div class="ms-chart-sub">{geo} &middot; {baseline_year} vs. {current_year}</div>
          <div class="ms-chart-legend">
            <span class="ms-legend-toggle" data-chart="chartUnits" data-dataset="0"><span class="ms-legend-dot" style="background:#22c55e;"></span> {baseline_year}</span>
            <span class="ms-legend-toggle" data-chart="chartUnits" data-dataset="1"><span class="ms-legend-diamond" style="background:#fff;"></span> {current_year}</span>
          </div>
          <div class="ms-chart-canvas-wrap">
            <canvas id="chartUnits" height="220"></canvas>
          </div>
        </div>
        <div class="ms-chart-wrap">
          <div class="ms-chart-title">Average Days on Market</div>
          <div class="ms-chart-sub">{geo} &middot; {baseline_year} vs. {current_year}</div>
          <div class="ms-chart-legend">
            <span class="ms-legend-toggle" data-chart="chartDOM" data-dataset="0"><span class="ms-legend-dot" style="background:#22c55e;"></span> {baseline_year}</span>
            <span class="ms-legend-toggle" data-chart="chartDOM" data-dataset="1"><span class="ms-legend-diamond" style="background:#fff;"></span> {current_year}</span>
          </div>
          <div class="ms-chart-canvas-wrap">
            <canvas id="chartDOM" height="220"></canvas>
          </div>
        </div>
      </div>

      <!-- Charts: S/A Ratio + At 100% -->
      <div class="ms-charts-2col">
        <div class="ms-chart-wrap">
          <div class="ms-chart-title">Average Sold-to-Ask Ratio (%)</div>
          <div class="ms-chart-sub">{geo} &middot; {baseline_year} vs. {current_year}</div>
          <div class="ms-chart-legend">
            <span class="ms-legend-toggle" data-chart="chartSA" data-dataset="0"><span class="ms-legend-dot" style="background:#22c55e;"></span> {baseline_year}</span>
            <span class="ms-legend-toggle" data-chart="chartSA" data-dataset="1"><span class="ms-legend-diamond" style="background:#fff;"></span> {current_year}</span>
          </div>
          <div class="ms-chart-canvas-wrap">
            <canvas id="chartSA" height="220"></canvas>
          </div>
        </div>
        <div class="ms-chart-wrap">
          <div class="ms-chart-title"># Sold at 100% or More of Asking</div>
          <div class="ms-chart-sub">{geo} &middot; {baseline_year} vs. {current_year}</div>
          <div class="ms-chart-legend">
            <span class="ms-legend-toggle" data-chart="chartAt100" data-dataset="0"><span class="ms-legend-dot" style="background:#22c55e;"></span> {baseline_year}</span>
            <span class="ms-legend-toggle" data-chart="chartAt100" data-dataset="1"><span class="ms-legend-diamond" style="background:#fff;"></span> {current_year}</span>
          </div>
          <div class="ms-chart-canvas-wrap">
            <canvas id="chartAt100" height="220"></canvas>
          </div>
        </div>
      </div>

      <p class="ms-explainer">{explainers.get("monthly_charts", "")}</p>
    </div>
  </div>''', monthly


def build_hpi_section(cfg):
    """Build the HPI Tableau embed section (master pages only)."""
    if not cfg.get("hpi_embed"):
        return ""
    workbook = cfg.get("hpi_workbook", "NewfoundlandHPIDashboard-member/Intro")
    workbook_escaped = workbook.replace("/", "&#47;")

    return f'''
<section class="stats-tableau-section" style="background:#111; padding:60px 20px; text-align:center;">
  <style>@media(max-width:768px){{.stats-tableau-section{{padding:32px 12px !important}}}}</style>
  <div class="stats-section-inner" style="max-width:1040px; margin:0 auto;">
    <h2 style="color:#f2f2f2; font-family:'Raleway',sans-serif; font-weight:900; margin-bottom:8px;">Newfoundland &amp; Labrador MLS&reg; Home Price Index</h2>
    <p style="color:rgba(255,255,255,0.85); margin-bottom:32px;">The official benchmark price index for our market, maintained by NLAR and CREA. Explore 20-year price history and compare neighbourhood benchmarks.</p>
    <div style="overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:6px">
    <div class='tableauPlaceholder' id='viz_nlar_hpi_dashboard' style='position:relative;min-width:320px;background:#fff'>
      <noscript>
        <a href='https://public.tableau.com/views/{workbook}' target='_blank' rel='noopener'>
          <img alt='Newfoundland and Labrador MLS HPI dashboard' src='https://public.tableau.com/static/images/Ne/{workbook.split("/")[0]}/Intro/1_rss.png' style='border:none' />
        </a>
      </noscript>
      <object class='tableauViz' style='display:none;'>
        <param name='host_url' value='https%3A%2F%2Fpublic.tableau.com%2F' />
        <param name='embed_code_version' value='3' />
        <param name='site_root' value='' />
        <param name='name' value='{workbook_escaped}' />
        <param name='tabs' value='yes' />
        <param name='toolbar' value='yes' />
        <param name='animate_transition' value='yes' />
        <param name='display_static_image' value='yes' />
        <param name='display_spinner' value='yes' />
        <param name='display_overlay' value='yes' />
        <param name='display_count' value='yes' />
        <param name='language' value='en-US' />
      </object>
    </div>
    <script type='text/javascript'>
      var divElement = document.getElementById('viz_nlar_hpi_dashboard');
      var vizElement = divElement.getElementsByTagName('object')[0];
      if (window.innerWidth < 480) {{ vizElement.style.width = '100%'; vizElement.style.minHeight = '650px'; }}
      else if (window.innerWidth < 768) {{ vizElement.style.width = '100%'; vizElement.style.minHeight = '750px'; }}
      else if (window.innerWidth < 1024) {{ vizElement.style.width = '100%'; vizElement.style.minHeight = '850px'; }}
      else {{ vizElement.style.width = '100%'; vizElement.style.minHeight = '900px'; }}
      var scriptElement = document.createElement('script');
      scriptElement.src = 'https://public.tableau.com/javascripts/api/viz_v1.js';
      vizElement.parentNode.insertBefore(scriptElement, vizElement);
    </script>
    </div>
    <p style="color:#888; font-size:12px; margin-top:16px;">Data: <strong style="color:#bbb;">MLS&reg; Home Price Index</strong> via NLAR and CREA. <a href="https://public.tableau.com/views/{workbook}" target="_blank" rel="noopener" style="color:#9ec5fe;">View on Tableau Public &rarr;</a></p>
    <p style="color:#bbb; font-size:14px; margin-top:20px;">Prefer to browse it region by region and town by town? Our <a href="https://realestategander.com/pages/nl-housing-market-data.html" target="_blank" rel="noopener" style="color:#9ec5fe;">NL Housing Market Data</a> page breaks down median sale prices for every region and community in Newfoundland and Labrador, updated nightly.</p>
  </div>
</section>'''


def build_cta(cfg):
    """Build the CTA section — the market-report PDF download capture form
    (name+email -> instant per-region PDF + monthly newsletter). Region carried
    via data-attrs so BoldTrailForms.marketReport builds the right form
    and the subscribe endpoint resolves the territory agent server-side
    (Gander parity — task #81 follow-up, 2026-07-29: the container previously
    carried no region context, so the Goosebay market-stats page silently
    offered the "Happy Valley / Goose Bay" default regardless of intent, and
    would have been wrong the moment a 2nd Goosebay market-stats page shipped)."""
    heading = cfg.get("cta_heading", "Know What Your Home Is Worth.")
    sub = cfg.get("cta_sub", "")
    phone = cfg.get("cta_phone", "709-896-5001")
    phone_display = cfg.get("cta_phone_display", f"Call {phone}")
    phone_digits = phone.replace("-", "")
    region_key = html.escape(cfg.get("region_key", ""), quote=True)
    label = html.escape(cfg.get("label", ""), quote=True)

    return f'''
  <!-- ═══════ CTA ═══════ -->
  <div class="ms-cta" id="ms-cta">
    <div class="ms-cta-inner">
      <h2>{heading}</h2>
      <p>{sub}</p>
      <div class="ms-cta-btns">
        <div id="rf-stats-report" data-region-key="{region_key}" data-region-label="{label}" data-source="market-stats-page" style="margin:30px auto 20px;max-width:520px;"></div>
        <script>(function(){{try{{var u=new URLSearchParams(location.search).get('utm_source');if(u){{document.getElementById('rf-stats-report').dataset.source='market-stats-page:'+u.replace(/[^a-z0-9_-]/gi,'').slice(0,40);}}}}catch(e){{}}BoldTrailForms.marketReport('#rf-stats-report')}})()</script>
        <a href="home-value.html" class="ms-cta-white">Get a Free Market Evaluation</a>
        <a href="tel:{phone_digits}" class="ms-cta-outline">{phone_display}</a>
      </div>
    </div>
  </div>'''


def build_disclaimer():
    """Build the disclaimer section."""
    return '''
  <!-- ═══════ DISCLAIMER ═══════ -->
  <div class="ms-disclaimer">
    <div class="ms-disclaimer-inner">
      Data sourced from the Newfoundland &amp; Labrador Association of REALTORS&reg; MLS&reg; System. Headline statistics are residential resale only; new construction is reported separately in the What&rsquo;s Selling section. Not included in statistics: commercial, private, exclusive, pocket listings, rentals, farms, vacant land, co-listings. MLS&reg;, Multiple Listing Service&reg;, and the associated logos are owned by The Canadian Real Estate Association (CREA) and identify the quality of services provided by real estate professionals who are members of CREA.
    </div>
  </div>

</div>'''


def build_footer():
    """Build the site footer. Per-site _footer.html partial if present
    (Avalon/Goosebay, Conv #64); otherwise the hardcoded Gander default below.

    Note (2026-09-08 fleet review): this Gander-default template is a plain
    (non-f) string -- it contains literal JS braces (`function() {`) that
    would break outright if converted to an f-string -- so its hardcoded
    `window.TURNER_SITE='gander'` is fixed up with a targeted .replace()
    below rather than an f-string conversion. This branch is DEAD for Goose
    Bay today (tools/market-stats-config/_footer.html exists, so
    FOOTER_PARTIAL.exists() is True and this fallback never runs) -- the
    real live bug was the partial itself: it ended at </footer> with NO
    trailing scripts at all (verified on the live pages/market-stats.html --
    zero footer.js/nav-auth.js/turner-network.js/chat-widget.js, and
    window.TURNER_SITE never set, not merely set wrong). Fixed by adding the
    missing script block to _footer.html directly. This substitution is kept
    as a defensive backstop for whichever site's fallback branch DOES run."""
    if FOOTER_PARTIAL.exists():
        return FOOTER_PARTIAL.read_text()
    _footer_default = '''
<footer class="site-footer">
  <div class="footer-inner">
    <div class="footer-brand">
      <img loading="lazy" src="../images/rlp-logo.png" alt="Royal LePage Turner Realty" width="80" height="80">
      <p>Brokerage: Royal LePage Turner Realty<br>204 Airport Boulevard, Gander, NL A1V 1L6<br><a href="tel:7092567999">709-256-7999</a> &middot; <a href="mailto:office@realestategander.com">office@realestategander.com</a></p>
    </div>
    <div>
      <div class="footer-heading">Quick Links</div>
      <ul class="footer-links">
        <li><a href="../index.html">Home</a></li>
        <li><a href="/listings/">Listings</a></li>
        <li><a href="about.html">About Us</a></li>
        <li><a href="contact.html">Contact</a></li>
        <li><a href="join-our-team.html">Join Our Team</a></li>
      </ul>
    </div>
    <div>
      <div class="footer-heading">Services</div>
      <ul class="footer-links">
        <li><a href="sell-your-home.html">Selling</a></li>
        <li><a href="/listings/">Buying</a></li>
        <li><a href="home-value.html">Free Home Evaluation</a></li>
        <li><a href="/listings/">MLS&reg; Search</a></li>
        <li><a href="/listings/commercial/">Commercial</a></li>
      </ul>
    </div>
    <div>
      <div class="footer-heading">Areas We Serve</div>
      <ul class="footer-links">
        <li><a href="gander.html">Gander</a></li>
        <li><a href="appleton-glenwood.html">Appleton &amp; Glenwood</a></li>
        <li><a href="gambo.html">Gambo</a></li>
        <li><a href="glovertown.html">Glovertown</a></li>
        <li><a href="lewisporte.html">Lewisporte &amp; Notre Dame Bay</a></li>
        <li><a href="twillingate.html">Twillingate &amp; Fogo Island</a></li>
        <li><a href="eastport-peninsula.html">Eastport Peninsula</a></li>
        <li><a href="gander-loop.html">The Gander Loop</a></li>
      </ul>
    </div>
  </div>
  <div class="footer-bottom">
    <p>&copy; 1998&ndash;2026 Royal LePage Turner Realty (2014) Inc. &middot; Est. 1998 &middot; Turner Realty Team since 2009. Serving Newfoundland &amp; Labrador.</p>
    <p>Each office independently owned and operated. Not intended to solicit buyers or sellers currently under contract.</p>
  </div>
<!-- crea-compliance:v1 -->
<aside class="crea-compliance" role="contentinfo" aria-label="REALTOR and MLS trademark statement">
  <p>The information contained on this page is based in whole or in part on information that is provided by members of The Canadian Real Estate Association, who are responsible for its accuracy. CREA reproduces and distributes this information as a service for its members and assumes no responsibility for its accuracy.</p>
  <p>REALTOR&reg;, REALTORS&reg;, and the REALTOR&reg; logo are certification marks owned or controlled by The Canadian Real Estate Association (CREA) and identify real estate professionals who are members of CREA. The trademarks MLS&reg;, Multiple Listing Service&reg;, and the associated logos identify professional services rendered by REALTOR&reg; members of CREA.</p>
</aside>
<!-- /crea-compliance:v1 -->
</footer>
<script src="../js/footer.js?v=20260909-footer-converge"></script>
<script src="../js/nav-auth.js?v=20260818-portal" defer></script>
<script src="../js/app-shell.js?v=20260920-app8" defer></script>
<script src="/js/lead-shim.js"></script>
<script>
(function() {
    var sdk = new BoldTrail.Sdk();
    sdk.Leads.track && sdk.Leads.track({ lead_channel: 'be54b577-026d-4a65-b1ae-2a49ecd1bcb8' });
})();
</script>
<script src="../js/mobile-nav.js" defer></script>
  <script>window.TURNER_SITE='gander';</script>
  <script src="../js/turner-network.js" defer></script>
<script>
document.addEventListener("DOMContentLoaded",function(){if(typeof BoldTrailForms!=="undefined"){BoldTrailForms.exitIntent("listingAlerts");BoldTrailForms.stickyBar("listingAlerts","Get Listing Alerts");}});
</script>
<script src="../js/chat-widget.js?v=20260613-mobilebar" async></script>'''
    return _footer_default.replace(
        "window.TURNER_SITE='gander';",
        "window.TURNER_SITE='%s';window.TURNER_API_ORIGIN='%s';" % (_SITE_CFG["site_key"], _SITE_CFG["api_url"]))


# ── Market Summary phrase tables ────────────────────────────────────────────
# The ONLY adjectives this page generates. Each is a (floor, phrase) list read
# top-down: the first row whose floor the delta clears wins. Keeping them as
# data rather than prose in the builder means the wording is auditable in one
# place and the same delta always produces the same sentence.
COUNT_PHRASES = [(15, "well ahead of"), (5, "ahead of"), (-5, "roughly even with"),
                 (-15, "behind"), (None, "well behind")]
PRICE_PHRASES = [(10, "up sharply from"), (3, "up from"),
                 (-3, "essentially flat against"), (-10, "down from"),
                 (None, "down sharply from")]
# Days on market: a NEGATIVE delta is fewer days, i.e. a faster market.
DOM_PHRASES = [(15, "slower than"), (5, "slightly slower than"),
               (-5, "about the same as"), (-15, "faster than"),
               (None, "much faster than")]


def _ytd_year(cfg, region, now=None):
    """The year the live YTD figures ACTUALLY cover.

    Must come from the data, never from `baseline_year + 1`. baseline_year is
    hand-keyed (it only advances when Mike re-runs the NLAR Matrix export), so
    the old derivation silently mislabels live aggregates the moment the
    calendar rolls over: on 2027-01-01 every page would render live 2027
    numbers under a "2026 YTD" heading — fresh data, wrong label, no error.
    Conv #74 fallback chain: the aggregator's own ytd_year -> the real calendar
    year -> the legacy config guess.
    """
    if region and region.get("ytd_year"):
        return int(region["ytd_year"])
    if now is not None:
        return now.year
    return cfg.get("baseline_year", 2025) + 1


def _last_completed_month(now):
    """(year, month) of the last COMPLETED calendar month relative to `now`.
    Recording the July report in early August must show July, not August."""
    y, m = now.year, now.month
    return (y - 1, 12) if m == 1 else (y, m - 1)


def _prev_calendar_month(year, month):
    """Calendar month before (year, month). December/January rollover in ONE
    place — the January build compares against the previous December."""
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _thin(bucket):
    """True when a comparison month is missing or below the small-sample floor
    (Convention #21) — the same test _month_delta applies before dividing."""
    return not bucket or bucket.get("count", 0) < 5


def _month_delta(current, prior, key, suffix, *, is_pts=False, lower_is_better=False):
    """Percent (or point) change for one metric between two month buckets.

    Returns '' when the prior month is too thin to compare against — a 2-sale
    July last year makes any percentage meaningless (Convention #21, same floor
    the aggregator's calc_yoy uses)."""
    if not prior or prior.get("count", 0) < 5:
        return ""
    cur_v, pri_v = current.get(key), prior.get(key)
    if cur_v is None or pri_v is None or not pri_v:
        return ""
    delta = (cur_v - pri_v) if is_pts else (cur_v - pri_v) / pri_v * 100
    return fmt_delta(delta, suffix, is_pts=is_pts, lower_is_better=lower_is_better)


def _month_fully_reported(agg, year, month):
    """True once the board has reported past the end of (year, month).

    NLAR files closings weeks after they happen — the lag observed 2026-07-28
    was 19 days — so a month rendered too early shows a fraction of its real
    sales. Left unguarded that is not a cosmetic problem: on 2026-07-28 the
    feed held 4 July sales against 38 for July 2025, which would have rendered
    a ~-89% collapse that is pure reporting lag. The prior-month floor in
    _month_delta does NOT catch this — it only tests the year-ago bucket.

    The test is the aggregator's own `latest_close_date`: if the newest closing
    anywhere in the feed still falls inside the month (or earlier), the month
    is still filling in. Deliberately conservative — a latest close of the 30th
    still means anything filed after the fetch is missing.

    Fails CLOSED (returns False) when the field is absent or unparseable:
    withholding a comparison costs a percentage, publishing a wrong one costs
    Mike's credibility on camera. Warns on stderr rather than degrading in
    silence, per the same reasoning as the STALE BASELINE guard in main()."""
    raw = (agg or {}).get("latest_close_date")
    if not raw:
        print("[MARKET-STATS] MONTHLY SPOTLIGHT: aggregator has no "
              "latest_close_date — cannot tell whether the spotlight month is "
              "fully reported, so year-over-year changes are withheld. If this "
              "persists, the aggregator's shape has changed and this guard "
              "needs rewiring.", file=sys.stderr)
        return False
    try:
        latest = datetime.strptime(str(raw)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        print(f"[MARKET-STATS] MONTHLY SPOTLIGHT: could not parse "
              f"latest_close_date={raw!r} — year-over-year changes withheld.",
              file=sys.stderr)
        return False
    return (latest.year, latest.month) > (year, month)


def compute_record_claims(region, cfg, spot):
    """Milestones the data on hand can actually prove.

    Two record windows exist and they are not interchangeable:
      * by_year_month — ~25 months of real monthly buckets. Monthly records are
        claimed against this and MUST say how long the window is, because "the
        highest median on record" means something very different over two years
        than over twenty.
      * the hand-keyed decade arrays in YAML — ANNUAL averages only. A monthly
        figure can never be compared against them; only a year against a year.

    Deliberately excluded, each for a reason: projections ("on pace for") are
    forecasts, not records; ties never claim, because "highest ever" that merely
    equals a previous month invites an easy contradiction; thin buckets are
    excluded because a 3-sale month sets meaningless records constantly; and
    there is no fastest-DOM claim, since a single quick sale in a thin month
    produces one without the market having changed at all.

    Returns [] freely — no claim is the normal case."""
    if not spot or not spot.get("complete"):
        return []
    bym = (region or {}).get("by_year_month") or {}
    cur_key = f"{spot['cy']}-{spot['cm']:02d}"
    cur = spot["current"]
    n_months = len(bym)
    month_name = MONTH_NAMES[spot["cm"] - 1]
    claims = []

    def _others(field):
        """Every OTHER month's value for `field`, from buckets thick enough to
        count. Excluding thin months from the comparison set is what stops a
        2-sale month's freak median from blocking a legitimate record."""
        return [b.get(field) for k, b in bym.items()
                if k != cur_key and not _thin(b) and b.get(field) is not None]

    if n_months >= 18 and not _thin(cur):
        med = cur.get("median_price")
        others = _others("median_price")
        if med is not None and others and med > max(others):
            claims.append({
                "kind": "monthly_median_record",
                "text": (f"{month_name}'s median of {fmt_price_full(med)} is the "
                         f"highest monthly median in our {n_months}-month record."),
            })

        hi = cur.get("max_price")
        others = _others("max_price")
        if hi is not None and others and hi > max(others):
            claims.append({
                "kind": "highest_sale_record",
                "text": (f"The month's top sale of {fmt_price_full(hi)} is the "
                         f"highest single sale in our {n_months}-month record."),
            })

        cnt = cur.get("count")
        others = _others("count")
        if cnt is not None and others and cnt > max(others):
            claims.append({
                "kind": "busiest_month_record",
                "text": (f"{fmt_int(cnt)} sales made {month_name} the busiest "
                         f"month in our {n_months}-month record."),
            })

    # Year-to-date against the hand-keyed decade of ANNUAL averages. Gated on a
    # real sample and on being far enough into the year that a YTD average is a
    # meaningful number rather than a handful of January sales.
    ytd = (region or {}).get("ytd") or {}
    decade = cfg.get("ten_year_historical_prices") or []
    through_month = (region or {}).get("ytd_through_month") or 0
    if (len(decade) >= 8 and (ytd.get("count") or 0) >= 50 and through_month >= 6
            and ytd.get("avg_price") is not None):
        vals = [v for v in decade if isinstance(v, (int, float))]
        if vals and ytd["avg_price"] > max(vals):
            claims.append({
                "kind": "ytd_vs_decade",
                "text": (f"The {region.get('ytd_year') or ''} year-to-date average of "
                         f"{fmt_price_full(ytd['avg_price'])} is higher than any "
                         f"full-year average in the decade table below.").replace("  ", " "),
            })

    return claims


def build_records_callouts(claims, limit=2):
    """Render milestone cards. Capped — a wall of records reads as marketing
    noise and devalues the one that matters. '' when there is nothing to say."""
    if not claims:
        return ""
    cards = "".join(
        f'\n        <div class="ms-record-card">'
        f'<div class="ms-record-eyebrow">Milestone</div>'
        f'<div class="ms-record-text">{c["text"]}</div></div>'
        for c in claims[:limit])
    return f'\n      <div class="ms-records">{cards}\n      </div>'


def build_monthly_spotlight_section(cfg, region, agg, spot):
    """The month just finished, against the same month a year ago.

    This is the top of Mike's monthly video: he records the report the month
    right after it finishes filing, so the section shows whichever month
    `_spotlight_context` resolved -- data-driven (Mike 2026-08-03), not a
    calendar guess; see that function's own docstring. Everything else on the
    page is YTD or annual — this is the only place a single month stands on
    its own.

    Convention #74: `spot` is None when the region has no monthly data at all
    (the IDX cache only holds ~2 years, so a thin sub-region can fall off the
    edge). Convention #32: the "reported through" line is mandatory — NLAR
    posts closings weeks after they happen, so an early build genuinely
    undercounts the newest month and the page must say so."""
    if not region or not spot:
        return ""
    cy, cm = spot["cy"], spot["cm"]
    current = spot["current"]
    prior = spot["yoy_prior"]
    mom_prior = spot["mom_prior"]
    complete = spot["complete"]
    py, pm = _prev_calendar_month(cy, cm)

    month_name = MONTH_NAMES[cm - 1]
    label = cfg.get("label", "")
    explainers = cfg.get("explainers", {})

    # Short suffixes — the strip is five columns wide, and a long phrase wraps to
    # two lines under every number on a 1080p screen share. The MoM suffix names
    # the year only when it differs (the January build reads "vs Dec 2025").
    suffix = f"vs {MONTH_ABBR[cm - 1]} {cy - 1}"
    mom_suffix = (f"vs {MONTH_ABBR[pm - 1]}" if py == cy
                  else f"vs {MONTH_ABBR[pm - 1]} {py}")

    def _dyoy(key, **kw):
        return _month_delta(current, prior, key, suffix, **kw) if complete else ""

    def _dmom(key, **kw):
        return _month_delta(current, mom_prior, key, mom_suffix, **kw) if complete else ""

    # Pass both rows (MoM above YoY, WOWA's order) whenever the month is
    # complete, so every cell carries the stack wrapper and the five numbers stay
    # baseline-aligned even where one comparison is suppressed for thin data.
    def _cell(value_html, lbl, key, **kw):
        if not complete:
            return build_stat_cell(value_html, lbl)
        return build_stat_cell(value_html, lbl, _dmom(key, **kw), _dyoy(key, **kw))

    cells = "\n".join([
        _cell(fmt_int(current.get("count")), "Units Sold", "count"),
        _cell(fmt_price_k(current.get("median_price")), "Median Sale Price", "median_price"),
        _cell(fmt_price_k(current.get("avg_price")), "Avg Sale Price", "avg_price"),
        _cell(fmt_dom(current.get("avg_dom")), "Avg Days on Market", "avg_dom",
              lower_is_better=True),
        _cell(fmt_pct(current.get("avg_sa")), "Sale-to-List Ratio", "avg_sa",
              is_pts=True),
    ])

    highest = current.get("max_price")
    highest_html = (
        f'<div class="ms-spotlight-highest">Highest sale this month: '
        f'<span>{fmt_price_full(highest)}</span></div>'
        if highest else ""
    )

    through = (agg or {}).get("latest_close_date")
    through_html = (
        f'<div class="ms-spotlight-note">Based on MLS&reg; closings reported '
        f'through {through}. Sales are reported to the board after closing, so '
        f'the most recent weeks fill in over time.</div>'
        if through else ""
    )
    foot = (f'\n      <div class="ms-spotlight-foot">{highest_html}{through_html}</div>'
            if (highest_html or through_html) else "")

    # Only promise the year-ago comparison in the heading when it is actually
    # rendered — an incomplete month shows bare figures and no deltas.
    heading = (f'{month_name} {cy} <em>vs. {month_name} {cy - 1}.</em>' if complete
               else f'{month_name} {cy} <em>so far.</em>')

    # Milestones, if the month earned any. compute_record_claims re-derives the
    # spotlight context rather than taking it as an argument so this section
    # stays callable standalone; it gates itself on `complete` internally.
    records = build_records_callouts(
        compute_record_claims(region, cfg, {
            "cy": cy, "cm": cm, "current": current, "complete": complete}))

    prior_note = ""
    if not complete:
        # Takes precedence over the thin-prior note: if the month isn't in yet,
        # that is the reason the percentages are missing, whatever else is true.
        through_txt = f" reported through {through}" if through else ""
        prior_note = (f'\n      <p class="ms-explainer" style="margin-top:16px;">'
                      f'<strong>{month_name} {cy} is still being reported.</strong> '
                      f'Sales are filed with the board after closing, so these '
                      f'figures count only the {fmt_int(current.get("count"))} '
                      f'sales{through_txt} and will rise over the coming weeks. '
                      f'Year-over-year changes are withheld until the month is '
                      f'complete — measuring a partial month against a finished '
                      f'one would show a decline that is not real. The '
                      f'year-to-date numbers below are the reliable read.</p>')
    elif _thin(prior) or _thin(mom_prior):
        # Which comparison is missing, and why. Each prior is tested separately:
        # a thin year-ago month can suppress the YoY row while MoM still renders.
        yoy_thin, mom_thin = _thin(prior), _thin(mom_prior)
        prior_month_name = MONTH_NAMES[pm - 1]
        if yoy_thin and mom_thin:
            missing = (f'Neither {prior_month_name} {py} nor {month_name} {cy - 1} '
                       f'had enough sales in {label} to compare against fairly, so '
                       f'no change figures are shown here.')
        elif yoy_thin:
            missing = (f'{month_name} {cy - 1} had too few sales in {label} to compare '
                       f'against fairly, so only the change since {prior_month_name} '
                       f'is shown.')
        else:
            missing = (f'{prior_month_name} {py} had too few sales in {label} to compare '
                       f'against fairly, so only the change from a year ago is shown.')
        prior_note = (f'\n      <p class="ms-explainer" style="margin-top:16px;">'
                      f'{missing} The year-to-date numbers below are the reliable '
                      f'read.</p>')
    elif explainers.get("monthly_spotlight"):
        prior_note = (f'\n      <p class="ms-explainer" style="margin-top:16px;">'
                      f'{explainers["monthly_spotlight"]}</p>')

    return f'''
  <!-- ═══════ MONTHLY SPOTLIGHT ═══════ -->
  <div class="ms-spotlight">
    <div class="ms-spotlight-inner">
      <div class="ms-spotlight-head">
        <div class="ms-eyebrow">Monthly Spotlight</div>
        <h2>{heading}</h2>
      </div>
      <div class="ms-annual-grid">
{cells}
      </div>{records}{foot}{prior_note}
    </div>
  </div>'''


# ── Market Summary phrase tables ────────────────────────────────────────────
# The ONLY adjectives this page generates. Each is a (floor, phrase) list read
# top-down: the first row whose floor the delta clears wins. Keeping them as
# data rather than prose in the builder means the wording is auditable in one
# place and the same delta always produces the same sentence.


def _phrase(delta_pct, table):
    """First phrase whose floor the delta clears. '' when the delta is None —
    every caller treats that as 'omit this clause' rather than guessing."""
    if delta_pct is None:
        return ""
    for floor, text in table:
        if floor is None or delta_pct >= floor:
            return text
    return ""


def _spotlight_context(region, agg):
    """The month the spotlight is showing, resolved ONCE.

    Both the spotlight and the narrative read this, so the two can never
    disagree about which month is on screen or whether it is complete — a
    summary that describes June while the numbers above it show July is the
    kind of error nobody catches until it is in the video.

    Data-driven, not calendar-driven (Mike 2026-08-03): walks `by_year_month`
    back from the newest bucket to the newest one _month_fully_reported()
    accepts -- the same rule fb-post.py / market-report-pdf.py already use to
    pick their month. The old `_last_completed_month(now)` picked "last
    calendar month" regardless of whether a NEWER month was already fully
    reported by build time (built on the 3rd of a new month, it showed the
    month before last -- a full month stale relative to the social posts).
    Falls back to the newest month WITH data, marked incomplete, when none is
    fully reported yet -- same always-something-renders posture as before
    (Convention #74)."""
    if not region:
        return None
    bym = region.get("by_year_month") or {}
    months = sorted((k for k, v in bym.items() if (v or {}).get("count")), reverse=True)
    if not months:
        return None
    cur_key = None
    complete = False
    for k in months:
        ky, km = int(k[:4]), int(k[5:7])
        if _month_fully_reported(agg, ky, km):
            cur_key = k
            complete = True
            break
    if cur_key is None:
        cur_key = months[0]
    cy, cm = int(cur_key[:4]), int(cur_key[5:7])
    current = bym[cur_key]
    py, pm = _prev_calendar_month(cy, cm)
    return {
        "cy": cy, "cm": cm,
        "current": current,
        "yoy_prior": bym.get(f"{cy - 1}-{cm:02d}"),
        "mom_prior": bym.get(f"{py}-{pm:02d}"),
        "complete": complete,
    }


def market_summary_sentences(cfg, region, agg, spot, complete_only=False):
    """The market in plain language -- the SENTENCES. build_market_summary_section
    wraps them in HTML for the page; market-report-newsletter-send.py and the
    agent talking points reuse them verbatim (2026-09-07), so one generator
    speaks for every surface. Assembled from the numbers already on the
    page — and the opening script for Mike's monthly video.

    Every sentence is a template with a gate. Nothing here interprets, predicts,
    or reaches for an adjective that is not in the phrase tables above, because
    this is broker-branded copy about other people's largest asset. A sentence
    whose data is thin or missing returns '' and simply does not appear; if
    fewer than two survive, the whole section is omitted rather than published
    as a one-line 'summary'."""
    if not region:
        return []   # sentences, not markup
    label = cfg.get("label", "This market")
    # complete_only (2026-09-07): email/agent consumers quote the complete-month
    # window so the sentence agrees with the tiles beside it (the page keeps its
    # labelled partial window). Falls back to the partial window when no complete
    # month exists yet.
    if complete_only and (region.get("ytd_complete") or {}).get("count"):
        ytd = region.get("ytd_complete") or {}
        yoy = region.get("yoy_complete") or {}
        _thru = region.get("ytd_complete_through_month")
        ytd_phrase = (f"Through {MONTH_NAMES[int(_thru) - 1]}" if _thru else "Year to date")
    else:
        ytd = region.get("ytd") or {}
        yoy = region.get("yoy") or {}
        ytd_phrase = "Year to date"
    mb = region.get("market_balance") or {}
    snlr = region.get("snlr") or {}
    baseline_year = cfg.get("baseline_year", 2025)

    sentences = []
    complete = bool(spot and spot["complete"])

    # 1/2. Lede — the finished month, or an explicit hand-off to YTD when the
    # month is still being filed (same reasoning as the spotlight's guard).
    if spot and complete and (spot["current"].get("count") or 0) >= 5:
        cur = spot["current"]
        month_name = MONTH_NAMES[spot["cm"] - 1]
        s = (f"{label} recorded {fmt_int(cur.get('count'))} MLS&reg; sales in "
             f"{month_name} {spot['cy']} at a median price of "
             f"{fmt_price_full(cur.get('median_price'))}")
        prior = spot["yoy_prior"]
        if not _thin(prior) and prior.get("count"):
            d = (cur["count"] - prior["count"]) / prior["count"] * 100
            ph = _phrase(d, COUNT_PHRASES)
            if ph:
                s += (f" — {ph} the {fmt_int(prior['count'])} sales of "
                      f"{month_name} {spot['cy'] - 1}")
        sentences.append(s + ".")
    elif spot and not complete:
        month_name = MONTH_NAMES[spot["cm"] - 1]
        sentences.append(
            f"With {month_name} {spot['cy']} still being reported to the board, "
            f"the year-to-date picture is the reliable read.")

    # 3. Year to date, against the same stretch of last year.
    if (ytd.get("count") or 0) >= 5 and not yoy.get("small_sample"):
        s = f"{ytd_phrase}, {fmt_int(ytd['count'])} homes have sold"   # window-aware (2026-09-07)
        ph = _phrase(yoy.get("count_pct"), COUNT_PHRASES)
        if ph:
            s += f", {ph} last year's pace"
        pph = _phrase(yoy.get("avg_price_pct"), PRICE_PHRASES)
        if pph and ytd.get("avg_price"):
            s += (f", and the average sale price of "
                  f"{fmt_price_full(ytd['avg_price'])} is {pph} the same period "
                  f"in {baseline_year}")
        sentences.append(s + ".")

    # 4. How fast homes are selling — the month when it is trustworthy,
    # otherwise the YTD figure, which is never a partial-month artifact.
    if spot and complete and spot["current"].get("avg_dom") is not None \
            and not _thin(spot["yoy_prior"]) and spot["yoy_prior"].get("avg_dom"):
        cur_dom, pri_dom = spot["current"]["avg_dom"], spot["yoy_prior"]["avg_dom"]
        ph = _phrase((cur_dom - pri_dom) / pri_dom * 100, DOM_PHRASES)
        if ph:
            sentences.append(
                f"Homes that sold in {MONTH_NAMES[spot['cm'] - 1]} averaged "
                f"{fmt_dom(cur_dom)} days on market, {ph} a year ago.")
    elif ytd.get("avg_dom") is not None and yoy.get("avg_dom_pct") is not None:
        ph = _phrase(yoy["avg_dom_pct"], DOM_PHRASES)
        if ph:
            sentences.append(
                f"Homes are averaging {fmt_dom(ytd['avg_dom'])} days on market "
                f"so far this year, {ph} the same stretch of {baseline_year}.")

    # 5. Supply. The label is consumed, never recomputed here.
    if mb.get("market_type_label") and mb.get("months_of_supply") is not None \
            and mb.get("active_inventory") and not mb.get("small_market"):   # thin: no verdict
        sentences.append(
            f"With {fmt_int(mb['active_inventory'])} homes on the market and "
            f"{mb['months_of_supply']} months of supply, {label} sits in "
            f"{mb['market_type_label'].lower().replace(' market', '-market')} "
            f"territory.")

    # 6. Demand against fresh supply. Prefer the rolling figure — a single
    # month of 15-40 sales swings hard on a handful of transactions.
    basis = (snlr.get("rolling_3mo") or snlr.get("latest") or {})
    if basis.get("ratio_pct") is not None:
        if snlr.get("rolling_3mo"):
            window = "over the last three months"
        else:
            _mk = str((snlr.get("latest") or {}).get("month") or "")
            try:
                window = f"in {MONTH_NAMES[int(_mk.split('-')[1]) - 1]}"
            except (ValueError, IndexError):
                window = "in the latest reported month"
        s = (f"Buyers took up {basis['ratio_pct']:.0f}% of the new listings that "
             f"came to market {window}, {basis.get('condition_label', '').lower()} "
             f"conditions on the standard CREA measure")
        # When the two balance measures disagree, say so. Left unexplained it
        # reads as a contradiction on screen; named, it is a real signal that
        # standing inventory and current flow are telling different stories.
        if mb.get("market_type") and basis.get("condition") \
                and mb["market_type"] != basis["condition"]:
            s += (" — a different read than months of supply gives, which happens "
                  "when the pace of new listings and the size of standing "
                  "inventory are moving apart")
        sentences.append(s + ".")

    return sentences


def build_market_summary_section(cfg, region, agg, spot):
    """HTML wrapper around market_summary_sentences -- omitted entirely when
    fewer than two sentences survive their gates (never a one-line summary)."""
    if not region:
        return ""
    sentences = market_summary_sentences(cfg, region, agg, spot)
    complete = bool(spot and spot["complete"])
    if len(sentences) < 2:
        return ""

    month_name = MONTH_NAMES[spot["cm"] - 1] if spot else ""
    heading = (f"{month_name} {spot['cy']} <em>in plain language.</em>"
               if spot and complete
               # _ytd_year, not region["ytd_year"] — the sibling aggregators emit
               # ytd_anchor_year instead, and reading the raw key produced a
               # yearless "Market Summary  so far" heading on Goose Bay.
               else f"{_ytd_year(cfg, region)} <em>so far, in plain language.</em>")
    paras = "".join(f"\n        <p>{s}</p>" for s in sentences)
    return f'''
  <!-- ═══════ MARKET SUMMARY ═══════ -->
  <div class="ms-section ms-section--dark2">
    <div class="ms-section-inner">
      <div class="ms-section-head" style="margin-bottom:28px;">
        <div class="ms-eyebrow">Market Summary</div>
        <h2>{heading}</h2>
      </div>
      <div class="ms-summary">{paras}
      </div>
    </div>
  </div>'''


def build_price_bands_section(cfg, region):
    """Where the market's activity actually sits by price point.

    Trailing 12 months, because a single month in a market this size is 15-40
    sales — split five ways that is noise. The prior-year share sits beside each
    band so a shift in the mix is visible rather than implied.

    Convention #74: '' when the aggregator withheld the bands (thin data)."""
    bands_data = (region or {}).get("price_bands")
    if not bands_data or not bands_data.get("bands"):
        return "", None

    n_total = bands_data.get("n_total", 0)
    prior_bands = {b["label"]: b for b in bands_data.get("prior", {}).get("bands", [])}
    prior_n = bands_data.get("prior", {}).get("n_total", 0)
    max_share = max((b.get("share_pct") or 0) for b in bands_data["bands"]) or 1

    rows = []
    for b in bands_data["bands"]:
        share = b.get("share_pct") or 0
        width = round(share / max_share * 100, 1)
        pb = prior_bands.get(b["label"])
        prior_html = ""
        if prior_n and pb is not None:
            prior_html = (f'<div class="ms-band-prior">was {pb["share_pct"]:.0f}% '
                          f'last year</div>')
        rows.append(f'''        <div class="ms-band-row">
          <div class="ms-band-label">{b["label"]}</div>
          <div class="ms-band-track"><div class="ms-band-bar" style="width:{width}%"></div></div>
          <div class="ms-band-meta">
            <span class="ms-band-count">{fmt_int(b["count"])}</span><span class="ms-band-share">{share:.0f}%</span>
            {prior_html}
          </div>
        </div>''')

    # Grouped current-vs-prior chart (2026-07-30, Mike: make it interactive) —
    # sits above the existing width-bar breakdown rather than replacing it;
    # the breakdown keeps the per-band DOM + share-vs-last-year detail a
    # chart can't show as precisely, the chart adds a hoverable side-by-side
    # comparison for the video-narration use case. prior count defaults to 0
    # (not omitted) when a band is absent from last year's data — a bar of
    # height 0 reads correctly as "none," a missing bar reads as a data gap.
    chart_data = {
        "labels": [b["label"] for b in bands_data["bands"]],
        "current_counts": [b["count"] for b in bands_data["bands"]],
        "prior_counts": [prior_bands.get(b["label"], {}).get("count", 0) for b in bands_data["bands"]],
        "has_prior": bool(prior_n),
    }

    explainer = cfg.get("explainers", {}).get("price_bands", "")
    explainer_html = (f'\n      <p class="ms-explainer" style="margin-top:20px;">{explainer}</p>'
                      if explainer else "")

    return f'''
  <!-- ═══════ PRICE BANDS ═══════ -->
  <div class="ms-section">
    <div class="ms-section-inner">
      <div class="ms-section-head">
        <div class="ms-eyebrow">Where the Sales Are</div>
        <h2>Sales by <em>Price Range.</em></h2>
        <p>How many homes sold in each price bracket, and how that mix compares to the year before.</p>
      </div>
      <div class="ms-chart-wrap">
        <div class="ms-chart-title">Homes Sold by Price Band</div>
        <div class="ms-chart-sub">{cfg.get('geo_description', '')} &middot; Trailing 12 months &middot; {n_total:,} sales{" this year vs. " + f"{prior_n:,} last year" if prior_n else ""}</div>
        <div class="ms-chart-canvas-wrap" style="height:280px;">
          <canvas id="chartPriceBands"></canvas>
        </div>
        <div class="ms-bands">
{chr(10).join(rows)}
        </div>
      </div>{explainer_html}
    </div>
  </div>''', chart_data



def build_new_construction_section(cfg, region):
    """New construction vs. resale (Mike 2026-09-07). The headline numbers on this
    page are RESALE ONLY; this block shows the new-build segment beside them so
    a buyer weighing a new build against a resale sees both prices, and a seller
    sees how much of the market's activity is new supply. Convention #74: ''
    when the aggregator has no segment block; renders an explicit "no new
    builds" line rather than nothing when the segment is empty this year."""
    nc = (region or {}).get("new_construction")
    if nc is None:
        return ""
    label = cfg.get("label", "This market")
    res = (region or {}).get("ytd_complete") or (region or {}).get("ytd") or {}
    new = nc.get("ytd_complete") or nc.get("ytd") or {}
    n_new, n_res = int(new.get("count") or 0), int(res.get("count") or 0)
    share = nc.get("share_pct_ytd")
    thru = (region or {}).get("ytd_complete_through_month")
    year = (region or {}).get("ytd_complete_through_year") or (region or {}).get("ytd_year") or ""
    window = f"January–{MONTH_NAMES[int(thru) - 1]} {year}" if thru else f"{year} year to date"

    def cell(v, lbl, sub=""):
        return (f'\n        <div class="ms-annual-stat"><div class="ms-annual-num">{v}</div>'
                f'<div class="ms-stat-lbl">{lbl}</div>'
                + (f'<div style="font-size:12px;color:#a0a0a0;margin-top:4px;">{sub}</div>' if sub else "") + "</div>")

    def money(v):
        try:
            return f"${float(v):,.0f}"
        except (TypeError, ValueError):
            return "—"

    def days(v):
        return f"{float(v):.0f}" if v is not None else "—"

    # $/sq ft, new build vs resale (Mike 2026-09-18: "we should have both what
    # the new construction price per foot is and what the resale price per
    # foot is"). Same rolling-12-month figure + tier system as Around the
    # Region's own $/sq ft column, so a withheld/limited new-build figure
    # reads the same way it does everywhere else on the site -- new
    # construction volume is low, so "too few sales" here is the common case,
    # not an edge case.
    def ppsf_cell():
        nc_ppsf = nc.get("ppsf") or {}
        res_ppsf = (region or {}).get("ppsf") or {}
        tier = _ppsf_tier(nc_ppsf)
        res_bit = (f"resale ${res_ppsf['median_ppsf']:,.0f}"
                   if res_ppsf.get("median_ppsf") and _ppsf_tier(res_ppsf) != "withheld" else "")
        if tier == "withheld" or not nc_ppsf.get("median_ppsf"):
            return cell("&mdash;", "$ / sq ft &middot; new build",
                       " &middot; ".join(x for x in ("too few new builds with a floor area", res_bit) if x))
        limited_bit = f"limited &middot; {nc_ppsf.get('n_sized', 0)} sales" if tier == "limited" else ""
        return cell(f"${nc_ppsf['median_ppsf']:,.0f}", "$ / sq ft &middot; new build",
                   " &middot; ".join(x for x in (res_bit, limited_bit) if x))

    # Year-over-year for the segment (Mike 2026-09-07): same complete-month
    # window last year. The % only appears when both years have >= 5 new-build
    # sales -- below that it is one house moving the needle, so the count alone.
    prior_new = nc.get("prior_ytd_complete") or nc.get("prior_ytd") or {}
    n_prior = int(prior_new.get("count") or 0)
    nc_yoy = nc.get("yoy_complete") or nc.get("yoy") or {}
    ly = ""
    if prior_new.get("count") is not None:
        ly = f"{n_prior} last year"
        if nc_yoy.get("count_pct") is not None and n_new >= 5 and n_prior >= 5:
            ly += f" ({'+' if nc_yoy['count_pct'] >= 0 else '−'}{abs(nc_yoy['count_pct']):.0f}%)"
    if n_new == 0:
        body = (f'<p class="ms-explainer" style="padding:12px 0 0;">No new-construction sales were recorded in {html.escape(label)} '
                f'{window}' + (f' ({ly})' if ly else '') + ' — every figure on this page is a resale.</p>')
    else:
        sa_new = f"{float(new['avg_sa']):.1f}%" if new.get("avg_sa") is not None else "—"
        sa_res = f"resale {float(res['avg_sa']):.1f}%" if res.get("avg_sa") is not None else ""
        share_sub = " · ".join(x for x in ((f"{share:.0f}% of all sales" if share is not None else ""), ly) if x)
        body = ('\n      <div class="ms-annual-grid">'
                + cell(f"{n_new}", "New-build sales", share_sub)
                + cell(money(new.get("median_price")), "Median price · new build", f"resale {money(res.get('median_price'))}")
                + ppsf_cell()
                + cell(days(new.get("avg_dom")), "Avg days on market · new build", f"resale {days(res.get('avg_dom'))} days")
                + cell(sa_new, "Sale-to-list · new build", sa_res)
                + "\n      </div>")
        if n_new < 5:
            body += (f'<p class="ms-explainer" style="padding:12px 0 0;">Only {n_new} new-build sale{"s" if n_new != 1 else ""} '
                     f'this year — read these as examples, not a market rate.</p>')
    return f'''
  <!-- ═══════ NEW CONSTRUCTION VS RESALE ═══════ -->
  <div class="ms-section ms-section--dark2">
    <div class="ms-section-inner">
      <div class="ms-section-head" style="margin-bottom:18px;">
        <div class="ms-eyebrow">New Construction vs. Resale</div>
        <h2>New builds, <em>counted separately.</em></h2>
        <p class="ms-explainer" style="padding:8px 0 0;">Every other number on this page is a resale. New construction — homes sold within a year of being built, or listed as new, under construction or to be built — is shown here on its own ({window}), so the two markets never blur into one average.</p>
      </div>{body}
    </div>
  </div>'''


def build_property_type_mix_section(cfg, region):
    """What kind of homes are trading — single-family vs multi-family vs condo.

    Convention #74: '' when the aggregator withheld the mix, and buckets under
    five sales are already dropped upstream rather than shown as a 'median'
    built on two houses."""
    mix = (region or {}).get("property_type_mix")
    style = (region or {}).get("home_style_mix")
    beds = (region or {}).get("bedroom_mix")
    if not mix or not mix.get("types"):
        return ""

    blocks = _mix_table(mix, "types", "Property Type", show_beds=True)
    # Where the $/sq ft spread is widest and most useful: by style of house.
    blocks += _ppsf_range_chart(style, "styles", "Price per Square Foot, by Home Style")
    blocks += _mix_table(style, "styles", "Home Style", show_beds=True,
                         heading="By Home Style",
                         intro="Most of what trades here is detached single-family, "
                               "so the style of house is the split that actually "
                               "separates one seller's market from another's.")
    # Bedroom count is the cut buyers search by. No median-beds column: it would
    # restate the row label.
    blocks += _mix_table(beds, "beds", "Bedrooms", show_beds=False,
                         heading="By Bedroom Count")

    explainer = cfg.get("explainers", {}).get("property_type_mix", "")
    explainer_html = (f'\n      <p class="ms-explainer" style="margin-top:20px;">{explainer}</p>'
                      if explainer else "")

    return f'''
  <!-- ═══════ PROPERTY-TYPE MIX ═══════ -->
  <div class="ms-section ms-section--dark2">
    <div class="ms-section-inner">
      <div class="ms-section-head">
        <div class="ms-eyebrow">What's Selling</div>
        <h2>What Kind of Homes <em>Are Selling.</em></h2>
        <p>The homes that changed hands over the last twelve months, cut three ways — by property type, by style of house, and by bedroom count.</p>
      </div>{blocks}{explainer_html}
    </div>
  </div>'''


def _ppsf_tier(d):
    """The aggregator's sample tier for a $/sq ft figure: ok | limited |
    withheld. An aggregate written before tiers existed carries a bare
    median_ppsf that already cleared the old coverage gate, so it reads as ok."""
    d = d or {}
    return d.get("ppsf_tier") or d.get("tier") or ("ok" if d.get("median_ppsf") else "withheld")


def _ppsf_cell(d, *, n_key, bar_max=None):
    """One $/sq ft table cell. Every published figure says how many sales it
    is built on; a limited one (5-9 sales) is flagged rather than dressed up as
    equal to its neighbours; a withheld one says why it is blank."""
    tier = _ppsf_tier(d)
    val = (d or {}).get("median_ppsf")
    if tier == "withheld" or not val:
        return '<td class="ms-ppsf ms-ppsf--na">Too few sales with a floor area</td>'
    n = int((d or {}).get(n_key) or 0)
    bar = ""
    if bar_max:
        pct = max(4, min(100, round(val / bar_max * 100)))
        bar = (f'<span class="ms-ppsf-track" aria-hidden="true">'
               f'<span class="ms-ppsf-bar" style="width:{pct}%"></span></span>')
    note = (f'Limited &middot; {n} sales' if tier == "limited" else f'{n:,} sales')
    return (f'<td class="ms-ppsf ms-ppsf--{tier}"><span class="ms-ppsf-val">${val:,.0f}</span>'
            f'{bar}<span class="ms-ppsf-n">{note}</span></td>')


def _size_cell(d):
    sq = (d or {}).get("median_sqft")
    return (f'<td class="ms-col-size">{sq:,.0f} sq ft</td>' if sq and _ppsf_tier(d) != "withheld"
            else '<td class="ms-col-size">&mdash;</td>')


PPSF_LEGEND = ('<p class="ms-ppsf-legend"><span><i class="ms-ppsf-key"></i>10 or more sales with a '
               'floor area</span><span><i class="ms-ppsf-key ms-ppsf-key--limited"></i>5 to 9 sales: '
               'read as direction, not precision</span><span>Under 5: not shown</span></p>')


def _ppsf_range_chart(block, rows_key, heading):
    """Middle-half range of $/sq ft per row (25th to 75th percentile, median
    tick), drawn in plain CSS so it prints and needs no chart library. Only rows
    at the published tier carry a range; fewer than two and there is nothing to
    compare, so no chart."""
    rows = [r for r in (block or {}).get(rows_key) or []
            if _ppsf_tier(r) == "ok" and r.get("ppsf_p25") and r.get("ppsf_p75")]
    if len(rows) < 2:
        return ""
    lo = min(r["ppsf_p25"] for r in rows)
    hi = max(r["ppsf_p75"] for r in rows)
    pad = (hi - lo) * 0.12 or 10
    lo, hi = max(0, lo - pad), hi + pad
    span = hi - lo

    def pos(v):
        return round((v - lo) / span * 100, 1)

    lines = "".join(f'''
        <div class="ms-range-row">
          <span class="ms-range-label">{html.escape(str(r["label"]))}</span>
          <span class="ms-range-track"><span class="ms-range-bar" style="left:{pos(r["ppsf_p25"])}%;width:{round(pos(r["ppsf_p75"]) - pos(r["ppsf_p25"]), 1)}%"></span><span class="ms-range-tick" style="left:{pos(r["median_ppsf"])}%"></span></span>
          <span class="ms-range-val">${r["median_ppsf"]:,.0f}</span>
          <span class="ms-range-n">${r["ppsf_p25"]:,.0f}&ndash;${r["ppsf_p75"]:,.0f} &middot; {int(r.get("ppsf_n") or 0)} sales</span>
        </div>''' for r in rows)
    return f'''
      <div class="ms-range-chart">
        <div class="ms-range-head"><h3 class="ms-mix-head" style="margin:0;">{heading}</h3><span>Bar = the middle half of sales &middot; white tick = median</span></div>{lines}
        <p class="ms-range-foot">Smaller homes almost always cost more per square foot than larger ones, so compare a style against itself over time before comparing it to another style.</p>
      </div>'''


def _mix_table(block, rows_key, col_label, *, show_beds, heading=None, intro=""):
    """One breakout table. Returns '' when the aggregator withheld the cut, so a
    thin sub-region simply shows fewer tables rather than empty headings.

    Optional columns appear only when the data earns them: median beds when the
    label isn't already a bedroom count, and price per square foot only if at
    least half the visible rows cleared the aggregator's coverage gate. A column
    of mostly em-dashes reads as broken rather than as incomplete."""
    if not block or not block.get(rows_key):
        return ""
    rows_data = block[rows_key]

    beds_col = show_beds and any(r.get("median_beds") for r in rows_data)
    # $/sq ft earns its columns as soon as one row publishes a figure. A row
    # that cannot says so in words ("Too few sales with a floor area"), which
    # reads as an honest gap rather than the broken table a bare dash did.
    ppsf_rows = [r for r in rows_data if _ppsf_tier(r) != "withheld" and r.get("median_ppsf")]
    ppsf_col = bool(ppsf_rows)

    head = "".join([
        f"<th>{col_label}</th>", "<th>Sales</th>", "<th>Share</th>",
        "<th>Median Price</th>",
        "<th>Median Beds</th>" if beds_col else "",
        '<th class="ms-col-size">Typical Size</th>' if ppsf_col else "",
        "<th>$ / Sq Ft &middot; Median</th>" if ppsf_col else "",
        "<th>Avg Days on Market</th>",
    ])  # Typical Size rides with the $/sq ft column: one without the other misleads

    def _row(r):
        cells = [f'<td>{r["label"]}</td>', f'<td>{fmt_int(r["count"])}</td>',
                 f'<td>{r["share_pct"]:.0f}%</td>',
                 f'<td>{fmt_price_full(r["median_price"])}</td>']
        if beds_col:
            b = r.get("median_beds")
            cells.append(f'<td>{b:g}</td>' if b else '<td>—</td>')
        if ppsf_col:
            cells.append(_size_cell(r))
            cells.append(_ppsf_cell(r, n_key="ppsf_n"))   # value + the sales it rests on
        cells.append(f'<td>{fmt_dom(r["avg_dom"])}</td>')
        return "          <tr>" + "".join(cells) + "</tr>"

    rows = "\n".join(_row(r) for r in rows_data)

    # Say what the table does NOT cover. Built form is blank on roughly a fifth
    # of Gander closings, and a share presented without that context reads as a
    # share of the whole market when it is a share of the classified subset.
    notes = [f"Trailing 12 months &middot; {block.get('n_total', 0):,} sales"]
    if block.get("unclassified"):
        notes.append(f"{block['unclassified']:,} more had no {col_label.lower()} recorded")
    if block.get("below_floor"):
        notes.append(f"{block['below_floor']:,} in groups too small to report")
    if ppsf_col:
        notes.append("typical size and $/sq ft use only the sales that recorded a floor area")

    head_html = (f'\n      <h3 class="ms-mix-head">{heading}</h3>' if heading else "")
    intro_html = (f'\n      <p class="ms-mix-intro">{intro}</p>' if intro else "")
    return f'''{head_html}{intro_html}
      <div class="ms-table-scroll">
        <table class="ms-ptype-table">
          <thead>
            <tr>{head}</tr>
          </thead>
          <tbody>
{rows}
          </tbody>
        </table>
      </div>
      <p class="ms-chart-sub" style="margin-top:14px;">{" &middot; ".join(notes)}</p>'''


def build_community_snapshot_section(cfg, agg):
    """One table covering every surrounding community — the 'around the region'
    segment of the monthly video, and a set of internal links to the sub-pages.

    Rows come from the YAML `community_snapshot:` list (region_key + href) and
    are read straight out of the aggregator, so nothing here is hand-keyed.
    Convention #74: a region missing from the aggregator is skipped, not
    rendered as a row of dashes; no rows at all → no section."""
    entries = cfg.get("community_snapshot") or []
    if not entries or not agg:
        return "", None

    type_class = {"seller": "ms-mkt-type--seller",
                  "balanced": "ms-mkt-type--balanced",
                  "buyer": "ms-mkt-type--buyer"}

    # Rows sorted by YTD sales count, busiest community first (Mike, 2026-07-30)
    # — the table previously rendered in whatever order the YAML happened to
    # list regions, which is config-authoring order, not a meaningful read.
    scored_rows = []
    for entry in entries:
        region_key = entry.get("region_key")
        if not region_key:
            continue
        r = get_region_data(agg, region_key)
        if not r:
            continue
        ytd = r.get("ytd", {})
        count = ytd.get("count")
        if not count:
            continue

        raw_name = entry.get("label") or r.get("label") or region_key
        name = html.escape(raw_name)
        href = entry.get("href")
        name_html = f'<a href="{html.escape(href)}">{name}</a>' if href else name

        mb = r.get("market_balance") or {}
        mtype = mb.get("market_type")
        mlabel = mb.get("market_type_label")
        if mb.get("small_market"):   # verdict withheld below 15 sales YTD (2026-09-07)
            mtype, mlabel = "", "Small market"
        type_html = (f'<span class="ms-mkt-type {type_class.get(mtype, "")}">{mlabel}</span>'
                     if mlabel else "—")

        # Row HTML is assembled after the loop: the $/sq ft bar is scaled to
        # the highest community, which is not known until every row is read.
        row_html = {"name": name_html, "count": count, "ytd": ytd,
                    "type": type_html, "ppsf": r.get("ppsf") or {}}
        # raw_name (unescaped) for the chart — Canvas text rendering doesn't
        # interpret HTML entities, so the escaped &amp; form would render
        # literally on a chart axis.
        scored_rows.append((count, raw_name, row_html))

    if not scored_rows:
        return "", None

    scored_rows.sort(key=lambda triple: triple[0], reverse=True)
    # The two $/sq ft columns appear only if some community publishes a figure
    # (an aggregate from before the ppsf block shipped has none: Convention #74).
    published = [d["ppsf"]["median_ppsf"] for _c, _n, d in scored_rows
                 if _ppsf_tier(d["ppsf"]) != "withheld" and d["ppsf"].get("median_ppsf")]
    ppsf_col = bool(published)
    bar_max = max(published) if published else None
    rows = []
    for _count, _name, d in scored_rows:
        ppsf_cells = ((_ppsf_cell(d["ppsf"], n_key="n_sized", bar_max=bar_max) + _size_cell(d["ppsf"]))
                      if ppsf_col else "")
        rows.append(f'''          <tr>
            <td>{d["name"]}</td>
            <td>{fmt_int(d["count"])}</td>
            <td>{fmt_price_full(d["ytd"].get("median_price"))}</td>
            {ppsf_cells}
            <td class="ms-col-dom">{fmt_dom(d["ytd"].get("avg_dom"))}</td>
            <td>{d["type"]}</td>
          </tr>''')
    ppsf_head = ('<th>$ / Sq Ft &middot; Median</th>\n              <th class="ms-col-size">Typical Size</th>'
                 if ppsf_col else "")
    ppsf_intro = (" Price per square foot uses the last 12 months of resale homes that recorded a floor "
                  "area, and every figure shows how many sales it is built on."
                  if ppsf_col else "")
    ppsf_legend = ((PPSF_LEGEND + _ppsf_howto()) if ppsf_col else "")
    chart_data = {
        "labels": [name for _count, name, _row in scored_rows],
        "counts": [count for count, _name, _row in scored_rows],
    }

    explainer = cfg.get("explainers", {}).get("community_snapshot", "")
    explainer_html = (f'\n      <p class="ms-explainer" style="margin-top:20px;">{explainer}</p>'
                      if explainer else "")

    # Chart height grows with the number of communities so bars stay legible
    # rather than being squeezed into a fixed 300px regardless of count
    # (Convention: every OTHER chart on this page is fixed-height for the
    # YouTube screen-share scroll — this one chart is the deliberate
    # exception because a horizontal bar's whole point is one row per
    # community, and squeezing 9+ rows into 300px defeats that).
    chart_height = max(240, 34 * len(scored_rows) + 40)

    return f'''
  <!-- ═══════ COMMUNITY SNAPSHOT ═══════ -->
  <div class="ms-section">
    <div class="ms-section-inner">
      <div class="ms-section-head">
        <div class="ms-eyebrow">Around the Region</div>
        <h2>Every Community<br><em>Side by Side.</em></h2>
        <p>Year-to-date results for each community we serve. Click any community for its full market page.{ppsf_intro}</p>
      </div>
      <div class="ms-chart-wrap">
        <div class="ms-chart-title">Sales YTD by Community</div>
        <div class="ms-chart-sub">Busiest first &middot; hover any bar for the exact count</div>
        <div class="ms-chart-canvas-wrap" style="height:{chart_height}px;">
          <canvas id="chartCommunity"></canvas>
        </div>
      </div>
      <div class="ms-table-scroll">
        <table class="ms-community-table">
          <thead>
            <tr>
              <th>Community</th>
              <th>Sales YTD</th>
              <th>Median Price</th>
              {ppsf_head}
              <th class="ms-col-dom">Avg Days on Market</th>
              <th>Market Type</th>
            </tr>
          </thead>
          <tbody>
  {chr(10).join(rows)}
          </tbody>
        </table>
      </div>{ppsf_legend}{explainer_html}
    </div>
  </div>''', chart_data


def build_cross_region_compare(cfg):
    """One-row 'Compare: Avalon · Labrador' link line, master pages ONLY
    (Slice 3 step 5, canvas decision (c) -- market-stats pages already load
    js/turner-network.js's network strip right above the footer, so a full
    cross-region band here would triple-stack; a single line is enough).
    Same registry gating as build-homepage.py's band_network() and
    build-region-hub.py's cross-region band, via
    _fleet_genutils.cross_region_data(). Returns '' if the registry or this
    site's own identity can't be resolved (Convention #74/#202)."""
    data = cross_region_data()
    if not data:
        return ""
    me, turner_others, peers, recruiting = data
    if not turner_others:
        return ""
    links = " &middot; ".join(
        f'<a href="{(r.get("domain") or "").rstrip("/")}{(r.get("routes") or {}).get("market", "")}">{html.escape(r["nav_label"])}</a>'
        for r in turner_others if (r.get("routes") or {}).get("market")
    )
    if not links:
        return ""
    return f'''
  <!-- ═══════ COMPARE MARKETS (Slice 3 step 5) ═══════ -->
  <div class="ms-section ms-section--dark2">
    <div class="ms-section-inner">
      <div class="ms-eyebrow">Compare Markets</div>
      <p style="margin-top:8px">See how {html.escape(me.get("label") or me.get("nav_label") or "")} compares: {links}</p>
    </div>
  </div>'''


def build_explore_community(cfg):
    """Build the 'Explore the Community' cross-link block.

    Links to the paired community guide page and the /listings/ city index,
    closing the stats<->guide<->listings crawl triangle. Returns '' when the
    YAML config omits the required keys (silent no-op — Convention #74)."""
    guide = cfg.get("explore_community_guide")
    listings = cfg.get("explore_listings_url") or "/listings/"
    label = cfg.get("label", "")
    if not guide:
        # (2026-09-07) derive the paired community page from the config stem
        # so Reference ends on "where to go next" instead of an embed.
        _stem = str(cfg.get("slug") or "").replace("-market-stats", "")
        _cand = _COMMUNITY_SLUG_FOR_STEM.get(_stem, _stem)
        _cand = {"gander-mls": "gander", "stjohns-mls": "avalon", "market-stats": "labrador-city",
                 "galway": "galway-southlands", "bay-bulls": "southern-shore", "south-st-johns": "goulds"}.get(_stem, _cand)
        if _cand and not _cand.startswith("_") and (Path(__file__).resolve().parent.parent / "pages" / f"{_cand}.html").exists():
            guide = f"{_cand}.html"
    if not guide:
        return ""
    return f'''
  <!-- ═══════ EXPLORE THE COMMUNITY ═══════ -->
  <div class="ms-section ms-section--dark2">
    <div class="ms-section-inner">
      <div class="ms-eyebrow">Explore the Community</div>
      <div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:8px;">
        <a href="{guide}" class="ms-btn">Community Guide: {label}</a>
        <a href="{listings}" class="ms-btn-sec">Browse {label} Listings</a>
      </div>
    </div>
  </div>'''


def _sold_photo_url(mls):
    """Resolve a sold listing's hero photo by MLS number, or None.

    Mirrors ddf-generate-pages.py's sold-detail photo resolution exactly —
    same images/listings-sold/<MLS>/ path, same .meta.json-existence-as-R2-
    signal. Returns None when the sync hasn't covered this MLS (a closing
    outside the sync's in-scope postal filter, or one the sync just hasn't
    reached yet) — the card renders text-only rather than a broken image
    (Convention #74)."""
    mls = (mls or "").strip()
    if not mls:
        return None
    # Goosebay adaptation (2026-07-31): Goose Bay runs no sold-photo sync
    # of its own -- island-wide sold-listing photos live in Gander's
    # shared R2 tree since Mike's 2026-05-12 "all the sold data across
    # the island" directive (idx-sold-photo-sync.py's is_in_scope()
    # returns True unconditionally, fleet-wide -- not just Central NL).
    # Confirmed live 2026-07-31 by direct HEAD request: 3 real HVGB MLS
    # numbers (1266189, 1282074, 1294621) all resolve HTTP 200 at this
    # exact URL. Emit it directly rather than checking a local
    # .meta.json sentinel that will never exist here (Goose Bay never
    # writes one) -- the <img onerror> in build_notable_sales_section
    # covers the rare case a very fresh closing hasn't synced yet.
    if R2_SITE_SLUG in ("goosebay", "labwest"):   # Lab West too. Gander's shared tree is island-wide (HEAD-checked for Happy Valley-Goose Bay rows; Lab West rows not yet checked here: the card's <img onerror> covers a miss)
        return f"https://photos.realestategander.com/gander/listings-sold/{mls}/001.jpg"
    meta_path = SITE_ROOT / "images" / "listings-sold" / mls / ".meta.json"
    local_photo_path = SITE_ROOT / "images" / "listings-sold" / mls / "001.jpg"
    if R2_BASE_URL and meta_path.exists():
        return f"{R2_BASE_URL}/{R2_SITE_SLUG}/listings-sold/{mls}/001.jpg"
    if local_photo_path.exists():
        return f"/images/listings-sold/{mls}/001.jpg"
    return None


def build_notable_sales_section(cfg, region, spot):
    """A few real, named closings from the spotlight month — human-interest
    beat for the monthly video, sitting beside the plain-language summary.
    Each card gets its synced hero photo when one exists (2026-07-30, Mike),
    and the grid is followed by a CTA into the VOW sold-listings archive —
    Mike's framing: "a good place to pick up people for the sold listings."
    Registering to see full sold prices is the lead-capture moment; these
    three real examples are what earns the click.

    VOW COMPLIANCE: renders ONLY the fields the aggregator's build_notable_
    sales already vetted safe for an ungated page (address, style, beds/
    baths, DOM, list price, MLS number). Never add ClosePrice or a sale-to-
    list % here — see that function's docstring in idx-stats-aggregator.py
    for why.

    Convention #74: '' when the aggregator found nothing (thin month, or an
    aggregates file built before this feature shipped, so the key is absent)."""
    sales = (region or {}).get("notable_sales") or []
    if not sales:
        return ""
    label = cfg.get("label", "this market")
    month_label = ""
    if spot and spot.get("cm"):
        try:
            month_label = f"{MONTH_NAMES[spot['cm'] - 1]} {spot['cy']}"
        except (KeyError, IndexError, TypeError):
            month_label = ""

    cards = []
    for s in sales:
        bits = []
        if s.get("beds"):
            bits.append(f"{s['beds']} bed")
        if s.get("baths"):
            b = s["baths"]
            bits.append(f"{b:g} bath")
        style = (s.get("style") or "").strip()
        if style:
            bits.append(style)
        detail_line = " &middot; ".join(bits)
        dom = s.get("dom")
        dom_line = (f"Sold in {dom} day{'s' if dom != 1 else ''} on market"
                    if dom is not None else "")
        lp = s.get("list_price")
        lp_line = f"Listed at {fmt_price_full(lp)}" if lp else ""
        second_line = " &middot; ".join(x for x in (lp_line, dom_line) if x)

        address = s.get("address", "")
        photo_url = _sold_photo_url(s.get("mls"))
        if photo_url:
            alt = html.escape(f"{address} — sold {month_label}" if month_label else address, quote=True)
            photo_html = (f'<img class="ms-signal-photo" src="{photo_url}" alt="{alt}" '
                          f'width="400" height="250" loading="lazy" decoding="async" '
                          f'onerror="this.style.display=\'none\'">')
            card_class = "ms-signal-card has-photo"
            body_open, body_close = '<div class="ms-signal-body">', '</div>'
        else:
            photo_html = ""
            card_class = "ms-signal-card"
            body_open, body_close = "", ""

        cards.append(f'''
      <div class="{card_class}">{photo_html}
        {body_open}<h3>{address}</h3>
        <p>{detail_line}</p>
        <p>{second_line}</p>{body_close}
      </div>''')

    return f'''
  <!-- ═══════ NOTABLE SALES ═══════ -->
  <div class="ms-section">
    <div class="ms-section-inner">
      <div class="ms-section-head">
        <div class="ms-eyebrow">Notable Sales</div>
        <h2>Recent Closings<br><em>in {label}.</em></h2>
        <p>A few of the homes that changed hands{f" in {month_label}" if month_label else ""} — real closings, straight from the MLS&reg; record.</p>
      </div>
      <div class="ms-signals-grid">{"".join(cards)}
      </div>
      <div class="ms-signals-cta">
        <p>Want to see what homes like these actually <strong>sold for</strong>? Register free to unlock full sale prices, sale-to-list ratios, and price history for every closing in {label}.</p>
        <a href="../listings/sold/" class="ms-btn">See Full Sold Prices</a>
      </div>
    </div>
  </div>'''


def build_ppsf_trend_section(cfg, region):
    """Is a square foot getting more expensive here? Median $/sq ft, one
    point per month, each point a rolling trailing-12-month window (Conv:
    smooths the noise a raw monthly median would show without losing real
    movement -- see build_ppsf_trend's own docstring). Reuses the region's
    own build_ppsf_block figure (already computed for Around the Region) for
    the big current-value callout, so the two numbers can never disagree.

    Convention #74: '' when the aggregator withheld the series (fewer than
    PPSF_TREND_MIN_POINTS non-withheld months)."""
    trend = (region or {}).get("ppsf_trend")
    points = (trend or {}).get("points") or []
    if not trend or len(points) < 2:
        return "", None  # Lab West fix: the caller unpacks (html, data); a bare "" crashed the build on a thin series
    ppsf = (region or {}).get("ppsf") or {}
    label = cfg.get("label", "This market")

    labels, data, tiers = [], [], []
    for pt in points:
        y, m = pt["month"].split("-")
        labels.append(f"{MONTH_ABBR[int(m) - 1]} {y}")
        data.append(pt["median_ppsf"])
        tiers.append(pt["tier"])

    current = ppsf.get("median_ppsf")
    yoy = ppsf.get("yoy_pct")
    yoy_html = ""
    if yoy is not None:
        cls = "ms-ppsf-trend-up" if yoy > 0 else ("ms-ppsf-trend-down" if yoy < 0 else "")
        arrow = "&uarr;" if yoy > 0 else ("&darr;" if yoy < 0 else "&rarr;")
        yoy_html = f'<span class="{cls}">{arrow} {abs(yoy):.1f}% vs a year ago</span>'
    current_html = (f'<div class="ms-ppsf-trend-now"><span class="ms-ppsf-trend-val">${current:,.0f}</span>'
                    f'<span class="ms-ppsf-trend-lbl">per sq ft today &middot; {label}</span>{yoy_html}</div>'
                    if current else "")

    n_limited = sum(1 for t in tiers if t == "limited")
    n_gap = sum(1 for t in tiers if t == "withheld")
    notes = [f"Rolling 12-month median &middot; {len(points)} months"]
    if n_limited:
        notes.append(f"{n_limited} month{'s' if n_limited != 1 else ''} on a limited sample (5&ndash;9 sales)")
    if n_gap:
        notes.append(f"{n_gap} month{'s' if n_gap != 1 else ''} withheld &mdash; too few sales with a floor area")

    return f'''
  <!-- ═══════ $/SQ FT TREND OVER TIME ═══════ -->
  <div class="ms-section ms-section--dark2">
    <div class="ms-section-inner">
      <div class="ms-section-head">
        <div class="ms-eyebrow">Price Trend</div>
        <h2>Is a Square Foot<br><em>Getting More Expensive?</em></h2>
        <p>Median sold price per square foot, {label}, tracked as a rolling 12-month figure so one unusually large or small sale doesn't swing the whole trend.</p>
      </div>
      {current_html}
      <div class="ms-chart-wrap">
        <div class="ms-chart-title">$ / Sq Ft &middot; Rolling 12 Months</div>
        <div class="ms-chart-sub">{cfg.get("geo_description", label)}</div>
        <div class="ms-chart-canvas-wrap">
          <canvas id="chartPpsfTrend" height="260"></canvas>
        </div>
      </div>
      <p class="ms-chart-sub" style="margin-top:14px;">{" &middot; ".join(notes)}</p>
    </div>
  </div>'''.replace('\n      \n', '\n'), {"labels": labels, "data": data, "tiers": tiers}


def build_supply_trend_section(cfg, region):
    """Sales-to-new-listings ratio, month by month — is the market drifting
    toward buyers or sellers, not just what it reads today.

    Convention #74 + #196: needs at least 2 eligible months (the aggregator's
    own build_snlr already withholds a month whose sales or listings count
    isn't trustworthy) — a single point is a reading, not a trend, and this
    ledger only started 2026-05, so depth grows one point per month rather
    than arriving fully formed. Returns (html, chart_data) so build_chart_js
    can render the canvas the html declares; chart_data is None when '' is
    returned, mirroring the ten_year/monthly pattern."""
    snlr = (region or {}).get("snlr") or {}
    by_month = snlr.get("by_month") or {}
    thr = snlr.get("thresholds") or {}
    eligible = sorted(k for k, v in by_month.items() if v.get("eligible"))
    if len(eligible) < 2:
        return "", None
    label = cfg.get("label", "This market")
    buyer_max = thr.get("buyer_max", 40)
    seller_min = thr.get("seller_min", 60)

    color_for = {"buyer": "#60a5fa", "balanced": "#fbbf24", "seller": "#22c55e"}
    labels, data, colors = [], [], []
    for k in eligible:
        v = by_month[k]
        y, m = k.split("-")
        labels.append(f"{MONTH_ABBR[int(m) - 1]} {y}")
        data.append(v["ratio_pct"])
        colors.append(color_for.get(v.get("condition"), "#bbbbbb"))

    html = f'''
  <!-- ═══════ SUPPLY TREND ═══════ -->
  <div class="ms-section ms-section--dark2">
    <div class="ms-section-inner">
      <div class="ms-section-head">
        <div class="ms-eyebrow">Supply Trend</div>
        <h2>Is {label}<br><em>Shifting?</em></h2>
        <p>Sales-to-new-listings ratio, month by month &mdash; under {buyer_max:g}% favours buyers, over {seller_min:g}% favours sellers. This is a new measure we started tracking in May 2026, so it gains one more month every month rather than showing a full year at once.</p>
      </div>
      <div class="ms-chart-wrap">
        <div class="ms-chart-title">Sales-to-New-Listings Ratio</div>
        <div class="ms-chart-sub">{cfg.get("geo_description", label)}</div>
        <div class="ms-chart-canvas-wrap">
          <canvas id="chartSupplyTrend" height="220"></canvas>
        </div>
      </div>
    </div>
  </div>'''
    return html, {"labels": labels, "data": data, "colors": colors,
                  "buyer_max": buyer_max, "seller_min": seller_min}


def build_market_balance_section(cfg, region):
    """Supply-side Market Balance: active inventory, months of supply, the
    buyer's-vs-seller's gauge, and new listings. Data-driven from the
    aggregator's market_balance block. Convention #74: '' when absent."""
    mb = (region or {}).get("market_balance") or {}
    mos = mb.get("months_of_supply")
    active = mb.get("active_inventory")
    label = cfg.get("label", "This market")
    # Two honest "no verdict" states, each with its reason on the page instead
    # of a silent gap under a header that still asks "buyer's or seller's?"
    # (2026-09-07). The reason text is the aggregator's -- rendered, not
    # re-derived. (1) neighbourhood supply-scope withheld; (2) small market.
    withheld = (region or {}).get("market_balance_withheld_reason")
    if not mb and withheld:
        return f'''
  <!-- ═══════ MARKET BALANCE (withheld — neighbourhood scope) ═══════ -->
  <div class="ms-balance">
    <div class="ms-balance-inner">
      <div class="ms-strip-label red">Market Balance — Buyer's vs Seller's Market</div>
      <p class="ms-explainer" style="padding:12px 0 0;">Market balance isn't shown for {html.escape(label)}. {html.escape(withheld)}</p>
    </div>
  </div>'''
    if not mb or mos is None or not active:
        return ""
    if mb.get("small_market"):
        reason = mb.get("small_market_reason") or (
            "Too few sales this year for months of supply to be a reliable read.")
        return f'''
  <!-- ═══════ MARKET BALANCE (withheld — small market) ═══════ -->
  <div class="ms-balance">
    <div class="ms-balance-inner">
      <div class="ms-strip-label red">Market Balance — Buyer's vs Seller's Market</div>
      <div class="ms-balance-verdict">
        <div class="ms-balance-type">Small market</div>
      </div>
      <p class="ms-explainer" style="padding:12px 0 0;">{html.escape(reason)} {html.escape(label)} currently has {fmt_int(active)} homes for sale.</p>
    </div>
  </div>'''
    mtype = mb.get("market_type") or "balanced"
    mtype_label = mb.get("market_type_label") or "Balanced Market"
    rate = mb.get("monthly_sold_rate")
    new_listings = mb.get("new_listings_month")
    pin = min((mos or 0) / 10.0, 0.97) * 100          # 0-10 mo → 0-100% (cap 97)
    rate_disp = fmt_int(round(rate)) if rate is not None else "—"
    new_disp = fmt_int(new_listings) if new_listings is not None else "—"
    verdict_word = {"seller": "seller's-market", "balanced": "balanced-market",
                    "buyer": "buyer's-market"}.get(mtype, "balanced-market")

    # Thresholds come FROM the aggregator so the captions can never drift from
    # the verdict beside them (they had, in three different tools). Defaults
    # match the aggregator's own constants for pages rebuilt off older data.
    thr = mb.get("mos_thresholds") or {}
    seller_max = thr.get("seller_max", 5)
    balanced_max = thr.get("balanced_max", 7)
    _n = lambda v: (f"{v:g}" if isinstance(v, (int, float)) else str(v))

    # New listings for the CURRENT month is a partial count by definition.
    # When the aggregator withheld it (stale listings pull) the cell shows a
    # dash: a truncated flow count reads as a market that stopped, and "3 so
    # far" from a three-day-old pull is worse than no number at all.
    new_label = ("New Listings This Month (so far)"
                 if mb.get("new_listings_month_partial")
                 else "New Listings This Month")
    if mb.get("new_listings_month_stale"):
        new_disp = "—"
        new_label = "New Listings This Month"

    # Sales-to-new-listings — the CREA balance measure. Present only for months
    # the aggregator judged trustworthy on both legs; absent leaves the original
    # four-cell layout untouched, which is the path every sibling config takes.
    snlr = (region or {}).get("snlr") or {}
    snlr_latest = snlr.get("latest") or {}
    snlr_roll = snlr.get("rolling_3mo") or {}
    # Same basis the Market Summary sentence uses -- the rolling 3-month figure
    # when the aggregator has it, the single month otherwise -- so one page never
    # shows two different sales-to-new-listings numbers under loose labels
    # (2026-09-07: summary said 114% for the last three months, the tile said
    # 92% for August). The single month rides along as a sub-line, and the
    # definition sits IN the cell, next to the number it defines.
    basis = snlr_roll if snlr_roll.get("ratio_pct") is not None else snlr_latest
    snlr_cell = ""
    snlr_line = ""
    if basis.get("ratio_pct") is not None:
        def _mabbr(k):
            try:
                return MONTH_ABBR[int(str(k).split("-")[1]) - 1]
            except (ValueError, IndexError):
                return str(k)
        s_sub = ""
        if basis is snlr_roll and snlr_roll.get("months"):
            _ms = list(snlr_roll["months"])
            s_label = f"{_mabbr(_ms[0])}–{_mabbr(_ms[-1])}, 3-month"
            if snlr_latest.get("ratio_pct") is not None:
                s_sub = (f'\n          <div style="font-size:12px;color:#a0a0a0;margin-top:4px;">'
                         f'{_mabbr(snlr_latest.get("month"))} alone: {snlr_latest["ratio_pct"]:.0f}%</div>')
        else:
            s_label = _mabbr(basis.get("month"))
        s_thr = snlr.get("thresholds") or {}
        snlr_cell = f'''
        <div class="ms-annual-stat">
          <div class="ms-annual-num">{basis["ratio_pct"]:.0f}<em>%</em></div>
          <div class="ms-stat-lbl">Sales-to-New-Listings ({s_label})</div>{s_sub}
          <div style="font-size:12px;line-height:1.45;color:#a0a0a0;margin-top:8px;">Homes sold as a share of homes newly listed: under {_n(s_thr.get("buyer_max", 40))}% favours buyers, over {_n(s_thr.get("seller_min", 60))}% favours sellers.</div>
        </div>'''
    grid_mod = " ms-balance-grid--5" if snlr_cell else ""

    # Say when the inventory snapshot was taken. Active counts come from a
    # periodic pull, not from "now", and a page that implies otherwise is
    # making a freshness claim it cannot support.
    feed_date = mb.get("listings_feed_date")
    as_of = ""
    if feed_date:
        try:
            _fd = datetime.strptime(str(feed_date)[:10], "%Y-%m-%d")
            as_of = (f" Listing counts are current as of "
                     f"{MONTH_NAMES[_fd.month - 1]} {_fd.day}, {_fd.year}.")
        except ValueError:
            as_of = ""
    return f'''
  <!-- ═══════ MARKET BALANCE ═══════ -->
  <div class="ms-balance">
    <div class="ms-balance-inner">
      <div class="ms-strip-label red">Market Balance — Buyer's vs Seller's Market</div>
      <div class="ms-balance-verdict">
        <div class="ms-balance-type ms-balance-type--{mtype}">{mtype_label}</div>
        <div class="ms-balance-gauge">
          <div class="ms-gauge-bar">
            <span class="ms-gauge-zone ms-gauge-zone--seller">Seller's<small>under {_n(seller_max)} mo</small></span>
            <span class="ms-gauge-zone ms-gauge-zone--balanced">Balanced<small>{_n(seller_max)}–{_n(balanced_max)} mo</small></span>
            <span class="ms-gauge-zone ms-gauge-zone--buyer">Buyer's<small>{_n(balanced_max)}+ mo</small></span>
            <div class="ms-gauge-pin" style="left:{pin:.0f}%"></div>
          </div>
        </div>{snlr_line}
      </div>
      <div class="ms-annual-grid ms-balance-grid{grid_mod}">
        <div class="ms-annual-stat">
          <div class="ms-annual-num">{fmt_int(active)}</div>
          <div class="ms-stat-lbl">Homes For Sale Now</div>
        </div>
        <div class="ms-annual-stat">
          <div class="ms-annual-num">{mos}<em>&nbsp;mo</em></div>
          <div class="ms-stat-lbl">Months of Supply</div>
        </div>
        <div class="ms-annual-stat">
          <div class="ms-annual-num">{rate_disp}<em>/mo</em></div>
          <div class="ms-stat-lbl">Homes Sold per Month</div>
        </div>
        <div class="ms-annual-stat">
          <div class="ms-annual-num">{new_disp}</div>
          <div class="ms-stat-lbl">{new_label}</div>
        </div>{snlr_cell}
      </div>
    </div>
  </div>
  <p class="ms-explainer" style="padding:12px 24px; max-width:1000px; margin:0 auto;">Months of supply is how long it would take to sell every home currently for sale at the recent pace of sales. Under {_n(seller_max)} months is a seller's market — tight supply, firm prices. {_n(balanced_max)} months or more favours buyers. {label} is in {verdict_word} territory.{as_of}</p>'''


def build_pricing_strategy_section(cfg, region):
    """Pricing Strategy — how the sale-to-ask ratio erodes the longer a home
    sits on market. The single strongest seller-education chart (price it right
    in week 1 vs leave money on the table by week 6+). Data-driven from the
    aggregator's dom_sa block. Convention #74: '' when absent/thin."""
    ds = (region or {}).get("dom_sa") or {}
    weeks = ds.get("weeks") or []
    sa = ds.get("sa") or []
    if not ds or len(weeks) < 4 or not sa:
        return ""
    labels = ds.get("labels") or [str(w) for w in weeks]
    best = ds.get("best_sa") or 0
    worst = ds.get("worst_late_sa") or 0
    drop = ds.get("drop_pts") or 0
    impact = ds.get("dollar_impact_400k") or 0
    label = cfg.get("label", "the local")
    geo = cfg.get("geo_description", "")

    def _ratio_class(v):
        if v >= 98.5:
            return "ms-ratio-high"
        if v >= 96.0:
            return "ms-ratio-mid"
        return "ms-ratio-low"

    rows = "".join(
        f'''
              <tr data-n="{cnt}">
                <td>Week {lab}</td>
                <td><span class="ms-ratio {_ratio_class(v)}">{v:.2f}%</span></td>
                <td>{dom_sa_signal(v)}</td>
              </tr>'''
        for lab, v, cnt in zip(labels, sa, (ds.get("n") or [0] * len(sa)))
    )
    st = dom_sa_story(ds)
    if st:
        _win = (st["window_text"] + " (" + html.escape(label) + " data), homes") if st["window_text"] else "Homes"
        _win = _win[0].upper() + _win[1:]
        intro_html = (
            f'<p>{_win} that sold in {st["early_label"]} closed at an average of <strong>{st["early_avg"]:.1f}%</strong> '
            f'of asking, across {st["early_n"]:,} sales. Homes that took {st["late_label"]} closed at an average of '
            f'<strong>{st["late_avg"]:.1f}%</strong>, across {st["late_n"]:,} sales.</p>\n'
            f'          <p>The gap is {st["gap_pts"]:.1f} percentage points between the two sale-to-list ratios, or about '
            f'<strong>${st["gap_dollars"]:,.0f}</strong> on a $400,000 home. This compares two different groups of homes. '
            f'They differ in condition, type, location and starting price, so the gap is not a loss to any one seller.</p>\n'
            f'          <p>Each figure is a percentage of the asking price, so the gap is stated in percentage points. Homes that took '
            f'{st["late_label"]} sold at an average of {st["late_avg"]:.1f}% of asking, {st["late_below_asking"]:.1f} percentage points '
            f'under asking.</p>\n'
            f'          <p>Ask us for the recent sales near you before you set a price.</p>')
        insights_html = (
            f'''<div class="ms-insight">
            <div class="ms-insight-label">The Takeaway for Sellers</div>
            <p>Homes that sold in {st["early_label"]} averaged {st["early_avg"]:.1f}% of asking. Homes that took {st["late_label"]} averaged {st["late_avg"]:.1f}%. On a $400,000 home that gap is about <strong>${st["gap_dollars"]:,.0f}</strong>. These are different homes, so this describes a pattern in the data, not what any one sale would have done.</p>
          </div>
          <div class="ms-insight">
            <div class="ms-insight-label">The Opportunity for Buyers</div>
            <p>Homes that took {st["late_label"]} closed at an average of <strong>{st["late_avg"]:.1f}%</strong> of asking, {st["late_below_asking"]:.1f} percentage points under asking. Long-listed homes are where buyers often have the most room to negotiate. Every home is different, so check its own recent sales.</p>
          </div>''')
    else:
        intro_html = (f'<p>The table shows the average sale-to-ask ratio for {html.escape(label)} homes by the number of weeks '
                      f'they were on the market, from {ds.get("n_total", 0):,} sales.</p>')
        insights_html = ""
    return f'''
  <!-- ═══════ PRICING STRATEGY (DOM vs S/A) ═══════ -->
  <div class="ms-section ms-section--dark2">
    <div class="ms-section-inner">
      <div class="ms-analysis">
        <div class="ms-analysis-text">
          <div class="ms-eyebrow">Pricing Strategy</div>
          <h2>Days on Market and<br><em>Sale Price.</em></h2>
          {intro_html}
          <p>This is what the {html.escape(label)} data shows, updated every month.</p>
          <div class="ms-chart-wrap" style="margin-top:32px;">
            <div class="ms-chart-title">Impact of Days on Market on Sale-to-Ask %</div>
            <div class="ms-chart-sub">{geo} &middot; by week on market &middot; trailing 24 months</div>
            <div class="ms-chart-canvas-wrap">
              <canvas id="chartDOMSA"></canvas>
            </div>
          </div>
        </div>
        <div>
          <div class="ms-table-scroll">
            <table class="ms-dom-table">
              <thead>
                <tr><th>Time on Market</th><th>Avg S/A Ratio</th><th>{DOM_SA_SIGNAL_HEADER}</th></tr>
              </thead>
              <tbody>{rows}
              </tbody>
            </table>
          </div>
          {insights_html}
        </div>
      </div>
    </div>
  </div>'''


def build_chart_js(cfg, ten_year_data, monthly_data, dom_sa=None, supply_trend=None,
                   community_data=None, price_bands_data=None, ppsf_trend=None):
    """Build the Chart.js script block at end of body."""
    baseline_year = cfg.get("baseline_year", 2025)
    current_year = baseline_year + 1
    price_max = ten_year_data.get("price_max", 400000)
    units_max = ten_year_data.get("units_max", 250)

    # Compute chart bounds from monthly data
    prior_prices = [p for p in monthly_data["prior_price"] if p is not None]
    curr_prices = [p for p in monthly_data["current_price"] if p is not None]
    all_prices = prior_prices + curr_prices
    price_chart_min = max(0, (min(all_prices) - 50) // 50 * 50) if all_prices else 0
    price_chart_max = ((max(all_prices) + 80) // 50 * 50) if all_prices else 500

    prior_units = [u for u in monthly_data["prior_units"] if u is not None]
    curr_units = [u for u in monthly_data["current_units"] if u is not None]
    all_units = prior_units + curr_units
    units_chart_max = max(max(all_units) + 5, 10) if all_units else 30

    prior_dom = [d for d in monthly_data["prior_dom"] if d is not None]
    curr_dom = [d for d in monthly_data["current_dom"] if d is not None]
    all_dom = prior_dom + curr_dom
    dom_chart_max = max(max(all_dom) + 20, 50) if all_dom else 150

    prior_at = [a for a in monthly_data["prior_at100"] if a is not None]
    curr_at = [a for a in monthly_data["current_at100"] if a is not None]
    all_at = prior_at + curr_at
    at100_max = max(max(all_at) + 3, 10) if all_at else 15

    # Dynamic S/A axis (2026-06-12, Mike-flagged): the old hardcoded 94.5-100.5
    # band CLIPPED any month outside it (a single 102% over-ask sale shot the
    # line off the chart on small-market pages). Bound to the data, padded.
    all_sa = [v for v in (monthly_data["prior_sa"] + monthly_data["current_sa"]) if v is not None]
    sa_chart_min = min(94.5, (min(all_sa) - 1.0)) if all_sa else 94.5
    sa_chart_max = max(100.5, (max(all_sa) + 1.0)) if all_sa else 100.5
    sa_chart_min = round(sa_chart_min * 2) / 2
    sa_chart_max = round(sa_chart_max * 2) / 2

    chart_labels = monthly_data.get("_labels")  # quarterly labels in small-market mode

    # Pricing Strategy chart (DOM vs S/A%) — only emitted when the aggregator
    # produced a credible curve (Convention #74; thin markets omit it).
    dom_sa_js = ""
    if dom_sa and dom_sa.get("sa"):
        dvals = dom_sa["sa"]
        dlabels = [f"Wk {l}" for l in dom_sa.get("labels", [str(w) for w in dom_sa.get("weeks", [])])]
        bar_colors = ["rgba(34,197,94,0.78)" if v >= 98.5
                      else "rgba(251,191,36,0.78)" if v >= 96.0
                      else "rgba(234,0,42,0.78)" for v in dvals]
        bar_borders = [c.replace("0.78", "1") for c in bar_colors]
        dom_min = max(0, int(min(dvals)) - 2)
        dom_max = min(102, int(max(dvals)) + 2)
        dom_sa_js = f'''
  // ── Pricing Strategy: Days on Market vs Sale-to-Ask % ──
  new Chart(document.getElementById('chartDOMSA'), {{
    type: 'bar',
    data: {{
      labels: {json.dumps(dlabels)},
      datasets: [{{
        label: 'S/A %', data: {json.dumps(dvals)},
        backgroundColor: {json.dumps(bar_colors)},
        borderColor: {json.dumps(bar_borders)},
        borderWidth: 1, borderRadius: 2
      }}]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ backgroundColor: '#1a1a1a', borderColor: '#333', borderWidth: 1, titleColor: '#fff', bodyColor: '#d0d0d0', padding: 12, titleFont: {{ size: 14, family: 'Roboto' }}, bodyFont: {{ size: 13, family: 'Roboto' }}, callbacks: {{ label: function(ctx) {{ return 'S/A Ratio: ' + ctx.raw + '%'; }} }} }}
      }},
      scales: {{
        x: {{ grid: {{ color: GRID_COLOR }}, ticks: {{ color: TICK_COLOR, font: {{ size: 13, family: 'Roboto' }} }}, border: {{ color: '#333' }} }},
        y: {{ min: {dom_min}, max: {dom_max}, grid: {{ color: GRID_COLOR }}, ticks: {{ color: TICK_COLOR, font: {{ size: 13, family: 'Roboto' }}, callback: function(v) {{ return v + '%'; }} }}, border: {{ color: '#333' }} }}
      }}
    }}
  }});'''

    # Supply Trend (sales-to-new-listings ratio) — only emitted when
    # build_supply_trend_section found >=2 eligible months (Convention #74;
    # the section and its chart share the same data, so one can't render
    # without the other).
    supply_trend_js = ""
    if supply_trend and supply_trend.get("data"):
        st_max = max(100.0, max(supply_trend["data"]) + 10)
        supply_trend_js = f'''
  // ── Supply Trend: Sales-to-New-Listings Ratio by month ──
  new Chart(document.getElementById('chartSupplyTrend'), {{
    type: 'bar',
    data: {{
      labels: {json.dumps(supply_trend["labels"])},
      datasets: [{{
        label: 'Sales-to-New-Listings %', data: {json.dumps(supply_trend["data"])},
        backgroundColor: {json.dumps(supply_trend["colors"])},
        borderColor: {json.dumps(supply_trend["colors"])},
        borderWidth: 1, borderRadius: 3
      }}]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ backgroundColor: '#1a1a1a', borderColor: '#333', borderWidth: 1, titleColor: '#fff', bodyColor: '#d0d0d0', padding: 12, titleFont: {{ size: 14, family: 'Roboto' }}, bodyFont: {{ size: 13, family: 'Roboto' }}, callbacks: {{ label: function(ctx) {{ return ctx.raw + '% sales-to-new-listings'; }} }} }}
      }},
      scales: {{
        x: {{ grid: {{ color: GRID_COLOR }}, ticks: {{ color: TICK_COLOR, font: {{ size: 13, family: 'Roboto' }} }}, border: {{ color: '#333' }} }},
        y: {{ min: 0, max: {st_max}, grid: {{ color: GRID_COLOR }}, ticks: {{ color: TICK_COLOR, font: {{ size: 13, family: 'Roboto' }}, callback: function(v) {{ return v + '%'; }} }}, border: {{ color: '#333' }} }}
      }}
    }}
  }});'''

    # $/sq ft trend, rolling 12mo (2026-09-18). A LINE (not bar, unlike its
    # sibling supply-trend chart above) since this is one continuous figure
    # moving over many months rather than a per-month ratio; limited-tier
    # points draw as larger hollow-style markers so a thin month reads as
    # thin without breaking the line, and a genuine None (withheld) gap is
    # never bridged (spanGaps left at its false default).
    ppsf_trend_js = ""
    if ppsf_trend and ppsf_trend.get("data") and any(v is not None for v in ppsf_trend["data"]):
        pt_vals = [v for v in ppsf_trend["data"] if v is not None]
        pt_min = max(0, (min(pt_vals) - 15) // 10 * 10)
        pt_max = ((max(pt_vals) + 15) // 10 + 1) * 10
        pt_radius = [3 if t == "ok" else (5 if t == "limited" else 0) for t in ppsf_trend["tiers"]]
        pt_fill = ["#EA002A" if t == "ok" else "rgba(234,0,42,0.15)" for t in ppsf_trend["tiers"]]
        ppsf_trend_js = f'''
  // ── Price Trend: $/sq ft, rolling 12 months ──
  new Chart(document.getElementById('chartPpsfTrend'), {{
    type: 'line',
    data: {{
      labels: {json.dumps(ppsf_trend["labels"])},
      datasets: [{{
        label: '$ / sq ft', data: {json.dumps(ppsf_trend["data"])},
        borderColor: '#EA002A', backgroundColor: 'rgba(234,0,42,0.08)',
        pointBackgroundColor: {json.dumps(pt_fill)}, pointBorderColor: '#EA002A',
        pointRadius: {json.dumps(pt_radius)},
        pointHoverRadius: 6, borderWidth: 2, tension: 0.25, fill: true, spanGaps: false
      }}]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ backgroundColor: '#1a1a1a', borderColor: '#333', borderWidth: 1, titleColor: '#fff', bodyColor: '#d0d0d0', padding: 12, titleFont: {{ size: 14, family: 'Roboto' }}, bodyFont: {{ size: 13, family: 'Roboto' }}, callbacks: {{ label: function(ctx) {{ return ctx.raw == null ? 'Too few sales this month' : '$' + ctx.raw.toLocaleString() + ' / sq ft'; }} }} }}
      }},
      scales: {{
        x: {{ grid: {{ color: GRID_COLOR }}, ticks: {{ color: TICK_COLOR, font: {{ size: 11, family: 'Roboto' }}, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 }}, border: {{ color: '#333' }} }},
        y: {{ min: {pt_min}, max: {pt_max}, grid: {{ color: GRID_COLOR }}, ticks: {{ color: TICK_COLOR, font: {{ size: 13, family: 'Roboto' }}, callback: function(v) {{ return '$' + v; }} }}, border: {{ color: '#333' }} }}
      }}
    }}
  }});'''

    # Community bar chart (2026-07-30, Mike: interactive charts throughout).
    # Horizontal orientation — community NAMES are the thing a viewer scans,
    # and a horizontal bar keeps every label readable at full length instead
    # of rotating/truncating vertical-bar x-axis ticks.
    community_js = ""
    if community_data and community_data.get("labels"):
        community_max = max(community_data["counts"] + [1])
        community_js = f'''
  // ── Community Snapshot: Sales YTD by community (horizontal bar) ──
  new Chart(document.getElementById('chartCommunity'), {{
    type: 'bar',
    data: {{
      labels: {json.dumps(community_data["labels"])},
      datasets: [{{
        label: 'Sales YTD', data: {json.dumps(community_data["counts"])},
        backgroundColor: 'rgba(234,0,42,0.65)', borderColor: 'rgba(234,0,42,0.9)',
        borderWidth: 1, borderRadius: 3
      }}]
    }},
    options: {{
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ backgroundColor: '#1a1a1a', borderColor: '#333', borderWidth: 1, titleColor: '#fff', bodyColor: '#d0d0d0', padding: 12, titleFont: {{ size: 14, family: 'Roboto' }}, bodyFont: {{ size: 13, family: 'Roboto' }}, callbacks: {{ label: function(ctx) {{ return ctx.raw + ' sale' + (ctx.raw === 1 ? '' : 's') + ' YTD'; }} }} }}
      }},
      scales: {{
        x: {{ min: 0, max: {community_max + 2}, grid: {{ color: GRID_COLOR }}, ticks: {{ color: TICK_COLOR, font: {{ size: 12, family: 'Roboto' }} }}, border: {{ color: '#333' }} }},
        y: {{ grid: {{ display: false }}, ticks: {{ color: TICK_COLOR, font: {{ size: 12, family: 'Roboto' }} }}, border: {{ color: '#333' }} }}
      }}
    }}
  }});'''

    # Price Bands grouped bar chart (2026-07-30, Mike: interactive charts
    # throughout) — current vs prior year count per band, sitting above the
    # existing width-bar breakdown. prior_counts defaults to 0 per band
    # (never omitted) so a genuinely-empty prior band draws as a zero-height
    # bar rather than a gap that reads as missing data.
    price_bands_js = ""
    if price_bands_data and price_bands_data.get("labels"):
        pb_all = price_bands_data["current_counts"] + price_bands_data["prior_counts"]
        pb_max = max(pb_all + [1])
        price_bands_js = f'''
  // ── Price Bands: current vs. prior year, by band ──
  new Chart(document.getElementById('chartPriceBands'), {{
    type: 'bar',
    data: {{
      labels: {json.dumps(price_bands_data["labels"])},
      datasets: [
        {{
          label: '{current_year}', data: {json.dumps(price_bands_data["current_counts"])},
          backgroundColor: 'rgba(234,0,42,0.7)', borderColor: 'rgba(234,0,42,0.95)',
          borderWidth: 1, borderRadius: 3
        }}{"," if price_bands_data.get("has_prior") else ""}
        {f"""{{
          label: '{baseline_year}', data: {json.dumps(price_bands_data["prior_counts"])},
          backgroundColor: 'rgba(255,255,255,0.25)', borderColor: 'rgba(255,255,255,0.5)',
          borderWidth: 1, borderRadius: 3
        }}""" if price_bands_data.get("has_prior") else ""}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: {json.dumps(bool(price_bands_data.get("has_prior")))}, labels: {{ color: TICK_COLOR, font: {{ size: 12, family: 'Roboto' }}, boxWidth: 14 }} }},
        tooltip: {{ backgroundColor: '#1a1a1a', borderColor: '#333', borderWidth: 1, titleColor: '#fff', bodyColor: '#d0d0d0', padding: 12, titleFont: {{ size: 14, family: 'Roboto' }}, bodyFont: {{ size: 13, family: 'Roboto' }}, callbacks: {{ label: function(ctx) {{ return ctx.dataset.label + ': ' + ctx.raw + ' sale' + (ctx.raw === 1 ? '' : 's'); }} }} }}
      }},
      scales: {{
        x: {{ grid: {{ color: GRID_COLOR }}, ticks: {{ color: TICK_COLOR, font: {{ size: 12, family: 'Roboto' }} }}, border: {{ color: '#333' }} }},
        y: {{ min: 0, max: {pb_max + 2}, grid: {{ color: GRID_COLOR }}, ticks: {{ color: TICK_COLOR, font: {{ size: 13, family: 'Roboto' }} }}, border: {{ color: '#333' }} }}
      }}
    }}
  }});'''

    return f'''
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
<script>
(function() {{
  window.__tcMarket = {{ region: {json.dumps(cfg.get("label", ""))} }};
  var MONTHS = {json.dumps(chart_labels or MONTH_ABBR)};
  var GRID_COLOR = 'rgba(255,255,255,0.10)';
  var TICK_COLOR = '#9a9a9a';
  var GREEN = '#22c55e';
  var WHITE = '#ffffff';
  var RED = '#EA002A';

  function baseOpts(yMin, yMax, yCallback) {{
    return {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: '#1a1a1a', borderColor: '#333', borderWidth: 1,
          titleColor: '#fff', bodyColor: '#d0d0d0', padding: 12,
          titleFont: {{ size: 14, family: 'Roboto' }}, bodyFont: {{ size: 13, family: 'Roboto' }},
          callbacks: yCallback ? {{ label: yCallback }} : {{}}
        }}
      }},
      scales: {{
        x: {{ grid: {{ color: GRID_COLOR }}, ticks: {{ color: TICK_COLOR, font: {{ size: 13, family: 'Roboto' }} }}, border: {{ color: '#333' }} }},
        y: {{ min: yMin, max: yMax, grid: {{ color: GRID_COLOR }}, ticks: {{ color: TICK_COLOR, font: {{ size: 13, family: 'Roboto' }} }}, border: {{ color: '#333' }} }}
      }}
    }};
  }}

  function dsPrior(data, color) {{
    return {{
      label: '{baseline_year}', data: data,
      borderColor: color || GREEN, backgroundColor: 'transparent',
      pointBackgroundColor: color || GREEN, pointRadius: 5, pointHoverRadius: 7,
      tension: 0.1, borderWidth: 3, spanGaps: true
    }};
  }}

  function dsCurrent(data) {{
    return {{
      label: '{current_year}', data: data,
      borderColor: WHITE, backgroundColor: 'transparent',
      pointBackgroundColor: WHITE, pointStyle: 'rectRot', pointRadius: 6, pointHoverRadius: 8,
      tension: 0, borderWidth: 3, borderDash: [4,3], spanGaps: true
    }};
  }}

  // ── 10-Year Trend (combo bar + line) ──
  new Chart(document.getElementById('chart10Year'), {{
    type: 'bar',
    data: {{
      labels: {ten_year_data["labels"]},
      datasets: [
        {{
          label: 'Number of Sales',
          data: {ten_year_data["sales"]},
          backgroundColor: {ten_year_data["sales"]}.map(function(v,i,a) {{ return i === a.length - 1 ? 'rgba(234,0,42,0.35)' : 'rgba(234,0,42,0.6)'; }}),
          borderColor: {ten_year_data["sales"]}.map(function(v,i,a) {{ return i === a.length - 1 ? 'rgba(234,0,42,0.5)' : 'rgba(234,0,42,0.9)'; }}),
          borderWidth: 1, borderRadius: 3, yAxisID: 'y1', order: 2
        }},
        {{
          label: 'Avg Sale Price',
          data: {ten_year_data["prices"]},
          type: 'line', borderColor: GREEN, backgroundColor: 'transparent',
          pointBackgroundColor: GREEN, pointRadius: 6, pointHoverRadius: 8,
          tension: 0.2, borderWidth: 3, yAxisID: 'y', order: 1
        }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: '#1a1a1a', borderColor: '#333', borderWidth: 1,
          titleColor: '#fff', bodyColor: '#d0d0d0', padding: 12,
          titleFont: {{ size: 14, family: 'Roboto' }}, bodyFont: {{ size: 13, family: 'Roboto' }},
          callbacks: {{
            label: function(ctx) {{
              if (ctx.dataset.yAxisID === 'y') return 'Avg Price: $' + ctx.raw.toLocaleString();
              return 'Sales: ' + ctx.raw;
            }}
          }}
        }},
        // Zoom/pan on the 10-year chart only (2026-07-30, Mike: interactive
        // for the YouTube recording use case — scroll or pinch to zoom into
        // a stretch of years, drag to pan). Scoped to this one chart, not
        // every chart, per Mike's sign-off. mode:'x' only (year axis) — a
        // y-zoom would distort the price/units comparison the chart exists
        // to show. Reset button wired below via data-reset-zoom.
        zoom: {{
          pan: {{ enabled: true, mode: 'x' }},
          zoom: {{ wheel: {{ enabled: true }}, pinch: {{ enabled: true }}, mode: 'x' }},
          limits: {{ x: {{ minRange: 3 }} }}
        }}
      }},
      scales: {{
        x: {{ grid: {{ color: GRID_COLOR }}, ticks: {{ color: TICK_COLOR, font: {{ size: 13, family: 'Roboto' }} }}, border: {{ color: '#333' }} }},
        y: {{
          position: 'left', min: 0, max: {price_max},
          grid: {{ color: GRID_COLOR }},
          ticks: {{ color: TICK_COLOR, font: {{ size: 13, family: 'Roboto' }}, callback: function(v) {{ return '$' + (v/1000) + 'K'; }} }},
          border: {{ color: '#333' }},
          title: {{ display: true, text: 'Average Sale Price', color: TICK_COLOR, font: {{ size: 13, family: 'Roboto' }} }}
        }},
        y1: {{
          position: 'right', min: 0, max: {units_max},
          grid: {{ drawOnChartArea: false }},
          ticks: {{ color: TICK_COLOR, font: {{ size: 13, family: 'Roboto' }} }},
          border: {{ color: '#333' }},
          title: {{ display: true, text: 'Number of Sales', color: TICK_COLOR, font: {{ size: 13, family: 'Roboto' }} }}
        }}
      }}
    }}
  }});

  // ── Average Sale Price (monthly) ──
  new Chart(document.getElementById('chartPrice'), {{
    type: 'line',
    data: {{
      labels: MONTHS,
      datasets: [
        dsPrior({json.dumps(monthly_data["prior_price"])}),
        dsCurrent({json.dumps(monthly_data["current_price"])})
      ]
    }},
    options: {{
      ...baseOpts({price_chart_min}, {price_chart_max}),
      plugins: {{ ...baseOpts({price_chart_min},{price_chart_max}).plugins, tooltip: {{ ...baseOpts({price_chart_min},{price_chart_max}).plugins.tooltip, callbacks: {{ label: function(ctx) {{ return ctx.dataset.label + ': $' + ctx.raw + 'K'; }} }} }} }},
      scales: {{ ...baseOpts({price_chart_min},{price_chart_max}).scales, y: {{ ...baseOpts({price_chart_min},{price_chart_max}).scales.y, ticks: {{ color: TICK_COLOR, font: {{ size: 13, family: 'Roboto' }}, callback: function(v) {{ return '$' + v + 'K'; }} }} }} }}
    }}
  }});

  // ── Units Sold (monthly) ──
  new Chart(document.getElementById('chartUnits'), {{
    type: 'line',
    data: {{
      labels: MONTHS,
      datasets: [
        dsPrior({json.dumps(monthly_data["prior_units"])}),
        dsCurrent({json.dumps(monthly_data["current_units"])})
      ]
    }},
    options: baseOpts(0, {units_chart_max})
  }});

  // ── Average Days on Market (monthly) ──
  new Chart(document.getElementById('chartDOM'), {{
    type: 'line',
    data: {{
      labels: MONTHS,
      datasets: [
        dsPrior({json.dumps(monthly_data["prior_dom"])}),
        dsCurrent({json.dumps(monthly_data["current_dom"])})
      ]
    }},
    options: baseOpts(0, {dom_chart_max})
  }});

  // ── Sold-to-Ask Ratio (monthly) ──
  new Chart(document.getElementById('chartSA'), {{
    type: 'line',
    data: {{
      labels: MONTHS,
      datasets: [
        dsPrior({json.dumps(monthly_data["prior_sa"])}),
        dsCurrent({json.dumps(monthly_data["current_sa"])})
      ]
    }},
    options: {{
      ...baseOpts({sa_chart_min}, {sa_chart_max}),
      plugins: {{ ...baseOpts({sa_chart_min},{sa_chart_max}).plugins, tooltip: {{ ...baseOpts({sa_chart_min},{sa_chart_max}).plugins.tooltip, callbacks: {{ label: function(ctx) {{ return ctx.dataset.label + ': ' + ctx.raw + '%'; }} }} }} }},
      scales: {{ ...baseOpts({sa_chart_min},{sa_chart_max}).scales, y: {{ ...baseOpts({sa_chart_min},{sa_chart_max}).scales.y, ticks: {{ color: TICK_COLOR, font: {{ size: 13, family: 'Roboto' }}, callback: function(v) {{ return v + '%'; }} }} }} }}
    }}
  }});

  // ── # Sold at 100%+ of Asking (monthly) ──
  new Chart(document.getElementById('chartAt100'), {{
    type: 'line',
    data: {{
      labels: MONTHS,
      datasets: [
        dsPrior({json.dumps(monthly_data["prior_at100"])}),
        dsCurrent({json.dumps(monthly_data["current_at100"])})
      ]
    }},
    options: baseOpts(0, {at100_max})
  }});
{dom_sa_js}
{supply_trend_js}
{ppsf_trend_js}
{community_js}
{price_bands_js}

  // ── Legend click-to-toggle (2026-07-30, Mike: make it interactive) ──
  // The "● {baseline_year} ◆ {current_year}" markers above each trend chart
  // were static labels; clicking one now hides/shows that year's line via
  // Chart.js's own dataset-visibility API, with the legend item dimming to
  // show its state. Works for narrating live: "let's just look at this
  // year" — click, the prior-year line disappears.
  document.querySelectorAll('.ms-legend-toggle').forEach(function(el){{
    el.addEventListener('click', function(){{
      var chart = Chart.getChart(el.dataset.chart);
      if (!chart) return;
      var idx = parseInt(el.dataset.dataset, 10);
      var visible = chart.isDatasetVisible(idx);
      chart.setDatasetVisibility(idx, !visible);
      chart.update();
      el.classList.toggle('ms-legend-toggle--off', visible);
    }});
  }});

  // ── Reset Zoom button (10-Year Trend) ──
  document.querySelectorAll('[data-reset-zoom]').forEach(function(btn){{
    btn.addEventListener('click', function(){{
      var chart = Chart.getChart(btn.dataset.resetZoom);
      if (chart && chart.resetZoom) chart.resetZoom();
    }});
  }});
}})();
</script>'''


def _stat_badge(value_html, label):
    """A small number-stack badge for an accordion header row (2026-07-30,
    Mike: give each drop-down a current market stat, not just words).
    Convention #74: caller passes a falsy value_html when no qualifying
    stat exists for that section — the header renders with no badge at
    all rather than a placeholder dash."""
    if not value_html:
        return ""
    return (f'<span class="ms-accordion-badge"><strong>{value_html}</strong>'
            f'<small>{label}</small></span>')


def _verdict_badge(label, market_type):
    """The market-balance verdict as a small colored pill, reusing the exact
    seller/balanced/buyer colors the Market Balance section already uses so
    the accordion badge and the section content never disagree."""
    if not label or not market_type:
        return ""
    return (f'<span class="ms-accordion-badge ms-accordion-badge--pill '
            f'ms-accordion-badge--{market_type}">{label}</span>')


_ACCORDION_CHEVRON_SVG = (
    '<svg class="ms-accordion-chevron" viewBox="0 0 20 20" fill="none" '
    'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    '<path d="M5 7.5L10 12.5L15 7.5" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


def build_accordion_bundle(section_defs):
    """Wrap the report's data sections into a vertical accordion (2026-07-30,
    Mike: replaced an earlier tabs cut with a Wikipedia-mobile-style
    reference screenshot — "organized expandable sections stacked
    vertically where the drop down to view that type of data is obvious
    and you can see a little explainer sentence for each category").

    `section_defs` is an ordered list of (section_id, title, explainer,
    badge_html, [section_html, ...]). badge_html is a small current-market-
    stat pill (2026-07-30, Mike: "each section needs at least something
    visual... a current market stat") rendered on the right of the header
    row; pass '' when no qualifying stat exists for that section (Reference
    has none — see _stat_badge/_verdict_badge). A section whose parts are
    all empty (Convention #74 — every section here can legitimately render
    '' on a thin market) is dropped entirely rather than shipping an empty
    row. If fewer than 2 sections survive that filter, an accordion would
    add a click for no payoff, so the surviving content renders as a flat
    scroll instead — the pre-accordion behaviour, preserved for the
    thinnest configs.

    Unlike tabs, sections toggle INDEPENDENTLY — opening one does not close
    another (matches the real behaviour of Wikipedia's mobile collapsible
    sections, which is the pattern Mike pointed at). The first section
    starts open (mirrors what "This Month" showed by default under the
    tabs cut, so the page still has visible content on first paint rather
    than five bare headers); the rest start collapsed.

    Every panel is emitted server-side regardless of open/closed state
    (CSS display:none, never removed from markup) — a no-JS visitor or a
    search-engine crawler still gets every word; only a human clicking
    through ever sees a section expand.
    """
    resolved = []
    for section_id, title, explainer, badge_html, parts in section_defs:
        body = "\n".join(p for p in parts if p)
        if body.strip():
            resolved.append((section_id, title, explainer, badge_html, body))

    if len(resolved) < 2:
        return "\n".join(body for _id, _t, _e, _b, body in resolved)

    rows = []
    for i, (section_id, title, explainer, badge_html, body) in enumerate(resolved):
        open_state = i == 0
        expanded_attr = "true" if open_state else "false"
        panel_class = " is-open" if open_state else ""
        rows.append(f'''
  <div class="ms-accordion-section">
    <button type="button" class="ms-accordion-header" data-accordion="{section_id}" aria-expanded="{expanded_attr}">
      {_ACCORDION_CHEVRON_SVG}
      <span class="ms-accordion-heading-group">
        <span class="ms-accordion-title">{title}</span>
        <span class="ms-accordion-explainer">{explainer}</span>
      </span>
      {badge_html}
    </button>
    <div class="ms-accordion-panel{panel_class}" data-accordion-panel="{section_id}">
{body}
    </div>
  </div>''')

    rows_html = "\n".join(rows)

    return f'''
  <!-- ═══════ ACCORDION ═══════ -->
  <div class="ms-accordion">{rows_html}
  </div>
<script>
(function(){{
  var headers = document.querySelectorAll('.ms-accordion-header');
  // #hash deep links (2026-09-07): a link to #around-the-region opens that
  // group and scrolls to it -- the Facebook comment, the newsletter and the
  // agent talking points can point at a section, not a collapsed page.
  function openHash(){{
    var id = (location.hash || '').replace('#', '');
    if (!id) return;
    var h = document.querySelector('.ms-accordion-header[data-accordion="' + id + '"]');
    if (h && h.getAttribute('aria-expanded') !== 'true') h.click();
    var el = h || document.getElementById(id);
    if (el) setTimeout(function(){{ el.scrollIntoView({{ block: 'start' }}); }}, 60);
  }}
  window.addEventListener('hashchange', openHash);
  setTimeout(openHash, 0);
  // Share row: copy the page link (falls back to opening it).
  document.querySelectorAll('[data-copy-link]').forEach(function(a){{
    a.addEventListener('click', function(e){{
      if (!navigator.clipboard) return;
      e.preventDefault();
      navigator.clipboard.writeText(a.getAttribute('data-copy-link')).then(function(){{
        var sp = a.querySelector('span'); if (sp) {{ sp.textContent = 'Copied'; setTimeout(function(){{ sp.textContent = 'Copy link'; }}, 1800); }}
      }});
    }});
  }});
  headers.forEach(function(h){{
    h.addEventListener('click', function(){{
      var id = h.dataset.accordion;
      var panel = document.querySelector('.ms-accordion-panel[data-accordion-panel="' + id + '"]');
      var wasOpen = h.getAttribute('aria-expanded') === 'true';
      h.setAttribute('aria-expanded', wasOpen ? 'false' : 'true');
      panel.classList.toggle('is-open', !wasOpen);
      if (!wasOpen) {{
        // Chart.js sizes a canvas from its container at construction time;
        // a chart built while its section is collapsed gets measured at
        // 0x0 — and .resize() alone can NOT recover from that (verified
        // 2026-07-30: even an explicit resize(w,h) against a container
        // that has since gained a real, fixed height leaves the canvas
        // stuck at its construction-time 0x0). The only reliable fix is
        // a destroy+rebuild against the now-visible, fixed-height wrap,
        // done ONCE per chart (data-ms-sized guards repeat opens so a
        // user's zoom/pan state on chart10Year survives a close+reopen).
        panel.querySelectorAll('canvas').forEach(function(c){{
          if (c.dataset.msSized) return;
          var inst = window.Chart && Chart.getChart(c.id);
          if (!inst) return;
          var cfg = {{ type: inst.config.type, data: inst.config.data, options: inst.config.options }};
          inst.destroy();
          new Chart(c, cfg);
          c.dataset.msSized = '1';
        }});
      }}
    }});
  }});
}})();
</script>'''


# ═══════════════════════════════════════════════════════════════════════════
# Page assembly
# ═══════════════════════════════════════════════════════════════════════════

def generate_counts_page(cfg, agg, css_text, region, now, output_path, verbose=False):
    """Counts-and-days-on-market page (sites, D-1021-12). Lab West shows how many homes sold and how long they took, and
    NO sold-price figure: no averages, medians, volumes, sale-to-list or price per square foot. The aggregates this reads
    carry none either (idx-stats-aggregator.strip_sold_prices), so nothing here can reach for one. Selected by
    `sold_prices: false` in the page's YAML."""
    label = cfg.get("label", cfg.get("slug"))
    lab = html.escape(label)
    baseline_year = cfg.get("baseline_year", 2025)
    current_year = baseline_year + 1
    by_year = region.get("by_year") or {}
    ytd = region.get("ytd_complete") or region.get("ytd") or {}
    yoy = (region.get("yoy_complete") if region.get("ytd_complete") else region.get("yoy")) or {}
    thru_iso = region.get("ytd_complete_through_date_iso") if region.get("ytd_complete") else region.get("ytd_through_date_iso")
    thru_month = int(region.get("ytd_complete_through_month") or region.get("ytd_through_month") or 0)
    latest = str(thru_iso or agg.get("latest_close_date") or "")[:10]
    try:
        d = datetime.strptime(latest, "%Y-%m-%d")
        through = f"{_HERO_MONTHS[d.month][:3]} {d.day}, {d.year}"
    except (ValueError, TypeError):
        through = ""
    if not through:
        print("ERROR: no latest close date in the aggregates; refusing to write a page that cannot say what it runs through",
              file=sys.stderr)
        return None

    def _dom(v):
        return f"{float(v):.0f} days" if v else "n/a"

    base = by_year.get(str(baseline_year)) or {}
    # Complete months only (always-on #40): the current year's row and the month table stop at the last complete month, so
    # a half-recorded month is never a row or a point. The aggregates' by_year[current_year] still holds the partial month.
    complete_ym = str(thru_iso or "")[:7]
    first_year = cfg.get("first_complete_year")
    rows = []
    for yr in sorted(by_year, key=int):
        y = by_year[yr]
        if first_year and int(yr) < int(first_year):
            continue
        if int(yr) == current_year:
            y = ytd
        if not y.get("count"):
            continue
        part = f" (January 1 to {html.escape(through)})" if int(yr) == current_year else ""
        rows.append(f"            <tr><td>{yr}{part}</td><td>{fmt_int(y.get('count'))}</td><td>{_dom(y.get('avg_dom'))}</td></tr>")
    table = "\n".join(rows)

    months = region.get("by_year_month") or {}
    mrows = []
    for key in sorted((k for k in months if not complete_ym or k <= complete_ym), reverse=True)[:12]:
        m = months[key]
        if not m.get("count"):
            continue
        yy, mm = key.split("-")
        mrows.append(f"            <tr><td>{_HERO_MONTHS[int(mm)]} {yy}</td><td>{fmt_int(m.get('count'))}</td><td>{_dom(m.get('avg_dom'))}</td></tr>")
    mtable = "\n".join(mrows)
    ytd_n = int(ytd.get("count") or 0)

    strips = []
    if base.get("count"):
        strips.append(f"""
  <div class="ms-annual">
    <div class="ms-annual-inner">
      <div class="ms-strip-label">{baseline_year} Full Year</div>
      <div class="ms-annual-grid">
{build_stat_cell(fmt_int(base.get("count")), "Homes Sold")}
{build_stat_cell(_dom(base.get("avg_dom")), "Average Days on Market")}
      </div>
    </div>
  </div>""")
    suffix = f"vs the same months of {baseline_year}"
    strips.append(f"""
  <div class="ms-ytd">
    <div class="ms-ytd-inner">
      <div class="ms-strip-label red">{current_year}: January 1 to {html.escape(through)}</div>
      <div class="ms-annual-grid">
{build_stat_cell(fmt_int(ytd_n), "Homes Sold", fmt_delta(yoy.get("count_pct"), suffix))}
{build_stat_cell(_dom(ytd.get("avg_dom")), "Average Days on Market", fmt_delta(yoy.get("avg_dom_pct"), suffix, lower_is_better=True))}
      </div>
    </div>
  </div>""")

    first_note = ""
    if first_year:
        first_note = (f" The NLAR feed this page counts from starts part-way through {int(first_year) - 1}, "
                      f"so {first_year} is the first full year shown.")

    body = f"""
  <div class="ms-hero">
    <div class="ms-hero-inner">
      <div class="ms-eyebrow">{html.escape(cfg.get("eyebrow", label + " Market Statistics"))}</div>
      <h1>{html.escape(cfg.get("headline", label))} <em>{html.escape(cfg.get("headline_em", ""))}</em></h1>
      <p class="ms-hero-lede">{html.escape(cfg.get("hero_sub", ""))}</p>
      <p class="ms-hero-caption">Data through {html.escape(through)} (complete months only), sourced from NLAR MLS&reg;. Sold prices are not shown on this page.</p>
    </div>
  </div>
{"".join(strips)}
  <div class="ms-section">
    <div class="ms-section-inner">
      <div class="ms-section-head">
        <h2>Homes sold <em>by year.</em></h2>
        <p>How many homes sold in {lab} each year and how long they took to sell. {current_year} runs through {html.escape(through)}.{first_note}</p>
      </div>
      <div class="ms-table-scroll">
        <table class="ms-10yr-table">
          <thead><tr><th>Year</th><th>Homes Sold</th><th>Average Days on Market</th></tr></thead>
          <tbody>
{table}
          </tbody>
        </table>
      </div>
      <p class="ms-explainer" style="margin-top:20px;">{cfg.get("explainers", {}).get("units_sold", "")} {cfg.get("explainers", {}).get("days_on_market", "")}</p>
    </div>
  </div>
  <div class="ms-section">
    <div class="ms-section-inner">
      <div class="ms-section-head">
        <h2>The last twelve months, <em>month by month.</em></h2>
        <p>{cfg.get("explainers", {}).get("monthly_spotlight", "")}</p>
      </div>
      <div class="ms-table-scroll">
        <table class="ms-10yr-table">
          <thead><tr><th>Month</th><th>Homes Sold</th><th>Average Days on Market</th></tr></thead>
          <tbody>
{mtable}
          </tbody>
        </table>
      </div>
    </div>
  </div>
  <div class="ms-cta" id="ms-cta">
    <div class="ms-cta-inner">
      <h2>{cfg.get("cta_heading", "")}</h2>
      <p>{cfg.get("cta_sub", "")}</p>
      <div class="ms-cta-btns">
        <a href="contact.html" class="ms-cta-white">Contact Mike Turner</a>
        <a href="tel:{cfg.get("cta_phone", "").replace("-", "")}" class="ms-cta-outline">{cfg.get("cta_phone_display", "")}</a>
      </div>
    </div>
  </div>"""
    parts = [build_head(cfg, css_text, current_year), build_nav(cfg), body, build_disclaimer(), build_footer()]
    if SCRIPTS_PARTIAL.exists():
        parts.append(SCRIPTS_PARTIAL.read_text())
    parts.append("\n</body>\n</html>")
    return "\n".join(p for p in parts if p)


def generate_page(cfg, agg, css_text, verbose=False, dry_run=False):
    """
    Generate a complete HTML page from config + aggregator data.
    Returns (html_string, output_path) or (None, None) on failure.
    """
    slug = cfg.get("slug")
    region_key = cfg.get("region_key")
    label = cfg.get("label", slug)
    baseline_year = cfg.get("baseline_year", 2025)
    current_year = baseline_year + 1

    if verbose:
        print(f"  Generating {slug} (region: {region_key})...")

    # Get region data (Convention #74 — skip gracefully if missing)
    region = get_region_data(agg, region_key)
    if region is None:
        print(f"WARNING: No aggregator data for region '{region_key}' "
              f"— skipping {slug}", file=sys.stderr)
        return None, None

    # Convention #18 sanity floor
    ytd = region.get("ytd", {})
    ytd_count = ytd.get("count", 0)
    if ytd_count == 0:
        print(f"WARNING: 0 YTD sales for '{region_key}' — likely bad data, "
              f"skipping {slug}", file=sys.stderr)
        return None, None

    now = datetime.now(timezone.utc)
    # output_root: the page lives at the site root (Lab West: the public URL has always been /market-stats.html)
    output_path = (SITE_ROOT if OUTPUT_ROOT[0] else PAGES_DIR) / f"{slug}.html"

    # `sold_prices: false` (Lab West, D-1021-12): counts and days on market only, no sold-price figure of any kind.
    if cfg.get("sold_prices", True) is False:
        counts_html = generate_counts_page(cfg, agg, css_text, region, now, output_path, verbose=verbose)
        if counts_html is None:
            return None, None
        return counts_html, output_path

    # Per-region gates: Market Balance + Pricing Strategy default ON for the
    # master (Gander) page, OFF for community pages until Mike vets the rural
    # reads (Part C). A community YAML opts in with show_market_balance: true /
    # show_pricing_strategy: true — a pure config flip, no code change. (Plus
    # Convention #74: the builders return '' if the data is missing/thin anyway.)
    is_master = cfg.get("page_type") == "master"
    show_mb = cfg.get("show_market_balance", is_master)
    show_ps = cfg.get("show_pricing_strategy", is_master)
    show_notable = cfg.get("show_notable_sales", is_master)
    show_supply_trend = cfg.get("show_supply_trend", is_master)

    # Which month the page is reporting on, resolved once and shared by the
    # spotlight and the narrative so they cannot describe different months.
    spot = _spotlight_context(region, agg)
    faqs = build_market_faqs(cfg, region, agg, spot)   # FAQPage schema + Quick answers (2026-09-07)

    # SECTION ORDER, grouped into an accordion (2026-07-30, Mike: first "it's
    # just one big long scroll... can we have tabs?", then a Wikipedia-mobile
    # reference screenshot refining that to vertical expandable sections with
    # an explainer sentence per section, rather than a horizontal tab row).
    # The 5 groups keep the same freshest-first narrative the flat page used
    # to read top to bottom — This Month is still the opening beat the monthly
    # video records first (and is the one section open by default), Reference is
    # still the material a reader only needs occasionally. Unlike tabs, each
    # section expands independently — opening one doesn't close another.
    # build_accordion_bundle() drops any group that ends up empty (Convention
    # #74) and, if fewer than 2 groups survive, falls back to a flat join.
    # Ship 2 (2026-09-19): write/refresh this slug's live-numbers og:image
    # card BEFORE build_head so it can pick up the file that just landed on
    # disk. Never raises (Conv #74) -- a card failure must not block the page.
    _write_og_market_card(cfg, region, dry_run=dry_run)

    parts = []
    parts.append(build_head(cfg, css_text, current_year))
    parts.append(build_faq_jsonld(faqs))   # JSON-LD is valid in <body>; keeps the three head forks untouched
    parts.append(build_nav(cfg))
    parts.append(build_hero(cfg, region, now, agg))

    # ── Section 1: This Month — the month that just closed, in plain
    # language, backed by real named sales.
    tab_this_month = []
    if cfg.get("show_monthly_spotlight", is_master):
        tab_this_month.append(build_monthly_spotlight_section(cfg, region, agg, spot))
    if cfg.get("show_market_summary", is_master):
        tab_this_month.append(build_market_summary_section(cfg, region, agg, spot))
    if show_notable:
        tab_this_month.append(build_notable_sales_section(cfg, region, spot))

    # ── Section 2: Market Conditions — buyer's/seller's read right now, its
    # trend over time, and this region's own YTD numbers.
    tab_conditions = []
    if show_mb:
        tab_conditions.append(build_market_balance_section(cfg, region))
    # supply_trend_data feeds build_chart_js below; None when
    # build_supply_trend_section found fewer than 2 eligible months
    # (Convention #74).
    supply_trend_data = None
    if show_supply_trend:
        supply_trend_html, supply_trend_data = build_supply_trend_section(cfg, region)
        tab_conditions.append(supply_trend_html)
    tab_conditions.append(build_current_ytd_strip(cfg, region))
    # (2026-09-07) the 2025 YTD strip is gone -- the deltas on the current
    # strip already carry last year -- and Market Conditions renders OPEN on
    # the page right under the hero instead of inside the accordion.

    # ── Section 3: Around the Region — the community-by-community table, on
    # its own now that it's sortable by volume rather than glued below the
    # YTD strips it used to anchor.
    community_html, community_data = build_community_snapshot_section(cfg, agg)
    tab_region = [community_html]

    # ── Section 4: What's Selling — price distribution + property-type mix.
    # Split out from the old mega "Pricing & Trends" section (2026-07-31,
    # Mike: "Pricing & Trends seems a little long in the tooth, break that
    # up") — this was the single biggest accordion panel on the page, five
    # distinct sub-topics stacked under one header. Splitting it the same
    # way the original tabs→accordion cut split the whole page.
    tab_price_range = []
    price_bands_data = None
    if cfg.get("show_price_bands", is_master):
        price_bands_html, price_bands_data = build_price_bands_section(cfg, region)
        tab_price_range.append(price_bands_html)
    if cfg.get("show_property_type_mix", is_master):
        tab_price_range.append(build_new_construction_section(cfg, region))   # resale vs new builds (2026-09-07)
        tab_price_range.append(build_property_type_mix_section(cfg, region))

    # ── Section 5: Pricing & Trends — narrowed to just the monthly charts
    # (how it's priced THIS year, month by month) now that price-range mix
    # and the ten-year history have their own homes.
    tab_pricing = []
    monthly_html, monthly_data = build_monthly_charts_section(cfg, region)
    tab_pricing.append(monthly_html)
    # $/sq ft over time, right after the monthly price chart it extends.
    # Same opt-in pattern as Market Balance/Pricing Strategy -- master ON by
    # default, a community YAML adds show_ppsf_trend: true once vetted.
    ppsf_trend_data = None
    if cfg.get("show_ppsf_trend", is_master):
        ppsf_trend_html, ppsf_trend_data = build_ppsf_trend_section(cfg, region)
        tab_pricing.append(ppsf_trend_html)
    if show_ps:
        tab_pricing.append(build_pricing_strategy_section(cfg, region))
    # Speed + asking-price shares. Same master-only default as the pricing curve
    # above; a community YAML opts in with show_sale_outcomes: true.
    if cfg.get("show_sale_outcomes", is_master):
        tab_pricing.append(build_sale_outcomes_section(cfg, region))

    # ── Section 6: 10-Year History — the long view, on its own so it isn't
    # buried at the bottom of the old mega-section.
    tab_history = []
    ten_year_html, ten_year_data = build_ten_year_section(cfg, region)
    tab_history.append(ten_year_html)
    tab_history.append(build_full_year_strip(cfg, region))

    # ── Section 7: Reference — definitions and the way out to the rest of
    # the site.
    tab_reference = [build_faq_section(cfg, faqs), build_stat_glossary_section(cfg)]
    if cfg.get("page_type") == "master":
        tab_reference.append(build_hpi_section(cfg))
    tab_reference.append(build_explore_community(cfg))
    if cfg.get("page_type") == "master":
        tab_reference.append(build_cross_region_compare(cfg))

    # ── Accordion header badges (2026-07-30, Mike: "each section needs at
    # least something visual... a current market stat"). Each badge is
    # sourced from data the section beneath it already computed — no new
    # aggregation, so a badge can never disagree with its own section.
    # Convention #74: every source is optional; a badge helper returns ''
    # on a missing/thin value and the header renders with no badge at all.
    spot_current = (spot or {}).get("current") or {}
    badge_this_month = _stat_badge(
        fmt_int(spot_current.get("count")) if spot_current.get("count") else "",
        "sales this month")
    mb = (region or {}).get("market_balance") or {}
    badge_conditions = _verdict_badge(
        "" if mb.get("small_market") else mb.get("market_type_label"),   # thin: no pill
        mb.get("market_type"))
    badge_region = (
        _stat_badge(f'{community_data["labels"][0]} &middot; {community_data["counts"][0]}', "busiest YTD")
        if community_data and community_data.get("labels") else "")
    # Busiest price band this trailing 12 months (2026-07-31) — the same
    # "pull the badge from data the section below already computed" rule
    # as the region badge; find the band with the highest current count.
    badge_price_range = ""
    if price_bands_data and price_bands_data.get("current_counts"):
        top_idx = max(range(len(price_bands_data["current_counts"])),
                      key=lambda i: price_bands_data["current_counts"][i])
        badge_price_range = _stat_badge(price_bands_data["labels"][top_idx], "most sales")
    badge_pricing = _stat_badge(
        f"${spot_current['median_price'] / 1000:.0f}K" if spot_current.get("median_price") else "",
        "median this month")

    _conditions_body = "\n".join(p for p in tab_conditions if p)
    if _conditions_body.strip():
        parts.append(f'''
  <!-- ═══════ MARKET CONDITIONS (open on the page, 2026-09-07) ═══════ -->
  <section class="ms-open-group" id="market-conditions">
    <div class="ms-open-head"><span class="ms-accordion-title">Market Conditions</span><span class="ms-accordion-explainer">Buyer&rsquo;s market or seller&rsquo;s? Where it stands right now, and its trend over time.</span>{badge_conditions}</div>
{_conditions_body}
  </section>''')
    _ten_year_badge = ""
    _by = (region or {}).get("by_year") or {}
    _prev = str(int(current_year) - 1)
    if (_by.get(_prev) or {}).get("count"):
        _ten_year_badge = _stat_badge(f"{int(_by[_prev]['count']):,}", f"sold in {_prev}")
    _ref_badge = _stat_badge(str(len(faqs)), "quick answers") if faqs else ""
    parts.append(build_accordion_bundle([
        ("this-month", "This Month", "The month that just closed &mdash; plain language, real numbers, real sales.", badge_this_month, tab_this_month),
        ("around-the-region", "Around the Region", "Every community side by side, busiest first.", badge_region, tab_region),
        ("whats-selling", "What&rsquo;s Selling", "The price range and property type doing the most business right now.", badge_price_range, tab_price_range),
        ("pricing-trends", "Pricing &amp; Trends", "How homes are priced today, month by month.", badge_pricing, tab_pricing),
        ("ten-year-history", f"{cfg.get('ten_year_start', 2016)}&ndash;{current_year} History", f"Sale prices and sales volume, {cfg.get('ten_year_start', 2016)} to {current_year} ({current_year} is year to date), side by side.", _ten_year_badge, tab_history),
        ("reference", "Reference", "Quick answers, definitions, and where to go next.", _ref_badge, tab_reference),
    ]))

    parts.append(build_cta(cfg))
    parts.append(build_disclaimer())
    parts.append(build_footer())
    # Per-site end-of-body scripts (e.g. Avalon's js/nav.js + js/footer.js that
    # build its JS-driven nav/footer). Gander/Goosebay ship none → no-op.
    if SCRIPTS_PARTIAL.exists():
        parts.append(SCRIPTS_PARTIAL.read_text())
    parts.append(build_chart_js(cfg, ten_year_data, monthly_data,
                                region.get("dom_sa") if show_ps else None,
                                supply_trend_data, community_data, price_bands_data,
                                ppsf_trend_data))
    parts.append("\n</body>\n</html>")

    html = "\n".join(p for p in parts if p)
    return html, output_path


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Generate market-statistics HTML pages from YAML configs "
                    "+ live aggregator data."
    )
    parser.add_argument("--config", help="Path to a specific YAML config file")
    parser.add_argument("--all", action="store_true",
                        help="Generate all pages from all YAMLs in config dir")
    parser.add_argument("--source", default=str(DEFAULT_AGG),
                        help="Path to live-aggregates.json")
    parser.add_argument("--output-root", action="store_true",
                        help="Write each page to the site root (/<slug>.html) with that canonical, not pages/ "
                             "(Lab West's refresh: the public URL has always been /market-stats.html)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute but don't write files")
    parser.add_argument("--verbose", action="store_true",
                        help="Progress logging")

    args = parser.parse_args()
    if args.output_root:
        OUTPUT_ROOT[0] = True

    if not args.config and not args.all:
        print("ERROR: specify --config <path.yml> or --all", file=sys.stderr)
        sys.exit(1)

    # Load aggregator data
    agg = load_aggregates(args.source)
    if agg is None:
        print("WARNING: No aggregator data available. Pages that require it "
              "will be skipped.", file=sys.stderr)

    # Load CSS
    css_text = load_css()

    # Collect configs
    configs = []
    if args.config:
        cfg = load_config(args.config)
        if cfg:
            configs.append(cfg)
    elif args.all:
        for f in sorted(CONFIG_DIR.glob("*.yml")):
            if f.name.startswith("_"):
                continue
            cfg = load_config(f)
            if cfg:
                configs.append(cfg)

    if not configs:
        print("ERROR: No valid configs found.", file=sys.stderr)
        sys.exit(1)

    # Generate pages
    generated = 0
    skipped = 0
    copy_failed = 0
    for cfg in configs:
        html, output_path = generate_page(cfg, agg, css_text, verbose=args.verbose,
                                           dry_run=args.dry_run)
        if html is None:
            skipped += 1
            continue

        # Commentary must agree with the table on the same page (D-1008-22): a page that
        # disagrees is not written, and the run exits 1 after the other pages are done.
        _copy_errs = market_copy_check.check_page(html, output_path.name)
        if _copy_errs:
            for _e in _copy_errs:
                print("  COPY-CHECK FAIL: " + _e, file=sys.stderr)
            copy_failed += 1
            continue

        if args.dry_run:
            print(f"  [dry-run] Would write {output_path} "
                  f"({len(html):,} bytes)")
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html)
            if args.verbose:
                print(f"  Wrote {output_path} ({len(html):,} bytes)")
        generated += 1

    # Always-on heartbeat (Conv #190): a run that legitimately keeps every
    # card as-is (thin market, unchanged data) must be distinguishable from
    # one where the renderer silently stopped working.
    print(f"[og-card] {_OG_CARD_STATS['written']} written, "
          f"{_OG_CARD_STATS['kept_photo']} kept-photo (thin), "
          f"{_OG_CARD_STATS['failed']} failed")

    print(f"\nDone: {generated} generated, {skipped} skipped.")
    if copy_failed:
        print(f"ERROR: {copy_failed} page(s) not written: commentary disagrees with the table.", file=sys.stderr)
        sys.exit(1)
    if skipped > 0:
        sys.exit(0)  # Warnings already emitted; exit clean per Convention #74


if __name__ == "__main__":
    main()
