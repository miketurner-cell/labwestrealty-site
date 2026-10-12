#!/usr/bin/env python3
"""
listing_script.py -- the narration script + HMAC signature for Ship 4
("Listen to this listing", ~/.claude/plans/now-that-we-have-polymorphic-wolf.md,
Mike 2026-09-10). Stdlib-only, imported by each site's ddf-generate-pages.py
at page-BUILD time (cheap: no TTS call, no network -- only the caller emits
an already-signed, already-priced-in script for the browser to later POST
to netlify/functions/listing-audio.ts on first play).

Compliance (Canada, NLAR §15.g): every script speaks the brokerage +
MLS(R) number + office phone -- the same "Listing courtesy of X -- NLAR
MLS(R) #N" fact build_attribution() already renders, read aloud. This
generator only ever builds ACTIVE-listing pages (build_listing_page()) --
there is no close_price on this page type at all, so unlike reel-voice.py
this module carries no "sold" branch or price-suppression logic to get
wrong; the VOW T&C's close_price gate simply never applies here.

Remarks are spoken VERBATIM (Conv #45/#32) -- never paraphrased, never
regenerated -- capped only by length, at a sentence boundary where
possible, never mid-word.
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import re

MAX_SCRIPT_CHARS = 1600  # ~90-110s spoken; bounds both narration length and TTS cost


def _fmt_price(v) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return ""
    return f"${n:,.0f}"


def _truncate_at_boundary(text: str, limit: int) -> str:
    """Cut at the last sentence-ending punctuation before `limit`, or the
    last space if no sentence boundary exists -- never mid-word, and never
    silently drops the cut (a trailing space/ellipsis is not injected;
    the caller's own closing sign-off sentence follows immediately)."""
    text = text.strip()
    if len(text) <= limit:
        return text
    window = text[:limit]
    for punct in (". ", "! ", "? "):
        idx = window.rfind(punct)
        if idx > limit * 0.4:  # don't cut absurdly short just to hit a boundary
            return window[:idx + 1].strip()
    idx = window.rfind(" ")
    return (window[:idx] if idx > 0 else window).strip()


def build_listing_script(listing: dict, *, address: str, office: str, phone: str) -> str:
    """The full spoken tour. `address`/`office`/`phone` are passed in
    already-computed by the caller (matches build_attribution()'s own
    idx_office_name-then-listing_brokerage fallback and the page's own
    `address = f"{street}, {city} NL"` line) so this module never
    re-derives a fact a page section already computed differently."""
    mls = str(listing.get("mls") or "").strip()
    price_s = _fmt_price(listing.get("list_price"))

    beds = listing.get("bedrooms")
    baths = listing.get("bathrooms")
    specs = []
    try:
        if beds not in (None, ""):
            b = int(float(beds))
            specs.append(f"{b} bedroom{'s' if b != 1 else ''}")
    except (TypeError, ValueError):
        pass
    try:
        if baths not in (None, ""):
            ba = float(baths)
            ba_s = f"{ba:g}"
            specs.append(f"{ba_s} bathroom{'s' if ba != 1 else ''}")
    except (TypeError, ValueError):
        pass

    parts = [f"{address}."]
    if price_s:
        parts.append(f"Listed at {price_s}.")
    if specs:
        parts.append(", ".join(specs).capitalize() + ".")

    remarks = (listing.get("public_remarks") or "").strip()
    remarks = " ".join(remarks.split())  # collapse the vendor's own irregular whitespace
    if remarks:
        # Budget: leave room for the sign-off sentences below (~180 chars)
        # inside MAX_SCRIPT_CHARS, so remarks get the truncation, not them.
        already = sum(len(p) + 1 for p in parts)
        remarks_budget = max(200, MAX_SCRIPT_CHARS - already - 200)
        parts.append(_truncate_at_boundary(remarks, remarks_budget))

    parts.append(f"Listing courtesy of {office}, NLAR MLS number {mls}.")
    parts.append(f"Royal LePage Turner Realty, {phone}.")

    script = " ".join(p.strip() for p in parts if p and p.strip())
    return script[:MAX_SCRIPT_CHARS]


def sign_payload(site: str, mls: str, script: str, secret: str) -> str:
    """HMAC-SHA256 hex digest over `site|mls|script` -- site and mls are
    included in the signed payload (not just the script) specifically so
    a valid {script, sig} pair from one listing can't be replayed against
    a DIFFERENT site/mls to write a mislabeled R2 object; the browser can
    only ever submit exactly what the generator signed, byte for byte."""
    payload = f"{site}|{mls}|{script}".encode("utf-8")
    return _hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def script_hash(script: str) -> str:
    """Short content-addressed key fragment for the R2 cache path -- same
    script text always resolves to the same cached object, so a listing
    whose remarks/price haven't changed never re-renders on a later build."""
    return hashlib.sha256(script.encode("utf-8")).hexdigest()[:16]
