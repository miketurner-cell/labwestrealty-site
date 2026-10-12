#!/usr/bin/env python3
"""
Turner Realty — IDX/VOW Photo Cleanup
======================================

Walks images/listings/<MLS>/ folders and:

    1. Soft-mark: when a listing's MLSNumber is no longer in either the
       active or sold cache, write `removed_at: <ISO>` into its .meta.json
       (idempotent — re-marks the same timestamp if already set).

    2. Hard-purge: with --hard-purge --confirm, delete folders whose
       removed_at is older than RETENTION_DAYS (default 90).

Soft-mark is safe to run hourly. Hard-purge runs nightly (and requires
--confirm to actually delete; without it, the script prints what WOULD
be purged).

Defensive design:
    - Listings can flip between Active → Pending → Active during negotiation.
      90 days is generous enough that brief disappearances don't cost photos.
    - SEO indexed pages may still be served briefly after status change;
      grace period keeps detail pages from breaking immediately on flip.
    - If a listing re-appears in the feed before purge, idx-photo-sync.py
      clears the removed_at marker (re-activation pattern).

Convention compliance:
    #21 — defensive layers; never hard-purge without explicit confirmation
    #22 — local cache freshness — refuse to run if cache is older than 6h
    #65 — staged-set audit pattern (counts before destructive ops)
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SITE_ROOT = SCRIPT_DIR.parent
CACHE_DIR = SCRIPT_DIR / "idx-cache"
IMAGES_DIR = SITE_ROOT / "images" / "listings"
ACTIVE_CACHE = CACHE_DIR / "listings.json"
SOLD_CACHE = CACHE_DIR / "sold-listings.json"

RETENTION_DAYS = 90
CACHE_FRESHNESS_HOURS = 6


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")


def load_cache_mls_set(path: Path) -> set:
    """Return the set of MLSNumbers in a cache file. Empty set if cache missing."""
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("rows") or data.get("listings") or []
    return {str(r.get("MLSNumber") or "").strip() for r in rows if r.get("MLSNumber")}


def cache_age_hours(path: Path) -> float:
    """Hours since cache file was generated (per its fetched_at field)."""
    if not path.exists():
        return 999.0
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        ts_str = data.get("fetched_at") or data.get("generated_at")
        if not ts_str:
            return 999.0
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        delta = _now() - ts
        return delta.total_seconds() / 3600
    except Exception:
        return 999.0


def parse_iso(ts_str: str):
    """Parse an ISO timestamp string to datetime. Returns None on failure."""
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def find_local_listing_dirs() -> list:
    """Enumerate images/listings/<MLS>/ folders that contain a .meta.json."""
    if not IMAGES_DIR.exists():
        return []
    result = []
    for entry in sorted(IMAGES_DIR.iterdir()):
        if not entry.is_dir():
            continue
        meta = entry / ".meta.json"
        if meta.exists():
            result.append(entry)
    return result


def load_meta(folder: Path) -> dict:
    try:
        with open(folder / ".meta.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_meta(folder: Path, meta: dict) -> None:
    with open(folder / ".meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)


def cmd_soft_mark(args):
    """Mark listings that have left the feed; clear marks for re-activations."""
    active_mls = load_cache_mls_set(ACTIVE_CACHE)
    sold_mls = load_cache_mls_set(SOLD_CACHE)
    live_mls = active_mls | sold_mls

    # Convention #74 fail-safe (refined 2026-06-07): a stale/absent active cache —
    # e.g. a transient NLAR pull failure (HTTP 403 / rate-limit) left no fresh
    # listings.json this run — means we can't safely decide which listings left
    # the feed, so soft-marking now could wrongly flag still-active listings as
    # removed. SKIP this non-critical step with a WARNING instead of exiting
    # non-zero. (The step is continue-on-error in CI so exit 2 never failed the
    # job, but it left a scary ERROR line in every pull-failure hourly log;
    # warn+skip is the correct graceful degrade — companion to the active-cache
    # restore added to the hourlies 2026-06-06.) --skip-freshness still forces a run.
    if not args.skip_freshness:
        age_active = cache_age_hours(ACTIVE_CACHE)
        if age_active > CACHE_FRESHNESS_HOURS:
            print(f"WARNING: active cache is {age_active:.1f}h old (>{CACHE_FRESHNESS_HOURS}h) — "
                  f"skipping soft-mark this run (nothing marked; not an error). "
                  f"Run tools/idx-ingest.py --pull active first, or pass --skip-freshness.",
                  file=sys.stderr)
            return

    folders = find_local_listing_dirs()
    print(f"Scanning {len(folders)} local listing folders against "
          f"{len(active_mls)} active + {len(sold_mls)} sold MLS numbers...")

    marked = 0
    cleared = 0
    fresh = 0

    for folder in folders:
        mls = folder.name
        meta = load_meta(folder)
        had_mark = "removed_at" in meta
        is_live = mls in live_mls

        if is_live and had_mark:
            # Re-activation — clear the mark
            del meta["removed_at"]
            if not args.dry_run:
                save_meta(folder, meta)
            cleared += 1
            if args.verbose:
                print(f"  [cleared] {mls} reactivated in feed")
        elif not is_live and not had_mark:
            # Newly absent — soft-mark
            meta["removed_at"] = _now_iso()
            if not args.dry_run:
                save_meta(folder, meta)
            marked += 1
            if args.verbose:
                print(f"  [marked] {mls} no longer in feed")
        elif is_live:
            fresh += 1
        # else: not live AND already marked — no-op

    print(f"\nsoft-mark summary: {marked} newly-marked, {cleared} re-activated, "
          f"{fresh} fresh-in-feed, {len(folders) - marked - cleared - fresh} "
          "still-marked-from-previous-run")


def cmd_hard_purge(args):
    """Delete folders past the retention window."""
    folders = find_local_listing_dirs()
    threshold = _now() - timedelta(days=RETENTION_DAYS)

    candidates = []
    for folder in folders:
        meta = load_meta(folder)
        removed_str = meta.get("removed_at")
        if not removed_str:
            continue
        removed_dt = parse_iso(removed_str)
        if not removed_dt:
            continue
        if removed_dt < threshold:
            age_days = (_now() - removed_dt).days
            candidates.append((folder, age_days))

    if not candidates:
        print(f"No folders past the {RETENTION_DAYS}-day retention window. "
              f"Total local folders: {len(folders)}.")
        return

    print(f"Found {len(candidates)} folder(s) past {RETENTION_DAYS}-day retention:")
    for folder, age in candidates[:20]:
        print(f"  {folder.name}  ({age}d since removal)")
    if len(candidates) > 20:
        print(f"  ... + {len(candidates) - 20} more")

    if not args.confirm:
        print(f"\nNOT deleting (use --confirm to actually purge).")
        return

    # Convention #65 — confirmation gate
    print(f"\n--confirm passed. Deleting {len(candidates)} folder(s)...")
    deleted_count = 0
    deleted_bytes = 0
    for folder, _ in candidates:
        try:
            size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
            shutil.rmtree(folder)
            deleted_count += 1
            deleted_bytes += size
        except Exception as e:
            print(f"  ERROR deleting {folder}: {e}", file=sys.stderr)

    mb = deleted_bytes / (1024 * 1024)
    print(f"\nHard-purge complete: {deleted_count} folder(s), {mb:.1f} MB freed.")


def cmd_status(args):
    """Print a human-readable summary of current state."""
    folders = find_local_listing_dirs()
    active_mls = load_cache_mls_set(ACTIVE_CACHE)
    sold_mls = load_cache_mls_set(SOLD_CACHE)
    live_mls = active_mls | sold_mls

    in_active = 0
    in_sold = 0
    marked_for_removal = 0
    past_retention = 0
    threshold = _now() - timedelta(days=RETENTION_DAYS)
    total_bytes = 0

    for folder in folders:
        meta = load_meta(folder)
        mls = folder.name
        if mls in active_mls:
            in_active += 1
        elif mls in sold_mls:
            in_sold += 1
        if "removed_at" in meta:
            marked_for_removal += 1
            removed_dt = parse_iso(meta["removed_at"])
            if removed_dt and removed_dt < threshold:
                past_retention += 1
        try:
            total_bytes += sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
        except Exception:
            pass

    mb = total_bytes / (1024 * 1024)
    print(f"images/listings/ status:")
    print(f"  Total local listing folders     : {len(folders)}")
    print(f"  Match active cache              : {in_active}")
    print(f"  Match sold cache                : {in_sold}")
    print(f"  Soft-marked for removal         : {marked_for_removal}")
    print(f"  Past {RETENTION_DAYS}-day retention (hard-purge candidates): {past_retention}")
    print(f"  Total disk usage                : {mb:.1f} MB")


# ─────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(description="IDX/VOW photo cleanup.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_mark = sub.add_parser("soft-mark", help="Mark folders for listings no longer in feed (safe).")
    p_mark.add_argument("--dry-run", action="store_true")
    p_mark.add_argument("--verbose", "-v", action="store_true")
    p_mark.add_argument("--skip-freshness", action="store_true",
                        help="Skip the 6h cache-freshness gate (use with caution).")
    p_mark.set_defaults(func=cmd_soft_mark)

    p_purge = sub.add_parser("hard-purge", help="Delete folders past retention window.")
    p_purge.add_argument("--confirm", action="store_true",
                         help="Required to actually delete; without it, dry-run only.")
    p_purge.add_argument("--verbose", "-v", action="store_true")
    p_purge.set_defaults(func=cmd_hard_purge)

    p_status = sub.add_parser("status", help="Print current cleanup-relevant state.")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
