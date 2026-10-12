#!/usr/bin/env python3
"""
Turner Realty — Open House Sync (Batch F1, 2026-08-19)
========================================================

Pulls upcoming PUBLIC open-house events from NLAR's OpenHouse RETS resource
(same resource + field vocabulary already proven live in
fb-post.py:_fetch_open_houses -- verified 2026-06-11: OpenHouseDate/
StartTime/EndTime/Listing_MUI/ActiveYN/OpenHouseType) and writes
tools/idx-cache/open-houses.json, grouped by Matrix_Unique_ID -- the SAME
shape + merge point idx-ingest.py --pull rooms already established
(tools/ddf-generate-pages.py:main() already bridges MLS->MUI via
idx_rec["Matrix_Unique_ID"] for the rooms merge; open houses reuse that
exact bridge, one dict lookup away, in the same overlay loop).

Why a standalone sync rather than folding into idx-ingest.py's ~1600-line
--pull machinery: OpenHouse is a small, independent RETS resource with its
own query shape (date-windowed forward from today, not incremental-by-
MatrixModifiedDT like Property:Listing) -- matches the
idx-drivetimes-sync.py precedent of a narrow, single-purpose sidecar sync
rather than growing the monolith. Reuses idx-ingest.py's proven
rets_login/load_credentials/search_paginated via importlib, the exact
pattern fb-post.py:_fetch_open_houses already uses.

Output: tools/idx-cache/open-houses.json
    {fetched_at, pull_type: "open-house", event_count, listing_count,
     by_mui: {<MUI>: [{date, start_time, end_time, type}, ...]}}

Modes:
    --probe     Verify login + one OpenHouse search only, print the raw
                first-record field set (Conv #68), write nothing.
    (default)   Full pull + write open-houses.json.

Conv #74 fail-safe throughout -- a RETS/auth/parse failure prints to
stderr and exits 0 (never blocks the CI regen it rides alongside); the
generator's own read-side guard already degrades gracefully on a missing
or unreadable cache, mirroring the rooms-cache pattern verbatim.
"""

import argparse
import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_DIR = SCRIPT_DIR / "idx-cache"


def _load_ingest_module():
    p = SCRIPT_DIR / "idx-ingest.py"
    spec = importlib.util.spec_from_file_location("idx_ingest_oh_sync", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("--probe", action="store_true",
                     help="Login + one OpenHouse search only; print the raw "
                          "first-record field set; write nothing.")
    ap.add_argument("--json", action="store_true", help="Machine-readable summary.")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    try:
        mod = _load_ingest_module()
        creds = mod.load_credentials()
    except SystemExit:
        print("  ⚠ open-house sync: credentials unavailable -- skipping", file=sys.stderr)
        return 0
    except Exception as e:  # noqa: BLE001 -- Conv #74
        print(f"  ⚠ open-house sync: could not load idx-ingest.py ({type(e).__name__}: {e}) -- skipping", file=sys.stderr)
        return 0

    try:
        session, caps, _info = mod.rets_login(creds, verbose=args.verbose)
    except Exception as e:  # noqa: BLE001 -- Conv #74
        print(f"  ⚠ open-house sync: RETS login failed ({type(e).__name__}: {e}) -- skipping", file=sys.stderr)
        return 0

    print("Login OK")
    print("")
    print("=== open-house ===")

    today = _dt.date.today().isoformat()
    query = f"(OpenHouseDate={today}+)"
    print(f"  resource: OpenHouse")
    print(f"  query: {query}")

    all_events = []
    try:
        for row in mod.search_paginated(session, caps, resource="OpenHouse",
                                         class_name="OpenHouse", query=query,
                                         fields=None, verbose=args.verbose):
            all_events.append(row)
    except SystemExit:
        print("  ✗ OpenHouse search failed", file=sys.stderr)
        try:
            mod.rets_logout(session, caps)
        except Exception:  # noqa: BLE001
            pass
        return 0
    except Exception as e:  # noqa: BLE001 -- Conv #74
        print(f"  ✗ OpenHouse search errored ({type(e).__name__}: {e})", file=sys.stderr)
        try:
            mod.rets_logout(session, caps)
        except Exception:  # noqa: BLE001
            pass
        return 0

    print(f"  fetched: {len(all_events):,} open-house event(s) from server")

    # Convention #68 -- dump the real field set every run (cheap, and the
    # only way to notice a vendor schema drift before a parse silently
    # starts returning nothing).
    if all_events:
        sample = all_events[0]
        print(f"  first-record keys ({len(sample)}): {sorted(sample.keys())}")
        if args.verbose:
            print(f"  first-record sample: {dict(list(sample.items())[:12])}")

    if args.probe:
        try:
            mod.rets_logout(session, caps)
        except Exception:  # noqa: BLE001
            pass
        print("")
        print("✓ Probe complete -- nothing written.")
        return 0

    horizon_days = 30  # generous window; renderer applies its own tighter
    # "upcoming" cutoff at build time (Conv #21 -- keep the cache a superset,
    # let the consumer decide what's still relevant by the time it renders).
    horizon = (_dt.date.today() + _dt.timedelta(days=horizon_days)).isoformat()

    by_mui: dict[str, list] = {}
    kept = 0
    for oh in all_events:
        if str(oh.get("ActiveYN") or "") != "1":
            continue
        if (oh.get("OpenHouseType") or "Public") != "Public":
            continue
        date_s = (oh.get("OpenHouseDate") or "")[:10]
        if not date_s or date_s > horizon:
            continue
        mui = str(oh.get("Listing_MUI") or "").strip()
        if not mui:
            continue
        by_mui.setdefault(mui, []).append({
            "date": date_s,
            "start_time": oh.get("StartTime") or "",
            "end_time": oh.get("EndTime") or "",
            "type": oh.get("OpenHouseType") or "Public",
        })
        kept += 1

    for mui in by_mui:
        by_mui[mui].sort(key=lambda e: (e["date"], e["start_time"]))

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CACHE_DIR / "open-houses.json"
    out_path.write_text(json.dumps({
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "pull_type": "open-house",
        "event_count": kept,
        "listing_count": len(by_mui),
        "by_mui": by_mui,
    }, indent=2, default=str), encoding="utf-8")

    print(f"  kept: {kept:,} public/active/upcoming event(s) across {len(by_mui):,} listing(s)")
    print(f"  written: {out_path.relative_to(SCRIPT_DIR.parent)} ({out_path.stat().st_size:,} bytes)")

    try:
        mod.rets_logout(session, caps)
    except Exception:  # noqa: BLE001
        pass

    print("")
    print("✓ Open-house sync complete.")
    if args.json:
        print(json.dumps({"event_count": kept, "listing_count": len(by_mui)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
