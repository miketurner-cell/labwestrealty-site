"""The ONE definition of the listing counts every consumer-facing surface shows.

Sites session 2026-10-09 (plan item 4, D-1008-22/23). Fleet canonical: the file is
byte-identical on Gander, Avalon and Goose Bay (and in fleet/canonical/tools/).

Definition (nothing here is new; each rule is what the site already did somewhere):
  rows       the generator's own post-filter `listings` (the same rows that become
             listings/data.json), or any subset of them (team, ours, one town).
  re-listing two rows with the same street + unit + city_slug (street and city
             non-empty): only the newest is kept (list_date, list_price, mls,
             newest first). This is `_sort_listings_for_display`'s dedupe -- the one
             the homepage cards use -- plus the unit (see relist_key for why).
  pending    status that is not "Active" and matches PENDING_RE. This is
             `_status_is_pending` in ddf-generate-pages.py and `isPending()` in
             js/listings-index.js verbatim.
  available  rows left after the dedupe that are NOT pending   -> "N available"
  pending    rows left after the dedupe that ARE pending       -> "N conditional/pending"
  updated    the feed's own time (counts_as_of: the projected cache's generated_at),
             in America/St_Johns; see "Every-run refresh" below.

Pure functions; the only I/O is refresh_baked_counts() and refresh_count_outputs().
Python 3.10 compatible.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

PENDING_RE = re.compile(r"pending|under contract|conditional|stfrm|stcos", re.IGNORECASE)

PENDING_LABEL = "conditional/pending"
NL_TZ_NAME = "America/St_Johns"


def is_pending(status) -> bool:
    if not status or status == "Active":
        return False
    return bool(PENDING_RE.search(status))


def relist_key(row: dict):
    """(street, unit, city_slug) lower-cased, or None when street or city is
    missing (a row with missing address data is never dropped as a duplicate).

    UNIT is the one deliberate difference from `_sort_listings_for_display`
    (street + city only): on Avalon that rule folds 21 groups of genuinely
    different units / parcels (e.g. five "00 Saddle Hill" parcels, the suites
    at 136 Crosbie Road) into one row, which understates what is for sale and
    would drop real listings from search. Same address AND same unit is a
    re-listing. To get the old homepage rule back, return (street, "", city)."""
    street = (row.get("street") or "").strip().lower()
    city = (row.get("city_slug") or "").strip().lower()
    unit = (row.get("unit") or "").strip().lower()
    return (street, unit, city) if street and city else None


def dedupe_relistings(rows) -> list:
    """Newest row per address; order of the survivors is newest-first."""
    def sort_key(r):
        return (r.get("list_date") or "", r.get("list_price") or 0, r.get("mls") or "")
    seen, out = set(), []
    for r in sorted(rows, key=sort_key, reverse=True):
        k = relist_key(r)
        if k is not None:
            if k in seen:
                continue
            seen.add(k)
        out.append(r)
    return out


def dedupe_keep_order(rows) -> list:
    """Same survivors as dedupe_relistings, in the caller's original order
    (data.json keeps the order the cache gave it)."""
    keep = {id(r) for r in dedupe_relistings(rows)}
    return [r for r in rows if id(r) in keep]


def available_count(rows) -> int:
    """Just the 'N available' number (no timestamp): the drop-in for any code
    that used to count 'active' rows itself."""
    return sum(1 for r in dedupe_relistings(rows) if not is_pending(r.get("status")))


def nl_label(now: datetime | None = None) -> str:
    """'Oct 8, 2:05 pm NL' for `now` (naive = UTC), in Newfoundland time."""
    from zoneinfo import ZoneInfo
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    t = now.astimezone(ZoneInfo(NL_TZ_NAME))
    hour = t.hour % 12 or 12
    return f"{t:%b} {t.day}, {hour}:{t:%M} {'am' if t.hour < 12 else 'pm'} NL"


def listing_counts(rows, now: datetime | None = None) -> dict:
    kept = dedupe_relistings(rows)
    pend = sum(1 for r in kept if is_pending(r.get("status")))
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return {
        "available": len(kept) - pend,
        "pending": pend,
        "total": len(kept),
        "relistings_removed": len(rows) - len(kept),
        "updated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_label": nl_label(now),
    }


def fmt(n: int) -> str:
    return f"{int(n):,}"


def count_badge(n: int) -> str:
    """Body of a '<name>-count' DDF fragment (must end in a closing tag)."""
    return f'<span class="hx-count">{fmt(n)}</span>'


def summary_text(c: dict) -> str:
    """'1,586 available · 292 conditional/pending · Updated Oct 8, 2:05 pm NL'"""
    bits = [f'{fmt(c["available"])} available']
    if c["pending"]:
        bits.append(f'{fmt(c["pending"])} {PENDING_LABEL}')
    bits.append(f'Updated {c["updated_label"]}')
    return " &middot; ".join(bits)


def summary_span(c: dict) -> str:
    """Body of the 'listings-summary' DDF fragment (ends in a closing tag)."""
    return f'<span class="hx-summary">{summary_text(c)}</span>'


# The nightly snapshot card as it was written before this change (a baked number,
# labelled "Active"). The first hourly run after the change migrates it in place so
# no site waits for a nightly run to show the shared number.
_LEGACY_CARD_RE = re.compile(
    r'<div class="hp-snap-val">[\d,]+</div>(<div class="hp-snap-label">)Active MLS&reg; Listings')


def refresh_baked_counts(fragments_dir: Path, c: dict) -> int:
    """Patch <span data-lc="available|pending|updated">..</span> inside fragment
    files the nightly job wrote (e.g. home-market-snapshot.html), so the hourly
    injection never puts yesterday's number back. Returns files changed."""
    vals = {"available": fmt(c["available"]), "pending": fmt(c["pending"]), "updated": c["updated_label"]}
    changed = 0
    for f in Path(fragments_dir).glob("*.html"):
        t = f.read_text()
        new = _LEGACY_CARD_RE.sub(
            lambda m: f'<div class="hp-snap-val"><span data-lc="available">{vals["available"]}</span></div>'
                      f'{m.group(1)}Available MLS&reg; Listings', t)
        if "data-lc=" in new:
            new = re.sub(r'(<span data-lc="(available|pending|updated)">)[^<]*(</span>)',
                         lambda m: m.group(1) + vals[m.group(2)] + m.group(3), new)
        if new != t:
            f.write_text(new)
            changed += 1
    return changed


