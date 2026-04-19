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

This is intentionally more lenient than the Turner-brand check used on
realestategander-site/goosebay-site. The site-specific design-system
assertions (contrast tokens, H2 size, hover colors, nav class pattern)
are out of scope here because these sites don't share those tokens.
"""

import os
import re
import sys
import glob

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(SITE, "pages")

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
