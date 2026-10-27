#!/usr/bin/env python3
"""
build-community-pages.py — generate THIN, data-bound community pages.

Each page is a concise overview that routes visitors into the four audience hubs
(buyer / seller / relocate / agent). Market stats are read LIVE from
idx-cache/live-aggregates.json — the SAME source build-market-stats-page.py uses —
so the community snapshot can never disagree with the market-stats page (this is
what kills the old "three different average prices on one page" problem). Per-
community data lives in community-config/<slug>.yml with schema-capped list lengths
so no community can regrow into the old 21-section wall.

Chrome (nav/footer) + data helpers are reused from build-market-stats-page.py;
formatters from stats_format.py. Toward the one provincial site: one template +
per-community data, regenerated nightly.

Usage:
  python3 build-community-pages.py --config community-config/gander.yml
  python3 build-community-pages.py --all [--dry-run] [--verbose]
"""
from __future__ import annotations

import argparse
import html as _html
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote as _urlquote  # Batch W5 (2026-08-19) -- watch-community URL param

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml required. pip3 install --user pyyaml", file=sys.stderr)
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
SITE_ROOT = SCRIPT_DIR.parent
DEFAULT_AGG = SITE_ROOT / "tools" / "idx-cache" / "live-aggregates.json"
CONFIG_DIR = SCRIPT_DIR / "community-config"
CSS_BASE = CONFIG_DIR / "_base.css"
PAGES_DIR = SITE_ROOT / "pages"
AGENT_MAP_PATH = SCRIPT_DIR / "community-agent-map.json"

from stats_format import fmt_price_k, fmt_pct, fmt_int  # shared formatters (Phase 0)
import _community_v2 as _cv2  # layout v2 (D-1008-86), byte-identical on the three sites; default v1 = today

# Reuse the market-stats generator's chrome + data helpers (hyphenated file → importlib).
_spec = importlib.util.spec_from_file_location("ms_gen", str(SCRIPT_DIR / "build-market-stats-page.py"))
ms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ms)


def esc(s):
    return _html.escape(str(s)) if s is not None else ""


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_css():
    return CSS_BASE.read_text() if CSS_BASE.exists() else ""


# audience → (card title, hub page, icon, selector word)
HUBS = {
    "buyer":    ("Buying a home",     "buyer-hub.html",    "🔑", "Buy"),
    "seller":   ("Selling your home", "seller-hub.html",   "🏷️", "Sell"),
    "relocate": ("Relocating here",   "relocate-hub.html", "🧭", "Relocate"),
    "agent":    ("Joining our team",  "agent-hub.html",    "🤝", "Join the team"),
}


# Follow Up Boss visitor-tracking pixel (account: royallepage545). Fleet-wide --
# same literal script on all 5 sites. fleet/canonical/tools/inject-fub-pixel.py
# puts this on every already-generated page; this constant keeps it on every
# page this generator produces going forward. Sentinel-gated (`fub-pixel:v1`).
FUB_PIXEL_HEAD = (
    '<!-- fub-pixel:v1 -->\n'
    '<!-- begin Widget Tracker Code -->\n'
    '<script type="text/plain" data-consent="marketing">\n'
    '(function(w,i,d,g,e,t){w["WidgetTrackerObject"]=g;(w[g]=w[g]||function() '
    '{(w[g].q=w[g].q||[]).push(arguments);}),(w[g].ds=1*new Date());(e="script"), '
    '(t=d.createElement(e)),(e=d.getElementsByTagName(e)[0]);t.async=1;t.src=i; '
    'e.parentNode.insertBefore(t,e);}) (window,"https://widgetbe.com/agent",document,"widgetTracker"); '
    'window.widgetTracker("create", "WT-ZOUGZFEJ"); window.widgetTracker("send", "pageview");\n'
    '</script>\n'
    '<!-- end Widget Tracker Code -->\n'
    '<!-- /fub-pixel:v1 -->'
)


