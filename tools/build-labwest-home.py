#!/usr/bin/env python3
"""Build the Lab West consumer homepage (sites, D-1012-34, component 7; picture: _ops/previews/2026-10-12/redesign_labwest_home_*.png).

Reads only what the gated rebuild already wrote: tools/idx-cache/listings-projected.json (homes for sale; leases are already
dropped by the projector) and listings/sold/data.json (sold rows: list price, sold date, facts, never a sold price), and
composes the page from the listing generator's own head, card, nav and footer builders, so it looks like the rest of the
listing pages. Every number on it is a count of those rows, with the feed date shown (always-on #35: nothing typed in).

  python3 tools/build-labwest-home.py --out home-preview.html          # preview: a noindex copy at /home-preview.html (state script adds noindex)
  python3 tools/build-labwest-home.py --out index.html             # on: replaces the recruiting homepage

Run only by the gated rebuild workflows, never while LABWEST_LISTINGS is off, so the committed index.html is untouched until the
flip. Fails loud on missing inputs rather than writing a page from a fallback (always-on #16).
"""
import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load_generator():
    spec = importlib.util.spec_from_file_location("lw_gen", HERE / "ddf-generate-pages.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lw_gen"] = mod
    spec.loader.exec_module(mod)
    return mod


def month_label(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso[:10]).strftime("%b %Y").upper()
    except ValueError:
        return ""


