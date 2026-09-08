#!/usr/bin/env python3
"""regions_check.py -- sanity checks on tools/regions.json (fleet canonical).

Run standalone (`python3 tools/regions_check.py`) or imported and called from
fleet-check.py. Exits 1 with a printed reason on the first failure (Convention
#97 verbose-on-failure) rather than a bare assert, since this is meant to run
in CI where the only feedback is the log.

Checks (fleet-review Part C prerequisite, 2026-09-08):
  1. Region keys match their own `territory` field.
  2. Every postal_prefixes collision across regions has a documented
     _ambiguous_prefixes resolution (so a NEW collision can't ship silently).
  3. Every live + turner-operated region carries the fields a real consumer
     needs: site_id, r2_slug, repo_dir, site_key, domain, office_key.
  4. Every region has a non-empty label and nav_label.
  5. towns[] is present (may be empty only for a region with no known
     geography yet -- but must exist as a key, never silently absent).
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

REGIONS_PATH = Path(__file__).resolve().parent / "regions.json"


def load():
    return json.loads(REGIONS_PATH.read_text(encoding="utf-8"))


def check(data, verbose=False):
    errors = []
    regions = data.get("regions", {})
    ambiguous = data.get("_ambiguous_prefixes", {})

    # 1. key == territory
    for key, r in regions.items():
        if r.get("territory") != key:
            errors.append(f"region '{key}': territory field is {r.get('territory')!r}, expected {key!r}")

    # 2. postal_prefixes collisions must be documented
    claims = defaultdict(list)
    for key, r in regions.items():
        for prefix in r.get("postal_prefixes") or []:
            claims[prefix].append(key)
    for prefix, keys in claims.items():
        if len(keys) > 1 and prefix not in ambiguous:
            errors.append(
                f"postal prefix {prefix!r} is claimed by {keys} with no "
                f"_ambiguous_prefixes entry -- add a resolution before shipping"
            )
        if prefix in ambiguous:
            claimed_by = set(ambiguous[prefix].get("claimed_by") or [])
            if claimed_by != set(keys):
                errors.append(
                    f"_ambiguous_prefixes[{prefix!r}].claimed_by {sorted(claimed_by)} "
                    f"doesn't match the regions that actually list it {sorted(keys)}"
                )

    # 3. live + turner regions need the real consumer fields
    required_for_live_turner = ["site_id", "r2_slug", "repo_dir", "site_key", "domain", "office_key"]
    for key, r in regions.items():
        if r.get("state") == "live" and r.get("operator") == "turner":
            for field in required_for_live_turner:
                if not r.get(field):
                    errors.append(f"region '{key}' is live+turner but missing '{field}'")

    # 4. labels
    for key, r in regions.items():
        if not (r.get("label") or "").strip():
            errors.append(f"region '{key}' has an empty label")
        if not (r.get("nav_label") or "").strip():
            errors.append(f"region '{key}' has an empty nav_label")

    # 5. towns[] key must exist
    for key, r in regions.items():
        if "towns" not in r:
            errors.append(f"region '{key}' has no towns[] key at all (empty list is fine, absent is not)")

    if verbose:
        print(f"[regions_check] {len(regions)} region(s) checked, {len(errors)} error(s)")
    return errors


def main():
    verbose = "--verbose" in sys.argv
    try:
        data = load()
    except Exception as exc:
        print(f"[regions_check] FAILED to load {REGIONS_PATH}: {exc}", file=sys.stderr)
        return 1
    errors = check(data, verbose=verbose)
    if errors:
        print(f"[regions_check] {len(errors)} problem(s) in {REGIONS_PATH}:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"[regions_check] OK -- {len(data.get('regions', {}))} region(s), 0 problems")
    return 0


if __name__ == "__main__":
    sys.exit(main())
