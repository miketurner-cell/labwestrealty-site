"""_fleet_genutils.py — shared pure leaf-helpers for the fleet site generators.

Tier-1 fleet-canonical (synced byte-identical to <site>/tools/_fleet_genutils.py by
tools/fleet-sync.py). Convergence Inc 1 (2026-06-22): these 20 helpers were byte-identical
across all 3 ddf-generate-pages.py copies; extracted here so the generators import them
instead of each carrying an inline copy. Pattern mirrors agent_roster_loader.py.

CRITICAL: the path helpers (_swept_cache_path / _maa_muni_code / _get_google_maps_key) use
Path(__file__) relative to THIS file. Because this module syncs to <site>/tools/ — the same
directory as the generator — __file__ resolves identically to the inline originals. Do not
move this module to a different directory depth without re-checking those three.

NEVER hand-edit per-site copies; edit fleet/canonical/tools/_fleet_genutils.py + fleet-sync.
"""
from __future__ import annotations
import os
import re
import sys
import json
import html
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime, timezone

# Module-level caches that move with their functions (were generator globals).
_GOOGLE_MAPS_KEY_CACHE = None
_MAA_MUNI_MAP = None

def _current_year() -> int:
    return datetime.now(timezone.utc).year

def _is_first_time_buyer(l: dict) -> bool:
    """Residential with list_price ≤ $300,000 — entry-level pool.

    We exclude Land/Commercial/Business/Multi-Family deliberately —
    first-time buyers are looking for a home to live in, not vacant lots
    or investment properties.
    """
    if l.get("property_type") != "Residential":
        return False
    p = l.get("list_price") or 0
    return 0 < p <= 300_000

def _is_commercial(l: dict) -> bool:
    """Commercial real estate bucket: Commercial, Business, Multi-Family."""
    return l.get("property_type") in {"Commercial", "Business", "Multi-Family"}

def fmt_int(n):
    if n is None:
        return "—"
    return f"{int(n):,}"

def fmt_bath(b):
    if b is None:
        return "—"
    return f"{b:.1f}".rstrip("0").rstrip(".") if b != int(b) else f"{int(b)}"

def fmt_sqft(n):
    if n is None:
        return "—"
    return f"{int(n):,} sq ft"

def fmt_lot(area, units):
    if area is None:
        return "—"
    if units and units.lower() in ("acres", "acre"):
        return f"{area:.2f} acres"
    return f"{int(area):,} sq ft"

def he(s) -> str:
    """HTML-escape, treating None as empty string."""
    return html.escape(str(s)) if s is not None else ""

def ja(obj) -> str:
    """JSON-encode for safe embedding in <script type=application/ld+json>."""
    # </script in a JSON string would close the tag; escape it.
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")

def ja_ascii(obj, **kwargs) -> str:
    """JSON-encode for safe embedding in <script type=application/ld+json>, keeping
    json.dumps' default ensure_ascii=True (unlike ja(), which sets ensure_ascii=False).
    Use at call sites that already rely on plain json.dumps(obj, ...) defaults --
    swapping those to ja() would flip every non-ASCII byte in the output and is not
    a like-for-like fix. Same </script escape guard as ja(); accepts any json.dumps
    kwarg (e.g. indent=2) so it's a drop-in replacement for a bare json.dumps call."""
    return json.dumps(obj, **kwargs).replace("</", "<\\/")

def build_facts_strip(listing: dict) -> str:
    facts = []
    if listing.get("bedrooms") is not None:
        facts.append(("Bedrooms", str(listing["bedrooms"])))
    if listing.get("bathrooms") is not None:
        facts.append(("Bathrooms", fmt_bath(listing["bathrooms"])))
    if listing.get("living_area"):
        facts.append(("Living Area", fmt_sqft(listing["living_area"])))
    if listing.get("lot_size"):
        facts.append(("Lot", fmt_lot(listing["lot_size"], listing.get("lot_size_units"))))
    if listing.get("year_built"):
        facts.append(("Year Built", str(listing["year_built"])))
    if listing.get("parking_total"):
        facts.append(("Parking", str(listing["parking_total"])))

    if not facts:
        return ""
    cells = "".join(
        f'<div class="lst-fact"><div class="lst-fact-num">{he(v)}</div>'
        f'<div class="lst-fact-label">{he(label)}</div></div>'
        for label, v in facts
    )
    return f'<div class="lst-facts">{cells}</div>'

