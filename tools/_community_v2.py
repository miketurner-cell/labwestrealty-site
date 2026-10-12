#!/usr/bin/env python3
"""
_community_v2.py -- the second community-page layout (Mike D-1008-86, "homes first,
the agent's form last"; redesign session, 2026-10-09).

Byte-identical on Gander, Avalon and Goose Bay (D-1008-25). The three
build-community-pages.py generators drift per site, so this module owns no copy of
its own: each generator hands it the sections its own builders already render
(`pieces`), and it only re-orders, merges and tags them.

The 7 sections, in this order (the drawing
_ops/previews/2026-10-08/redesign_layout_2-community-order_*.png):
  1 hero            2 homes for sale      3 the town's sales (public fields; the sold
  price stays behind the VOW gate)        4 the market in plain words
  5 "Living in <town>" (guide + FAQ)      6 the agent's card + the one short form, last
  7 nearby communities
Dropped from v2: the duplicate CTAs, the PDF-report form, the alerts form, the routes,
the about columns, the property lookup, the photo bands. No new copy, numbers or claims:
the only strings written here are the drawing's own CTA labels and one sentence
paraphrasing the existing sold-band copy. No recruiting link or word (D-1009-19): the
hero intent row loses its "Join the team" button in v2.

The switch (default v1 = today, byte-identical):
  tools/community-layout.json  {"communityLayout": "v1" | "v2"}   (gate COMMUNITY_LAYOUT)
  a per-config `communityLayout:` key wins; env COMMUNITY_LAYOUT overrides both (local use).
  v1 -> pages/<slug>.html unchanged, AND each v2 page is also written to
        community-v2/<slug>.html (noindex,nofollow, self-canonical, not in any sitemap).
  v2 -> the v2 markup is written to pages/<slug>.html and community-v2/ is removed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

LAYOUT_FILE = Path(__file__).resolve().parent / "community-layout.json"
PREVIEW_DIR = "community-v2"
SECTION_ORDER = ("hero", "homes", "sold", "market", "living", "agent", "nearby")


def layout_mode(cfg=None):
    """'v1' (default) or 'v2'. Env > per-config key > tools/community-layout.json."""
    for cand in (os.environ.get("COMMUNITY_LAYOUT"),
                 (cfg or {}).get("communityLayout")):
        if cand in ("v1", "v2"):
            return cand
    try:
        v = json.loads(LAYOUT_FILE.read_text()).get("communityLayout")
        if v in ("v1", "v2"):
            return v
    except Exception:
        pass
    return "v1"


def v2_cfg(cfg):
    """cfg copy for the v2 hero: no recruiting intent button (D-1009-19)."""
    c = dict(cfg)
    c["hubs"] = [h for h in (cfg.get("hubs") or []) if h != "agent"]
    return c


def clear_preview(site_root, slug=None):
    """v2 live: remove community-v2/ (one page when slug given, else the folder)."""
    d = Path(site_root) / PREVIEW_DIR
    if slug:
        (d / f"{slug}.html").unlink(missing_ok=True)
        try:
            d.rmdir()
        except OSError:
            pass
    elif d.is_dir():
        shutil.rmtree(d)


# ── helpers ────────────────────────────────────────────────────────────────
def _esc(s):
    import html
    return html.escape(str(s)) if s is not None else ""


def _tag(sec, name):
    return re.sub(r"<section\b", f'<section data-cmx-section="{name}"', sec, count=1)


def _inner(sec):
    """Content of a section's .cmx-section-inner div (either quote style)."""
    m = re.search(r"<div class=['\"]cmx-section-inner['\"]>", sec)
    if not m:
        return ""
    end = sec.rfind("</section>")
    j = sec.rfind("</div>", m.end(), end)
    return sec[m.end():j] if j > 0 else ""


def _cta_html(links):
    links = [(h, t) for h, t in links if h]
    if not links:
        return ""
    return ('<p class="cmx-v2-cta">'
            + "".join(f'<a class="cmx-link" href="{_esc(h)}">{t} &rarr;</a>' for h, t in links)
            + "</p>")


def _add_cta(sec, cta):
    if not cta:
        return sec
    idx = sec.rfind("</section>")
    j = sec.rfind("</div>", 0, idx)
    return sec[:j] + cta + "\n  " + sec[j:]


_V2_CSS = """<style id="cmx-v2-css">
/* community layout v2: 56 px between sections on desktop, 40 on a phone (drawn rule) */
.cmx-v2 .cmx-section-inner{padding:28px 24px}
@media(max-width:560px){.cmx-v2 .cmx-section-inner{padding:20px 18px}}
.cmx-v2 .cmx-v2-cta{margin:22px 0 0;display:flex;flex-wrap:wrap;gap:10px 24px;font-weight:700}
.cmx-v2 [data-cmx-section="living"] h3{margin:1.4em 0 .4em}
.cmx-v2 [data-cmx-section="living"] .cmx-faq{margin-top:12px}
</style>"""


_RECRUIT_LINK = re.compile(
    r"<li>\s*<a\b[^>]*(?:join-our-team|recruit|agent-hub)[^>]*>[^<]*</a>\s*</li>\s*"
    r"|<a\b[^>]*(?:join-our-team|recruit|agent-hub)[^>]*>[^<]*</a>", re.I)