def build_head(cfg, css_text):
    """Community-page <head>: standard site chrome CSS (main/mobile/turner-network)
    so the reused nav/footer render, plus the inlined cmx- section styles."""
    domain = cfg.get("domain", "realestategander.com")
    slug = cfg["slug"]
    label = esc(cfg["label"])
    title = esc(cfg.get("title", f"{cfg['label']}, NL Real Estate — Homes for Sale | RLP Turner Realty"))
    desc = esc(cfg.get("meta_description",
                       f"{cfg['label']}, Newfoundland real estate — live MLS listings, market stats, "
                       f"and guides for buyers, sellers, and people relocating to the area."))
    # _resolve_og_image (2026-09-19 share-image ship): reuse the same
    # disk-resolution fallback build-market-stats-page.py's build_head()
    # uses -- this generator's own og_image never had one, which on Avalon
    # let a stale community-config og_image value regenerate a 404'ing tag
    # on every nightly run, even after a hand-patch to the HTML.
    og_image = ms._resolve_og_image(
        cfg.get("og_image", "/images/og/pages-sell-your-home-og.jpg"), slug)
    canonical = f"https://{domain}/pages/{slug}.html"
    gtag = {"realestategander.com": "G-FEMZDX1BJQ", "avalonrealestate.ca": "G-M3VNK9T9ZZ",
            "goosebayrealestate.ca": "G-BGYHM2FYPP", "labwestrealty.com": "GT-M38MJCDZ"}.get(domain, "G-FEMZDX1BJQ")
    # gtag.js loads by the Google tag where Google 404s the G- ID (Mike, B-1007-21).
    gtag_src = {"goosebayrealestate.ca": "GT-KVJZ77ZD", "labwestrealty.com": "GT-M38MJCDZ"}.get(domain, gtag)
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<script src="/data/consent-switch.js" defer></script><script src="/js/consent.js" defer></script><script async type="text/plain" data-consent="analytics" data-src="https://www.googletagmanager.com/gtag/js?id={gtag_src}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{gtag_src}');
</script>
{FUB_PIXEL_HEAD}
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <meta name="description" content="{desc}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{desc}">
  <meta property="og:image" content="https://{domain}{og_image}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="{title}">
  <meta property="og:site_name" content="Royal LePage Turner Realty">
  <meta property="og:type" content="website">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{desc}">
  <meta name="twitter:image" content="https://{domain}{og_image}">
  <title>{title}</title>
  <link rel="canonical" href="{canonical}">
  <link rel="icon" type="image/x-icon" href="../favicon.ico">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Raleway:wght@800;900&family=Roboto:wght@300;400&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="../css/main.css?v=20260916-mobile-a">
  <link rel="stylesheet" href="../css/mobile-fixes.css?v=20260916-mobile-a">
  <link rel="stylesheet" href="../css/turner-network.css?v=20260519-cdn-recovery">
  <link rel="stylesheet" href="../css/ddf-fragment.css?v=20260826-visual-refresh">
  <script src="../js/analytics-events.js" defer></script>
<style>
{css_text}
</style>
</head>
<body>
<div class="nav-top-bar"></div>
<nav class="nav-main-bar"></nav>'''


def build_hero(cfg):
    label = esc(cfg["label"])
    vp = esc(cfg.get("value_prop", ""))
    img = cfg.get("hero_image", "")
    bg = (f"background-image:linear-gradient(rgba(10,10,10,.5),rgba(10,10,10,.82)),url('{img}');"
          if img else "background:linear-gradient(135deg,#0a0a0a,#1a1a1a);")
    btns = "".join(
        f'<a class="cmx-aud" href="{HUBS[h][1]}?community={cfg["slug"]}">{HUBS[h][3]}</a>'
        for h in cfg.get("hubs", []) if h in HUBS)
    selector = f'<div class="cmx-aud-row"><span class="cmx-aud-lbl">I\'m here to…</span>{btns}</div>' if btns else ""
    return f'''
<section class="cmx-hero" style="{bg}">
  <div class="cmx-hero-inner">
    <div class="cmx-eyebrow">Welcome to</div>
    <h1>{label}, NL <span>Real Estate</span></h1>
    <p class="cmx-hero-sub">{vp}</p>
    {selector}
  </div>
