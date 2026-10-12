#!/usr/bin/env python3
"""
Turner Realty — IDX/VOW Photo Sync — Lab West site (labwestrealty.com)
=========================================================================

Convention #15 byte-symmetric port from realestategander-site canonical.
Only R2_SITE_SLUG, postal-prefix scope filter, and header docstring
differ; all RETS GetObject + photo binary writing + hero generation
logic is identical.

Pulls listing photo binaries from NLAR Matrix RETS via the GetObject method
and hosts them on our side, per Angie Liang's 2026-05-11 guidance:

    "For photos, since the NLAR RETS feed provides photos through the
    GetObject method, the best approach would be to retrieve the images
    through RETS and then host/cache them on your side for public display,
    including listing galleries and OG/Twitter share images."

Output: images/listings/<MLSNumber>/001.jpg ... NNN.jpg + hero.jpg + .meta.json

Sync strategy (idempotent):
    For each listing in tools/idx-cache/listings.json that falls within
    this site's service area (per-site filter):
        1. Read tools/../images/listings/<MLS>/.meta.json (if exists)
        2. Compare its photo_mod_ts against listings.json:PhotoModificationTimestamp
        3. If newer or missing → fetch via RETS GetObject, write binaries
        4. Generate hero.jpg (1200x630 OG-optimized from photo 001)
        5. Update .meta.json with photo_mod_ts, photo_count, last_sync, urls

Modes:
    --probe                Login + check capability URLs, no writes
    --sample <MLS> [<MLS>] Pull a small set of MLS numbers for manual verification
    --all                  Pull all in-scope listings (filter applies)
    --force                Re-pull every photo regardless of mod-ts comparison
                           (use after a code change to photo handling)
    --dry-run              Don't write to disk; just report what would happen

Design spec: _research/IDX_Photo_Hosting_Design_Spec_2026-05-11.md

Convention compliance:
    #14 — listing photo files become tracked assets; pre-deploy-check sees them
    #15 — this tool is Gander-only today; propagation candidate to siblings
    #19 — baseline-additive-clean (new tool, no existing pipeline changes)
    #21 — defensive layers: fail-soft on missing/corrupt photos, listing still renders
    #31 — design spec on disk before code
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default as default_policy
from pathlib import Path

import requests

# Import shared RETS infrastructure from idx-ingest
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# Use importlib to load idx-ingest.py (hyphen in filename means we can't
# use plain `import idx-ingest`)
import importlib.util
_spec = importlib.util.spec_from_file_location("idx_ingest", SCRIPT_DIR / "idx-ingest.py")
_idx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_idx)

load_credentials = _idx.load_credentials
rets_login = _idx.rets_login
rets_logout = _idx.rets_logout

# R2 uploader — Convention #74 fail-safe import. When boto3 is missing OR
# R2 env vars are unset, r2_uploader.is_r2_enabled() returns False and all
# disk-write paths below stay active. Design spec:
# _research/Cloudflare_R2_Migration_Design_Spec_2026-05-21.md
import r2_uploader

# ─────────────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────────────

SITE_ROOT = SCRIPT_DIR.parent
CACHE_DIR = SCRIPT_DIR / "idx-cache"
IMAGES_DIR = SITE_ROOT / "images" / "listings"
LISTINGS_CACHE = CACHE_DIR / "listings.json"

# Per-site prefix for R2 keys (Decision A — single fleet bucket with
# site-prefix scheme). Gander's prefix is "gander/"; Avalon = "avalon/";
# Goosebay = "goosebay/"; Lab West = "labwest/". Each site's photo-sync script overrides this
# constant in its Convention #15 port.
R2_SITE_SLUG = "labwest"

# R2 path-segment inside the site prefix (Decision A scheme:
# <site>/listings/<MLS>/<NNN>.jpg).
R2_LISTINGS_PATH = "listings"

# Per-site filter for service-area listings: Lab West uses the projector's own in_scope()
# (Subdistrict "Labrador City / Wabush", A2V, or A0R with a Lab West town), so photos are
# only fetched for rows the site can actually show. Loaded lazily; fail-closed on error.
# Generate this many photos at minimum even if PhotoCount < this; saves
# a re-pull when a listing later gains more photos. Keep at 0 to trust feed.
MIN_PHOTO_PULL = 0

# Per-photo HTTP timeout (RETS GetObject can return large multipart bodies).
PHOTO_TIMEOUT = 60

# Photo type to fetch. NLAR Matrix offers Photo (~8 KB thumbnails) and
# LargePhoto (~70 KB gallery-quality). We want gallery quality.
PHOTO_TYPE = "LargePhoto"

# Hero image target size for OG/Twitter shares.
HERO_WIDTH = 1200
HERO_HEIGHT = 630


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────────────────────────────────────────────
#  SCOPE FILTER
# ─────────────────────────────────────────────────────────────────

_SCOPE_FN = None


def is_in_scope(listing: dict) -> bool:
    """True if listing falls within this site's service area (Labrador City / Wabush)."""
    global _SCOPE_FN
    if _SCOPE_FN is None:
        spec = importlib.util.spec_from_file_location("idx_projection", SCRIPT_DIR / "idx-project-to-ddf-shape.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _SCOPE_FN = mod.in_scope
    return bool(_SCOPE_FN(listing))


# ─────────────────────────────────────────────────────────────────
#  CACHE READ
# ─────────────────────────────────────────────────────────────────

def load_listings_cache() -> list:
    """Load tools/idx-cache/listings.json and return the list of records."""
    if not LISTINGS_CACHE.exists():
        print(f"ERROR: {LISTINGS_CACHE} not found. Run idx-ingest.py --pull active first.",
              file=sys.stderr)
        sys.exit(1)
    with open(LISTINGS_CACHE, encoding="utf-8") as f:
        cache = json.load(f)
    return cache.get("rows") or cache.get("listings") or []


# ─────────────────────────────────────────────────────────────────
#  PER-LISTING META
# ─────────────────────────────────────────────────────────────────

def listing_dir(mls: str) -> Path:
    """Per-listing photo folder path."""
    return IMAGES_DIR / str(mls)


def meta_path(mls: str) -> Path:
    return listing_dir(mls) / ".meta.json"


def load_meta(mls: str) -> dict:
    p = meta_path(mls)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_meta(mls: str, meta: dict) -> None:
    p = meta_path(mls)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)