def _get_google_maps_key():
    """Read GOOGLE_MAPS_API_KEY from env (workspace-root .env loaded by idx-ingest).

    Module-level cache so the lookup runs once per generator run. Returns
    empty string if env var unset, NOT None, so the caller can branch on
    truthiness uniformly. Convention #74 fail-safe: missing key → section
    omits, no broken pages.
    """
    global _GOOGLE_MAPS_KEY_CACHE
    if _GOOGLE_MAPS_KEY_CACHE is not None:
        return _GOOGLE_MAPS_KEY_CACHE
    # First-call: lazy-load workspace-root .env if not already in env
    if "GOOGLE_MAPS_API_KEY" not in os.environ:
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        if env_path.exists():
            try:
                with open(env_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, _, v = line.partition("=")
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except OSError:
                pass
    _GOOGLE_MAPS_KEY_CACHE = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    return _GOOGLE_MAPS_KEY_CACHE

def build_breadcrumb_jsonld(crumbs: list[tuple[str, str]]) -> str:
    """Schema.org BreadcrumbList — lets Google show breadcrumb trails in SERPs.
    `crumbs` is a list of (name, url) tuples in display order."""
    schema = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "name": name,
                "item": url,
            }
            for i, (name, url) in enumerate(crumbs)
        ],
    }
    return f'<script type="application/ld+json">{ja(schema)}</script>'

def _slugify_city(text: str) -> str:
    """Slim slugifier used only for sold-city → active-slug matching.
    Lowercase, strip punctuation, collapse spaces+hyphens.
    """
    import re as _re
    s = text.lower().strip()
    # Drop apostrophes entirely (St. John's → st-johns)
    s = s.replace("'", "").replace("’", "")
    # Replace non-alphanumeric with hyphen, collapse
    s = _re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s

def _days_on_market(listing: dict, now: "datetime | None" = None) -> int | None:
    """Return whole days since list_date in NEWFOUNDLAND calendar days, or None
    if list_date is missing/unparseable.

    Both ends are America/St_Johns days (sites 2026-10-09, D-1008-22): the old
    code took UTC "now" minus the date part of list_date; pages are not rebuilt
    01:00-10:00 UTC, so a home listed yesterday read "Listed today" until the
    NL-morning rebuild. `now` is injectable for tests (naive = UTC).
    list_date goes through nl_dates.nl_date(), which tolerates any fractional-
    second precision and converts offset timestamps to the NL day."""
    from nl_dates import nl_date, NL_TZ
    ld = nl_date(listing.get("list_date"))
    if not ld:
        return None
    try:
        listed = datetime.strptime(ld, "%Y-%m-%d").date()
    except Exception:
        return None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max((now.astimezone(NL_TZ).date() - listed).days, 0)

def _list_date_label(listing: dict, now: "datetime | None" = None) -> str:
    """"Oct 7" (or "Oct 7, 2025" when not the current NL year) for list_date, or "".
    A calendar date, not "today": the pages are static between rebuilds, so a
    relative word goes stale at NL midnight while a date never does."""
    from nl_dates import nl_date, NL_TZ
    ld = nl_date(listing.get("list_date"))
    if not ld:
        return ""
    d = datetime.strptime(ld, "%Y-%m-%d").date()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    label = f"{d:%b} {d.day}"
    return label if d.year == now.astimezone(NL_TZ).year else f"{label}, {d.year}"