</section>'''


def _trailing_12mo(region):
    """Rolling last-12-months window from by_year_month — always CURRENT (rolls
    forward every month) + a full 12-month sample (so the 'homes sold' count never
    looks like a weak partial-year figure). Count and count-weighted days on market
    only: no sold-price figure (sites, D-1021-12). Anchored on the newest month present (which may be the
    current partial month — standard for a trailing-twelve window). Returns {} if
    fewer than 6 months of data are present, so the caller falls back to a full
    year (thin/new markets)."""
    bym = (region or {}).get("by_year_month") or {}
    keys = sorted(bym.keys())
    if not keys:
        return {}
    anchor = keys[-1]                       # e.g. "2026-07"
    ay, am = int(anchor[:4]), int(anchor[5:7])
    want = []
    for i in range(12):
        mm, yy = am - i, ay
        while mm <= 0:
            mm += 12; yy -= 1
        want.append(f"{yy}-{mm:02d}")
    months = [bym[k] for k in want if bym.get(k)]
    if len(months) < 6:
        return {}
    count = sum(m.get("count", 0) or 0 for m in months)
    if count <= 0:
        return {}
    dom_den = sum((m.get("count", 0) or 0) for m in months if m.get("avg_dom"))
    dom_num = sum((m.get("count", 0) or 0) * (m.get("avg_dom") or 0) for m in months if m.get("avg_dom"))
    return {"count": count,
            "avg_dom": (dom_num / dom_den) if dom_den else None}


# Community → sold-rollup link (2026-09-08, Conv #15 port of the Gander block
# shipped 2026-08-24). The Aug-24 build wired this on Gander + Avalon; Goose
# Bay's community page is generator-built too, so a hand edit would have been
# wiped on the next nightly — it belongs here. Emits only when the rollup's
# index.html exists at build time (Conv #74: a town that drops below the
# rollup threshold simply loses the link, never 404s).
SOLD_CITY_SLUGS = {
    "labrador-city": ["labrador-city"],
    "wabush": ["wabush"],
}


def _sold_link_html(cfg):
    slugs = SOLD_CITY_SLUGS.get(cfg["slug"])
    if not slugs:
        return ""
    live = [s for s in slugs if (SITE_ROOT / "listings" / "sold" / s / "index.html").exists()]
    if not live:
        return ""
    label = esc(cfg["label"])
    if len(live) == 1:
        return (f'\n    <a class="cmx-link" style="margin-left:18px;" '
                f'href="/listings/sold/{live[0]}/">Recently sold homes in {label} &rarr;</a>')
    parts = []
    for s in live:
        town_label = esc(s.replace("-", " ").title())
        parts.append(f'\n    <a class="cmx-link" style="margin-left:18px;" '
                     f'href="/listings/sold/{s}/">Recently sold in {town_label} &rarr;</a>')
    return "".join(parts)


SMALL_SNAPSHOT_N = 5  # fewer recorded sales than this: the snapshot says so


def build_snapshot(cfg, region):
    if not region:
        return ""
    # Primary: rolling last-12-months (current + full sample). Fallback: the
    # config's baseline_year (thin/new markets without 6+ months of monthly data).
    win = _trailing_12mo(region)
    if win:
        yr, window_label = win, "Last 12 months"
    else:
        by = cfg.get("baseline_year", 2025)
        yr = ((region or {}).get("by_year") or {}).get(str(by)) or {}
        window_label = str(by)
    if not yr:
        return ""
    cells = [(fmt_int(yr.get("count")), "Homes Sold"),
             (f'{float(yr["avg_dom"]):.0f} days' if yr.get("avg_dom") else "n/a", "Avg Days on Market")]
    # Small-sample label (D-1008-38, 2026-10-08): a snapshot built on one or a
    # handful of recorded sales must say so. One sale is that sale, not an
    # "average"; below SMALL_SNAPSHOT_N the figures are a rough guide, not a trend.
    # Count is the same field the "Homes Sold" tile prints, so label and tile agree.
    small_note = ""
    _cnt = int(yr.get("count") or 0)
    _when = "in the last 12 months" if window_label == "Last 12 months" else f"in {window_label}"
    if _cnt == 1:
        small_note = (f'\n    <p class="cmx-small-n" style="margin:12px 0 0;font-size:.95rem;">'
                      f'<strong>Based on one recorded sale</strong> {esc(_when)}. That is one home, not a market average or a trend.</p>')
    elif 1 < _cnt < SMALL_SNAPSHOT_N:
        small_note = (f'\n    <p class="cmx-small-n" style="margin:12px 0 0;font-size:.95rem;">'
                      f'<strong>Based on only {_cnt} recorded sales</strong> {esc(_when)}. That is too few to '
                      f'call a trend; treat these figures as a rough guide.</p>')
    inner = "".join(f'<div class="cmx-stat"><div class="cmx-stat-num">{v}</div>'
                    f'<div class="cmx-stat-lbl">{esc(l)}</div></div>' for v, l in cells)
    ms_url = esc(cfg.get("market_stats_url", f"{cfg['slug']}-market-stats.html"))
    sold_link = _sold_link_html(cfg)  # '' unless the town's sold rollup is live
    # YTD line (2026-09-07, showcase): the same complete-month resale window
    # the card / PDF / homepage quote, with a YoY delta and the verdict pill;
    # gated exactly like them (no delta below 15 sales or on a small sample,
    # no verdict on a small market). '' when the window is missing.
    ytd_line = ""
    _yc = region.get("ytd_complete") or {}
    _yy = region.get("yoy_complete") or {}
    _mb = region.get("market_balance") or {}
    _n = int(_yc.get("count") or 0)
    if _n >= 5:
        _MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                   "August", "September", "October", "November", "December"]
        _thru = region.get("ytd_complete_through_month")
        _yr = region.get("ytd_complete_through_year") or ""
        _win = f"{_yr} through {_MONTHS[int(_thru) - 1]}" if _thru else f"{_yr} year to date"
        _stable = _n >= 15 and not _yy.get("small_sample")
        _pct = _yy.get("count_pct")
        _d = ""
        if _stable and _pct is not None:
            _d = (f' <span style="color:{"#22c55e" if _pct >= 0 else "#ff5e6b"};font-weight:700;">'
                  f'{"&#9650;" if _pct >= 0 else "&#9660;"} {abs(float(_pct)):.0f}% vs last year</span>')
        if _mb.get("small_market") or not _stable:
            _pill = '<span style="display:inline-block;margin-left:10px;padding:3px 10px;border-radius:999px;background:rgba(205,205,212,.14);color:#cdcdd4;font-weight:800;font-size:.78rem;">Small market</span>'
        elif _mb.get("market_type_label"):
            _col = {"seller": "#22c55e", "buyer": "#60a5fa"}.get((_mb.get("market_type") or "").lower(), "#fbbf24")
            _pill = (f'<span style="display:inline-block;margin-left:10px;padding:3px 10px;border-radius:999px;'
                     f'background:rgba(255,255,255,.08);color:{_col};font-weight:800;font-size:.78rem;">{esc(_mb["market_type_label"])}</span>')
        else:
            _pill = ""
        ytd_line = (f'\n    <p style="margin:12px 0 0;font-size:.95rem;">{esc(_win)}: '
                    f'<strong>{_n} homes sold</strong>{_d}{_pill}</p>')
    return f'''
<section class="cmx-section cmx-section-alt">
  <div class="cmx-section-inner">
    <div class="cmx-head-row"><h2>{esc(cfg["label"])} Market Snapshot</h2>
      <span class="cmx-sub">{window_label} · based on MLS® System data owned by the Newfoundland and Labrador Association of REALTORS®</span></div>
    <div class="cmx-snapshot">{inner}</div>{small_note}{ytd_line}
    <a class="cmx-link" href="{ms_url}">Full market data &rarr;</a>{sold_link}
  </div>