# ─────────────────────────────────────────────────────────────────
#  RETS GetObject CALL + MULTIPART PARSE
# ─────────────────────────────────────────────────────────────────

def fetch_photos(session: requests.Session, getobject_url: str, matrix_uid: str,
                 *, photo_type: str = PHOTO_TYPE, verbose: bool = False) -> list:
    """Fetch all photos for one listing via RETS GetObject.

    Returns: list of dicts: [{"index": 1, "bytes": b"...", "content_type": "image/jpeg"}, ...]
    Empty list on failure (fail-soft per Convention #21).

    Matrix GetObject params:
        Resource=Property              — what we're asking about
        Type=Photo or LargePhoto       — photo size (LargePhoto = gallery-quality)
        ID=<Matrix_Unique_ID>:*        — '*' means "all photos for this listing"
                                          (Matrix's Property KeyField is
                                          Matrix_Unique_ID, NOT MLSNumber)
        Location=0                     — binaries inline (Location=1 disabled by NLAR)
    """
    params = {
        "Resource": "Property",
        "Type": photo_type,
        "ID": f"{matrix_uid}:*",
        "Location": "0",
    }
    try:
        r = session.get(getobject_url, params=params, timeout=PHOTO_TIMEOUT)
    except requests.RequestException as e:
        if verbose:
            print(f"  [fetch] {mls}: connection failed: {e}", file=sys.stderr)
        return []

    if r.status_code != 200:
        if verbose:
            print(f"  [fetch] {matrix_uid}: HTTP {r.status_code}", file=sys.stderr)
        return []

    content_type = r.headers.get("Content-Type", "")
    body = r.content

    # RETS error response (returns 200 with XML body, NOT image binary)
    if "text/xml" in content_type.lower() or body.startswith(b"<?xml"):
        if verbose:
            err_match = re.search(rb'ReplyCode="(\d+)"\s+ReplyText="([^"]+)"', body)
            if err_match:
                print(f"  [fetch] {matrix_uid}: RETS error {err_match.group(1).decode()} "
                      f"{err_match.group(2).decode()}", file=sys.stderr)
            else:
                print(f"  [fetch] {matrix_uid}: XML error response", file=sys.stderr)
        return []

    # Single-photo response — content is the raw binary, headers have metadata
    if "multipart/" not in content_type.lower():
        idx = int(r.headers.get("Object-ID", "1"))
        return [{
            "index": idx,
            "bytes": body,
            "content_type": content_type.split(";")[0].strip() or "image/jpeg",
        }]

    # Multipart response — parse each part
    # RETS multipart wraps response in `multipart/parallel; boundary="..."`
    # Use Python's email parser (works on bytes when policy=default)
    boundary_match = re.search(r'boundary="?([^";\s]+)"?', content_type)
    if not boundary_match:
        if verbose:
            print(f"  [fetch] {matrix_uid}: no boundary in Content-Type: {content_type}",
                  file=sys.stderr)
        return []

    # Build a synthetic MIME envelope the parser can consume
    full = f"Content-Type: {content_type}\r\n\r\n".encode() + body
    msg = BytesParser(policy=default_policy).parsebytes(full)

    photos = []
    for i, part in enumerate(msg.iter_parts(), start=1):
        ctype = part.get_content_type() or "image/jpeg"
        # Skip text/error parts (RETS sometimes embeds a 20403 "no photos" reply)
        if not ctype.startswith("image/"):
            continue
        payload = part.get_payload(decode=True) or b""
        if not payload:
            continue
        # Object-ID header carries the photo index; fall back to enumerate
        obj_id = part.get("Object-ID")
        try:
            idx = int(obj_id) if obj_id else i
        except ValueError:
            idx = i
        # RETS Matrix returns Object-ID=0 as the "default photo" sentinel,
        # which is a duplicate of Object-ID=1. Skip it — Object-IDs 1..N
        # are the canonical numbered photos.
        if idx == 0:
            continue
        photos.append({"index": idx, "bytes": payload, "content_type": ctype})

    return photos


