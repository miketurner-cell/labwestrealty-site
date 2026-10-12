#!/usr/bin/env python3
"""
IDX → DDF shape projection adapter — Lab West site (labwestrealty.com).

Port of goosebayrealestate-site/tools/idx-project-to-ddf-shape.py (closest twin) with the
Lab West config block only (sites, D-1012-34, component 2):
  - scope = Lab West: Subdistrict "Labrador City / Wabush", or postal A2V (Labrador City)
    or A0R (Wabush) with a Labrador City / Wabush town name. A0R also covers coastal
    Labrador, so A0R alone is not enough.
  - lease rows (TransactionType LEASE) are dropped at projection, so they never reach a
    page or a count (same intent as Goose Bay's is_lease; plan correction 2026-10-12).
  - scope = "labwest" in payload metadata; photos under the R2 prefix labwest/.

Reads tools/idx-cache/listings.json (raw IDX rows from idx-ingest.py)
and emits tools/idx-cache/listings-projected.json in DDF-compatible
envelope and row shape so ddf-generate-pages.py can consume the IDX
feed without code changes.

The DDF ingester (ddf-ingest.py) does heavy field projection at ingest:
city_slug, slug, url_path, photos[], normalized bedrooms/bathrooms/sqft,
longitude sign-flip, etc. The IDX ingester (idx-ingest.py) does only an
allowlist projection — keeps raw Matrix field names. This adapter bridges
the gap.

Geographic scope: Labrador City + Wabush only (about 34 active rows in the NLAR feed on
2026-10-12, one of them a lease). Every other Labrador row is out of scope.

Output envelope matches ddf-ingest's payload shape:
    {
        "generated_at": ISO8601 timestamp,
        "source": "idx-projected",
        "scope": "labwest",
        "count": N,
        "listings": [Listing-as-dict, ...]
    }
"""

from __future__ import annotations
import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

_OH_CACHE = None


def _oh_by_mui() -> dict:
    """Lazy-load tools/idx-cache/open-houses.json once per process
    (Batch F1, 2026-08-19 -- Convention #15 propagation from Gander).
    Convention #74 fail-safe: missing/malformed cache -> empty dict,
    never blocks projection. Shape written by idx-openhouse-sync.py:
    {"by_mui": {<Listing_MUI>: [{date, start_time, end_time, type}, ...]}}.
    """
    global _OH_CACHE
    if _OH_CACHE is None:
        try:
            p = Path(__file__).resolve().parent / "idx-cache" / "open-houses.json"
            _OH_CACHE = json.loads(p.read_text()).get("by_mui", {})
        except Exception:
            _OH_CACHE = {}
    return _OH_CACHE

# ═══════════════════════════════════════════════════════════════════
#  PER-SITE CONFIG — LAB WEST (Labrador City + Wabush)
# ═══════════════════════════════════════════════════════════════════
# The feed is not city-filtered at pull time; every site pulls the whole board and
# filters here. In the feed, City is empty on Labrador rows: only CityText, Subdistrict
# and PostalCode identify the town. A2V = Labrador City, A0R = Wabush (A0R also covers
# coastal Labrador, so it only counts together with a Lab West town name).
POSTAL_PREFIXES = ("A2V", "A0R")
SCOPE_SUBDISTRICT = "labrador city / wabush"
SCOPE_SLUG = "labwest"
R2_PREFIX = "labwest"
SITE_DEFAULT_COUNTRY = "CA"
SITE_DEFAULT_PROVINCE = "NL"

# ═══════════════════════════════════════════════════════════════════
#  CITY NORMALIZATION (ported from ddf-ingest.py:CITY_CANONICAL)
# ═══════════════════════════════════════════════════════════════════
# goosebay-site/tools/ddf-ingest.py was removed when CREA DDF was retired
# (2026-10-01), so this map is the only copy; edit it here.
CITY_CANONICAL = {
    "labrador city":  "labrador-city",
    "lab city":       "labrador-city",
    "labrador city / wabush": "labrador-city",
    "wabush":         "wabush",
}
LABRADOR_FALLBACK = "labrador"

PROVINCE_NAME_TO_CODE = {
    "newfoundland & labrador": "NL", "newfoundland and labrador": "NL",
    "nova scotia": "NS", "new brunswick": "NB",
    "prince edward island": "PE", "quebec": "QC", "ontario": "ON",
    "manitoba": "MB", "saskatchewan": "SK", "alberta": "AB",
    "british columbia": "BC", "yukon": "YT",
    "northwest territories": "NT", "nunavut": "NU",
}