</section>'''


def build_listings(cfg):
    frag = cfg.get("ddf_fragment")
    if not frag:
        return ""
    view = esc(cfg.get("listings_view_all", "/listings/"))
    return f'''
<section class="cmx-section">
  <div class="cmx-section-inner">
    <div class="cmx-head-row"><h2>Homes for Sale in {esc(cfg["label"])}</h2>
      <a class="cmx-link" href="{view}">View all {esc(cfg["label"])} homes for sale &rarr;</a></div>
    <!-- DDF_FRAGMENT: {frag} -->
    <div class="cmx-ddf"></div>
<!-- /DDF_FRAGMENT: {frag} -->
  </div>
</section>'''


def build_routes(cfg):
    ctx = cfg.get("hub_context", {})
    cards = []
    for h in cfg.get("hubs", []):
        if h not in HUBS:
            continue
        title, url, icon, _ = HUBS[h]
        cards.append(
            f'<a class="cmx-route" href="{url}?community={cfg["slug"]}">'
            f'<div class="cmx-route-icon">{icon}</div><h3>{esc(title)}</h3>'
            f'<p>{esc(ctx.get(h, ""))}</p><span class="cmx-route-cta">Start here &rarr;</span></a>')
    if not cards:
        return ""
    return f'''
<section class="cmx-section" id="routes">
  <div class="cmx-section-inner">
    <h2 class="cmx-center">How can we help?</h2>
    <div class="cmx-routes">{"".join(cards)}</div>
  </div>
</section>'''


def build_overview(cfg):
    def col(title, items, render):
        if not items:
            return ""
        return f'<div class="cmx-ov-col"><h3>{esc(title)}</h3><ul>{"".join(render(i) for i in items)}</ul></div>'
    cols = (col("Neighbourhoods", cfg.get("neighbourhoods"), lambda i: f"<li>{esc(i)}</li>")
            + col("Schools", cfg.get("schools"), lambda i: f"<li>{esc(i)}</li>")
            + col("Getting around", cfg.get("drive_times"),
                  lambda i: f'<li><span>{esc(i.split("|")[0])}</span>'
                            f'<strong>{esc(i.split("|", 1)[1]) if "|" in i else ""}</strong></li>')
            + col("Life here", cfg.get("lifestyle"), lambda i: f"<li>{esc(i)}</li>"))
    if not cols:
        return ""
    return f'''
<section class="cmx-section cmx-section-alt">
  <div class="cmx-section-inner">
    <h2>About {esc(cfg["label"])}</h2>
    <div class="cmx-overview">{cols}</div>
  </div>
</section>'''


def build_lookup(cfg):
    if not cfg.get("property_lookup"):
        return ""
    comm = esc(cfg.get("property_lookup_community", ""))
    return f'''
<section class="cmx-section">
  <div class="cmx-section-inner">
    <h2>Look Up Any {esc(cfg["label"])} Property</h2>
    <p class="cmx-lead">Check the official municipal zoning, permitted uses, and flood-risk status for
      any address — free, straight from the NL Land Use Atlas.</p>
    <div id="property-lookup-root" data-community="{comm}"></div>
  </div>
</section>'''


def build_explore(cfg):
    rel = cfg.get("related") or []
    if not rel:
        return ""
    links = "".join(f'<a class="cmx-region" href="{esc(s)}.html">{esc(s.replace("-", " ").title())}</a>'
                    for s in rel)
    return f'''
<section class="cmx-section cmx-section-alt">
  <div class="cmx-section-inner">
    <h2>Explore Other Communities</h2>
    <div class="cmx-regions">{links}</div>
  </div>
</section>'''


def build_scripts(cfg):
    site = cfg.get("site_key", "gander")
    # Fixed 2026-09-08 (fleet review): the comment this replaced claimed
    # "Avalon/Goosebay ship an EMPTY nav-main-bar that js/nav.js builds at
    # runtime -- load the wrong one and the nav is blank" and picked
    # mobile-nav.js for Goosebay on that basis. That was backwards for THIS
    # site: build_head() above emits NO nav markup at all for either site --
    # mobile-nav.js only wires up toggle behaviour on markup that has to
    # already exist, so a Goosebay page built by this generator shipped with
    # no nav whatsoever unless someone hand-pasted baked <nav> HTML onto it
    # after generation (which is what happened to happy-valley-goose-bay.html
    # and north-west-river.html -- drift that never survived the next regen
    # cycle uniformly, and carried no region strip). js/nav.js is the one
    # renderer that builds the nav from nothing via find-or-create, so both
    # sites load it the same way, preceded by nav-config.js.
    nav_js = "nav.js"
    s = cfg["slug"]
    # boldtrail-forms.js loaded dynamically (async) so it powers the community
    # "Ask" form that build_agent_cta emits on EVERY community page, without
    # waking the page's dormant exit-intent / sticky-bar.
    lead = ('<script>(function(){var s=document.createElement("script");'
            's.src="../js/boldtrail-forms.js?v=d7dca662";'
            's.onload=function(){'
            'if(window.BoldTrailForms&&BoldTrailForms.communityInquiry)'
            'BoldTrailForms.communityInquiry("#cmx-ask-' + s + '");'
            'if(window.BoldTrailForms&&BoldTrailForms.marketReport&&document.getElementById("cmx-report-' + s + '"))'
            'BoldTrailForms.marketReport("#cmx-report-' + s + '");'
            '};'
            'document.body.appendChild(s);})();</script>\n')
    # Text-alert widget on every community page (task #82, 2026-07-29 -- ported
    # from Gander alongside build_alerts, unconditional).
    lead += '<script src="../js/alert-inline.js" defer></script>\n'
    return f'''{lead}<script src="../js/footer.js?v=20260909-footer-converge"></script>
