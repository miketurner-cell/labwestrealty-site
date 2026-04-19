#!/usr/bin/env python3
"""
Turner Realty — CREA Compliance Footer Injector
================================================
Idempotently inject the CREA-required MLS®/REALTOR® trademark statement and
brokerage identification block (DDF Rule 6(c)(i) + 6(c)(ii)) into every
marketing-page .html on the current site.

Why static injection (vs runtime JS):
    Rule 6(c)(i) says "every page must display." Static HTML survives JS
    failures, runs without script execution, and can be enforced by the
    pre-deploy check. The DDF detail pages already follow this pattern
    (`lst-ddr` block), so this brings marketing pages to parity.

Scope:
    All *.html under the site root, excluding:
      - listings/            (DDF detail pages have their own lst-ddr block)
      - tools/               (developer scripts and HTML previews)
      - netlify/             (edge functions)
      - node_modules/        (defensive)
      - any "_*.html"        (partials / fragments)

Placement rule (per-page):
    1. If page has a closing </footer>, inject just before it.
    2. Else if page has a closing </body>, inject just before it.
    3. Else: skip with error (malformed page).

Idempotency:
    Looks for the sentinel comment `<!-- crea-compliance:v1 -->`.
    If present and the body matches the canonical version → unchanged.
    If present but drifted → updated in place.
    If absent → inserted.

Usage:
    python3 tools/inject-crea-footer.py             # dry-run summary (default)
    python3 tools/inject-crea-footer.py --apply     # actually write changes
    python3 tools/inject-crea-footer.py --remove    # rollback (strip the block)
    python3 tools/inject-crea-footer.py --json      # machine-readable summary

Exit:
    0 = no errors; non-zero = at least one malformed page or write error.

Author: Claude · Date: 2026-04-19
Closes audit gap: DDF Rule 6(c)(i) on marketing pages.
"""

import argparse
import json
import os
import re
import sys

# ═══════════════════════════════════════════════════════════════════════════
# PER-SITE NAP (Name + Address + Phone) — used in the trademark block.
# Detected from the site root directory name. Add a new entry when wiring
# this script into another site.
# ═══════════════════════════════════════════════════════════════════════════
SITE_NAP = {
    "realestategander-site":  "Royal LePage Turner Realty (2014) Inc., 204 Airport Boulevard, Gander, NL A1V 1L6",
    "goosebay-site":          "Royal LePage Turner Realty (2014) Inc., 371 Hamilton River Road, Suite 102, Happy Valley-Goose Bay, NL A0P 1C0",
    "labwestrealty-site":     "Royal LePage Turner Realty (2014) Inc.",
    "royallepageturner-site": "Royal LePage Turner Realty (2014) Inc., 204 Airport Boulevard, Gander, NL A1V 1L6",
    # stjohns-site: Mike confirmed brokerage-line-only posture 2026-04-19
    # (same as labwestrealty-site). No per-office NAP for Avalon at this time.
    "stjohns-site":           "Royal LePage Turner Realty (2014) Inc.",
}

SENTINEL_OPEN  = "<!-- crea-compliance:v1 -->"
SENTINEL_CLOSE = "<!-- /crea-compliance:v1 -->"

# Directories to skip wholesale during the recursive scan.
SKIP_DIRS = {"listings", "tools", "netlify", "node_modules", ".git", "ddf-cache"}

# Filename patterns to skip (partials, embeds).
SKIP_FILE_RE = re.compile(r"^_")


def canonical_block(site_nap: str) -> str:
    """Return the canonical compliance block, with site NAP substituted."""
    return (
        SENTINEL_OPEN + "\n"
        '<aside class="crea-compliance" role="contentinfo" aria-label="REALTOR and MLS trademark statement">\n'
        '  <p>The information contained on this page is based in whole or in part on information '
        'that is provided by members of The Canadian Real Estate Association, who are responsible '
        'for its accuracy. CREA reproduces and distributes this information as a service for its '
        f'members and assumes no responsibility for its accuracy. {site_nap} is a member of '
        'The Canadian Real Estate Association.</p>\n'
        '  <p>REALTOR®, REALTORS®, and the REALTOR® logo are certification marks owned or '
        'controlled by The Canadian Real Estate Association (CREA) and identify real estate '
        'professionals who are members of CREA. The trademarks MLS®, Multiple Listing Service®, '
        'and the associated logos identify professional services rendered by REALTOR® members of '
        'CREA to effect the purchase, sale and lease of real estate as part of a cooperative '
        'selling system.</p>\n'
        '</aside>\n'
        + SENTINEL_CLOSE
    )