def _no_recruiting(chunk):
    """The shared nav/footer chrome carries a 'Join Our Team' link; v2 has none (D-1009-19)."""
    return _RECRUIT_LINK.sub("", chunk or "")


def _sold_href(*texts):
    found = []
    for t in texts:
        for m in re.finditer(r'href="(/listings/sold/[a-z0-9-]+/)"', t or ""):
            if m.group(1) not in found:
                found.append(m.group(1))
    return found[0] if len(found) == 1 else "/listings/sold/"


# ── the 7 sections ─────────────────────────────────────────────────────────
def _homes(cfg, pieces):
    label = _esc(cfg["label"])
    view = cfg.get("listings_view_all", "/listings/")
    cta = _cta_html([(view, f"Find a home in {label}")])
    sec = pieces.get("listings") or ""
    if not sec:  # no feed fragment for this town: the heading + the link, never a blank
        sec = (f'<section class="cmx-section"><div class="cmx-section-inner">'
               f'<h2>Homes for Sale in {label}</h2></div></section>')
    sec = re.sub(r'<a class="cmx-link" href="[^"]*">View all [^<]*&rarr;</a>', "", sec)
    return _add_cta(_tag(sec, "homes"), cta)


def _sold(cfg, pieces):
    label = _esc(cfg["label"])
    href = _sold_href(pieces.get("sold"), pieces.get("snapshot"))
    cta = _cta_html([(href, "See what it sold for")])
    sec = pieces.get("sold") or ""
    if sec:  # Avalon: the existing recently-sold band (asking price + sold date; price stays gated)
        sec = re.sub(r'<a class="cmx-link" href="[^"]*">See all sold homes &rarr;</a>', "", sec)
    else:
        sec = (f'<section class="cmx-section cmx-section-alt"><div class="cmx-section-inner">'
               f'<h2>What sold in {label}</h2>'
               f'<p class="cmx-lead">Asking price and sold date shown; the sold price unlocks '
               f'through secure VOW registration.</p></div></section>')
    return _add_cta(_tag(sec, "sold"), cta)


def _market(cfg, pieces):
    label = _esc(cfg["label"])
    ms_url = cfg.get("market_stats_url")
    cta = _cta_html([(ms_url, f"See the {label} market")])
    sec = pieces.get("snapshot") or ""
    if not sec:  # region has no aggregate row: heading + the market page link only
        sec = (f'<section class="cmx-section cmx-section-alt"><div class="cmx-section-inner">'
               f'<h2>The {label} market</h2></div></section>')
    return _add_cta(_tag(sec, "market"), cta)


def _living(cfg, pieces):
    label = _esc(cfg["label"])
    chunks = []
    for key in ("about", "faq"):
        raw = pieces.get(key) or ""
        for sec in re.findall(r"<section\b.*?</section>", raw, flags=re.S):
            body = _inner(sec).replace("<h2>", "<h3>").replace("</h2>", "</h3>")
            if body.strip():
                chunks.append(body)
    if not chunks:
        raise ValueError(f"community v2: {cfg['slug']} has neither guide text nor FAQ for 'Living in'")
    hubs = cfg.get("hubs") or []
    cta = _cta_html([(f"relocate-hub.html?community={cfg['slug']}", "Plan my move")]
                    if "relocate" in hubs else [])
    return (f'<section data-cmx-section="living" class="cmx-section" id="living">'
            f'<div class="cmx-section-inner"><h2>Living in {label}</h2>'
            + "".join(chunks) + cta + '</div></section>')


def compose(cfg, pieces, preview=False, site_root=None):
    """pieces: head, nav, jsonld, hero, region, agent, snapshot, listings, sold, about,
    faq, explore, footer, scripts (strings from the generator's own builders; '' ok)."""
    slug = cfg["slug"]
    for need in ("agent", "explore", "hero"):
        if not pieces.get(need):
            raise ValueError(f"community v2: {slug} has no '{need}' block (the page cannot be built)")
    head = pieces["head"]
    if preview:
        head = head.replace(f"/pages/{slug}.html", f"/{PREVIEW_DIR}/{slug}.html")
        head = head.replace('<meta name="description"',
                            '<meta name="robots" content="noindex,nofollow">\n  <meta name="description"', 1)
    body = "\n".join(p for p in [
        '<main class="cmx cmx-v2">',
        _V2_CSS,
        pieces.get("jsonld", ""),
        _tag(pieces["hero"], "hero"),
        pieces.get("region", ""),
        _homes(cfg, pieces),
        _sold(cfg, pieces),
        _market(cfg, pieces),
        _living(cfg, pieces),
        _tag(pieces["agent"], "agent"),
        _tag(pieces["explore"], "nearby"),
        '</main>',
    ] if p)
    rest = "\n".join(p for p in [_no_recruiting(pieces.get("nav", "")), body,
                                 _no_recruiting(pieces.get("footer", "")), pieces.get("scripts", "")] if p)
    html = head + "\n" + rest
    if preview:  # bare pages/ links (footer, nearby, hubs) keep working from community-v2/
        html = re.sub(r'href="([a-z0-9][a-z0-9_-]*\.html)', r'href="/pages/\1', html)
    root = Path(site_root) if site_root else Path(__file__).resolve().parent.parent
    out = root / (PREVIEW_DIR if preview else "pages") / f"{slug}.html"
    return html, out