# ---- Every-run refresh (sites 2026-10-08) -------------------------------------
# The hourly workflows skip the full regen when the feed pull changed nothing
# (tools/check-changes-gate.py). The counts must still be re-derived on those runs,
# or a hand-seeded or stale number survives until the next data change (seen live
# 2026-10-08 after #892: the PR's seed line stayed up after the merge because the
# runs that followed skipped the regen). The generator's `--counts-only` mode
# computes the counts from its own filtered rows and calls refresh_count_outputs();
# the injector then puts them in the pages.
#
# "Updated" is the feed's own time, the same on every site: the projected cache's
# generated_at (stamped in the run that pulled the data), read by counts_as_of().
# Two runs over the same data write the same bytes, so a quiet run commits nothing.
# When a quiet run's numbers DO move (a firm deal, the 180-day stale gate), the
# generator stamps that run's time instead (the moment the numbers changed).

_FRAG_HEADER_RE = re.compile(r"\A<!--[^\n]*-->\n?")
_VIEWALL_RE = re.compile(r'(ddf-viewall-card-label">View all )[\d,]+')
_DATA_COUNTS_KEYS = ("available", "pending", "total", "relistings_removed", "updated_at", "updated_label")


def counts_as_of(cache: dict):
    """The projected cache's generated_at as an aware datetime, or None."""
    try:
        return datetime.fromisoformat(str(cache.get("generated_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        return None


def same_numbers(a, b) -> bool:
    """True when two counts dicts agree on available and pending."""
    try:
        return all(int(a[k]) == int(b[k]) for k in ("available", "pending"))
    except (TypeError, KeyError, ValueError):
        return False


def heartbeat(c: dict, regen: str) -> str:
    """The one log line every hourly run prints (always-on #8): what the site now says."""
    return (f'[counts] {fmt(c["available"])} available · {fmt(c["pending"])} pending · '
            f'updated {c["updated_label"]} (regen {regen})')


def _write_fragment(path: Path, name: str, body: str, note: str) -> bool:
    """Write a DDF fragment only when its BODY changes (the header comment carries
    nothing the pages use, so a header-only change must never make a commit)."""
    if path.exists() and _FRAG_HEADER_RE.sub("", path.read_text(), count=1) == body:
        return False
    path.write_text(f"<!-- ddf-fragment:{name} | {note} -->\n{body}")
    return True


def refresh_count_outputs(site_root, c: dict, badges: dict, viewall: dict | None = None,
                          note: str = "counts refresh (regen skipped)") -> list:
    """Re-derive every baked count from `c` without a regen. Writes a file only when
    its content changes; returns the site-relative paths it changed.

      tools/ddf-fragments/listings-summary.html   the summary line
      tools/ddf-fragments/<name>.html (badges)    {fragment: number} tab badges
      tools/ddf-fragments/<name>.html (viewall)   the "View all N" number in a card fragment
      tools/ddf-fragments/*.html data-lc spans    refresh_baked_counts (the nightly snapshot)
      listings/data.json "counts"                 the /listings/ header (rows untouched)
    """
    import json
    site_root = Path(site_root)
    frag = site_root / "tools" / "ddf-fragments"
    changed = []
    if _write_fragment(frag / "listings-summary.html", "listings-summary", summary_span(c), note):
        changed.append("tools/ddf-fragments/listings-summary.html")
    for name, n in sorted((badges or {}).items()):
        if _write_fragment(frag / f"{name}.html", name, count_badge(n), note):
            changed.append(f"tools/ddf-fragments/{name}.html")
    for name, n in sorted((viewall or {}).items()):
        p = frag / f"{name}.html"
        if p.exists():
            t = p.read_text()
            new = _VIEWALL_RE.sub(lambda m: m.group(1) + fmt(n), t)
            if new != t:
                p.write_text(new)
                changed.append(f"tools/ddf-fragments/{name}.html")
    before = {p: p.read_text() for p in frag.glob("*.html")}
    refresh_baked_counts(frag, c)
    for p, t in before.items():
        rel = f"tools/ddf-fragments/{p.name}"
        if p.read_text() != t and rel not in changed:
            changed.append(rel)
    data = site_root / "listings" / "data.json"
    if data.exists():
        payload = json.loads(data.read_text())
        want = {k: c[k] for k in _DATA_COUNTS_KEYS if k in c}
        if payload.get("counts") != want:
            if "counts" in payload:
                payload["counts"] = want
            else:  # the key order the generator writes: counts just before listings
                rows = payload.pop("listings", None)
                payload["counts"] = want
                if rows is not None:
                    payload["listings"] = rows
            data.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            changed.append("listings/data.json")
    return changed