HOME_CSS = """
.lwh-hero { max-width:1200px; margin:0 auto; padding:56px 20px 28px; }
.lwh-eyebrow { color:#EA002A; font:700 .78rem/1 Raleway,sans-serif; letter-spacing:.12em; text-transform:uppercase; margin:0 0 14px; }
.lwh-hero h1 { font:900 clamp(2rem,5vw,3.1rem)/1.05 Raleway,sans-serif; margin:0 0 16px; }
.lwh-hero h1 em { color:#EA002A; font-style:normal; }
.lwh-sub { max-width:640px; color:#cfcfd4; font-size:1.05rem; line-height:1.5; margin:0 0 22px; }
.lwh-stats { display:flex; gap:40px; flex-wrap:wrap; margin:0 0 10px; }
.lwh-stat b { display:block; font:900 1.7rem/1 Raleway,sans-serif; }
.lwh-stat span { color:#bdbdc4; font-size:.9rem; }
.lwh-src { color:#9a9aa3; font-size:.85rem; margin:8px 0 0; }
.lwh-sec { max-width:1200px; margin:0 auto; padding:34px 20px 8px; }
.lwh-sec h2 { font:900 1.6rem/1.1 Raleway,sans-serif; margin:0 0 6px; }
.lwh-note { color:#9a9aa3; font-size:.9rem; margin:0 0 18px; }
.lwh-more { display:inline-block; margin:18px 0 6px; color:#fff; font-weight:700; border-bottom:2px solid #EA002A; text-decoration:none; }
.lwh-recruit { background:#161618; border-left:4px solid #EA002A; margin:42px 0 0; }
.lwh-recruit-in { max-width:1200px; margin:0 auto; padding:34px 20px; display:grid; grid-template-columns:1.1fr 1fr; gap:36px; align-items:center; }
.lwh-recruit h2 { font:900 2rem/1.1 Raleway,sans-serif; margin:6px 0 12px; }
.lwh-recruit p { color:#cfcfd4; line-height:1.55; margin:0 0 18px; }
.lwh-recruit ul { margin:0; padding:0; list-style:none; }
.lwh-recruit li { padding:0 0 12px 18px; position:relative; font-weight:600; line-height:1.4; }
.lwh-recruit li:before { content:""; position:absolute; left:0; top:.55em; width:7px; height:7px; background:#EA002A; }
.lwh-btns { display:flex; gap:14px; flex-wrap:wrap; align-items:center; }
.lwh-btn { display:inline-block; padding:12px 20px; border-radius:6px; font-weight:800; text-decoration:none; background:#EA002A; color:#fff; }
.lwh-btn.ghost { background:transparent; border:1px solid #444; }
.lwh-btn.line { background:none; padding:12px 2px; border-bottom:1px solid #888; border-radius:0; }
.lwh-sold-badge { position:absolute; top:12px; left:12px; background:#EA002A; color:#fff; font:800 .7rem/1 Raleway,sans-serif; letter-spacing:.06em; padding:6px 9px; border-radius:3px; z-index:2; }
.lwh-card { position:relative; }
.lwh-broker { max-width:1200px; margin:34px auto 0; padding:0 20px; }
.lwh-broker-in { background:#121214; border:1px solid #2a2a2e; border-radius:12px; padding:24px; display:grid; grid-template-columns:1fr auto; gap:20px; align-items:center; }
.lwh-broker h2 { font:900 1.35rem/1.1 Raleway,sans-serif; margin:0 0 8px; }
.lwh-broker p { color:#cfcfd4; margin:0 0 6px; line-height:1.5; }
.lwh-broker .lwh-btns { flex-direction:column; align-items:stretch; text-align:center; }
@media (max-width:800px){ .lwh-recruit-in,.lwh-broker-in { grid-template-columns:1fr; } .lwh-stats{gap:26px;} }
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="home-preview.html")
    ap.add_argument("--site-root", default=str(ROOT))
    a = ap.parse_args(argv)
    root = Path(a.site_root)
    proj = root / "tools" / "idx-cache" / "listings-projected.json"
    sold_path = root / "listings" / "sold" / "data.json"
    for p in (proj, sold_path):
        if not p.exists():
            print(f"[home] missing input {p}; refusing to write a homepage from a fallback", file=sys.stderr)
            return 1
    cache = json.loads(proj.read_text(encoding="utf-8"))
    listings = cache.get("listings") or []
    sold = json.loads(sold_path.read_text(encoding="utf-8")).get("rows") or []
    if not listings:
        print("[home] projected cache has no listings; refusing to write", file=sys.stderr)
        return 1

    gen = load_generator()
    he = gen.he
    as_of = datetime.fromisoformat(str(cache.get("generated_at")).replace("Z", "+00:00"))
    counts = gen._lc.listing_counts(listings, as_of)
    avail, pend = counts["available"], counts["pending"]
    today = as_of.date()
    last12 = [r for r in sold if (r.get("sold_date") or "") >= today.replace(year=today.year - 1).isoformat()]
    sold_sorted = sorted(sold, key=lambda r: (r.get("sold_date") or "", r.get("mls") or ""), reverse=True)

    active = [l for l in gen._sort_listings_for_display(listings) if not gen._lc.is_pending(l.get("status"))]
    newest = active[:3]
    out = Path(a.out)
    if not out.is_absolute():
        out = root / out
    depth = len(out.relative_to(root).parts) - 1
    prefix = "../" * depth   # "" for a root file; deeper outputs get "../" per level
    cards = "\n".join(gen.build_listing_card(l, prefix) for l in newest)

    sold_cards = []
    for r in sold_sorted[:6]:
        city = gen.city_display_name(r.get("city_slug") or "")
        href = gen._sold_property_href(root, r) or "/listings/sold/"   # root-absolute: fine at any depth
        photo = r.get("photo") or ""
        img = (f'<img src="{he(photo)}" alt="{he(r.get("street") or "")}, {he(city)}, NL" loading="lazy" '
               f'onerror="this.style.display=\'none\'">') if photo else ""
        price = gen.fmt_price(r.get("list_price"))
        kind = he((r.get("psub") or r.get("ptype") or "").strip())
        sold_cards.append(
            f'<article class="lst-card lwh-card"><span class="lwh-sold-badge">SOLD {he(month_label(r.get("sold_date") or ""))}</span>'
            f'<a class="lst-card-link" href="{he(href)}"><div class="lst-card-photo">{img}</div>'
            f'<div class="lst-card-body"><p class="lst-card-price">Listed at {he(price)}</p>'
            f'<p class="lst-card-addr">{he(r.get("street") or "")}</p><p class="lst-card-city">{he(city)}, NL</p>'
            f'<p class="lst-card-meta">{kind} &middot; see what it sold for when you register</p></div></a></article>')
    sold_html = "\n".join(sold_cards)

    feed_label = as_of.strftime("%b %-d, %Y")
    title = "Labrador West Homes for Sale — Labrador City & Wabush | Royal LePage Turner Realty"
    desc = (f"{avail} homes for sale in Labrador City and Wabush from the NLAR MLS® System, and recent sales. "
            "Questions go to Mike Turner, Broker of Record, Royal LePage Turner Realty.")
    canonical = f"{gen.SITE_ORIGIN}/"
    og = f"{gen.SITE_ORIGIN}/images/og/index-og.jpg"
    jsonld = {
        "@context": "https://schema.org", "@type": "RealEstateAgent", "name": "Royal LePage Turner Realty",
        "url": canonical, "telephone": "+1-709-256-7999", "email": "miketurner@royallepage.ca",
        "employee": {"@type": "Person", "name": "Mike Turner", "jobTitle": "Broker of Record"},
        "areaServed": [{"@type": "Place", "name": "Labrador City, Newfoundland and Labrador"}, {"@type": "Place", "name": "Wabush, Newfoundland and Labrador"}],
    }
    pend_txt = f" ({pend} more under contract)" if pend else ""
    page = f"""<!DOCTYPE html>