<script src="../js/regions-data.js" defer></script>
<script src="../js/nav-config.js" defer></script>
<script src="../js/{nav_js}?v=20260909c-nav-parity" defer></script>
<script src="../js/nav-auth.js?v=20260818-portal" defer></script>
<script src="../js/app-shell.js?v=20260920-app8" defer></script>
<script>window.TURNER_SITE='{site}';window.TURNER_API_ORIGIN='https://realestategander.com';</script>
<script src="../js/turner-network.js" defer></script>
<script src="../js/property-lookup.js?v=20260621c-lookup" defer></script>
<script src="../js/chat-widget.js?v=20260611b-listing-ctx" async></script>
</body>
</html>'''



def _cmx_paras(body):
    if isinstance(body, list):
        return "".join(f"<p class='cmx-lead'>{esc(x)}</p>" for x in body if x)
    return f"<p class='cmx-lead'>{esc(body)}</p>" if body else ""

def build_about(cfg):
    blocks = cfg.get("about", [])
    if not blocks:
        return ""
    secs = []
    for i, b in enumerate(blocks):
        h = esc(b.get("heading", ""))
        body = _cmx_paras(b.get("body", ""))
        pts = b.get("points", [])
        pl = ("<ul class='cmx-about-list'>" + "".join(f"<li>{esc(x)}</li>" for x in pts) + "</ul>") if pts else ""
        alt = " cmx-section-alt" if i % 2 else ""
        secs.append(f"<section class='cmx-section{alt}'><div class='cmx-section-inner'><h2>{h}</h2>{body}{pl}</div></section>")
    return "\n".join(secs)

def build_faq(cfg):
    import json as _j
    faqs = cfg.get("faq", [])
    if not faqs:
        return ""
    items = "".join(f"<details class='cmx-faq-item'><summary>{esc(q['q'])}</summary><div class='cmx-faq-a'>{esc(q['a'])}</div></details>" for q in faqs)
    ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q["q"], "acceptedAnswer": {"@type": "Answer", "text": q["a"]}} for q in faqs]}
    return f"<section class='cmx-section cmx-section-alt'><div class='cmx-section-inner'><h2>Frequently Asked Questions</h2><div class='cmx-faq'>{items}</div><script type='application/ld+json'>{_j.dumps(ld)}</script></div></section>"

def place_jsonld(cfg):
    import json as _j
    ld = {"@context": "https://schema.org", "@type": "Place", "name": cfg.get("label", ""), "description": cfg.get("value_prop", ""), "address": {"@type": "PostalAddress", "addressRegion": "NL", "addressCountry": "CA"}}
    return f"<script type='application/ld+json'>{_j.dumps(ld)}</script>"

_REGION_MAP_CACHE = None


def _load_region_map():
    """child community slug -> {label, slug, domain} from tools/region-config/*.yml (cached, site-local)."""
    global _REGION_MAP_CACHE
    if _REGION_MAP_CACHE is not None:
        return _REGION_MAP_CACHE
    import yaml as _y
    m = {}
    rc_dir = Path(__file__).resolve().parent / "region-config"
    if rc_dir.is_dir():
        for f in sorted(rc_dir.glob("*.yml")):
            try:
                r = _y.safe_load(f.read_text())
            except Exception:
                continue
            if not isinstance(r, dict):
                continue
            info = {"label": r.get("label", ""), "slug": r.get("slug", f.stem), "domain": r.get("domain", "")}
            for child in (r.get("children") or []):
                m[child] = info
    _REGION_MAP_CACHE = m
    return m


def build_region_link(cfg):
    """Breadcrumb backlink from a community page up to its region hub — closes the
    internal-linking loop (hub links down; this links child->parent) and passes authority
    to the region head-term via descriptive anchor text. Convention #74: no match -> ''."""
    region = _load_region_map().get(cfg.get("slug", ""))
    if not region:
        return ""
    import json as _j
    dom = region.get("domain", "")
    hub_path = f"/pages/{region['slug']}.html"
    hub_abs = f"https://{dom}{hub_path}" if dom else hub_path
    rlabel = esc(region["label"])
    clabel = esc(cfg.get("label", ""))
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": (f"https://{dom}/" if dom else "/")},
        {"@type": "ListItem", "position": 2, "name": f"{region['label']} Real Estate", "item": hub_abs},
        {"@type": "ListItem", "position": 3, "name": cfg.get("label", "")},
    ]}
    return (
        f'<nav class="cmx-region-crumb" aria-label="Breadcrumb" '
        f'style="max-width:1100px;margin:0 auto;padding:16px 24px 0;font-size:.92rem;color:#9a9a9a">'
        f'<a href="{hub_path}" style="color:#EA002A;font-weight:600;text-decoration:none">'
        f'{rlabel} real estate</a>'
        f'<span style="color:#555;margin:0 8px">&rsaquo;</span>{clabel}'
        f'</nav>'
        f"<script type='application/ld+json'>{_j.dumps(ld)}</script>"
    )


def load_agent_map():
    """community-agent-map.json -> dict; Convention #74 fail-safe to {} on any error."""
    try:
        import json as _j
        return _j.loads(AGENT_MAP_PATH.read_text())
    except Exception:
        return {}


# The 1 Goosebay region_key that has a real market-stats-config AND
# generates a PDF (tools/market-report-pdf.py:SITES["goosebay"] +
# netlify/functions/market-report-subscribe.ts:REGION_AGENT/REGION_STEM must
# all agree, Conv #74: a region not here -> no band). North West River has no
# market-stats-config today and correctly gets no band.
MARKET_REPORT_REGION_KEYS = set()   # Lab West has no market-report PDF


def build_report_band(cfg):
    """Inline market-report PDF capture band (name+email -> instant per-region
    PDF + monthly newsletter), ported from Gander (task #81, 2026-07-29). Posts
    to the SHARED Gander-hosted market-report-subscribe function via
    BoldTrailForms.marketReport (js/boldtrail-forms.js), initialized in
    build_scripts after the script loads."""
    if cfg.get("region_key") not in MARKET_REPORT_REGION_KEYS:
        return ""
    slug = cfg["slug"]
    label = esc(cfg["label"])
    rk = esc(cfg["region_key"])
    return f'''