def write_photos(mls: str, photos: list, *, dry_run: bool = False):
    """Write photo binaries.

    Branches on r2_uploader.is_r2_enabled():
      - R2 mode: PUT each photo to R2 under <site>/listings/<MLS>/<NNN>.<ext>;
        skip disk-write entirely. Convention #74 fail-safe — if R2 client
        init fails mid-batch, falls back to disk-write for remaining photos
        (logged but not raised).
      - Disk mode (default): existing behavior, write to images/listings/<MLS>/.

    Returns (count_written, r2_put_failures).  r2_put_failures > 0 means
    Convention #74 fail-safe absorbed an R2 AccessDenied / other PUT error
    and silently fell back to disk-write. Surface via Convention #49.
    """
    if not photos:
        return 0
    if dry_run:
        return len(photos)

    # Map content-type to extension. RETS GetObject usually returns image/jpeg.
    ext_map = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }

    r2_active = r2_uploader.is_r2_enabled()

    # In disk mode, ensure the local directory exists.
    if not r2_active:
        out_dir = listing_dir(mls)
        out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    r2_failed = 0
    for p in photos:
        idx = p["index"]
        ctype = p["content_type"].lower()
        ext = ext_map.get(ctype, ".jpg")
        fname = f"{idx:03d}{ext}"

        if r2_active:
            # R2 PUT — key scheme: <site>/listings/<MLS>/<NNN>.<ext>
            key = r2_uploader.build_key(
                R2_SITE_SLUG,
                f"{R2_LISTINGS_PATH}/{mls}/{fname}",
            )
            result = r2_uploader.upload_bytes(
                p["bytes"],
                key,
                content_type=ctype if ctype.startswith("image/") else "image/jpeg",
                cache_control="public, max-age=31536000, immutable",
                skip_if_exists=False,  # within sync_one(), we wipe stale first; always overwrite
            )
            if result.ok:
                written += 1
            else:
                # Convention #74 — log loud, fall back to disk for THIS photo
                r2_failed += 1
                print(f"  [r2-write] {mls} #{idx} FAILED: {result.error} — "
                      "falling back to disk for this photo", file=sys.stderr)
                out_dir = listing_dir(mls)
                out_dir.mkdir(parents=True, exist_ok=True)
                with open(out_dir / fname, "wb") as f:
                    f.write(p["bytes"])
                written += 1
        else:
            # Disk mode (legacy / fail-safe)
            out_path = listing_dir(mls) / fname
            with open(out_path, "wb") as f:
                f.write(p["bytes"])
            written += 1

    return written, r2_failed