<html lang="en">
{gen.head_block_simple(title, desc, canonical, og, prefix)}
<style>
{HOME_CSS}
</style>
<body>
{gen.nav_html(prefix)}

<div class="lst-shell">

<header class="lwh-hero">
  <p class="lwh-eyebrow">Labrador City &middot; Wabush &middot; Labrador West</p>
  <h1>Labrador West <em>homes for sale</em></h1>
  <p class="lwh-sub">Every home for sale in Labrador City and Wabush from the MLS&reg; System. Questions about buying or selling here go to Mike Turner, Broker of Record.</p>
  <div class="lwh-stats">
    <div class="lwh-stat"><b>{avail}</b><span>homes for sale{he(pend_txt)}</span></div>
    <div class="lwh-stat"><b>{len(last12)}</b><span>sold in the last 12 months</span></div>
  </div>
  <p class="lwh-src">Source: NLAR MLS&reg; System, as of {he(feed_label)}.</p>
</header>

<section class="lwh-sec" aria-labelledby="lwh-new">
  <h2 id="lwh-new">Newest homes for sale</h2>
  <p class="lwh-note">From the NLAR MLS&reg; System.</p>
  <div class="lst-card-grid">
{cards}
  </div>
  <a class="lwh-more" href="{prefix}listings/">See all {avail} Labrador West listings &rarr;</a>
</section>

<section class="lwh-recruit" aria-labelledby="lwh-recruit-h">
  <div class="lwh-recruit-in">
    <div>
      <p class="lwh-eyebrow">Now recruiting in Labrador West</p>
      <h2 id="lwh-recruit-h">This could be your territory.</h2>
      <p>No Turner office or agent is in Labrador West yet. Be the first Royal LePage agent in Labrador City and Wabush, with the same tools our agents use every day.</p>
      <div class="lwh-btns"><a class="lwh-btn" href="{prefix}why-join.html">See what agents get</a><a class="lwh-btn line" href="{prefix}contact.html">Talk to Mike Turner</a></div>
    </div>
    <ul>
      <li>Automatic social posts and a just-sold letter for every listing and sale</li>
      <li>Follow Up Boss: leads assigned to you, with a first-call task</li>
      <li>Listing pages that update every hour, with Listing Text Alerts and Listing Email Alerts</li>
    </ul>
  </div>
</section>

<section class="lwh-sec" aria-labelledby="lwh-sold">
  <h2 id="lwh-sold">Recently sold in Labrador West</h2>
  <p class="lwh-note">Asking price and the month it sold. The sold price unlocks when you register.</p>
  <div class="lst-card-grid">
{sold_html}
  </div>
  <p class="lwh-note" style="margin-top:14px">Sold prices are shown to registered users (free). Everything else is public.</p>
</section>

<section class="lwh-broker" aria-label="Contact Mike Turner">
  <div class="lwh-broker-in">
    <div>
      <h2>Mike Turner, Broker of Record</h2>
      <p>Royal LePage Turner Realty &middot; 709-256-7999 &middot; miketurner@royallepage.ca</p>
      <p>Buying or selling in Labrador City or Wabush? Mike handles every Labrador West inquiry until an agent joins.</p>
    </div>
    <div class="lwh-btns"><a class="lwh-btn" href="mailto:miketurner@royallepage.ca?subject=Labrador%20West">Ask Mike about Labrador West</a><a class="lwh-btn ghost" href="tel:7092567999">Call 709-256-7999</a></div>
  </div>
</section>

<div class="lst-ddr">
  <p>{he(gen.DDR_DISCLAIMER)}</p>
  <p>{he(gen.TRADEMARK_NOTICE)}</p>
</div>

</div>

{gen.footer_html(prefix)}

<script type="application/ld+json">{gen.ja(jsonld)}</script>

<script src="{prefix}js/footer.js"></script>
<script src="{prefix}js/regions-data.js" defer></script>
<script src="{prefix}js/nav-config.js" defer></script>
<script>window.TURNER_SITE='{gen._SITE_CFG["site_key"]}';window.TURNER_API_ORIGIN='{gen._SITE_CFG["api_url"]}';</script>
<script src="{prefix}js/nav.js" defer></script>
<script src="{prefix}js/turner-network.js" defer></script>
{gen._chat_script(prefix)}
</body>
</html>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"[home] wrote {out.relative_to(root) if out.is_relative_to(root) else out}: {avail} for sale (+{pend} pending), {len(last12)} sold in 12 months, as of {feed_label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