<section class="cmx-section cmx-report-band" id="market-report">
  <style>.cmx-report-band .cmx-section-inner{{max-width:680px;text-align:center}}.cmx-report-band .cmx-report-form{{margin-top:18px;text-align:left}}</style>
  <div class="cmx-section-inner">
    <div class="cmx-eyebrow">Free download</div>
    <h2>The {label} market, in one report</h2>
    <p class="cmx-lead">A short PDF &mdash; the last 12 months of sales, how this year compares to last, the current market balance, and the 10-year trend for {label}. Updated monthly.</p>
    <div class="cmx-report-form" id="cmx-report-{slug}" data-region-key="{rk}" data-region-label="{label}" data-source="community-page"></div>
  </div>
</section>'''


def build_alerts(cfg):
    """Inline 1-tap text-alert widget (js/alert-inline.js), ported verbatim
    from Gander (task #82, 2026-07-29) -- label scoped per community, no
    account needed, reply STOP anytime. Wired unconditionally into every
    community page (unlike Gander's original 2-page canary gate, removed
    fleet-wide the same day)."""
    label = esc(cfg["label"])
    short = label[4:] if label.lower().startswith("the ") else label
    return f'''
<section class="cmx-section cmx-section-alt cmx-alerts">
  <style>.cmx-alerts .cmx-section-inner{{max-width:680px;text-align:center}}.cmx-alerts .cmx-alert-widget{{margin-top:18px;text-align:left}}</style>
  <div class="cmx-section-inner">
    <div class="cmx-eyebrow">Stay ahead of the market</div>
    <h2>Be the first to see new {short} listings</h2>
    <p class="cmx-lead">Get a text the moment a new home hits the market around {short}. No account needed &mdash; reply STOP anytime.</p>
    <div class="cmx-alert-widget" data-lta-inline data-lta-city="{short}" data-lta-label="All new {short}-area listings"></div>
  </div>
