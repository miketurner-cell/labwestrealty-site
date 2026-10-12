#!/usr/bin/env python3
"""
Turner Realty — Listing Page Generator
=======================================
Reads tools/idx-cache/listings-projected.json (NLAR IDX/VOW, produced by
idx-ingest.py + idx-project-to-ddf-shape.py; CREA DDF retired 2026-10-01) and emits:

    /listings/<city>/<address-slug>-<mls>.html        per-listing detail pages
    /listings/<city>/index.html                       per-city landing pages
    /listings/index.html                              all-listings index
    /sitemap-listings.xml                             search-engine discovery file

Design system: matches labwestrealty.com (#0a0a0a / #EA002A / Raleway+Roboto).
Ported from goosebayrealestate-site/tools/ddf-generate-pages.py (closest twin) for Lab West (sites,
D-1012-34, component 4). Per-site deltas vs. Goose Bay, kept to config and copy only:
  - SITE_ORIGIN (from _fleet_config.json), contact = Mike Turner, Broker of Record, Royal LePage
    Turner Realty, miketurner@royallepage.ca, 709-256-7999. NO Lab West street address anywhere
    (the office is not in Labrador West; tools/tests/labwest-no-address-test.py enforces it)
  - CITY_DISPLAY / rollup copy / footer: Labrador City and Wabush
  - lease rows are dropped by the projector (TransactionType LEASE) before this file sees them
Page scope: `.lst-` (listing).
Pre-existing site files are NEVER modified — only new files in /listings/.

Usage
-----
    python3 ddf-generate-pages.py                  # full regen (default)
    python3 ddf-generate-pages.py --limit 5        # generate first N for testing
    python3 ddf-generate-pages.py --listings-only  # skip city + index pages
    python3 ddf-generate-pages.py --site-root PATH # default: ../  (parent of tools/)

Compliance
----------
* CREA DDR disclaimer + "Powered by REALTOR.ca" badge on every detail page
* JSON-LD RealEstateListing structured data for SEO
* Listing brokerage attribution mandatory (per CREA terms); listing-agent NAME
  intentionally NOT displayed (per Turner business decision 2026-04 — all inquiries
  funnel to a Turner agent via BoldTrail for non-Turner listings)
* CREA Analytics LogEvents beacon fires on page load (per-listing telemetry)
"""

from __future__ import annotations

# Inc 1 (2026-06-22): 20 shared leaf-helpers, were inline across all 3 generators.
# Imported before any module-level use (e.g. ROLLUPS); self-contained sys.path setup.
import os as _fg_os, sys as _fg_sys
_fg_sys.path.insert(0, _fg_os.path.dirname(_fg_os.path.abspath(__file__)))
import listing_script as _listing_script  # Ship 4 port, 2026-09-11 -- narration + HMAC signing
import _fleet_listing_counts as _lc  # the ONE listing-count definition (sites 2026-10-09)
import _listing_terms as _lr  # lease rent labels + availability status, shared fleet file (sites, D-1009-77)
from _fleet_genutils import (
    CREA_ANALYTICS_URL,
    NEW_LISTING_DAYS,
    TOUR_JUNK_HOSTS,
    TURNER_BROKERAGE_FRAGMENT,
    _HOST_RE,
    _IGUIDE_RE,
    _MP_RE,
    _YT_RE,
    _current_year,
    _days_on_market,
    _list_date_label,
    _get_google_maps_key,
    _git_sha,
    _hash_listings_dir,
    _is_commercial,
    _is_first_time_buyer,
    _is_new,
    _maa_muni_code,
    _render_tour_embed,
    _save_swept_cache,
    _slugify_city,
    _split_tour_urls,
    _swept_cache_path,
    _viewpoint_clean,
    _youtube_tour_video_jsonld,
    build_analytics_beacon,
    build_breadcrumb_jsonld,
    build_facts_strip,
    fmt_bath,
    fmt_int,
    fmt_lot,
    fmt_sqft,
    he,
    is_turner,
    ja,
    ja_ascii,
)
from _fleet_config import load_site_config
from nl_dates import nl_date, nl_month_year  # every rendered date = the NL calendar day (2026-09-28)
# Shared feed field list (sites, D-1009-29, 2026-10-09): idx-ingest now keeps
# Gander's 122 fields. Fields new to this site are STORED but held off the
# sold pages until the display design call; PendingDate is not held.
from idx_fields import hold_sold_display_fields
del _fg_os, _fg_sys

# Goose Bay kept none of the held fields before the parity change, so
# all of them stay held.
SOLD_DISPLAY_HOLD_EXEMPT = frozenset()

import argparse
import hashlib
import html
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from datetime import date as _date
from collections import Counter as _Counter
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════════

_SITE_CFG = load_site_config()

def _chat_script(prefix: str) -> str:
    """The chat widget tag, only when this repo carries the chat function (component 9). Otherwise nothing is
    emitted: no widget that posts to a function that does not exist."""
    if not (Path(__file__).resolve().parent.parent / "netlify" / "functions" / "chat.ts").exists():
        return ""
    return f'<script src="{prefix}js/chat-widget.js?v=20260613-mobilebar" async></script>'


def _nav_auth_script(prefix: str) -> str:
    """The Sign in / My Account nav entry, only when this repo has an account page to link to (it has none yet; the
    sold-price sign-in arrives with the sold component)."""
    if not _page_exists("account.html"):
        return ""
    return f'<script src="{prefix}js/nav-auth.js?v=20260818-portal" defer></script>'


def _page_exists(name: str) -> bool:
    """True when pages/<name> exists in this repo. Lab West has no marketing pages/ yet (they arrive with the
    homepage component), so every link to one is emitted only when the page is really there (Convention #17:
    degrade the copy with the data, never link a dead page)."""
    return (Path(__file__).resolve().parent.parent / "pages" / name).exists()


_LW_SCOPE_FN = None


def _lw_in_scope(row) -> bool:
    """Lab West scope test = in_scope() from idx-project-to-ddf-shape.py (single source of the rules)."""
    global _LW_SCOPE_FN
    if _LW_SCOPE_FN is None:
        import importlib.util as _ilu
        _sp = _ilu.spec_from_file_location("_lw_proj", Path(__file__).resolve().parent / "idx-project-to-ddf-shape.py")
        _m = _ilu.module_from_spec(_sp)
        _sp.loader.exec_module(_m)
        _LW_SCOPE_FN = _m.in_scope
    return bool(_LW_SCOPE_FN(row))
SITE_ORIGIN = _SITE_CFG["site_origin"]

# The one reply promise (Mike, D-1008-30, 2026-10-08): read from the fleet-canonical
# js/reply-promise.js so no generated page carries its own reply time. Fails loud if the
# file or the string is missing (a page must never fall back to an invented promise).
def _load_reply_promise() -> str:
    _src = (Path(__file__).resolve().parent.parent / "js" / "reply-promise.js").read_text(encoding="utf-8")
    _m = re.search(r'TURNER_REPLY_PROMISE\s*=\s*"([^"]+)"', _src)
    if not _m:
        raise SystemExit("ddf-generate-pages: js/reply-promise.js has no TURNER_REPLY_PROMISE string")
    return _m.group(1)

REPLY_PROMISE = _load_reply_promise()
# ── Cloudflare R2 photo hosting (Convention #15 from Gander) ──
# When R2_BASE_URL is set, photo URLs emit absolute R2 URLs against
# {R2_BASE_URL}/{R2_SITE_SLUG}/listings/<MLS>/<NNN>.jpg instead of
# root-relative /images/listings/ paths. Fail-safe: missing env var
# falls through to disk-mode emission.
R2_BASE_URL = os.environ.get("R2_BASE_URL", "").strip().rstrip("/")
R2_SITE_SLUG = _SITE_CFG["r2_site_slug"]
GTAG_ID = _SITE_CFG["gtag_id"]
# gtag.js is loaded AND configured by the site's Google tag (GT-...), never the G- ID:
# gtag.js registers the container under the loader ID, so a
# config call naming the G- ID fetches gtag/js?id=G-...&cx=c, which Google 404s, and
# no hit is sent (verified live 2026-10-11, D-1011-20). Google 404s the G- ID as a
# gtag.js loader (Mike, B-1007-21, 2026-10-07).
GTAG_LOADER_ID = _SITE_CFG.get("gtag_loader_id") or GTAG_ID

# Follow Up Boss visitor-tracking pixel (account: royallepage545). Fleet-wide --
# same literal script on all 5 sites, one FUB account tracking the whole fleet.
# fleet/canonical/tools/inject-fub-pixel.py puts this on every already-generated
# page; this constant is what keeps it on every page this generator produces
# going forward. Sentinel-gated (`fub-pixel:v1`) so the two stay idempotent
# with each other -- never edit the tracker ID here, paste a fresh copy from
# FUB's Admin > Website Tracking > Pixel page instead.
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

# "Listen to this listing" audio tours (Ship 4 port, 2026-09-11 -- fleet
# rollout of Gander's 2026-09-10 ship, ~/.claude/plans/now-that-we-have-
# polymorphic-wolf.md). Off by default (Conv #74): with the gate off, or
# the HMAC secret unset, the generator emits NO audio-player markup at
# all -- not a broken/hidden button, no markup whatsoever, so an
# unconfigured build changes nothing. Reads env fresh at import time same
# as every other gate in this file.
LISTING_AUDIO_MODE = os.environ.get("LISTING_AUDIO", "off").strip().lower()
# SITE_PERSONAL_REVIEW (site track gate, Mike 2026-09-30 item 6; same semantics on all three sites):
#   off -> nothing emitted;  preview (default) -> data-review="preview" on the card, the third tab is built by
#   js/boldtrail-forms.js ONLY when the URL has ?preview=review;  on -> every visitor.
PERSONAL_REVIEW_MODE = os.environ.get("SITE_PERSONAL_REVIEW", "preview").strip().lower()
if PERSONAL_REVIEW_MODE not in ("off", "preview", "on"):
    PERSONAL_REVIEW_MODE = "preview"
PERSONAL_REVIEW_TEAM_LABEL = 'Ask Mike Turner'
LISTING_AUDIO_SCOPE = os.environ.get("LISTING_AUDIO_SCOPE", "own").strip().lower()
LISTING_AUDIO_HMAC = os.environ.get("LISTING_AUDIO_HMAC", "").strip()

# Convention #141 diagnostic — distinguishes "env var unset" (intentional
# disk-mode) from "set-but-empty-after-cleanup" (config bug; today's precedent
# was Goosebay R2_BASE_URL set 2026-05-22 but value evaluated to empty). When
# raw env value is truthy but cleaned R2_BASE_URL is falsy, emit a loud warning
# to stderr so CI step logs surface the gap instead of silently emitting
# disk-mode URLs.
_R2_BASE_URL_RAW = os.environ.get("R2_BASE_URL", "")
if _R2_BASE_URL_RAW and not R2_BASE_URL:
    import sys as _sys_r2check
    print(
        "[R2-CHECK] WARNING (labwest): R2_BASE_URL env var IS SET to "
        + repr(_R2_BASE_URL_RAW)
        + " but resolves to empty after .strip().rstrip('/'). "
        + "Generator running in disk-mode — photo URLs will be relative "
        + "/images/listings/... paths instead of absolute R2 URLs. If R2 mode "
        + "was intended, re-set the GH Actions secret via "
        + "gh secret set R2_BASE_URL --body \"https://photos...\" per "
        + "Convention #123 (explicit --body form, NEVER stdin pipe).",
        file=_sys_r2check.stderr,
    )


# CREA Analytics beacon (per CREA member docs — POST a tiny JSON event per page view)

# REALTOR.ca canonical URL pattern — links the mandatory badge to the source listing
REALTOR_CA_LISTING_URL_TEMPLATE = "https://www.realtor.ca/real-estate/{listing_key}/"

# DDR disclaimer (DRAFT — Mike to sign off; sourced from CREA DDF Help Guide)
DDR_DISCLAIMER = (
    "The information contained on this page is based in whole or in part on "
    "information that is provided by members of The Canadian Real Estate Association, "
    "who are responsible for its accuracy. CREA reproduces and distributes this "
    "information as a service for its members and assumes no responsibility for its "
    "accuracy. Listings are updated daily. Royal LePage Turner Realty (2014) Inc. is "
    "a member of The Canadian Real Estate Association."
)

TRADEMARK_NOTICE = (
    "REALTOR®, REALTORS®, and the REALTOR® logo are certification marks owned or "
    "controlled by The Canadian Real Estate Association (CREA) and identify real "
    "estate professionals who are members of CREA. The trademarks MLS®, Multiple "
    "Listing Service®, and the associated logos identify professional services "
    "rendered by REALTOR® members of CREA to effect the purchase, sale and lease "
    "of real estate as part of a cooperative selling system."
)

# Pretty city names (slug → display) — fallback derives from slug.
# Scoped to Labrador City + Wabush (postal A2V / A0R, see idx-project-to-ddf-shape.py).
CITY_DISPLAY = {
    "labrador-city":          "Labrador City",
    "wabush":                 "Wabush",
    # Generic fallback (a row with a town name the projector could not map)
    "labrador":               "Labrador",
}


# ═══════════════════════════════════════════════════════════════════
#  ROLLUP CONFIG  (task #69 — filtered collection pages)
# ═══════════════════════════════════════════════════════════════════
#
# Rollups are filtered collection pages that sit alongside city landings:
#
#     /listings/new-construction/index.html
#     /listings/first-time-buyer/index.html
#     /listings/commercial/index.html
#
# Each rollup is defined by a filter function over the listing dict. The
# generator runs the filter over the full cache, emits an index page with
# the matching listings, and registers the slug so the stale-sweep step
# doesn't 301 it away.
#
# These are the three surfaces that today use RealtyVis iframe widgets
# (pages/new-construction.html, pages/first-time-buyers.html,
# pages/commercial.html — same pattern carried over from Gander). Once this
# generator's output ships, those marketing pages can link into
# /listings/<rollup>/ and retire the iframes on labwestrealty.com.
#
# Key design choices:
#   * Filters are pure functions — easy to test, reorder, add more.
#   * Custom sort_key per rollup (e.g. first-time-buyer ascends by price,
#     commercial descends by price, new-construction descends by year).
#   * Empty rollups still emit an index page with an empty-state message,
#     so the sweep never tries to 301 them away and the URL stays stable
#     in sitemaps/ads/social posts.
#
# Collision guard: rollup slugs MUST NOT overlap with any city_slug. The
# generator logs a warning and skips the conflicting rollup if they do.

# Words in public_remarks that signal new-build inventory even when the
# structured year_built field is missing or stale.
_NEW_BUILD_RE = re.compile(
    r'\b(new build|brand new|newly built|new construction|just built|never lived(?: in)?)\b',
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════════
#  STALE-ACTIVE GATE  (task #117 — consumer-trust freshness filter)
# ═══════════════════════════════════════════════════════════════════
#
# DDF marks listings as "active" based on the source board's declared status.
# Some boards leave records active long after they should have rolled off —
# the Avalon Phase 1 audit (2026-04-21) surfaced two listings with
# modification_timestamp > 180 days still serving as active. A listing that
# hasn't been touched in six months is almost certainly sold, withdrawn, or
# abandoned; showing it as "for sale" is a consumer-trust failure.
#
# This gate is now the only stale-active guard: the `ddf-audit.py` freshness
# check that used to halt CI before regen read the DDF cache and was removed
# with the DDF retirement (2026-10-01).
#
# Filtered listings are dropped from every downstream surface. Their on-disk
# HTML is reaped by the existing stale-page sweep. Counts land in the deploy
# manifest under `stale_active_gate`.
#
# Why 180 days: matches the `freshness` threshold in `ddf-audit.py`.

STALE_ACTIVE_THRESHOLD_DAYS = 180

# DDF emits ISO8601 timestamps with arbitrary fractional-second precision
# ('.02Z', '.9Z', '.87Z', '.123456Z' all appear). Python 3.10's
# datetime.fromisoformat only accepts exactly 3 or 6 fractional digits.
# Normalize to microseconds (6 digits) before parsing. Canonical copy also
# lives in `ddf-audit.py:parse_ts`.
_STALE_GATE_FRAC_RE = re.compile(r"\.(\d+)")


def _parse_ddf_ts(ts: str | None) -> datetime | None:
    """Parse a DDF/IDX ISO8601 timestamp safely. Returns None on any failure.

    Goosebay IDX cutover 2026-05-21 (Convention #15 from Avalon `1cb0e7686` /
    Gander `1cb0e7686` hotfix): IDX returns NAIVE ISO timestamps
    ("2025-07-21T15:01:56.717" — no Z, no +00:00 offset) while DDF returned
    tz-aware ("...Z" suffix). When the stale-active gate compares parser
    output to `datetime.now(timezone.utc)`, a naive return crashes with
    TypeError. Defense: if fromisoformat returns a naive datetime, attach
    UTC (NLAR convention is UTC for all timestamps).
    """
    if not ts or not isinstance(ts, str):
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        def _pad(m: re.Match) -> str:
            digits = m.group(1)
            return "." + (digits + "000000")[:6]
        ts = _STALE_GATE_FRAC_RE.sub(_pad, ts, count=1)
        result = datetime.fromisoformat(ts)
        # IDX returns naive ISO — attach UTC for safe comparison against
        # tz-aware now(). NLAR convention is UTC for all timestamps.
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────────
# Lease-listing detection (Convention #21 layer-1 — ingest-time correction)
# ─────────────────────────────────────────────────────────────────────
# DDF + IDX feeds both flow lease-rate-per-sqft and monthly-rent values
# through the same `list_price` field used for sale prices. Generator
# would emit "$50" or "$17" on listing cards for what's actually a
# commercial lease at $50/sqft or office at $17/sqft. Consumer sees a
# nonsensical price (caught by Mike 2026-05-22 on MLS 1297866 Goosebay
# 218 Hamilton River Road); fleet-audit surfaced ~70 affected fleet-wide.
# Convention #15 byte-symmetric port from Gander canonical.
_LEASE_REMARKS_RE = re.compile(
    r"\b(?:lease|leasing|for rent|rental|net rent|nnn|triple net|"
    r"per sq\.? ?ft|/sq\.? ?ft|per square|build-to-suit|build to suit|"
    r"tenant fitup|tenant fit-up|tenant fit up|monthly rent)\b",
    re.IGNORECASE,
)
_LEASE_PRICE_FLOOR = 5000  # NL sale prices never legitimately below $5K


def _detect_lease_listing(listing: dict) -> bool:
    """True for a lease row. Since 2026-10-09 (D-1009-77) the rules live in
    tools/_listing_terms.py (shared, byte-identical on the three listing sites):
    the feed's TransactionType first, then the counted fallbacks."""
    return _lr.detect_lease(listing)[0]


_LEASE_COUNTS = {}


def _normalize_lease_listings(listings: list) -> int:
    """Mark lease rows in place (is_lease, lease_rate, rent, rent_basis,
    list_price=None) via tools/_listing_terms.py. Returns the lease count; the
    per-source counts for the build log are kept in _LEASE_COUNTS."""
    counts = _lr.apply(listings)
    _LEASE_COUNTS.clear()
    _LEASE_COUNTS.update(counts)
    return counts["lease"]


def _filter_stale_active(
    listings: list[dict],
    threshold_days: int = STALE_ACTIVE_THRESHOLD_DAYS,
) -> tuple[list[dict], list[dict]]:
    """Partition listings into (fresh, stale) by modification_timestamp age.

    Fail-open: missing/unparseable mod_ts → fresh. The generator's job is
    to surface inventory, not invent absence; real data defects are the
    audit's job.
    """
    now = datetime.now(timezone.utc)
    fresh: list[dict] = []
    stale: list[dict] = []
    for lst in listings:
        mod = _parse_ddf_ts(lst.get("modification_timestamp"))
        if mod is None:
            fresh.append(lst)
            continue
        age_days = (now - mod).days
        if age_days > threshold_days:
            stale.append(lst)
        else:
            fresh.append(lst)
    return fresh, stale




def _is_pre_construction(l: dict) -> bool:
    """NLAR Matrix explicitly flags this build as not yet started.

    Distinct from _is_new_construction (recently-built OR under-
    construction inventory): pre-construction means the listing agent
    marked the build as not-yet-started via one of the two IDX overlay
    fields carrying that signal (idx_year_built_desc's 8-option enum,
    idx_new_construction_only's 2-option enum -- both surface "To Be
    Built" on Matrix's Building Information tab, Input_296/Input_193).
    A future or blank year_built alone never triggers this -- only an
    explicit "To Be Built" flag does, so a resale with an unfilled
    year_built can't false-positive into this rollup.
    """
    if (l.get("idx_year_built_desc") or "").strip() == "To Be Built":
        return True
    if (l.get("idx_new_construction_only") or "").strip() == "To Be Built":
        return True
    return False


def _is_new_construction(l: dict) -> bool:
    """year_built within the last 2 years, or explicit new-build phrasing.

    Pre-construction listings (build not yet started) are excluded here
    even when year_built/remarks would otherwise match -- they belong to
    the separate Pre-Construction rollup instead (2026-08-09), never both.
    """
    if _is_pre_construction(l):
        return False
    yb = l.get("year_built") or 0
    if yb >= _current_year() - 2:
        return True
    # Year-built sanity guard (2026-07-20, fleet-wide): remarks phrasing
    # ("new build", "brand new", ...) only counts when year_built is
    # ABSENT — a present-but-old numeric year contradicts the phrasing
    # (the resale-mislabel class, cf. Avalon MLS 1300231).
    if yb:
        return False
    remarks = l.get("public_remarks") or ""
    return bool(_NEW_BUILD_RE.search(remarks))






# Each rollup is a plain dict so we can keep this file dependency-free
# (no dataclasses import) and so the shape is easy to serialize into
# deploy-manifest.json if we ever want to.
#
# Required keys per rollup:
#   slug      URL segment and directory name. Must not collide with city slugs.
#   display   Human-readable label (breadcrumb + page headline).
#   eyebrow   Small label shown above the H1.
#   headline  The H1 text. Prefer "<category> in Labrador City & Wabush".
#   sub       Sub-paragraph below the H1.
#   filter    Callable(listing) -> bool.
#   sort_key  Callable(listing) -> tuple — sort order for this rollup.
ROLLUPS: list[dict] = [
    {
        "slug":     "new-construction",
        "display":  "New Construction",
        "eyebrow":  "Brand-new Builds",
        "headline": "New Construction Homes in Labrador City & Wabush",
        "sub":      (
            "Newly built and under-construction homes across our coverage "
            "area — live MLS® data from NLAR, updated daily."
        ),
        "filter":   _is_new_construction,
        # Newest year first, then priciest, then stable by MLS.
        "sort_key": lambda l: (
            -(l.get("year_built") or 0),
            -(l.get("list_price") or 0),
            l.get("mls") or "",
        ),
    },
    {
        "slug":     "pre-construction",
        "display":  "Pre-Construction",
        "eyebrow":  "Coming Soon · Build to Suit",
        "headline": "Pre-Construction Homes in Labrador City & Wabush",
        "sub":      (
            "Homes not yet built — reserve your lot or customize the build "
            "before ground breaks. Live MLS® data from NLAR, updated daily."
        ),
        "filter":   _is_pre_construction,
        # Cheapest first (lowest barrier to reserve), then stable by MLS.
        "sort_key": lambda l: (
            (l.get("list_price") or 0),
            l.get("mls") or "",
        ),
    },
    {
        "slug":     "first-time-buyer",
        "display":  "First-Time Buyer Homes",
        "eyebrow":  "Entry-Level · Under $300k",
        "headline": "Homes for First-Time Buyers in Labrador City & Wabush",
        "sub":      (
            "Every residential listing under $300,000 across our coverage "
            "area — the entry-level pool for first-time buyers. Live MLS® "
            "data from NLAR, updated daily."
        ),
        "filter":   _is_first_time_buyer,
        # Cheapest first (most FTB-relevant), then stable by MLS.
        "sort_key": lambda l: (
            (l.get("list_price") or 0),
            l.get("mls") or "",
        ),
    },
    {
        "slug":     "commercial",
        "display":  "Commercial & Business Listings",
        "eyebrow":  "Commercial · Business · Multi-Family",
        "headline": "Commercial Real Estate in Labrador City & Wabush",
        "sub":      (
            "Active commercial, business-for-sale, and multi-family "
            "listings across our coverage area. Live MLS® data from "
            "NLAR, updated daily."
        ),
        "filter":   _is_commercial,
        # Highest price first (investor-oriented).
        "sort_key": lambda l: (
            -(l.get("list_price") or 0),
            l.get("mls") or "",
        ),
    },
]

ROLLUP_SLUGS: frozenset[str] = frozenset(r["slug"] for r in ROLLUPS)


# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════

def city_display_name(slug: str) -> str:
    if slug in CITY_DISPLAY:
        return CITY_DISPLAY[slug]
    # Title-case the slug, then repair the apostrophe-stripping artifact:
    # upstream slugifier turns "Heart's Content" into `heart-s-content`,
    # which without repair displays as "Heart S Content". Convert any
    # standalone " S " (orphaned 's' between words) back to "'s ", and
    # the same for trailing " S" at end-of-string.
    # Mirror of stjohns/aec2fd89 2026-04-28; Convention #15 propagation.
    label = " ".join(w.capitalize() for w in slug.split("-"))
    import re as _re
    label = _re.sub(r"(?<=\w) S(?=\s|$)", "'s", label)
    return label


def fmt_price(p, *, listing=None):
    """Format price for consumer surfaces.

    `listing` arg (optional) lets callers carry the full row so we can render
    "For lease — Contact for rate" instead of generic "Contact for price"
    when the row has been normalized by `_normalize_lease_listings()`
    (Convention #21 layer 1 + Convention #74 fail-safe). Backward-compat:
    fmt_price(None) still returns "Contact for price" when listing not passed.
    """
    if listing and listing.get("is_lease"):
        # D-1009-77: "$5,000/month", "$17.50/sq ft", "$2,175 (lease)" or
        # "Contact for rent" -- the period only when the listing states it.
        return _lr.rent_label(listing.get("rent"), listing.get("rent_basis"))
    if p is None:
        return "Contact for price"
    return f"${p:,.0f}"










def fmt_postal(p):
    """Canadian postal code formatter — 'A1V1L6' -> 'A1V 1L6'.

    Convention #15 propagation from realestategander-site canonical
    (2026-05-16). DDF/IDX feeds sometimes return postal codes without
    the space between FSA and LDU. Canada Post and every Canadian
    carrier expects spaced form, and consumers visually recognize
    "A1V 1L6" not "A1V1L6". Normalizes any 6-char Canadian postal
    (A#A#A# pattern); returns other inputs unchanged so it's safe at
    every render site.
    """
    if not p:
        return ""
    s = str(p).strip().upper().replace(" ", "")
    if (len(s) == 6
            and s[0].isalpha() and s[1].isdigit() and s[2].isalpha()
            and s[3].isdigit() and s[4].isalpha() and s[5].isdigit()):
        return s[:3] + " " + s[3:]
    return p  # not a Canadian postal — return as-is








# ═══════════════════════════════════════════════════════════════════
#  TURNER REALTY TEAM — listing-agent recognition registry
# ═══════════════════════════════════════════════════════════════════
# Convention #15 byte-symmetric port from realestategander-site canonical
# at d977f7395 (2026-05-19) + stjohns-site at 6ed6ca357 (2026-05-20).
# When a listing's idx_list_agent_full_name matches an entry here, the
# generator surfaces "Listed by <Agent>" on cards + a full agent card
# (photo + cell + email + profile link) on the detail page right-rail
# sidebar instead of the generic "Inquiries handled by The Dynamic Duo"
# byline.
#
# Goosebay sees its own 2 agents (Karen + Roberta) most often but the
# full fleet roster is mirrored verbatim so the byline still works when
# a Turner-network listing appears in HVGB feed (cross-territory referral
# situations, agent vacations, etc.). Convention #15 byte-symmetric
# discipline — same registry on all 3 sites.
#
# Convention #74 fail-safe — non-Turner-team listings keep the existing
# brokerage byline. Convention #18 silent-degraded protection: lookup is
# case-insensitive with name-variant aliases.

# Agent registries (card / aliases / widget-team / widget-slug) — loaded from the
# canonical tools/agent_roster.json via load_registries() (Convention #148/#174
# canonical-pass Phase B; seeded 2026-06-18 from this site's own literals, byte-equality
# proven). reconstruct() rebuilds these four byte-for-byte — kills the per-site 4-mirror
# drift. Maintain agent NAP directly in agent_roster.json on this site.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from agent_roster_loader import load_registries
TURNER_AGENT_CARD, _TURNER_AGENT_ALIASES, TEAM_BY_AGENT, AGENT_PROFILE_SLUG = load_registries()

# Precomputed case-folded index for fast lookup
_TURNER_AGENT_FOLDED = {n.lower(): n for n in TURNER_AGENT_CARD}
_TURNER_AGENT_FOLDED.update(_TURNER_AGENT_ALIASES)


def match_turner_agent(idx_agent_name):
    """Case-insensitive lookup of a listing's idx_list_agent_full_name.

    Returns the TURNER_AGENT_CARD dict (with canonical 'name' key
    injected) when the agent is on the Turner team, else None.
    Convention #74 fail-safe — empty/null/non-team names return None
    cleanly so callers can fall through to brokerage default.
    """
    if not idx_agent_name:
        return None
    canon = _TURNER_AGENT_FOLDED.get(str(idx_agent_name).strip().lower())
    if not canon:
        return None
    rec = TURNER_AGENT_CARD.get(canon)
    if not rec:
        return None
    return {**rec, "name": canon}


# ═══════════════════════════════════════════════════════════════════
#  BOLDTRAIL AGENT UUID MAP (LCA-F per-territory routing — Convention #15
#  byte-symmetric port from realestategander-site c2dcf874d 2026-05-20)
# ═══════════════════════════════════════════════════════════════════
# Loads tools/boldtrail-agent-map.json once at module-load. Used by
# build_inquiry_card to emit data-agent-uuid attributes alongside
# data-agent-email so js/boldtrail-forms.js buildAssignees() can prefer
# UUID. Today UUIDs are empty placeholder — code path lights up the
# moment Mike fills any in. Convention #74 fail-safe — missing/
# malformed JSON returns empty lookup table.
_BOLDTRAIL_AGENT_MAP_LOADED = None
def _load_boldtrail_agent_map():
    global _BOLDTRAIL_AGENT_MAP_LOADED
    if _BOLDTRAIL_AGENT_MAP_LOADED is not None:
        return _BOLDTRAIL_AGENT_MAP_LOADED
    map_path = Path(__file__).resolve().parent / "boldtrail-agent-map.json"
    try:
        data = json.loads(map_path.read_text())
        _BOLDTRAIL_AGENT_MAP_LOADED = data.get("agents") or {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        _BOLDTRAIL_AGENT_MAP_LOADED = {}
    return _BOLDTRAIL_AGENT_MAP_LOADED


def boldtrail_id_for_agent(agent_slug: str) -> str:
    """Lookup BoldTrail user_id UUID for a Turner team agent by slug.

    Returns empty string when slug unmapped or UUID empty (placeholder
    state). Callers emit `data-agent-uuid="<value>"` regardless of
    empty-string state so the js/boldtrail-forms.js buildAssignees() UUID-
    first preference activates the moment a real UUID lands.
    """
    if not agent_slug:
        return ""
    entry = _load_boldtrail_agent_map().get(agent_slug)
    if not entry:
        return ""
    return (entry.get("boldtrail_id") or "").strip()


def _fmt_phone(digits: str) -> str:
    """Render a 10-digit North American number as '(709) 725-6520'.

    Accepts already-formatted strings (returns them untouched) and tolerates
    leading country-code 1. Used only for display; tel: links always use
    the raw digits."""
    if not digits:
        return ""
    d = "".join(c for c in digits if c.isdigit())
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    if len(d) != 10:
        return digits  # not a clean 10-digit; return original
    return f"({d[:3]}) {d[3:6]}-{d[6:]}"


# ═══════════════════════════════════════════════════════════════════
#  HTML BUILDING BLOCKS
#  Nav + footer are reproduced verbatim from /pages/page-template.html
#  but with link paths adjusted from "../" to "../../" because listing
#  pages live at /listings/<city>/ (one level deeper than /pages/).
# ═══════════════════════════════════════════════════════════════════

MORTGAGE_EST_RATE = 5.49        # matches pages/mortgage-calculator.html default rate
MORTGAGE_EST_DOWN = 0.20        # 20% down (no CMHC) — matches the calculator's landing state
MORTGAGE_EST_AMORT_YEARS = 25


def _est_monthly_payment(price):
    """Estimated monthly principal & interest at the mortgage calculator's default
    assumptions (20% down, 25-yr amortization, Canadian semi-annual compounding).
    Returns int dollars, or None for a non-positive / non-numeric price. Kept in
    lockstep with the #mcx calculator so the listing estimate == the calculator's
    landing value when the buyer clicks through with ?price=."""
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if p <= 0:
        return None
    mortgage = p * (1 - MORTGAGE_EST_DOWN)
    mr = (1 + (MORTGAGE_EST_RATE / 100) / 2) ** (1 / 6) - 1
    n = MORTGAGE_EST_AMORT_YEARS * 12
    pay = mortgage / n if mr == 0 else mortgage * (mr * (1 + mr) ** n) / ((1 + mr) ** n - 1)
    return int(round(pay))


def build_payment_estimate_line(listing) -> str:
    """Crawlable 'Est. $X/mo' line under the price banner, deep-linking to the
    mortgage calculator prefilled with this listing's price. Omitted for lease
    listings and non-priced listings (Convention #21 layer 4 render-time fallback)."""
    if listing.get("is_lease"):
        return ""
    price = listing.get("list_price")
    est = _est_monthly_payment(price)
    if est is None:
        return ""
    price_int = int(float(price))
    if not _page_exists("mortgage-calculator.html"):
        return (
            f'<p style="margin:2px 0 0;font-size:14px;color:var(--ld-text-dim,rgba(255,255,255,0.55));" '
            f'title="Estimated principal &amp; interest at {MORTGAGE_EST_RATE}% with 20% down over 25 years.">'
            f'Est. ${est:,}/mo</p>'
        )
    return (
        f'<p style="margin:2px 0 0;font-size:14px;">'
        f'<a href="../../pages/mortgage-calculator.html?price={price_int}" '
        f'style="color:#EA002A;text-decoration:none;font-weight:600;" '
        f'title="Estimated principal &amp; interest at {MORTGAGE_EST_RATE}% with 20% down '
        f'over 25 years. Click to add CMHC, closing costs and affordability.">'
        f'Est. ${est:,}/mo '
        f'<span style="color:var(--ld-text-dim,rgba(255,255,255,0.55));font-weight:400;">'
        f'&middot; calculate &rarr;</span></a></p>'
    )


def build_budget_record(listing) -> str:
    """Inert JSON island that js/budget-v1.js (OWNERSHIP_BUDGET, portal idea 1, Mike D-1009-30) reads on this page and on /budget/?mls=.
    Carries only what the listing record holds: the list price, the yearly tax (Taxamount) and its year, the heating type, the monthly
    condo fee (only when > 0) and the property subtype. Nothing is estimated here, and no sold price is ever written (VOW). Omitted for
    lease listings and non-priced listings. Invisible: the switch decides whether the sheet is drawn at all."""
    if listing.get("is_lease"):
        return ""
    try:
        price = float(str(listing.get("list_price") or "").strip())
    except (TypeError, ValueError):
        return ""
    if price <= 0:
        return ""

    def _pos(v):
        try:
            f = float(str(v or "").replace("$", "").replace(",", "").strip())
        except (TypeError, ValueError):
            return None
        if f <= 0:
            return None
        return int(f) if f == int(f) else f

    rec = {"mls": str(listing.get("mls") or ""), "price": int(round(price))}
    for key, val in (("tax", _pos(listing.get("idx_tax_amount"))), ("condo", _pos(listing.get("idx_condo_fee")))):
        if val:
            rec[key] = val
    for key, val in (("taxYear", listing.get("idx_tax_year")), ("heating", listing.get("idx_heating")), ("sub", listing.get("property_subtype"))):
        if val and str(val).strip():
            rec[key] = str(val).strip()
    return ('<script type="application/json" id="budget-record">'
            + json.dumps(rec, separators=(",", ":")).replace("<", "\\u003c").replace("&", "\\u0026")
            + "</script>")


def build_all_in_line(listing) -> str:
    """Second small line under the P&I estimate: an 'all-in' monthly figure
    adding property tax (annual idx_tax_amount / 12) + condo fee (already
    a MONTHLY dollar string per _fmt_idx_money's own docstring) when
    present. Renders ONLY when idx_tax_amount parses to a positive number
    (Batch F2, 2026-08-20, plan's own no-guessing rule) -- condo fee is an
    optional addend, never a trigger on its own, and the '0.00' condo-fee
    sentinel is excluded exactly like _fmt_idx_money already excludes it
    elsewhere on this page. Omitted for lease listings and non-priced
    listings, same guards as build_payment_estimate_line."""
    if listing.get("is_lease"):
        return ""
    price = listing.get("list_price")
    pi = _est_monthly_payment(price)
    if pi is None:
        return ""
    try:
        tax_annual = float(str(listing.get("idx_tax_amount") or "").strip())
    except (TypeError, ValueError):
        return ""
    if tax_annual <= 0:
        return ""
    tax_monthly = tax_annual / 12
    condo_monthly = 0.0
    has_condo = False
    try:
        cf = float(str(listing.get("idx_condo_fee") or "").strip())
        if cf > 0:
            condo_monthly = cf
            has_condo = True
    except (TypeError, ValueError):
        pass
    all_in = int(round(pi + tax_monthly + condo_monthly))
    breakdown = "P&amp;I + taxes" + (" + condo fee" if has_condo else "")
    condo_note = " and condo fee" if has_condo else ""
    return (
        f'<p style="margin:2px 0 0;font-size:12px;'
        f'color:var(--ld-text-dim,rgba(255,255,255,0.5));" '
        f'title="Estimate \u2014 property tax{condo_note} from the listing '
        f'record; P&amp;I at {MORTGAGE_EST_RATE}% with 20% down over '
        f'{MORTGAGE_EST_AMORT_YEARS} years.">'
        f'\u2248 ${all_in:,}/mo all-in &middot; {breakdown}'
        f'</p>'
    )


def build_resource_strip(listing) -> str:
    """Compact one-line resource nudge between the facts strip and the
    description (W4, 2026-08-19). Deliberately NOT a third CTA in
    build_keep_exploring, which is a strict two-CTA "no dead end" block per
    Mike's own 2026-04-19 rule -- this is a quieter secondary resource line,
    not a competing call to action. Skipped for lease listings (closing costs
    don't apply to a lease) and non-priced listings (Convention #21 layer 4)."""
    if listing.get("is_lease"):
        return ""
    price = listing.get("list_price")
    try:
        price_int = int(float(price))
    except (TypeError, ValueError):
        return ""
    _links = []
    if _page_exists("closing-cost-calculator-nl.html"):
        _links.append(f'<a href="../../pages/closing-cost-calculator-nl.html?price={price_int}">Estimate your closing costs &rarr;</a>')
    if _page_exists("real-estate-paperwork-nl.html"):
        _links.append('<a href="../../pages/real-estate-paperwork-nl.html">See every form you&rsquo;ll sign &rarr;</a>')
    if not _links:
        return ""
    return (
        '<div class="lst-resource-strip">'
        '<p>Buying this home? ' + ' &middot; '.join(_links) +
        '</p></div>'
    )


def head_block(listing) -> str:
    """The complete <head>…</head> for a listing detail page."""
    title = f"{listing['street']}, {city_display_name(listing['city_slug'])} NL — {fmt_price(listing['list_price'], listing=listing)}"
    if len(title) > 60:  # SEO: keep <title> <=60 so Google does not truncate; MLS# stays in URL/meta/H1/JSON-LD
        title = f"{listing['street']}, {city_display_name(listing['city_slug'])} NL"
    description_parts = [listing.get("street") or "", city_display_name(listing["city_slug"]) + ", NL"]
    if listing.get("bedrooms"):
        description_parts.append(f"{listing['bedrooms']} bed")
    if listing.get("bathrooms"):
        description_parts.append(f"{fmt_bath(listing['bathrooms'])} bath")
    if listing.get("list_price"):
        description_parts.append(fmt_price(listing["list_price"], listing=listing))
    description_parts.append(f"MLS® {listing['mls']}.")
    description_parts.append("Live MLS® listing from Royal LePage Turner Realty.")
    description = " · ".join(p for p in description_parts if p)

    canonical = f"{SITE_ORIGIN}{listing['url_path']}"
    og_image = listing["photos"][0]["url"] if listing["photos"] else f"{SITE_ORIGIN}/images/og/pages-listing-detail-og.jpg"

    # LCP optimization (added 2026-05-10): the hero photo IS the LCP element on
    # listing-detail pages. Preconnect to the realtor.ca CDN saves the TLS
    # handshake; preload pushes the hero to the top of the network queue.
    # Both lines are no-ops when listing has no photos.
    hero_preload_html = (
        f'<link rel="preload" as="image" href="{he(listing["photos"][0]["url"])}" fetchpriority="high">'
        if listing["photos"] else ""
    )

    return f"""<head>
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id={GTAG_LOADER_ID}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{GTAG_LOADER_ID}');
</script>
{FUB_PIXEL_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="description" content="{he(description)}">
<meta property="og:url" content="{he(canonical)}">
<meta property="og:title" content="{he(title)}">
<meta property="og:description" content="{he(description)}">
<meta property="og:image" content="{he(og_image)}">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{he(title)}">
<meta name="twitter:description" content="{he(description)}">
<meta name="twitter:image" content="{he(og_image)}">
<title>{he(title)}</title>
<link rel="canonical" href="{he(canonical)}">
<link rel="icon" type="image/x-icon" href="../../favicon.ico">
<link rel="icon" type="image/png" sizes="32x32" href="../../favicon-32x32.png">
<link rel="apple-touch-icon" sizes="180x180" href="../../apple-touch-icon.png">
<meta name="theme-color" content="#EA002A">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="Lab West Realty">
<link rel="preconnect" href="https://ddfcdn.realtor.ca" crossorigin>
{hero_preload_html}
<link rel="stylesheet" href="../../css/main.css?v=20260916-mobile-a">
<link rel="stylesheet" href="../../css/mobile-fixes.css?v=20260916-mobile-a">
<link rel="stylesheet" href="../../css/turner-network.css">
<link rel="stylesheet" href="../../css/mobile-action-bar.css?v=20260917-mobile-action-bar">
<link rel="stylesheet" href="../../css/favorites.css?v=20260605-favorites">
<style>
{LISTING_PAGE_CSS}
</style>
<script src="../../js/analytics-events.js" defer></script>
</head>"""


# Nav + footer are path-parameterized so the same template can be used at depth 1
# (`/listings/index.html` → prefix `../`) or depth 2 (`/listings/<city>/<slug>.html`
# → prefix `../../`). NAV_HTML and FOOTER_HTML below are the depth-2 variants;
# nav_html(prefix) and footer_html(prefix) are the generic builders.

def nav_html(prefix: str = "../../") -> str:
    return _NAV_TEMPLATE.replace("{{P}}", prefix)


def footer_html(prefix: str = "../../") -> str:
    return _FOOTER_TEMPLATE.replace("{{P}}", prefix).replace("{{YEAR}}", str(datetime.now(timezone.utc).year))


_NAV_TEMPLATE = """<div class="nav-top-bar"></div>
<nav class="nav-main-bar"></nav>"""

_FOOTER_TEMPLATE = """<footer class="site-footer">
  <div class="footer-inner">
    <div class="footer-brand">
      <img loading="lazy" src="{{P}}images/rlp-logo.png" alt="Royal LePage Turner Realty" width="80">
      <p>Mike Turner, Broker of Record<br>Royal LePage Turner Realty<br><a href="tel:7092567999">709-256-7999</a> &middot; <a href="mailto:miketurner@royallepage.ca">miketurner@royallepage.ca</a></p>
    </div>
    <div>
      <div class="footer-heading">Quick Links</div>
      <ul class="footer-links">
        <li><a href="{{P}}index.html">Home</a></li>
        <li><a href="{{P}}listings/">Homes for Sale</a></li>
        <li><a href="{{P}}labrador-west.html">Labrador West Market</a></li>
        <li><a href="{{P}}contact.html">Contact</a></li>
      </ul>
    </div>
    <div>
      <div class="footer-heading">Agents</div>
      <ul class="footer-links">
        <li><a href="{{P}}become-a-realtor.html">This Could Be Your Territory</a></li>
        <li><a href="{{P}}why-join.html">Why Join</a></li>
        <li><a href="{{P}}about-turner.html">About Turner</a></li>
      </ul>
    </div>
  </div>
  <div class="footer-bottom">
    <p>&copy; 1998&ndash;{{YEAR}} Royal LePage Turner Realty (2014) Inc. &middot; Est. 1998. Serving Newfoundland &amp; Labrador.</p>
    <p>Each office independently owned and operated. Not intended to solicit buyers or sellers currently under contract.</p>
  </div>
</footer>"""


# ═══════════════════════════════════════════════════════════════════
#  PAGE-SCOPED CSS (.lst-)
# ═══════════════════════════════════════════════════════════════════

LISTING_PAGE_CSS = """
/* Listing page scope (.lst-) */
.lst-shell { background: #0a0a0a; color: #fff; }

/* Hero gallery + lightbox-wired CTA wrapper.
   2026-09-15: ported from Avalon/Gander (Tier 1 fleet photo-display check)
   -- adds the .lst-gallery-wrap/.lst-gallery-noimg/.lst-view-all-btn
   machinery js/lightbox.js + build_gallery() now emit, plus a
   low-photo-count layout (lst-gallery--n1..--n4) so 1-4-photo listings
   don't leave an empty grid cell and non-hero tiles (floor plans,
   portrait photos) aren't cropped by object-fit:cover. */
.lst-gallery-wrap { max-width: 1200px; margin: 24px auto 0; padding: 0 20px; position: relative; }
.lst-gallery-noimg { display: none; }
.lst-gallery-wrap--noimg .lst-gallery,
.lst-gallery-wrap--noimg .lst-view-all-btn { display: none !important; }
.lst-gallery-wrap--noimg .lst-gallery-noimg {
  display: flex; align-items: center; justify-content: center;
  aspect-ratio: 1.6 / 1; max-height: 460px;
  background: linear-gradient(135deg, #1a1a1a, #0f0f0f);
  border-radius: 4px;
  color: rgba(255, 255, 255, 0.4);
  font-family: 'Raleway', sans-serif; font-weight: 800; font-size: 1.5rem;
}
.lst-gallery {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  grid-template-rows: 1fr 1fr;
  gap: 8px;
}
.lst-gallery a { display: block; overflow: hidden; border-radius: 4px; background: #111; cursor: zoom-in; }
.lst-gallery a img { width: 100%; height: 100%; object-fit: cover; transition: transform .4s; display: block; }
.lst-gallery a:hover img { transform: scale(1.04); }
.lst-gallery a:nth-child(1) { grid-row: 1 / span 2; aspect-ratio: 1.6 / 1; }
.lst-gallery a:nth-child(n+2) { aspect-ratio: 1.5 / 1; }
.lst-gallery .lst-more-overlay {
  position: relative;
}
.lst-gallery .lst-more-overlay::after {
  content: attr(data-more) " more photos";
  position: absolute; inset: 0;
  background: rgba(0,0,0,0.55);
  color: #fff;
  font-family: 'Raleway', sans-serif; font-weight: 800; font-size: 1rem;
  display: flex; align-items: center; justify-content: center;
  letter-spacing: 0.5px;
  pointer-events: none;
}
/* Photos 6+ (B3, 2026-09-17): only exist for the mobile swipe gallery.
   Hidden on desktop/tablet so the existing 5-tile grid is unaffected. */
.lst-gallery .lst-gallery-extra { display: none; }
.lst-view-all-btn {
  display: none;
  margin: 12px auto 0;
  background: #EA002A; color: #fff;
  border: none; padding: 12px 24px; border-radius: 4px;
  font-family: 'Raleway', sans-serif; font-weight: 700;
  font-size: 0.95rem; letter-spacing: 0.4px;
  text-transform: uppercase; cursor: pointer;
  transition: background .15s ease;
}
.lst-view-all-btn:hover, .lst-view-all-btn:focus {
  background: #c8001f; outline: none;
}
/* "1 / N" photo counter — mobile swipe mode only (see @media max-width:767px
   below). */
.lst-gallery-counter {
  display: none;
  position: absolute;
  right: 28px; bottom: 16px;
  background: rgba(0,0,0,0.65);
  color: #fff;
  font-family: 'Roboto', sans-serif;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 999px;
  letter-spacing: .3px;
  pointer-events: none;
  z-index: 3;
}
/* Low-photo-count layouts. Applies to the shared desktop/tablet grid
   (≥768px) -- below 768px the mobile swipe gallery takes over and photo
   count doesn't affect layout. */
@media (min-width: 768px) {
  .lst-gallery--n1 { grid-template-columns: 1fr; grid-template-rows: 1fr; }
  .lst-gallery--n1 a:nth-child(1) { grid-row: 1; aspect-ratio: 1.6 / 1; max-height: 560px; }
  .lst-gallery--n2 { grid-template-columns: 1fr 1fr; grid-template-rows: 1fr; }
  .lst-gallery--n2 a:nth-child(1) { grid-row: 1; aspect-ratio: 1.6 / 1; }
  .lst-gallery--n2 a:nth-child(2) { aspect-ratio: 1.6 / 1; }
  .lst-gallery--n3 { grid-template-columns: 2fr 1fr; grid-template-rows: 1fr 1fr; }
  .lst-gallery--n3 a:nth-child(n+2) { aspect-ratio: 1.5 / 1; }
  .lst-gallery--n4 { grid-template-columns: 2fr 1fr 1fr; grid-template-rows: 1fr 1fr; }
  .lst-gallery--n4 a:nth-child(4) { grid-column: 2 / span 2; aspect-ratio: 3 / 1; }
  .lst-gallery--n1 a:not(:nth-child(1)) img,
  .lst-gallery--n2 a:nth-child(2) img,
  .lst-gallery--n3 a:nth-child(n+2) img,
  .lst-gallery--n4 a:nth-child(n+2) img {
    object-fit: contain; background: #111;
  }
}
/* ─── Tablet (768–1023px, B3 2026-09-17): a smaller version of the same
   grid — still 1 hero + up to 4 thumbnails, just tighter gaps/aspect. ─── */
@media (min-width: 768px) and (max-width: 1023px) {
  .lst-gallery-wrap { padding: 0 16px; }
  .lst-gallery { gap: 6px; }
  .lst-gallery a:nth-child(1) { aspect-ratio: 1.4 / 1; }
}
/* ─── Mobile (<768px, B3 2026-09-17): horizontally swipeable, scroll-snap
   gallery — one full-width photo per "page", native touch scrolling, no
   JS carousel. Photos 6+ (.lst-gallery-extra, hidden above 768px) join the
   strip here so a swipe can reach every photo on the listing. ─── */
@media (max-width: 767px) {
  .lst-gallery-wrap { padding: 0; }
  .lst-gallery {
    display: flex;
    grid-template-columns: none;
    overflow-x: auto;
    scroll-snap-type: x mandatory;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    gap: 0;
  }
  .lst-gallery::-webkit-scrollbar { display: none; }
  .lst-gallery a,
  .lst-gallery a:nth-child(1),
  .lst-gallery a:nth-child(n+2) {
    flex: 0 0 100%;
    grid-row: unset;
    aspect-ratio: 4 / 3;
    scroll-snap-align: start;
    scroll-snap-stop: always;
    border-radius: 0;
  }
  .lst-gallery .lst-gallery-extra { display: block; }
  .lst-gallery .lst-more-overlay::after { display: none; } /* swipe already reveals every photo */
  .lst-view-all-btn { display: none; } /* redundant once swipe shows all photos */
  .lst-gallery-counter { display: block; }
}

/* ═══ Virtual tour / video embed ═══ */
.lst-tour-section h2 { margin-bottom: 16px; }
.lst-tour-embed {
  position: relative;
  width: 100%;
  padding-bottom: 56.25%; /* 16:9 — YouTube default */
  height: 0;
  background: #111;
  border-radius: 4px;
  overflow: hidden;
  margin: 0 0 16px;
}
.lst-tour-embed:last-child { margin-bottom: 0; }
.lst-tour-embed iframe {
  position: absolute; top: 0; left: 0;
  width: 100%; height: 100%;
  border: 0;
}
/* iGuide / Matterport render taller by default */
.lst-tour-3d { padding-bottom: 65%; }
.lst-tour-fallback { margin: 0 0 16px; }
.lst-tour-fallback a { display: inline-block; }

/* ═══════════════════════════════════════════════════════════════════
   Google Street View Static — server-side <img> embed (2026-05-14)
   Convention #15 propagation from realestategander-site canonical
   (a657aef07). Convention #91: rules MUST live in LISTING_PAGE_CSS.
   ═══════════════════════════════════════════════════════════════════ */
.lst-streetview {
  margin: 28px 0;
  padding: 20px;
  background: #0f0f0f;
  border: 1px solid #1f1f1f;
  border-radius: 6px;
}
.lst-streetview-h {
  margin: 0 0 14px;
  font-family: 'Raleway', sans-serif;
  font-size: 1.1rem;
  font-weight: 700;
  letter-spacing: 0.3px;
  color: #fff;
}
.lst-streetview-img-wrap {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  border-radius: 4px;
  background: #1a1a1a;
}
.lst-streetview-img-wrap img,
.lst-streetview-img-wrap iframe {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  border: 0;
}
/* Scroll trap (mobile review 2026-09-16, A11): a live Street View iframe
   swallows every touch that lands on it, so a thumb scrolling the page
   pans the panorama instead. The iframe is inert until the visitor taps
   the overlay, which adds .is-live. */
.lst-streetview-img-wrap iframe { pointer-events: none; }
.lst-streetview-img-wrap.is-live iframe { pointer-events: auto; }
.lst-streetview-tap {
  position: absolute;
  inset: 0;
  width: 100%;
  min-height: 44px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin: 0;
  padding: 0;
  background: rgba(0, 0, 0, 0.28);
  color: #fff;
  border: 0;
  cursor: pointer;
  font-family: 'Raleway', sans-serif;
  font-weight: 800;
  font-size: 0.9rem;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.6);
}
.lst-streetview-tap svg { width: 48px; height: 48px; }
.lst-streetview-tap:hover, .lst-streetview-tap:focus-visible { background: rgba(0, 0, 0, 0.42); outline: none; }
.lst-streetview-img-wrap.is-live .lst-streetview-tap { display: none; }
.lst-streetview-attr {
  margin: 12px 0 0;
  font-family: 'Roboto', sans-serif;
  font-size: 0.78rem;
  color: #8a8a8a;
  text-align: right;
}
.lst-streetview-attr a {
  color: #b0b0b0;
  text-decoration: underline;
}
.lst-streetview-attr a:hover { color: #EA002A; }

@media (max-width: 560px) {
  .lst-streetview { padding: 14px; }
}

/* ═══════════════════════════════════════════════════════════════════
   Room-by-Room dimensions table (2026-05-14)
   Convention #15 propagation from Gander Client Full parity ship.
   ═══════════════════════════════════════════════════════════════════ */
.lst-rooms-section h2 {
  font-family: 'Raleway', sans-serif;
  font-weight: 700;
  color: #fff;
  font-size: 1.3rem;
  margin: 0 0 12px;
}
.lst-rooms-table {
  width: 100%;
  border-collapse: collapse;
  font-family: 'Roboto', sans-serif;
  margin-top: 12px;
  font-size: 0.92rem;
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 6px;
  overflow: hidden;
}
.lst-rooms-table th,
.lst-rooms-table td {
  padding: 10px 14px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  text-align: left;
  color: rgba(255,255,255,0.88);
}
.lst-rooms-table th {
  font-family: 'Raleway', sans-serif;
  font-weight: 700;
  text-transform: uppercase;
  font-size: 0.75rem;
  letter-spacing: 0.06em;
  color: rgba(255,255,255,0.55);
  background: rgba(255,255,255,0.03);
  border-bottom: 1px solid rgba(255,255,255,0.1);
}
.lst-rooms-table tbody tr:last-child td {
  border-bottom: 0;
}
.lst-rooms-table tbody tr:hover td {
  background: rgba(234, 0, 42, 0.04);
}
@media (max-width: 560px) {
  .lst-rooms-table th,
  .lst-rooms-table td {
    padding: 8px 10px;
    font-size: 0.85rem;
  }
}

/* Two-column layout */
.lst-main {
  max-width: 1200px;
  margin: 40px auto;
  padding: 0 20px;
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 40px;
}
/* min-width:0 unconditionally -- without it, a grid item's intrinsic
   min-content (long unbroken team/testimonial-count text in .lst-sidebar)
   can blow the 2-col grid past its container at ANY width the grid is
   active, not just phones. .lst-detail kept alongside the real
   .lst-sidebar class for safety (found dead here, pre-existing typo --
   plan B5 2026-09-17). */
.lst-content, .lst-detail, .lst-sidebar { min-width: 0; }
/* B3 2026-09-17: bumped from 900px to 1023px so genuine tablets (iPad
   landscape and similar ~1024px-wide viewports) get the stacked,
   non-sticky-sidebar layout too, not just phones -- see .lst-sidebar
   override in the same breakpoint below. Desktop (≥1024px) is unchanged. */
@media (max-width: 1023px) { .lst-main { grid-template-columns: 1fr; } }

/* Stage 4 mobile CTA bar retired 2026-09-17 -- superseded by the
   site-owned .mab-bar (css/mobile-action-bar.css, js/mobile-action-bar.js).
   See Mobile + iPad review of the fleet, Part 1 Tier B row B1. */

/* Title block */
.lst-title-block { margin-bottom: 30px; }
.lst-eyebrow {
  font-family: 'Roboto', sans-serif;
  font-size: 0.85rem;
  color: #EA002A;
  text-transform: uppercase;
  letter-spacing: 1px;
  font-weight: 600;
  margin: 0 0 12px;
}
.lst-title-block h1 {
  font-family: 'Raleway', sans-serif;
  font-size: clamp(1.7rem, 3.5vw, 2.4rem);
  font-weight: 900;
  color: #fff;
  margin: 0 0 8px;
  letter-spacing: -0.5px;
  line-height: 1.2;
}
.lst-locality {
  font-family: 'Roboto', sans-serif;
  color: rgba(255,255,255,0.65);
  font-size: 1rem;
  margin: 0 0 18px;
}
.lst-price {
  font-family: 'Raleway', sans-serif;
  font-size: clamp(2rem, 4vw, 2.8rem);
  font-weight: 900;
  color: #fff;
  margin: 0;
  letter-spacing: -1px;
}
.lst-price-meta {
  font-family: 'Roboto', sans-serif;
  font-size: 0.85rem;
  color: rgba(255,255,255,0.5);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin: 6px 0 0;
}
.lst-dom-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 18px 0 0;
  font-family: 'Roboto', sans-serif;
  font-size: 0.88rem;
  color: rgba(255,255,255,0.6);
}
.lst-detail-status-badge {
  display: inline-block;
  color: #fff;
  padding: 6px 14px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .75px;
  margin: 0 0 10px;
}
.lst-detail-status-badge.pending { background: #d97706; }  /* amber — accepted offer, conditions in play */
.lst-just-listed {
  display: inline-block;
  background: #EA002A;
  color: #fff;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-size: 0.72rem;
  padding: 4px 10px;
  border-radius: 3px;
}
.lst-dom {
  color: rgba(255,255,255,0.55);
}

/* Quick facts strip */
.lst-facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 16px;
  background: #111;
  border: 1px solid #222;
  border-radius: 4px;
  padding: 24px;
  margin: 30px 0;
}
.lst-fact { text-align: center; }
.lst-fact-num {
  font-family: 'Raleway', sans-serif;
  font-weight: 900;
  font-size: 1.6rem;
  color: #fff;
}
.lst-fact-label {
  font-family: 'Roboto', sans-serif;
  font-size: 0.75rem;
  color: rgba(255,255,255,0.5);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-top: 4px;
}
/* B3 (2026-09-17): the auto-fit grid wraps awkwardly at phone width once
   there are 5-6 facts. A horizontally scrollable single row keeps every
   stat compact and reachable without dropping any of them. */
@media (max-width: 767px) {
  .lst-facts {
    display: flex;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    gap: 22px;
  }
  .lst-facts::-webkit-scrollbar { display: none; }
  .lst-fact { flex: 0 0 auto; min-width: 64px; }
}

/* Section */
.lst-section { margin: 40px 0; }
.lst-section h2 {
  font-family: 'Raleway', sans-serif;
  font-size: 1.4rem;
  font-weight: 800;
  color: #fff;
  margin: 0 0 16px;
  padding-bottom: 10px;
  border-bottom: 1px solid #222;
}
/* ─── Description clamp + Read more (B3, 2026-09-17) — mobile only, and
   scoped to .lst-remarks specifically so it never touches the many other
   .lst-section paragraphs on this page (details grid intro text, etc). ─── */
.lst-remarks-toggle { display: none; }
@media (max-width: 767px) {
  p.lst-remarks {
    display: -webkit-box;
    -webkit-line-clamp: 6;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  p.lst-remarks.is-expanded {
    display: block;
    -webkit-line-clamp: unset;
    overflow: visible;
  }
  .lst-remarks-toggle {
    display: inline-flex;
    align-items: center;
    margin-top: 10px;
    min-height: 44px;
    background: transparent;
    border: 0;
    color: #EA002A;
    font-weight: 600;
    font-size: 14px;
    font-family: inherit;
    cursor: pointer;
    padding: 0;
  }
}
.lst-section p, .lst-section li {
  font-family: 'Roboto', sans-serif;
  color: rgba(255,255,255,0.78);
  line-height: 1.7;
  font-size: 0.97rem;
}
.lst-details-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 14px 24px;
}
.lst-details-grid .lst-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #1a1a1a; }
.lst-spec-group-title { grid-column: 1 / -1; margin: 14px 0 2px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: rgba(255,255,255,0.55); border-bottom: 1px solid #1f1f1f; padding-bottom: 6px; }
.lst-spec-group-title:first-child { margin-top: 0; }

/* Feature chips (task #80, 2026-07-29) */
.lst-feature-chips {
  display: flex; flex-wrap: wrap; gap: 6px;
  margin-top: 8px;
}
.lst-feature-chip {
  background: #141414;
  border: 1px solid #222;
  color: rgba(255,255,255,0.85);
  padding: 6px 14px;
  border-radius: 999px;
  font-size: 13px;
  line-height: 1.4;
  transition: border-color .15s ease, background .15s ease;
}
.lst-feature-chip:hover {
  border-color: #EA002A;
  background: #1a1a1a;
}
.lst-details-grid .lst-row span:first-child { color: rgba(255,255,255,0.5); }
.lst-details-grid .lst-row span:last-child { color: #fff; }

/* Sidebar */
.lst-sidebar {
  position: sticky;
  top: 20px;
  align-self: start;
}
/* B3 2026-09-17: non-sticky, inline flow up to 1023px (phones + tablets,
   matches .lst-main's stacked-layout breakpoint above) -- a sticky sidebar
   in a single-column stack has nothing left to "stick" against once its
   own content ends, which read as a visual glitch on iPad-width viewports.
   Reverts to sticky at genuine desktop widths (≥1024px). */
@media (max-width: 1023px) {
  .lst-sidebar { position: static; top: auto; }
}
.lst-cta-card {
  background: #1a1a1a;
  border: 1px solid #222;
  border-radius: 4px;
  padding: 28px;
  margin-bottom: 20px;
}
.lst-cta-card h3 {
  font-family: 'Raleway', sans-serif;
  font-weight: 800;
  font-size: 1.2rem;
  color: #fff;
  margin: 0 0 8px;
}
.lst-cta-card p {
  font-family: 'Roboto', sans-serif;
  color: rgba(255,255,255,0.65);
  font-size: 0.9rem;
  margin: 0 0 18px;
}

/* Two-tab inquiry card — Book a Showing / Ask a Question. Convention #15 port
   from Gander (2026-06-19). Lab West listing-detail cards are dark, so the dark
   tab styling matches verbatim. */
.lst-rf-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  margin: 0 0 18px;
  border-radius: 4px;
  overflow: hidden;
  border: 1px solid #2a2a2a;
}
.lst-rf-tab {
  appearance: none;
  background: #111;
  color: rgba(255,255,255,0.55);
  border: none;
  padding: 12px 14px;
  font-family: 'Raleway', sans-serif;
  font-weight: 800;
  font-size: 0.78rem;
  letter-spacing: 1px;
  text-transform: uppercase;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.lst-rf-tab:hover { background: #181818; color: #fff; }
.lst-rf-tab.active {
  background: #EA002A;
  color: #fff;
  cursor: default;
}
.lst-rf-tab svg {
  vertical-align: -2px;
  margin-right: 4px;
  width: 14px;
  height: 14px;
}
.lst-rf-panel[hidden] { display: none; }
.lst-rf-tab[data-rf-tab="review"] { grid-column: 1 / -1; border-top: 1px solid #2a2a2a; text-transform: none; letter-spacing: 0.2px; font-size: 0.86rem; }
.lst-cta-card .rf-form-wrap.rf-form-flush,
.lst-cta-card .rf-form-wrap {
  background: transparent;
  border: none;
  padding: 0;
  margin: 0;
  max-width: none;
}

/* Listing-agent recognition (Convention #15 byte-symmetric port from
   stjohns-site canonical at 6ed6ca357 / 2026-05-20 — Avalon B3b). When
   the listing's IDX agent matches a Turner team agent, the right-rail
   sidebar shows their photo + name + cell + email instead of the generic
   team byline. */
.lst-cta-agent {
  border-top: 3px solid #EA002A;
  padding-top: 22px;
}
.lst-cta-agent-row {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 14px;
  align-items: center;
  margin-bottom: 16px;
}
.lst-cta-agent-photo {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid rgba(255,255,255,0.1);
  background: #1a1a1a;
}
.lst-cta-agent-meta { min-width: 0; }
.lst-cta-agent-meta p { margin: 0 !important; }
.lst-team-eyebrow {
  font-family: 'Roboto', sans-serif;
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: rgba(255,255,255,0.5);
  margin: 0 !important;
}
.lst-cta-agent-name {
  font-family: 'Raleway', sans-serif;
  font-weight: 800;
  font-size: 1.1rem;
  line-height: 1.2;
  color: #fff;
  margin: 4px 0 2px !important;
}
.lst-cta-agent-name a {
  color: #fff;
  text-decoration: none;
  transition: color 0.2s;
}
.lst-cta-agent-name a:hover { color: #EA002A; }
.lst-cta-agent-title {
  font-family: 'Roboto', sans-serif;
  font-size: 0.78rem;
  color: rgba(255,255,255,0.7);
  margin: 0 0 2px !important;
}
.lst-cta-agent-team {
  font-family: 'Roboto', sans-serif;
  font-size: 0.72rem;
  color: rgba(255,255,255,0.45);
  margin: 0 !important;
}
.lst-cta-agent-contact {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.lst-cta-agent-tel,
.lst-cta-agent-email {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px 12px;
  font-family: 'Raleway', sans-serif;
  font-weight: 700;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  text-decoration: none;
  border-radius: 4px;
  border: 1px solid rgba(255,255,255,0.15);
  color: #fff;
  background: rgba(255,255,255,0.02);
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.lst-cta-agent-tel:hover,
.lst-cta-agent-email:hover {
  background: #EA002A;
  border-color: #EA002A;
  color: #fff;
}
.lst-cta-agent-tel svg,
.lst-cta-agent-email svg {
  width: 14px;
  height: 14px;
  fill: currentColor;
}
.lst-cta-agent-email svg { fill: none; stroke: currentColor; stroke-width: 2; }

/* Card-level "Listed by X" byline (city/rollup pages) */
.lst-card-team {
  margin: 6px 0 0 !important;
  font-family: 'Roboto', sans-serif;
  font-size: 0.72rem;
  color: rgba(255,255,255,0.55);
}
.lst-card-team strong {
  color: rgba(255,255,255,0.85);
  font-weight: 600;
}

/* Brokerage attribution + DDR badge */
.lst-attribution {
  background: #111;
  border: 1px solid #222;
  border-radius: 4px;
  padding: 20px;
  margin: 30px 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}
.lst-attribution-text {
  font-family: 'Roboto', sans-serif;
  font-size: 0.8rem;
  color: rgba(255,255,255,0.6);
  margin: 0;
}
.lst-attribution-text strong { color: #fff; font-weight: 600; }
/* "Hear about this home" -- Ship 4 port, 2026-09-11 */
.lst-listen {
  background: #111;
  border: 1px solid #222;
  border-radius: 4px;
  padding: 20px;
  margin: 20px 0;
}
.lst-listen--preview { display: none; }
.lst-listen-btn {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 999px;
  color: #fff;
  font-family: 'Roboto', sans-serif;
  font-weight: 600;
  font-size: 0.9rem;
  padding: 10px 20px;
  cursor: pointer;
  transition: border-color .15s, color .15s;
}
.lst-listen-btn:hover { border-color: #EA002A; color: #EA002A; }
.lst-listen-btn-label { line-height: 1; }
.lst-listen-btn[data-playing] svg { animation: lst-listen-pulse 1.2s ease-in-out infinite; }
@keyframes lst-listen-pulse { 0%,100% { opacity: 1; } 50% { opacity: .5; } }
.lst-listen-status {
  font-family: 'Roboto', sans-serif;
  font-size: 0.8rem;
  color: rgba(255,255,255,0.5);
  margin: 10px 0 0;
}
.lst-listen-audio {
  width: 100%;
  margin-top: 12px;
  border-radius: 4px;
}
.lst-listen-transcript {
  margin-top: 14px;
}
.lst-listen-transcript summary {
  font-family: 'Roboto', sans-serif;
  font-size: 0.78rem;
  color: rgba(255,255,255,0.45);
  cursor: pointer;
}
.lst-listen-transcript p {
  font-family: 'Roboto', sans-serif;
  font-size: 0.85rem;
  color: rgba(255,255,255,0.7);
  line-height: 1.5;
  margin: 10px 0 0;
}
.lst-realtor-badge {
  display: inline-flex; align-items: center; gap: 8px;
  background: #EA002A;
  color: #fff;
  padding: 8px 14px;
  border-radius: 4px;
  font-family: 'Raleway', sans-serif;
  font-size: 0.75rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  text-decoration: none;
  white-space: nowrap;
}
.lst-realtor-badge:hover { background: #c8001f; }

/* DDR disclaimer footer block */
.lst-ddr {
  max-width: 1200px;
  margin: 30px auto 60px;
  padding: 24px 20px;
  border-top: 1px solid #1e1e1e;
  font-family: 'Roboto', sans-serif;
  font-size: 0.75rem;
  color: rgba(255,255,255,0.45);
  line-height: 1.6;
}
.lst-ddr p { margin: 0 0 10px; }

/* "Keep Exploring" CTA block — kills dead-end pages. Every listing
   detail and city landing page gets two next-step buttons so users
   always have an obvious path deeper into the site. */
.lst-keep-exploring {
  max-width: 1200px;
  margin: 40px auto 20px;
  padding: 36px 20px;
  border-top: 1px solid #1e1e1e;
  border-bottom: 1px solid #1e1e1e;
  text-align: center;
}
.lst-keep-exploring h2 {
  font-family: 'Raleway', sans-serif;
  font-weight: 900;
  font-size: clamp(1.3rem, 2.5vw, 1.8rem);
  color: #fff;
  margin: 0 0 8px;
  letter-spacing: -0.3px;
}
.lst-keep-exploring p.lst-ke-sub {
  font-family: 'Roboto', sans-serif;
  color: rgba(255,255,255,0.6);
  font-size: 0.95rem;
  margin: 0 0 24px;
}
.lst-cta-row {
  display: flex;
  gap: 14px;
  justify-content: center;
  flex-wrap: wrap;
}
.lst-cta {
  display: inline-block;
  font-family: 'Raleway', sans-serif;
  font-weight: 700;
  font-size: 0.9rem;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  padding: 14px 28px;
  border-radius: 2px;
  text-decoration: none;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
  border: 1px solid transparent;
}
.lst-cta-primary {
  background: #EA002A;
  color: #fff;
}
.lst-cta-primary:hover { background: #c8001f; }
.lst-cta-secondary {
  background: transparent;
  color: #fff;
  border-color: rgba(255,255,255,0.3);
}
.lst-cta-secondary:hover {
  border-color: #EA002A;
  color: #EA002A;
}
@media (max-width: 520px) {
  .lst-cta { width: 100%; text-align: center; }
}

/* ═══ Share button + share modal ═══
   Wired by js/listing-share.js. The button itself sits inside the
   listing title block; the modal is appended to <body> on first open. */
.lst-share-row {
  margin-top: 18px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.lst-share-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: 'Raleway', sans-serif;
  font-weight: 700;
  font-size: 0.85rem;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  padding: 10px 16px;
  background: transparent;
  color: #fff;
  border: 1px solid rgba(255,255,255,0.3);
  border-radius: 2px;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.lst-share-btn:hover { border-color: #EA002A; color: #EA002A; }
.lst-share-btn svg { display: block; }

/* Modal */
.lst-share-modal[hidden] { display: none; }
.lst-share-modal {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
}
.lst-share-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0,0,0,0.78);
}
.lst-share-panel {
  position: relative;
  max-width: 460px;
  width: calc(100% - 32px);
  max-height: calc(100vh - 32px);
  overflow-y: auto;
  background: #1b1b1b;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  padding: 28px 24px 24px;
  font-family: 'Roboto', sans-serif;
  color: #fff;
  box-shadow: 0 30px 80px rgba(0,0,0,0.6);
}
.lst-share-close {
  position: absolute;
  top: 6px;
  right: 6px;
  background: transparent;
  border: 0;
  color: rgba(255,255,255,0.6);
  font-size: 1.8rem;
  line-height: 1;
  padding: 8px 14px;
  cursor: pointer;
  border-radius: 3px;
}
.lst-share-close:hover { color: #fff; background: rgba(255,255,255,0.06); }
.lst-share-panel h3 {
  font-family: 'Raleway', sans-serif;
  font-weight: 900;
  font-size: 1.2rem;
  margin: 0 0 18px;
  letter-spacing: -0.2px;
}
.lst-share-targets {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}
.lst-share-tgt {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 14px 6px;
  background: #262626;
  border: 1px solid #2a2a2a;
  border-radius: 4px;
  color: #fff;
  text-decoration: none;
  font-size: 0.78rem;
  font-family: 'Roboto', sans-serif;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.lst-share-tgt:hover { background: #2d2d2d; border-color: #EA002A; color: #fff; }
.lst-share-tgt svg { display: block; opacity: 0.92; }
.lst-share-copy { font: inherit; }
.lst-share-url {
  font-size: 0.72rem;
  color: rgba(255,255,255,0.55);
  word-break: break-all;
  padding: 10px 12px;
  background: #262626;
  border: 1px solid #2a2a2a;
  border-radius: 3px;
  margin: 0;
  user-select: all;
  font-family: 'Roboto', monospace;
}
.lst-share-toast {
  position: absolute;
  left: 50%;
  bottom: -54px;
  transform: translateX(-50%);
  padding: 10px 18px;
  background: #EA002A;
  color: #fff;
  font-size: 0.85rem;
  font-weight: 600;
  border-radius: 3px;
  white-space: nowrap;
  box-shadow: 0 4px 16px rgba(0,0,0,0.4);
}

/* ═══════════════════════════════════════════════════════════════════
   Price-Change Timeline (Strategic Vision Recommendation #1, 2026-05-14)
   Convention #15 propagation from realestategander-site canonical
   (9d5fc66e2). Convention #91: rules in LISTING_PAGE_CSS.
   ═══════════════════════════════════════════════════════════════════ */
.lst-price-history {
  max-width: 1200px;
  margin: 24px auto 0;
  padding: 0 20px;
}
.lst-price-history-inner {
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 12px;
  padding: 20px 24px;
}
.lst-price-history-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin: 0 0 14px;
}
.lst-price-history-title {
  font-family: 'Raleway', sans-serif;
  font-size: 1.1rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #fff;
  margin: 0;
}
.lst-price-history-delta {
  font-family: 'Roboto', sans-serif;
  font-size: 0.95rem;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 6px;
  white-space: nowrap;
}
.lst-price-history-delta--down {
  background: rgba(234, 0, 42, 0.18);
  color: #ff4d6d;
  border: 1px solid rgba(234, 0, 42, 0.45);
}
.lst-price-history-delta--up {
  background: rgba(212, 175, 55, 0.18);
  color: #d4af37;
  border: 1px solid rgba(212, 175, 55, 0.45);
}
.lst-price-history-timeline {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.lst-price-history-row {
  display: grid;
  grid-template-columns: minmax(140px, 200px) minmax(120px, 1fr) auto;
  align-items: baseline;
  gap: 16px;
  padding: 8px 0;
  font-family: 'Roboto', sans-serif;
}
.lst-price-history-row + .lst-price-history-row {
  border-top: 1px dashed rgba(255,255,255,0.08);
}
.lst-price-history-label {
  font-size: 0.88rem;
  color: rgba(255,255,255,0.6);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 600;
}
.lst-price-history-amount {
  font-size: 1.25rem;
  font-weight: 700;
  font-family: 'Raleway', sans-serif;
}
.lst-price-history-row--from .lst-price-history-amount {
  color: rgba(255,255,255,0.6);
  text-decoration: line-through;
  text-decoration-color: rgba(255,255,255,0.35);
}
.lst-price-history-row--mid .lst-price-history-amount {
  color: rgba(255,255,255,0.75);
}
.lst-price-history-row--to .lst-price-history-amount {
  color: #fff;
  font-size: 1.4rem;
}
.lst-price-history-date {
  font-size: 0.85rem;
  color: rgba(255,255,255,0.45);
  font-style: italic;
}
@media (max-width: 600px) {
  .lst-price-history-row {
    grid-template-columns: 1fr;
    gap: 4px;
    padding: 10px 0;
  }
  .lst-price-history-label {
    font-size: 0.82rem;
  }
  .lst-price-history-amount {
    font-size: 1.15rem;
  }
  .lst-price-history-row--to .lst-price-history-amount {
    font-size: 1.3rem;
  }
}

/* ═══════════════════════════════════════════════════════════════════
   Similar Active Listings ("More homes in <city>") section, 2026-05-14
   Convention #15 propagation from realestategander-site canonical
   (afdb1747). Renders 4-6 card grid at the bottom of every detail page.
   ═══════════════════════════════════════════════════════════════════ */
.lst-similar {
  background: #0c0c0c;
  border-top: 1px solid #1f1f1f;
  border-bottom: 1px solid #1f1f1f;
  padding: 48px 0 24px;
  margin: 60px 0 0;
}
.lst-similar-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 20px;
}
.lst-similar-heading {
  font-family: 'Raleway', sans-serif;
  font-weight: 900;
  font-size: clamp(22px, 3vw, 32px);
  color: #fff;
  margin: 0 0 24px;
  letter-spacing: -0.01em;
}
.lst-similar .lst-card-grid {
  margin: 0 0 24px;
  padding: 0;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
}
.lst-similar-viewall {
  margin: 0;
  font-family: 'Roboto', sans-serif;
  font-size: 0.95rem;
  text-align: right;
}
.lst-similar-viewall a {
  color: #EA002A;
  text-decoration: none;
  font-weight: 700;
}
.lst-similar-viewall a:hover { text-decoration: underline; }

/* Convention #91 fix (2026-09-12, Check #20 full-tree scan — ported from
   realestategander-site/avalonrealestate-site same day). .lst-resource-strip
   renders in the HTML but had no rule anywhere LISTING_PAGE_CSS reaches;
   rewritten (not copied from css/listing-detail.css, which depends on
   --ld-* custom properties defined nowhere reachable here) with concrete
   values matching this page's actual dark theme. .lst-similar-grid is a
   pure marker with no unique style of its own — the real grid layout comes
   from .lst-similar .lst-card-grid above; anchor stub only. */
.lst-resource-strip {
  background: #111;
  border-top: 1px solid #222;
  border-bottom: 1px solid #222;
  padding: 14px 24px;
  text-align: center;
}
.lst-resource-strip p {
  max-width: 1200px; margin: 0 auto;
  font-size: 13px; color: #c8c8c8;
}
.lst-resource-strip a {
  color: #EA002A; font-weight: 600; text-decoration: none;
}
.lst-resource-strip a:hover { text-decoration: underline; }
.lst-similar-grid {}

/* Stage 5 hotfix pattern (Convention #91) — .lst-card* chrome copied
   from INDEX_PAGE_CSS because listing-detail pages load only
   LISTING_PAGE_CSS via head_block. */
.lst-card-grid {
  max-width: 1200px;
  margin: 24px auto 60px;
  padding: 0 20px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 24px;
}
.lst-card {
  background: #111;
  border: 1px solid #1e1e1e;
  border-radius: 4px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: transform .3s, border-color .3s;
  color: inherit;
}
.lst-card:hover { transform: translateY(-4px); border-color: #EA002A; }
.lst-card-link {
  display: block;
  text-decoration: none;
  color: inherit;
}
.lst-card-link:focus-visible {
  outline: 2px solid #EA002A;
  outline-offset: -2px;
}
.lst-card-realtor {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 14px;
  border-top: 1px solid #1e1e1e;
  background: #0d0d0d;
  font-family: 'Roboto', sans-serif;
  font-size: 0.72rem;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  color: rgba(255,255,255,0.55);
  text-decoration: none;
  transition: background .2s, color .2s;
}
.lst-card-realtor:hover,
.lst-card-realtor:focus-visible {
  background: #151515;
  color: #fff;
  outline: none;
}
.lst-card-realtor strong {
  color: #EA002A;
  font-weight: 700;
}
.lst-card-img {
  aspect-ratio: 3 / 2;
  background: #0a0a0a;
  overflow: hidden;
  position: relative;
}
.lst-card-img img {
  width: 100%; height: 100%; object-fit: cover; display: block;
  transition: transform .4s;
}
.lst-card:hover .lst-card-img img { transform: scale(1.05); }
.lst-card-img .lst-card-noimg {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  color: rgba(255,255,255,0.3);
  font-family: 'Raleway', sans-serif; font-weight: 800; font-size: 2rem;
  background: linear-gradient(135deg,#1a1a1a,#0f0f0f);
}
.lst-card-body { padding: 18px 20px 20px; }
.lst-card-price {
  font-family: 'Raleway', sans-serif;
  font-weight: 900;
  font-size: 1.4rem;
  color: #fff;
  margin: 0 0 4px;
}
.lst-card-addr {
  font-family: 'Roboto', sans-serif;
  color: rgba(255,255,255,0.85);
  font-size: 0.95rem;
  font-weight: 500;
  margin: 0 0 2px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.lst-card-city {
  font-family: 'Roboto', sans-serif;
  color: rgba(255,255,255,0.55);
  font-size: 0.85rem;
  margin: 0 0 12px;
}
.lst-card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 18px;
  font-family: 'Roboto', sans-serif;
  color: rgba(255,255,255,0.65);
  font-size: 0.82rem;
  border-top: 1px solid #1e1e1e;
  padding-top: 12px;
}
.lst-card-meta span strong {
  color: #fff; font-weight: 700; margin-right: 4px;
}
.lst-card-mls {
  font-family: 'Roboto', sans-serif;
  color: rgba(255,255,255,0.4);
  font-size: 0.75rem;
  margin-top: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.lst-card-new {
  position: absolute;
  top: 10px; left: 10px;
  background: #EA002A;
  color: #fff;
  font-family: 'Raleway', sans-serif;
  font-weight: 800;
  font-size: 0.7rem;
  padding: 4px 10px;
  border-radius: 2px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}
.lst-card-pending {
  position: absolute;
  top: 10px; left: 10px;
  background: #d97706;
  color: #fff;
  font-family: 'Raleway', sans-serif;
  font-weight: 800;
  font-size: 0.7rem;
  padding: 4px 10px;
  border-radius: 2px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}


/* -- Print-friendly flyer (Batch F3, 2026-08-20) --------------------
   window.print() from the "Print" button in .lst-share-row. Hides nav,
   footer, share/mobile-CTA controls, the sidebar CTA/showing-form
   column, and every embedded iframe (tour, street view, map) -- none
   of those survive onto paper meaningfully. Forces light-on-white
   since the site theme is dark and printing a dark background wastes
   ink. Gallery collapses to the hero + first row (reuses the same
   nth-child cutoff the tablet breakpoint already uses).
   .lst-print-footer is display:none on screen, shown only here. */
@media print {
  nav.nav-main-bar, footer.site-footer, .lst-share-row, .mab-bar,
  .lst-sidebar, .lst-tour-embed, .lst-streetview-img-wrap, .lst-detail-map,
  .skip-nav { display: none !important; }
  .lst-shell { background: #fff !important; color: #000 !important; }
  .lst-shell a { color: #000 !important; text-decoration: underline; }
  .lst-gallery a:nth-child(n+4) { display: none !important; }
  .lst-content { max-width: 100% !important; }
  .lst-main { display: block !important; }
  .lst-print-footer {
    display: block !important; margin: 20px 0; padding-top: 16px;
    border-top: 1px solid #000; font-size: 12px; color: #000;
  }
}
.lst-print-footer { display: none; }


/* ═══════════════════════════════════════════════════════════════════
   Batch D — Distance to hospital / school / grocery / airport (2026-08-20)
   Replaces Walk Score (build_walkscore_section, kept in source but no
   longer called -- its stale cache walkscore.json is left on disk,
   Convention #74/#199, in case a future session revives it). Walk Score
   is structurally wrong for rural NL outports (no sidewalks/transit to
   score, and the cache rotted). Straight-line haversine distances to a
   curated per-community POI list (tools/community-poi.json) are honest,
   zero-API-cost, and never go stale.
   ═══════════════════════════════════════════════════════════════════ */
.lst-distanceto {
  margin: 28px 0;
  padding: 20px;
  background: #0f0f0f;
  border: 1px solid #1f1f1f;
  border-radius: 6px;
}
.lst-distanceto-h {
  margin: 0 0 16px;
  font-family: 'Raleway', sans-serif;
  font-size: 1.1rem;
  font-weight: 700;
  letter-spacing: 0.3px;
  color: #fff;
}
.lst-distanceto-rows {
  display: grid;
  gap: 10px;
}
.lst-distanceto-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: #1a1a1a;
  border: 1px solid #262626;
  border-radius: 4px;
}
.lst-distanceto-icon {
  font-size: 1.3rem;
  width: 28px;
  text-align: center;
  flex-shrink: 0;
}
.lst-distanceto-dist {
  font-family: 'Raleway', sans-serif;
  font-size: 1.05rem;
  font-weight: 800;
  color: #EA002A;
  white-space: nowrap;
}
.lst-distanceto-name {
  font-family: 'Roboto', sans-serif;
  font-size: 0.88rem;
  color: #d0d0d0;
  line-height: 1.3;
}
.lst-distanceto-note {
  margin: 14px 0 0;
  font-family: 'Roboto', sans-serif;
  font-size: 0.76rem;
  color: #8a8a8a;
  text-align: center;
}

@media (max-width: 560px) {
  .lst-distanceto { padding: 14px; }
  .lst-distanceto-row { padding: 8px 10px; gap: 10px; }
  .lst-distanceto-dist { font-size: 0.95rem; }
  .lst-distanceto-name { font-size: 0.82rem; }
}
"""


# ═══════════════════════════════════════════════════════════════════
#  PAGE BUILDERS
# ═══════════════════════════════════════════════════════════════════

def build_keep_exploring(prefix: str, *, city_slug: str | None = None,
                         city_name: str | None = None,
                         commercial: bool = False,
                         href_override: str | None = None,
                         label_override: str | None = None) -> str:
    # commercial=True swaps both CTAs: a warehouse shopper is not
    # looking for "More Homes", and offering them a free HOME
    # evaluation is the wrong product entirely.
    """Two-CTA "no dead end" block for the bottom of every DDF page.

    Mike's rule (2026-04-19): every page must give the user at least two
    obvious next steps. We surface this block right above the DDR
    disclaimer on listing detail pages and city landing pages.

    Behaviour:
        * On a listing DETAIL page (city_slug supplied) — primary CTA goes
          back up one level to the city's listing index ("More Homes in
          {city}"), so the user can keep browsing comparable inventory.
        * On a CITY LANDING page (city_slug=None) — primary CTA widens
          the search to the full MLS® search experience ("Search All
          Lab West Listings").
        * The secondary CTA is the same on both: a soft conversion to the
          free home evaluation page. Anyone shopping listings is also a
          potential seller.

    `prefix` matches the relative-path prefix the caller is using for the
    rest of the page (e.g. "../../" from depth-2 listings, "../" from
    depth-1 city indexes).
    """
    # Primary CTA — context-aware
    # href_override/label_override (2026-07-29): a pending listing whose city
    # has no active index (swept to a 301) must NOT link "More Homes in
    # {city}" at the raw city URL -- the caller passes the SAME already-
    # resolved _city_link/_city_link_label main() uses for the sidebar CTA
    # and mobile bar, rather than re-deriving here (ported from Gander's
    # fix at commit 380bffa7 for the 2026-07-27 site-freeze class of bug).
    if href_override and label_override:
        primary_label = he(label_override)
        primary_href = href_override
        sub_text = "Keep exploring — more options below."
    elif city_slug and city_name:
        primary_label = (f"More Listings in {he(city_name)}" if commercial
                         else f"More Homes in {he(city_name)}")
        primary_href = f"{prefix}listings/{city_slug}/"
        sub_text = "Keep exploring — more options below."
    else:
        primary_label = "Search All Lab West Listings"
        primary_href = f"{prefix}listings/"
        sub_text = "View more MLS listings."

    # Secondary CTA — a soft SELLER conversion on residential. On commercial
    # that offer makes no sense (nobody shopping a plaza wants a home
    # valued), so commercial widens to the commercial inventory instead.
    if commercial:
        secondary_label = "All Commercial Listings"
        secondary_href = f"{prefix}listings/commercial/"
    else:
        if _page_exists("home-value.html"):
            secondary_label = "Free Home Evaluation"
            secondary_href = f"{prefix}pages/home-value.html"
        else:
            secondary_label = "Call Mike: 709-256-7999"
            secondary_href = "tel:7092567999"

    return (
        '<section class="lst-keep-exploring">'
        '<h2>Keep Exploring</h2>'
        f'<p class="lst-ke-sub">{sub_text}</p>'
        '<div class="lst-cta-row">'
        f'<a class="lst-cta lst-cta-primary" href="{primary_href}">{primary_label}</a>'
        f'<a class="lst-cta lst-cta-secondary" href="{secondary_href}">{secondary_label}</a>'
        '</div>'
        '</section>'
    )


def build_gallery(listing: dict) -> str:
    """Render the top photo grid + lightbox-wired wrapper.

    Up to 5 tiles render in the grid (1 hero + 4 smalls). The 5th tile gets
    an '+N more photos' overlay if there are more. The full photo set is
    serialized as JSON in data-lightbox-gallery; js/lightbox.js parses it
    on click and opens a full-screen lightbox at the clicked index.
    On mobile (<=800px) only the hero tile shows + a 'View all N photos'
    button below -- both open the lightbox.

    2026-09-15: ported from Avalon/Gander (Tier 1 fleet photo-display
    check, Mike-reported "images don't seem to be displaying properly" on
    an Avalon listing) -- Goose Bay's build_gallery had never gained the
    lightbox wiring both sibling sites shipped 2026-06-22, so GB listing
    pages had no working "View all N photos" and a dead "+N more" overlay
    (a 50-photo listing rendered exactly 5, with no way to see the rest).
    Same pass adds the low-photo-count layout (lst-gallery--n1..--n4) so
    1-4-photo listings don't leave an empty grid cell.

    Takes the full listing (not just its photo list) for address-aware alt
    text (WCAG 1.1.1 + image SEO) -- was alt="{caption}", and the DDF/IDX
    caption is almost always empty, so every gallery image on this site
    rendered alt="". Mirrors Gander's listing-card fix (2026-06-04) and
    Avalon's matching listing-detail-gallery fix, ported same day (Tier 1
    SEO audit, 2026-06-22).
    """
    photos = listing.get("photos") or []
    if not photos:
        return ""
    _street = (listing.get("street") or "").strip()
    _city = city_display_name(listing.get("city_slug") or "")
    _addr = ", ".join(p for p in (_street, _city, "NL") if p) or "Royal LePage Turner Realty listing"
    visible = photos[:5]
    overflow = len(photos) - len(visible)
    # Low-photo-count layout (2026-09-15): a fixed 5-slot grid leaves empty
    # cells for the ~1 in 6 GB listings with fewer than 5 photos. Below 5,
    # emit a count-specific class so CSS can lay out exactly N tiles with
    # no gap and let non-hero tiles show floor plans/portraits uncropped.
    n_visible = len(visible)
    count_cls = f" lst-gallery--n{n_visible}" if n_visible < 5 else ""
    n = len(photos)
    # Mobile swipe gallery (B3, 2026-09-17): all photos render into the DOM —
    # not just the first 5 — so the mobile scroll-snap strip can swipe through
    # every photo natively (no JS carousel). Cells 6+ carry .lst-gallery-extra,
    # which desktop/tablet CSS keeps display:none (so the existing 5-tile grid
    # is unchanged there) and the mobile media query reveals; since they stay
    # display:none outside mobile, their loading="lazy" images never fetch
    # until a mobile viewport actually scrolls them into view.
    cells = []
    for i, p in enumerate(photos):
        url = p["url"]
        is_last_grid_cell_with_overflow = (i == n_visible - 1) and overflow > 0 and i < 5
        cls_bits = []
        if is_last_grid_cell_with_overflow:
            cls_bits.append("lst-more-overlay")
        if i >= 5:
            cls_bits.append("lst-gallery-extra")
        cls_attr = f' class="{" ".join(cls_bits)}"' if cls_bits else ""
        more_attr = f' data-more="{overflow}"' if is_last_grid_cell_with_overflow else ""
        # LCP optimization (added 2026-05-10): hero (i==0) is the LCP element on
        # listing-detail pages — eager-load with high priority. Tiles 1+ stay
        # lazy to save initial-paint bytes. Pairs with the head_block preload.
        img_attrs = 'fetchpriority="high"' if i == 0 else 'loading="lazy"'
        # onerror: a PhotoCount-derived URL whose R2 upload hasn't landed yet
        # (brand-new listing). The HERO failing collapses the whole gallery to a
        # single "Photos coming soon" placeholder + hides the broken lightbox
        # button (via the .lst-gallery-wrap--noimg class); thumbs just hide.
        # Self-healing once photo-sync lands. (No-Photo gallery bug — 2026-06-04.)
        if i == 0:
            onerr = "this.style.display='none';this.closest('.lst-gallery-wrap').classList.add('lst-gallery-wrap--noimg')"
        else:
            onerr = "this.style.display='none'"
        cells.append(
            f'<a href="{he(url)}" target="_blank" rel="noopener" data-lb-index="{i}"{cls_attr}{more_attr}>'
            f'<img src="{he(url)}" alt="{he(_addr)} — photo {i+1}" {img_attrs} onerror="{onerr}"></a>'
        )

    # Full photo set as JSON for the lightbox (no cap — every DDF photo goes through)
    photos_payload = [
        {"url": p["url"], "caption": p.get("caption") or ""}
        for p in photos
    ]
    photos_json = json.dumps(photos_payload, ensure_ascii=True, separators=(",", ":"))

    cta_label = f"View all {n} photos" if n > 1 else "View photo"

    # Photo counter overlay — swipe mode only (hidden via CSS outside <768px).
    counter_html = (
        f'<div class="lst-gallery-counter" aria-hidden="true">'
        f'<span class="lst-gallery-counter-cur">1</span> / '
        f'<span class="lst-gallery-counter-total">{n}</span></div>'
        if n > 1 else ""
    )
    counter_js = (
        f"""<script>(function(){{
  var wrap = document.currentScript.closest('.lst-gallery-wrap');
  if (!wrap) return;
  var gal = wrap.querySelector('.lst-gallery');
  var cur = wrap.querySelector('.lst-gallery-counter-cur');
  if (!gal || !cur || !('IntersectionObserver' in window)) return;
  var cells = gal.querySelectorAll('a[data-lb-index]');
  var io = new IntersectionObserver(function(entries){{
    entries.forEach(function(e){{
      if (e.isIntersecting) {{
        cur.textContent = (parseInt(e.target.getAttribute('data-lb-index'), 10) || 0) + 1;
      }}
    }});
  }}, {{ root: gal, threshold: 0.6 }});
  cells.forEach(function(c){{ io.observe(c); }});
}})();</script>"""
        if n > 1 else ""
    )

    return (
        '<div class="lst-gallery-wrap">'
        '<div class="lst-gallery-noimg" aria-hidden="true">Photos coming soon</div>'
        f'<div class="lst-gallery{count_cls}" data-lightbox-gallery="{he(photos_json)}">'
        + "".join(cells) +
        '</div>'
        + counter_html +
        f'<button class="lst-view-all-btn" type="button" data-lightbox-open="0" '
        f'aria-label="Open photo gallery">{he(cta_label)}</button>'
        + counter_js +
        '</div>'
    )


# ═══════════════════════════════════════════════════════════════════
#  VIRTUAL TOUR / VIDEO EMBED
# ═══════════════════════════════════════════════════════════════════
#
#  The DDF `virtual_tour` field is a free-text URL populated by the listing
#  agent. In practice it carries YouTube videos (most common), iGuide 3D
#  tours (youriguide.com), Matterport 3D tours, and occasionally junk
#  (Google Drive / Gmail attachment links from agents who pasted the wrong
#  thing). This helper type-dispatches each URL and renders the appropriate
#  iframe, or falls back to a "View virtual tour" outbound button for
#  unrecognized providers. Prefers `virtual_tours` (list, new schema) and
#  falls back to splitting `virtual_tour` (legacy single/comma-joined).








# ═══════════════════════════════════════════════════════════════════
# Google Street View Static — server-side <img> embed
# Strategic Vision §6 — first Maps Platform ship (Convention #15
# propagation from realestategander-site/tools/ddf-generate-pages.py,
# canonical at a657aef07 / 2026-05-14). Byte-symmetric with Gander
# and Avalon except for site-specific call site placement.
# ═══════════════════════════════════════════════════════════════════




_COMMUNITY_POI_CACHE_GLOBAL = None  # populated lazily on first call


def _load_community_poi():
    """Load tools/community-poi.json once per generator run.

    Returns {} on any I/O or parse error -- Convention #74 fail-safe, so
    a missing or corrupt file never breaks the generator; the section
    just renders nothing. Mirrors _load_walkscore_cache()'s
    __file__-relative path resolution.
    """
    global _COMMUNITY_POI_CACHE_GLOBAL
    if _COMMUNITY_POI_CACHE_GLOBAL is not None:
        return _COMMUNITY_POI_CACHE_GLOBAL
    cache_path = Path(__file__).resolve().parent / "community-poi.json"
    if not cache_path.exists():
        _COMMUNITY_POI_CACHE_GLOBAL = {}
        return _COMMUNITY_POI_CACHE_GLOBAL
    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
        _COMMUNITY_POI_CACHE_GLOBAL = {
            k: v for k, v in data.items() if not k.startswith("_")
        }
    except (ValueError, OSError):
        _COMMUNITY_POI_CACHE_GLOBAL = {}
    return _COMMUNITY_POI_CACHE_GLOBAL


def _haversine_km(lat1, lng1, lat2, lng2):
    """Great-circle straight-line distance in km. Standard haversine
    formula -- no external service, no API cost, never stale."""
    r = 6371.0088  # mean Earth radius, km
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2)
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


_POI_DISPLAY = [
    # (key, icon, category label used only in the alt/aria text)
    ("hospital", "\U0001F3E5", "hospital"),
    ("school",   "\U0001F3EB", "school"),
    ("grocery",  "\U0001F6D2", "grocery store"),
    ("airport",  "\u2708\uFE0F", "airport"),
    ("ferry",    "\u26F4", "ferry terminal"),
]


def build_distance_to_section(listing: dict) -> str:
    """Render straight-line distances to the nearest hospital, school,
    grocery store, and (where relevant) airport/ferry -- Batch D,
    2026-08-20. Replaces build_walkscore_section, which is structurally
    wrong for rural NL outports (no sidewalks/transit to score) and
    whose cache had rotted (last refresh months old, thin coverage).

    Sourced from tools/community-poi.json, a curated per-community POI
    list (hand-verified per Convention #32 against NL Health Services /
    NLESD / OpenStreetMap before this ship -- see the file's own
    _source_note). Distances are computed HERE, at generation time, via
    plain haversine great-circle math -- zero API cost, never stale,
    and honestly labeled "approx." since it is straight-line, not a
    driving distance.

    Empty string when:
      - listing has no city_slug, or the slug has no POI entry
      - listing has no lat/lng to measure from
      - the town's POI entry is empty (defensive; shouldn't happen)
    A town/category not in the file simply renders nothing for that
    row -- coverage is deliberately partial (Convention #74), never
    forced or guessed.
    """
    poi_map = _load_community_poi()
    if not poi_map:
        return ""
    slug = str(listing.get("city_slug") or "").strip()
    if not slug or slug not in poi_map:
        return ""
    lat, lng = listing.get("latitude"), listing.get("longitude")
    if lat is None or lng is None:
        return ""
    town_pois = poi_map.get(slug) or {}
    if not town_pois:
        return ""

    rows = []
    for key, icon, _label in _POI_DISPLAY:
        poi = town_pois.get(key)
        if not poi or poi.get("lat") is None or poi.get("lng") is None:
            continue
        dist_km = _haversine_km(lat, lng, poi["lat"], poi["lng"])
        dist_label = f"{dist_km:.1f} km" if dist_km < 10 else f"{dist_km:.0f} km"
        rows.append(
            f'<div class="lst-distanceto-row">'
            f'<span class="lst-distanceto-icon" aria-hidden="true">{icon}</span>'
            f'<span class="lst-distanceto-dist">approx. {dist_label}</span>'
            f'<span class="lst-distanceto-name">to {he(poi["name"])}</span>'
            f'</div>'
        )

    if not rows:
        return ""

    return (
        '<section class="lst-distanceto" aria-labelledby="lst-distanceto-h">'
          '<h2 id="lst-distanceto-h" class="lst-distanceto-h">Nearby essentials</h2>'
          f'<div class="lst-distanceto-rows">{"".join(rows)}</div>'
          '<p class="lst-distanceto-note">Straight-line distances, not driving distance.</p>'
        '</section>'
    )


def build_street_view_section(listing: dict) -> str:
    """Render a Google Street View Static API embedded image of the listing's street.

    Convention #15 propagation from realestategander-site canonical at
    a657aef07 / 2026-05-14. See Gander generator + design spec for full
    rationale (Strategic Vision §6).

    Emit conditions (Convention #74 layered defense):
      - Section omits when GOOGLE_MAPS_API_KEY env var is unset
      - Section omits when listing has no lat/lng (defensive — most do)

    NOTE 2026-05-14: return_error_code=true REMOVED after Gander live
    diagnosis. With that param, Google's "scaffolding" response layer
    strips Content-Type from successful responses, blocking browser
    image render. Trade-off: rural NL outport listings without coverage
    show Google's "Sorry, we have no imagery here" placeholder instead
    of auto-hiding. Acceptable for v1.
    """
    key = _get_google_maps_key()
    if not key:
        return ""
    lat = listing.get("latitude") or listing.get("lat")
    lng = listing.get("longitude") or listing.get("lng")
    if lat is None or lng is None:
        return ""

    # v3 retry 2026-05-15 AM: Maps Embed iframe with referrerpolicy="unsafe-url".
    # Convention #15 from Gander v3 ship.
    iframe_src = (
        f"https://www.google.com/maps/embed/v1/streetview"
        f"?key={key}"
        f"&location={lat},{lng}"
        f"&heading=0&pitch=0&fov=80"
    )
    return (
        '<section class="lst-streetview" aria-labelledby="lst-streetview-h">'
          '<h2 id="lst-streetview-h" class="lst-streetview-h">Street view</h2>'
          '<div class="lst-streetview-img-wrap">'
            f'<iframe src="{iframe_src}" '
              'loading="lazy" '
              'referrerpolicy="unsafe-url" '
              'allowfullscreen '
              'title="Interactive Street View — drag to pan, click arrows to walk down the street"></iframe>'
            '<button type="button" class="lst-streetview-tap" '
              'aria-label="Tap to explore Street View" '
              'onclick="this.parentNode.classList.add(\'is-live\')">'
              '<svg viewBox="0 0 48 48" fill="none" aria-hidden="true">'
                '<circle cx="24" cy="24" r="22" fill="rgba(0,0,0,0.55)" stroke="#fff" stroke-width="2"/>'
                '<path d="M19 15l14 9-14 9z" fill="#fff"/>'
              '</svg>'
              '<span>Tap to explore</span>'
            '</button>'
          '</div>'
          '<p class="lst-streetview-attr">'
            'Imagery &copy; Google &mdash; '
            f'<a href="https://www.google.com/maps/@{lat},{lng},3a,75y,0h,90t/data=!3m4!1e1" '
            'target="_blank" rel="noopener noreferrer">Open full panorama in Google Maps</a>'
          '</p>'
        '</section>'
    )


def build_tour_section(listing: dict, address: str) -> str:
    """Render the Virtual tour section, or empty string if no usable URLs."""
    raw = listing.get("virtual_tours") or listing.get("virtual_tour")
    urls = _split_tour_urls(raw)
    if not urls:
        return ""
    embeds = [_render_tour_embed(u) for u in urls]
    # GSC "No thumbnail URL provided" fix (2026-09-14): a VideoObject block
    # per YouTube tour URL so Google has a real thumbnail to index against.
    video_jsonld = "".join(_youtube_tour_video_jsonld(u, address) for u in urls)
    return (
        '<section class="lst-section lst-tour-section">'
        '<h2>Virtual tour</h2>'
        + "".join(embeds) +
        '</section>'
        + video_jsonld
    )




def _format_idx_multivalue(s):
    """Convert RETS comma-separated multi-value to display format.

    Examples:
        'Electric,Heat Pump,Radiant' -> 'Electric, Heat Pump, Radiant'
        'Concrete,Partially Developed' -> 'Concrete, Partially Developed'
        'Attached,Storage Shed,Wired' -> 'Attached, Storage Shed, Wired'

    Track A.2 enrichment 2026-05-08 (Convention #15 propagation from
    realestategander-site canonical at 971aec15).
    """
    if not s:
        return ""
    return ", ".join(p.strip() for p in str(s).split(",") if p.strip())


_GB_SPEC_GROUPS = [
    ("Property",            ["Property Type", "Status", "MLS\u00ae", "Postal Code"]),
    ("Structure & Systems", ["Heating", "Foundation", "Garage", "Builder"]),
    ("Listing Info",        ["Elementary School", "Secondary School", "Listed", "Updated"]),
]


def _grouped_spec_rows(rows, groups):
    """Group flat (label, value) spec rows under labeled sub-headers.

    Fail-safe: <3 non-empty groups -> None so the caller emits its flat grid
    (sparse/land listings never get orphan headers). Unmapped labels join the
    FIRST group rather than vanish.
    """
    if not rows:
        return None
    by_label = {}
    for pair in rows:
        by_label.setdefault(pair[0], []).append(pair)
    mapped, used = [], set()
    for title, labels in groups:
        picked = []
        for lab in labels:
            for pair in by_label.get(lab, []):
                picked.append(pair); used.add(id(pair))
        if picked:
            mapped.append((title, picked))
    leftovers = [p for p in rows if id(p) not in used]
    if leftovers and mapped:
        mapped[0] = (mapped[0][0], mapped[0][1] + leftovers)
    if len([g for g in mapped if g[1]]) < 3:
        return None
    return mapped


def build_details_grid(listing: dict) -> str:
    rows = []
    if listing.get("property_subtype"): rows.append(("Property Type", listing["property_subtype"]))
    # One availability vocabulary (D-1009-77): Available / Conditional / Pending.
    if listing.get("status"): rows.append(("Status", _lr.status_label(listing["status"])))
    if listing.get("mls"): rows.append(("MLS®", listing["mls"]))
    # Track A.2 enrichment from IDX/VOW overlay (Convention #21 graceful — only
    # surfaces when the matching IDX record exists AND the target field is populated).
    # NL-specific consumer concerns surfaced here per Track A spec sign-off 2026-05-07.
    if listing.get("idx_heating"):
        rows.append(("Heating", _format_idx_multivalue(listing["idx_heating"])))
    if listing.get("idx_foundation"):
        rows.append(("Foundation", _format_idx_multivalue(listing["idx_foundation"])))
    if listing.get("idx_garage_type"):
        garage_str = _format_idx_multivalue(listing["idx_garage_type"])
        if listing.get("idx_garage_sqft"):
            garage_str += f" ({listing['idx_garage_sqft']} sq ft)"
        rows.append(("Garage", garage_str))
    # Track A.2c — Schools (Decision F = a, plain text in Property Details)
    if listing.get("idx_elementary_school"):
        rows.append(("Elementary School", listing["idx_elementary_school"]))
    if listing.get("idx_secondary_school"):
        rows.append(("Secondary School", listing["idx_secondary_school"]))
    if listing.get("postal_code"): rows.append(("Postal Code", fmt_postal(listing["postal_code"])))
    if listing.get("list_date"): rows.append(("Listed", listing["list_date"][:10]))
    if listing.get("modification_timestamp"): rows.append(("Updated", listing["modification_timestamp"][:10]))
    _grouped = _grouped_spec_rows(rows, _GB_SPEC_GROUPS)
    if _grouped:
        _cells = "".join(
            f'<h3 class="lst-spec-group-title">{he(_t)}</h3>' + "".join(
                f'<div class="lst-row"><span>{he(k)}</span><span>{he(v)}</span></div>'
                for k, v in _rs)
            for _t, _rs in _grouped
        )
        return f'<div class="lst-details-grid">{_cells}</div>'
    cells = "".join(
        f'<div class="lst-row"><span>{he(k)}</span><span>{he(v)}</span></div>'
        for k, v in rows
    )
    return (
        '<section class="lst-section">'
        '<h2>Property Details</h2>'
        f'<div class="lst-details-grid">{cells}</div>'
        '</section>'
    )


def _fmt_idx_money(s):
    """Format a RETS dollar value like '657.00' as '$657'.

    Returns None for empty/zero values so caller can skip the row.
    Drops trailing .00 for clean display ($657 not $657.00); keeps
    cents when they're meaningful ($8.85 stays as $8.85).

    Track A.2b: CondoFee + MobileLeasedLandFees come through as
    numeric strings; '0.00' sentinel for "no condo fee" should not
    render a row.
    """
    if not s:
        return None
    try:
        v = float(str(s).strip())
    except (ValueError, TypeError):
        return None
    if v <= 0:
        return None
    if v == int(v):
        return f"${int(v):,}"
    return f"${v:,.2f}"


def build_features_section(listing: dict) -> str:
    """Port of Gander's Panel-4 "Features" logic (2026-07-29, task #80),
    adapted from a tab panel to a flat section matching this site's
    single-scroll listing-detail layout. Reads the same 4 IDX overlay
    fields Gander does (Features/InteriorFeatures/LandFeatures/Services,
    now wired into this site's own _IDX_FIELD_MAP + idx-ingest.py allowlist
    in the same port). Convention #19: renders nothing when none of the 4
    fields are populated, rather than an empty section."""
    feature_cards = []
    for label, key in [
        ("Included appliances &amp; features", "idx_features"),
        ("Interior features", "idx_interior_features"),
        ("Land features", "idx_land_features"),
        ("Services", "idx_services"),
    ]:
        val = listing.get(key, "")
        if val:
            items = [s.strip() for s in val.split(",") if s.strip()]
            if items:
                chips = "".join(f'<span class="lst-feature-chip">{he(it)}</span>' for it in items)
                feature_cards.append(f'<div class="lst-feature-chips">{chips}</div>')
    if not feature_cards:
        return ""
    return (
        '<section class="lst-section">'
        '<h2>Features</h2>'
        + "".join(feature_cards) +
        '</section>'
    )


def build_operating_costs_section(listing: dict) -> str:
    """Track A.2b — Utility responsibility + fees from the IDX overlay.

    Section hides entirely when zero of the 5 fields populated (Convention
    #19 + Decision C from Track A spec sign-off 2026-05-07).

    NLAR field semantics (verified from real cache values 2026-05-07):
    - HeatingBill / WaterBill / ElectricBill = string 'Tenant' or 'Owner'
      indicating who pays the utility (mostly commercial listings)
    - CondoFee = monthly dollar amount; '0.00' sentinel = "no condo fee"
    - MobileLeasedLandFees = monthly dollar amount for trailer-park leases
    """
    rows = []

    # Utility responsibility (Tenant/Owner) — mostly commercial listings
    for label, key in [
        ("Heating Cost",     "idx_heating_bill"),
        ("Water Cost",       "idx_water_bill"),
        ("Electricity Cost", "idx_electric_bill"),
    ]:
        v = listing.get(key)
        if v and str(v).strip():
            rows.append((label, f"Paid by {str(v).strip()}"))

    # Dollar amounts — only render when > 0 (Decision C)
    cf = _fmt_idx_money(listing.get("idx_condo_fee"))
    if cf:
        rows.append(("Condo Fee", f"{cf}/month"))

    mlf = _fmt_idx_money(listing.get("idx_mobile_lease_fee"))
    if mlf:
        rows.append(("Mobile Land Lease", f"{mlf}/month"))

    # Decision C: hide entire section if zero rows
    if not rows:
        return ""

    cells = "".join(
        f'<div class="lst-row"><span>{he(k)}</span><span>{he(v)}</span></div>'
        for k, v in rows
    )
    return (
        '<section class="lst-section">'
        '<h2>Utilities &amp; Fees</h2>'
        f'<div class="lst-details-grid">{cells}</div>'
        '</section>'
    )


def _load_pending_listings(script_dir, site_root):
    """Firm ("sale pending") listings, projected into Listing shape.

    Source is tools/idx-cache/pending-listings.json, written by
    pending-from-deals.py from the deal spine + git-recovered listing pages --
    NOT from the IDX feed, which by NLAR policy no longer carries these.

    Projected through idx-project-to-ddf-shape.project_row so a pending row is
    structurally identical to an active one (city_slug / slug / url_path /
    photos), which is what lets build_listing_page render it unchanged.

    Convention #74: any failure here returns [] and the generator proceeds
    exactly as it does today. A missing or malformed pending file must never
    cost us the active site.
    """
    import importlib.util
    pending_path = script_dir / "idx-cache" / "pending-listings.json"
    if not pending_path.exists():
        return []
    try:
        raw = json.loads(pending_path.read_text())
        rows = raw.get("rows") or []
        if not rows:
            return []
        proj_path = script_dir / "idx-project-to-ddf-shape.py"
        spec = importlib.util.spec_from_file_location("_idxproj", proj_path)
        proj = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(proj)
        out = []
        for r in rows:
            try:
                lst = proj.project_row(r, site_root)
            except Exception:
                continue
            if not lst.get("mls") or not lst.get("city_slug") or not lst.get("slug"):
                continue
            # The badge machinery keys on status: listings-index.js:isPending()
            # matches /pending|under contract|conditional|stfrm|stcos/i, and
            # build_client_full_l1_section already renders a "Firm Sale,
            # Awaiting Close" amber badge for a firm status. Setting it here is
            # what lights up both surfaces without touching either renderer.
            lst["status"] = "Firm Sale - Pending"
            lst["_pending"] = True
            lst["_close_date"] = r.get("_close_date") or ""
            # 2026-08-05 (1 Gatty Place, MLS 1298186, round 3): project_row()
            # doesn't carry the raw-Matrix field name match_turner_agent()
            # reads -- so every pending detail page rendered since the
            # 2026-07-28 pending-page rollout lost its "Listed by <Name>"
            # agent card and fell back to the generic team byline, even for
            # listings whose real agent IS known (pending-from-deals.py now
            # populates ListAgentFullName from the deal spine -- see that
            # file's own 2026-08-05 fix). Stamp it here so match_turner_agent
            # can resolve the same way it does for an active listing.
            lst["idx_list_agent_full_name"] = (r.get("ListAgentFullName") or "").strip()
            out.append(lst)
        return out
    except Exception as e:
        print(f"[GEN] WARN: pending listings unreadable ({e}) — continuing without them")
        return []



def _pending_banner(listing: dict) -> str:
    """Full-width SALE PENDING notice, or "" for an ordinary active listing.

    Deliberately states only what we can source. There is no reliable firm DATE
    anywhere in the stack (pending-from-deals documents why it emits none), so
    this promises a status, not a timeline.
    """
    # D-1009-77 (2026-10-09, redesign's call): the full-width SALE PENDING
    # banner is dropped. The page's one availability label is the Pending
    # badge beside the price (.lst-status, tools/_listing_terms.py); redesign
    # adds its one-sentence note there. The text below is kept for reference.
    return ""
    if not listing.get("_pending"):
        return ""
    return (
        '<div style="background:#fff8ed;border:1px solid #f0c98a;'
        'border-left:5px solid #d97706;border-radius:8px;padding:14px 18px;'
        'margin:0 0 18px;">'
        '<div style="font-weight:700;color:#92400e;font-size:1.02rem;'
        'letter-spacing:.02em;">SALE PENDING</div>'
        '<div style="color:#7c4a11;font-size:.92rem;line-height:1.5;margin-top:4px;">'
        'An offer on this property has been accepted and conditions are removed. '
        'It has not closed yet, so the details below are the last published '
        'listing information.</div>'
        '</div>'
    )



def _crumb_city_html(listing: dict) -> str:
    """Breadcrumb city crumb — a LINK only when that city's index exists.

    A pending-only city (its last active listing went firm) has had its index
    swept to a permanent 301, so linking there is a real broken link. On
    2026-07-27 that failed the generator's own self-check, and because the commit
    step never runs after a failed regen the whole Gander site froze for ~43h
    until Mike noticed a new listing had never appeared.

    This was the THIRD emitter of the same link. The sidebar CTA card and the
    mobile CTA bar were fixed first and the build still failed on the identical
    three pages — the breadcrumb is where the ".../index.html" form in the error
    message came from. Conv #116: audit EVERY emitter, and when a fix does not
    change the error, let the failing string tell you which one you missed.

    Plain unlinked text is the right answer for a breadcrumb: it keeps the
    hierarchy readable without pointing at a page that is not there.
    """
    name = he(city_display_name(listing["city_slug"]))
    orphaned = (listing.get("_pending")
                and listing.get("_city_link") == "../../listings/")
    if orphaned:
        return f'<span style="color:rgba(255,255,255,0.5);">{name}</span> &rsaquo; '
    return (f'<a href="../../listings/{listing["city_slug"]}/index.html" '
            f'style="color:rgba(255,255,255,0.5);">{name}</a> &rsaquo; ')



def build_inquiry_card(listing: dict) -> str:
    """Sidebar inquiry CTA — wires the existing BoldTrailForms.listingInquiry handler.

    Listing-agent recognition (Convention #15 byte-symmetric port from
    stjohns-site 6ed6ca357 / 2026-05-20): when the listing's IDX agent
    matches a Turner team member, swap the generic team byline for a full
    agent card (photo + cell + email + profile link). Falls back to the
    HVGB office card on no-match (Convention #74 fail-safe). Form
    data-agent-email populated for Tier 1.1 fallback chain routing.
    """
    # ── Sale pending: no showing form ────────────────────────────────
    # An accepted offer means a showing request wastes everyone's time.
    # Offer what's actually useful instead: similar active homes, and a
    # direct line for "call me if it falls through". Early return so the
    # active path below is untouched and its output stays byte-identical.
    if listing.get("_pending"):
        _prec = match_turner_agent(listing.get("idx_list_agent_full_name"))
        _pd = (_prec["phone"] if _prec else "7092567999")
        _pname = he(_prec["name"] if _prec else "Mike Turner, Broker")
        _city = city_display_name(listing["city_slug"])
        return f"""
<div class="lst-cta-card">
  <h3>This one\'s under contract</h3>
  <p style="margin:0 0 14px;color:#b9b9b9;font-size:.9rem;line-height:1.5;">An offer has been accepted, so it\'s no longer available for showings. If something like it is what you\'re after, we can show you what else is on the market in {he(_city)}.</p>
  <a href="{he(listing.get('_city_link') or f"../../listings/{listing['city_slug']}/")}" class="xx-btn xx-btn-primary" style="display:block;text-align:center;">{he(listing.get('_city_link_label') or f"See active homes in {_city}")}</a>
</div>
<div class="lst-cta-card">
  <h3>Want to be next?</h3>
  <p>Deals do fall through, and similar homes come up. Tell {_pname} what you\'re looking for.</p>
  <a href="tel:{he(_pd)}" class="xx-btn xx-btn-primary" style="display:block;text-align:center;">{he(_fmt_phone(_pd))}</a>
</div>
"""

    address = f"{listing['street']}, {city_display_name(listing['city_slug'])} NL"

    agent_record = match_turner_agent(listing.get("idx_list_agent_full_name"))
    if agent_record:
        agent_name      = he(agent_record["name"])
        agent_slug      = he(agent_record["slug"])
        agent_photo     = he(agent_record["photo"])
        agent_phone     = agent_record["phone"]
        agent_phone_fmt = he(_fmt_phone(agent_phone))
        agent_email     = he(agent_record["email"])
        agent_title     = he(agent_record["title"])
        agent_team      = he(agent_record["team"])
        form_agent_email = agent_record["email"]
        # LCA-F per-territory routing (Convention #15 port 2026-05-20).
        form_agent_uuid = boldtrail_id_for_agent(agent_record["slug"])
        primary_card = f"""
<div class="lst-cta-card lst-cta-agent">
  <div class="lst-cta-agent-row">
    <img class="lst-cta-agent-photo" src="{agent_photo}" alt="{agent_name}"
         width="80" height="80" loading="lazy">
    <div class="lst-cta-agent-meta">
      <p class="lst-team-eyebrow">Listed by</p>
      <p class="lst-cta-agent-name">{agent_name}</p>
      <p class="lst-cta-agent-title">{agent_title}</p>
      <p class="lst-cta-agent-team">Royal LePage Turner Realty &middot; {agent_team}</p>
    </div>
  </div>
  <div class="lst-cta-agent-contact">
    <a href="tel:{he(agent_phone)}" class="lst-cta-agent-tel">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.88.37 1.73.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c1.08.33 1.93.57 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
      {agent_phone_fmt}
    </a>
    <a href="mailto:{agent_email}" class="lst-cta-agent-email">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
      Email
    </a>
  </div>
</div>"""
        call_direct_text = f"Prefer to talk? Reach {agent_name} direct."
        call_direct_tel = he(agent_phone)
        call_direct_display = agent_phone_fmt
    else:
        # Lab West (D-1012-28/33): every inquiry on this site names Mike Turner, Broker of Record. For
        # a listing another brokerage holds he is the contact, never "Listed by" (the listing brokerage
        # is shown separately, as CREA requires).
        _mike = TURNER_AGENT_CARD.get("Mike Turner") or {}
        form_agent_email = _mike.get("email", "")
        form_agent_uuid = ""
        primary_card = f"""
<div class="lst-cta-card lst-cta-agent">
  <div class="lst-cta-agent-row">
    <img class="lst-cta-agent-photo" src="{he(_mike.get('photo', ''))}" alt="Mike Turner"
         width="80" height="80" loading="lazy">
    <div class="lst-cta-agent-meta">
      <p class="lst-team-eyebrow">Questions about this home?</p>
      <p class="lst-cta-agent-name">Mike Turner</p>
      <p class="lst-cta-agent-title">{he(_mike.get('title', 'Broker of Record'))}</p>
      <p class="lst-cta-agent-team">Royal LePage Turner Realty</p>
    </div>
  </div>
  <div class="lst-cta-agent-contact">
    <a href="tel:7092567999" class="lst-cta-agent-tel">709-256-7999</a>
    <a href="mailto:{he(_mike.get('email', 'miketurner@royallepage.ca'))}" class="lst-cta-agent-email">Email</a>
  </div>
</div>"""
        call_direct_text = "Prefer to talk? Reach Mike Turner, Broker, direct."
        call_direct_tel = "7092567999"
        call_direct_display = "709-256-7999"

    # Two-tab inquiry card — Book a Showing (default) / Ask a Question.
    # Convention #15 port from Gander (2026-06-19). Both forms POST to the same
    # BoldTrail lead channel; the showing form tags "Showing Request" for triage.
    team_name_attr = agent_record["team"] if agent_record else "Royal LePage Turner Realty"
    city_name = he(city_display_name(listing['city_slug']))
    list_price_display = he(fmt_price(listing.get('list_price'), listing=listing))
    # ── Commercial: a fitted ask instead of the residential two-tab card ──
    # Reuses the commercialInquiry form + COMMERCIAL_CONTACT shipped
    # 2026-07-24 for the /listings/commercial/ band: it asks intent, use
    # type, square footage and timeline rather than a showing date, and
    # routes through the same buildAssignees chain (no JS change needed).
    # Early return so the residential path below is untouched.
    if _is_commercial(listing):
        _cc = COMMERCIAL_CONTACT
        _cc_rec = TURNER_AGENT_CARD.get((_cc.get("agent_name") or "").strip()) or {}
        if agent_record:
            # The Turner listing agent owns the lead; COMMERCIAL_CONTACT is
            # only the fallback for listings no Turner agent is on.
            _c_name, _c_slug = agent_record["name"], agent_record["slug"]
            _c_email = agent_record["email"]
            _c_phone = _fmt_phone(agent_record["phone"])
        else:
            _c_name = (_cc.get("display_name") or _cc.get("agent_name")
                       or "our commercial team")
            _c_slug = _cc_rec.get("slug") or ""
            _c_email = form_agent_email or _cc_rec.get("email") or ""
            _d = "".join(ch for ch in (_cc_rec.get("phone") or "") if ch.isdigit())
            _c_phone = (f"{_d[0:3]}-{_d[3:6]}-{_d[6:10]}" if len(_d) == 10
                        else (_cc.get("office_phone") or ""))
        _c_first = (_c_name.split(" ")[0] if _c_name else "us")
        _c_tel = "".join(ch for ch in _c_phone if ch.isdigit())
        return f"""
{primary_card}
<div class="lst-cta-card">
  <h3>Request the Property Package</h3>
  <p style="margin:0 0 14px;color:#b9b9b9;font-size:.9rem;line-height:1.5;">Tell {he(_c_first)} what you need &mdash; including whether this one actually fits.</p>
  <div id="lst-commercial-inquiry"
       data-listing-address="{he(address)}"
       data-listing-city="{city_name}"
       data-listing-price="{list_price_display}"
       data-mls-number="{he(listing['mls'])}"
       data-agent-name="{he(_c_name)}"
       data-agent-email="{he(_c_email)}"
       data-agent-uuid="{he(form_agent_uuid)}"
       data-agent-slug="{he(_c_slug)}"
       data-agent-phone="{he(_c_phone)}"
       data-team-email="{he('miketurner@royallepage.ca')}"
       data-market="{he(_cc.get('market') or '')}"></div>
</div>
<div class="lst-cta-card">
  <h3>Call Direct</h3>
  <p>Commercial moves on conversations, not forms. Reach {he(_c_name)} direct.</p>
  <a href="tel:{he(_c_tel)}" class="xx-btn xx-btn-primary" style="display:block;text-align:center;">{he(_c_phone)}</a>
</div>
"""

    # Item 6 (2026-09-30): "Ask [agent] for a personal review" third tab, built client-side from these attributes
    # (BoldTrailForms.personalReview). Listing agent when one is of record, else this site's own team label.
    review_attrs = ""
    if PERSONAL_REVIEW_MODE in ("preview", "on"):
        _rv_agent = agent_record["name"] if agent_record else ""
        _rv_first = _rv_agent.split()[0] if _rv_agent else ""
        review_attrs = (
            f' data-review="{PERSONAL_REVIEW_MODE}"'
            f' data-review-agent="{he(_rv_agent)}" data-review-first="{he(_rv_first)}"'
            f' data-review-teamlabel="{he(PERSONAL_REVIEW_TEAM_LABEL)}"'
            f' data-review-address="{he(address)}" data-review-city="{city_name}"'
            f' data-review-mls="{he(listing["mls"])}" data-review-team="{he(team_name_attr)}"'
            f' data-review-agent-email="{he(form_agent_email)}" data-review-agent-uuid="{he(form_agent_uuid)}"'
            f' data-review-team-email="miketurner@royallepage.ca"'
        )
    return f"""
{primary_card}
<div class="lst-cta-card"{review_attrs}>
  <h3>Interested in this property?</h3>
  <div class="lst-rf-tabs" role="tablist">
    <button class="lst-rf-tab active" type="button" data-rf-tab="showing" role="tab" aria-selected="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
      Book a Showing
    </button>
    <button class="lst-rf-tab" type="button" data-rf-tab="inquiry" role="tab" aria-selected="false">
      Ask a Question
    </button>
  </div>
  <div id="lst-showing-form" class="lst-rf-panel" data-rf-panel="showing" role="tabpanel"
       data-listing-address="{he(address)}"
       data-listing-city="{city_name}"
       data-listing-price="{list_price_display}"
       data-team-name="{he(team_name_attr)}"
       data-mls-number="{he(listing['mls'])}"
       data-agent-email="{he(form_agent_email)}"
       data-agent-uuid="{he(form_agent_uuid)}"
       data-team-email="miketurner@royallepage.ca"></div>
  <div id="lst-inquiry-form" class="lst-rf-panel" data-rf-panel="inquiry" role="tabpanel" hidden
       data-listing-address="{he(address)}"
       data-team-name="{he(team_name_attr)}"
       data-mls-number="{he(listing['mls'])}"
       data-agent-email="{he(form_agent_email)}"
       data-agent-uuid="{he(form_agent_uuid)}"
       data-team-email="miketurner@royallepage.ca"></div>
</div>
<div class="lst-cta-card">
  <h3>Call Direct</h3>
  <p>{call_direct_text}</p>
  <a href="tel:{call_direct_tel}" class="xx-btn xx-btn-primary" style="display:block;text-align:center;">{call_direct_display}</a>
</div>
"""


def _has_local_photos_meta(mls: str, site_root: Path) -> dict | None:
    """Return parsed .meta.json for this MLS if photos are on disk, else None.

    Fails open on any error (missing file, malformed JSON, IO error) — a
    listing without local photos simply falls through to DDF URLs.
    """
    if not mls:
        return None
    meta_path = site_root / "images" / "listings" / mls / ".meta.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _apply_local_photos(listings: list[dict], site_root: Path) -> int:
    """Swap each listing's photos list to local paths when on-disk photos exist.

    For each listing whose `images/listings/<MLS>/.meta.json` is present
    AND whose `001.jpg` is also on disk, replaces `listing["photos"]`
    with a list of `{"url": "/images/listings/<MLS>/NNN.jpg", "caption":
    "", "preferred": (N==1)}` dicts and sets `listing["_local_photos"]
    = True`. Also stores `listing["_hero_url"]` if `hero.jpg` exists
    (drives og:image / twitter:image — see head_block / build_city_page
    / build_filtered_rollup_page og_image construction).

    Returns the count of listings swapped to local photos (telemetry).

    Idempotent. Mutates in place. Fails open per listing — if anything
    looks off (meta missing photo_count, 001.jpg absent), the listing
    stays on DDF photos rather than rendering with broken gallery URLs.
    """
    # R2 mode emits absolute URLs against R2_BASE_URL; disk mode emits
    # root-relative local paths (existing contract). The .meta.json file
    # stays on disk in both modes — it's the incremental sync tracker.
    # In R2 mode the 001.jpg + hero.jpg existence checks are skipped (we
    # trust .meta.json since the bytes live in R2 not on local disk).
    r2_mode = bool(R2_BASE_URL)

    swapped = 0
    for lst in listings:
        mls = str(lst.get("mls", "")).strip()
        meta = _has_local_photos_meta(mls, site_root)
        if not meta:
            continue
        photo_count = 0
        try:
            photo_count = int(meta.get("photo_count") or 0)
        except (TypeError, ValueError):
            photo_count = 0
        if photo_count < 1:
            continue

        if r2_mode:
            # R2 URL scheme: {R2_BASE_URL}/{R2_SITE_SLUG}/listings/<MLS>/<NNN>.jpg
            url_prefix = f"{R2_BASE_URL}/{R2_SITE_SLUG}/listings/{mls}"
            local_photos = [
                {
                    "url": f"{url_prefix}/{i:03d}.jpg",
                    "caption": "",
                    "preferred": (i == 1),
                }
                for i in range(1, photo_count + 1)
            ]
            lst["photos"] = local_photos
            lst["_local_photos"] = True
            # Trust .meta.json hero_generated flag in R2 mode (no disk check).
            if meta.get("hero_generated"):
                lst["_hero_url"] = f"{url_prefix}/hero.jpg"
            swapped += 1
            continue

        # Disk mode (legacy / fail-safe). Defensive: confirm 001.jpg is
        # actually on disk. The .meta.json could be from an aborted sync
        # that wrote meta before any image part landed. Without this check
        # the gallery would emit 404 URLs.
        listing_dir = site_root / "images" / "listings" / mls
        if not (listing_dir / "001.jpg").exists():
            continue
        local_photos = [
            {
                "url": f"/images/listings/{mls}/{i:03d}.jpg",
                "caption": "",
                "preferred": (i == 1),
            }
            for i in range(1, photo_count + 1)
        ]
        lst["photos"] = local_photos
        lst["_local_photos"] = True
        # hero.jpg is the 1200×630 social-share crop produced by PIL
        # (or byte-copy of 001.jpg as PIL fallback). Used for og:image /
        # twitter:image only — gallery still uses photos[0]=001.jpg.
        if (listing_dir / "hero.jpg").exists():
            lst["_hero_url"] = f"/images/listings/{mls}/hero.jpg"
        swapped += 1
    return swapped


def _abs_photo_url(url: str) -> str:
    """If url is root-relative ('/images/...'), prefix with SITE_ORIGIN.

    Used for og:image, twitter:image, and Schema.org JSON-LD `image` —
    all three demand absolute URLs. Within-page <img src=> tags can stay
    root-relative (browsers resolve fine against the page origin).
    """
    if url.startswith("/"):
        return f"{SITE_ORIGIN}{url}"
    return url



def build_attribution(listing: dict) -> str:
    """Brokerage attribution — NLAR direct feed only (post-IDX cutover 2026-05-19).

    Per Angie Liang's locked guidance 2026-05-11:
      ``Listing courtesy of [ListOfficeName] — NLAR MLS® #[MLSNumber]``.
    No NLAR badge/logo required. No REALTOR.ca badge — the DDF
    "Powered by REALTOR.ca" requirement stops applying once we're on the
    NLAR direct IDX/VOW feed.

    Pre-2026-05-19 history: this function had a DDF-fallback path that
    emitted ``Listed by <brokerage> + Powered by REALTOR.ca`` per CREA
    DDR Rule 6(a)(i). That code path was retired alongside the DDF→IDX
    cutover at 52560d0d3 (2026-05-19 morning). Gander is now 100% on
    NLAR direct; the fallback was dead code. Mike's directive
    2026-05-19 evening: "we no longer use the CREA DDF for anything."

    Source-of-truth field: idx_office_name (populated by IDX overlay from
    RETS ListOfficeName field — see _IDX_FIELD_MAP). Falls back to
    listing_brokerage when the overlay hasn't matched a row yet
    (transient race for very-fresh listings). Final fallback is a
    generic NLAR-member-brokerage string for the edge case where
    neither populates.
    """
    office = (
        listing.get("idx_office_name")
        or listing.get("listing_brokerage")
        or "an NLAR MLS® member brokerage"
    )
    return f"""
<div class="lst-attribution">
  <p class="lst-attribution-text">Listing courtesy of <strong>{he(office)}</strong> &mdash; NLAR MLS&reg; #{he(listing['mls'])}</p>
</div>
"""


def build_listen_section(listing: dict, address: str) -> str:
    """"Hear about this home" -- Ship 4 port, 2026-09-11 (fleet rollout of
    Gander's 2026-09-10 ship, ~/.claude/plans/now-that-we-have-polymorphic-
    wolf.md). Returns "" (no markup at all) whenever the feature is off,
    unconfigured, or this listing is out of scope -- Conv #74: an
    unconfigured/gated build must change NOTHING, not render a broken or
    hidden button.

    Scope (LISTING_AUDIO_SCOPE=own|all, default own): "own" narrates only
    Turner's own listings (is_turner(), the same fleet-canonical check
    build_attribution's office line effectively mirrors) -- the DDF/IDX
    display licence for narrating ANOTHER brokerage's PublicRemarks text
    aloud has not been confirmed with CREA/NLAR (plan's own compliance
    note); "all" is not switched on until that's answered.

    The script text is embedded TWICE: once in a `data-script` attribute
    (what the client JS actually POSTs -- HTML-attribute-escaped, so it
    round-trips exactly) and once in a visible <details> transcript (the
    plan's compliance rule: "the page text is the transcript"). Both are
    the SAME string; only the attribute is authoritative for what gets
    signed/verified.
    """
    if LISTING_AUDIO_MODE not in ("preview", "on"):
        return ""
    if not LISTING_AUDIO_HMAC:
        return ""
    if LISTING_AUDIO_SCOPE == "own":
        office_for_scope = listing.get("idx_office_name") or listing.get("listing_brokerage") or ""
        if not is_turner(office_for_scope):
            return ""

    office = (
        listing.get("idx_office_name")
        or listing.get("listing_brokerage")
        or "an NLAR MLS® member brokerage"
    )
    script = _listing_script.build_listing_script(
        listing, address=address, office=office, phone="709-256-7999")
    sig = _listing_script.sign_payload("labwest", str(listing.get("mls") or ""), script, LISTING_AUDIO_HMAC)

    # preview mode: the button still renders (so a direct link works for
    # Mike to test) but stays hidden unless ?listen=1 is in the URL --
    # js/listing-audio.js checks this class + the query string before
    # un-hiding it. "on" mode never adds the class, so it's always visible.
    preview_class = " lst-listen--preview" if LISTING_AUDIO_MODE == "preview" else ""

    return f"""
<section class="lst-listen{preview_class}">
  <button type="button" class="lst-listen-btn" data-listen
      data-site="labwest" data-mls="{he(listing.get('mls'))}"
      data-sig="{he(sig)}" data-script="{he(script)}"
      aria-label="Hear about this home">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18" aria-hidden="true">
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
      <path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path>
      <path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path>
    </svg>
    <span class="lst-listen-btn-label">Hear about this home</span>
  </button>
  <p class="lst-listen-status" hidden></p>
  <audio class="lst-listen-audio" preload="none" hidden></audio>
  <details class="lst-listen-transcript">
    <summary>AI-generated narration &middot; read the transcript</summary>
    <p>{he(script)}</p>
  </details>
</section>"""


def build_jsonld(listing: dict) -> str:
    """Schema.org RealEstateListing structured data — drives Google rich results."""
    schema = {
        "@context": "https://schema.org",
        "@type": "RealEstateListing",
        "name": f"{listing['street']}, {city_display_name(listing['city_slug'])}",
        "description": (listing.get("public_remarks") or "")[:500],
        "url": f"{SITE_ORIGIN}{listing['url_path']}",
        "datePosted": listing.get("list_date"),
        "dateModified": listing.get("modification_timestamp"),
        "image": [p["url"] for p in listing["photos"][:8]],
        "address": {
            "@type": "PostalAddress",
            "streetAddress": listing.get("street"),
            "addressLocality": listing.get("city_raw") or city_display_name(listing["city_slug"]),
            "addressRegion": listing.get("province"),
            "postalCode": fmt_postal(listing.get("postal_code")),
            "addressCountry": listing.get("country"),
        },
    }
    # Lab West (D-1012-28): the contact for every listing is Mike Turner, Broker of Record, at the brokerage. No office
    # address is ever emitted (there is no Lab West office; the "address" above is the HOME for sale, not the broker).
    schema["listingAgent"] = {
        "@type": "RealEstateAgent",
        "name": "Mike Turner",
        "jobTitle": "Broker of Record",
        "telephone": "+1-709-256-7999",
        "email": "miketurner@royallepage.ca",
        "worksFor": {"@type": "RealEstateAgent", "name": "Royal LePage Turner Realty", "telephone": "+1-709-256-7999"},
    }
    if listing.get("list_price"):
        schema["offers"] = {
            "@type": "Offer",
            "price": listing["list_price"],
            "priceCurrency": listing.get("currency", "CAD"),
            "availability": "https://schema.org/InStock",
        }
    if listing.get("latitude") and listing.get("longitude"):
        schema["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": listing["latitude"],
            "longitude": listing["longitude"],
        }
    if listing.get("bedrooms"):
        schema["numberOfBedrooms"] = listing["bedrooms"]
    if listing.get("bathrooms"):
        schema["numberOfBathroomsTotal"] = listing["bathrooms"]
    if listing.get("living_area"):
        schema["floorSize"] = {"@type": "QuantitativeValue", "value": listing["living_area"], "unitCode": "FTK"}
    return f'<script type="application/ld+json">{ja(schema)}</script>'






def build_rooms_section(listing: dict) -> str:
    """Render a Room-by-Room dimensions table on the listing detail page.

    Convention #15 propagation pattern from realestategander-site canonical
    (Client Full parity ship 2026-05-11) via Avalon ship 2026-05-14.
    Standalone section (no tab wrapper). Convention #74 fail-safe: empty
    when no idx_rooms data.
    """
    rooms = listing.get("idx_rooms") or []
    if not rooms:
        return ""

    def _order_key(r):
        try:
            return int(r.get("order") or 999)
        except (TypeError, ValueError):
            return 999
    rooms = sorted(rooms, key=_order_key)

    rows = []
    for r in rooms:
        floor = he(r.get("floor", ""))
        room = he(r.get("room", ""))
        dims = ""
        size = (r.get("size") or "").strip()
        if size:
            dims = he(size)
        else:
            length = (r.get("length") or "").strip()
            width = (r.get("width") or "").strip()
            if length and width:
                dims = he(f"{length} × {width}")
            elif length:
                dims = he(length)
        if not (floor or room or dims):
            continue
        rows.append(
            f'<tr><td>{floor}</td><td>{room}</td><td>{dims}</td></tr>'
        )
    if not rows:
        return ""

    table_rows = "".join(rows)
    return (
        '<section class="lst-section lst-rooms-section">'
        '<h2>Rooms</h2>'
        '<table class="lst-rooms-table">'
        '<thead><tr>'
        '<th scope="col">Floor</th>'
        '<th scope="col">Room</th>'
        '<th scope="col">Dimensions</th>'
        '</tr></thead>'
        f'<tbody>{table_rows}</tbody>'
        '</table>'
        '</section>'
    )


def build_price_history_section(listing: dict) -> str:
    """Render a 2-3 point price-change timeline. Strategic Vision Rec #1.
    Convention #15 propagation from realestategander-site (9d5fc66e2).
    Fires only when OriginalListPrice ≠ ListPrice (Convention #74).
    """
    def _fmt_price(v):
        try:
            n = float(v)
            if not n or n <= 0:
                return None
            return f"${int(round(n)):,}"
        except (TypeError, ValueError):
            return None

    def _fmt_date_iso(ts):
        if not ts:
            return ""
        import datetime as _dt
        try:
            s = str(ts)
            if "." in s:
                s = s.split(".")[0]
            if s.endswith("Z"):
                s = s[:-1]
            d = _dt.datetime.fromisoformat(s).date()
            return d.strftime("%b %-d, %Y")
        except (ValueError, TypeError):
            try:
                d = _dt.date.fromisoformat(str(ts)[:10])
                return d.strftime("%b %-d, %Y")
            except (ValueError, TypeError):
                return ""

    try:
        olp = listing.get("idx_original_list_price")
        olp_f = float(olp) if olp is not None else None
    except (TypeError, ValueError):
        olp_f = None
    try:
        lp = listing.get("list_price")
        lp_f = float(lp) if lp is not None else None
    except (TypeError, ValueError):
        lp_f = None
    try:
        llp = listing.get("idx_last_list_price")
        llp_f = float(llp) if llp is not None else None
    except (TypeError, ValueError):
        llp_f = None

    if olp_f is None or lp_f is None:
        return ""
    if olp_f <= 0 or lp_f <= 0:
        return ""
    if abs(olp_f - lp_f) < 1.0:
        return ""

    change_date = _fmt_date_iso(listing.get("idx_price_change_timestamp"))
    list_date = _fmt_date_iso(listing.get("list_date"))

    delta_dollars = lp_f - olp_f
    delta_pct = (delta_dollars / olp_f) * 100.0 if olp_f else 0.0
    delta_down = delta_dollars < 0

    sign = "−" if delta_down else "+"
    delta_abs = abs(delta_dollars)
    delta_text = f"{sign}${int(round(delta_abs)):,} ({sign}{abs(delta_pct):.1f}%)"
    delta_class = "lst-price-history-delta--down" if delta_down else "lst-price-history-delta--up"
    delta_label_word = "Reduced" if delta_down else "Increased"

    rows = []
    olp_str = _fmt_price(olp_f)
    lp_str = _fmt_price(lp_f)
    llp_str = _fmt_price(llp_f) if llp_f is not None else None

    olp_date_html = (
        f'<span class="lst-price-history-date">on {he(list_date)}</span>'
        if list_date else ""
    )
    rows.append(
        '<div class="lst-price-history-row lst-price-history-row--from">'
        '<span class="lst-price-history-label">Originally listed</span>'
        f'<span class="lst-price-history-amount">{he(olp_str)}</span>'
        f'{olp_date_html}'
        '</div>'
    )

    if (
        llp_f is not None
        and llp_f > 0
        and abs(llp_f - olp_f) >= 1.0
        and abs(llp_f - lp_f) >= 1.0
    ):
        rows.append(
            '<div class="lst-price-history-row lst-price-history-row--mid">'
            '<span class="lst-price-history-label">Previously listed</span>'
            f'<span class="lst-price-history-amount">{he(llp_str)}</span>'
            '</div>'
        )

    current_date_html = (
        f'<span class="lst-price-history-date">on {he(change_date)}</span>'
        if change_date else ""
    )
    rows.append(
        '<div class="lst-price-history-row lst-price-history-row--to">'
        f'<span class="lst-price-history-label">{he(delta_label_word)} to</span>'
        f'<span class="lst-price-history-amount">{he(lp_str)}</span>'
        f'{current_date_html}'
        '</div>'
    )

    badge_html = (
        f'<span class="lst-price-history-delta {delta_class}">{he(delta_text)}</span>'
    )

    return (
        '<section class="lst-price-history" aria-label="Price history">'
        '<div class="lst-price-history-inner">'
        '<div class="lst-price-history-header">'
        f'<h2 class="lst-price-history-title">Price history</h2>'
        f'{badge_html}'
        '</div>'
        f'<div class="lst-price-history-timeline">{"".join(rows)}</div>'
        '</div>'
        '</section>'
    )


def build_similar_listings_section(listing: dict, all_listings: list | None) -> str:
    """More-homes card grid at bottom of listing-detail. Same-city first,
    fallback to same property type. Convention #15 propagation (afdb1747).
    """
    if not all_listings:
        return ""
    current_mls = listing.get("mls")
    current_city = listing.get("city_slug")
    current_ptype = listing.get("property_type")
    same_city = [
        l for l in all_listings
        if l.get("city_slug") == current_city
        and l.get("mls") != current_mls
    ]
    same_city.sort(key=lambda l: l.get("list_date") or "", reverse=True)
    selected = same_city[:6]
    if len(selected) < 4 and current_ptype:
        same_type = [
            l for l in all_listings
            if l.get("property_type") == current_ptype
            and l.get("mls") != current_mls
            and l.get("city_slug") != current_city
        ]
        same_type.sort(key=lambda l: l.get("list_date") or "", reverse=True)
        selected.extend(same_type[: 6 - len(selected)])
    if not selected:
        return ""
    city_label = city_display_name(current_city) if current_city else "Labrador"
    if len(same_city) >= 4 or len(selected) <= len(same_city):
        heading = f"More homes in {city_label}"
    else:
        heading = "More homes you might like"
    cards_html = "".join(build_listing_card(l, prefix="../../") for l in selected)
    return f"""
<section class="lst-similar">
  <div class="lst-similar-inner">
    <h2 class="lst-similar-heading">{he(heading)}</h2>
    <div class="lst-similar-grid lst-card-grid">{cards_html}</div>
    <p class="lst-similar-viewall"><a href="../../listings/{current_city or ''}/">View all listings in {he(city_label)} &rarr;</a></p>
  </div>
</section>
"""


# Listing Text Alerts inline band (Conv #15 port from Gander 2026-07-04 —
# the Avalon-conversion-sprint 1b ship). Rendered by js/alert-inline.js, which
# is already site-aware (posts cross-origin to the Gander-homed sms-subscribe).
def lta_band(city: str = "") -> str:
    """The Listing Text Alerts band, optionally scoped to one town.

    Alerts v2 I4 (2026-07-24): this band sits at the foot of every listing and
    city page and used to sign people up for EVERY new listing on the site —
    someone reading a listing in one town got texted about every other town,
    with no way to narrow it. Passing the page's town emits data-lta-city, and
    js/alert-inline.js posts {v:2, cities:[city]} instead of {}.

    Called with no city (rollups, which legitimately span towns) it returns
    the original site-wide band byte-for-byte.
    """
    if city:
        c = (city.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;"))
        attrs = f' data-lta-city="{c}" data-lta-label="New listings in {c}"'
    else:
        attrs = ' data-lta-label="All new Lab West listings"'
    return (
    '<section aria-label="Listing Text Alerts signup" '
    'style="background:linear-gradient(135deg,#1a1a1a 0%,#222 100%);border-top:3px solid #EA002A;display:flex;justify-content:center;">'
    '<div style="max-width:600px;width:100%;padding:34px 20px 38px;text-align:center;box-sizing:border-box;">'
    '<span style="display:inline-block;background:rgba(234,0,42,.14);border:1px solid rgba(234,0,42,.5);color:#ff5a73;font-family:Raleway,sans-serif;font-weight:800;font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;padding:5px 12px;border-radius:999px;">Listing Text Alerts</span>'
    '<h2 style="font-family:Raleway,sans-serif;font-weight:900;font-size:1.5rem;color:#fff;margin:14px 0 6px;line-height:1.15;">Get new listings texted to you</h2>'
    '<p style="color:#cdcdcd;font-size:.95rem;line-height:1.5;margin:0 auto 18px;max-width:480px;">New listings in Labrador City &amp; Wabush, straight to your phone the moment they hit the market &mdash; free. No account, no app.</p>'
    f'<div style="max-width:520px;margin:0 auto;text-align:left;"><div data-lta-inline{attrs}></div></div>'
    + ('<a href="/text-alerts" style="display:inline-block;margin-top:14px;color:#9aabb3;font-size:.84rem;text-decoration:none;border-bottom:1px dotted #5a6b73;">Customize by area or price &rarr;</a>' if _page_exists("text-alerts.html") else '') +
    '</div></section>'
)


# Site-wide default — kept so existing call sites stay byte-identical.
LTA_INLINE_BAND = lta_band()


def _oh_time_fmt(hhmm: str) -> str:
    """"1400" -> "2:00 PM". Byte-identical to Gander's helper (Convention
    #15 port, Batch F1 close-out 2026-08-20) -- same raw NLAR
    StartTime/EndTime format, so the same 6-line conversion applies."""
    hhmm = (hhmm or "").strip().zfill(4)
    try:
        h, mi = int(hhmm[:2]), hhmm[2:]
        ap = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{mi} {ap}"
    except ValueError:
        return hhmm


def _open_house_banner(listing: dict) -> str:
    """Full-width upcoming-open-house notice, or "" when none is on file.

    Sourced from tools/idx-cache/open-houses.json (idx-openhouse-sync.py,
    NLAR's OpenHouse RETS resource, merged onto the overlay by
    Matrix_Unique_ID -- Batch F1 close-out, 2026-08-20, Convention #15
    port from Gander). Only ever shows the SOONEST upcoming event -- a
    listing with 2 dates on file just shows the next one. A past date
    on a stale cache is refused rather than shown (Conv #74's spirit
    applied to time, not just missing data)."""
    oh = listing.get("idx_open_house_next")
    if not oh or not oh.get("date"):
        return ""
    try:
        d = datetime.strptime(oh["date"], "%Y-%m-%d")
    except (ValueError, TypeError):
        return ""
    if d.date() < datetime.now(timezone.utc).date():
        return ""
    day_label = d.strftime("%A, %B %-d")
    times = f"{_oh_time_fmt(oh.get('start_time'))}\u2013{_oh_time_fmt(oh.get('end_time'))}"
    return (
        '<div style="background:#f0fdf4;border:1px solid #86efac;'
        'border-left:5px solid #16a34a;border-radius:8px;padding:14px 18px;'
        'margin:0 0 18px;">'
        '<div style="font-weight:700;color:#14532d;font-size:1.02rem;'
        'letter-spacing:.02em;">\U0001F3E1 OPEN HOUSE</div>'
        f'<div style="color:#15803d;font-size:.92rem;line-height:1.5;margin-top:4px;">'
        f'{he(day_label)} \u00b7 {he(times)} \u2014 drop by, no appointment needed.</div>'
        '</div>'
    )


def build_print_footer(listing, canonical_url) -> str:
    """Print-only footer -- hidden on screen (see .lst-print-footer in
    LISTING_PAGE_CSS), shown only when window.print() runs (Batch F3,
    2026-08-20). Carries the agent/office NAP + the listing's canonical
    URL + MLS# so a printed flyer identifies itself once separated from
    the browser. Reuses match_turner_agent(), the SAME lookup
    build_inquiry_card already calls (Conv #148 -- never re-derive NAP by
    hand); Goose Bay has no get_team() (Duo-team site, no per-city
    default map), so the no-match fallback mirrors build_inquiry_card's
    own hardcoded HVGB office NAP verbatim."""
    agent_record = match_turner_agent(listing.get("idx_list_agent_full_name"))
    if agent_record:
        contact_name = he(agent_record["name"])
        contact_phone = he(_fmt_phone(agent_record["phone"]))
        contact_email = he(agent_record["email"])
    else:
        contact_name = "Mike Turner, Broker \u2014 Royal LePage Turner Realty"
        contact_phone = he(_fmt_phone("7092567999"))
        contact_email = "miketurner@royallepage.ca"
    return f"""
<div class="lst-print-footer">
  <p>{contact_name} &middot; Royal LePage Turner Realty &middot; {contact_phone} &middot; {contact_email}</p>
  <p>MLS&reg; {he(listing.get('mls',''))} &middot; {he(canonical_url)}</p>
</div>"""


def build_listing_page(listing: dict, all_listings: list | None = None) -> str:
    """Assemble the complete HTML for a single listing detail page."""
    city_name = city_display_name(listing["city_slug"])
    breadcrumb_jsonld = build_breadcrumb_jsonld([
        ("Home", f"{SITE_ORIGIN}/"),
        ("Listings", f"{SITE_ORIGIN}/listings/"),
        (city_name, f"{SITE_ORIGIN}/listings/{listing['city_slug']}/"),
        (f"MLS® {listing['mls']}", f"{SITE_ORIGIN}{listing['url_path']}"),
    ])

    # D-1009-77 (2026-10-09): the page carries ONE availability label, the
    # .lst-status line under the price (tools/_listing_terms.py). This badge is
    # still computed (its data-status matches) but no longer placed on the page.
    # ── Conditional-status badge (task-#57 port, 2026-07-17; Mike 2026-05-18
    # + re-affirmed 2026-07-15: "Under contract should stay on the site").
    # idx-ingest.py now pulls UC + STCOS into the active feed (widened same
    # day) — an accepted-offer listing renders with the amber badge instead
    # of vanishing from the site. Minimal-churn port: the badge renders ONLY
    # for conditional states; plain-active listings keep Goosebay's existing
    # look (no green "For sale" pill — that's Gander's CX-8 layout, not
    # ported here). NLAR long-form statuses: "Cond Pending - Under Contract"
    # (UC) · "Conditional - SST" (STCOS) · "Conditional Pending" (STFRM,
    # defensive — the feed returns zero STFRM rows per the 07-15 dump).
    _raw_status = ("" if listing.get("is_lease")
                   else (listing.get("status") or "").strip().lower())
    if "under contract" in _raw_status or "sst" in _raw_status:
        # One availability vocabulary (D-1009-77).
        status_badge = ('<span class="lst-detail-status-badge pending" data-status="conditional">'
                        'Conditional</span>')
    elif "firm" in _raw_status or _raw_status == "conditional pending":
        status_badge = ('<span class="lst-detail-status-badge pending" data-status="pending">'
                        'Pending</span>')
    else:
        status_badge = ""

    # Days-on-market row: "Just listed" pill (≤7 days) + "Days on market: N"
    dom = _days_on_market(listing)
    dom_parts = []
    if dom is not None and dom <= NEW_LISTING_DAYS:
        dom_parts.append('<span class="lst-just-listed">Just listed</span>')
    if dom is not None:
        # dom is NL-day based (_fleet_genutils); a date, never the word "today",
        # because the page stays static until the next rebuild (sites 2026-10-09).
        dom_label = f"Listed {_list_date_label(listing)}" if dom == 0 else (
            f"Days on market: <strong style=\"color:#fff;\">{dom}</strong>"
        )
        dom_parts.append(f'<span class="lst-dom">{dom_label}</span>')
    dom_block = f'<div class="lst-dom-row">{"".join(dom_parts)}</div>' if dom_parts else ""

    # Share button metadata — canonical URL + title + one-line teaser.
    # Consumed by js/listing-share.js which invokes navigator.share (native
    # OS share sheet) when available and falls back to an in-page modal.
    share_url = f"{SITE_ORIGIN}{listing['url_path']}"
    share_title = f"{listing['street']}, {city_name}, NL"
    share_text_bits = [fmt_price(listing.get('list_price'), listing=listing)]
    if listing.get('bedrooms') is not None:
        share_text_bits.append(f"{listing['bedrooms']}bd")
    if listing.get('bathrooms') is not None:
        share_text_bits.append(f"{fmt_bath(listing['bathrooms'])}ba")
    share_text_bits.append(f"MLS® {listing['mls']}")
    share_text = " · ".join(share_text_bits)

    share_button = (
        f'<div class="lst-share-row">'
        f'<button type="button" class="lst-share-btn" '
        f'data-share-url="{he(share_url)}" '
        f'data-share-title="{he(share_title)}" '
        f'data-share-text="{he(share_text)}" '
        f'aria-label="Share this listing">'
        # Classic 3-node share glyph (iOS/Android universal)
        f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="2" width="16" height="16" aria-hidden="true">'
        f'<circle cx="18" cy="5" r="3"/>'
        f'<circle cx="6" cy="12" r="3"/>'
        f'<circle cx="18" cy="19" r="3"/>'
        f'<line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/>'
        f'<line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>'
        f'</svg>'
        f'Share'
        f'</button>'
        # Favorites (Saved Homes) — Phase 2 #12. Heart pairs with Share.
        # js/favorites.js binds [data-fav-toggle] + toggles .is-fav.
        f'<button type="button" class="lst-fav-btn" data-fav-toggle="{he(listing["mls"])}" '
        f'aria-pressed="false" aria-label="Save this home">'
        f'<svg viewBox="0 0 24 24" aria-hidden="true">'
        f'<path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>'
        f'</svg>'
        f'<span class="lst-fav-label">Save</span>'
        f'</button>'
        f'<button type="button" class="lst-share-btn" onclick="window.print()" aria-label="Print this listing">'
        f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" aria-hidden="true">'
        f'<polyline points="6,9 6,2 18,2 18,9"/>'
        f'<path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>'
        f'<rect x="6" y="14" width="12" height="8"/>'
        f'</svg>'
        f'Print'
        f'</button>'
        f'</div>'
    )

    crumb = (
        f'<nav style="max-width:1200px;margin:24px auto 0;padding:0 20px;font-size:0.85rem;color:rgba(255,255,255,0.5);font-family:\'Roboto\',sans-serif;">'
        f'<a href="../../index.html" style="color:rgba(255,255,255,0.5);">Home</a> &rsaquo; '
        f'<a href="../../listings/index.html" style="color:rgba(255,255,255,0.5);">Listings</a> &rsaquo; '
        f'{_crumb_city_html(listing)}'
        f'<span style="color:#EA002A;">MLS® {he(listing["mls"])}</span>'
        f'</nav>'
    )

    # B3 (2026-09-17): mobile clamps to 6 lines with a "Read more" toggle
    # (CSS -webkit-line-clamp, see p.lst-remarks in LISTING_PAGE_CSS);
    # desktop/tablet render the full remarks unclamped, unchanged.
    description_section = ""
    if listing.get("public_remarks"):
        description_section = (
            '<section class="lst-section">'
            '<h2>About This Property</h2>'
            f'<p class="lst-remarks" id="lst-remarks-{he(listing.get("mls",""))}">{he(listing["public_remarks"])}</p>'
            f'<button type="button" class="lst-remarks-toggle" '
            f'data-expand-target="lst-remarks-{he(listing.get("mls",""))}" aria-expanded="false">Read more</button>'
            '</section>'
            '<script>(function(){'
            "document.querySelectorAll('.lst-remarks-toggle').forEach(function(btn){"
            "btn.addEventListener('click', function(){"
            "var id = btn.getAttribute('data-expand-target');"
            "var el = id && document.getElementById(id);"
            "if (!el) return;"
            "var expanded = el.classList.toggle('is-expanded');"
            "btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');"
            "btn.textContent = expanded ? 'Read less' : 'Read more';"
            "});});"
            '})();</script>'
        )

    tour_section = build_tour_section(listing, f"{listing['street']}, {city_name} NL")

    map_section = ""
    if listing.get("latitude") and listing.get("longitude"):
        map_section = f"""
<section class="lst-section">
  <h2>Location</h2>
  <iframe
    src="https://www.openstreetmap.org/export/embed.html?bbox={listing['longitude']-0.01},{listing['latitude']-0.005},{listing['longitude']+0.01},{listing['latitude']+0.005}&amp;layer=mapnik&amp;marker={listing['latitude']},{listing['longitude']}"
    style="width:100%;height:360px;border:1px solid #222;border-radius:4px;"
    loading="lazy" referrerpolicy="no-referrer"></iframe>
</section>"""

    return f"""<!DOCTYPE html>
<html lang="en">
{head_block(listing)}
<body class="lst-listing">
{nav_html()}

<div class="lst-shell">

{crumb}

{_pending_banner(listing)}
{_open_house_banner(listing)}
{build_gallery(listing)}

<div class="lst-main">

  <div class="lst-content">
    <div class="lst-title-block">
      <p class="lst-eyebrow">{he(listing.get('property_subtype') or 'Property')} · MLS® {he(listing['mls'])}</p>
      <h1>{he(listing['street'])}</h1>
      <p class="lst-locality">{he(city_display_name(listing['city_slug']))}, {he(listing.get('province') or 'NL')} {he(fmt_postal(listing.get('postal_code') or ''))}</p>
      <p class="lst-price">{fmt_price(listing['list_price'], listing=listing)}</p>
      {_lr.status_line_html(listing)}
      {build_payment_estimate_line(listing)}
      {build_all_in_line(listing)}
      {build_budget_record(listing)}
      <p class="lst-price-meta">{he(listing.get('currency') or 'CAD')}</p>
      {dom_block}
      {share_button}
    </div>

    {build_price_history_section(listing)}

    {build_facts_strip(listing)}

    {build_resource_strip(listing)}

    {description_section}

    {build_listen_section(listing, f"{listing['street']}, {city_name} NL")}

    {tour_section}

    {build_street_view_section(listing)}

    {build_distance_to_section(listing)}

    {_lr.rental_details_html(listing)}

    {build_details_grid(listing)}

    {build_rooms_section(listing)}

    {build_operating_costs_section(listing)}

    {build_features_section(listing)}

    {map_section}

    {build_attribution(listing)}

    {build_print_footer(listing, share_url)}
  </div>

  <aside class="lst-sidebar">
    {build_inquiry_card(listing)}
  </aside>

</div>

{build_similar_listings_section(listing, all_listings)}

{build_keep_exploring("../../", city_slug=listing["city_slug"], city_name=city_display_name(listing["city_slug"]), commercial=_is_commercial(listing), href_override=(listing.get("_city_link") if listing.get("_pending") else None), label_override=(listing.get("_city_link_label") if listing.get("_pending") else None))}

<div class="lst-ddr">
  <p>{he(DDR_DISCLAIMER)}</p>
  <p>{he(TRADEMARK_NOTICE)}</p>
</div>

</div>

{footer_html()}

<!-- Mobile/tablet bottom action bar rendered by js/mobile-action-bar.js
     (retired the per-listing .lst-mobile-cta here, 2026-09-17). -->

{build_jsonld(listing)}
{breadcrumb_jsonld}
{build_analytics_beacon(listing)}

<script src="../../js/footer.js?v=20260909-footer-converge"></script>
<script src="/js/lead-shim.js"></script>
<script src="../../js/boldtrail-forms.js?v=d7dca662"></script>
<script src="../../js/regions-data.js" defer></script>
<script src="../../js/nav-config.js" defer></script>
<script src="../../js/nav-config-listings.js" defer></script>
<script>window.TURNER_SITE='{_SITE_CFG["site_key"]}';window.TURNER_API_ORIGIN='{_SITE_CFG["api_url"]}';</script>
<script src="../../js/nav.js?v=20260913-mobile-nav-fix" defer></script>
<script src="../../js/mobile-action-bar.js?v=20260917-mobile-action-bar" defer></script>
{_nav_auth_script("../../")}
<script src="../../js/app-shell.js?v=20260920-app8" defer></script>
<script src="../../js/turner-network.js" defer></script>
<script src="../../js/recently-viewed.js" defer></script>
{_chat_script("../../")}
{lta_band(city_name)}
<script src="/js/alert-inline.js?v=20260724-lta-city" defer></script>
<script src="../../js/listing-share.js" defer></script>
<script src="../../js/listing-audio.js" defer></script>
<script src="../../js/lightbox.js" defer></script>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js" defer></script>
<script src="../../js/auth.js?v=20260929-sold-auth" defer></script>
<script src="../../js/agent-registry-link.js?v=20260911-safebottom" defer></script>
<script src="../../js/favorites.js?v=20260929-noprojected" defer></script>
<script src="../../js/saved-search.js?v=20260925-tq-token" defer></script>
<script src="../../js/save-nudge.js?v=20260929-noprojected" defer></script>
<script src="../../js/budget-v1.js?v=20261009-budget" defer></script>
<script>
  // Wire both sidebar forms + tab toggle (Book a Showing / Ask a Question).
  if (window.BoldTrailForms) {{
    if (document.getElementById('lst-showing-form')) {{
      BoldTrailForms.bookShowing('#lst-showing-form');
    }}
    if (document.getElementById('lst-inquiry-form')) {{
      BoldTrailForms.listingInquiry('#lst-inquiry-form');
    }}
    // Item 6: third tab (gate SITE_PERSONAL_REVIEW); must run BEFORE the tab toggle below binds the tabs.
    if (BoldTrailForms.personalReview) {{
      BoldTrailForms.personalReview('.lst-cta-card[data-review]');
    }}
    // Commercial listings render this instead of the showing/inquiry tabs.
    if (document.getElementById('lst-commercial-inquiry')) {{
      BoldTrailForms.commercialInquiry('#lst-commercial-inquiry');
    }}
  }}
  (function(){{
    var tabs = document.querySelectorAll('.lst-rf-tab');
    var panels = document.querySelectorAll('.lst-rf-panel');
    if (!tabs.length) return;
    tabs.forEach(function(t){{
      t.addEventListener('click', function(){{
        var target = t.getAttribute('data-rf-tab');
        tabs.forEach(function(x){{
          var active = x === t;
          x.classList.toggle('active', active);
          x.setAttribute('aria-selected', active ? 'true' : 'false');
        }});
        panels.forEach(function(p){{
          p.hidden = p.getAttribute('data-rf-panel') !== target;
        }});
      }});
    }});
  }})();
  // Mobile CTA bar's own scroll-to-showing handler retired 2026-09-17 --
  // js/mobile-action-bar.js creates the "Book a Showing" button itself
  // and attaches the identical tab/scroll/focus behaviour directly,
  // including the same #lst-showing-form / #lst-commercial-inquiry /
  // #lst-inquiry-form fallback chain this page used.
</script>
</body>
</html>
"""


# ═══════════════════════════════════════════════════════════════════
#  CITY LANDING / INDEX / SITEMAP BUILDERS
# ═══════════════════════════════════════════════════════════════════

# Additional CSS appended to LISTING_PAGE_CSS for card-grid index pages.
# Uses the same .lst- scope so both kinds of page share the shell look.
INDEX_PAGE_CSS = """
/* ═══ Listing card grid (city landing + all-listings index) ═══ */
.lst-index-head {
  max-width: 1200px;
  margin: 40px auto 20px;
  padding: 0 20px;
}
.lst-index-head .lst-eyebrow { margin-bottom: 10px; }
.lst-index-head h1 {
  font-family: 'Raleway', sans-serif;
  font-weight: 900;
  font-size: clamp(1.8rem, 4vw, 2.8rem);
  color: #fff;
  margin: 0 0 10px;
  letter-spacing: -0.5px;
}
.lst-index-head p.lst-sub {
  font-family: 'Roboto', sans-serif;
  color: rgba(255,255,255,0.7);
  font-size: 1rem;
  margin: 0;
  max-width: 720px;
}
.lst-index-head .lst-count {
  font-family: 'Roboto', sans-serif;
  color: rgba(255,255,255,0.5);
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-top: 14px;
}

/* Card grid */
.lst-card-grid {
  max-width: 1200px;
  margin: 24px auto 60px;
  padding: 0 20px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 24px;
}
.lst-card {
  background: #111;
  border: 1px solid #1e1e1e;
  border-radius: 4px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: transform .3s, border-color .3s;
  color: inherit;
}
.lst-card:hover { transform: translateY(-4px); border-color: #EA002A; }
.lst-card-link {
  display: block;
  text-decoration: none;
  color: inherit;
}
.lst-card-link:focus-visible {
  outline: 2px solid #EA002A;
  outline-offset: -2px;
}
.lst-card-realtor {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 14px;
  border-top: 1px solid #1e1e1e;
  background: #0d0d0d;
  font-family: 'Roboto', sans-serif;
  font-size: 0.72rem;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  color: rgba(255,255,255,0.55);
  text-decoration: none;
  transition: background .2s, color .2s;
}
.lst-card-realtor:hover,
.lst-card-realtor:focus-visible {
  background: #151515;
  color: #fff;
  outline: none;
}
.lst-card-realtor strong {
  color: #EA002A;
  font-weight: 700;
}
.lst-card-img {
  aspect-ratio: 3 / 2;
  background: #0a0a0a;
  overflow: hidden;
  position: relative;
}
.lst-card-img img {
  width: 100%; height: 100%; object-fit: cover; display: block;
  transition: transform .4s;
}
.lst-card:hover .lst-card-img img { transform: scale(1.05); }
.lst-card-img .lst-card-noimg {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  color: rgba(255,255,255,0.3);
  font-family: 'Raleway', sans-serif; font-weight: 800; font-size: 2rem;
  background: linear-gradient(135deg,#1a1a1a,#0f0f0f);
}
.lst-card-body { padding: 18px 20px 20px; }
.lst-card-price {
  font-family: 'Raleway', sans-serif;
  font-weight: 900;
  font-size: 1.4rem;
  color: #fff;
  margin: 0 0 4px;
}
.lst-card-addr {
  font-family: 'Roboto', sans-serif;
  color: rgba(255,255,255,0.85);
  font-size: 0.95rem;
  font-weight: 500;
  margin: 0 0 2px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.lst-card-city {
  font-family: 'Roboto', sans-serif;
  color: rgba(255,255,255,0.55);
  font-size: 0.85rem;
  margin: 0 0 12px;
}
.lst-card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 18px;
  font-family: 'Roboto', sans-serif;
  color: rgba(255,255,255,0.65);
  font-size: 0.82rem;
  border-top: 1px solid #1e1e1e;
  padding-top: 12px;
}
.lst-card-meta span strong {
  color: #fff; font-weight: 700; margin-right: 4px;
}
.lst-card-mls {
  font-family: 'Roboto', sans-serif;
  color: rgba(255,255,255,0.4);
  font-size: 0.75rem;
  margin-top: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.lst-card-new {
  position: absolute;
  top: 10px; left: 10px;
  background: #EA002A;
  color: #fff;
  font-family: 'Raleway', sans-serif;
  font-weight: 800;
  font-size: 0.7rem;
  padding: 4px 10px;
  border-radius: 2px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}
.lst-card-pending {
  position: absolute;
  top: 10px; left: 10px;
  background: #d97706;
  color: #fff;
  font-family: 'Raleway', sans-serif;
  font-weight: 800;
  font-size: 0.7rem;
  padding: 4px 10px;
  border-radius: 2px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

/* City chip bar (used on top-level index) */
.lst-city-chips {
  max-width: 1200px;
  margin: 20px auto 0;
  padding: 0 20px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.lst-city-chips a {
  background: #1a1a1a;
  border: 1px solid #222;
  color: rgba(255,255,255,0.8);
  font-family: 'Roboto', sans-serif;
  font-size: 0.85rem;
  padding: 7px 14px;
  border-radius: 30px;
  text-decoration: none;
  transition: background .2s, border-color .2s, color .2s;
}
.lst-city-chips a:hover {
  background: #222;
  border-color: #EA002A;
  color: #fff;
}
.lst-city-chips a span {
  color: rgba(255,255,255,0.5);
  margin-left: 6px;
  font-size: 0.78rem;
}

.lst-empty {
  max-width: 720px;
  margin: 60px auto;
  padding: 40px 20px;
  text-align: center;
  color: rgba(255,255,255,0.6);
  font-family: 'Roboto', sans-serif;
}

/* Result cards: rendered by js/listings-filter.js for 2-50 matches.
   Convention #15 propagation from stjohns-site. */
.lst-result-card {
  background: var(--dark-card, #1a1a1a);
  border: 1px solid var(--dark-border, #2a2a2a);
  border-radius: 6px;
  transition: border-color 0.2s, transform 0.2s;
  overflow: hidden;
}
.lst-result-card:hover { border-color: var(--accent-red, #EA002A); transform: translateY(-2px); }
.lst-result-link { display: block; padding: 20px; color: #fff; text-decoration: none; }
.lst-result-price { font-family: Raleway, sans-serif; font-weight: 900; font-size: 1.5rem; color: var(--accent-red, #EA002A); margin: 0 0 8px; }
.lst-result-addr { font-family: Roboto, sans-serif; font-weight: 600; font-size: 1.05rem; margin: 0 0 4px; color: #fff; }
.lst-result-city { font-family: Roboto, sans-serif; font-size: 0.9rem; color: rgba(255,255,255,0.7); margin: 0 0 12px; }
.lst-result-meta { display: flex; gap: 12px; margin: 0 0 12px; font-size: 0.85rem; color: rgba(255,255,255,0.7); }
.lst-result-meta span strong { color: #fff; font-weight: 700; margin-right: 2px; }
.lst-result-mls { font-family: Roboto, sans-serif; font-size: 0.78rem; color: rgba(255,255,255,0.5); margin: 0 0 12px; }
.lst-result-cta { font-family: Raleway, sans-serif; font-weight: 700; font-size: 0.85rem; color: var(--accent-red, #EA002A); text-transform: uppercase; letter-spacing: 0.5px; margin: 0; }
"""


def head_block_simple(title: str, description: str, canonical: str,
                      og_image: str, prefix: str, lean: bool = False) -> str:
    """A simpler <head>…</head> for city landing + all-listings index pages."""
    full_css = LISTING_PAGE_CSS + "\n" + INDEX_PAGE_CSS
    # lean=True (Viewpoint pages) skips the ~47KB inline listing CSS.
    style_block = "" if lean else "<style>\n" + full_css + "\n</style>"
    return f"""<head>
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id={GTAG_LOADER_ID}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{GTAG_LOADER_ID}');
</script>
{FUB_PIXEL_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="description" content="{he(description)}">
<meta property="og:url" content="{he(canonical)}">
<meta property="og:title" content="{he(title)}">
<meta property="og:description" content="{he(description)}">
<meta property="og:image" content="{he(og_image)}">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{he(title)}">
<meta name="twitter:description" content="{he(description)}">
<meta name="twitter:image" content="{he(og_image)}">
<title>{he(title)}</title>
<link rel="canonical" href="{he(canonical)}">
<link rel="icon" type="image/x-icon" href="{prefix}favicon.ico">
<link rel="icon" type="image/png" sizes="32x32" href="{prefix}favicon-32x32.png">
<link rel="apple-touch-icon" sizes="180x180" href="{prefix}apple-touch-icon.png">
<meta name="theme-color" content="#EA002A">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="Lab West Realty">
<link rel="stylesheet" href="{prefix}css/main.css?v=20260916-mobile-a">
<link rel="stylesheet" href="{prefix}css/mobile-fixes.css?v=20260916-mobile-a">
<link rel="stylesheet" href="{prefix}css/turner-network.css">
<link rel="stylesheet" href="{prefix}css/mobile-action-bar.css?v=20260917-mobile-action-bar">
<link rel="stylesheet" href="{prefix}css/favorites.css?v=20260605-favorites">
{style_block}
<script src="{prefix}js/analytics-events.js" defer></script>
<script src="{prefix}js/favorites.js?v=20260929-noprojected" defer></script>
</head>"""


# Days-on-market threshold for "NEW" badge






def build_listing_card(listing: dict, prefix: str) -> str:
    """One card for the grid view. prefix is the site-root prefix for the linked URL."""
    photos = listing.get("photos") or []
    # Address-aware alt for a11y (WCAG 1.1.1) + image SEO — was alt=""
    # (LISTING-CARD-EMPTY-ALT, 2026-06-04). e.g. "166 Airport Boulevard, Gander, NL".
    _street = (listing.get("street") or "").strip()
    _city = city_display_name(listing.get("city_slug") or "")
    _alt = ", ".join(p for p in (_street, _city, "NL") if p) or "Royal LePage Turner Realty listing"
    img_html = ""
    if photos:
        img_html = (
            f'<img src="{he(photos[0]["url"])}" alt="{he(_alt)}" loading="lazy" '
            'onerror="this.style.display=\'none\';this.parentElement.classList.add(\'lst-card-img--imgfail\')">'
        )
    else:
        img_html = '<div class="lst-card-noimg">No Photo</div>'

    # Conditional badge outranks "New" (task-#57 port 2026-07-17): a card can
    # be both, and "an offer is in play" is the load-bearing fact for a buyer.
    _card_status = ("" if listing.get("is_lease")
                    else (listing.get("status") or "").strip().lower())
    if "under contract" in _card_status or "sst" in _card_status:
        new_badge = '<span class="lst-card-pending">Accepted Offer</span>'
    else:
        new_badge = '<span class="lst-card-new">New</span>' if _is_new(listing) else ""

    meta_bits = []
    if listing.get("bedrooms") is not None:
        meta_bits.append(f'<span><strong>{listing["bedrooms"]}</strong>bd</span>')
    if listing.get("bathrooms") is not None:
        meta_bits.append(f'<span><strong>{fmt_bath(listing["bathrooms"])}</strong>ba</span>')
    if listing.get("living_area"):
        meta_bits.append(f'<span><strong>{int(listing["living_area"]):,}</strong>sq ft</span>')
    # Commercial + Land rows have no beds/baths/sqft — show the banded
    # property size + municipal zoning instead (100% populated on commercial
    # rows per the 2026-06-10 NLAR field audit; Conv #15 port of Gander pass).
    if not meta_bits:
        if listing.get("property_size"):
            meta_bits.append(f'<span><strong>{he(listing["property_size"])}</strong></span>')
        if listing.get("zoning"):
            meta_bits.append(f'<span>Zoning <strong>{he(listing["zoning"])}</strong></span>')
    meta_html = "".join(meta_bits)

    # The url_path on each listing starts with /listings/... — strip the leading /
    # then prepend the relative prefix from the current page location.
    rel_url = prefix + listing["url_path"].lstrip("/")
    city = city_display_name(listing["city_slug"])
    meta_block = f'<div class="lst-card-meta">{meta_html}</div>' if meta_html else ""

    # Per-card REALTOR.ca linkback gated post-IDX cutover (Convention #15
    # from Gander 2026-05-19). When _local_photos is True (NLAR direct feed),
    # suppress the badge — Angie Liang's locked guidance 2026-05-11: no DDF
    # "Powered by REALTOR.ca" badge required on NLAR-direct listings. DDF
    # fallback path keeps the badge for any listing without local photos.
    if listing.get("_local_photos"):
        realtor_badge = ""
    else:
        realtor_url = REALTOR_CA_LISTING_URL_TEMPLATE.format(listing_key=listing["mls"])
        realtor_badge = (
            f'<a class="lst-card-realtor" href="{he(realtor_url)}" '
            f'target="_blank" rel="noopener" '
            f'aria-label="View MLS® {he(listing["mls"])} on REALTOR.ca">'
            f'Powered by <strong>REALTOR.ca</strong>'
            f'</a>'
        )

    # Listing-agent recognition byline (Convention #15 byte-symmetric port from
    # stjohns-site 6ed6ca357 / 2026-05-20). When the listing's IDX agent matches
    # a Turner team member, surface "Listed by <Agent Name>" so the agent gets
    # recognition on every card placement. Convention #74 fail-safe — no
    # match keeps the card chrome clean (Goosebay's DDF feed still requires
    # the REALTOR.ca attribution badge below the card body for compliance).
    agent_record = match_turner_agent(listing.get("idx_list_agent_full_name"))
    if agent_record:
        team_byline = (
            f'<p class="lst-card-team">Listed by '
            f'<strong>{he(agent_record["name"])}</strong></p>'
        )
    else:
        # Default team byline for non-Turner-team listings (P3 task #22).
        # The Dynamic Duo (Karen Pomeroy + Roberta Primmer) handles buyer-side
        # inquiries for HVGB-area cards we did not list ourselves.
        # Convention #15 sibling pattern: Gander emits Turner Realty Team byline,
        # Avalon emits Chris Morrison's Team byline.
        team_byline = (
            '<p class="lst-card-team">Inquiries handled by '
            '<strong>Mike Turner, Broker</strong></p>'
        )

    return (
        # data-mls lets js/favorites.js bind the heart overlay on generator-emitted
        # cards too (community + /listings/ grids). Harmless where it isn't loaded.
        f'<article class="lst-card" data-mls="{he(str(listing["mls"]))}">'
        f'<a class="lst-card-link" href="{he(rel_url)}">'
        f'<div class="lst-card-img">{img_html}{new_badge}</div>'
        f'<div class="lst-card-body">'
        f'<p class="lst-card-price">{fmt_price(listing.get("list_price"), listing=listing)}</p>'
        f'<p class="lst-card-addr">{he(listing.get("street") or "")}</p>'
        f'<p class="lst-card-city">{he(city)}, NL</p>'
        f'{meta_block}'
        f'<p class="lst-card-mls">MLS® {he(listing["mls"])}</p>'
        f'{team_byline}'
        f'</div></a>'
        f'{realtor_badge}'
        f'</article>'
    )


def _sort_listings_for_display(listings: list[dict]) -> list[dict]:
    """Newest first, then price desc, then MLS."""
    def key(lst):
        ld = lst.get("list_date") or ""
        price = lst.get("list_price") or 0
        return (ld, price, lst.get("mls") or "")
    return sorted(listings, key=key, reverse=True)


# Sites 2026-10-09: ONE listing-count definition (tools/_fleet_listing_counts.py)
# for the homepage tab badges, the View-all link, the summary line, data.json and
# the /listings/ header. "As of" is the feed's own timestamp (set from the projected
# cache in main()), so two regens of the same data write identical bytes.
_COUNTS_AS_OF = None


def _site_counts(listings, as_of=None) -> dict:
    """available / conditional-pending / updated for the rows data.json carries
    (rows without lat/lng are dropped from the feed, so they are not counted)."""
    rows = [r for r in listings if r.get("latitude") is not None and r.get("longitude") is not None]
    return _lc.listing_counts(rows, as_of or _COUNTS_AS_OF or datetime.now(timezone.utc))


# Mike Turner (team-listings fragment). Module level since 2026-10-08 so the
# --counts-only refresh counts the same pool as _emit_team_listings_fragment.
TEAM_NAMES = {"mike turner"}


def _is_team(L) -> bool:
    raw = (L.get("idx_list_agent_full_name") or L.get("list_agent_name") or "").strip().lower()
    return raw in TEAM_NAMES


def _counts_only(listings, site_root: Path) -> int:
    """--counts-only (sites 2026-10-08): the hourly run's skipped-regen path.
    Recomputes the counts from the same filtered rows a regen would use and patches
    only the count outputs (tools/_fleet_listing_counts.py refresh_count_outputs);
    the workflow then runs the injector. A quiet run over the same data changes
    nothing; when the numbers moved without a feed change (the stale gate), "Updated"
    is this run's time."""
    c = _site_counts(listings)
    prev = None
    try:
        prev = json.loads((site_root / "listings" / "data.json").read_text()).get("counts")
    except (OSError, ValueError) as e:
        print(f"[counts] WARN: listings/data.json unreadable ({e}); writing fresh counts")
    if not _lc.same_numbers(prev, c):
        c = _site_counts(listings, as_of=datetime.now(timezone.utc))
    team_n = _lc.available_count([L for L in _sort_listings_for_display(listings) if _is_team(L)])
    changed = _lc.refresh_count_outputs(
        site_root, c,
        badges={"featured-listings-count": c["available"], "team-listings-count": team_n},
        viewall={"featured-listings": c["available"], "team-listings": team_n},
    )
    print(f"[counts] changed: {', '.join(changed) if changed else 'nothing (already current)'}")
    print(_lc.heartbeat(c, "skipped"))
    return 0


# ─── DDF fragment emit (Convention #15 byte-symmetric port from Gander) ───
# Added 2026-05-19 to fix NameError that broke Goosebay hourly + nightly since
# b2a77b6 (the original team-listings emit port). The previous port copied the
# call-site (_emit_team_listings_fragment in main()) but missed the constants +
# build_fragment() helper it depends on. Convention #109 propagation-depth gap.
FRAGMENT_DEFAULT_LIMIT = 6
FRAGMENT_DIR_NAME = "ddf-fragments"


def build_fragment(
    listings: list[dict],
    fragment_name: str,
    viewall_href: str,
    viewall_label: str,
    total_count: int,
    *,
    limit: int = FRAGMENT_DEFAULT_LIMIT,
    sort: bool = True,
) -> str:
    """Build one fragment body: a card grid plus a "View all" link.

    Output shape:
      <div class="ddf-fragment-grid" data-fragment="…" data-count="…" data-total="…">
        <article class="lst-card">…</article> × N
      </div>
      <p class="ddf-fragment-viewall"><a href="…">View all N listings →</a></p>

    `total_count` is the size of the unfiltered pool (before the `limit`
    cap). It's surfaced in the "View all N" link so the consumer knows
    they're clicking through to a larger set, and persisted in the
    `data-total` attribute for analytics / validators.
    """
    pool = _sort_listings_for_display(listings) if sort else list(listings)
    shown = pool[:limit]

    cards_html = "\n".join(build_listing_card(l, "/") for l in shown)
    if not cards_html:
        cards_html = (
            '<p class="ddf-fragment-empty">No active listings right now. '
            'Check back soon — inventory updates hourly.</p>'
        )

    viewall_html = ""
    if viewall_href and shown:
        viewall_html = (
            f'<p class="ddf-fragment-viewall">'
            f'<a href="{he(viewall_href)}">{he(viewall_label)} &rarr;</a>'
            f'</p>'
        )

    return (
        f'<div class="ddf-fragment-grid" '
        f'data-fragment="{he(fragment_name)}" '
        f'data-count="{len(shown)}" '
        f'data-total="{total_count}">\n'
        f'{cards_html}\n'
        f'</div>\n'
        f'{viewall_html}'
    )


def build_city_page(city_slug: str, listings: list[dict]) -> str:
    """City landing page at /listings/<city>/index.html (depth 2, prefix = ../../)."""
    prefix = "../../"
    city = city_display_name(city_slug)
    listings = _sort_listings_for_display(listings)
    count = len(listings)

    title = f"Homes for Sale in {city}, NL — Royal LePage Turner Realty"
    description = (
        f"Homes for sale in {city}, NL — {count} active MLS® listing{'s' if count != 1 else ''}, "
        f"updated daily from NLAR. Photos + direct inquiry via Royal LePage Turner Realty."
    )
    canonical = f"{SITE_ORIGIN}/listings/{city_slug}/"
    og_image = listings[0]["photos"][0]["url"] if (listings and listings[0].get("photos")) else f"{SITE_ORIGIN}/images/og/pages-listing-detail-og.jpg"

    cards = "\n".join(build_listing_card(l, prefix) for l in listings)
    if not cards:
        cards = '<div class="lst-empty">No active listings in this area right now. Check back soon.</div>'

    crumb = (
        f'<nav style="max-width:1200px;margin:24px auto 0;padding:0 20px;font-size:0.85rem;color:rgba(255,255,255,0.5);font-family:\'Roboto\',sans-serif;">'
        f'<a href="{prefix}index.html" style="color:rgba(255,255,255,0.5);">Home</a> &rsaquo; '
        f'<a href="{prefix}listings/index.html" style="color:rgba(255,255,255,0.5);">Listings</a> &rsaquo; '
        f'<span style="color:#EA002A;">{he(city)}</span>'
        f'</nav>'
    )

    jsonld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": title,
        "description": description,
        "url": canonical,
        "about": {"@type": "Place", "name": f"{city}, Newfoundland and Labrador, Canada"},
        "numberOfItems": count,
    }

    breadcrumb_jsonld = build_breadcrumb_jsonld([
        ("Home", f"{SITE_ORIGIN}/"),
        ("Listings", f"{SITE_ORIGIN}/listings/"),
        (city, canonical),
    ])

    return f"""<!DOCTYPE html>
<html lang="en">
{head_block_simple(title, description, canonical, og_image, prefix)}
<body>
{nav_html(prefix)}

<div class="lst-shell">

<div id="lst-recently-viewed" style="display:none"></div>

{crumb}

<header class="lst-index-head">
  <p class="lst-eyebrow">Communities · {he(city)}</p>
  <h1>Homes for Sale in {he(city)}, NL</h1>
  <p class="lst-sub">Every active MLS® listing currently in {he(city)} — updated daily from NLAR. Inquire on any listing. {he(REPLY_PROMISE)}{_city_ms_link(city_slug, he(city), prefix)}</p>
  <p class="lst-count">{count} active listing{'s' if count != 1 else ''}</p>
</header>

<div class="lst-card-grid">
{cards}
</div>


{build_keep_exploring(prefix)}

<div class="lst-ddr">
  <p>{he(DDR_DISCLAIMER)}</p>
  <p>{he(TRADEMARK_NOTICE)}</p>
</div>

</div>

{footer_html(prefix)}

<script type="application/ld+json">{ja(jsonld)}</script>
{breadcrumb_jsonld}

<script src="{prefix}js/footer.js?v=20260909-footer-converge"></script>
<script src="{prefix}js/regions-data.js" defer></script>
<script src="{prefix}js/nav-config.js" defer></script>
<script src="{prefix}js/nav-config-listings.js" defer></script>
<script>window.TURNER_SITE='{_SITE_CFG["site_key"]}';window.TURNER_API_ORIGIN='{_SITE_CFG["api_url"]}';</script>
<script src="{prefix}js/nav.js?v=20260913-mobile-nav-fix" defer></script>
<script src="{prefix}js/mobile-action-bar.js?v=20260917-mobile-action-bar" defer></script>
{_nav_auth_script(prefix)}
<script src="{prefix}js/app-shell.js?v=20260920-app8" defer></script>
<script src="{prefix}js/turner-network.js" defer></script>
{_chat_script(prefix)}
{lta_band(city)}
<script src="/js/alert-inline.js?v=20260724-lta-city" defer></script>
<script src="{prefix}js/recently-viewed.js" defer></script>
<script>
document.addEventListener("DOMContentLoaded", function () {{
  if (window.RecentlyViewed) window.RecentlyViewed.renderTo("lst-recently-viewed");
}});
</script>
</body>
</html>
"""


# ═══════════════════════════════════════════════════════════════════
#  COMMERCIAL LEAD CAPTURE — /listings/commercial/  (2026-07-24)
# ═══════════════════════════════════════════════════════════════════
# The commercial rollup shipped with NO capture: a tel: link and (on the
# siblings) a raw untracked mailto:. Chris landed a commercial showing
# lead off this surface anyway on 2026-07-24, which is what prompted it —
# the page converts, it just wasn't measured or routed.
#
# Routing (Mike 2026-07-24): Avalon -> Chris, Gander -> Mike, Goosebay ->
# the Duo. Goosebay leaves data-agent-email EMPTY so lead-receive's
# goosebayDefaultSlug() round-robins Karen/Roberta — the same
# fall-through the Duo community cards use.
#
# Agent NAP is read from TURNER_AGENT_CARD (canonical agent_roster.json)
# rather than hand-typed — Conv #148.
COMMERCIAL_CONTACT = {
    # Goose Bay posts as the Dynamic Duo. agent_name stays EMPTY so
    # data-agent-email renders blank and lead-receive's
    # goosebayDefaultSlug() round-robins Karen/Roberta — the same
    # fall-through the Duo community cards use.
    "agent_name":   "Mike Turner",
    "display_name": "Mike Turner, Broker",
    "short_name":   "Mike",
    "team_email":   "miketurner@royallepage.ca",
    "office_phone": "709-256-7999",
    "market":       "Labrador City & Wabush",
}


def build_commercial_cta_section(prefix: str) -> str:
    """Lead-capture band for the commercial rollup.

    Conv #74: every lookup degrades to the team email / office phone and
    the tel: fallback stays in the markup, so a roster miss or a JS
    failure still leaves a reachable contact path — never a dead end.
    Inline styles only (no new classes) so pre-deploy Check #20 can't
    red-line the regen on an undefined selector.
    """
    cfg = COMMERCIAL_CONTACT
    name = (cfg.get("agent_name") or "").strip()
    rec = TURNER_AGENT_CARD.get(name) or {}
    agent_email = rec.get("email") or ""
    agent_slug = rec.get("slug") or ""
    digits = "".join(ch for ch in (rec.get("phone") or "") if ch.isdigit())
    phone = (f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
             if len(digits) == 10 else (cfg.get("office_phone") or ""))
    team_email = cfg.get("team_email") or ""
    market = cfg.get("market") or "Newfoundland and Labrador"
    display = (cfg.get("display_name") or name or "our commercial team")
    short = (cfg.get("short_name") or (name.split(" ")[0] if name else "us"))
    tel_digits = "".join(ch for ch in phone if ch.isdigit())

    return (
        '\n<section id="commercial-contact" style="max-width:1200px;margin:48px auto 0;'
        'padding:0 20px;">'
        '<div style="background:#141414;border:1px solid #2a2a2a;border-radius:10px;'
        'padding:28px 24px;">'
        '<h2 style="margin:0 0 6px;font-size:1.35rem;color:#fff;">'
        'Talk to someone who actually transacts commercial</h2>'
        f'<p style="margin:0 0 22px;color:#b9b9b9;max-width:62ch;line-height:1.55;">'
        f'Commercial in {he(market)} is a small market with few active buyers and '
        f'fewer agents who work it. Tell {he(short)} what you need and '
        f'you&rsquo;ll get a straight answer &mdash; including when the answer is '
        f'&ldquo;nothing on the market fits yet.&rdquo; '
        f'Prefer the phone? <a href="tel:{he(tel_digits)}" style="color:#ff6b7a;">'
        f'{he(phone)}</a>.</p>'
        f'<div id="lst-commercial-inquiry"'
        f' data-agent-name="{he(display)}"'
        f' data-agent-email="{he(agent_email)}"'
        f' data-agent-slug="{he(agent_slug)}"'
        f' data-agent-phone="{he(phone)}"'
        f' data-team-email="{he(team_email)}"'
        f' data-market="{he(market)}"></div>'
        '</div></section>\n'
        f'<script src="{prefix}js/boldtrail-forms.js" defer></script>\n'
        '<script>document.addEventListener("DOMContentLoaded",function(){'
        'try{if(window.BoldTrailForms&&BoldTrailForms.commercialInquiry)'
        'BoldTrailForms.commercialInquiry("#lst-commercial-inquiry");}catch(e){}});'
        '</script>\n'
    )


def build_rollup_page(cfg: dict, matching: list[dict]) -> str:
    """Filtered-collection landing page at /listings/<slug>/index.html (depth 2).

    Mirrors the visual structure of `build_city_page` so the three rollup
    pages feel like a natural sibling of the city landings — same shell,
    same card grid, same DDR + keep-exploring block.
    """
    prefix = "../../"
    commercial_cta_html = (
        build_commercial_cta_section(prefix)
        if cfg["slug"] == "commercial" else ""
    )
    listings = sorted(matching, key=cfg["sort_key"])
    count = len(listings)

    title = (
        f"{cfg['display']} in Labrador City & Wabush — "
        f"{count} Active | Royal LePage Turner Realty"
    )
    description = (
        f"{count} active {cfg['display'].lower()} in Labrador City "
        f"and Wabush. Live MLS® data from NLAR via Royal "
        f"LePage Turner Realty."
    )
    canonical = f"{SITE_ORIGIN}/listings/{cfg['slug']}/"
    og_image = (
        listings[0]["photos"][0]["url"]
        if (listings and listings[0].get("photos"))
        else f"{SITE_ORIGIN}/images/og/pages-listing-detail-og.jpg"
    )

    cards = "\n".join(build_listing_card(l, prefix) for l in listings)
    if not cards:
        # Empty-state still renders a full page so the URL is stable and
        # sweep doesn't 301 it away. Copy is deliberately gentle — it's a
        # normal condition for a low-volume market like commercial NL.
        cards = (
            '<div class="lst-empty">No active listings matching this '
            'category right now. Check back soon — inventory updates '
            'daily.</div>'
        )

    crumb = (
        f'<nav style="max-width:1200px;margin:24px auto 0;padding:0 20px;'
        f'font-size:0.85rem;color:rgba(255,255,255,0.5);'
        f'font-family:\'Roboto\',sans-serif;">'
        f'<a href="{prefix}index.html" style="color:rgba(255,255,255,0.5);">Home</a> &rsaquo; '
        f'<a href="{prefix}listings/index.html" style="color:rgba(255,255,255,0.5);">Listings</a> &rsaquo; '
        f'<span style="color:#EA002A;">{he(cfg["display"])}</span>'
        f'</nav>'
    )

    jsonld = {
        "@context":      "https://schema.org",
        "@type":         "CollectionPage",
        "name":          title,
        "description":   description,
        "url":           canonical,
        "about":         {"@type": "Place", "name": "Labrador City and Wabush, Newfoundland and Labrador, Canada"},
        "numberOfItems": count,
    }

    breadcrumb_jsonld = build_breadcrumb_jsonld([
        ("Home",          f"{SITE_ORIGIN}/"),
        ("Listings",      f"{SITE_ORIGIN}/listings/"),
        (cfg["display"],  canonical),
    ])

    return f"""<!DOCTYPE html>
<html lang="en">
{head_block_simple(title, description, canonical, og_image, prefix)}
<body>
{nav_html(prefix)}

<div class="lst-shell">

<div id="lst-recently-viewed" style="display:none"></div>

{crumb}

<header class="lst-index-head">
  <p class="lst-eyebrow">{he(cfg["eyebrow"])}</p>
  <h1>{he(cfg["headline"])}</h1>
  <p class="lst-sub">{he(cfg["sub"])}</p>
  <p class="lst-count">{count} active listing{'s' if count != 1 else ''}</p>
</header>

<div class="lst-card-grid">
{cards}
</div>

{commercial_cta_html}

{build_keep_exploring(prefix)}

<div class="lst-ddr">
  <p>{he(DDR_DISCLAIMER)}</p>
  <p>{he(TRADEMARK_NOTICE)}</p>
</div>

</div>

{footer_html(prefix)}

<script type="application/ld+json">{ja(jsonld)}</script>
{breadcrumb_jsonld}

<script src="{prefix}js/footer.js?v=20260909-footer-converge"></script>
<script src="{prefix}js/regions-data.js" defer></script>
<script src="{prefix}js/nav-config.js" defer></script>
<script src="{prefix}js/nav-config-listings.js" defer></script>
<script>window.TURNER_SITE='{_SITE_CFG["site_key"]}';window.TURNER_API_ORIGIN='{_SITE_CFG["api_url"]}';</script>
<script src="{prefix}js/nav.js?v=20260913-mobile-nav-fix" defer></script>
<script src="{prefix}js/mobile-action-bar.js?v=20260917-mobile-action-bar" defer></script>
{_nav_auth_script(prefix)}
<script src="{prefix}js/app-shell.js?v=20260920-app8" defer></script>
<script src="{prefix}js/turner-network.js" defer></script>
{_chat_script(prefix)}
{LTA_INLINE_BAND}
<script src="/js/alert-inline.js?v=20260724-lta-city" defer></script>
<script src="{prefix}js/recently-viewed.js" defer></script>
<script>
document.addEventListener("DOMContentLoaded", function () {{
  if (window.RecentlyViewed) window.RecentlyViewed.renderTo("lst-recently-viewed");
}});
</script>
</body>
</html>
"""


def build_index_page(
    all_listings: list[dict],
    by_city: dict[str, list[dict]],
    by_rollup: dict[str, list[dict]] | None = None,
) -> str:
    """Top-level /listings/index.html (depth 1, prefix = ../).

    `by_rollup` (new in task #69) is optional — when supplied, a second
    chip row above the city chips links into the filtered rollup pages
    (new construction, first-time buyer, commercial). Omitting it keeps
    the old behaviour for callers that haven't been updated yet.
    """
    prefix = "../"
    listings = _sort_listings_for_display(all_listings)
    count = len(listings)
    recent = listings[:24]   # newest 24 on front page of index
    by_rollup = by_rollup or {}

    title = f"MLS® Listings in Labrador City & Wabush — {count} Active | Royal LePage Turner Realty"
    description = (
        f"{count} active MLS® listings across Labrador City and Wabush. "
        f" Live data from NLAR — updated daily. Browse by "
        f"community, view photos, and inquire directly with Royal LePage Turner Realty."
    )
    canonical = f"{SITE_ORIGIN}/listings/"
    og_image = recent[0]["photos"][0]["url"] if (recent and recent[0].get("photos")) else f"{SITE_ORIGIN}/images/og/pages-listing-detail-og.jpg"

    # City chips, sorted by count desc, name asc.
    # Cap: only render cities with >= CHIP_MIN_COUNT active listings to
    # avoid the wall-of-chips problem. Goosebay at ~18 active listings
    # has minimal long tail today but the cap is defensive future-
    # proofing as the HVGB feed grows.
    # Mirror of stjohns/aec2fd89 2026-04-28; Convention #15 propagation.
    CHIP_MIN_COUNT = 3
    chip_cities = [
        (slug, lst) for slug, lst in
        sorted(by_city.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        if len(lst) >= CHIP_MIN_COUNT
    ]
    hidden_cities = [
        (slug, lst) for slug, lst in by_city.items()
        if len(lst) < CHIP_MIN_COUNT
    ]
    city_chips_html = "".join(
        f'<a href="{prefix}listings/{slug}/index.html">{he(city_display_name(slug))} <span>{len(lst)}</span></a>'
        for slug, lst in chip_cities
    )
    n_hidden = len(hidden_cities)
    if n_hidden > 0:
        n_hidden_listings = sum(len(lst) for slug, lst in hidden_cities)
        city_chips_html += (
            f'<a href="{prefix}listings/" '
            f'style="opacity:0.7;" title="See all communities below">'
            f'+ {n_hidden} more towns <span>{n_hidden_listings}</span></a>'
        )

    # Rollup chips (task #69): "Browse by type" row above the town chips.
    # Renders in ROLLUPS declaration order so the row is stable regardless
    # of count. Rollups with zero matches are skipped — we don't want to
    # entice a click into an empty-state page from the front door.
    rollup_chips_html = "".join(
        f'<a href="{prefix}listings/{r["slug"]}/index.html">'
        f'{he(r["display"])} <span>{len(by_rollup.get(r["slug"], []))}</span>'
        f'</a>'
        for r in ROLLUPS
        if by_rollup.get(r["slug"])
    )
    rollup_chips_block = (
        f'\n<nav class="lst-city-chips" aria-label="Browse by type" '
        f'style="margin-bottom:8px;">\n{rollup_chips_html}\n</nav>\n'
        if rollup_chips_html else ""
    )

    cards = "\n".join(build_listing_card(l, prefix) for l in recent)

    crumb = (
        f'<nav style="max-width:1200px;margin:24px auto 0;padding:0 20px;font-size:0.85rem;color:rgba(255,255,255,0.5);font-family:\'Roboto\',sans-serif;">'
        f'<a href="{prefix}index.html" style="color:rgba(255,255,255,0.5);">Home</a> &rsaquo; '
        f'<span style="color:#EA002A;">Listings</span>'
        f'</nav>'
    )

    jsonld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": title,
        "description": description,
        "url": canonical,
        "about": {"@type": "Place", "name": "Labrador City and Wabush, Newfoundland and Labrador, Canada"},
        "numberOfItems": count,
    }

    breadcrumb_jsonld = build_breadcrumb_jsonld([
        ("Home", f"{SITE_ORIGIN}/"),
        ("Listings", canonical),
    ])

    # ── Full-inventory search index (Convention #15 from stjohns-site) ──
    # The 24 newest cards on /listings/ cover only a fraction of the active
    # inventory. Inline JSON projection of every listing lets js/listings-
    # filter.js deliver on the homepage form's ?q=<text> promise for any
    # listing, not just the visible 24. Minimal projection keeps payload
    # small (~250 bytes/listing × ~20 listings on Goosebay = ~5KB inline).
    search_index = []
    for L in all_listings:
        url_path = L.get("url_path") or ""
        mls = L.get("mls")
        if not (mls and url_path):
            continue
        search_index.append({
            "mls":   str(mls),
            "url":   url_path,
            "addr":  L.get("street") or "",
            "city":  city_display_name(L.get("city_slug") or ""),
            "price": L.get("list_price"),
            "beds":  L.get("bedrooms"),
            "baths": L.get("bathrooms"),
            "ptype": L.get("property_type") or "",
        })
    search_index_json = json.dumps(search_index, separators=(',', ':'), ensure_ascii=True)

    return f"""<!DOCTYPE html>
<html lang="en">
{head_block_simple(title, description, canonical, og_image, prefix)}
<body>
{nav_html(prefix)}

<div class="lst-shell">

{crumb}

<header class="lst-index-head">
  <p class="lst-eyebrow">Live MLS® Data · {count} Active Listings</p>
  <h1>MLS® Listings in Labrador City &amp; Wabush</h1>
  <p class="lst-sub">Every active home-for-sale MLS® listing in Labrador City and Wabush. Updated daily from NLAR. Browse by category, by community, or scroll for the newest below.</p>
</header>
{rollup_chips_block}
<nav class="lst-city-chips" aria-label="Browse by town">
{city_chips_html}
</nav>

<header class="lst-index-head" style="margin-top:40px;">
  <p class="lst-eyebrow">Recently Listed</p>
  <h1 style="font-size:clamp(1.4rem,2.5vw,1.8rem);">Newest on the Market</h1>
  <p class="lst-sub">The 24 most recently listed properties across our coverage area.</p>
</header>

<div class="lst-card-grid">
{cards}
</div>

{build_keep_exploring(prefix)}

<div class="lst-ddr">
  <p>{he(DDR_DISCLAIMER)}</p>
  <p>{he(TRADEMARK_NOTICE)}</p>
</div>

</div>

{footer_html(prefix)}

<script type="application/ld+json">{ja(jsonld)}</script>
{breadcrumb_jsonld}

<!-- Full-inventory search index (Convention #15 from stjohns-site). Consumed
     by js/listings-filter.js to deliver the homepage form's ?q=<text>
     promise on listings outside the visible 24-card newest set. -->
<script type="application/json" id="lst-search-index">{search_index_json}</script>

<script src="{prefix}js/footer.js?v=20260909-footer-converge"></script>
<script src="{prefix}js/listings-filter.js?v=20260516-result-cards" defer></script>
<script src="{prefix}js/regions-data.js" defer></script>
<script src="{prefix}js/nav-config.js" defer></script>
<script src="{prefix}js/nav-config-listings.js" defer></script>
<script>window.TURNER_SITE='{_SITE_CFG["site_key"]}';window.TURNER_API_ORIGIN='{_SITE_CFG["api_url"]}';</script>
<script src="{prefix}js/nav.js?v=20260913-mobile-nav-fix" defer></script>
<script src="{prefix}js/mobile-action-bar.js?v=20260917-mobile-action-bar" defer></script>
{_nav_auth_script(prefix)}
<script src="{prefix}js/app-shell.js?v=20260920-app8" defer></script>
<script src="{prefix}js/turner-network.js" defer></script>
{_chat_script(prefix)}
</body>
</html>
"""


def build_sitemap(
    all_listings: list[dict],
    by_city: dict[str, list[dict]],
    by_rollup: dict[str, list[dict]] | None = None,
    sold_city_slugs: list[str] | None = None,
) -> str:
    """sitemap-listings.xml — indexes the /listings/ tree for search engines.

    `by_rollup` (new in task #69) is optional. When supplied, rollup
    landing pages are emitted at priority 0.85 (between the all-listings
    index at 0.9 and individual city landings at 0.8) — they aggregate
    inventory across the whole network so they outrank a single town.
    """
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    entries = []
    # Top-level index
    entries.append((f"{SITE_ORIGIN}/listings/", now_date, "daily", "0.9"))
    # Rollup landings (always present — empty rollups still render an index)
    for slug in sorted((by_rollup or {}).keys()):
        entries.append((f"{SITE_ORIGIN}/listings/{slug}/", now_date, "daily", "0.85"))
    # City landings
    for slug in sorted(by_city.keys()):
        entries.append((f"{SITE_ORIGIN}/listings/{slug}/", now_date, "daily", "0.8"))
    # Per-city sold rollups (SEO Forward Plan Tier 2 item E, 2026-08-05 --
    # Conv #15 port from Avalon 2026-05-21 PM). Priority 0.75 -- between
    # rollup landings (0.85) and city landings (0.8) since these are
    # paywall-content pages aggregating sold inventory per city.
    for slug in sorted(sold_city_slugs or []):
        entries.append((f"{SITE_ORIGIN}/listings/sold/{slug}/", now_date, "weekly", "0.75"))
    # The parent /listings/sold/ landing itself (paywall-content but indexable)
    if sold_city_slugs:
        entries.append((f"{SITE_ORIGIN}/listings/sold/", now_date, "daily", "0.85"))
    # Detail pages — use modification_timestamp where available for lastmod
    for l in all_listings:
        lastmod = (l.get("modification_timestamp") or l.get("list_date") or "")[:10] or now_date
        entries.append((f"{SITE_ORIGIN}{l['url_path']}", lastmod, "weekly", "0.7"))

    url_xml = "\n".join(
        f"  <url>\n"
        f"    <loc>{he(loc)}</loc>\n"
        f"    <lastmod>{he(lastmod)}</lastmod>\n"
        f"    <changefreq>{chg}</changefreq>\n"
        f"    <priority>{pri}</priority>\n"
        f"  </url>"
        for loc, lastmod, chg, pri in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{url_xml}\n"
        '</urlset>\n'
    )


# ═══════════════════════════════════════════════════════════════════
#  STALE-PAGE SWEEP — delete sold/withdrawn listings, 301 to city page
# ═══════════════════════════════════════════════════════════════════
#
# When a listing comes off the CREA DDF feed (sold, withdrawn, expired),
# the previous generator left its HTML on disk forever. That's a bug:
#   * Consumers get a live page for a property that's no longer available.
#   * Google keeps the URL indexed, so the SERP result 404s in perception.
#   * Stale URLs accumulate in the sitemap.
#
# This sweep:
#   1. Computes the set of URLs we EXPECT to write this run (current cache).
#   2. Scans /listings/ for every HTML file actually on disk.
#   3. Anything on disk but not expected = stale → delete it + register a
#      301 redirect to the city landing page (or /listings/ if the city is
#      also empty).
#   4. Persists every swept URL in tools/ddf-cache/swept-listings.json so
#      the redirect survives future runs (the stale HTML is gone, but the
#      redirect has to keep forwarding forever for SEO).
#   5. Regenerates the managed block in <site_root>/_redirects from the
#      full swept-cache on every run — Netlify reads this file at deploy.
#
# Why 301 instead of 410 Gone?
#   A sold-listing URL has earned backlinks and accumulated SEO equity on
#   OUR domain. A 301 to the city collection page consolidates that equity
#   onto a live indexed page with current inventory — consumers who click
#   the stale SERP result see a useful page. A 410 would deindex the URL
#   entirely and throw the backlink value away.
#
# Reactivation:
#   If an MLS number that was previously swept reappears in the cache
#   (same city, same slug → same URL), we REMOVE it from the swept cache
#   so the redirect goes away and the live detail page wins.

_REDIRECTS_BEGIN_MARKER = "# BEGIN DDF-SWEEP MANAGED BLOCK (regenerated by ddf-generate-pages.py — do not hand-edit)"
_REDIRECTS_END_MARKER = "# END DDF-SWEEP MANAGED BLOCK"




def _load_swept_cache() -> dict:
    """Load tools/ddf-cache/swept-listings.json.
    Structure: {source_url: {"target_url": str, "swept_at": iso-datetime, "city_slug": str}}

    Includes a backward-compat migration: every detail-URL entry MUST carry both
    extensionless AND .html variants in _redirects, because Google indexes
    listing URLs WITH .html (matching the canonical sitemap), but earlier code
    only registered the extensionless form. Netlify does exact-match on
    _redirects rules — so missing .html variant = silent 404 instead of 301
    on every Google-indexed swept listing. Convention #18 silent-degraded-output
    bug fixed 2026-05-21. The migration auto-adds the .html variant for any
    extensionless detail entry that doesn't have one already.
    """
    p = _swept_cache_path()
    if not p.exists():
        return {}
    try:
        swept = json.loads(p.read_text())
    except Exception as e:
        print(f"[SWEEP] WARNING: swept cache corrupted, starting fresh: {e}")
        return {}
    # Migration: ensure every detail-URL entry has both extensionless + .html variants
    additions = {}
    for url, meta in swept.items():
        if not url.startswith("/listings/"):
            continue
        if url.endswith("/") or url.endswith(".html"):
            continue
        parts = url.split("/")
        if len(parts) != 4 or not parts[2] or not parts[3]:
            continue
        html_url = url + ".html"
        if html_url not in swept:
            additions[html_url] = dict(meta)
    if additions:
        swept.update(additions)
    return swept




def _write_redirects_block(site_root: Path, swept: dict) -> int:
    """Rewrite the managed block in <site_root>/_redirects from the full
    swept cache. Preserves anything outside the markers verbatim.
    Returns the number of redirects written."""
    redirects_path = site_root / "_redirects"
    existing = redirects_path.read_text() if redirects_path.exists() else ""

    # Strip any previous managed block (everything between markers, inclusive).
    if _REDIRECTS_BEGIN_MARKER in existing:
        before, _, rest = existing.partition(_REDIRECTS_BEGIN_MARKER)
        _, _, after = rest.partition(_REDIRECTS_END_MARKER)
        existing = before.rstrip() + ("\n" + after.lstrip() if after.strip() else "\n")
    existing = existing.rstrip()

    if not swept:
        # Nothing to manage. Write back just the preserved content (if any).
        if existing:
            redirects_path.write_text(existing + "\n")
        elif redirects_path.exists():
            redirects_path.write_text("")
        return 0

    lines = [_REDIRECTS_BEGIN_MARKER, ""]
    # Sort by source URL for stable diffs
    for source_url in sorted(swept.keys()):
        target_url = swept[source_url]["target_url"]
        # Netlify format: <from>  <to>  <status>
        lines.append(f"{source_url}  {target_url}  301")
    lines.append("")
    lines.append(_REDIRECTS_END_MARKER)

    managed_block = "\n".join(lines)
    if existing:
        content = existing + "\n\n" + managed_block + "\n"
    else:
        content = managed_block + "\n"

    redirects_path.write_text(content)
    return len(swept)


def _sweep_stale_listings(
    site_root: Path,
    listings_dir: Path,
    current_listings: list[dict],
    by_city: dict[str, list[dict]],
    verbose: bool = False,
    rollup_slugs: frozenset[str] | set[str] | None = None,
    pending_listings: list[dict] | None = None,
) -> dict:
    """Delete listing HTML files on disk that aren't in the current cache,
    register 301 redirects for them, and rewrite the managed _redirects block.
    Returns a summary dict.

    `rollup_slugs` (task #69) lists the filtered-collection slugs whose
    `/listings/<slug>/index.html` pages must be preserved even though the
    sweep sees them as "not a city". Without this guard, every generator
    run would 301-redirect rollup pages away on the first pass.
    """
    rollup_slugs = frozenset(rollup_slugs or ())

    # Expected file paths for this run
    expected_detail_paths: set[Path] = set()
    expected_detail_urls: set[str] = set()
    for lst in current_listings:
        p = listings_dir / lst["city_slug"] / f"{lst['slug']}.html"
        expected_detail_paths.add(p)
        # URL without .html, trailing-slash style matches canonical
        expected_detail_urls.add(f"/listings/{lst['city_slug']}/{lst['slug']}")
        expected_detail_urls.add(f"/listings/{lst['city_slug']}/{lst['slug']}.html")

    # Sale-pending: protect the page AND let the reactivation loop below clear
    # the 301 left from when this listing was swept on going firm. Most of these
    # WERE swept, so without the URL registration the freshly-written page would
    # sit behind its own stale redirect.
    for lst in (pending_listings or []):
        try:
            expected_detail_paths.add(
                listings_dir / lst["city_slug"] / f"{lst['slug']}.html")
            expected_detail_urls.add(f"/listings/{lst['city_slug']}/{lst['slug']}")
            expected_detail_urls.add(f"/listings/{lst['city_slug']}/{lst['slug']}.html")
        except Exception:
            continue

    expected_city_indexes: set[Path] = {
        listings_dir / slug / "index.html" for slug in by_city.keys()
    }
    # Top-level /listings/index.html is always kept
    expected_city_indexes.add(listings_dir / "index.html")
    # Rollup indexes are always kept regardless of match count — empty
    # rollups render an empty-state page so the URL stays stable.
    for rslug in rollup_slugs:
        expected_city_indexes.add(listings_dir / rslug / "index.html")

    # Reserved hand-authored subdirs (Conv #15 port of Gander 9c21cf9 /
    # Avalon bf0f23d45, 2026-06-11): the sold canary pages are hand-authored,
    # NOT generator-emitted — without this the sweep deletes them (the exact
    # bug from the Avalon sold-canary launch).
    expected_city_indexes.add(listings_dir / "sold" / "index.html")
    expected_city_indexes.add(listings_dir / "sold" / "detail.html")
    # "compare" (2026-10-09, COMPARE_V2): listings/compare/index.html is emitted by tools/build-compare-page.py, not by this generator;
    # without this the sweep would delete it and 301 /listings/compare/ to /listings/ (the Gander failure of 2026-05-19, D-1008-31).
    expected_city_indexes.add(listings_dir / "compare" / "index.html")

    expected_all = expected_detail_paths | expected_city_indexes

    # Actual HTML files on disk
    actual_html = set(listings_dir.rglob("*.html")) if listings_dir.exists() else set()

    stale_paths = sorted(actual_html - expected_all)

    # Load persistent swept cache
    swept = _load_swept_cache()

    # Handle reactivation: any URL currently in swept-cache that is now expected
    # (listing came back on the market under the same slug, or a rollup was
    # re-enabled after a --no-rollups run) → remove the 301.
    #
    # Rollup reactivation closes the foot-gun where testing the generator with
    # --no-rollups writes 301s for `/listings/<rollup>/` because the sweep can't
    # tell rollup indexes from stale city indexes without the slug set. When the
    # next normal run brings the rollup back, its URL lands here and the stale
    # 301 gets cleared.
    expected_rollup_urls: set[str] = {f"/listings/{rslug}/" for rslug in rollup_slugs}
    # Sold canary URLs reactivate (clear any stale 301) — Conv #15 port 2026-06-11
    expected_rollup_urls |= {"/listings/sold/", "/listings/sold/detail", "/listings/sold/detail.html"}
    expected_rollup_urls.add("/listings/compare/")
    reactivated = 0
    for url in list(swept.keys()):
        if url in expected_detail_urls or url in expected_rollup_urls:
            del swept[url]
            reactivated += 1
            if verbose:
                print(f"  [sweep] REACTIVATED {url} — removed 301")

    detail_removed = 0
    city_indexes_removed = 0
    newly_swept: list[str] = []

    for path in stale_paths:
        rel = path.relative_to(listings_dir)
        parts = rel.parts
        if len(parts) == 1:
            # Top-level file in /listings/ other than index.html — leave alone
            if verbose:
                print(f"  [sweep] skipping top-level file: {rel}")
            continue
        if len(parts) != 2:
            # Deeper nested than /listings/<city>/<slug>.html — unexpected, skip
            if verbose:
                print(f"  [sweep] skipping deeply-nested file: {rel}")
            continue
        city_slug, filename = parts
        is_city_index = filename == "index.html"

        if is_city_index:
            source_urls = [f"/listings/{city_slug}/"]
        else:
            # Register BOTH URL variants — extensionless (canonical sitemap form)
            # AND .html (what Google has indexed). Netlify does exact-match on
            # _redirects rules; without both, the .html variant 404s instead of
            # 301'ing. Convention #18 silent-degraded-output bug fixed 2026-05-21
            # — see _load_swept_cache() docstring for the matching backward-compat
            # migration that handles historical extensionless-only entries.
            source_urls = [
                f"/listings/{city_slug}/{filename[:-5]}",  # extensionless
                f"/listings/{city_slug}/{filename}",       # with .html
            ]

        # Target: city landing if it still exists, else /listings/ top-level
        if city_slug in by_city:
            target_url = f"/listings/{city_slug}/"
        else:
            target_url = "/listings/"

        for source_url in source_urls:
            # Don't redirect to self (can happen if a city index becomes stale and
            # the city has no listings — target is /listings/, source is the city
            # path; that's fine and non-circular.)
            if source_url == target_url:
                if verbose:
                    print(f"  [sweep] skipping self-redirect: {source_url}")
                continue
            swept[source_url] = {
                "target_url": target_url,
                "swept_at": datetime.now(timezone.utc).isoformat(),
                "city_slug": city_slug,
            }
            newly_swept.append(source_url)

        try:
            path.unlink()
        except Exception as e:
            print(f"[SWEEP] WARNING: could not delete {path}: {e}")
            continue

        if is_city_index:
            city_indexes_removed += 1
        else:
            detail_removed += 1
        if verbose:
            print(f"  [sweep] removed {rel} → 301 {source_url} → {target_url}")

    # Remove empty city directories left behind (tidy-up)
    empty_dirs_removed = 0
    if listings_dir.exists():
        for child in sorted(listings_dir.iterdir()):
            if child.is_dir():
                try:
                    if not any(child.iterdir()):
                        child.rmdir()
                        empty_dirs_removed += 1
                        if verbose:
                            print(f"  [sweep] removed empty dir {child.relative_to(listings_dir)}/")
                except Exception:
                    pass

    # Persist swept cache and rewrite _redirects
    _save_swept_cache(swept)
    total_redirects = _write_redirects_block(site_root, swept)

    return {
        "detail_pages_removed": detail_removed,
        "city_indexes_removed": city_indexes_removed,
        "empty_dirs_removed": empty_dirs_removed,
        "newly_swept_urls": len(newly_swept),
        "reactivated_urls": reactivated,
        "total_redirects_in_file": total_redirects,
    }






def _prune_dead_hub_links(site_root: Path) -> int:
    """Drop already-dead <li> links from listings/index.html's hand-authored
    <ul class="lst-hub-newest"> "Newest listings" block — entries whose target
    detail page was swept (listing sold / off-market). Runs AFTER the sweep and
    BEFORE the self-check so a sold listing in this STATIC block can never freeze
    the whole deploy on a broken-link error (task #77; froze Avalon 2026-06-24 +
    06-26). Keeps every VALID crawlable link (no SEO downside). Convention #74:
    any parse hiccup leaves the file untouched. Returns count pruned."""
    idx = site_root / "listings" / "index.html"
    if not idx.exists():
        return 0
    try:
        html = idx.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return 0
    m = re.search(r'<ul class="lst-hub-newest">.*?</ul>', html, re.S)
    if not m:
        return 0
    block = m.group(0)
    pruned = []
    def _keep(li_m):
        li = li_m.group(0)
        hm = re.search(r'href="([^"]+)"', li)
        if hm:
            rel = hm.group(1).split("?", 1)[0].split("#", 1)[0].lstrip("/")
            if rel and not (site_root / rel).exists():
                pruned.append(hm.group(1))
                return ""   # drop this <li> (and its leading whitespace)
        return li
    new_block = re.sub(r"\s*<li\b.*?</li>", _keep, block, flags=re.S)
    if not pruned:
        return 0
    idx.write_text(html[:m.start()] + new_block + html[m.end():], encoding="utf-8")
    for h in pruned:
        print(f"[GEN]   pruned dead hub link: {h}")
    print(f"[GEN] pruned {len(pruned)} dead lst-hub-newest link(s) from listings/index.html")
    return len(pruned)


def _run_self_check(site_root: Path) -> tuple[int, int]:
    """Invoke pre-deploy-check.py scoped to listings/. Returns (errors, warnings).
    Self-validation closes the "I forgot to run the check" failure mode.

    Verbose-on-failure (Convention #97 — banked 2026-05-13 on Gander
    canonical e81df96c7; ported byte-symmetric to Goosebay 2026-05-20):
    when errors > 0, also print the first N ERROR-severity issues with
    their file paths so CI logs surface the actual failure detail, not
    just the count. Without this, diagnosing CI-only failures required
    re-running pre-deploy-check.py manually — impossible on the
    ephemeral runner.
    """
    check_path = Path(__file__).parent / "pre-deploy-check.py"
    if not check_path.exists():
        print("[GEN] pre-deploy-check.py not found — skipping self-validation")
        return (0, 0)
    out = subprocess.run(
        [sys.executable, str(check_path), "--scope", "listings/", "--json", "--quiet"],
        capture_output=True, text=True,
    )
    try:
        # Heartbeat lines (e.g. "[check34] scanned ...") are printed to stdout before the
        # JSON document, so parse from the first "{" (2026-10-10, D-1010-31: the whole
        # payload failed to parse and the log said "1 error" without naming it).
        _s = out.stdout
        payload = json.loads(_s[_s.find("{"):] if "{" in _s else _s)
        errors = payload.get("errors", 0)
        warnings = payload.get("warnings", 0)
        # Print the first 10 ERROR-severity issues verbatim so CI logs
        # don't swallow the diagnostic detail when the wrapper exits 1.
        if errors > 0:
            printed = 0
            for relpath, issues in (payload.get("files") or {}).items():
                for issue in issues:
                    if issue.get("severity") == "ERROR":
                        msg = issue.get("message", "?")
                        if len(msg) > 400:
                            msg = msg[:400] + " …(truncated)"
                        print(f"[GEN]   ❌ {relpath}: {msg}")
                        printed += 1
                        if printed >= 10:
                            break
                if printed >= 10:
                    break
            if errors > printed:
                print(f"[GEN]   …and {errors - printed} more ERROR(s) "
                      f"— re-run pre-deploy-check.py --scope listings/ for full output")
        if out.returncode != 0 and errors == 0:
            # Fail-safe: a non-zero exit with no ERROR in the JSON still fails, and says why.
            print(f"[GEN]   ❌ pre-deploy-check exited {out.returncode} with 0 ERROR(s) in its JSON; stderr/stdout tail:")
            print((out.stderr or "")[-1500:] + (out.stdout or "")[-1500:])
            errors = 1
        return (errors, warnings)
    except Exception:
        # Fall back to exit code if JSON didn't parse; show the output so the cause is visible.
        sys.stderr.write(out.stderr)
        print("[GEN]   self-check output did not parse as JSON; stdout tail:\n" + (out.stdout or "")[-2000:])
        return (1 if out.returncode != 0 else 0, 0)


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════

# ── _slugify_city + Viewpoint consumer pages (Convention #15 port from Gander) ──
# Goosebay uses INLINE nav like Gander (not Avalon's JS-injected), so the Gander
# builders port directly. Canary = Happy Valley-Goose Bay (142 sold rows).


VIEWPOINT_CANARY_TOWNS = {"labrador-city", "wabush"}

VIEWPOINT_CSS = """
body { background:#f5f5f7 !important; }
.vp-wrap { max-width: 880px; margin: 24px auto; padding: 28px 26px 48px;
  background:#fff; border-radius:12px; box-shadow:0 1px 4px rgba(0,0,0,.08); }
@media (max-width:600px){ .vp-wrap { margin:0; border-radius:0; padding:20px 16px 40px; } }
.vp-crumb { font-size:.82rem; color:#6a6a72; margin: 14px 0 6px; }
.vp-crumb a { color:#6a6a72; }
.vp-h1 { font-size:1.7rem; line-height:1.25; margin:.1em 0 .15em; color:#1a1a1a; }
.vp-sub { color:#555; font-size:1rem; margin:0 0 18px; }
.vp-sold-pill { display:inline-block; background:#1a1a1a; color:#fff;
  font-size:.8rem; font-weight:700; letter-spacing:.03em; padding:5px 12px;
  border-radius:999px; }
.vp-gallery { display:grid; grid-template-columns:2fr 1fr 1fr; gap:6px;
  border-radius:10px; overflow:hidden; margin:16px 0; }
.vp-gallery img { width:100%; height:100%; object-fit:cover; display:block;
  aspect-ratio:4/3; background:#ececef; }
.vp-gallery img:first-child { grid-row: span 2; aspect-ratio:4/3.5; }
.vp-noimg { background:#ececef; color:#9a9aa2; display:flex; align-items:center;
  justify-content:center; height:240px; border-radius:10px; margin:16px 0;
  font-size:.95rem; }
.vp-facts { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
  gap:1px; background:#e3e3e6; border:1px solid #e3e3e6; border-radius:10px;
  overflow:hidden; margin:18px 0; }
.vp-fact { background:#fff; padding:14px 16px; }
.vp-fact .vp-fact-v { font-size:1.15rem; font-weight:700; color:#1a1a1a; }
.vp-fact .vp-fact-l { font-size:.78rem; color:#6a6a72; text-transform:uppercase;
  letter-spacing:.04em; margin-top:2px; }
.vp-section-h { font-size:1.1rem; font-weight:700; color:#1a1a1a;
  margin:26px 0 10px; }
.viewpoint-price-gated { border:1px solid #e3e3e6; border-radius:12px;
  padding:24px; background:#faf7f8; text-align:center; margin:18px 0; }
.viewpoint-price-gated .vp-lock { font-size:.85rem; color:#6a6a72;
  text-transform:uppercase; letter-spacing:.05em; }
.viewpoint-price-gated .vp-gate-h { font-size:1.25rem; font-weight:800;
  color:#1a1a1a; margin:6px 0 4px; }
.viewpoint-price-gated .vp-gate-p { color:#555; margin:0 0 14px; font-size:.95rem; }
.vp-gate-cta { display:inline-block; background:#EA002A; color:#fff;
  font-weight:700; padding:11px 22px; border-radius:8px; text-decoration:none;
  border:none; cursor:pointer; font-size:1rem; }
.vp-gate-form { display:flex; gap:8px; justify-content:center; flex-wrap:wrap; margin:6px 0 4px; }
.vp-gate-input { padding:11px 14px; border:1px solid #d0d0d6; border-radius:8px;
  font-size:1rem; min-width:240px; }
.vp-gate-msg { font-size:.88rem; color:#555; min-height:1.2em; margin-top:6px; }
.vp-price-big { font-size:2.2rem; font-weight:800; color:#1a1a1a; margin:6px 0 2px; }
.vp-price-note { font-size:.82rem; color:#9a9aa2; }
.vp-enrich { border:1px solid #e3e3e6; border-radius:12px; padding:6px 18px;
  color:#1a1a1a; font-size:.95rem; margin:18px 0; }
.vp-enrich-empty { color:#9a9aa2; padding:12px 0; }
.vp-enrich-dl { margin:0; }
.vp-enrich-row { display:flex; justify-content:space-between; gap:16px;
  padding:11px 0; border-bottom:1px solid #efeff1; }
.vp-enrich-row:last-child { border-bottom:none; }
.vp-enrich-row dt { color:#6a6a72; }
.vp-enrich-row dd { margin:0; font-weight:700; text-align:right; }
.vp-enrich-y { color:#9a9aa2; font-weight:400; font-size:.85rem; }
.vp-enrich-warn { color:#c0392b; }
.vp-enrich-src { color:#9a9aa2; font-size:.76rem; padding:10px 0 4px; line-height:1.5; }
.vp-hvcta { background:#faf7f8; border:1px solid #f3d4d8; border-radius:12px;
  padding:18px 20px; margin:18px 0; display:flex; align-items:center;
  justify-content:space-between; flex-wrap:wrap; gap:10px; }
.vp-hvcta-h { font-weight:700; color:#1f1f1f; }
.vp-hvcta-link { color:#EA002A; font-weight:700; text-decoration:none; }
.vp-hvcta-link:hover { text-decoration:underline; }
.vp-disclaimer { font-size:.78rem; color:#9a9aa2; margin-top:24px; line-height:1.5; }
.vp-index-list { list-style:none; padding:0; margin:18px 0; columns:2; column-gap:36px; }
@media (max-width:600px){ .vp-index-list { columns:1; } }
.vp-index-list li { margin:0 0 9px; break-inside:avoid; font-size:.97rem; }
.vp-index-list a { color:#1a1a1a; text-decoration:none; font-weight:600; }
.vp-index-list a:hover { color:#EA002A; text-decoration:underline; }
.vp-index-meta { color:#9a9aa2; font-size:.84rem; font-weight:400; margin-left:4px; }
/* CREA disclaimer (.lst-ddr) re-styled for the light Viewpoint theme — the
   site listing CSS (skipped via the lean head) styled this white = invisible
   on light; this is dark+muted. */
.lst-ddr { max-width:880px; margin:18px auto 0; padding:18px 0 0;
  border-top:1px solid #e3e3e6; font-family:'Roboto',sans-serif;
  font-size:.72rem; color:#9a9aa2; line-height:1.5; }
.lst-ddr p { margin:0 0 10px; }

/* ── CX kit (2026-07-14): gate trust line, sold neighbors, active bridge, office card ── */
.vp-gate-trust { font-size:.82rem; color:#6a6a72; margin:10px 0 12px; }
.vp-near { list-style:none; margin:0 0 26px; padding:0; border:1px solid #e3e3e6;
  border-radius:10px; overflow:hidden; background:#fff; }
.vp-near li { display:flex; justify-content:space-between; gap:12px;
  padding:11px 16px; border-bottom:1px solid #eee; }
.vp-near li:last-child { border-bottom:0; }
.vp-near a { color:#1a1a1a; text-decoration:none; font-weight:500; }
.vp-near a:hover { color:#EA002A; }
.vp-near-meta { color:#9a9aa2; font-size:.82rem; flex:0 0 auto; }
.vp-active { background:#fff5f6; border:1px solid #f3c6cd; border-radius:10px;
  padding:20px 22px; margin:0 0 26px; }
.vp-active-h { font-weight:700; font-size:1rem; margin-bottom:10px; color:#1a1a1a; }
.vp-active-cta { display:inline-block; background:#EA002A; color:#fff;
  text-decoration:none; font-weight:600; font-size:.9rem; padding:11px 20px;
  border-radius:6px; }
.vp-active-cta:hover { background:#c8001f; }
.vp-office { border:1px solid #e3e3e6; border-radius:10px; padding:20px 22px;
  margin:0 0 26px; background:#fff; }
.vp-office-h { font-weight:700; font-size:.95rem; color:#1a1a1a; margin-bottom:4px; }
.vp-office-sub { color:#6a6a72; font-size:.82rem; margin-bottom:14px; }
.vp-office-actions { display:flex; gap:10px; flex-wrap:wrap; }
.vp-office-call { display:inline-block; background:#EA002A; color:#fff;
  text-decoration:none; font-weight:600; font-size:.9rem; padding:11px 20px;
  border-radius:6px; }
.vp-office-call:hover { background:#c8001f; }
.vp-office-msg { display:inline-block; border:1px solid #c9c9ce; color:#333;
  text-decoration:none; font-weight:600; font-size:.9rem; padding:11px 20px;
  border-radius:6px; }
.vp-office-msg:hover { border-color:#EA002A; color:#EA002A; }
@media (max-width:480px){ .vp-office-actions a, .vp-active-cta { flex:1 1 100%;
  text-align:center; display:block; } }
"""




def _viewpoint_public_record(row: dict):
    """Sanitize one VOW sold row → a public-safe Viewpoint record (or None).

    DELIBERATELY excludes every price + person-name field. The only fields
    that leave this function are public, non-person property attributes
    (Convention #32 + Decision B1/E1). VOW eligibility enforced here too.
    """
    if str(row.get("PublishToPublicSitesYN", "")).strip() != "1":
        return None
    if str(row.get("PublishToInternetSitesYN", "")).strip() != "1":
        return None
    mls = str(row.get("MLSNumber", "")).strip()
    city = str(row.get("CityText") or row.get("City") or "").strip()
    num = _viewpoint_clean(row.get("StreetNumber"))
    name = _viewpoint_clean(row.get("StreetName"))
    suf = _viewpoint_clean(row.get("StreetSuffix"))
    street = " ".join(p for p in [num, name, suf] if p).strip()
    if not street:
        al = str(row.get("AddressLine") or "").strip()
        street = al.split(",")[0].strip()
    if not (mls and city and street):
        return None
    sold_my = ""
    cd = nl_date(row.get("CloseDate"))
    sold_my = nl_month_year(cd)
    return {
        "mls": mls,
        "street": street,
        "civic": num,            # street number — for MAA address match
        "street_name": name,     # street name (no suffix) — for MAA query
        "unit": _viewpoint_clean(row.get("UnitNumber")),
        "city": city,
        "town_slug": _slugify_city(city),
        "addr_slug": _slugify_city(street) or "property",
        "beds": _viewpoint_clean(row.get("BedsTotal")),
        "baths": _viewpoint_clean(row.get("BathsTotal")),
        "sqft": _viewpoint_clean(row.get("TotalLivingAreaSqFt")),
        "ptype": _viewpoint_clean(row.get("PropertyType")),
        "psub": _viewpoint_clean(row.get("PropertySubType"))
                or _viewpoint_clean(row.get("StyleOfDwelling")),
        "year_built": _viewpoint_clean(row.get("YearBuilt")),
        "sold_my": sold_my,
        "postal_fsa": str(row.get("PostalCode") or "").strip()[:3],
        "lat": _viewpoint_clean(row.get("Latitude")),
        "lng": _viewpoint_clean(row.get("Longitude")),
        # ClosePrice / ListPrice / *AgentFullName DELIBERATELY excluded.
    }


def _viewpoint_photos(site_root: Path, mls: str, limit: int = 5) -> list:
    """Public photo URL(s) for a sold MLS. Goosebay adaptation (2026-08-21,
    mirrors the 2026-06-11 sold-data.json precedent at emit_sold_data): sold
    photos live in the FLEET-MASTER tree on R2 under the gander prefix —
    Goosebay has no local listings-sold sentinels and never will (the sync
    tool only ever writes one 001.jpg per MLS, no gallery, so a single-URL
    list is not a degradation). Emit the master URL unconditionally; the
    consuming template's vp-noimg fallback degrades any genuine miss
    (Conv #76)."""
    if not mls:
        return []
    return [f"https://photos.realestategander.com/gander/listings-sold/{mls}/001.jpg"]






def _trust_count() -> str:
    """Live review count from the TT brokerage-count fragment so the /property/ gate
    trust line stays evergreen (these pages regen nightly). Byte-identical to Gander's
    helper -- copied, not re-invented (Conv #148).

    THIS IS THE FLEET COUNT, NOT GOOSE BAY'S OWN -- so the consuming copy MUST say
    "across Royal LePage Turner Realty" (same reasoning as Avalon's copy of this
    function): an unlabeled number here would misattribute the whole brokerage's
    review count to just the Dynamic Duo, or vice versa if this site's own fragment
    is scoped narrower. The 300-5000 sanity band below also means a stale/narrow
    fragment (e.g. a per-team count well under 300) safely falls through to the
    "345+" floor rather than rendering a misleadingly small number.

    Conv #74 fail-safe: any problem -> the "345+" floor.
    """
    try:
        from pathlib import Path as _P
        frag = (_P(__file__).resolve().parent / "tt-fragments" / "brokerage-count.html").read_text()
        import re as _re
        m = _re.search(r">(\d{3,4})<", frag)
        if m and 300 <= int(m.group(1)) <= 5000:
            return m.group(1)
    except Exception:
        pass
    return "345+"


def build_viewpoint_page(rec: dict, site_root: Path,
                         neighbors: list | None = None,
                         town_has_active: bool = False) -> str:
    addr = rec["street"] + (f" #{rec['unit']}" if rec["unit"] else "")
    full_addr = f"{addr}, {rec['city']}, NL"
    canonical = (f"{SITE_ORIGIN}/property/{rec['town_slug']}/"
                 f"{rec['addr_slug']}-{rec['mls']}.html")
    sold_phrase = f"Sold {rec['sold_my']}" if rec["sold_my"] else "Recently sold"
    title = f"{full_addr} — {sold_phrase}"  # address-led, ≤60 where possible
    fact_bits = [b for b in [
        (f"{rec['beds']} bed" if rec["beds"] else ""),
        (f"{rec['baths']} bath" if rec["baths"] else ""),
        (f"{rec['sqft']} sq ft" if rec["sqft"] else ""),
        (rec["ptype"] or ""),
    ] if b]
    desc = (f"{full_addr}. {sold_phrase}. Sign in for the sold price; see "
            "assessed value, zoning & flood data — Royal LePage Turner Realty.")
    if len(desc) > 158:
        desc = desc[:157].rstrip() + "…"

    # Photos (moved up from below — og_image needs the R2-vs-disk-aware,
    # .meta.json-sentinel-checked result, not a blind local-disk path).
    # Convention #67(d): this bug shipped an og:image tag pointing at
    # /images/listings-sold/<mls>/001.jpg unconditionally, which 404s once
    # the legacy binary is untracked from git (2026-09 R2 photo cleanup) —
    # the tag was built before _viewpoint_photos() even ran, so it never
    # benefited from that helper's mode-aware, sentinel-checked lookup.
    photos = _viewpoint_photos(site_root, rec["mls"])
    if photos:
        first = photos[0]
        # R2 mode already returns an absolute URL; disk mode returns a
        # page-relative one ("../../images/...") which is invalid in an
        # og:image meta tag (crawlers need an absolute URL) — rebuild it
        # absolute against SITE_ORIGIN using the same disk path.
        og_image = first if first.startswith(("http://", "https://")) else \
            f"{SITE_ORIGIN}/images/listings-sold/{rec['mls']}/001.jpg"
    else:
        og_image = f"{SITE_ORIGIN}/images/og/pages-listing-detail-og.jpg"

    # Schema.org via json.dumps (avoids f-string brace escaping; Convention #140)
    schema = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": full_addr + " — " + sold_phrase,
        "url": canonical,
        "description": desc,
        "isAccessibleForFree": False,
        "hasPart": {
            "@type": "WebPageElement",
            "isAccessibleForFree": False,
            "cssSelector": ".viewpoint-price-gated",
        },
        "about": {
            "@type": "Residence",
            "name": full_addr,
            "address": {
                "@type": "PostalAddress",
                "streetAddress": addr,
                "addressLocality": rec["city"],
                "addressRegion": "NL",
                "addressCountry": "CA",
            },
        },
        "publisher": {
            "@type": "RealEstateAgent",
            "name": "Royal LePage Turner Realty",
            "url": SITE_ORIGIN + "/",
            "telephone": "709-256-7999",
        },
    }
    jsonld = ja_ascii(schema, indent=2)

    # Photos — already computed above (og_image needs it first).
    if photos:
        imgs = "".join(
            f'<img src="{he(u)}" alt="{he(full_addr)} — photo {i+1}" '
            f'loading="lazy" onerror="this.style.display=\'none\'">'
            for i, u in enumerate(photos)
        )
        gallery = f'<div class="vp-gallery">{imgs}</div>'
    else:
        gallery = '<div class="vp-noimg">Photo on request</div>'

    # Public fact tiles (omit empties)
    tiles = []
    if rec["beds"]:
        tiles.append((rec["beds"], "Beds"))
    if rec["baths"]:
        tiles.append((rec["baths"], "Baths"))
    if rec["sqft"]:
        tiles.append((rec["sqft"], "Sq ft"))
    if rec["ptype"]:
        tiles.append((rec["ptype"], "Type"))
    if rec["year_built"]:
        tiles.append((rec["year_built"], "Year built"))
    if rec["sold_my"]:
        tiles.append((rec["sold_my"], "Sold"))
    facts = "".join(
        f'<div class="vp-fact"><div class="vp-fact-v">{he(v)}</div>'
        f'<div class="vp-fact-l">{he(l)}</div></div>'
        for v, l in tiles
    )

    # ── CX kit (2026-07-14): exits + conversion for the sold-record page.
    # These pages are top organic landers; without exits they dead-end.
    neighbors_html = ""
    if neighbors:
        li = "".join(
            f'<li><a href="{he(nb["slug"])}.html">{he(nb["addr"])}</a>'
            f'<span class="vp-near-meta">{he(nb["sold_my"] or "")}</span></li>'
            for nb in neighbors[:6])
        neighbors_html = (f'\n  <div class="vp-section-h">More sold records in {he(rec["city"])}</div>'
                          f'\n  <ul class="vp-near">{li}</ul>\n')
    # Link the town's ACTIVE listings only when its index exists (Check #10 —
    # a sold-record town with no active inventory would 404); else the hub.
    active_href = f"../../listings/{rec['town_slug']}/" if town_has_active else "../../listings/"
    active_label = (f"See active listings in {he(rec['city'])}" if town_has_active
                    else "See all active listings")
    active_html = (f'\n  <div class="vp-active"><div class="vp-active-h">Looking to buy in {he(rec["city"])}?</div>'
                   f'<a class="vp-active-cta" href="{active_href}">{active_label} &rarr;</a></div>\n')

    head = head_block_simple(title, desc, canonical, og_image, "../../", lean=True)
    nav = nav_html("../../")
    footer = footer_html("../../")
    _hvcta_html = ""
    if _page_exists("home-value.html"):
        _hvcta_html = (
            '  <div class="vp-hvcta">\n'
            f'    <div class="vp-hvcta-h">Own a home in {he(rec["city"])}?</div>\n'
            '    <a class="vp-hvcta-link" href="../../pages/home-value.html">See what it&rsquo;s worth — free estimate &rarr;</a>\n'
            '  </div>\n'
        )
    return f"""<!DOCTYPE html>
<html lang="en">
{head}
<link rel="stylesheet" href="../../css/viewpoint.css?v=20260911-vp-kit-sync">
<script type="application/ld+json">
{jsonld}
</script>
<body>
{nav}
<main class="vp-wrap">
  <div class="vp-crumb"><a href="../../">Home</a> ›
    <a href="../../listings/sold/">Sold records</a> › {he(rec['city'])}</div>
  <span class="vp-sold-pill">{he(sold_phrase)}</span>
  <h1 class="vp-h1">{he(full_addr)}</h1>
  <p class="vp-sub">{he(', '.join(fact_bits))}</p>
  {gallery}
  <div class="vp-facts">{facts}</div>

  <div class="viewpoint-price-gated" data-mls="{he(rec['mls'])}" data-addr="{he(addr)}">
    <div class="vp-lock">🔒 Sold price — members only</div>
    <div class="vp-gate-h">Sign in to see what {he(addr)} sold for</div>
    <p class="vp-gate-p">Sold prices in Newfoundland &amp; Labrador aren't public.
       Create a free account to unlock the sold price — the same data REALTORS® use.</p>
    <div class="vp-gate-trust">Trusted by Newfoundlanders &mdash; 5.0&#9733; &middot; {_trust_count()} verified client reviews across Royal LePage Turner Realty</div>
    <a class="vp-gate-cta" href="../../listings/sold/">Sign in to see the price →</a>
  </div>

  <div class="vp-section-h">Property intelligence</div>
  <div class="vp-enrich" data-lat="{he(rec['lat'])}" data-lng="{he(rec['lng'])}"
       data-postal="{he(rec['postal_fsa'])}" data-muni="{he(_maa_muni_code(rec['city']) or '')}"
       data-civic="{he(rec.get('civic',''))}" data-street="{he(rec.get('street_name',''))}">
    Loading public assessment &amp; land-use data…
  </div>

{_hvcta_html}
{neighbors_html}{active_html}  <div class="vp-office">
    <div class="vp-office-h">Questions about this property or the {he(rec['city'])} market?</div>
    <div class="vp-office-sub">Royal LePage Turner Realty &middot; Labrador City &amp; Wabush</div>
    <div class="vp-office-actions">
      <a class="vp-office-call" href="tel:7092567999">Call 709-256-7999</a>
      <a class="vp-office-msg" href="mailto:miketurner@royallepage.ca">Email Mike</a>
    </div>
  </div>

  <div class="vp-disclaimer">Property record compiled from the Newfoundland &amp;
    Labrador MLS® sold feed and public data sources. Sold price shown to
    registered members only. Not a substitute for a title search or legal opinion.</div>

  <div class="lst-ddr">
    <p>The information contained on this page is based in whole or in part on information that is provided by members of The Canadian Real Estate Association, who are responsible for its accuracy. CREA reproduces and distributes this information as a service for its members and assumes no responsibility for its accuracy. Listings are updated daily. Royal LePage Turner Realty (2014) Inc. is a member of The Canadian Real Estate Association.</p>
    <p>REALTOR®, REALTORS®, and the REALTOR® logo are certification marks owned or controlled by The Canadian Real Estate Association (CREA) and identify real estate professionals who are members of CREA. The trademarks MLS®, Multiple Listing Service®, and the associated logos identify professional services rendered by REALTOR® members of CREA to effect the purchase, sale and lease of real estate as part of a cooperative selling system.</p>
  </div>
</main>
{footer}
<script src="../../js/regions-data.js" defer></script>
<script src="../../js/nav-config.js" defer></script>
<script src="../../js/nav-config-listings.js" defer></script>
<script>window.TURNER_SITE='{_SITE_CFG["site_key"]}';window.TURNER_API_ORIGIN='{_SITE_CFG["api_url"]}';</script>
<script src="../../js/nav.js?v=20260913-mobile-nav-fix" defer></script>
<script src="../../js/mobile-action-bar.js?v=20260917-mobile-action-bar" defer></script>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js" defer></script>
<script src="../../js/auth.js?v=20260929-sold-auth" defer></script>
<script src="../../js/viewpoint-price.js?v=20260826-signin2" defer></script>
<script src="../../js/viewpoint-enrich.js?v=20260606-vp" defer></script>
</body>
</html>"""


def build_viewpoint_index(prefix: str, title: str, desc: str, canonical: str,
                          h1: str, intro: str, list_html: str) -> str:
    """A Viewpoint hub / town-index page (pure navigation — no gated content,
    so no paywall schema). Gives Google a crawl path into the property tree."""
    og = f"{SITE_ORIGIN}/apple-touch-icon.png"
    head = head_block_simple(title, desc, canonical, og, prefix, lean=True)
    nav = nav_html(prefix)
    footer = footer_html(prefix)
    return f"""<!DOCTYPE html>
<html lang="en">
{head}
<link rel="stylesheet" href="{prefix}css/viewpoint.css?v=20260911-vp-kit-sync">
<body>
{nav}
<main class="vp-wrap">
  <h1 class="vp-h1">{he(h1)}</h1>
  <p class="vp-sub">{he(intro)}</p>
  {list_html}
  <div class="vp-disclaimer">Property records compiled from the Newfoundland &amp;
    Labrador MLS® sold feed and public data sources. Sold prices shown to
    registered members only. Not a substitute for a title search or legal opinion.</div>
  <div class="lst-ddr">
    <p>The information contained on this page is based in whole or in part on information that is provided by members of The Canadian Real Estate Association, who are responsible for its accuracy. CREA reproduces and distributes this information as a service for its members and assumes no responsibility for its accuracy. Listings are updated daily. Royal LePage Turner Realty (2014) Inc. is a member of The Canadian Real Estate Association.</p>
    <p>REALTOR®, REALTORS®, and the REALTOR® logo are certification marks owned or controlled by The Canadian Real Estate Association (CREA) and identify real estate professionals who are members of CREA. The trademarks MLS®, Multiple Listing Service®, and the associated logos identify professional services rendered by REALTOR® members of CREA to effect the purchase, sale and lease of real estate as part of a cooperative selling system.</p>
  </div>
</main>
{footer}
<script src="{prefix}js/regions-data.js" defer></script>
<script src="{prefix}js/nav-config.js" defer></script>
<script src="{prefix}js/nav-config-listings.js" defer></script>
<script>window.TURNER_SITE='{_SITE_CFG["site_key"]}';window.TURNER_API_ORIGIN='{_SITE_CFG["api_url"]}';</script>
<script src="{prefix}js/nav.js?v=20260913-mobile-nav-fix" defer></script>
<script src="{prefix}js/mobile-action-bar.js?v=20260917-mobile-action-bar" defer></script>
</body>
</html>"""


def emit_viewpoint_pages(site_root: Path, *, town_scope=None,
                         limit: int = None, verbose: bool = False) -> dict:
    """Emit the /property/<town>/<slug> Viewpoint tree from the VOW sold feed,
    plus the discoverability scaffold: a /property/ hub, per-town index pages,
    and sitemap-property.xml (referenced from sitemap-index.xml).

    Nightly-only (needs the sold cache, like emit_sold_data). Convention #74:
    skips cleanly if the cache is absent/small (hourly runner). town_scope =
    a set of town-slugs to limit to (the canary uses VIEWPOINT_CANARY_TOWNS).
    """
    sold_cache_path = Path(__file__).resolve().parent / "idx-cache" / "sold-listings.json"
    out_root = site_root / "property"
    if not sold_cache_path.exists() or sold_cache_path.stat().st_size < 1_000_000:
        if verbose:
            print("  → viewpoint: sold cache missing/small (hourly runner) — skip")
        return {"emitted": "skipped (no sold cache)", "dir": None}

    # Externalize the Viewpoint CSS to one shared sheet (was inlined per page).
    # Pairs with the lean head (skips the ~47KB listing CSS) so each property
    # page is ~15KB not ~62KB — keeps the full sold corpus pushable fleet-wide.
    (site_root / "css").mkdir(parents=True, exist_ok=True)
    (site_root / "css" / "viewpoint.css").write_text(VIEWPOINT_CSS)

    data = json.loads(sold_cache_path.read_text())
    rows = data.get("rows", data) if isinstance(data, dict) else data
    emitted, seen = 0, set()
    recs: list = []   # (rec, slug) — pass 1 collects, pass 2 renders (CX kit)
    by_town: dict = {}   # town_slug -> {"name": city, "items": [ {slug,addr,sold_my,cd} ]}
    for row in rows:
        rec = _viewpoint_public_record(row)
        if not rec:
            continue
        if town_scope is not None and rec["town_slug"] not in town_scope:
            continue
        slug = f"{rec['addr_slug']}-{rec['mls']}"
        key = (rec["town_slug"], slug)
        if key in seen:
            continue
        seen.add(key)
        addr = rec["street"] + (f" #{rec['unit']}" if rec["unit"] else "")
        bt = by_town.setdefault(rec["town_slug"], {"name": rec["city"], "items": []})
        bt["items"].append({"slug": slug, "addr": addr, "sold_my": rec["sold_my"],
                            "cd": nl_date(row.get("CloseDate"))})
        recs.append((rec, slug))
        emitted += 1
        if limit and emitted >= limit:
            break

    # pass 2 — render each page with its town neighbors + active-listings bridge
    # (CX kit 2026-07-14; neighbors need the complete town list, hence two passes)
    for _t, _info in by_town.items():
        _info["items"].sort(key=lambda x: x["cd"], reverse=True)
    for rec, slug in recs:
        _items = by_town[rec["town_slug"]]["items"]
        _neighbors = [it for it in _items if it["slug"] != slug][:6]
        _has_active = (site_root / "listings" / rec["town_slug"] / "index.html").exists()
        page_dir = out_root / rec["town_slug"]
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / f"{slug}.html").write_text(
            build_viewpoint_page(rec, site_root,
                                 neighbors=_neighbors, town_has_active=_has_active))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sitemap_urls = []

    # Per-town index pages (newest sales first) — crawl path into each town.
    for tslug, info in by_town.items():
        items = sorted(info["items"], key=lambda x: x["cd"], reverse=True)
        li = "\n".join(
            f'    <li><a href="{he(it["slug"])}.html">{he(it["addr"])}</a>'
            f'<span class="vp-index-meta">{he(it["sold_my"] or "")}</span></li>'
            for it in items)
        list_html = f'<ul class="vp-index-list">\n{li}\n</ul>'
        canonical = f"{SITE_ORIGIN}/property/{tslug}/"
        title = f"{info['name']}, NL Property Records — Sold Homes"
        desc = (f"Sold-home records for {info['name']}, NL — {len(items)} properties: "
                "address, size and sold date. Sign in for sold prices.")
        if len(desc) > 158:
            desc = desc[:157].rstrip() + "…"
        h1 = f"{info['name']}, NL — Property Records"
        intro = (f"{len(items)} sold-home records in {info['name']}. Each page shows "
                 "address, size and sold date — sign in to see the sold price.")
        (out_root / tslug / "index.html").write_text(
            build_viewpoint_index("../../", title, desc, canonical, h1, intro, list_html))
        sitemap_urls.append(canonical)
        sitemap_urls.extend(
            f"{SITE_ORIGIN}/property/{tslug}/{it['slug']}.html" for it in items)

    # Root hub (/property/) — links to each town index.
    if by_town:
        root_li = "\n".join(
            f'    <li><a href="{he(t)}/">{he(info["name"])}</a>'
            f'<span class="vp-index-meta">{len(info["items"])} records</span></li>'
            for t, info in sorted(by_town.items(), key=lambda kv: kv[1]["name"]))
        root_list = f'<ul class="vp-index-list">\n{root_li}\n</ul>'
        root_canonical = f"{SITE_ORIGIN}/property/"
        root_title = "Newfoundland & Labrador Property Records — Sold Homes"
        root_desc = ("Browse permanent sold-home property records across the "
                     "communities we serve in NL — address, size, sold date. "
                     "Sign in for sold prices.")
        if len(root_desc) > 158:
            root_desc = root_desc[:157].rstrip() + "…"
        # NOTE: root index is depth-1 (prefix "../"), but build_viewpoint_index
        # hard-codes the tawk path at ../../ — acceptable: tawk.js 404 at depth-1
        # would only drop chat on the hub, not error the page. Use depth-2 prefix
        # for chrome links via a depth-aware call below.
        out_root.mkdir(parents=True, exist_ok=True)
        (out_root / "index.html").write_text(
            _build_viewpoint_root(root_title, root_desc, root_canonical, root_list))
        sitemap_urls.insert(0, root_canonical)

    # sitemap-property.xml (referenced from sitemap-index.xml).
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in sitemap_urls:
        sm.append(f"  <url>\n    <loc>{he(u)}</loc>\n    <lastmod>{today}</lastmod>\n"
                  f"    <changefreq>monthly</changefreq>\n    <priority>0.5</priority>\n  </url>")
    sm.append("</urlset>")
    (site_root / "sitemap-property.xml").write_text("\n".join(sm) + "\n")

    if verbose:
        print(f"  → viewpoint: {emitted} pages + {len(by_town)} town index(es) "
              f"+ hub + sitemap-property.xml ({len(sitemap_urls)} urls)")
    return {"emitted": emitted, "towns": len(by_town),
            "sitemap_urls": len(sitemap_urls),
            "dir": str(out_root.relative_to(site_root)) if out_root.exists() else None}


def _build_viewpoint_root(title: str, desc: str, canonical: str, list_html: str) -> str:
    """Root /property/ hub — depth-1, so chrome prefix is '../'."""
    og = f"{SITE_ORIGIN}/apple-touch-icon.png"
    head = head_block_simple(title, desc, canonical, og, "../", lean=True)
    nav = nav_html("../")
    footer = footer_html("../")
    return f"""<!DOCTYPE html>
<html lang="en">
{head}
<link rel="stylesheet" href="../css/viewpoint.css?v=20260911-vp-kit-sync">
<body>
{nav}
<main class="vp-wrap">
  <h1 class="vp-h1">Newfoundland &amp; Labrador Property Records</h1>
  <p class="vp-sub">Permanent sold-home records across the communities we serve.
     Sign in to unlock sold prices.</p>
  {list_html}
  <div class="vp-disclaimer">Property records compiled from the Newfoundland &amp;
    Labrador MLS® sold feed and public data sources. Sold prices shown to
    registered members only. Not a substitute for a title search or legal opinion.</div>
  <div class="lst-ddr">
    <p>The information contained on this page is based in whole or in part on information that is provided by members of The Canadian Real Estate Association, who are responsible for its accuracy. CREA reproduces and distributes this information as a service for its members and assumes no responsibility for its accuracy. Listings are updated daily. Royal LePage Turner Realty (2014) Inc. is a member of The Canadian Real Estate Association.</p>
    <p>REALTOR®, REALTORS®, and the REALTOR® logo are certification marks owned or controlled by The Canadian Real Estate Association (CREA) and identify real estate professionals who are members of CREA. The trademarks MLS®, Multiple Listing Service®, and the associated logos identify professional services rendered by REALTOR® members of CREA to effect the purchase, sale and lease of real estate as part of a cooperative selling system.</p>
  </div>
</main>
{footer}
<script src="../js/regions-data.js" defer></script>
<script src="../js/nav-config.js" defer></script>
<script src="../js/nav-config-listings.js" defer></script>
<script>window.TURNER_SITE='{_SITE_CFG["site_key"]}';window.TURNER_API_ORIGIN='{_SITE_CFG["api_url"]}';</script>
<script src="../js/nav.js?v=20260913-mobile-nav-fix" defer></script>
<script src="../js/mobile-action-bar.js?v=20260917-mobile-action-bar" defer></script>
</body>
</html>"""



# ── Sold canary support (Convention #15 port from Avalon, 2026-06-11) ──
# TEAM_BY_AGENT + AGENT_PROFILE_SLUG are loaded near the top via load_registries()
# (Convention #174 Phase B, canonical agent_roster.json). Literals removed here.

def _normalize_agent_for_widget(raw_name):
    """Title-case agent name so cache lookups match the aggregator's keys.
    Convention #77 — feed casing variants normalize to single bucket."""
    if not raw_name:
        return ""
    return str(raw_name).strip().title()



def _widget_city_slug(city):
    """Slugify city for matching against per-agent-widget-stats.json keys.
    Must match _city_slug_widget() in tools/idx-stats-aggregator.py.
    Convention #15 byte-symmetric drift candidate."""
    if not city:
        return ""
    s = str(city).strip().lower()
    s = re.sub(r"['’]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s



def build_walkscore_section(listing):
    """Convention #74 fail-safe stub — Labrador doesn't have walkscore data
    integration yet. Returns empty string so emit_sold_data() row projection
    emits walk_score_html="" gracefully. Full port from Gander deferred to
    when Labrador walkscore sync infrastructure ships (see Strategic Vision
    Recommendation #14, currently Gander-only).
    """
    return ""



# Scope label for this site's sold feed, taken from the page's own
# title/description rather than assumed: this feed is Labrador City & Wabush-scoped.
SOLD_PUBLIC_PLACE = "Labrador City & Wabush"

# ── Crawler-visible sold records (ungated fields only) ──────────────────
# /listings/sold/ served 398 crawler-visible words and 0 records because every
# one of the 12,731 sales sits behind a JS fetch inside #page, which is
# display:none until the VOW gate passes. It lost 53% of its clicks in W30.
#
# Mike's T&C reading (2026-05-18, authoritative): close_price is the ONLY
# field CREA Rule 5(k) requires behind registration. Address, sold date, days
# on market, list price, beds/baths/type are all permitted ungated. So a
# public records block is legitimate content, not a cloaked preview — the
# same markup is served to every visitor.
#
# The allowlist is the safety property: fields are copied IN by name, so a
# gated field cannot reach the markup even if a future row carries it.
SOLD_PUBLIC_FIELDS = frozenset({
    "mls", "street", "address_line", "city", "sold_date",
    "dom", "beds", "baths", "ptype", "psub", "sqft", "list_price",
})
SOLD_GATED_FIELDS = frozenset({"close_price", "sa_ratio"})
SOLD_PUBLIC_LIMIT = 40
SOLD_RECORDS_BEGIN = "<!-- SOLD_PUBLIC_RECORDS:BEGIN -->"
SOLD_RECORDS_END = "<!-- SOLD_PUBLIC_RECORDS:END -->"


def _sold_full_address(row):
    """Compose "136 Elizabeth Dr" from two incomplete fields.

    `street` often lacks the suffix while `address_line`'s first segment has
    it. Match on WORD boundaries, not substring: a substring test thinks
    "1 Test St" already contains "st" and silently drops "Forester St".
    """
    street = (row.get("street") or "").strip()
    if not street:
        return ""
    seg = (row.get("address_line") or "").split(",")[0].strip()
    toks = seg.split()
    if len(toks) > 1:
        suffix = toks[-1]
        if suffix.lower() not in [t.lower() for t in street.split()]:
            return street + " " + suffix.title()
    return street


def _sold_property_href(site_root, row):
    """Root-absolute /property/ link, but ONLY if the page exists on disk.

    Matches by MLS-numbered filename SUFFIX rather than reconstructing the
    address slug: the viewpoint-page generator can build its slug from a
    different source/expansion than _sold_full_address does (confirmed bug,
    2026-07-30 — a "64 Moffatt" / "Moffatt RD" row reconstructs to
    "64-moffatt-rd" while the real page is "64-moffatt-road-<mls>.html"),
    so slug reconstruction silently drops real, existing pages. Matching on
    the MLS suffix is exact regardless of slug precision — it only ever
    links a page that actually exists.
    """
    mls = str(row.get("mls") or "").strip()
    tslug = str(row.get("city_slug") or "").strip() or _slugify_city(row.get("city") or "")
    if not (mls and tslug):
        return ""
    town_dir = Path(site_root) / "property" / tslug
    if not town_dir.is_dir():
        return ""
    for match in town_dir.glob("*-" + mls + ".html"):
        return "/property/" + tslug + "/" + match.stem
    return ""


def build_sold_public_records(rows, place_label, site_root, limit=SOLD_PUBLIC_LIMIT):
    """Crawler-visible table of recent sales — ungated fields only."""
    import html as _h

    picked = []
    for r in rows:
        rec = {k: r.get(k) for k in SOLD_PUBLIC_FIELDS if r.get(k) not in (None, "")}
        assert not (SOLD_GATED_FIELDS & set(rec)), "gated field leaked into public block"
        addr = _sold_full_address(r)
        if not addr:
            continue
        rec["_addr"] = addr
        rec["_href"] = _sold_property_href(site_root, r)
        rec["_sd"] = str(r.get("sold_date") or "")[:10]
        picked.append(rec)
    picked.sort(key=lambda x: x["_sd"], reverse=True)
    picked = picked[:limit]
    if not picked:
        return ""

    esc = _h.escape
    out = []
    out.append('<section class="sold-public" aria-labelledby="sold-public-h">')
    out.append('<h2 id="sold-public-h">Recently sold homes in ' + esc(place_label) + '</h2>')
    out.append(
        '<p class="sold-public-intro">The ' + str(len(picked)) + ' most recent sales '
        'recorded in ' + esc(place_label) + ', with the asking price and how long each '
        'home was on the market. Newfoundland &amp; Labrador is one of the few markets '
        'where final sold prices stay private &mdash; those are shown to registered '
        'users under the CREA Virtual Office Website rules.</p>')
    out.append('<table class="sold-public-table"><thead><tr>'
               '<th scope="col">Address</th><th scope="col">Sold</th>'
               '<th scope="col">Asking</th><th scope="col">Days on market</th>'
               '<th scope="col">Details</th></tr></thead><tbody>')
    for p in picked:
        addr = esc(p["_addr"])
        cell = ('<a href="' + p["_href"] + '">' + addr + '</a>') if p["_href"] else addr
        city = esc(str(p.get("city") or ""))
        sd = esc(p["_sd"] or "&mdash;")
        lp = p.get("list_price")
        try:
            ask = "$" + format(int(float(lp)), ",") if lp else "&mdash;"
        except (TypeError, ValueError):
            ask = "&mdash;"
        dom = p.get("dom")
        dom_s = (esc(str(dom)) + " days") if str(dom).strip() not in ("", "None") else "&mdash;"
        bits = []
        for k, lab in (("beds", "bed"), ("baths", "bath")):
            v = str(p.get(k) or "").strip()
            if v and v != "0":
                bits.append(v + " " + lab)
        pt = str(p.get("psub") or p.get("ptype") or "").strip()
        if pt:
            bits.append(pt)
        out.append("<tr><td>" + cell + ("<span class=\"sold-public-city\">" + city + "</span>" if city else "")
                   + "</td><td>" + sd + "</td><td>" + ask + "</td><td>" + dom_s
                   + "</td><td>" + esc(" · ".join(bits)) + "</td></tr>")
    out.append("</tbody></table>")
    out.append('<p class="sold-public-note">Sold prices, sale-to-list ratios and the '
               'full archive of past sales are available free after registration.</p>')
    out.append("</section>")
    return "\n".join(out)


def _inject_sold_records(html, block):
    """Replace everything between the sentinels. Idempotent by construction."""
    b, e = html.find(SOLD_RECORDS_BEGIN), html.find(SOLD_RECORDS_END)
    if b == -1 or e == -1 or e < b:
        return html
    return html[:b + len(SOLD_RECORDS_BEGIN)] + "\n" + block + "\n" + html[e:]


def emit_sold_public_records(site_root, *, verbose = False):
    """Inject the crawler-visible records block into /listings/sold/index.html.

    Standalone rather than folded into emit_sold_city_rollups (as on Gander)
    because the three generators order their emits differently and this site
    may not have rollup machinery at all. Called AFTER emit_sold_data has
    written data.json and AFTER emit_viewpoint_pages has written the /property/
    tree, so the rows are current and the deep-link existence check is real.

    Guards on ROW COUNT, not file size: the byte threshold in
    emit_sold_city_rollups was tuned to Gander's much larger feed and would
    misjudge a smaller market.
    """
    import json as _json

    sold_dir = Path(site_root) / "listings" / "sold"
    page, data = sold_dir / "index.html", sold_dir / "data.json"
    if not page.exists() or not data.exists():
        print("[sold-seo] skipped — listings/sold/index.html or data.json absent")
        return {"records": 0, "skipped": "missing inputs"}
    try:
        rows = _json.loads(data.read_text()).get("rows") or []
    except Exception as exc:
        print(f"[sold-seo] skipped — data.json unreadable: {exc}")
        return {"records": 0, "skipped": "unreadable"}
    if not rows:
        print("[sold-seo] skipped — data.json parsed but carries 0 rows")
        return {"records": 0, "skipped": "no rows"}

    html = page.read_text()
    if SOLD_RECORDS_BEGIN not in html:
        print("[sold-seo] skipped — sentinel absent from listings/sold/index.html")
        return {"records": 0, "skipped": "no sentinel"}

    # Empty the region first: this file is both the source we read and the file
    # we write, so a prior run's block would otherwise nest inside this one.
    html = _inject_sold_records(html, "")
    block = build_sold_public_records(rows, SOLD_PUBLIC_PLACE, site_root)
    if not block:
        print(f"[sold-seo] WARNING: block is EMPTY — {len(rows)} row(s) in "
              "data.json but none rendered (missing street/address_line?); "
              "/listings/sold/ keeps its previous body")
        return {"records": 0, "skipped": "nothing renderable"}

    out = _inject_sold_records(html, block)
    if out != page.read_text():
        page.write_text(out)
    n_rec = block.count("<tr>") - 1
    n_link = block.count('href="/property/')
    print(f"[sold-seo] {n_rec} record(s), {n_link} /property/ link(s) "
          f"-> listings/sold/index.html")
    return {"records": n_rec, "property_links": n_link}


# ═══════════════════════════════════════════════════════════════════
#  /listings/data.json — the slim discovery feed (2026-09-25)
# ═══════════════════════════════════════════════════════════════════
# Port of Gander's emit_discover_data(). Until now js/listings-index.js
# fetched /tools/idx-cache/listings-projected.json on every /listings/ load:
# ~12 MB raw / ~1.2 MB Brotli, because every row carries the full photos
# array, public + private remarks, agent names, schools, heating, etc.
# The page needs one photo and ~30 short fields per row.
#
# Rows use Gander's field names (price/beds/lat/photo, not list_price/
# bedrooms/latitude/photos) so that:
#   - normalizeListing() passes them straight through (it accepts both), and
#   - js/saved-search.js, which already fetches /listings/data.json on every
#     site and expects this shape, gets a real feed on Avalon for the first
#     time (it has been 404ing here, so the live match-count chip read 0).
#
# Rows are the generator's own post-filter `listings` (province / postal /
# city-slug passes, stale-active gate, lease-normalize), so every card links
# to a page this same run wrote. Firm sale-pending rows are NOT merged in
# (Gander merges them); Avalon's /listings/ has never shown them, and that
# stays a separate decision.
#
# postal_code + subdistrict are included for js/site-search.js (tokenized
# search matches postal codes and neighbourhoods).
#
# waterfront / ocean_view are computed from public_remarks exactly as on
# Gander. The projected cache has never carried them, so Avalon's Waterfront
# and Ocean view chips matched no active listing. cottage stays False: the
# Gander cottage-country slug list is Central NL only.
_WATERFRONT_RE = re.compile(
    r'\b(waterfront|water-?front|ocean-?front|lake-?front|river-?front|'
    r'harbour-?front|harbor-?front|water frontage|on the water|'
    r'on the harbour|on the harbor|on the lake|on the ocean|water access)\b',
    re.IGNORECASE,
)
_OCEAN_VIEW_RE = re.compile(
    r'\b(ocean|sea|bay|harbour|harbor) views?\b',
    re.IGNORECASE,
)

# Below this many rows the feed is treated as a broken upstream and the
# existing data.json is left alone (Conv #18/#74). The page falls back to the
# projected cache if data.json is missing, so leaving a stale-but-whole file
# is the better failure.
DISCOVER_MIN_ROWS = 5   # Lab West carries ~33 homes for sale (Goose Bay ~30, Avalon: 100)


def emit_discover_data(
    all_listings: list[dict],
    site_root: Path,
    *,
    source_generated_at: str | None = None,
    verbose: bool = False,
) -> dict:
    """Write <site_root>/listings/data.json. Returns a summary dict.

    The payload is deterministic for a given cache: generated_at is the
    projected cache's own timestamp, not wall-clock time, so two regens of the
    same data write identical bytes and never race each other in git.
    """
    # Sites 2026-10-09: counts and rows are one universe. Re-listings (same address +
    # unit, older MLS#) are dropped from the feed, so /listings/ never shows a card the
    # homepage count left out and its header reads the same numbers (payload["counts"]).
    counts = _site_counts(all_listings)
    _geo_rows = [L for L in all_listings if L.get("latitude") is not None and L.get("longitude") is not None]
    _no_geo_dropped = len(all_listings) - len(_geo_rows)
    all_listings = _lc.dedupe_keep_order(_geo_rows)
    rows: list[dict] = []
    skipped_no_geo = _no_geo_dropped
    for L in all_listings:
        lat = L.get("latitude")
        lng = L.get("longitude")
        if lat is None or lng is None:
            skipped_no_geo += 1
            continue

        photo_url = ""
        photos = L.get("photos") or []
        if photos:
            preferred = [p for p in photos if isinstance(p, dict) and p.get("preferred")]
            chosen = preferred[0] if preferred else photos[0]
            if isinstance(chosen, dict):
                photo_url = chosen.get("url", "") or ""
            elif isinstance(chosen, str):
                photo_url = chosen

        remarks = L.get("public_remarks") or ""
        year_built = L.get("year_built")
        if isinstance(year_built, str):
            try:
                year_built = int(year_built)
            except (TypeError, ValueError):
                year_built = None

        rows.append({
            "mls":        L.get("mls", ""),
            "url":        L.get("url_path", ""),
            "street":     L.get("street", ""),
            "city":       L.get("city_raw", ""),
            "lat":        lat,
            "lng":        lng,
            "price":      L.get("list_price"),       # None on leases (lease-normalize)
            "beds":       L.get("bedrooms"),
            "baths":      L.get("bathrooms"),
            "half_baths": L.get("half_baths") or 0,
            "sqft":       L.get("living_area"),
            "ptype":      L.get("property_type", ""),
            "zoning":     L.get("zoning") or "",
            "psize":      L.get("property_size") or "",
            "is_lease":   bool(L.get("is_lease")),
            # Lease rent (D-1009-77): the rent and its stated basis
            # ('month' | 'sqft' | 'year' | ''), from tools/_listing_terms.py.
            # The card shows "$5,000/month", "$2,175 (lease)" or "Contact for rent".
            "rent":       L.get("rent") if L.get("is_lease") else None,
            "rent_basis": (L.get("rent_basis") or "") if L.get("is_lease") else "",
            "psub":       L.get("property_subtype", ""),
            "list_date":  L.get("list_date", ""),
            "photo":      photo_url,
            "status":     L.get("status", "Active"),
            "year_built": year_built,
            "waterfront": bool(_WATERFRONT_RE.search(remarks)),
            "ocean_view": bool(_OCEAN_VIEW_RE.search(remarks)),
            "cottage":    False,
            "ours":       bool(L.get("ours")),
            "idx_year_built_desc":        L.get("idx_year_built_desc"),
            "idx_new_construction_only":  L.get("idx_new_construction_only"),
            "idx_original_list_price":    L.get("idx_original_list_price"),
            "idx_price_change_timestamp": L.get("idx_price_change_timestamp"),
            "idx_last_list_price":        L.get("idx_last_list_price"),
            "virtual_tour":  L.get("virtual_tour"),
            "virtual_tours": L.get("virtual_tours") or [],
            "open_house_next": L.get("open_house_next") or L.get("idx_open_house_next"),
            # Site search (js/site-search.js): postal codes + neighbourhoods.
            # subdistrict is absent from the projection until the #92 projector
            # change has run once; None until then.
            "postal_code": L.get("postal_code") or "",
            "subdistrict": L.get("subdistrict") or None,
        })

    listings_data_path = site_root / "listings" / "data.json"
    summary = {
        "path":           str(listings_data_path.relative_to(site_root)),
        "count":          len(rows),
        "skipped_no_geo": skipped_no_geo,
        "bytes":          0,
        "written":        False,
    }
    if len(rows) < DISCOVER_MIN_ROWS:
        print(f"[GEN] ⚠ discover feed: only {len(rows)} row(s) (< {DISCOVER_MIN_ROWS}) — "
              f"leaving the existing listings/data.json untouched")
        summary["skipped_reason"] = "too_few_rows"
        return summary

    payload = {
        "generated_at":   source_generated_at or "",
        "count":          len(rows),
        "skipped_no_geo": skipped_no_geo,
        "counts":         counts,
        "listings":       rows,
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    summary["bytes"] = len(body.encode("utf-8"))
    if not (listings_data_path.exists() and listings_data_path.read_text() == body):
        listings_data_path.write_text(body)
    summary["written"] = True
    if verbose:
        print(f"  → {summary['path']} ({summary['count']} listings, "
              f"{summary['bytes']:,} bytes, {skipped_no_geo} skipped — no geo)")
    return summary




def emit_sold_data(
    site_root: Path,
    *,
    rolling_years: int = 2,
    verbose: bool = False,
) -> dict:
    """Emit /listings/sold/data.json — the lean JSON feed for the
    sold-listing-search canary at listings/sold/index.html.

    RV cancellation gate (May 21, 2026): replaces the legacy
    pages/sold-listing-search.html which was a RealtyVis VOW embed.
    The new canary is a static page with light-touch VOW gate
    (email + name + agent-consent checkbox per Decision A signed off
    2026-05-06) that reads this data feed.

    Source: tools/idx-cache/sold-listings.json (2yr rolling window
    populated nightly by `idx-ingest.py --pull sold --backfill`).

    Field projection — only what cards + filters need:
      mls, street, city, lat, lng, close_price, list_price, sold_date,
      dom, photo, ptype, psub, beds, baths, sa_ratio, postal_fsa.

    Filters applied at emit time:
      - PublishToPublicSitesYN == 1 (VOW eligibility)
      - PublishToInternetSitesYN == 1
      - close_date within rolling_years of today
      - has lat + lng (otherwise can't render on map)

    Output: <site_root>/listings/sold/data.json. The /listings/sold/
    subdir is a Convention #18-aware reserved sweep-skip target —
    see the _sweep_stale_listings reserved loop landed at 9c21cf9.
    """
    sold_dir = site_root / "listings" / "sold"
    sold_dir.mkdir(parents=True, exist_ok=True)

    sold_cache_path = Path(__file__).resolve().parent / "idx-cache" / "sold-listings.json"
    out_path = sold_dir / "data.json"

    # Convention #18 fail-safe (banked 2026-05-08 from production canary bug):
    # The hourly-rebuild workflow only runs `idx-ingest.py --pull active`,
    # so on hourly CI runs `tools/idx-cache/sold-listings.json` does NOT
    # exist. Previous behaviour was to emit an empty stub here, which
    # CI then committed back over the rich data.json from the most recent
    # nightly — silently breaking the consumer-facing /listings/sold/ page.
    # The fix: if the source cache is missing OR suspiciously small, skip
    # writing entirely. Leave the existing data.json on disk untouched.
    # Nightly cycles (which DO pull sold) will refresh it normally.
    if not sold_cache_path.exists():
        if verbose:
            print(f"  → sold-listings.json not present (hourly runner) — leaving existing data.json alone")
        return {"path": str(out_path.relative_to(site_root)) if out_path.exists() else None,
                "count": "skipped (cache missing)", "bytes": 0}

    # Sanity-floor on cache size — if it's plausibly truncated, refuse to
    # overwrite a previously-good data.json. 1MB threshold is well below
    # the real-world ~46MB sold cache and well above any partial / error
    # state that might be returned by a half-failed RETS pull.
    try:
        cache_size = sold_cache_path.stat().st_size
    except OSError:
        cache_size = 0
    if cache_size < 1_000_000:  # 1MB floor
        if verbose:
            print(f"  → sold-listings.json only {cache_size} bytes — suspect, skipping write")
        return {"path": str(out_path.relative_to(site_root)) if out_path.exists() else None,
                "count": f"skipped (cache only {cache_size} bytes)", "bytes": 0}

    cache_data = json.loads(sold_cache_path.read_text())
    cache_rows = cache_data.get("rows", []) if isinstance(cache_data, dict) else cache_data

    # ─── Rooms cache load (task #345 — Client Full parity) ──────────────
    # PropertySubTable:Room records pulled by `idx-ingest.py --pull rooms`.
    # Keyed by Matrix_Unique_ID. Same join key used for active overlay.
    # Graceful degrade: missing rooms cache = no rooms array per row.
    rooms_cache_path = Path(__file__).resolve().parent / "idx-cache" / "rooms-listings.json"
    rooms_by_mui: dict[str, list] = {}
    if rooms_cache_path.exists():
        try:
            rdata = json.loads(rooms_cache_path.read_text())
            rooms_by_mui = rdata.get("by_mui", {}) or {}
        except (json.JSONDecodeError, OSError):
            pass

    # Cutoff date (today minus rolling_years)
    today = datetime.now(timezone.utc).date()
    cutoff = today.replace(year=today.year - rolling_years)

    # ─── Dropdown-config load (city canonical + region map) ─────────
    # Mike's directive 2026-05-11: 870 cities in the dropdown is unusable.
    # Apply Phase A (canonical-name merge) + Phase B (50+ sales threshold
    # for major-centre dropdown entry, else group by region) per
    # AskUserQuestion sign-off same day.
    #
    # tools/idx-cache/nl-city-canonical.json — variant → canonical
    #   (St. John's / St John's / St.John's / St. John's curly-apostrophe
    #   all → "St. John's"; same shape for ~20 other commonly-typoed cities).
    #
    # tools/idx-cache/nl-region-map.json — 13 NL geographic regions with
    #   explicit member lists + FSA-prefix fallback for novel cities.
    #
    # Threshold: cities with >= SOLD_DROPDOWN_THRESHOLD sales over the
    #   rolling window get their own dropdown entry under a "Major centres"
    #   section. Everything else rolls up into a "Regions" section.
    #
    # Fail-soft per Convention #21: if either config is missing or malformed,
    # fall back to the pre-2026-05-11 behaviour (every city its own entry,
    # no region grouping).
    sold_dropdown_threshold = 50
    variant_to_canonical: dict[str, str] = {}
    city_to_region: dict[str, str] = {}
    fsa_to_region: dict[str, str] = {}

    canonical_path = Path(__file__).resolve().parent / "idx-cache" / "nl-city-canonical.json"
    if canonical_path.exists():
        try:
            cdata = json.loads(canonical_path.read_text())
            for canonical, variants in (cdata.get("canonical") or {}).items():
                variant_to_canonical[canonical.lower().strip()] = canonical
                for v in variants or []:
                    variant_to_canonical[v.lower().strip()] = canonical
        except (json.JSONDecodeError, OSError) as e:
            if verbose:
                print(f"  → nl-city-canonical.json parse failed (continuing on pre-merge behaviour): {e}")

    region_path = Path(__file__).resolve().parent / "idx-cache" / "nl-region-map.json"
    if region_path.exists():
        try:
            rdata = json.loads(region_path.read_text())
            # Threshold is authoritative in the region map (integer); canonical
            # JSON has a doc-string under the same key for context only.
            try:
                sold_dropdown_threshold = int(rdata.get("_threshold", sold_dropdown_threshold))
            except (TypeError, ValueError):
                pass
            for region_name, region_def in (rdata.get("regions") or {}).items():
                for c in (region_def.get("members") or []):
                    city_to_region[c.lower().strip()] = region_name
                for c in (region_def.get("major_centres_in_region") or []):
                    city_to_region[c.lower().strip()] = region_name
            for prefix, region_name in (rdata.get("fsa_prefix_fallback") or {}).items():
                fsa_to_region[prefix.upper().strip()] = region_name
        except (json.JSONDecodeError, OSError) as e:
            if verbose:
                print(f"  → nl-region-map.json parse failed (continuing on pre-region behaviour): {e}")

    rows: list[dict] = []
    skipped_no_geo = 0
    skipped_old = 0
    skipped_unpublished = 0
    for r in cache_rows:
        # D-1009-29: newly stored feed fields stay off the sold pages for now
        # (tools/idx_fields.py SOLD_DISPLAY_HOLD); PendingDate passes through.
        r = hold_sold_display_fields(r, SOLD_DISPLAY_HOLD_EXEMPT)
        # VOW publication eligibility — both flags must be 1.
        if str(r.get("PublishToInternetSitesYN", "")).strip() != "1":
            skipped_unpublished += 1
            continue
        if str(r.get("PublishToPublicSitesYN", "")).strip() != "1":
            skipped_unpublished += 1
            continue
        # Close-date filter — within rolling window
        close_date_str = r.get("CloseDate", "")
        if not close_date_str:
            continue
        try:
            close_date = datetime.fromisoformat(nl_date(close_date_str)).date()
        except (ValueError, TypeError):
            continue
        if close_date < cutoff:
            skipped_old += 1
            continue
        # Geo filter
        try:
            lat = float(r.get("Latitude", "") or 0)
            lng = float(r.get("Longitude", "") or 0)
        except (ValueError, TypeError):
            skipped_no_geo += 1
            continue
        if lat == 0 or lng == 0:
            skipped_no_geo += 1
            continue
        # Goosebay scope filter (Conv #15 port 2026-06-11): HVGB + North
        # West River + Lake Melville ride postal prefix A0P — mirrors
        # POSTAL_PREFIXES in idx-project-to-ddf-shape.py (scope=goosebay).
        _postal_check = (r.get("PostalCode") or "").strip().upper().replace(" ", "")
        _postal_prefix = _postal_check[:3] if len(_postal_check) >= 3 else ""
        # Lab West scope = the projector's own in_scope() (Subdistrict, A2V, or A0R + a Lab West town),
        # loaded once, so there is no second copy of the rules.
        if not _lw_in_scope(r):
            skipped_no_geo += 1  # Reuse the no-geo counter; geographic-scope rejection
            continue
        # Address composition
        street_num = (r.get("StreetNumber") or "").strip()
        street_name = (r.get("StreetName") or "").strip()
        unit = (r.get("UnitNumber") or "").strip()
        street = " ".join(p for p in [street_num, street_name] if p)
        if unit:
            street = f"{street} Unit {unit}"
        # Numeric coercions
        def _to_float(v):
            try: return float(str(v).strip())
            except (ValueError, TypeError): return None
        def _to_int(v):
            # Tolerant of decimal-string inputs from RETS — cache stores
            # numeric fields like BathsTotal as "4.00", BedsTotal as "3",
            # mixed forms across the schema. Coerce via float first so
            # both "4" and "4.00" resolve cleanly. Convention #68 — never
            # assume one upstream string format.
            try: return int(float(str(v).strip()))
            except (ValueError, TypeError): return None
        close_price = _to_float(r.get("ClosePrice"))
        list_price = _to_float(r.get("ListPrice"))
        sa_ratio = None
        if close_price and list_price and list_price > 0:
            sa_ratio = round(100 * close_price / list_price, 1)
        postal = (r.get("PostalCode") or "").strip().upper().replace(" ", "")

        # City normalization — case-fix + canonical-variant merge.
        # Phase A (case-fix, banked 2026-05-08): the NLAR cache has 122+
        # cities split across multiple casings ('Appleton'/'APPLETON');
        # this re-cases all-upper/all-lower strings via .title() and
        # un-mangles the *'S → 's artifact.
        # Phase B (canonical merge, banked 2026-05-11 from Mike's "dropdown
        # is unusable" feedback): collapses punctuation/spacing variants
        # via the variant_to_canonical map loaded from
        # tools/idx-cache/nl-city-canonical.json. The 6 St. John's variants
        # (3,269 sales total) collapse into one entry; ~20 other typoed
        # cities similarly merge. If the map is missing or has no entry
        # for this city, falls through to the case-fix result.
        def _normalize_city(c):
            if not c:
                return ""
            s = c.strip()
            if not s:
                return ""
            if s == s.upper() or s == s.lower():
                s = s.title()
                # .title() turns "St. John's" → "St. John'S"; fix that
                s = s.replace("'S", "'s").replace("`S", "`s").replace("’S", "’s")
            # Phase B — canonical variant merge.
            canonical = variant_to_canonical.get(s.lower().strip())
            if canonical:
                return canonical
            return s

        # Region resolution — for the post-loop dropdown_key assignment.
        # Prefer explicit city→region map (from members + major_centres_in_region
        # lists in nl-region-map.json); fall back to FSA-prefix lookup; final
        # fallback is "Other NL" so the dropdown still works without crashing.
        def _resolve_region(canonical_city: str, fsa_prefix: str) -> str:
            r = city_to_region.get((canonical_city or "").lower().strip())
            if r:
                return r
            r = fsa_to_region.get((fsa_prefix or "").upper().strip())
            if r:
                return r
            return "Other NL"

        # Photo URL — local-photo preference (Phase 1, 2026-05-11) +
        # defensive RETS-field fallback chain.
        #
        # As of Ship 1+2 of sold-photo-sync (2026-05-11), tools/idx-sold-
        # photo-sync.py pulls the first photo for every in-scope (postal
        # A0J/A0G/A1V) sold listing via RETS GetObject and writes it to
        # images/listings-sold/<MLS>/001.jpg. When that file is on disk,
        # the consumer-facing sold-search card uses it directly (same-
        # origin asset, NLAR-direct, no CDN handshake). Listings outside
        # the in-scope filter — or in-scope listings the photo-sync
        # hasn't caught yet — fall through to the RETS-field defensive
        # chain (currently always None since the sold-cache doesn't
        # carry photo URLs from the Search response). When that chain
        # also fails, photo=None and the JS frontend renders the dark-
        # gradient fallback. Per Decision E (first-image-only on sold)
        # + Angie Liang locked guidance 2026-05-11.
        mls_str = str(r.get("MLSNumber", "")).strip()

        # R2 vs disk photo-URL resolution (Phase 2 of Storage_Hosting_Strategy):
        # Convention #15 byte-symmetric with Gander. R2 mode trusts .meta.json
        # (the incremental-sync state tracker which stays on disk in both modes).
        meta_path = site_root / "images" / "listings-sold" / mls_str / ".meta.json"
        local_photo_path = site_root / "images" / "listings-sold" / mls_str / "001.jpg"

        # Goosebay adaptation (2026-06-11): sold photos live in the FLEET-
        # MASTER tree on R2 under the gander prefix (master-on-Gander sold
        # architecture) — Goosebay has no local listings-sold sentinels.
        # Emit the master URL unconditionally; the JS card onerror degrades
        # any missing photo to the dark placeholder (Conv #76).
        if mls_str:
            photo_url = f"https://photos.realestategander.com/gander/listings-sold/{mls_str}/001.jpg"
        elif mls_str and local_photo_path.exists():
            photo_url = f"/images/listings-sold/{mls_str}/001.jpg"
        else:
            photo_url = (
                r.get("PhotoURL_1")
                or r.get("MainPhotoURL")
                or r.get("LargePhotoURL")
                or r.get("PhotoURL")
                or r.get("PrimaryPhotoURL")
                or None
            )

        # A3 photo gallery prep (Wave C frontend ship, 2026-05-20). R2 + disk
        # dual mode. Cap at 24 matching active-listing gallery convention.
        photo_urls = []
        if mls_str and photo_url and R2_BASE_URL and photo_url.startswith(R2_BASE_URL):
            photo_urls.append(photo_url)
            try:
                meta_data = json.loads(meta_path.read_text())
                photo_count = int(meta_data.get("photo_count") or 1)
            except (json.JSONDecodeError, OSError, ValueError, TypeError):
                photo_count = 1
            for n in range(2, min(photo_count + 1, 25)):
                photo_urls.append(
                    f"https://photos.realestategander.com/gander/listings-sold/{mls_str}/{n:03d}.jpg"
                )
        elif mls_str and photo_url and photo_url.startswith("/images/listings-sold/"):
            photo_urls.append(photo_url)
            sold_photo_dir = site_root / "images" / "listings-sold" / mls_str
            for n in range(2, 25):
                extra = sold_photo_dir / f"{n:03d}.jpg"
                if extra.exists():
                    photo_urls.append(f"/images/listings-sold/{mls_str}/{n:03d}.jpg")
                else:
                    break
        elif photo_url:
            photo_urls.append(photo_url)

        _canonical_city = _normalize_city(r.get("CityText", ""))
        _fsa = postal[:3] if len(postal) >= 3 else ""
        _region = _resolve_region(_canonical_city, _fsa)
        # Field-name lookup chains per Convention #68 — NLAR RETS cache uses
        # legacy names (BedsTotal/BathsTotal/TotalLivingAreaSqFt). RESO-canonical
        # variants kept as fallback for future-proofing if/when the feed shape
        # changes. Bug history: pre-2026-05-11 projection used only the RESO
        # names and silently emitted 0% coverage on beds/baths/sqft for ALL
        # 12,816 sold rows — classic Convention #18 silent-degraded-output.
        # Pending date + days-to-firm-offer (Mike directive 2026-05-18):
        # show "Listed → Under Contract → Sold" timeline so consumers can see
        # how fast offers landed. Matrix's PendingDate is the canonical
        # field that gets stamped when a listing transitions to Conditional
        # Pending. days_to_pending = listing date → pending date (the
        # actually-on-market duration; total DOM also includes the
        # contract-firm-up window).
        _pending_raw = (r.get("PendingDate") or "").strip()
        _pending_iso = nl_date(_pending_raw)
        _list_date_iso = nl_date(r.get("ListingContractDate"))
        _days_to_pending = None
        if _pending_iso and _list_date_iso:
            try:
                from datetime import date as _date
                _y1, _m1, _d1 = _list_date_iso.split("-")
                _y2, _m2, _d2 = _pending_iso.split("-")
                _delta = (_date(int(_y2), int(_m2), int(_d2))
                          - _date(int(_y1), int(_m1), int(_d1))).days
                if 0 <= _delta <= 3650:  # sanity-floor — reject obvious garbage
                    _days_to_pending = _delta
            except (ValueError, TypeError):
                pass

        rows.append({
            "mls":         r.get("MLSNumber", ""),
            "street":      street,
            "address_line": r.get("AddressLine", ""),
            "city":        _canonical_city,
            "city_slug":   _slugify_city(_canonical_city),  # Mike fix 2026-05-18
            "region":      _region,
            "postal_code": postal,
            # dropdown_key filled in by the post-loop pass below
            "lat":         lat,
            "lng":         lng,
            "close_price": close_price,
            "list_price":  list_price,
            "original_list_price": _to_float(r.get("OriginalListPrice")),
            "sa_ratio":    sa_ratio,           # % of list price
            "sold_date":   nl_date(close_date_str),
            "list_date":   _list_date_iso,
            "pending_date": _pending_iso,       # Mike directive 2026-05-18
            "days_to_pending": _days_to_pending,  # Mike directive 2026-05-18
            "last_status": (r.get("LastStatus") or "").strip(),
            "dom":         _to_int(r.get("DOM")),
            "ptype":       r.get("PropertyType", ""),
            "psub":        r.get("PropertySubType", ""),
            "style":       r.get("StyleOfDwelling", ""),
            "beds":        _to_int(r.get("BedsTotal") or r.get("BedroomsTotal")),
            "baths":       _to_int(r.get("BathsTotal") or r.get("BathroomTotalInteger")),
            "baths_full":  _to_int(r.get("BathsFull")),
            "baths_half":  _to_int(r.get("BathsHalf")),
            "sqft":        _to_int(r.get("TotalLivingAreaSqFt") or r.get("LivingArea")),
            "year_built":  _to_int(r.get("YearBuilt")),
            "lot_size":    r.get("Lotsize", "") or "",
            "property_size": r.get("PropertySize", "") or "",
            "water":       r.get("Water", "") or "",
            "sewer":       r.get("Sewer", "") or "",
            "access":      r.get("Access", "") or "",
            "road":        r.get("Road", "") or "",
            "land_features": r.get("LandFeatures", "") or "",
            "remarks":     r.get("PublicRemarks", "") or "",
            # list_office RESTORED 2026-09-15 (Mike: "out of an abundance of
            # caution... proper accreditation" for the listing brokerage on
            # sold-listing VOW records -- not required per the 2026-09-15
            # NLAR advertising-rules review, added anyway). Supersedes the
            # 2026-08-06 "no attribution at all" decision (comment preserved
            # in git history). Brokerage name only, never the individual
            # agent -- matches the 2026-08-04 company-not-agent decision.
            # selling_office stays out (only the Listing Brokerage is the
            # §15(d)(ii) concern; a buyer-side sale's co-op brokerage is a
            # separate question already flagged to Bill Stirling). No slim/
            # shard split exists on this site (small inventory) -- this one
            # field flows straight to both the grid and the detail page.
            "list_office": (r.get("ListOfficeName", "") or "").strip(),
            # Per-agent widget click-through filter wiring (Ship 3, 2026-05-17).
            # build_per_agent_widget_section emits links like
            #   /listings/sold/?agent=crystal-hynes&city=gander
            #   /listings/sold/?team=turner-realty-team&city=gander
            # The sold-listings.js applyFilters reads ?team + ?agent and matches
            # against these slugs. Convention #77 normalize (Title Case) keeps
            # casings collapsed; AGENT_PROFILE_SLUG + TEAM_BY_AGENT lookups
            # produce the same slugs the widget renders into hrefs.
            "list_agent_name": _normalize_agent_for_widget(
                r.get("ListAgentFullName", "") or ""),
            "list_agent_slug": AGENT_PROFILE_SLUG.get(
                _normalize_agent_for_widget(r.get("ListAgentFullName", "") or ""), ""),
            "team_slug": _widget_city_slug(
                TEAM_BY_AGENT.get(
                    _normalize_agent_for_widget(r.get("ListAgentFullName", "") or ""), "")),
            # Wave C Day 1 — Street View Static pre-render (2026-05-19).
            # Empty string if no lat/lng or no GOOGLE_MAPS_API_KEY env var.
            "street_view_html": build_street_view_section({
                "lat": lat, "lng": lng, "latitude": lat, "longitude": lng,
            }),
            # Wave C C10 — Walk Score pre-render (2026-05-20).
            # Mirrors active listings (build_walkscore_section already in
            # use on detail pages via line ~5147). Reads from cached
            # tools/idx-cache/walkscore.json populated by idx-walkscore-sync.py.
            # Convention #74 fail-safe — empty string when:
            #   (a) cache absent (any pipeline that hasn't run walk-score sync)
            #   (b) listing has no entry in cache
            #   (c) all 3 scores below the meaningful-signal threshold
            # Sold listings inherit Walk Score data when their MLS overlaps
            # the active-feed cache (i.e., the property was once active and
            # got synced). Rural NL sold listings without cached entries
            # render the section omitted.
            "walk_score_html": build_walkscore_section({
                "mls": str(r.get("MLSNumber") or r.get("Matrix_Unique_ID") or "").strip(),
                "street": (r.get("AddressLine") or "").strip(),
                "city": (r.get("CityText") or "").strip(),
            }),
            # Wave C Day 2 — Operating Costs raw fields (2026-05-19).
            # Per CLAUDE.md, ~1-3% of listings populate these; most sold
            # pages will see Convention #74 fail-safe (JS renderer hides
            # section when all five fields are blank).
            "heating_bill":     (r.get("HeatingBill", "") or "").strip(),
            "water_bill":       (r.get("WaterBill", "") or "").strip(),
            "electric_bill":    (r.get("ElectricBill", "") or "").strip(),
            "condo_fee":        r.get("CondoFee"),
            "mobile_lease_fee": r.get("MobileLeasedLandFees"),
            # Selling-side (buyer's agent) attribution block REMOVED
            # 2026-08-06 -- it was explicitly deferred/never rendered (see
            # the git history at this line for the original Wave A note),
            # and Mike's 2026-08-06 directive rules out ever shipping any
            # sold-side agent/brokerage attribution. No replacement.
            "fsa":         _fsa,
            "photo":       photo_url,
            "photos":      photo_urls,
            # ─── Tier A Client Full parity fields (free — already in cache) ───
            # Per design spec _research/Client_Full_Parity_Design_Spec_2026-05-11.md
            # Decision A: big-bang ship; Decision B: L1 hero+tabs layout.
            # These render in the "Property" + "Tax & Lot" tabs of L1.
            "district":          r.get("District", "") or "",
            "subdistrict":       r.get("Subdistrict", "") or "",
            "area":              r.get("Area", "") or "",
            "basement_sqft":     _to_int(r.get("BasementAreaSqFt")),
            "beds_above_grade":  _to_int(r.get("BdrmAboveGrade")),
            "beds_below_grade":  _to_int(r.get("BdrmBelowGrade")),
            "cdom":              _to_int(r.get("CDOM")),
            "treed_acres":       r.get("TreedAcres", "") or "",
            "workable_acres":    r.get("WorkableAcres", "") or "",
            "tax_amount":        _to_float(r.get("Taxamount")),
            "tax_year":          _to_int(r.get("Taxyear")),
            "waterfront":        r.get("Waterfrontyn", "") in ("1", "Y", "y"),
            "building_type":     r.get("BuildingType", "") or "",
            "unit_number":       r.get("UnitNumber", "") or "",
            # ─── Tier B Client Full parity fields (idx-ingest extended 2026-05-11) ───
            # Per Client Full PDF samples (active 144 Penwell + sold 22 Read St).
            # These are pulled into the cache by `idx-ingest.py --pull sold`
            # via the extended SAFE_FIELDS_ACTIVE allowlist. They start at 0%
            # coverage until the next nightly cycle re-pulls; after that they
            # populate in the same proportions the active fields already do.
            "side_of_road":      r.get("SideOfRoad", "") or "",
            "title_to_land":     r.get("Title", "") or "",
            "zoning":            r.get("Zoning", "") or "",
            "possession":        r.get("Possession", "") or "",
            "number_of_floors":  r.get("NumberOfFloors", "") or "",
            "second_floor_sqft": _to_int(r.get("SecondFloorAreaSqFt")),
            "third_floor_sqft":  _to_int(r.get("ThirdFloorAreaSqFt")),
            "fourth_floor_sqft": _to_int(r.get("FourthFloorAreaSqFt")),
            "features":          r.get("Features", "") or "",
            "interior_features": r.get("InteriorFeatures", "") or "",
            "exterior":          r.get("Exterior", "") or "",
            "exterior_maintenance": r.get("ExteriorMaintenance", "") or "",
            "roof":              r.get("Roof", "") or "",
            "flooring":          r.get("Flooring", "") or "",
            "driveway":          r.get("Driveway", "") or "",
            "driveway_details":  r.get("Drivewaydetails", "") or "",
            "uffi":              r.get("Uffi", "") or "",
            "sign":              r.get("SignYN", "") in ("1", "Y", "y"),
            "rental_income":     r.get("Rentalincome", "") or "",
            "total_rental_income": r.get("TotalRentalIncome", "") or "",
            "rental_units":      r.get("NumberRentalUnits", "") or "",
            "units_1br":         _to_int(r.get("UnitsOneBedroom")),
            "units_2br":         _to_int(r.get("UnitsTwoBedroom")),
            "units_3br":         _to_int(r.get("UnitsThreeBedroom")),
            "units_4br":         _to_int(r.get("UnitsFourBedroom")),
            "water_tax":         r.get("Watertax", "") or "",
            "vt_url":            r.get("VirtualTourURL", "") or "",
            "vt_url_unbranded":  r.get("VirtualTourURL2Unbranded", "") or "",
            # DDFMoreInfoURL: NLAR "more info" field, agents commonly put
            # YouTube tour videos here. Convention #15 byte-symmetric port
            # from Gander (Mike caught 2026-05-23 MLS 1297950).
            "more_info_url":     r.get("DDFMoreInfoURL", "") or "",
            # ─── Rooms array (PropertySubTable:Room join via Matrix_Unique_ID) ───
            # Empty list when no rooms data exists for this listing.
            "rooms":             rooms_by_mui.get(str(r.get("Matrix_Unique_ID", "")).strip(), []),
        })

    # ─── Post-loop dropdown_key pass (Phase B of 2026-05-11 dropdown rework) ───
    # Walk rows once to count canonical-city occurrences, then determine
    # which cities clear the major-centre threshold. Cities at-or-above
    # threshold get their own dropdown entry (dropdown_key = canonical
    # city); cities below threshold roll into their region (dropdown_key
    # = region name). Major centres ALSO appear via region selection —
    # consumer-natural inclusivity: selecting "Avalon Peninsula" returns
    # St. John's + Mount Pearl + all the smaller Avalon towns.
    from collections import Counter as _Counter
    city_counts = _Counter(r["city"] for r in rows if r.get("city"))
    major_centres = {c for c, n in city_counts.items() if n >= sold_dropdown_threshold}
    for r in rows:
        c = r.get("city") or ""
        if c in major_centres:
            r["dropdown_key"] = c
        else:
            r["dropdown_key"] = r.get("region") or "Other NL"

    # Also build the dropdown options list, so the JS frontend doesn't
    # have to count rows itself. Two sections — major centres (alpha-sorted)
    # + regions (geography-sorted) — with sale counts attached.
    dropdown_counts = _Counter(r["dropdown_key"] for r in rows if r.get("dropdown_key"))
    dropdown_options = {
        "major_centres": sorted(
            [{"key": c, "count": dropdown_counts[c]} for c in major_centres if c in dropdown_counts],
            key=lambda x: x["key"]
        ),
        "regions": sorted(
            [{"key": k, "count": v} for k, v in dropdown_counts.items() if k not in major_centres],
            key=lambda x: x["key"]
        ),
        "threshold": sold_dropdown_threshold,
        "total_cities_collapsed": len(city_counts),  # diagnostic — pre-merge city count
    }

    # ─── Wave B C9 (task #57, 2026-05-18) — merge pending rows ────────
    # Per Mike directive: pending listings (Status=STFRM = "Conditional
    # Pending" = firm sale awaiting closing) appear ON the /listings/sold/
    # surface (still VOW-gated since they share consumer-state with sold)
    # but with a distinct "Firm Sale, Awaiting Close" badge instead of SOLD.
    # JS renderer keys off `state: "firm_pending"` on the row to swap badge
    # + suppress close_price (not yet known at pending stage).
    #
    # Source: tools/idx-cache/pending-listings.json (populated by
    # `idx-ingest.py --pull pending` on hourly + nightly CI cycles).
    # Convention #74 fail-safe: skip silently if cache missing.
    pending_cache_path = Path(__file__).resolve().parent / "idx-cache" / "pending-listings.json"
    pending_rows_added = 0

    def _safe_int(v):
        if v is None or v == "":
            return None
        try:
            return int(float(str(v).replace(",", "").strip()))
        except (TypeError, ValueError):
            return None

    def _safe_float(v):
        if v is None or v == "":
            return None
        try:
            return float(str(v).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    if pending_cache_path.exists():
        try:
            pcache_raw = json.loads(pending_cache_path.read_text())
            pcache_rows = pcache_raw.get("rows", []) if isinstance(pcache_raw, dict) else pcache_raw
            # Project pending rows using the same `row` shape as sold (lat/lng,
            # price, city, mls, etc.) so the consumer renderer needs ONE branch
            # for badge swap, not a different schema. Pending rows skip the
            # close_date filters since they don't have one yet.
            for pr in pcache_rows:
                lat = pr.get("Latitude")
                lng = pr.get("Longitude")
                if not lat or not lng:
                    continue
                # VOW eligibility — same gate as sold
                if str(pr.get("PublishToInternetSitesYN") or "").strip() != "1":
                    continue
                if str(pr.get("PublishToPublicSitesYN") or "").strip() != "1":
                    continue
                # Build a row matching the sold projection shape
                from datetime import datetime as _dt
                pending_date_raw = (pr.get("PendingDate") or "").strip()
                # Some Matrix exports format PendingDate as ISO timestamp; trim
                pending_date_iso = pending_date_raw.split("T")[0] if pending_date_raw else ""
                p_mls = str(pr.get("MLSNumber") or "").strip()
                if not p_mls:
                    continue
                # City + dropdown_key — reuse same normalization as sold loop
                p_city_raw = (pr.get("CityText") or pr.get("City") or "").strip()
                p_city = _normalize_city(p_city_raw) if p_city_raw else ""
                p_city_canonical = variant_to_canonical.get(p_city.lower(), p_city) if p_city else ""
                p_postal = (pr.get("PostalCode") or "").strip()
                p_fsa = p_postal[:3].upper() if len(p_postal) >= 3 else ""
                if p_city_canonical in major_centres:
                    p_dropdown_key = p_city_canonical
                else:
                    p_dropdown_key = (city_to_region.get(p_city_canonical.lower(), "")
                                       or fsa_to_region.get(p_fsa, "")
                                       or "Other NL")
                p_region = p_dropdown_key if p_dropdown_key != p_city_canonical else (
                    city_to_region.get(p_city_canonical.lower(), "")
                    or fsa_to_region.get(p_fsa, "")
                    or "Other NL"
                )

                # Photo lookup — same pattern as sold: emit the master R2
                # URL unconditionally, JS card onerror degrades to the
                # placeholder if missing (Conv #76). Convention #15
                # byte-symmetric with the primary sold-photo resolution
                # block above (no .meta.json read needed here — this
                # block never builds a photo gallery, just one URL).
                p_photo = None
                photo_dir = site_root / "images" / "listings-sold" / p_mls
                if p_mls:
                    p_photo = f"https://photos.realestategander.com/gander/listings-sold/{p_mls}/001.jpg"
                elif (photo_dir / "001.jpg").exists():
                    p_photo = f"/images/listings-sold/{p_mls}/001.jpg"

                p_row = {
                    "mls":          p_mls,
                    "street":       (pr.get("AddressLine") or "").strip(),
                    "city":         p_city_canonical,
                    "city_slug":    _slugify_city(p_city_canonical),
                    "region":       p_region,
                    "dropdown_key": p_dropdown_key,
                    "postal_fsa":   p_fsa,
                    "lat":          float(lat),
                    "lng":          float(lng),
                    "list_price":   _safe_int(pr.get("ListPrice")),
                    "original_list_price": _safe_int(pr.get("OriginalListPrice")),
                    "close_price":  None,        # Not known yet — pending
                    "sold_date":    pending_date_iso,   # Reuse field for sort
                    "pending_date": pending_date_iso,
                    "dom":          _safe_int(pr.get("DOM")),
                    "cdom":         _safe_int(pr.get("CDOM")),
                    "sa_ratio":     None,
                    "beds":         _safe_int(pr.get("BedsTotal")),
                    "baths":        _safe_float(pr.get("BathsTotal")),
                    "ptype":        (pr.get("PropertyType") or "").strip(),
                    "psub":         (pr.get("PropertySubType") or "").strip(),
                    # list_office/selling_office/selling_agent_name/
                    # selling_agent_slug REMOVED 2026-08-06 -- see the
                    # matching removal + rationale above the main sold-row
                    # build. list_agent_name/list_agent_slug/team_slug kept
                    # (Turner-agent ?agent=/?team= deep-link filter).
                    "list_agent_name":    (pr.get("ListAgentFullName") or "").strip(),
                    "list_agent_slug":    AGENT_PROFILE_SLUG.get(
                        (pr.get("ListAgentFullName") or "").strip(), ""
                    ),
                    "team_slug":    TEAM_BY_AGENT.get(
                        (pr.get("ListAgentFullName") or "").strip(), ""
                    ),
                    "photo":        p_photo,
                    # Wave C Day 1 — Street View Static pre-render (pending row variant)
                    "street_view_html": build_street_view_section({
                        "lat": float(lat) if lat is not None else None,
                        "lng": float(lng) if lng is not None else None,
                        "latitude": float(lat) if lat is not None else None,
                        "longitude": float(lng) if lng is not None else None,
                    }),
                    # Wave C Day 2 — Operating Costs raw fields (pending variant)
                    "heating_bill":     (pr.get("HeatingBill", "") or "").strip(),
                    "water_bill":       (pr.get("WaterBill", "") or "").strip(),
                    "electric_bill":    (pr.get("ElectricBill", "") or "").strip(),
                    "condo_fee":        pr.get("CondoFee"),
                    "mobile_lease_fee": pr.get("MobileLeasedLandFees"),
                    # State marker — JS renderer keys off this for badge swap
                    "state":        "firm_pending",
                }
                rows.append(p_row)
                pending_rows_added += 1
        except (json.JSONDecodeError, OSError) as e:
            if verbose:
                print(f"  ⚠ pending-listings.json load failed: {e}")

    if verbose and pending_rows_added:
        print(f"  → merged {pending_rows_added} pending (STFRM) rows into sold feed")

    # Positive heartbeat (always-on #8): the "Under contract" timeline row on
    # the sold detail page reads pending_date. Say how many sold rows carry it,
    # and say why when the answer is zero, so an empty section is never silent.
    _sold_only = [x for x in rows if x.get("state") != "firm_pending"]
    _with_pending = sum(1 for x in _sold_only if x.get("pending_date"))
    if _with_pending:
        print(f"  -> sold pending_date: {_with_pending}/{len(_sold_only)} sold rows carry a "
              f"PendingDate (Under contract row shown on those)")
    elif _sold_only:
        print(f"  -> sold pending_date: 0/{len(_sold_only)} sold rows carry a PendingDate -- "
              f"the feed sent none (or the sold cache predates the 2026-10-09 field list); "
              f"the Under contract row stays hidden")

    # Sort newest first — pending rows sort by pending_date, sold by sold_date
    # (both populate `sold_date` field per projection above for unified sort).
    rows.sort(key=lambda x: x.get("sold_date", ""), reverse=True)

    payload = {
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "git_sha":            _git_sha(site_root) or "unknown",
        "count":              len(rows),
        "pending_count":      pending_rows_added,
        "rolling_years":      rolling_years,
        "skipped_no_geo":     skipped_no_geo,
        "skipped_old":        skipped_old,
        "skipped_unpublished": skipped_unpublished,
        "dropdown":           dropdown_options,
        "rows":               rows,
    }

    out_path = sold_dir / "data.json"
    # PUBLIC artifact — drop the VOW-gated price fields (see
    # SOLD_GATED_PUBLIC_FIELDS). `rows` itself is left intact above so
    # every in-generator consumer still sees close_price.
    payload["rows"] = [_strip_gated_price_fields(r) for r in rows]
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    out_path.write_text(body)

    # Wave B C8 (task #56, 2026-05-18) — copy per-agent widget stats sidecar
    # for sold-detail JS. JS fetches /listings/sold/per-agent-stats.json once
    # per session to render the trust card (same shape as the active-listing
    # widget shipped via build_per_agent_widget_section). Convention #74
    # fail-safe: if the cache isn't on disk yet (hourly runner sometimes
    # races aggregator), skip silently — sold detail still renders without
    # the trust card.
    stats_src = Path(__file__).resolve().parent / "idx-cache" / "per-agent-widget-stats.json"
    if stats_src.exists():
        try:
            stats_dst = sold_dir / "per-agent-stats.json"
            stats_dst.write_text(stats_src.read_text())
            if verbose:
                print(f"  → {stats_dst.relative_to(site_root)} (per-agent widget stats sidecar)")
        except OSError as e:
            if verbose:
                print(f"  ⚠ per-agent-stats.json sidecar copy failed: {e}")

    summary = {
        "path":  str(out_path.relative_to(site_root)),
        "count": len(rows),
        "bytes": len(body.encode("utf-8")),
    }
    if verbose:
        print(
            f"  → {summary['path']} ({summary['count']} sold, "
            f"{summary['bytes']:,} bytes, "
            f"skipped: {skipped_unpublished} unpublished, "
            f"{skipped_old} pre-{cutoff.isoformat()}, {skipped_no_geo} no geo)"
        )
    return summary



# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════


# ─────────────────────────────────────────────────────────────────────
# Per-city sold rollups — SEO Forward Plan Tier 2 item (E)
# Banked 2026-05-21 PM per Mike's Avalon-first priority directive.
#
# Each city with >= threshold sold listings gets its own indexable rollup
# page at /listings/sold/<city_slug>/ with city-specific title/meta/H1
# and a city-filtered data.json. Pages share the same VOW gate as the
# parent /listings/sold/ index (Schema.org isAccessibleForFree=false).
#
# Convention #18 prevention: shares emit_sold_data's fail-safe — if the
# upstream sold cache is missing or too small, skip silently rather than
# overwrite previously-good per-city directories with empty stubs.
#
# Trimmed row projection (CARD_FIELDS) cuts per-row size by ~80% so the
# per-city data.json files are small (st-johns ~2.2MB, paradise ~0.6MB,
# most others <1MB) for fast first-page-load even on mobile.

SOLD_CITY_ROLLUP_THRESHOLD = 10  # Minimum sold count to emit a per-city rollup

# Self-canonical pilot (2026-08-05, Conv #15 port from Avalon 2026-07-30 /
# Gander's original 2026-07-30 pilot) -- HVGB carries genuinely unique
# content once build_sold_public_records renders it (this port). Only
# happy-valley-goose-bay clears the >=10 rollup threshold on the real
# feed (155 rows vs north-west-river's 5 and nain's 2), so this is a
# 1-entry set -- expand it if a second town ever crosses the threshold.
SOLD_SELF_CANONICAL_CITIES = frozenset({
    "labrador-city",
    "wabush",
})

# Trimmed projection — only the fields the JS card renderer + filters use.
# Cuts row size 3260 -> 653 bytes per row. Verified 2026-05-21 against the
# live data.json sample.

# ── VOW: gated price fields must never reach a PUBLIC artifact ──────────
# close_price + sa_ratio are the only fields CREA Rule 5(k) requires behind
# registration (Mike's 2026-05-18 T&C reading). They used to ride
# listings/sold/data.json, which is served with `cache-control: public` — an
# anonymous curl returned every sold price, so the JS gate was cosmetic.
#
# Stripped HERE, at serialization, NOT from the row dicts upstream: this
# generator reads close_price itself for similar-sold comp banding, the
# dropdown build and the price-history section. Removing it upstream would
# break its own logic. Registered consumers get prices from the RLS-gated
# `viewpoint_prices` table via js/sold-listings.js + js/sold-detail.js.
SOLD_GATED_PUBLIC_FIELDS = ("close_price", "sa_ratio")


def _strip_gated_price_fields(row):
    """Return `row` without the VOW-gated price fields (public artifacts only)."""
    if not any(k in row for k in SOLD_GATED_PUBLIC_FIELDS):
        return row
    return {k: v for k, v in row.items() if k not in SOLD_GATED_PUBLIC_FIELDS}


SOLD_CITY_CARD_FIELDS = frozenset({
    "mls", "address_line", "street", "city", "city_slug", "dropdown_key",
    "list_price", "sold_date", "close_date", "dom", "photo",
    # close_price + sa_ratio deliberately ABSENT — see
    # SOLD_GATED_PUBLIC_FIELDS above.
    "beds", "baths", "ptype", "psub", "lat", "lng", "state",
    # `state` added 2026-08-05 (Conv #15 port from Gander/Avalon's
    # 2026-08-04/08-05 P1 work) -- sold-detail.js's Similar Sold filter
    # needs it to exclude firm_pending rows from comparables, the same
    # way it already does when reading the full feed.
    # 2026-08-06 -- Mike: no sold-listing brokerage attribution at all
    # (supersedes the 2026-08-04 "show company" decision this comment used
    # to describe) -- list_office REMOVED. Agent-name fields were never in
    # this field set to begin with; the ?agent=/?team= deep-link filter and
    # the Turner trust card point at the main feed, unaffected.
    "days_to_pending", "original_list_price",
    "price_change_timestamp", "sqft",
})


def emit_sold_city_rollups(
    site_root: Path,
    *,
    threshold: int = SOLD_CITY_ROLLUP_THRESHOLD,
    verbose: bool = False,
) -> dict:
    """Emit per-city sold-rollup pages under /listings/sold/<city_slug>/.

    Skips silently if the upstream sold cache is missing or smaller than
    1MB (Convention #18 fail-safe — see emit_sold_data() for the same
    pattern).

    Per-city directory contents:
        index.html  — paywall-content shell with city-specific SEO metadata
        data.json   — trimmed row projection filtered to that city

    The HTML is rendered by string-substitution from the parent
    listings/sold/index.html template. The per-city HTML sets
    window.SOLD_DATA_URL to point at its own data.json before
    js/sold-listings.js loads.

    Returns a summary dict with `cities_created` + `cities_skipped_threshold`
    + `total_rows_emitted`.
    """
    import json as _json

    sold_dir = site_root / "listings" / "sold"
    template_path = sold_dir / "index.html"
    main_data_path = sold_dir / "data.json"

    # Convention #74 fail-safe — same pattern as emit_sold_data() but anchored
    # on the parent /listings/sold/data.json (which exists on every cycle —
    # hourly or nightly) rather than the source sold-listings.json cache
    # (which is nightly-only). This lets hourly cycles regenerate per-city
    # pages from the SAME data consumers see on the parent page.
    if not main_data_path.exists():
        if verbose:
            print(f"  -> listings/sold/data.json missing; skipping per-city rollups")
        return {"cities_created": 0, "skipped_reason": "main data.json missing"}

    if main_data_path.stat().st_size < 100_000:
        if verbose:
            print(f"  -> main data.json suspiciously small ({main_data_path.stat().st_size} bytes); skipping")
        return {"cities_created": 0, "skipped_reason": "main data.json too small"}

    if not template_path.exists():
        if verbose:
            print(f"  -> listings/sold/index.html template missing; skipping")
        return {"cities_created": 0, "skipped_reason": "template missing"}

    template_html = template_path.read_text()
    # Empty the records region before rendering per-city pages, so they never
    # inherit the parent's all-NL block (index.html is also our template).
    template_html = _inject_sold_records(template_html, "")
    main_data = _json.loads(main_data_path.read_text())
    projected_rows = main_data.get("rows") or []
    generated_at = main_data.get("generated_at") or ""
    if verbose:
        print(f"  -> using {len(projected_rows)} rows from {main_data_path}")

    # Bucket by city_slug, count threshold
    from collections import defaultdict
    by_city: dict[str, list[dict]] = defaultdict(list)
    for row in projected_rows:
        slug = (row.get("city_slug") or "").strip().lower()
        if slug:
            by_city[slug].append(row)

    cities_created: list[str] = []
    cities_skipped: list[tuple[str, int]] = []
    total_rows = 0

    for slug, rows in by_city.items():
        if len(rows) < threshold:
            cities_skipped.append((slug, len(rows)))
            continue

        # Derive city display name from row data (dropdown_key or city)
        city_label = rows[0].get("dropdown_key") or rows[0].get("city") or slug.replace("-", " ").title()

        city_dir = sold_dir / slug
        city_dir.mkdir(parents=True, exist_ok=True)

        # Write trimmed-projection data.json
        trimmed_rows = [
            {k: v for k, v in r.items() if k in SOLD_CITY_CARD_FIELDS}
            for r in rows
        ]
        city_data = {
            "city_slug": slug,
            "city_label": city_label,
            "count": len(trimmed_rows),
            "generated_at": generated_at,
            "rows": trimmed_rows,
        }
        (city_dir / "data.json").write_text(_json.dumps(city_data, separators=(",", ":")))

        # Render city-specific HTML by string-substitution against the template
        city_html = _render_sold_city_html(template_html, slug, city_label, len(rows))
        city_html = _inject_sold_records(
            city_html, build_sold_public_records(rows, city_label + ", NL", site_root))
        city_html = _add_sold_explore_links(city_html, slug, city_label, site_root)
        (city_dir / "index.html").write_text(city_html)

        cities_created.append(slug)
        total_rows += len(rows)

    if verbose:
        print(f"  -> per-city sold rollups: {len(cities_created)} cities created "
              f"(threshold >= {threshold}), {len(cities_skipped)} skipped, "
              f"{total_rows} total rows emitted")

    return {
        "cities_created": len(cities_created),
        "cities_skipped_threshold": len(cities_skipped),
        "total_rows_emitted": total_rows,
        "threshold": threshold,
        "city_slugs": sorted(cities_created),
    }


SOLD_EXPLORE_LINKS = {
    "labrador-city": ("labrador-city.html", "market-stats.html"),
    "wabush": ("wabush.html", "market-stats.html"),
}


def _city_ms_link(city_slug, city_label, prefix):
    """" See the live {city} market statistics." for towns that have a stats
    page (2026-09-07: was a Gander-only special case). '' otherwise."""
    entry = SOLD_EXPLORE_LINKS.get(city_slug)
    if not entry or not entry[1]:
        return ""
    if not (Path(__file__).resolve().parent.parent / "pages" / entry[1]).exists():
        return ""
    return (f' See the <a href="{prefix}pages/{entry[1]}" style="color:#EA002A;">live {city_label} '
            f'market statistics</a>.')


def _add_sold_explore_links(city_html: str, city_slug: str, city_label: str, site_root: Path) -> str:
    entry = SOLD_EXPLORE_LINKS.get(city_slug)
    if not entry:
        return city_html
    community_page, ms_page = entry
    pages_dir = site_root / "pages"
    links = []
    if community_page and (pages_dir / community_page).exists():
        links.append(
            '<a class="cmx-link" href="/pages/' + community_page + '">'
            "Explore " + city_label + " &rarr;</a>"
        )
    if ms_page and (pages_dir / ms_page).exists():
        links.append(
            '<a class="cmx-link" style="margin-left:18px;" href="/pages/' + ms_page + '">'
            + city_label + " market stats &amp; 10-year trends &rarr;</a>"
        )
    if not links:
        return city_html
    block = '<div class="sold-explore-links" style="margin-top:22px;">' + "".join(links) + "</div>\n"
    if SOLD_RECORDS_END in city_html:
        return city_html.replace(SOLD_RECORDS_END, block + SOLD_RECORDS_END, 1)
    return city_html + block


def _render_sold_city_html(template_html: str, city_slug: str, city_label: str, count: int) -> str:
    """Render a per-city sold-rollup HTML page from the parent template.

    String-substitutes the SEO-critical fields with city-specific values:
        - <title> + og:title + twitter:title
        - <meta name="description"> + og:description + twitter:description
        - <link rel="canonical"> + og:url
        - JSON-LD WebPage name + url + description
        - Visible H1 in body
        - Adds inline <script>window.SOLD_DATA_URL = "...";</script> before sold-listings.js

    Convention #74 fail-safe: if any expected substring is missing from the
    template (e.g., the template changed since this function shipped), the
    .replace() is a no-op and we still emit a valid HTML page — just without
    that particular SEO improvement.
    """
    site_origin = "https://labwestrealty.com"
    page_url = site_origin + "/listings/sold/" + city_slug + "/"
    data_url = "/listings/sold/" + city_slug + "/data.json"

    new_title = "Sold Listings " + city_label + ", NL — Royal LePage Turner Realty"
    new_desc = (
        "Search " + str(count) + "+ sold home prices in " + city_label
        + ", NL. Free registration required to view sold prices. Royal LePage Turner Realty."
    )
    new_desc_short = (
        "Search " + str(count) + "+ sold home prices in " + city_label
        + ", NL. Free registration required to view sold prices."
    )
    new_jsonld_name = "Sold Listings " + city_label + ", NL"
    new_jsonld_desc = (
        "Search sold home prices in " + city_label
        + ", NL. Free registration required to view sold prices."
    )

    out = template_html

    # Title tags
    out = out.replace(
        "<title>Sold Listings Labrador City & Wabush — Royal LePage Turner Realty</title>",
        "<title>" + new_title + "</title>",
    )
    # Self-canonical pilot (2026-08-05, Conv #15 port from Avalon 2026-07-30):
    # the 1 town in
    # SOLD_SELF_CANONICAL_CITIES now get their OWN canonical instead of the
    # parent's, since they carry real unique content -- everyone else keeps
    # the 2026-06-12 consolidation behaviour below unchanged.
    if city_slug in SOLD_SELF_CANONICAL_CITIES:
        out = out.replace(
            '<link rel="canonical" href="https://labwestrealty.com/listings/sold/">',
            '<link rel="canonical" href="' + page_url + '">',
        )
    # Canonical URL — GSC Duplicate-canonical fix (2026-06-12, Conv #15 port
    # of Gander 1a620622d 2026-05-25): per-city sold rollups keep the PARENT
    # /listings/sold/ canonical. Google flagged st-philips/ + arnolds-cove/
    # as "Duplicate, Google chose different canonical than user" — declaring
    # the parent consolidates equity where Google already sends it. Pages
    # stay reachable for direct links (og:url/title/desc stay city-specific).
    # (Canonical replacement deliberately removed — parent canonical carries
    # through from the template unchanged.)
    # Meta description
    old_meta_desc = '<meta name="description" content="Search sold home prices across Labrador City & Wabush. Free registration required to view sold prices. Royal LePage Turner Realty.">'
    new_meta_desc = '<meta name="description" content="' + new_desc + '">'
    out = out.replace(old_meta_desc, new_meta_desc)
    # OG tags
    out = out.replace(
        '<meta property="og:url" content="https://labwestrealty.com/listings/sold/">',
        '<meta property="og:url" content="' + page_url + '">',
    )
    out = out.replace(
        '<meta property="og:title" content="Sold Listings Labrador City & Wabush — Royal LePage Turner Realty">',
        '<meta property="og:title" content="' + new_title + '">',
    )
    out = out.replace(
        '<meta property="og:description" content="Search sold home prices across Labrador City & Wabush. Free registration required to view sold prices.">',
        '<meta property="og:description" content="' + new_desc_short + '">',
    )
    # Twitter card
    out = out.replace(
        '<meta name="twitter:title" content="Sold Listings Labrador City & Wabush — Royal LePage Turner Realty">',
        '<meta name="twitter:title" content="' + new_title + '">',
    )
    out = out.replace(
        '<meta name="twitter:description" content="Search sold home prices across Labrador City & Wabush. Free registration required to view sold prices.">',
        '<meta name="twitter:description" content="' + new_desc_short + '">',
    )
    # JSON-LD WebPage
    out = out.replace(
        '"name": "Sold Listings Labrador City & Wabush",',
        '"name": "' + new_jsonld_name + '",',
    )
    out = out.replace(
        '"url": "https://labwestrealty.com/listings/sold/",',
        '"url": "' + page_url + '",',
    )
    out = out.replace(
        '"description": "Search sold home prices across Labrador City & Wabush. Free registration required to view sold prices.",',
        '"description": "' + new_jsonld_desc + '",',
    )
    # Inject window.SOLD_DATA_URL + window.SOLD_CITY_SLUG + window.SOLD_CITY_LABEL
    # overrides before js/sold-listings.js script tag. The CITY_SLUG signal
    # tells sold-listings.js to replace the city dropdown filter group with a
    # "← View all sold listings across the Avalon" back-link, since the per-city
    # data.json is pre-filtered to one city and the dropdown would otherwise
    # render confusing "All cities (942) / Paradise (942)" legacy-fallback output.
    # Banked 2026-05-21 evening from Mike's screenshot bug report.
    # Lab West: match the tag with or without a ?v= stamp (Goose Bay's literal stamp went stale and the per-city data URL
    # override silently stopped being injected there; this site must never do that).
    _m = re.search(r'<script src="/js/sold-listings\.js(?:\?v=[^"]*)?"', out)
    if _m:
        inline_override = (
            '<script>'
            'window.SOLD_DATA_URL = "' + data_url + '";'
            'window.SOLD_CITY_SLUG = "' + city_slug + '";'
            'window.SOLD_CITY_LABEL = "' + city_label.replace('"', '\\"') + '";'
            '</script>\n'
        )
        out = out[:_m.start()] + inline_override + out[_m.start():]
    else:
        raise SystemExit("ddf-generate-pages: sold index template has no /js/sold-listings.js tag; per-town sold pages would lose their data URL")

    return out



def main() -> int:
    ap = argparse.ArgumentParser(description="Turner listing page generator")
    # Defaults are None so we can resolve relative to __file__ after parsing.
    # CWD-relative defaults bit us 2026-04-21 when a push block ran the
    # generator from the repo root and it silently skipped regeneration because
    # ./ddf-cache/listings.json didn't exist from that cwd. Per CLAUDE.md
    # Convention #15, the generator must work from any cwd.
    ap.add_argument("--cache",    default=None, help="Path to listings.json (default: <tools/>/idx-cache/listings-projected.json post-cutover 2026-05-21)")
    ap.add_argument("--site-root", default=None, help="Site root containing tools/ and listings/ (default: parent of <tools/>)")
    ap.add_argument("--limit",    type=int,       help="Generate first N pages only (for QA)")
    ap.add_argument("--listings-only", action="store_true", help="Skip city + index pages")
    ap.add_argument("--verbose",  action="store_true")
    ap.add_argument("--skip-check", action="store_true",
                    help="Skip the post-generation pre-deploy self-check (CI runs its own)")
    ap.add_argument("--no-manifest", action="store_true",
                    help="Skip writing tools/ddf-cache/deploy-manifest.json")
    ap.add_argument("--no-sweep", action="store_true",
                    help="Skip the stale-page sweep (don't delete pages no longer in cache, "
                         "don't update _redirects). Use only for testing — production runs "
                         "should always sweep so sold listings stop showing as active.")
    ap.add_argument("--no-viewpoint", action="store_true",
                    help="Skip Viewpoint consumer property pages "
                         "(/property/<town>/<slug>); scoped to VIEWPOINT_CANARY_TOWNS.")
    ap.add_argument("--no-rollups", action="store_true",
                    help="Skip filtered-rollup landing pages (new-construction, "
                         "first-time-buyer, commercial). Debugging aid only — "
                         "production runs should always emit rollups.")
    ap.add_argument("--rollups-only", action="store_true",
                    help="Regenerate only the rollup landing pages. Useful for "
                         "quick iteration on rollup copy/layout without doing a "
                         "full per-listing regen. Implies --no-sweep.")
    ap.add_argument("--counts-only", action="store_true",
                    help="Recompute the listing counts from the cache and patch only the count "
                         "outputs (count fragments, View-all numbers, data-lc spans, data.json "
                         "counts). The hourly run's skipped-regen path (sites 2026-10-08); "
                         "follow it with inject-ddf-fragments.py --apply.")
    args = ap.parse_args()

    if args.rollups_only and args.no_rollups:
        print("[GEN] --rollups-only and --no-rollups are mutually exclusive")
        return 2

    # Resolve paths relative to this script (not cwd) so the generator works
    # regardless of where it's invoked from. See CLAUDE.md Convention #15.
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    # Goosebay IDX/VOW cutover 2026-05-21 — primary cache switched from DDF
    # to IDX-direct projection (Convention #15 byte-symmetric from Avalon
    # cutover 52560d0d3 2026-05-20 / Gander cutover 2026-05-19). Generator
    # now reads listings-projected.json (output of idx-project-to-ddf-shape.py)
    # instead of ddf-cache/listings.json. The projection adapter emits
    # DDF-compatible row + envelope shape so downstream code is unchanged.
    if args.cache:
        cache_path = Path(args.cache).resolve()
    else:
        # The NLAR projected cache is the only source (CREA DDF retired
        # 2026-10-01; the DDF fallback to ddf-cache/listings.json is gone).
        # A projection-step failure under continue-on-error leaves the last
        # good projected file in place (it is committed and also restored
        # from the Actions cache), so the generator renders from that.
        cache_path = script_dir / "idx-cache" / "listings-projected.json"
    if not cache_path.exists():
        print(f"[GEN] cache file not found: {cache_path}")
        print("[GEN] run idx-ingest.py + idx-project-to-ddf-shape.py first (there is no DDF fallback)")
        return 1

    cache = json.loads(cache_path.read_text())
    global _COUNTS_AS_OF
    try:
        _COUNTS_AS_OF = datetime.fromisoformat(str(cache.get("generated_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        _COUNTS_AS_OF = None  # _site_counts falls back to now
    # Envelope-shape defensive accessor (Convention #113):
    # IDX-projected envelope uses "listings" key (matches DDF). Raw IDX
    # cache (idx-cache/listings.json from idx-ingest.py) uses "rows" key.
    # Accept either so the generator can run against any layer of the
    # pipeline for debug.
    listings = cache.get("listings") or cache.get("rows") or []
    if not listings:
        # Fail loud (always-on #16): with no DDF fallback, an empty NLAR cache
        # must stop the run, never sweep every page as "sold".
        print(f"[GEN] cache contained no rows (envelope keys: {list(cache.keys())})")
        return 1

    print(f"[GEN] cache source: {cache_path.name} ({cache.get('source', 'unknown')}, {len(listings)} rows)")

    # ── Track A.2 IDX overlay (Convention #15 propagation 2026-05-08) ──
    # Enrich each DDF listing with the matching IDX/VOW record from
    # tools/idx-cache/listings.json by MLS#. IDX has 91 fields per listing
    # vs DDF's ~30; the overlay surfaces NL-specific consumer fields
    # (HeatingCooling, Foundation, Garage*, Schools, Operating Costs)
    # on listing-detail pages.
    #
    # Graceful degrade: if IDX cache is absent (e.g. fresh clone before
    # idx-ingest.py has run), generator continues on DDF-only data with
    # no enrichment. Same applies to individual listings without an IDX
    # match (the listings that opted out of IDX/VOW —
    # PublishToInternetSitesYN=0 or PublishToPublicSitesYN=0).
    idx_cache_path = script_dir / "idx-cache" / "listings.json"
    idx_overlay = {}
    if idx_cache_path.exists():
        try:
            idx_data = json.loads(idx_cache_path.read_text())
            idx_rows = idx_data.get("rows", [])
            idx_overlay = {
                str(r.get("MLSNumber", "")).strip(): r
                for r in idx_rows
                if r.get("MLSNumber")
            }
            print(f"[GEN] IDX overlay loaded: {len(idx_overlay):,} records "
                  f"from {idx_cache_path.relative_to(script_dir)}")
        except (json.JSONDecodeError, OSError) as e:
            print(f"[GEN] IDX overlay load failed (continuing on DDF-only): {e}")

    # ── Rooms cache load (Convention #15 from realestategander-site Client Full ship) ──
    # PropertySubTable:Room records pulled by idx-ingest.py --pull rooms.
    # Keyed by Matrix_Unique_ID (MUI). Convention #74 graceful degrade.
    rooms_cache_path = script_dir / "idx-cache" / "rooms-listings.json"
    rooms_by_mui = {}
    if rooms_cache_path.exists():
        try:
            rooms_data = json.loads(rooms_cache_path.read_text())
            rooms_by_mui = rooms_data.get("by_mui", {}) or {}
            print(f"[GEN] Rooms cache loaded: {len(rooms_by_mui):,} listings "
                  f"have rooms data from {rooms_cache_path.relative_to(script_dir)}")
        except (json.JSONDecodeError, OSError) as e:
            print(f"[GEN] Rooms cache load failed (continuing without rooms): {e}")

    # ── Open-house cache load (Batch F1 close-out, 2026-08-20, Convention
    # #15 port from Gander) ──────────────────────────────────────────────
    # OpenHouse RETS resource pulled by idx-openhouse-sync.py -- keyed by
    # Matrix_Unique_ID, same MLS->MUI bridge as the rooms cache just above.
    # Missing/stale cache -> no banner, never an error (Conv #74).
    oh_cache_path = script_dir / "idx-cache" / "open-houses.json"
    oh_by_mui = {}
    if oh_cache_path.exists():
        try:
            oh_data = json.loads(oh_cache_path.read_text())
            oh_by_mui = oh_data.get("by_mui", {}) or {}
            print(f"[GEN] Open-house cache loaded: {len(oh_by_mui):,} listings "
                  f"have upcoming open-house data from {oh_cache_path.relative_to(script_dir)}")
        except (json.JSONDecodeError, OSError) as e:
            print(f"[GEN] Open-house cache load failed (continuing without open houses): {e}")

    # Merge selected IDX fields into each DDF listing under namespaced keys.
    # Track A.2 — listing-detail enrichment (Heating/Foundation/Garage/Schools/
    # Utilities & Fees). Conditional rendering downstream — only listings
    # with matching IDX records AND populated target fields get the new
    # Property Details rows.
    if idx_overlay:
        _IDX_FIELD_MAP = {
            # Track A.2a — Property Details rows (Heating + Foundation + Garage)
            "HeatingCooling":      "idx_heating",
            "Foundation":          "idx_foundation",
            "GarageType":          "idx_garage_type",
            "GarageAreaSqFt":      "idx_garage_sqft",
            # Pre-construction rollup (2026-08-09, Convention #15 port from
            # Avalon 2026-05-24) -- "To Be Built" on either field is the
            # pre-construction signal; see _is_pre_construction() below.
            "YearBuiltDesc":       "idx_year_built_desc",
            "NewConstructionOnly": "idx_new_construction_only",
            # Lease listings (sites, D-1009-77, 2026-10-09): the feed's own
            # SALE/LEASE flag, lease price and lease type. tools/_listing_terms.py
            # reads them; rows ingested before they were kept fall back to the
            # counted remarks/price-floor rules.
            "TransactionType":     "idx_transaction_type",
            "LeasePrice":          "idx_lease_price",
            "Leasetype":           "idx_lease_type",
            # Track A.2b — Operating Costs section (utility responsibility + fees)
            "HeatingBill":         "idx_heating_bill",
            "WaterBill":           "idx_water_bill",
            "ElectricBill":        "idx_electric_bill",
            "CondoFee":            "idx_condo_fee",
            "Taxamount":           "idx_tax_amount",
            "Taxyear":             "idx_tax_year",
            "MobileLeasedLandFees": "idx_mobile_lease_fee",
            # Track A.2c — Schools rows in Property Details (Decision F = a)
            # NOTE: lowercase 's' is RETS schema spelling per metadata verification 2026-05-07.
            "Elementaryschool":    "idx_elementary_school",
            "Secondaryschool":     "idx_secondary_school",
            # Features chips (task #80 parity port from Gander, 2026-07-29)
            "Features":            "idx_features",
            "InteriorFeatures":    "idx_interior_features",
            "LandFeatures":        "idx_land_features",
            "Services":            "idx_services",
            # Agent + office (Convention #15 from realestategander-site, added 2026-05-19).
            # Required by _emit_team_listings_fragment() filter — without these the
            # filter rejects everything because idx_list_agent_full_name is empty.
            # Mike confirmed via NLAR Matrix: Karen Pomeroy has 2 active listings
            # (4 Terrington Boat Club Road + 27 Ikey Street) that should populate
            # the team-listings fragment.
            "ListAgentFullName":   "idx_list_agent_full_name",
            "ListOfficeName":      "idx_office_name",
        }
        idx_match_count = 0
        for lst in listings:
            mls = str(lst.get("mls", "")).strip()
            if not mls:
                continue
            idx_rec = idx_overlay.get(mls)
            if not idx_rec:
                continue
            idx_match_count += 1
            for src, dst in _IDX_FIELD_MAP.items():
                v = idx_rec.get(src, "")
                if v and str(v).strip() and str(v).strip() not in ("0", "0.0"):
                    lst[dst] = str(v).strip()
            # Attach rooms (Convention #15 from Gander Client Full ship)
            mui = str(idx_rec.get("Matrix_Unique_ID", "")).strip()
            if mui and mui in rooms_by_mui:
                lst["idx_rooms"] = rooms_by_mui[mui]
            # Open-house next-event pick (Batch F1 close-out, 2026-08-20).
            # The cache is a 30-day-horizon superset; pick the SOONEST event
            # that has not already passed by the time THIS regen runs.
            if mui and mui in oh_by_mui:
                today_s = datetime.now(timezone.utc).date().isoformat()
                upcoming = [e for e in oh_by_mui[mui] if e.get("date", "") >= today_s]
                if upcoming:
                    lst["idx_open_house_next"] = upcoming[0]
        print(f"[GEN] IDX overlay applied: {idx_match_count}/{len(listings)} "
              f"listings enriched ({100*idx_match_count/len(listings):.1f}%)")
        rooms_match_count = sum(1 for l in listings if l.get("idx_rooms"))
        if rooms_match_count:
            print(f"[GEN] Rooms attached: {rooms_match_count}/{len(listings)} "
                  f"listings have room-by-room data")

    # ── Stale-active gate (task #117) ──────────────────────────────
    # Hide listings whose modification_timestamp is > STALE_ACTIVE_THRESHOLD_DAYS
    # old. Runs BEFORE --limit so the filter is deterministic regardless of
    # QA truncation. The existing stale-page sweep 301s any prior HTML to
    # its city landing.
    _cache_size = len(listings)
    listings, stale_gated = _filter_stale_active(listings)
    if stale_gated:
        print(
            f"[GEN] stale-active gate: dropped {len(stale_gated)} of {_cache_size} "
            f"listing(s) with mod_ts > {STALE_ACTIVE_THRESHOLD_DAYS}d"
        )
        for lst in stale_gated:
            mod = lst.get("modification_timestamp") or "?"
            mls = lst.get("mls") or lst.get("listing_key") or "?"
            city = lst.get("city_raw") or lst.get("city_slug") or "?"
            print(f"  · drop MLS {mls} ({city}) — last modified {mod}")
    stale_gate_summary = {
        "ran": True,
        "threshold_days": STALE_ACTIVE_THRESHOLD_DAYS,
        "cache_size": _cache_size,
        "dropped": len(stale_gated),
        "dropped_mls": [
            (l.get("mls") or l.get("listing_key") or "?")
            for l in stale_gated
        ],
    }


    # ── Lease-listing normalize (task #51) ──────────────────────────
    # Convention #15 byte-symmetric port from Gander canonical.
    # DDF feed flows lease-rate-per-sqft + monthly-rent through list_price
    # for commercial leases. Mike caught MLS 1297866 Goosebay rendering as
    # "$50" when it's actually a $50/sqft build-to-suit. Normalize in-place:
    # preserve original as lease_rate, null list_price, set is_lease=True.
    _lease_normalized = _normalize_lease_listings(listings)
    # Positive heartbeat every build (always-on #8): how many leases, how many
    # came from TransactionType vs the fallbacks, and how each rent shows.
    print(_lr.heartbeat(_LEASE_COUNTS))
    lease_gate_summary = {
        "ran": True,
        "normalized": _lease_normalized,
    }
    if args.limit:
        listings = listings[:args.limit]

    site_root = Path(args.site_root).resolve() if args.site_root else repo_root

    # --counts-only (sites 2026-10-08): skipped-regen hourly runs, from these same rows.
    if args.counts_only:
        return _counts_only(listings, site_root)

    # Convention #15 from Gander 2026-05-27 — apply local photos if
    # .meta.json sentinels exist (R2 mode) or 001.jpg files exist (disk
    # mode). Mutates listings in place; sets _local_photos: True + _hero_url.
    # Placed AFTER site_root assignment (UnboundLocalError fix from earlier
    # mis-placement at line 4319 before site_root was defined).
    local_photo_count = _apply_local_photos(listings, site_root)
    print(f"_apply_local_photos: {local_photo_count}/{len(listings)} listings on local/R2 photos")
    listings_dir = site_root / "listings"
    listings_dir.mkdir(exist_ok=True)

    # Pre-compute rollups so we can guard against slug collisions with cities
    # before we write anything. ROLLUP_SLUGS is a module-level frozenset so
    # this is a cheap check.
    # ── emit_team_listings_fragment (Convention #15 from Gander) ──
    # Mike 2026-05-19: agent profile "Active inventory" section should
    # show only Turner Realty team's actual listings, not all Goosebay-area
    # DDF brokerages. Filter by Karen Pomeroy + Roberta Primmer.
    def _emit_team_listings_fragment():
        # TEAM_NAMES / _is_team: module level since 2026-10-08 (shared with --counts-only).
        team_pool = [L for L in _sort_listings_for_display(listings) if _is_team(L)]

        fragments_dir = site_root / "tools" / FRAGMENT_DIR_NAME
        fragments_dir.mkdir(parents=True, exist_ok=True)

        try:
            generated_at_str = datetime.now(timezone.utc).isoformat()
        except NameError:
            from datetime import datetime as _dt, timezone as _tz
            generated_at_str = _dt.now(_tz.utc).isoformat()
        try:
            git_sha_str = _git_sha(site_root) or "unknown"
        except NameError:
            git_sha_str = "unknown"

        team_fragment = build_fragment(
            team_pool,
            "team-listings",
            viewall_href="/listings/",
            viewall_label=f"View all {_lc.available_count(team_pool):,} Turner Realty team listings",
            total_count=_lc.available_count(team_pool),
            limit=FRAGMENT_DEFAULT_LIMIT,
            sort=False,
        )
        team_header = (
            f"<!-- ddf-fragment:team-listings | generated_at={generated_at_str} | "
            f"git_sha={git_sha_str} | pool_size={len(team_pool)} | "
            f"shown={min(FRAGMENT_DEFAULT_LIMIT, len(team_pool))} -->\n"
        )
        out_path = fragments_dir / "team-listings.html"
        out_path.write_text(team_header + team_fragment)

        def _emit_aux(name, body, n):
            (fragments_dir / f"{name}.html").write_text(
                f"<!-- ddf-fragment:{name} | generated_at={generated_at_str} | git_sha={git_sha_str} | "
                f"pool_size={n} | shown={n} -->\n{body}")
        site_counts = _site_counts(listings)
        _emit_aux("team-listings-count", _lc.count_badge(_lc.available_count(team_pool)), len(team_pool))

        # featured-listings (2026-09-08 homepage redesign): every active listing,
        # newest first -- the "All active Labrador MLS listings" tab on the
        # homepage. Same header shape as team-listings so inject-ddf-fragments.py
        # strips it identically. Convention #74: an empty pool still writes a
        # valid (empty-grid) fragment rather than leaving a stale one behind.
        featured_pool = _sort_listings_for_display(listings)
        featured_fragment = build_fragment(
            featured_pool, "featured-listings",
            viewall_href="/listings/",
            viewall_label=f"View all {site_counts['available']:,} available listings",
            total_count=site_counts["available"],
            limit=FRAGMENT_DEFAULT_LIMIT,
            sort=False,
        )
        featured_header = (
            f"<!-- ddf-fragment:featured-listings | generated_at={generated_at_str} | "
            f"git_sha={git_sha_str} | pool_size={len(featured_pool)} | "
            f"shown={min(FRAGMENT_DEFAULT_LIMIT, len(featured_pool))} -->\n"
        )
        (fragments_dir / "featured-listings.html").write_text(featured_header + featured_fragment)
        # Tab badges + one summary line under the tabs, refreshed with the hourly injection
        # (the baked badges were frozen: 38 on the tab against 30 on the page).
        _emit_aux("featured-listings-count", _lc.count_badge(site_counts["available"]), site_counts["available"])
        _emit_aux("listings-summary", _lc.summary_span(site_counts), site_counts["available"])
        _lc.refresh_baked_counts(fragments_dir, site_counts)
        print(_lc.heartbeat(site_counts, "ran"))
        if args.verbose:
            print(f"[GEN]  → tools/{FRAGMENT_DIR_NAME}/team-listings.html "
                  f"({min(FRAGMENT_DEFAULT_LIMIT, len(team_pool))} of {len(team_pool)})")
        return {
            "name": "team-listings",
            "shown": min(FRAGMENT_DEFAULT_LIMIT, len(team_pool)),
            "pool_size": len(team_pool),
        }

    # Run team-listings emit before rollups (so it ships even if rollups
    # are skipped via --no-rollups).
    _team_summary = _emit_team_listings_fragment()

    # ── community-<slug>: per-community active-listing fragments ──
    # 2026-07-29: found via the 3-site convergence audit + confirmed live --
    # tools/build-community-pages.py writes the <!-- DDF_FRAGMENT:
    # community-<slug> --> sentinel wrapper on both Goose Bay community pages,
    # but NOTHING ever wrote the fragment file it splices in, so both pages
    # showed a "Homes for Sale in ..." heading over an empty section forever.
    #
    # Mirrors Gander's MULTI_CITY_FRAGMENTS pattern (Convention #15) at the
    # smallest scale that fits: Goose Bay has exactly 2 communities and both
    # map 1:1 onto a real city_slug (verified against the live projected
    # cache: happy-valley-goose-bay=34 rows, north-west-river=3 rows) -- no
    # multi-town aggregation is needed the way Gander's Loop needs it.
    COMMUNITY_LISTING_FRAGMENTS = [
        {"slug": "labrador-city", "city_slugs": ["labrador-city"],
         "display": "Labrador City",
         "viewall_href": "/listings/labrador-city/"},
        {"slug": "wabush", "city_slugs": ["wabush"],
         "display": "Wabush",
         "viewall_href": "/listings/wabush/"},
    ]

    def _emit_community_listings_fragments():
        fragments_dir = site_root / "tools" / FRAGMENT_DIR_NAME
        fragments_dir.mkdir(parents=True, exist_ok=True)
        generated_at_str = datetime.now(timezone.utc).isoformat()
        git_sha_str = _git_sha(site_root) or "unknown"
        summaries = []
        for cfg in COMMUNITY_LISTING_FRAGMENTS:
            pool = [L for L in listings if L.get("city_slug") in cfg["city_slugs"]]
            pool = _sort_listings_for_display(pool)
            name = f"community-{cfg['slug']}"
            count = len(pool)
            fragment_html = build_fragment(
                pool, name,
                viewall_href=cfg["viewall_href"],
                viewall_label=(f"View all {_lc.available_count(pool):,} available listing"
                               f"{'s' if _lc.available_count(pool) != 1 else ''} in {cfg['display']}"),
                total_count=_lc.available_count(pool),
                limit=FRAGMENT_DEFAULT_LIMIT,
                sort=False,
            )
            header = (
                f"<!-- ddf-fragment:{name} | generated_at={generated_at_str} | "
                f"git_sha={git_sha_str} | pool_size={count} | "
                f"shown={min(FRAGMENT_DEFAULT_LIMIT, count)} -->\n"
            )
            out_path = fragments_dir / f"{name}.html"
            out_path.write_text(header + fragment_html)
            if args.verbose:
                print(f"[GEN]  → tools/{FRAGMENT_DIR_NAME}/{name}.html "
                      f"({min(FRAGMENT_DEFAULT_LIMIT, count)} of {count})")
            summaries.append({"name": name, "shown": min(FRAGMENT_DEFAULT_LIMIT, count),
                               "pool_size": count})
        return summaries

    _community_summaries = _emit_community_listings_fragments()

    emit_rollups = not args.no_rollups
    by_rollup: dict[str, list[dict]] = {}
    rollup_collisions: list[str] = []
    if emit_rollups:
        # Collect all city slugs that would appear on disk. We check against
        # the full listings set (not by_city, which we haven't built yet in
        # --rollups-only mode) so this catches collisions regardless of code
        # path.
        all_city_slugs = {l["city_slug"] for l in listings}
        for cfg in ROLLUPS:
            if cfg["slug"] in all_city_slugs:
                rollup_collisions.append(cfg["slug"])
                continue
            matching = [l for l in listings if cfg["filter"](l)]
            by_rollup[cfg["slug"]] = matching
        if rollup_collisions:
            print(
                f"[GEN] ⚠ rollup/city slug collision — skipping rollup(s): "
                f"{', '.join(rollup_collisions)}"
            )
    rollup_slugs_emitted: frozenset[str] = frozenset(by_rollup.keys())

    # --rollups-only path: regenerate just the rollup indexes and return.
    # Implies --no-sweep (we haven't populated by_city so the sweep would
    # reap every non-rollup page on disk). Useful for fast iteration on
    # rollup copy and markup.
    if args.rollups_only:
        if not emit_rollups:
            # Caught earlier by mutual-exclusion check, but belt-and-braces.
            print("[GEN] --rollups-only with --no-rollups is a no-op")
            return 2
        rollup_written = 0
        for cfg in ROLLUPS:
            if cfg["slug"] not in by_rollup:
                continue
            rdir = listings_dir / cfg["slug"]
            rdir.mkdir(exist_ok=True)
            out_path = rdir / "index.html"
            out_path.write_text(build_rollup_page(cfg, by_rollup[cfg["slug"]]))
            rollup_written += 1
            if args.verbose:
                print(f"  → {out_path.relative_to(site_root)}  "
                      f"({len(by_rollup[cfg['slug']])} listings)")
        print(f"[GEN] wrote {rollup_written} rollup landing pages (rollups-only)")
        return 0

    # Firm ("sale pending") listings — a SEPARATE list on purpose. Six places
    # compute active inventory from len(listings); a home under contract is not
    # active inventory (Conv #45), so these never join that list.
    pending_listings = _load_pending_listings(script_dir, site_root)
    if pending_listings:
        print(f"[GEN] sale-pending: {len(pending_listings)} firm listing(s) "
              f"will keep their pages (excluded from active counts)")
        if "_apply_local_photos" in globals():
            _apply_local_photos(pending_listings, site_root)
        # Resolve the "see active homes" target ONCE, here, where the active set
        # is known. A pending-only city's index has been swept to a 301 — linking
        # it is a real broken link, and on 2026-07-27 that exit-1'd the Gander
        # regen and froze the site for ~43h because the commit step never runs
        # after a failed regen step.
        _active_city_slugs = {(l.get("city_slug") or "").strip().lower()
                              for l in listings if l.get("city_slug")}
        _orphaned = 0
        for _p in pending_listings:
            _cs = (_p.get("city_slug") or "").strip().lower()
            if _cs and _cs in _active_city_slugs:
                _p["_city_link"] = f"../../listings/{_cs}/"
                _p["_city_link_label"] = f"See active homes in {city_display_name(_cs)}"
            else:
                _p["_city_link"] = "../../listings/"
                _p["_city_link_label"] = "Browse all active listings"
                _orphaned += 1
        if _orphaned:
            print(f"[GEN] sale-pending: {_orphaned} pending page(s) are in cities "
                  f"with no active index → linked to /listings/ instead")

    print(f"[GEN] generating {len(listings)} listing pages → {listings_dir}/")

    written = 0
    by_city: dict[str, list[dict]] = {}
    for lst in listings:
        # Output path: <site_root>/listings/<city>/<slug>.html
        city_dir = listings_dir / lst["city_slug"]
        city_dir.mkdir(exist_ok=True)
        out_path = city_dir / f"{lst['slug']}.html"
        out_path.write_text(build_listing_page(lst, all_listings=listings))
        written += 1
        by_city.setdefault(lst["city_slug"], []).append(lst)
        if args.verbose:
            print(f"  → {out_path.relative_to(site_root)}")

    print(f"[GEN] wrote {written} listing detail pages across {len(by_city)} cities")

    # Pending pages go in the SAME tree so their URLs are unchanged — the page
    # the buyer bookmarked and Google indexed keeps working. NOT added to
    # by_city, so city-index counts and cards stay strictly active-only.
    pending_written = 0
    for lst in pending_listings:
        try:
            city_dir = listings_dir / lst["city_slug"]
            city_dir.mkdir(exist_ok=True)
            (city_dir / f"{lst['slug']}.html").write_text(
                build_listing_page(lst, all_listings=listings))
            pending_written += 1
        except Exception as e:
            print(f"[GEN] WARN: could not write pending page for {lst.get('mls')}: {e}")
    if pending_written:
        print(f"[GEN] wrote {pending_written} SALE PENDING page(s)")

    # /listings/data.json: the slim feed js/listings-index.js and the portal readers load
    # (site review 2026-09-29: replaces the public raw projected cache). Never on a --limit run.
    if args.limit:
        print("[GEN] discover feed skipped (--limit run)")
    else:
        discover_summary = emit_discover_data(
            listings, site_root,
            source_generated_at=cache.get("generated_at"),
            verbose=args.verbose,
        )
        if discover_summary.get("written"):
            print(f"[GEN] wrote discover feed -> {discover_summary['path']} "
                  f"({discover_summary['count']} listings, {discover_summary['bytes']:,} bytes)")

    if args.listings_only:
        return 0

    # City landing pages
    city_written = 0
    for slug, lst in by_city.items():
        out_path = listings_dir / slug / "index.html"
        out_path.write_text(build_city_page(slug, lst))
        city_written += 1
        if args.verbose:
            print(f"  → {out_path.relative_to(site_root)}")
    print(f"[GEN] wrote {city_written} city landing pages")

    # Rollup landing pages (new construction / first-time buyer / commercial).
    # These live at /listings/<rollup-slug>/index.html — same depth as city
    # landings, so they reuse the depth-2 prefix and card grid.
    rollup_written = 0
    if emit_rollups:
        for cfg in ROLLUPS:
            if cfg["slug"] not in by_rollup:
                continue  # collision with a city slug — already warned
            rdir = listings_dir / cfg["slug"]
            rdir.mkdir(exist_ok=True)
            out_path = rdir / "index.html"
            out_path.write_text(build_rollup_page(cfg, by_rollup[cfg["slug"]]))
            rollup_written += 1
            if args.verbose:
                print(f"  → {out_path.relative_to(site_root)}  "
                      f"({len(by_rollup[cfg['slug']])} listings)")
        print(f"[GEN] wrote {rollup_written} rollup landing pages")

    # Top-level /listings/index.html — DISABLED 2026-08-07. Replaced by
    # a hand-authored discovery shell (status-toggle/view-segment/sold-
    # layer engine, ported from Gander/Avalon the same day) at
    # listings/index.html, matching Avalon's promotion pattern (disabled
    # there 2026-05-22). Root cause of Mike's "the map search isn't
    # ported to Goose Bay" report: this exact write was silently
    # reverting the ported shell on every hourly/nightly regen (bot
    # commit 1fcbeee2f55d landed 7 min after the port shipped and swapped
    # the whole architecture back). build_index_page() kept in source for
    # now in case rollback needed; uncomment below to revert.
    # ---
    # index_path = listings_dir / "index.html"
    # index_path.write_text(build_index_page(listings, by_city, by_rollup))
    # print(f"[GEN] wrote all-listings index → {index_path.relative_to(site_root)}")
    index_path = listings_dir / "index.html"
    index_path.write_text(build_index_page(listings, by_city, by_rollup))
    print(f"[GEN] wrote all-listings index → {index_path.relative_to(site_root)}")

    # Viewpoint consumer property pages (HVGB canary — Happy Valley-Goose Bay).
    if not args.no_viewpoint:
        vp_summary = emit_viewpoint_pages(
            site_root, town_scope=VIEWPOINT_CANARY_TOWNS, verbose=args.verbose,
        )
        print(f"[GEN] wrote viewpoint pages → property/ ({vp_summary['emitted']} pages)")

    # Per-city sold rollups must run BEFORE build_sitemap so the new
    # /listings/sold/<city>/ URLs land in sitemap-listings.xml on this
    # cycle. emit_sold_data() doesn't run until further down in main()
    # but the per-city function reads from listings/sold/data.json which
    # is committed on origin -- so the per-city rollups can run
    # independently from the main data.json emit (Convention #69 atomic
    # ordering, Conv #15 port from Avalon 2026-07-30). GB carries no
    # shard fix (small feed, no sharding) so there is no bootstrap-gap
    # case here the way Avalon's does.
    sold_city_summary = emit_sold_city_rollups(site_root, verbose=args.verbose)

    # sitemap-listings.xml at the site root (includes rollup URLs at 0.85)
    sitemap_path = site_root / "sitemap-listings.xml"
    sitemap_path.write_text(build_sitemap(
        listings, by_city, by_rollup,
        sold_city_slugs=sold_city_summary.get("city_slugs", []),
    ))
    print(f"[GEN] wrote sitemap → {sitemap_path.relative_to(site_root)}")

    # ── Stale-page sweep: delete listings no longer in the cache ──
    # Sold/withdrawn/expired listings come off the DDF feed; without this,
    # their HTML lingers on disk and Google keeps the URL indexed as "active".
    # We replace each stale page with a 301 to its city landing page, persist
    # the redirect in tools/ddf-cache/swept-listings.json, and rewrite the
    # managed block in <site_root>/_redirects. Rollup index pages are passed
    # through as "expected" so the sweep never reaps them.
    sweep_summary = None
    if not args.no_sweep:
        print("[GEN] sweeping stale listing pages …")
        sweep_summary = _sweep_stale_listings(
            site_root, listings_dir, listings, by_city,
            verbose=args.verbose,
            rollup_slugs=rollup_slugs_emitted,
            pending_listings=pending_listings,
        )
        print(
            f"[GEN] sweep: {sweep_summary['detail_pages_removed']} detail page(s) removed, "
            f"{sweep_summary['city_indexes_removed']} city index(es) removed, "
            f"{sweep_summary['newly_swept_urls']} new 301(s), "
            f"{sweep_summary['reactivated_urls']} reactivated, "
            f"{sweep_summary['total_redirects_in_file']} total in _redirects"
        )

    # ── Sold canary data.json (Conv #15 port 2026-06-11) — Conv #74:

    # emit_sold_data self-skips when the sold cache is absent/thin.

    print("[GEN] emitting sold canary data.json …")

    sold_summary = emit_sold_data(site_root, verbose=getattr(args, 'verbose', False))

    if isinstance(sold_summary, dict) and 'count' in sold_summary:

        print(f"[GEN] wrote listings/sold/data.json ({sold_summary.get('count', '?')} rows)")

    # ── Search suggestions index v2 (2026-10-08, sites; Mike D-1008-86) ──
    # listings/search-index.json: listings, places, streets, pages (p), "Go to"
    # intents (i) and sold streets (ss, no price). Contract:
    # _research/search_index_contract_2026-10-08.md. Fleet-canonical builder
    # (tools/_search_index.py, byte-identical on Gander/Avalon); never raises
    # (Conv #74). After emit_sold_data so ss reads this run's sold rows.
    # Skipped on --limit QA runs so a truncated index can never be written.
    if not args.limit:
        try:
            from _search_index import emit_for_generator as _emit_search_index
            _emit_search_index(site_root, listings, site_key=_SITE_CFG["site_key"],
                               city_name=city_display_name, verbose=getattr(args, 'verbose', False))
        except Exception as _si_err:  # noqa: BLE001
            print(f"[GEN] search-index skipped: {_si_err!r}")


    # ── Prune dead links from the hand-authored "Newest listings" block ──
    # listings/index.html carries a STATIC <ul class="lst-hub-newest"> of hard-coded
    # detail links; when one sells its page is swept above, the link 404s, and the
    # broken-link self-check below HARD-FREEZES the whole deploy (task #77, Conv #15
    # port of Avalon df876389). Drop only the already-dead ones, keep every valid link.
    # Crawler-visible sold records. Placed here deliberately: emit_sold_data
    # has just written data.json and emit_viewpoint_pages has already written
    # the /property/ tree, so the rows are current and the deep-link existence
    # check is meaningful.
    emit_sold_public_records(site_root, verbose=getattr(args, "verbose", False))

    _prune_dead_hub_links(site_root)

    # ── Self-validation: invoke pre-deploy-check scoped to listings/ ──
    # Closes the "I forgot to run the check" failure mode that bit us on the
    # first push attempt. Errors here fail the generator so you can't push
    # broken pages even if you forget to run the check manually.
    check_errors = check_warnings = 0
    if not args.skip_check:
        print("[GEN] running pre-deploy self-check on listings/ …")
        check_errors, check_warnings = _run_self_check(site_root)
        if check_errors:
            print(f"[GEN] ❌ self-check found {check_errors} error(s), {check_warnings} warning(s)")
            print("[GEN] re-run `python3 pre-deploy-check.py --scope listings/` for details")
        else:
            print(f"[GEN] ✅ self-check passed ({check_warnings} warning(s))")

    # ── Deploy manifest: provenance + content fingerprint for traceability ──
    # "Did the deploy actually land?" becomes a trivial diff against the last
    # manifest instead of inferring from `git push` exit code.
    if not args.no_manifest:
        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "listing_count": written,
            "city_count": len(by_city),
            "rollups": {
                "ran": emit_rollups,
                "written": rollup_written,
                "collisions": rollup_collisions,
                "counts": {slug: len(lst) for slug, lst in by_rollup.items()},
            },
            "output_hash": _hash_listings_dir(listings_dir),
            # 2026-09-17 error sweep: a template-only ship (no listing data changed)
            # never got re-rendered on a quiet site -- check-changes-gate.py's skip-regen
            # gate only ever looked at IDX upsert/photo counts, so B3's mobile swipe
            # gallery merged and its own deploy landed, but the hourly regen kept
            # skipping (0 data delta) and the generator that would have RENDERED the
            # new markup into listing pages never ran. This fingerprint lets the gate
            # tell "generator code changed since our last real regen" apart from
            # "nothing changed" without any human remembering to pass force_regen.
            "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "git_sha": _git_sha(site_root),
            "self_check": {
                "ran": not args.skip_check,
                "errors": check_errors,
                "warnings": check_warnings,
            },
            "sweep": sweep_summary or {"ran": False},
            "stale_active_gate": stale_gate_summary,
            "lease_gate": lease_gate_summary,
            "cache_source": str(cache_path),
        }
        manifest_path = Path(__file__).parent / "ddf-cache" / "deploy-manifest.json"
        manifest_path.parent.mkdir(exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"[GEN] wrote deploy manifest → {manifest_path.relative_to(site_root)}")

    return 1 if check_errors else 0


if __name__ == "__main__":
    sys.exit(main())