def generate_hero(mls: str, *, dry_run: bool = False, verbose: bool = False,
                  source_bytes: bytes = None) -> bool:
    """Generate hero.jpg (1200x630 OG-optimized).

    Source: if `source_bytes` is provided, use it directly (R2 mode — bytes
    in memory from the photo fetch). Otherwise read 001.jpg from disk (legacy
    disk mode).

    Destination: R2 PUT to <site>/listings/<MLS>/hero.jpg if R2 enabled, else
    disk write to images/listings/<MLS>/hero.jpg.

    PIL path: crop-to-fit + resize to 1200x630 + re-encode at q85.
    Fallback (PIL missing): byte-copy source 001 → hero so OG/Twitter share
        previews still work (just not at the optimal aspect).

    Returns True on either path. Returns False only when source is unavailable.
    """
    if dry_run:
        return True

    r2_active = r2_uploader.is_r2_enabled()

    # Resolve source bytes — either from caller (R2 mode) or from disk (legacy).
    if source_bytes is None:
        src = listing_dir(mls) / "001.jpg"
        if not src.exists():
            return False
        try:
            source_bytes = src.read_bytes()
        except Exception as e:
            print(f"  [hero] {mls}: source read failed: {e}", file=sys.stderr)
            return False
    if not source_bytes:
        return False

    # Try PIL path first
    try:
        from PIL import Image
        from io import BytesIO
    except ImportError:
        if verbose:
            print(f"  [hero] {mls}: PIL not available — byte-copying source → hero",
                  file=sys.stderr)
        # Fallback: byte-copy source bytes to destination
        return _write_hero_bytes(mls, source_bytes, r2_active)

    try:
        img = Image.open(BytesIO(source_bytes))
        img = img.convert("RGB")  # JPEG can't carry alpha; flatten just in case
        # Cover-fit to 1200x630 (preserve aspect ratio, crop overflow)
        target_ratio = HERO_WIDTH / HERO_HEIGHT
        src_w, src_h = img.size
        src_ratio = src_w / src_h
        if src_ratio > target_ratio:
            new_w = int(src_h * target_ratio)
            offset = (src_w - new_w) // 2
            img = img.crop((offset, 0, offset + new_w, src_h))
        elif src_ratio < target_ratio:
            new_h = int(src_w / target_ratio)
            offset = (src_h - new_h) // 2
            img = img.crop((0, offset, src_w, offset + new_h))
        img = img.resize((HERO_WIDTH, HERO_HEIGHT), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, "JPEG", quality=85, optimize=True)
        return _write_hero_bytes(mls, buf.getvalue(), r2_active)
    except Exception as e:
        print(f"  [hero] {mls}: PIL failed: {e} — falling back to byte-copy",
              file=sys.stderr)
        return _write_hero_bytes(mls, source_bytes, r2_active)