</section>'''


# Real underlying MLS `city` field values per community area, used ONLY to
# build the "Watch this community" deep-link's cities= param (Batch W5,
# 2026-08-19, ported from Gander canonical same day). Reverse-derived from
# this file's OWN CITY_CANONICAL dict -- every raw variant listed here was
# a real observed key that CITY_CANONICAL already maps to the slug, never
# guessed (Conv #199). 
WATCH_CITIES = {
    'labrador-city': ['Labrador City'],
    'wabush': ['Wabush'],
}


def _watch_community_link(city_slug: str, city_label: str) -> str:
    """URL for the 'Watch this community' deep-link into /listings/ --
    prefills cities=<every real spelling variant for this slug> +
    status=both (so the save-search sheet also offers a sold-alert, per
    js/listings-index.js's save=1 handler) + save=1 (auto-opens
    SavedSearch.promptSave on load). Root-absolute: both callers already
    use root-absolute hrefs for this link's neighbours."""
    towns = WATCH_CITIES.get(city_slug) or ([city_label] if city_label else [])
    if not towns:
        return ""
    cities_param = _urlquote(",".join(towns))
    return f"/listings/?cities={cities_param}&status=both&save=1"


def build_agent_cta(cfg, am):
    """Territory-agent card + 'Ask' lead form on every Goosebay community page.

    Goose Bay is served by The Dynamic Duo (Karen Pomeroy + Roberta Primmer, 50-50
    partners), so the duo variant renders BOTH agents on one card and deliberately
    emits an EMPTY data-agent-email: js/boldtrail-forms.js communityInquiry falls
    through to data-team-email (goosebay@royallepage.ca), which lets lead-receive
    round-robin ownership between the partners and CC both (DUO_CC).

    data-agent-phone is set EXPLICITLY because communityInquiry's built-in fallback
    is a Gander number (709-256-7999).

    Card data from community-agent-map.json. Convention #74: unmapped slug -> ''.
    """
    am = am or {}
    a = (am.get("communities") or {}).get(cfg["slug"])
    if not a:
        return ""
    slug = cfg["slug"]
    label = esc(cfg["label"])
    is_duo = a.get("variant") == "duo"
    email = a.get("email", "goosebay@royallepage.ca")
    phone = a.get("phone", "709-896-5001")
    pd = "".join(c for c in phone if c.isdigit())
    head = esc(a.get("headline") or f"Your {cfg['label']} expert")
    tag = esc(a.get("tagline", ""))

    if is_duo:
        agents = a.get("agents", []) or []
        title = esc(a.get("team_name", "The Dynamic Duo"))
        form_name = a.get("form_name", title)
        # overlapping portraits + both names; profile links stay per-agent
        photos = "".join(
            f'<img class="cmx-agent-photo cmx-agent-photo-duo" src="{g.get("photo","")}" '
            f'alt="{esc(g.get("photo_alt",""))}" width="110" height="110" loading="lazy">'
            for g in agents)
        names = esc(" & ".join(g.get("name", "") for g in agents))
        links = "".join(
            f'<a class="cmx-agent-link" href="{g.get("page_link","")}">{esc(g.get("name",""))} &rarr;</a>'
            for g in agents if g.get("page_link"))
        agent_slug = ""  # duo: ownership round-robins server-side, never pinned here
        agent_email = ""  # EMPTY on purpose -> falls through to data-team-email
        photo_block = f'<div class="cmx-agent-photos">{photos}</div>'
        name_block = f"<h2>{title}</h2><div class=\"cmx-agent-names\">{names}</div>"
        link_block = f'<div class="cmx-agent-links">{links}</div>' if links else ""
    else:
        title = esc(a.get("agent_name", ""))
        form_name = a.get("agent_name", "")
        agent_slug = a.get("agent_slug", "")
        agent_email = a.get("email", email)
        pl = a.get("page_link", "")
        photo_block = (f'<img class="cmx-agent-photo" src="{a.get("photo","")}" '
                       f'alt="{esc(a.get("photo_alt",""))}" width="120" height="120" loading="lazy">')
        name_block = f"<h2>{title}</h2>"
        link_block = (f'<div class="cmx-agent-links">'
                      f'<a class="cmx-agent-link" href="{pl}">View full profile &rarr;</a></div>') if pl else ""
    watch_url = _watch_community_link(slug, label)
    watch_link = (
        f'<a href="{watch_url}">&#128065; Watch {label} for sale + sold listings</a>'
    ) if watch_url else ""

    fid = f"cmx-ask-{slug}"
    return f'''
