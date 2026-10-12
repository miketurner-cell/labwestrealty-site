#!/usr/bin/env python3
"""Skip-regen gate — outputs `should_regen=true|false` for GitHub Actions.

Reads stats files written by idx-ingest.py + idx-photo-sync.py at end of
each run. If both report zero changes (no IDX upserts, no photos written),
emits `should_regen=false` so the workflow skips the expensive regen.

Convention #74 fail-safe: any missing/unreadable stats file → defaults to
should_regen=true so we never silently skip when uncertain.

2026-09-17 error sweep: also forces a regen when ddf-generate-pages.py itself
has changed since the last real run recorded its own fingerprint in
deploy-manifest.json. Without this, a template-only ship (no listing data
changed) sits invisible on a quiet site until the next unconditional nightly
-- confirmed live: B3's mobile swipe gallery merged and deployed on Goose
Bay, but the hourly gate kept reading zero data delta and the generator that
would render the new markup never ran. A human remembering `force_regen` on
every generator PR is not a fix; comparing the file's own hash is.
"""
import hashlib
import json
import os
import sys
from pathlib import Path


def safe_load(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


def main():
    # force_regen workflow_dispatch input (2026-06-11): code-only/template
    # ships need same-hour rendering; the gate otherwise only sees data deltas.
    if os.environ.get("FORCE_REGEN", "").lower() in ("1", "true", "yes"):
        print("should_regen=true")
        print("[gate] FORCE_REGEN set — regen forced", file=sys.stderr)
        return
    cache_dir = Path(__file__).parent / "idx-cache"
    reasons = []

    pull_stats = safe_load(cache_dir / "last-pull-stats.json")
    if pull_stats is None:
        reasons.append("pull-stats-missing")
        upserts = -1
    elif not pull_stats.get("results"):
        # 2026-08-24: an NLAR search that errors mid-run does `continue`
        # inside idx-ingest.py's op loop -- summary["results"] never gets an
        # entry for that op, but the stats file still gets written (its
        # fetched_at is stamped at the START of the run, unconditionally).
        # A bare `{}.values()` sum over that then reads 0 with no reason,
        # which is the FALSE-SKIP class that actually fired on 2026-08-24
        # 10:45 (a failed search silently skipped a regen). Treat an
        # empty/missing results dict the same as a missing stats file.
        reasons.append("pull-failed-or-empty")
        upserts = -1
    else:
        upserts = 0
        for r in pull_stats.get("results", {}).values():
            # 2026-08-24: prefer region-scoped counts when idx-ingest.py
            # provided them (only the "active" op does, per the
            # region-scoping ship) -- key ABSENCE is the fallback signal
            # per Convention #74: an older idx-ingest.py, a failed filter
            # load, or a non-active op all fall straight through to the
            # feed-wide counts exactly as before.
            if "upserted_in_region" in r:
                upserts += int(r.get("upserted_in_region", 0) or 0)
            else:
                upserts += int(r.get("upserted", 0) or 0)
            upserts += int(r.get("upserted_full", 0) or 0)
            upserts += int(r.get("upserted_consumer", 0) or 0)
            if "removed_in_region" in r:
                upserts += int(r.get("removed_in_region", 0) or 0)
            else:
                upserts += int(r.get("removed", 0) or 0)

    photo_stats = safe_load(cache_dir / "last-photo-sync-stats.json")
    if photo_stats is None:
        reasons.append("photo-stats-missing")
        photos = -1
    else:
        photos = int(photo_stats.get("photos_written", 0) or 0)

    # generator-fingerprint check (2026-09-17): compare the CURRENT generator source
    # against the fingerprint recorded the last time it actually ran. A missing
    # manifest/field (first run after this ships, or a run that used --no-manifest)
    # fails safe toward regen, per Convention #74 -- never toward silently skipping.
    generator_path = Path(__file__).parent / "ddf-generate-pages.py"
    manifest = safe_load(Path(__file__).parent / "ddf-cache" / "deploy-manifest.json")
    try:
        current_gen_hash = hashlib.sha256(generator_path.read_bytes()).hexdigest()
    except Exception:
        current_gen_hash = None
    last_gen_hash = (manifest or {}).get("generator_sha256")
    if current_gen_hash is None or last_gen_hash is None or current_gen_hash != last_gen_hash:
        reasons.append("generator-changed")

    should_regen = True
    if not reasons and upserts == 0 and photos == 0:
        should_regen = False

    val = "true" if should_regen else "false"
    print(f"should_regen={val}")

    if should_regen:
        reason_txt = f" ({' + '.join(reasons)})" if reasons else ""
        sys.stderr.write(
            f"::notice::Changes detected — upserts={upserts} photos={photos}{reason_txt} → regen will run\n"
        )
    else:
        sys.stderr.write(
            "::notice::No changes (upserts=0 photos=0) — skipping regen (saves ~3 min)\n"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