def _swept_cache_path() -> Path:
    return Path(__file__).parent / "ddf-cache" / "swept-listings.json"

def _save_swept_cache(data: dict) -> None:
    p = _swept_cache_path()
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

def _git_sha(site_root: Path) -> str | None:
    """Best-effort: short git SHA of the site root, or None if unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=site_root, capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except Exception:
        pass
    return None

def _hash_listings_dir(listings_dir: Path) -> str:
    """SHA-256 of the concatenated bytes of every generated HTML file, sorted
    by relative path. Lets the manifest fingerprint exact output content so
    we can tell whether a "regen" actually changed anything."""
    h = hashlib.sha256()
    for p in sorted(listings_dir.rglob("*.html")):
        h.update(str(p.relative_to(listings_dir)).encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()[:16]

def _viewpoint_clean(v) -> str:
    v = str(v if v is not None else "").strip()
    return v if v and v not in ("0", "0.0", "0.00") else ""

def _maa_muni_code(city: str):
    """MAA municipality code for a town (for the public assessed-value lookup).
    Loads idx-cache/maa-municipalities.json once. Convention #74: returns None
    if unknown → the enrichment JS just skips MAA for that page."""
    global _MAA_MUNI_MAP
    if _MAA_MUNI_MAP is None:
        _MAA_MUNI_MAP = {}
        try:
            p = Path(__file__).resolve().parent / "idx-cache" / "maa-municipalities.json"
            raw = json.loads(p.read_text())
            entries = raw if isinstance(raw, list) else raw.get("municipalities", [])
            for m in entries:
                nm = str(m.get("name", "")).strip().upper()
                if nm:
                    _MAA_MUNI_MAP[nm] = str(m.get("id", "")).strip()
        except Exception:
            _MAA_MUNI_MAP = {}
    return _MAA_MUNI_MAP.get((city or "").strip().upper())


# ---- Inc 2 (2026-06-22): new-listing / tour-embed / analytics / brokerage helpers ----
TURNER_BROKERAGE_FRAGMENT = "turner"   # case-insensitive substring → "ours"


CREA_ANALYTICS_URL = "https://analytics.crea.ca/LogEvents.svc/LogEvents"


def is_turner(brokerage: str | None) -> bool:
    return bool(brokerage and TURNER_BROKERAGE_FRAGMENT in brokerage.lower())


TOUR_JUNK_HOSTS = {
    "docs.google.com",
    "drive.google.com",
    "mail.google.com",
    "outlook.office.com",
    "outlook.live.com",
}


_YT_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/|v/))([A-Za-z0-9_-]{11})",
    re.IGNORECASE,
)


_MP_RE = re.compile(r"matterport\.com/show/?\?m=([A-Za-z0-9]+)", re.IGNORECASE)


_IGUIDE_RE = re.compile(r"\b(youriguide\.com|iguide\.tours)/", re.IGNORECASE)


_HOST_RE = re.compile(r"https?://([^/]+)", re.IGNORECASE)


def _split_tour_urls(raw) -> list[str]:
    """Normalize the tour field into a clean list of URLs.

    Accepts either a list[str] (new schema) or a str (legacy single URL,
    possibly comma-joined by the listing agent). Strips junk hosts.
    """
    if not raw:
        return []
    if isinstance(raw, list):
        items = [str(x) for x in raw]
    else:
        # Legacy single-string field — agents sometimes joined multiple with ", "
        items = re.split(r"[,\s]+", str(raw))
    cleaned = []
    seen = set()
    for x in items:
        x = (x or "").strip().rstrip(".,;")
        if not x or not x.lower().startswith(("http://", "https://")):
            continue
        host_m = _HOST_RE.match(x)
        host = host_m.group(1).lower() if host_m else ""
        if host in TOUR_JUNK_HOSTS:
            continue
        if x in seen:
            continue
        seen.add(x)
        cleaned.append(x)
    return cleaned


def _render_tour_embed(url: str) -> str:
    """Produce an iframe or fallback-button HTML string for one tour URL."""
    yt = _YT_RE.search(url)
    if yt:
        vid = yt.group(1)
        return (
            '<div class="lst-tour-embed lst-tour-yt">'
            f'<iframe src="https://www.youtube.com/embed/{vid}?rel=0" '
            'title="Property video tour" loading="lazy" '
            'allow="accelerometer; autoplay; clipboard-write; encrypted-media; '
            'gyroscope; picture-in-picture; web-share" '
            'allowfullscreen></iframe>'
            '</div>'
        )
    mp = _MP_RE.search(url)
    if mp:
        key = mp.group(1)
        return (
            '<div class="lst-tour-embed lst-tour-3d">'
            f'<iframe src="https://my.matterport.com/show/?m={he(key)}&amp;play=1" '
            'title="3D property tour" loading="lazy" '
            'allow="xr-spatial-tracking; fullscreen" allowfullscreen></iframe>'
            '</div>'
        )
    if _IGUIDE_RE.search(url):
        return (
            '<div class="lst-tour-embed lst-tour-3d">'
            f'<iframe src="{he(url)}" '
            'title="iGuide 3D property tour" loading="lazy" '
            'allow="fullscreen; vr" allowfullscreen></iframe>'
            '</div>'
        )
    # Unrecognized provider — surface as an outbound button so the tour isn't hidden
    return (
        '<p class="lst-tour-fallback">'
        f'<a class="lst-cta lst-cta-secondary" href="{he(url)}" '
        'target="_blank" rel="noopener">View virtual tour &#8599;</a>'
        '</p>'
    )


_YT_UPLOAD_DATES: dict | None = None
_YT_UPLOAD_DATES_PATH = Path(__file__).resolve().parent / "idx-cache" / "youtube-upload-dates.json"


def _youtube_upload_dates() -> dict:
    """{video_id: uploadDate} from idx-cache/youtube-upload-dates.json, read once.

    Written by tools/youtube-upload-dates.py from the YouTube Data API
    (snippet.publishedAt, the real upload time). Missing or unreadable file ->
    {} and the VideoObject omits uploadDate, as it did before (Convention #74).
    """
    global _YT_UPLOAD_DATES
    if _YT_UPLOAD_DATES is None:
        _YT_UPLOAD_DATES = {}
        try:
            vids = json.loads(_YT_UPLOAD_DATES_PATH.read_text(encoding="utf-8")).get("videos") or {}
            _YT_UPLOAD_DATES = {str(k): str(v) for k, v in vids.items() if v}
        except (OSError, ValueError, AttributeError):
            pass
    return _YT_UPLOAD_DATES


def _youtube_tour_video_jsonld(url: str, address: str) -> str:
    """schema.org VideoObject JSON-LD for a YouTube tour URL, or "" if `url`
    isn't a recognized YouTube video.

    Search Console flagged listings fleet-wide 2026-09-14 ("New reasons
    prevent your videos from being indexed ... No thumbnail URL provided")
    -- the tour <iframe> from _render_tour_embed() carried no VideoObject
    markup at all, so Google had no thumbnail to index the video against.
    thumbnailUrl is YouTube's own deterministic per-video hqdefault.jpg
    (present for every public video, unlike the sometimes-missing
    maxresdefault), not a fabricated value. name/description are built from
    the real listing address, the only fact we actually have about an
    agent-pasted tour link -- uploadDate is never guessed (Convention #197).

    uploadDate (2026-10-07): Search Console flagged "Missing field uploadDate"
    (a critical Videos error) on realestategander.com. The value now comes
    only from idx-cache/youtube-upload-dates.json, which
    tools/youtube-upload-dates.py fills from the YouTube Data API's own
    snippet.publishedAt. A video not in that file still gets the block
    without uploadDate, exactly as before, so a site without the file (or
    without YouTube credentials) is unchanged.
    """
    yt = _YT_RE.search(url)
    if not yt:
        return ""
    vid = yt.group(1)
    name = f"{address} — Property video tour"
    data = {
        "@context": "https://schema.org",
        "@type": "VideoObject",
        "name": name,
        "description": name,
        "thumbnailUrl": [f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"],
        "embedUrl": f"https://www.youtube.com/embed/{vid}",
        "contentUrl": url,
    }
    upload = _youtube_upload_dates().get(vid)
    if upload:
        data["uploadDate"] = upload
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'


def build_analytics_beacon(listing: dict) -> str:
    """Fire CREA Analytics LogEvents POST on page load — required for compliance reporting."""
    payload = {
        "DestinationId": "27222",   # MUST match the registered feed destination id
        "ListingId": listing["mls"],
        "EventType": "Display",
    }
    return f"""
<script>
(function() {{
  try {{
    fetch({json.dumps(CREA_ANALYTICS_URL)}, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: {json.dumps(json.dumps(payload))},
      keepalive: true
    }}).catch(function(){{ /* silent */ }});
  }} catch (e) {{ /* silent */ }}
}})();
</script>"""


NEW_LISTING_DAYS = 7


def _is_new(listing: dict) -> bool:
    """Return True if listing was created in the last NEW_LISTING_DAYS days."""
    dom = _days_on_market(listing)
    return dom is not None and dom <= NEW_LISTING_DAYS


# ── Cross-region band data (Slice 3 step 5, 2026-09-09) ──────────────────
# Shared by build-homepage.py's band_network() and build-region-hub.py's
# cross-region card twin (×3 independently-diverged site copies) so both
# surfaces read the SAME gating logic instead of drifting into two
# almost-but-not-quite-identical implementations. Path helpers use
# Path(__file__) relative to THIS file, same convention as the rest of the
# module -- correct because this file always syncs to the generator's own
# tools/ directory.

def load_regions_registry():
    """The fleet-canonical region registry (tools/regions.json). Fail-safe
    (Convention #74/#202): a missing or unparsable file returns None so
    callers emit nothing rather than a half band."""
    path = Path(__file__).resolve().parent / "regions.json"
    if not path.exists():
        print(f"[cross-region] WARN: {path.name} missing -- cross-region band skipped", file=sys.stderr)
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))["regions"]
    except Exception as ex:
        print(f"[cross-region] WARN: {path.name} unreadable ({ex}) -- cross-region band skipped", file=sys.stderr)
        return None


def current_site_key():
    """This site's own site_key, read from tools/_fleet_config.json (the
    same file emit-regions-js.py reads) -- never guessed from the repo
    folder name."""
    path = Path(__file__).resolve().parent / "_fleet_config.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("site_key")
    except Exception:
        return None


def cross_region_data():
    """(me, turner_others, peers, recruiting) for the cross-region band, or
    None if the registry or this site's own identity can't be resolved.
    Gates on site_id (the real "one of our 3 live Turner sites" signal --
    domain alone also matches peer regions, the Slice 2 lesson banked in
    the [[nl-network-portal]] memory) and site_key (never territory --
    Labrador West's territory/site_key differ, same reason nav.js's
    regionBySiteKey() exists instead of a direct dict lookup)."""
    regions = load_regions_registry()
    my_key = current_site_key()
    if not regions or not my_key:
        return None
    me = next((r for r in regions.values() if r.get("site_key") == my_key), None)
    if not me:
        print(f"[cross-region] WARN: cross-region band skipped ({my_key!r} not found in the registry)", file=sys.stderr)
        return None
    turner_others = [r for r in regions.values()
                     if r.get("operator") == "turner" and r.get("state") == "live"
                     and r.get("site_id") and r.get("site_key") != my_key]
    peers = [r for r in regions.values() if r.get("operator") == "peer"]
    recruiting = [r for r in regions.values() if r.get("state") == "recruiting"]
    return me, turner_others, peers, recruiting