def _write_hero_bytes(mls: str, hero_bytes: bytes, r2_active: bool) -> bool:
    """Persist hero bytes to R2 or disk. Helper for generate_hero."""
    if r2_active:
        key = r2_uploader.build_key(
            R2_SITE_SLUG,
            f"{R2_LISTINGS_PATH}/{mls}/hero.jpg",
        )
        result = r2_uploader.upload_bytes(
            hero_bytes,
            key,
            content_type="image/jpeg",
            # Hero is revisable when new photos arrive — shorter cache + revalidate
            cache_control="public, max-age=86400, must-revalidate",
            skip_if_exists=False,
        )
        if not result.ok:
            print(f"  [hero] {mls}: R2 upload failed: {result.error} — "
                  "falling back to disk", file=sys.stderr)
            # Convention #74 fall-through to disk
        else:
            return True

    # Disk write (default mode OR R2 failure fallback)
    try:
        out_dir = listing_dir(mls)
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / "hero.jpg"
        dst.write_bytes(hero_bytes)
        return True
    except Exception as e:
        print(f"  [hero] {mls}: disk write failed: {e}", file=sys.stderr)
        return False


# ─────────────────────────────────────────────────────────────────
#  PER-LISTING SYNC
# ─────────────────────────────────────────────────────────────────

def needs_sync(listing: dict, meta: dict, *, force: bool = False) -> bool:
    """Should we re-pull this listing's photos?"""
    if force:
        return True
    if not meta:
        return True  # Never synced
    feed_ts = listing.get("PhotoModificationTimestamp")
    local_ts = meta.get("photo_mod_ts")
    if not feed_ts:
        return False  # No feed timestamp — nothing to compare against
    if feed_ts != local_ts:
        return True  # Timestamp drift
    # Photo count drift (defensive — handles case where mod-ts didn't update but count did)
    feed_count_str = listing.get("PhotoCount")
    try:
        feed_count = int(feed_count_str) if feed_count_str else 0
    except (TypeError, ValueError):
        feed_count = 0
    local_count = meta.get("photo_count", 0)
    if feed_count > local_count:
        return True
    return False


