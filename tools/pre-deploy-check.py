#!/usr/bin/env python3
"""
Pre-Deploy Quality Check (lean profile)
========================================
Portable version for sites that don't share the realestategander/goosebay
design system. Focus: CREA Rule 6(c) enforcement + universal basics.

Usage:  python3 tools/pre-deploy-check.py
Exit:   0 = all clear, 1 = ERRORs found

Checks:
  1. CREA compliance block (ERROR) — Rule 6(c)(i)/(ii). Every non-partial
     .html must carry the sentinel <!-- crea-compliance:v1 --> OR an
     lst-ddr DDF detail block.
  2. Meta tags (ERROR/WARN) — title, description, og:*.
  3. Footer present (ERROR) — <footer> tag or footer.js include.
  4. Broken internal links (ERROR) — href targets that don't resolve.
  5. Nav present (WARN) — any class containing "nav".
  6. Placeholder content (WARN) — visible "PLACEHOLDER", "lorem ipsum".
  7. Missing local images (WARN) — relative src paths that don't resolve.
  8. Asset refs resolve to tracked files (ERROR) — <link rel="stylesheet" href>
     and <script src> must point to files that exist on disk AND are tracked
     in git. Catches the "file on disk but forgotten in git add" / path-typo
     failure mode that 404s assets on Netlify. Precedent: 2026-04-22 Goosebay
     js/js/rechat-forms.js typo on 32 pages + css/turner-network.css untracked
     on 3 sites broke the footer strip render. Project-wide this is "Check #10"
     per CLAUDE.md Convention #14; numbered #8 here because this lean profile
     has only 7 pre-existing checks.

This is intentionally more lenient than the Turner-brand check used on
realestategander-site/goosebay-site. The site-specific design-system
assertions (contrast tokens, H2 size, hover colors, nav class pattern)
are out of scope here because these sites don't share those tokens.
"""

import os
import re
import subprocess
import sys
import glob

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(SITE, "pages")

# ═══════════════════════════════════════════
# CHECK #8 — ASSET REFERENCE HELPERS
# (project-wide this is "Check #10" per CLAUDE.md Convention #14;
#  numbered #8 here because this lean profile has only 7 other checks)
# ═══════════════════════════════════════════
ASSET_REF_RE = re.compile(
    r'<(?:link\s+[^>]*?href|script\s+[^>]*?src)\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_EXTERNAL_PREFIXES = (
    "http://", "https://", "//", "data:",
    "mailto:", "tel:", "javascript:", "#",
)