<section class="cmx-section cmx-agent-cta" id="ask-agent">
  <style>
  .cmx-agent-cta .cmx-agent-grid{{display:grid;grid-template-columns:1fr 1fr;gap:42px;align-items:start}}
  .cmx-agent-card{{display:flex;gap:20px;align-items:flex-start}}
  .cmx-agent-photo{{width:120px;height:120px;border-radius:50%;object-fit:cover;object-position:50% 30%;border:3px solid #EA002A;flex:0 0 auto}}
  .cmx-agent-photos{{display:flex;flex:0 0 auto}}
  .cmx-agent-photo-duo{{width:110px;height:110px}}
  .cmx-agent-photos .cmx-agent-photo-duo+.cmx-agent-photo-duo{{margin-left:-26px}}
  .cmx-agent-card h2{{margin:.12em 0 .18em;font-size:1.5rem}}
  .cmx-agent-names{{color:#e6e6e6;font-weight:600;font-size:.98rem;margin-bottom:.5em}}
  .cmx-agent-card .cmx-eyebrow{{margin-bottom:.25em}}
  .cmx-agent-card p{{color:#bbb;line-height:1.6;font-size:.98rem;margin:0 0 15px}}
  .cmx-agent-contact{{display:flex;flex-direction:column;gap:8px}}
  .cmx-agent-contact a{{color:#fff;text-decoration:none;font-size:.96rem}}
  .cmx-agent-contact a:hover{{color:#EA002A}}
  .cmx-agent-links{{display:flex;flex-wrap:wrap;gap:14px;margin-top:4px}}
  .cmx-agent-link{{color:#EA002A;font-weight:700;text-decoration:none;font-size:.94rem}}
  @media(max-width:768px){{.cmx-agent-cta .cmx-agent-grid{{grid-template-columns:1fr;gap:30px}}.cmx-agent-card{{flex-direction:column;text-align:center;align-items:center}}.cmx-agent-contact,.cmx-agent-links{{align-items:center;justify-content:center}}}}
  </style>
  <div class="cmx-section-inner">
    <div class="cmx-agent-grid">
      <div class="cmx-agent-card">
        {photo_block}
        <div class="cmx-agent-meta">
          <div class="cmx-eyebrow">{head}</div>
          {name_block}
          <p>{tag}</p>
          <div class="cmx-agent-contact">
            <a href="tel:{pd}">&#128222; {esc(phone)}</a>
            <a href="mailto:{email}">&#9993; {esc(email)}</a>
            {watch_link}
          </div>
          {link_block}
        </div>
      </div>
      <div class="cmx-agent-form" id="{fid}" data-agent-name="{esc(form_name)}" data-agent-email="{esc(agent_email)}" data-team-email="{esc(email)}" data-agent-phone="{esc(phone)}" data-agent-slug="{esc(agent_slug)}" data-community="{label}" data-community-slug="{slug}"></div>
    </div>
  </div>
</section>'''


def generate_page(cfg, agg, css_text, agent_map=None, verbose=False, layout=None):
    slug = cfg["slug"]
    region = ms.get_region_data(agg, cfg["region_key"]) if agg else None
    if region is None:
        print(f"  ! {slug}: region {cfg['region_key']!r} not found — snapshot will be omitted",
              file=sys.stderr)
    # Layout v2 (D-1008-86, homes first, the agent's form last): layout=None follows the switch
    # (tools/community-layout.json); 'v2-preview' = the noindex copy at community-v2/<slug>.html.
    # Pages that set _out_slug (seller pages) never switch. v1 falls through, unchanged.
    _lay = layout or _cv2.layout_mode(cfg)
    if _lay in ("v2", "v2-preview") and not cfg.get("_out_slug"):
        _pieces = dict(
            head=build_head(cfg, css_text),
            jsonld=place_jsonld(cfg),
            hero=build_hero(_cv2.v2_cfg(cfg)),
            region=build_region_link(cfg),
            agent=build_agent_cta(cfg, agent_map),
            snapshot=build_snapshot(cfg, region),
            listings=build_listings(cfg),
            about=build_about(cfg),
            faq=build_faq(cfg),
            explore=build_explore(cfg),
            footer=ms.build_footer(),
            scripts=build_scripts(cfg),
        )
        return _cv2.compose(cfg, _pieces, preview=(_lay == "v2-preview"), site_root=SITE_ROOT)
    parts = [
        build_head(cfg, css_text),
        # ms.build_nav(cfg) removed 2026-09-08 -- see build_scripts() note
        # above; nav.js now builds the nav bars at runtime instead.
        '<main class="cmx">',
        place_jsonld(cfg),
        build_hero(cfg),
        build_region_link(cfg),
        build_agent_cta(cfg, agent_map),
        build_snapshot(cfg, region),
        build_report_band(cfg),
        build_listings(cfg),
        build_alerts(cfg),
        build_routes(cfg),
        build_overview(cfg),
        build_about(cfg),
        build_lookup(cfg),
        build_faq(cfg),
        build_explore(cfg),
        '</main>',
        ms.build_footer(),
        build_scripts(cfg),
    ]
    return "\n".join(p for p in parts if p), PAGES_DIR / f"{slug}.html"


def main():
    ap = argparse.ArgumentParser(description="Generate thin data-bound community pages.")
    ap.add_argument("--config")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--source", default=str(DEFAULT_AGG))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    if not a.config and not a.all:
        print("ERROR: --config <path.yml> or --all", file=sys.stderr); sys.exit(1)

    agg = ms.load_aggregates(a.source)
    css = load_css()
    agent_map = load_agent_map()
    cfgs = []
    if a.config:
        c = load_config(a.config)
        if c:
            cfgs.append(c)
    else:
        for f in sorted(CONFIG_DIR.glob("*.yml")):
            if f.name.startswith("_"):
                continue
            c = load_config(f)
            if c:
                cfgs.append(c)
    if not cfgs:
        print("ERROR: no configs found.", file=sys.stderr); sys.exit(1)

    n = 0
    for cfg in cfgs:
        html, out = generate_page(cfg, agg, css, agent_map=agent_map, verbose=a.verbose)
        if a.dry_run:
            print(f"  [dry-run] {out} ({len(html):,} bytes)")
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html)
            if a.verbose:
                print(f"  Wrote {out} ({len(html):,} bytes)")
        n += 1
        # Layout v2: while the switch is v1, every page also gets its noindex preview at
        # community-v2/<slug>.html; once v2 is live that folder is removed. A preview that
        # cannot be built warns loudly and never breaks the real page.
        # Lab West: no layout-v2 preview copy (a Gander/Avalon/Goose Bay A/B). A community YAML opts in with community_v2_preview: true.
        if not cfg.get("_out_slug") and cfg.get("community_v2_preview"):
            if _cv2.layout_mode(cfg) == "v1":
                try:
                    phtml, pout = generate_page(cfg, agg, css, agent_map=agent_map, verbose=a.verbose, layout="v2-preview")
                except Exception as e:
                    print(f"  ! {cfg['slug']}: community-v2 preview NOT built: {e}", file=sys.stderr)
                else:
                    if a.dry_run:
                        print(f"  [dry-run] {pout} ({len(phtml):,} bytes)")
                    else:
                        pout.parent.mkdir(parents=True, exist_ok=True)
                        pout.write_text(phtml)
            elif not a.dry_run:
                _cv2.clear_preview(SITE_ROOT, cfg["slug"])
    if a.all and not a.dry_run and _cv2.layout_mode() == "v2":
        _cv2.clear_preview(SITE_ROOT)
    print(f"\nDone: {n} community page(s).")


if __name__ == "__main__":
    main()