def sync_one(session, getobject_url, listing: dict, *,
             force: bool = False, dry_run: bool = False, verbose: bool = False) -> dict:
    """Sync photos for one listing. Returns result dict."""
    mls = str(listing.get("MLSNumber") or "").strip()
    matrix_uid = str(listing.get("Matrix_Unique_ID") or "").strip()
    if not mls:
        return {"mls": "?", "status": "skipped", "reason": "no MLS"}
    if not matrix_uid:
        return {"mls": mls, "status": "skipped", "reason": "no Matrix_Unique_ID"}

    meta = load_meta(mls)

    if not needs_sync(listing, meta, force=force):
        return {"mls": mls, "status": "fresh", "photo_count": meta.get("photo_count", 0)}

    if dry_run:
        feed_count = int(listing.get("PhotoCount") or 0)
        return {
            "mls": mls,
            "status": "would-fetch",
            "feed_count": feed_count,
            "feed_ts": listing.get("PhotoModificationTimestamp"),
            "local_ts": meta.get("photo_mod_ts"),
        }

    if verbose:
        feed_count = int(listing.get("PhotoCount") or 0)
        print(f"  [sync] {mls} (MUID {matrix_uid}) → fetching {feed_count} photos",
              file=sys.stderr)

    photos = fetch_photos(session, getobject_url, matrix_uid, verbose=verbose)
    if not photos:
        return {"mls": mls, "status": "fetch-empty"}

    # Wipe stale photos before writing fresh set.
    # Disk-mode: glob + unlink the local directory.
    # R2-mode: same-key PUT overwrites; numbered-photo keys (001.jpg ... NNN.jpg)
    #          stay stable per listing. If a listing's photo count SHRINKS
    #          (NLAR removed some photos), the higher-numbered keys become
    #          orphaned in R2. The .meta.json photo_count tracks the current
    #          set; orphan cleanup happens via tools/idx-photo-cleanup.py
    #          on a separate cadence (Decision G — Phase 2 follow-on).
    if not r2_uploader.is_r2_enabled():
        out_dir = listing_dir(mls)
        if out_dir.exists():
            for old in out_dir.glob("*.jpg"):
                old.unlink()
            for old in out_dir.glob("*.webp"):
                old.unlink()
            for old in out_dir.glob("*.png"):
                old.unlink()

    written, r2_failed = write_photos(mls, photos, dry_run=False)
    # Pass photo[0]["bytes"] (the highest-priority source for hero) directly
    # in R2 mode so we don't need to round-trip via disk. In disk mode the
    # source_bytes arg is ignored and generate_hero reads 001.jpg from disk
    # (existing behavior preserved).
    hero_source = photos[0]["bytes"] if (photos and r2_uploader.is_r2_enabled()) else None
    hero_ok = generate_hero(mls, dry_run=False, verbose=verbose,
                            source_bytes=hero_source)

    # Persist meta
    new_meta = {
        "mls": mls,
        "matrix_uid": matrix_uid,
        "photo_mod_ts": listing.get("PhotoModificationTimestamp"),
        "photo_count": written,
        "photo_type": PHOTO_TYPE,
        "last_sync": _now_iso(),
        "hero_generated": hero_ok,
    }
    # Re-activation pattern: clear removed_at if it was set
    # (don't carry over from prior meta — fresh sync starts clean)
    save_meta(mls, new_meta)

    return {"mls": mls, "status": "synced", "photo_count": written, "hero": hero_ok, "r2_failed": r2_failed}