def _load_tracked_files():
    """Return the set of git-tracked paths (relative to SITE), or None if git
    is unavailable / this isn't a repo. Called once before the main loop."""
    try:
        out = subprocess.check_output(
            ["git", "-C", SITE, "ls-files"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    return set(out.splitlines())


TRACKED_FILES = _load_tracked_files()

html_files = sorted(
    glob.glob(os.path.join(SITE, "*.html")) +
    glob.glob(os.path.join(PAGES, "*.html"))
)

total_errors = 0
total_warnings = 0
results = {}


def add_issue(filename, severity, message):
    global total_errors, total_warnings
    if filename not in results:
        results[filename] = []
    results[filename].append((severity, message))
    if severity == "ERROR":
        total_errors += 1
    else:
        total_warnings += 1


for filepath in html_files:
    fname = os.path.basename(filepath)
    relpath = os.path.relpath(filepath, SITE)

    # Skip partials (filename starts with "_")
    if fname.startswith("_"):
        continue

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Internal tools are explicitly marked robots-noindex. They're outside
    # the public-page quality gate (no SEO meta, no site footer, no nav
    # required) but still must carry the CREA trademark block if they show
    # any listing/MLS data — so we enforce check #1 on them anyway, safely,
    # since the injector is sentinel-gated and idempotent.
    is_internal_tool = re.search(
        r'<meta\s+name="robots"\s+content="[^"]*noindex',
        content, re.I
    ) is not None

    # ── 1. CREA COMPLIANCE BLOCK (Rule 6(c)(i)/(ii)) ──
    if 'crea-compliance:v1' not in content and 'class="lst-ddr"' not in content:
        add_issue(relpath, "ERROR",
                  "Missing CREA trademark/disclaimer block "
                  "(Rule 6(c)(i)) — run tools/inject-crea-footer.py --apply")

    # Internal tools skip the rest of the public-page quality checks.
    if is_internal_tool:
        continue

    # ── 2. META TAGS ──
    if '<title>' not in content or '</title>' not in content:
        add_issue(relpath, "ERROR", "Missing <title> tag")
    if 'meta name="description"' not in content:
        add_issue(relpath, "ERROR", "Missing meta description")
    if 'og:title' not in content:
        add_issue(relpath, "WARN", "Missing og:title meta tag")
    if 'og:description' not in content:
        add_issue(relpath, "WARN", "Missing og:description meta tag")

    # ── 3. FOOTER PRESENT ──
    has_footer = (
        re.search(r'<footer\b', content) is not None or
        'footer.js' in content
    )
    if not has_footer:
        add_issue(relpath, "ERROR", "Missing footer (neither <footer> tag nor footer.js)")

    # ── 4. BROKEN INTERNAL LINKS ──
    for match in re.finditer(r'href="([^"#]*\.html)"', content):
        href = match.group(1)
        if href.startswith("http") or href.startswith("mailto") or href.startswith("tel"):
            continue
        file_dir = os.path.dirname(filepath)
        target = os.path.normpath(os.path.join(file_dir, href))
        if not os.path.exists(target):
            add_issue(relpath, "ERROR", f"Broken link: {href}")

    # ── 5. NAV PRESENT (lenient) ──
    has_nav = re.search(r'class="[^"]*\bnav\b[^"]*"', content) is not None or \
              re.search(r'<nav\b', content) is not None
    if not has_nav:
        add_issue(relpath, "WARN", "No nav element or class detected")

    # ── 6. PLACEHOLDER CONTENT ──
    for m in re.finditer(r'(?i)(lorem ipsum)', content):
        add_issue(relpath, "WARN", f"Placeholder content: '{m.group(1)}'")
    for m in re.finditer(r'PLACEHOLDER', content):
        start = max(0, m.start() - 60)
        ctx = content[start:m.end() + 20]
        if re.search(r'alt="[^"]*PLACEHOLDER|>.*PLACEHOLDER', ctx):
            add_issue(relpath, "WARN", "Visible PLACEHOLDER text in page content")
            break

    # ── 7. MISSING LOCAL IMAGES ──
    for match in re.finditer(r'src="(\.\./images/[^"]+|images/[^"]+|\./images/[^"]+)"', content):
        src = match.group(1)
        file_dir = os.path.dirname(filepath)
        target = os.path.normpath(os.path.join(file_dir, src))
        if not os.path.exists(target):
            add_issue(relpath, "WARN", f"Missing image: {src}")

    # ── 8. ASSET REFS RESOLVE TO TRACKED FILES ──
    # Every <link rel="stylesheet" href="..."> and <script src="..."> must
    # point to a file that exists on disk AND is tracked in git. Otherwise
    # Netlify serves a 404 for the asset on deploy and the page renders
    # broken (unstyled footer, dead JS widget, etc.) — a silent-break failure
    # mode because the HTML itself still returns 200.
    # Precedent (2026-04-22): Goosebay js/js/rechat-forms.js typo silently 404d
    # the inquiry form on 32 pages (f900dc4); css/turner-network.css untracked
    # on 3 sites → footer strip rendered unstyled.
    # Skip if git is unavailable (e.g., tarball install, CI setup issue).
    if TRACKED_FILES is not None:
        file_dir = os.path.dirname(filepath)
        for m in ASSET_REF_RE.finditer(content):
            url = m.group(1).split("?", 1)[0].split("#", 1)[0].strip()
            if not url or url.lower().startswith(_EXTERNAL_PREFIXES):
                continue
            if url.startswith("/"):
                asset_abs = os.path.normpath(os.path.join(SITE, url.lstrip("/")))
            else:
                asset_abs = os.path.normpath(os.path.join(file_dir, url))
            if not asset_abs.startswith(SITE):
                continue
            rel_to_site = os.path.relpath(asset_abs, SITE)
            if not os.path.exists(asset_abs):
                add_issue(relpath, "ERROR",
                          f"Asset missing on disk: {url} → {rel_to_site}")
            elif rel_to_site not in TRACKED_FILES:
                add_issue(relpath, "ERROR",
                          f"Asset untracked in git: {url} → {rel_to_site} "
                          "— will 404 on deploy ('git add' the file to fix)")


# ═══════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════
print("=" * 70)
print("PRE-DEPLOY QUALITY CHECK (lean profile)")
print("=" * 70)
print(f"Scanned: {len(html_files)} HTML files")
print(f"Errors: {total_errors}  |  Warnings: {total_warnings}")

if not results:
    print("\n  ✅ ALL CLEAR — No issues detected. Safe to deploy.")
    sys.exit(0)

for relpath in sorted(results.keys()):
    issues = results[relpath]
    errors = [i for i in issues if i[0] == "ERROR"]
    warns = [i for i in issues if i[0] == "WARN"]

    print(f"\n{'─' * 70}")
    print(f"  {relpath}  ({len(errors)} errors, {len(warns)} warnings)")
    for severity, msg in issues:
        icon = "❌" if severity == "ERROR" else "⚠️"
        print(f"    {icon} {msg}")

print(f"\n{'=' * 70}")
if total_errors > 0:
    print(f"❌ DEPLOY BLOCKED — {total_errors} error(s) must be fixed first.")
    sys.exit(1)
else:
    print(f"⚠️  {total_warnings} warning(s) found — review recommended but deploy OK.")
    sys.exit(0)