# ═══════════════════════════════════════════════════════════════════
#  HELPERS (ported byte-equivalent from ddf-ingest.py)
# ═══════════════════════════════════════════════════════════════════

def slugify(text: str, max_len: int = 80) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_len].rstrip("-")


def _clean_city_string(raw: str) -> str:
    s = raw.strip().lower()
    s = re.sub(r"\(\s*[^)]+\s*\)", "", s)
    s = re.sub(r",\s*(nl|newfoundland.*?|canada)\s*$", "", s)
    s = re.sub(r"\s+(area|district)\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── Canonical municipality merge (fleet-shared nl-city-canonical.json) ──
# Collapses spelling/punctuation variants of the SAME municipality to one
# canonical form BEFORE the per-site CITY_CANONICAL / slugify, so active-listing
# town pages + counts stop fragmenting (e.g. the 11 "St. John's" spellings → one
# slug). Same map the sold side already uses. Convention #74 fail-safe: a
# missing/corrupt map → empty dict → normalize_city falls through unchanged.
_CANON_MAP_PATH = Path(__file__).resolve().parent / "idx-cache" / "nl-city-canonical.json"


def _load_variant_to_canonical():
    try:
        data = json.loads(_CANON_MAP_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for canon, variants in (data.get("canonical") or {}).items():
        for v in variants:
            out[_clean_city_string(v)] = canon
    return out


VARIANT_TO_CANONICAL = _load_variant_to_canonical()


def normalize_city(raw_city, postal):
    if raw_city:
        key = _clean_city_string(raw_city)
        # Canonical-variant merge (fleet map) — collapse spelling variants
        # of the same municipality before per-site CITY_CANONICAL / slugify.
        canon = VARIANT_TO_CANONICAL.get(key)
        if canon:
            key = _clean_city_string(canon)
        if key in CITY_CANONICAL:
            return CITY_CANONICAL[key]
        if key in ("newfoundland", "newfoundland & labrador",
                   "newfoundland and labrador", "nl"):
            return LABRADOR_FALLBACK
        # Strip apostrophes from the city key so possessive town names slug
        # cleanly ("Spaniard's Bay" -> spaniards-bay) and match their
        # no-apostrophe spelling variants. City slug only — address/url_path
        # slugify is untouched.
        return slugify(key.replace("'", "").replace("`", "").replace("\u2019", ""))
    if postal:
        prefix = postal.strip().upper().replace(" ", "")[:3]
        if prefix == "A2V":
            return "labrador-city"
    return LABRADOR_FALLBACK


def derive_property_type(ptype_raw, subtype):
    """Derive the display property type from NLAR's PropertyType class
    (Residential / Lots / Commercial / Farm — the authoritative field)
    plus PropertySubType keywords. PropertySubType alone is NOT enough:
    NLAR leaves it EMPTY on Commercial and Lots rows, which left every
    commercial + land listing untyped (bug found 2026-06-10 — the
    /listings/commercial/ rollup showed only Multi-Family, and the Land +
    Commercial filter checkboxes on /listings/ matched nothing)."""
    s = f"{ptype_raw or ''} {subtype or ''}".strip().lower()
    if not s:
        return ""
    if "land" in s or "lot" in s or "acreage" in s:
        return "Land"
    if "commercial" in s or "industrial" in s or "office" in s or "retail" in s:
        return "Commercial"
    if "business" in s:
        return "Business"
    if "farm" in s or "agricultural" in s:
        return "Farm"
    if "multi" in s or "duplex" in s or "triplex" in s or "fourplex" in s:
        return "Multi-Family"
    return "Residential"


def normalize_province(raw):
    if not raw:
        return SITE_DEFAULT_PROVINCE
    key = raw.strip().lower()
    return PROVINCE_NAME_TO_CODE.get(key, raw.strip()[:2].upper())


def normalize_country(raw):
    if not raw:
        return SITE_DEFAULT_COUNTRY
    return "CA" if raw.strip().lower() in ("canada", "ca") else raw.strip()[:2].upper()


def _as_float(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _as_int(v):
    try:
        f = float(v) if v not in (None, "") else None
        return int(f) if f is not None else None
    except (TypeError, ValueError):
        return None


# Expand abbreviated street suffixes per Canada Post + REALTOR.ca convention.
_SUFFIX_EXPANSIONS = {
    "st": "Street", "rd": "Road", "ave": "Avenue", "av": "Avenue",
    "blvd": "Boulevard", "dr": "Drive", "ln": "Lane", "ct": "Court",
    "cres": "Crescent", "cir": "Circle", "pl": "Place", "pkwy": "Parkway",
    "hwy": "Highway", "tr": "Trail", "ter": "Terrace", "sq": "Square",
    "hbr": "Harbour", "hgts": "Heights", "mt": "Mount", "pt": "Point",
    "rte": "Route",
}


def _expand_suffix(suffix):
    """Map abbreviated street suffix to full word (case-aware)."""
    if not suffix:
        return suffix
    key = suffix.strip().lower().rstrip(".")
    return _SUFFIX_EXPANSIONS.get(key, suffix.strip())


def build_street_address(row):
    """Assemble street from IDX components. Parts first, AddressLine fallback.

    Per 2026-05-19 hotfix: IDX `AddressLine` is often in abbreviated canonical
    form missing the street number and using abbreviated suffix. Discrete parts
    (StreetNumber + StreetName + StreetSuffix) carry the full proper form.
    """
    num = (row.get("StreetNumber") or "").strip()
    name = (row.get("StreetName") or "").strip()
    suffix_raw = (row.get("StreetSuffix") or "").strip()
    suffix = _expand_suffix(suffix_raw)

    if name:
        # Dedupe a doubled street-type word: when StreetName already ends with
        # the suffix word (e.g. "Bay Bulls Road" + suffix "Road" =>
        # "Bay Bulls Road Road"), drop the suffix. Compare through the expansion
        # map so abbreviated forms ("Rd") dedupe against the full word too.
        name_words = name.split()
        if name_words and suffix and (
            _expand_suffix(name_words[-1]).strip().lower().rstrip(".")
            == suffix.strip().lower().rstrip(".")
        ):
            suffix = ""
        parts = [p for p in (num, name, suffix) if p]
        joined = " ".join(parts)
        if joined.strip():
            return joined

    al = (row.get("AddressLine") or "").strip()
    if al:
        return al.split(",")[0].strip() if "," in al else al

    return None


# ═══════════════════════════════════════════════════════════════════
#  CORE PROJECTION
# ═══════════════════════════════════════════════════════════════════

def in_scope(row):
    """Lab West scope: the Lab West subdistrict, or A2V, or A0R with a Lab West town."""
    sub = (row.get("Subdistrict") or "").strip().lower()
    if sub == SCOPE_SUBDISTRICT:
        return True
    city = _clean_city_string((row.get("CityText") or row.get("City") or ""))
    postal = (row.get("PostalCode") or "").strip().upper().replace(" ", "")
    if len(postal) < 3:
        return city in CITY_CANONICAL
    prefix = postal[:3]
    if prefix == "A2V":
        return True
    if prefix == "A0R":
        return city in CITY_CANONICAL
    return False


def is_lease_row(row):
    """True for a lease row. The feed's TransactionType is the authority (SALE / LEASE)."""
    return (row.get("TransactionType") or "").strip().upper() == "LEASE"


STALE_ACTIVE_THRESHOLD_DAYS = 180  # mirror of the generator gate (Conv #117 / #21 rail 3)


def _is_stale_active(row):
    """Drop ACTIVE rows unmodified in NLAR for >180d at PROJECTION time so the
    card grid (which reads listings-projected.json directly on this site)
    matches the page set the generator emits (same gate at regen). Without
    this, stale actives render cards linking to never-emitted pages — GSC
    404s + consumer dead links (Woodgrove Acres trio, found 2026-06-12).
    Fail-open on missing/unparseable timestamp (Conv #74)."""
    ts = row.get("MatrixModifiedDT") or row.get("ModificationTimestamp") or ""
    try:
        import datetime as _dt
        import re as _re
        t = _re.sub(r"\.(\d{1,6})\d*$", lambda m: "." + m.group(1).ljust(6, "0"), str(ts).rstrip("Z"))
        mod = _dt.datetime.fromisoformat(t)
        return (_dt.datetime.utcnow() - mod).days > STALE_ACTIVE_THRESHOLD_DAYS
    except Exception:
        return False


def project_row(row, site_root):
    """Map a raw IDX row to DDF-compatible Listing-shape dict."""
    mls = str(row.get("MLSNumber") or row.get("Matrix_Unique_ID") or "")
    city_raw = (row.get("CityText") or row.get("City") or "").strip() or None
    postal = (row.get("PostalCode") or "").strip() or None
    city_slug = normalize_city(city_raw, postal)
    street = build_street_address(row)

    # Slug + URL path (mirrors ddf-ingest.py)
    addr_slug = slugify(street or "") or "property"
    listing_slug = f"{addr_slug}-{mls}".strip("-")
    url_path = f"/listings/{city_slug}/{listing_slug}.html"

    # Photos — synthesize from local file existence (idx-photo-sync.py
    # populates these via RETS GetObject).
    #
    # R2 mode (Convention #15 port from Avalon, 2026-06-11 — Goosebay was
    # MISSING this branch since its 2026-05-27 R2 cutover, so every listing
    # added after the cutover projected photos=[] and rendered No-Photo):
    # when R2_BASE_URL is set, photos live in R2 not on local disk. Read
    # .meta.json for photo_count (fall back to the feed's authoritative
    # PhotoCount) + emit absolute R2 URLs. Convention #74 fail-safe — if
    # R2_BASE_URL unset, falls through to the disk-stat path.
    photos = []
    if mls:
        r2_base = os.environ.get("R2_BASE_URL", "").strip().rstrip("/")
        local_dir = Path(site_root) / "images" / "listings" / mls
        meta_path = local_dir / ".meta.json"

        if r2_base:
            photo_count = 0
            if meta_path.exists():
                try:
                    meta_data = json.loads(meta_path.read_text())
                    photo_count = int(meta_data.get("photo_count") or 0)
                except (json.JSONDecodeError, OSError, ValueError, TypeError):
                    photo_count = 0
            if photo_count == 0:
                try:
                    photo_count = int(row.get("PhotoCount") or 0)
                except (TypeError, ValueError):
                    photo_count = 0
            for n in range(1, photo_count + 1):
                photos.append({
                    "url": f"{r2_base}/{R2_PREFIX}/listings/{mls}/{n:03d}.jpg",
                    "caption": None,
                    "order": n,
                })
        elif local_dir.exists():
            for img in sorted(local_dir.glob("*.jpg")):
                fname = img.name
                if fname == "hero.jpg":
                    continue
                try:
                    order = int(fname.split(".")[0])
                except ValueError:
                    order = 999
                photos.append({
                    "url": f"/images/listings/{mls}/{fname}",
                    "caption": None,
                    "order": order,
                })

    # Virtual tours — IDX has both VirtualTourURL + VirtualTourURL2Unbranded
    virtual_tours = []
    for k in ("VirtualTourURL", "VirtualTourURL2Unbranded"):
        v = (row.get(k) or "").strip()
        if v and v not in virtual_tours:
            virtual_tours.append(v)
    virtual_tour = virtual_tours[0] if virtual_tours else None

    status_raw = (row.get("Status") or "").strip()
    status = status_raw or "Active"

    currency = "CAD"

    # Open house chip (Batch F1, 2026-08-19). Listing_MUI (not
    # MLSNumber) is the join key -- same field the rooms merge in
    # ddf-generate-pages.py already uses. Soonest event with
    # date >= today defends a stale cache from showing a past open
    # house (idx-openhouse-sync.py's own cache is a superset; the
    # consumer decides what's still relevant at read time).
    mui = str(row.get("Matrix_Unique_ID") or "").strip()
    open_house_next = None
    oh_events = _oh_by_mui().get(mui) or []
    if oh_events:
        today = datetime.now(timezone.utc).date().isoformat()
        upcoming = [e for e in oh_events if e.get("date", "") >= today]
        if upcoming:
            open_house_next = sorted(
                upcoming, key=lambda e: (e["date"], e.get("start_time", ""))
            )[0]

    return {
        "mls": mls,
        "status": status,
        "property_type": derive_property_type(row.get("PropertyType"), row.get("PropertySubType")),
        "property_subtype": (row.get("PropertySubType") or "").strip(),
        "list_price": _as_float(row.get("ListPrice")),
        "currency": currency,
        "street": street,
        "unit": (row.get("UnitNumber") or "").strip() or None,
        "city_raw": city_raw,
        "city_slug": city_slug,
        "province": normalize_province(row.get("StateOrProvince")),
        "postal_code": postal,
        "country": SITE_DEFAULT_COUNTRY,
        "latitude": _as_float(row.get("Latitude")),
        "longitude": _as_float(row.get("Longitude")),
        "bedrooms": _as_int(row.get("BedsTotal")),
        "bathrooms": _as_float(row.get("BathsTotal")),
        "half_baths": _as_int(row.get("BathsHalf")),
        "living_area": _as_float(row.get("TotalLivingAreaSqFt")),
        "lot_size": _as_float(row.get("Lotsize")),
        # Commercial data-richness (2026-06-10): both fields verified 100%
        # populated on commercial rows. PropertySize is a banded display
        # string ("4,501-7,250 sq ft", "0.5-0.99 Acres"); Zoning is the
        # municipal code/label ("Comm.", "CR", "COMM HWY").
        "zoning": (row.get("Zoning") or "").strip(),
        "property_size": (row.get("PropertySize") or "").strip(),
        "lot_size_units": None,
        "year_built": _as_int(row.get("YearBuilt")),
        "parking_total": None,
        "public_remarks": (row.get("PublicRemarks") or "").strip() or None,
        "private_remarks": None,
        "photos": photos,
        "virtual_tour": virtual_tour,
        "virtual_tours": virtual_tours,
        "listing_brokerage": (row.get("ListOfficeName") or "").strip() or None,
        # "Ours" = listed by Royal LePage Turner Realty, same rule as Avalon's projector (2026-10-10: the key
        # was never set here, so every Labrador Turner listing published to listings/data.json as ours=false).
        "ours": ("turner" in (row.get("ListOfficeName") or "").lower()),
        "listing_agent_key": None,
        "list_date": (row.get("ListingContractDate") or row.get("OriginalEntryTimestamp") or "").strip() or None,
        "modification_timestamp": (row.get("MatrixModifiedDT") or "").strip() or None,
        # Price-Change Timeline (Strategic Vision Rec #1, ported from Gander).
        # build_price_history_section + .lst-price-history CSS already exist on
        # Goosebay's generator. Section was returning empty because these idx_
        # fields weren't projected from the raw IDX cache. Added 2026-05-21
        # alongside Avalon's matching projection fix (commit 63771c3b8).
        # Convention #74 fail-safe in the render function still applies:
        # no-change listings emit nothing.
        "idx_original_list_price": _as_float(row.get("OriginalListPrice")),
        "idx_last_list_price": _as_float(row.get("LastListPrice")),
        "idx_price_change_timestamp": (row.get("PriceChangeTimestamp") or "").strip() or None,
        # Agent attribution card (Convention #15 from Gander). On Lab West every listing page names
        # Mike Turner, Broker (D-1012-28); the generator does that, this is only the raw field.
        "idx_list_agent_full_name": (row.get("ListAgentFullName") or "").strip() or None,
        # ─── Listings discovery shell port (2026-05-26 — Convention #15 byte-symmetric
        # from Avalon canonical e0b380634 + 2026-05-24 New Construction work) ───
        # 8-chip set on /listings/ (Just listed, Price drop, New construction,
        # Pre-construction, Virtual tour, Waterfront, Ocean view, Acreage) +
        # rollup-aware chip nav + lifecycle filtering all read these fields.
        # Convention #74 fail-safe: empty string → None; chips gracefully filter
        # to 0 matches if NLAR coverage is light. NLAR Matrix coverage on HVGB
        # listings varies (agents fill in to different degrees).
        "idx_year_built_desc": (row.get("YearBuiltDesc") or "").strip() or None,
        "idx_new_construction_only": (row.get("NewConstructionOnly") or "").strip() or None,
        "idx_original_list_price": _as_float(row.get("OriginalListPrice")),
        "idx_last_list_price": _as_float(row.get("LastListPrice")),
        "idx_price_change_timestamp": (row.get("PriceChangeTimestamp") or "").strip() or None,
        # ─── Track A.2 enrichment fields (Convention #15 propagation 2026-05-26) ───
        # Property Details + Schools sections on listing-detail pages auto-populate
        # when these are present. Mirror of stjohns-site/tools/idx-project-to-ddf-shape.py
        # canonical (shipped today 2026-05-25 as part of task #92 closure).
        "idx_heating": (row.get("HeatingCooling") or "").strip() or None,
        "idx_foundation": (row.get("Foundation") or "").strip() or None,
        "idx_garage_type": (row.get("GarageType") or "").strip() or None,
        "idx_garage_sqft": _as_float(row.get("GarageAreaSqFt")),
        "idx_elementary_school": (row.get("Elementaryschool") or "").strip() or None,
        "idx_secondary_school": (row.get("Secondaryschool") or "").strip() or None,
        "slug": listing_slug,
        "url_path": url_path,
        "open_house_next": open_house_next,
    }


def main():
    ap = argparse.ArgumentParser(description="Project IDX cache → DDF shape (Lab West)")
    ap.add_argument("--in",  dest="in_path",  default=None,
                    help="Input IDX cache (default: <script-dir>/idx-cache/listings.json)")
    ap.add_argument("--out", dest="out_path", default=None,
                    help="Output projected cache (default: <script-dir>/idx-cache/listings-projected.json)")
    ap.add_argument("--site-root", default=None,
                    help="Site root for photo path resolution (default: parent of <script-dir>)")
    ap.add_argument("--no-scope-filter", action="store_true",
                    help="Skip postal-prefix scope filter (for debug)")
    args = ap.parse_args()

    script_dir = Path(__file__).resolve().parent
    site_root = Path(args.site_root).resolve() if args.site_root else script_dir.parent
    in_path = Path(args.in_path).resolve() if args.in_path else script_dir / "idx-cache" / "listings.json"
    out_path = Path(args.out_path).resolve() if args.out_path else script_dir / "idx-cache" / "listings-projected.json"

    if not in_path.exists():
        # Convention #74 fail-safe extension: NLAR-transient absorber.
        # When idx-ingest.py fails (e.g. "20210 Too many outstanding queries"
        # rate-limit, NLAR maintenance window, auth blip), the raw listings.json
        # doesn't get written. Without this fallback, EVERY downstream step
        # cascades to failure: photo-sync bails, projection bails, generator
        # bails ("cache file not found"), workflow conclusion = failure,
        # consumer site falls out of date. With this fallback: if a prior
        # projected cache exists on disk (from Actions cache OR git checkout),
        # exit 0 cleanly so the generator runs against it. Convention #85
        # stale-cache gate in ddf-generate-pages.py is the safety floor —
        # refuses if projected cache is >24h older than deploy-manifest.
        # Worst case: site renders against ~1-3h stale data instead of full
        # deploy halt. Banked 2026-05-23 night after Gander hourly twice
        # failed on NLAR 20210 rate-limit during sold-photo backfill overlap.
        if out_path.exists():
            mtime = datetime.fromtimestamp(out_path.stat().st_mtime, tz=timezone.utc)
            age_h = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
            print(f"[PROJECT] input missing ({in_path.name}); using prior "
                  f"{out_path.name} on disk ({age_h:.1f}h old — likely NLAR transient)",
                  file=sys.stderr)
            return 0
        print(f"[PROJECT] input not found: {in_path}", file=sys.stderr)
        print(f"[PROJECT] no prior projected cache to fall back on either", file=sys.stderr)
        return 1

    cache = json.loads(in_path.read_text(encoding="utf-8"))
    rows = cache.get("rows") or cache.get("listings") or []
    if not rows:
        print(f"[PROJECT] no rows in {in_path} (envelope keys: {list(cache.keys())})", file=sys.stderr)
        return 1

    print(f"[PROJECT] loaded {len(rows)} raw rows from {in_path}")

    projected = []
    skipped_oos = 0
    skipped_no_mls = 0
    skipped_stale = 0
    skipped_lease = 0
    for row in rows:
        if not args.no_scope_filter and not in_scope(row):
            skipped_oos += 1
            continue
        if is_lease_row(row):
            skipped_lease += 1
            continue
        if _is_stale_active(row):
            skipped_stale += 1
            continue
        proj = project_row(row, site_root)
        if not proj["mls"]:
            skipped_no_mls += 1
            continue
        projected.append(proj)

    by_city = {}
    for p in projected:
        by_city[p["city_slug"]] = by_city.get(p["city_slug"], 0) + 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "idx-projected",
        "source_cache_path": str(in_path),
        "source_generated_at": cache.get("fetched_at") or cache.get("generated_at"),
        "scope": SCOPE_SLUG,
        "postal_prefixes": list(POSTAL_PREFIXES),
        "count": len(projected),
        "skipped_out_of_scope": skipped_oos,
        "skipped_no_mls": skipped_no_mls,
        "skipped_lease": skipped_lease,
        "by_city": by_city,
        "listings": projected,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    size_kb = out_path.stat().st_size // 1024
    print(f"[PROJECT] wrote {out_path} ({size_kb} KB)")
    print(f"[PROJECT] in scope: {len(projected)} / out of scope: {skipped_oos} / stale-active: {skipped_stale} / lease: {skipped_lease} / no MLS: {skipped_no_mls}")
    print(f"[PROJECT] top cities: " + ", ".join(
        f"{c}={n}" for c, n in sorted(by_city.items(), key=lambda x: -x[1])[:10]
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
