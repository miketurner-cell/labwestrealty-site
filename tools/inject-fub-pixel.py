#!/usr/bin/env python3
"""
Turner Realty — Follow Up Boss Pixel Injector
==============================================
Idempotently inject the Follow Up Boss visitor-tracking pixel into the
<head> of every real page on the current site.

Why static injection into every page (not just a few):
    The FUB pixel ("who visited your site recently and what they did") only
    has value if it sees the full visitor journey — homepage, listing pages,
    community pages, sold rollups, everything. Same principle as GA4, which
    is why FUB's own instructions say to paste it "the same place as Google
    Analytics." Unlike GA4 there is no per-site ID — one FUB account, one
    pixel ID, same literal script on all 5 sites (Mike's FUB account tracks
    the whole fleet).

Scope:
    All *.html under the site root, excluding:
      - tools/               (developer scripts, templates, generator output previews)
      - netlify/              (edge functions)
      - node_modules/         (defensive)
      - ddf-cache/            (raw feed cache, not served)
      - any dotfile directory (.git, .netlify, .github, etc.)
      - any "_*.html"         (partials / fragments, included into other pages)

Placement rule (per-page):
    Inject just before </head> (case-insensitive match, canonical casing
    written back). Pages with no <head>...</head> at all are partials that
    slipped past the filename filter — skipped, not treated as an error.

Idempotency:
    Looks for the sentinel comment `<!-- fub-pixel:v1 -->`.
    If present and the body matches the canonical version → unchanged.
    If present but drifted (e.g. a future pixel-ID rotation) → updated in place.
    If absent → inserted.

Usage:
    python3 tools/inject-fub-pixel.py             # dry-run summary (default)
    python3 tools/inject-fub-pixel.py --apply     # actually write changes
    python3 tools/inject-fub-pixel.py --remove    # rollback (strip the block)
    python3 tools/inject-fub-pixel.py --json      # machine-readable summary

Exit:
    0 = no errors (no-head pages are not errors); non-zero = a write error.

Author: Claude · Date: 2026-09-12
Follows the tools/inject-crea-footer.py pattern (Convention #15 canonical
tooling): self-contained, byte-identical across all 5 sites (no per-site
NAP needed here — the pixel snippet never varies by site).
"""

import argparse
import json
import os
import re
import sys

# ═══════════════════════════════════════════════════════════════════════════
# Follow Up Boss Pixel — account: royallepage545. Fleet-wide, one ID for all
# 5 sites. Copied verbatim from the FUB admin UI (Admin → Website Tracking →
# Pixel → Tracking tab) 2026-09-12. Do not hand-edit the tracker ID here —
# if FUB ever rotates it, paste the new snippet from that page and re-run
# with --apply (the sentinel makes this idempotent-safe).
# ═══════════════════════════════════════════════════════════════════════════
PIXEL_BODY = (
    '<!-- begin Widget Tracker Code -->\n'
    '<script>\n'
    '(function(w,i,d,g,e,t){w["WidgetTrackerObject"]=g;(w[g]=w[g]||function() '
    '{(w[g].q=w[g].q||[]).push(arguments);}),(w[g].ds=1*new Date());(e="script"), '
    '(t=d.createElement(e)),(e=d.getElementsByTagName(e)[0]);t.async=1;t.src=i; '
    'e.parentNode.insertBefore(t,e);}) (window,"https://widgetbe.com/agent",document,"widgetTracker"); '
    'window.widgetTracker("create", "WT-ZOUGZFEJ"); window.widgetTracker("send", "pageview");\n'
    '</script>\n'
    '<!-- end Widget Tracker Code -->'
)

SENTINEL_OPEN = "<!-- fub-pixel:v1 -->"
SENTINEL_CLOSE = "<!-- /fub-pixel:v1 -->"

# Directories to skip wholesale during the recursive scan. Dotfile dirs
# (.git, .netlify, .github, ...) are pruned separately, unconditionally.
SKIP_DIRS = {"tools", "netlify", "node_modules", "ddf-cache"}

# Filename patterns to skip (partials, embeds included into other pages).
SKIP_FILE_RE = re.compile(r"^_")

HEAD_CLOSE_RE = re.compile(r"</head\s*>", re.IGNORECASE)


def canonical_block() -> str:
    return SENTINEL_OPEN + "\n" + PIXEL_BODY + "\n" + SENTINEL_CLOSE


EXISTING_BLOCK_RE = re.compile(
    re.escape(SENTINEL_OPEN) + r".*?" + re.escape(SENTINEL_CLOSE),
    re.DOTALL,
)


def find_html_files(site_root: str):
    """Yield absolute paths to .html files within scope."""
    for root, dirs, files in os.walk(site_root):
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
    one of: "inserted", "updated", "unchanged", "no-head".
    """
    if SENTINEL_OPEN in html:
        new_html = EXISTING_BLOCK_RE.sub(lambda _m: block, html, count=1)
        if new_html == html:
            return html, "unchanged"
        return new_html, "updated"

    m = None
    for m in HEAD_CLOSE_RE.finditer(html):
        pass  # walk to the last match
    if m is None:
        return html, "no-head"

    idx = m.start()
    new_html = html[:idx] + block + "\n" + html[idx:]
    return new_html, "inserted"


def remove_block(html: str):
    """Strip the sentinel block. Used by --remove for rollback."""
    if SENTINEL_OPEN not in html:
        return html, "unchanged"
    new_html = EXISTING_BLOCK_RE.sub("", html, count=1)
    new_html = re.sub(r"\n{3,}", "\n\n", new_html)
    return new_html, "removed"


def detect_site_root() -> str:
    """The script lives in <site>/tools/ — site root is one dir up."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(
        description="Inject Follow Up Boss pixel into every page's <head>.",
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
    block = canonical_block()

    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "removed": 0,
              "no-head": 0, "skipped": 0}
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
        print(f"FUB pixel injection — site: {site_name}")
        print(f"Mode:   {summary['mode']}")
        print(f"Counts: {counts}")
        if counts["no-head"] > 0:
            print("\nPages with no <head>...</head> (skipped, not an error):")
            for f in per_file:
                if f["status"] == "no-head":
                    print(f"  - {f['path']}")
        if not args.apply and not args.remove:
            changes = counts["inserted"] + counts["updated"]
            if changes > 0:
                print(f"\n→ {changes} file(s) would change. Re-run with --apply to write.")

    sys.exit(1 if counts["skipped"] > 0 else 0)


if __name__ == "__main__":
    main()