# Regex that matches an existing block and everything between the sentinels.
EXISTING_BLOCK_RE = re.compile(
    re.escape(SENTINEL_OPEN) + r".*?" + re.escape(SENTINEL_CLOSE),
    re.DOTALL,
)


def find_html_files(site_root: str):
    """Yield absolute paths to .html files within scope."""
    for root, dirs, files in os.walk(site_root):
        # Prune skipped dirs in place so os.walk doesn't descend into them.
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            if not fname.endswith(".html"):
                continue
            if SKIP_FILE_RE.match(fname):
                continue
            yield os.path.join(root, fname)


def inject_or_update(html: str, block: str):
    """
    Apply the block to the html. Returns (new_html, status) where status is
    one of: "inserted", "updated", "unchanged", "malformed".
    """
    if SENTINEL_OPEN in html:
        # Already present — replace if drifted, otherwise unchanged.
        new_html = EXISTING_BLOCK_RE.sub(block.replace("\\", "\\\\"), html, count=1)
        # Note: re.sub treats backslashes in the replacement specially. Our
        # canonical block contains none, but we escape defensively.
        if new_html == html:
            return html, "unchanged"
        return new_html, "updated"

    # Insertion point: prefer just before </footer>, fall back to </body>.
    for anchor in ("</footer>", "</body>"):
        idx = html.rfind(anchor)
        if idx != -1:
            new_html = html[:idx] + block + "\n" + html[idx:]
            return new_html, "inserted"

    return html, "malformed"


def remove_block(html: str):
    """Strip the sentinel block. Used by --remove for rollback."""
    if SENTINEL_OPEN not in html:
        return html, "unchanged"
    new_html = EXISTING_BLOCK_RE.sub("", html, count=1)
    # Tidy up any double newlines we left behind.
    new_html = re.sub(r"\n{3,}", "\n\n", new_html)
    return new_html, "removed"


def detect_site_root() -> str:
    """The script lives in <site>/tools/ — site root is one dir up."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(
        description="Inject CREA compliance footer block into marketing pages.",
        epilog="Run with no flags for a dry-run summary; add --apply to write.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Write changes to disk (default: dry-run report only).")
    parser.add_argument("--remove", action="store_true",
                        help="Strip the block instead of injecting it (rollback).")
    parser.add_argument("--json", action="store_true",
                        help="Emit a JSON summary instead of human-readable output.")
    parser.add_argument("--site-root", default=None,
                        help="Override site root (default: parent of tools/ dir).")
    args = parser.parse_args()

    if args.apply and args.remove:
        print("ERROR: --apply and --remove are mutually exclusive.", file=sys.stderr)
        sys.exit(2)

    site_root = args.site_root or detect_site_root()
    site_name = os.path.basename(os.path.normpath(site_root))

    if site_name not in SITE_NAP:
        print(f"ERROR: site '{site_name}' has no SITE_NAP entry. "
              f"Add it to inject-crea-footer.py before running.", file=sys.stderr)
        sys.exit(2)

    block = canonical_block(SITE_NAP[site_name])

    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "removed": 0,
              "malformed": 0, "skipped": 0}
    per_file = []

    for path in find_html_files(site_root):
        rel = os.path.relpath(path, site_root)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                html = fh.read()
        except Exception as exc:
            counts["skipped"] += 1
            per_file.append({"path": rel, "status": "skipped", "reason": str(exc)})
            continue

        if args.remove:
            new_html, status = remove_block(html)
        else:
            new_html, status = inject_or_update(html, block)

        counts[status] = counts.get(status, 0) + 1
        per_file.append({"path": rel, "status": status})

        if status in ("inserted", "updated", "removed") and args.apply:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new_html)

    summary = {
        "site": site_name,
        "site_root": site_root,
        "mode": "remove" if args.remove else ("apply" if args.apply else "dry-run"),
        "counts": counts,
        "files": per_file,
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"CREA-compliance footer injection — site: {site_name}")
        print(f"Mode:   {summary['mode']}")
        print(f"Counts: {counts}")
        if counts["malformed"] > 0:
            print("\nMalformed pages (no </footer> or </body> found):")
            for f in per_file:
                if f["status"] == "malformed":
                    print(f"  - {f['path']}")
        if not args.apply and not args.remove:
            changes = counts["inserted"] + counts["updated"]
            if changes > 0:
                print(f"\n→ {changes} file(s) would change. Re-run with --apply to write.")

    # Exit non-zero on any malformed page.
    sys.exit(1 if counts["malformed"] > 0 else 0)


if __name__ == "__main__":
    main()