# ─────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(description="NLAR IDX/VOW photo sync.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--probe", action="store_true",
                       help="Login + check GetObject URL; no fetch.")
    group.add_argument("--sample", nargs="+", metavar="MLS",
                       help="Sync specific MLS numbers.")
    group.add_argument("--all", action="store_true",
                       help="Sync every in-scope listing in cache.")
    parser.add_argument("--force", action="store_true",
                        help="Re-pull regardless of mod-ts comparison.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report only; don't write files.")
    parser.add_argument("--limit", type=int, default=None,
                        help="With --all, stop after N listings (smoke-test).")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    creds = load_credentials()
    session, capabilities, server_info = rets_login(creds, verbose=args.verbose)

    getobject_url = capabilities.get("getobject")
    if not getobject_url:
        print("ERROR: GetObject capability URL not in login response.", file=sys.stderr)
        rets_logout(session, capabilities)
        sys.exit(1)

    if args.probe:
        print(f"GetObject URL: {getobject_url}")
        print(f"RETS version : {server_info.get('rets_version')}")
        print(f"Server       : {server_info.get('server')}")
        rets_logout(session, capabilities)
        return 0

    # Load listings cache + filter to scope
    all_listings = load_listings_cache()
    in_scope = [l for l in all_listings if is_in_scope(l)]
    print(f"In-scope listings (Labrador): {len(in_scope)} of {len(all_listings)} total")

    # Resolve which listings to sync this run
    if args.sample:
        target_mls = set(args.sample)
        targets = [l for l in in_scope if str(l.get("MLSNumber")) in target_mls]
        # Also accept out-of-scope MLS if user explicitly named it (debug)
        if len(targets) < len(target_mls):
            all_mls = {str(l.get("MLSNumber")): l for l in all_listings}
            for m in target_mls:
                if m in all_mls and all_mls[m] not in targets:
                    targets.append(all_mls[m])
    else:
        # Sync newest listings FIRST so brand-new listings (the ones
        # consumers + agents notice immediately) get their photos uploaded
        # before the run's time budget is spent on the older backlog.
        # MLSNumber is monotonic (higher = newer). Already-synced listings
        # skip fast via needs_sync() regardless of order. Ported from
        # Gander/Avalon (2026-06-04 fix) -- Goose Bay never gained this and
        # was still syncing in raw cache order. (2026-09-15 photo-display
        # fleet check.)
        def _recency_key(l):
            try:
                return int(str(l.get("MLSNumber") or "0").strip())
            except (TypeError, ValueError):
                return 0
        targets = sorted(in_scope, key=_recency_key, reverse=True)
        if args.limit:
            targets = targets[:args.limit]

    print(f"Targets to sync this run: {len(targets)}")

    # Sync loop
    stats = {"synced": 0, "fresh": 0, "fetch-empty": 0, "would-fetch": 0,
             "skipped": 0, "errored": 0, "r2_put_failures": 0}
    total_photos = 0
    t0 = time.time()
    for i, listing in enumerate(targets, 1):
        try:
            result = sync_one(session, getobject_url, listing,
                              force=args.force, dry_run=args.dry_run,
                              verbose=args.verbose)
        except Exception as e:
            print(f"  [sync] EXCEPTION on MLS {listing.get('MLSNumber')}: {e}",
                  file=sys.stderr)
            stats["errored"] += 1
            continue

        status = result.get("status", "skipped")
        stats[status] = stats.get(status, 0) + 1
        if status == "synced":
            total_photos += result.get("photo_count", 0)
            stats["r2_put_failures"] += result.get("r2_failed", 0)

        if args.verbose or i <= 3 or i % 25 == 0:
            print(f"  [{i}/{len(targets)}] {result}", file=sys.stderr)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print(f"  synced={stats.get('synced', 0)}  photos_written={total_photos}")
    print(f"  fresh={stats.get('fresh', 0)}  fetch-empty={stats.get('fetch-empty', 0)}")
    if args.dry_run:
        print(f"  would-fetch={stats.get('would-fetch', 0)}")
    print(f"  errored={stats.get('errored', 0)}")
    # Convention #49 — surface silent R2 PUT failures that Convention #74 absorbed.
    r2_fails = stats.get("r2_put_failures", 0)
    if r2_fails > 0:
        print(f"  ⚠ r2_put_failures={r2_fails} — R2 PUTs FAILED, photos fell back to disk only. "
              "Check R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY GH Actions secrets vs canonical "
              ".env (Convention #123 explicit --body re-set if stale).", file=sys.stderr)

    # Convention #74 — write structured stats for skip-regen gate
    # Workflow reads this to decide whether to run expensive regen
    try:
        import json as _json
        from pathlib import Path as _Path
        from datetime import datetime as _dt, timezone as _tz
        stats_out = {
            "completed_at": _dt.now(_tz.utc).isoformat(),
            "elapsed_sec": round(elapsed, 2),
            "photos_written": total_photos,
            "synced": stats.get("synced", 0),
            "fresh": stats.get("fresh", 0),
            "fetch_empty": stats.get("fetch-empty", 0),
            "errored": stats.get("errored", 0),
            "r2_put_failures": r2_fails,
        }
        stats_path = _Path(__file__).parent / "idx-cache" / "last-photo-sync-stats.json"
        stats_path.write_text(_json.dumps(stats_out, indent=2))
        print(f"  wrote stats: tools/idx-cache/last-photo-sync-stats.json")
    except Exception as _e:
        # Fail-safe: don't break pipeline if stats write fails
        print(f"  WARN: photo-sync stats write failed: {_e}", file=sys.stderr)

    rets_logout(session, capabilities)
    # Exit non-zero on R2 silent-fail so CI surfaces the issue loudly.
    return 1 if r2_fails > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
