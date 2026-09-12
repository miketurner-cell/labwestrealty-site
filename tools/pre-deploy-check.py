#!/usr/bin/env python3
"""
Turner Realty — Pre-Deploy Quality Check
=========================================
Run before every Netlify deploy to catch issues before they go live.

FLEET-CANONICAL (2026-09-12): this file is fleet/canonical/tools/pre-deploy-check.py,
config-injected per site via fleet/manifest.json (not a --profile CLI flag — 2 of 5
sites have no CI workflow to pass one from). The design-token checks (contrast, H2
size, hover color, community-page coverage) run only when the injected
PREDEPLOY_PROFILE constant is "full"; every other check is already self-gating (it
no-ops when the file/dir it depends on is absent) and needs no profile flag at all.
See fleet/config/<site>.json for what each site injects.

Usage:
  python3 tools/pre-deploy-check.py                    # full site
  python3 tools/pre-deploy-check.py --scope listings/  # only listings/
  python3 tools/pre-deploy-check.py --include '*.html' --exclude 'lp-*'
  python3 tools/pre-deploy-check.py --warn-only        # never exit non-zero
  python3 tools/pre-deploy-check.py --json             # machine-readable output

Exit:   0 = all clear (or --warn-only), 1 = errors found

Checks (per-file, run inside the main loop):
  1. Contrast — dark text on dark bg (scope-aware), white cards, dim body text
  2. Placeholder content — "placeholder", "lorem ipsum", "TODO"
  3. Meta tags — title, description, OG tags on every page
  4. Nav + footer — every page has standard site-nav and footer
  5. Broken internal links — href targets that don't exist
  6. Missing local images — ../images/ src paths that don't resolve
  7. Design system — H2 size matches clamp(26px, 4vw, 38px)
  8. Hover colors — hover backgrounds match design system palette
  9. CREA trademark/disclaimer block (Rule 6(c)(i)) — v1 sentinel or lst-ddr
 10. Asset refs resolve to tracked files — <link rel="stylesheet" href="..."> and
     <script src="..."> must point to files that exist on disk AND are tracked
     in git. Catches the "file on disk but forgotten in git add" failure mode
     that 404s assets on Netlify deploy. Precedent: 2026-04-22 css/turner-network.css
     untracked on 3 sites (Gander, Avalon, Labwest) broke the footer strip render.

Check (whole-site scan, run after the loop):
 11. RealtyVis surface drift — warns (non-blocking) when new RV mounts
     appear that aren't in .rv-surfaces.allowed. Protects the active-IDX
     → DDF migration from accidental regrowth.

Check (per-file, run inside the main loop):
 13. Agent-photo aspect-ratio bug — flags <img> with inline width="N"
     height="M" attributes inside a wrapper class whose CSS rule sets
     aspect-ratio on the descendant img selector but is missing
     `height: auto`. HTML Presentational Hints block aspect-ratio
     resolution, tower-stretching the photo at render time.
     Precedent: task #171 (pages/about.html .ab-agent-photo-wrap img,
     8 cards 272x1920 instead of 272x362, fixed at 477fe1a) and task
     #175 (pages/property-management.html .pm-crystal-photo-wrap img,
     fixed at c156685). One-line fix: add `height: auto` to the img CSS
     ruleset.
     Note: Check #12 number is reserved for the testimonials-canonical
     check landing under task #156.

Check (whole-site scan, run after the loop):
 14. Pre-publish SEO gate — title length, meta description length, H1
     count, <img> alt coverage, canonical URL, Open Graph image. Runs
     as WARNING-only per Convention #19 until baseline-clean is
     confirmed and rules promote to ERROR per the design spec.
     Design spec: _research/Check14_SEO_Gate_Design_Spec_2026-04-28.md

Check (whole-site scan, run after the loop):
 15. JSON-LD AggregateRating canonical-drift — Convention #32 + #45
     enforcement. Walks every <script type="application/ld+json">
     block, extracts any AggregateRating object, and compares
     ratingValue + ratingCount + reviewCount against the canonical
     numbers in tools/tt-fragments/emit-manifest.json. Strict equality
     after rounding ratingValue to 2 decimals. WARN (not the ERROR Gander's
     own pre-canonicalization copy used) at the 2026-09-12 canonicalization --
     Avalon's and Goose Bay's own pre-existing copies were both already WARN
     here and Goose Bay's real baseline has live, uncorrected drift today
     (caught by the Phase-1 dry-run) -- promoting straight to ERROR would
     have started hard-blocking its deploys for a pre-existing condition,
     contradicting Convention #19's own "WARN until confirmed-clean, then
     promote" discipline. Revisit once every full site's baseline is clean.
     Sites without TestimonialTree integration (no emit-manifest.json
     on disk) skip silently — today: Labwest, RoyalLePageTurner.
     Precedent: 2026-04-29 stale 4.9/330 in index.html JSON-LD shipped
     ~9 days after testimonials canonical landed at 1469e13/4.97/246.
     Design spec: _research/Pre_Deploy_Check_15_16_Design_Spec_2026-04-29.md

Check (per-file, run inside the main loop):
 16. Convention #44 — Netlify URL rewriter font-family pre-check.
     Detects <a> tags with quoted font names in inline styles. Netlify
     mangles `style="font-family:'Raleway',sans-serif"` at deploy time;
     browser parses broken value, font inherits to default serif/italic.
     Workaround: drop quotes around single-word font names.
     Precedent: task #201 (gander.html "Meet the team" link rendered
     serif/italic; fixed at 14e05d3 by dropping quotes). ERROR from
     day one.

Check (per-file, run inside the main loop):
 17. DDF fragment requires ddf-fragment.css link.
     When a file contains a <!-- DDF_FRAGMENT: --> sentinel, assert
     css/ddf-fragment.css is also linked in <head>. The
     .ddf-fragment-grid + .lst-card* rules live ONLY in that file;
     pages with the sentinel but no link render cards as unstyled
     stacked divs (no grid, no card chrome). Canonical Convention #18
     silent-degraded-output: HTTP 200, no CI errors, broken layout.
     Precedent: task #222 — 10 Gander pages shipped without the link
     from Phase 2 Wave A (#184) and Wave B (#194); fixed at 01a885db.
     ERROR from day one (Convention #19 baseline-clean confirmed by
     the #222 fix).

Check (filesystem-walking, runs after per-file loop):
 18. Orphan listing detail page detector.
     Walks listings/<city>/<address>-<MLS>.html files; flags any whose
     MLS is missing from tools/idx-cache/listings-projected.json. The
     existing stale-page sweep in tools/ddf-generate-pages.py catches
     orphans at REGEN time only — hand-edited or hand-created files
     survive between regens. WARNING from day one per Convention #19;
     can promote to ERROR after fleet baseline clean. Sites without a
     projected cache skip LOUDLY, per-reason (Convention #211, fixed
     2026-08-12 — cache_path was pointed at a dead DDF-era file, so
     this check provided zero coverage fleet-wide). Precedent: task
     #226 — MLS 1296533 transient feed drop; this check catches the
     inverse (file persists when cache loses the listing).

Special modes:
  --list-rv-surfaces          Print RealtyVis surface inventory and exit.
  --update-rv-surfaces-allowed  Rewrite .rv-surfaces.allowed from current scan.
"""

import argparse
import ast
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import glob

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(SITE, "pages")


def _fleet_list(raw):
    """Parse a __FLEET_*__ token's substituted text back into a Python list/set
    literal. fleet_lib.expected_content() substitutes a missing/null config key
    with a bare EMPTY STRING (not the text "None") -- so this token must always
    be placed INSIDE quotes in the canonical source (`_raw = "__FLEET_X__"`) and
    parsed here, never bare (`X = __FLEET_X__`), or a missing key produces a
    SyntaxError instead of a graceful empty default. Uses ast.literal_eval (not
    eval) since the substituted text is always a Python repr of a JSON-loaded
    list of plain strings (filenames/slugs), never something needing real code
    execution. Known limitation: a config value containing a literal double-quote
    character would break out of its enclosing `_raw = "..."` string early --
    fine for today's filename/slug values, worth widening if that ever changes."""
    raw = raw.strip()
    if not raw:
        return []
    try:
        return list(ast.literal_eval(raw))
    except (ValueError, SyntaxError):
        return []


def _fleet_int(raw, default):
    """Same rationale as _fleet_list -- parse a quoted __FLEET_*__ token back
    into an int, falling back to `default` on a missing/null/unparseable value."""
    raw = raw.strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _load_community_agent_slugs():
    """Slugs that MUST carry a territory-agent card (Check #24). Source of truth
    is tools/community-agent-map.json; a generated community page (pages/<slug>.html)
    without the card = a silently-dropped territory agent (Convention #18)."""
    try:
        with open(os.path.join(SITE, "tools", "community-agent-map.json")) as f:
            data = json.load(f)
        return set((data.get("communities") or data).keys())
    except Exception:
        return set()


_COMMUNITY_AGENT_SLUGS = _load_community_agent_slugs()

# ═══════════════════════════════════════════
# DESIGN SYSTEM TOKENS
# ═══════════════════════════════════════════
ALLOWED_BG_DARK = {"#0a0a0a", "#111111", "#111", "#1a1a1a", "#1e1e1e", "#222", "#222222"}
ALLOWED_TEXT_LIGHT = {"#fff", "#ffffff", "#ddd", "#dddddd", "#bbb", "#bbbbbb", "#ccc"}
ACCENT_RED = "#EA002A"
HOVER_RED = "#c8001f"

# Allowed hover-background colors (Check #8, full profile only). Confirmed
# byte-identical across Gander/Avalon/Goose Bay (not site-specific, despite
# living in a per-site file historically). Two entries looked, on first read,
# like contamination from an unrelated project -- #1f5c39 and #7f0000
# ("healthcare green, dark red login") -- and were dropped at the 2026-09-12
# canonicalization on that assumption. The Phase-1 dry-run against a real
# tree proved that assumption WRONG for #1f5c39: it's the real, intentional
# hover color on Gander's own pages/healthcare-relocation.html ("Healthcare
# Workers Moving to Gander") -- not contamination, a real per-page accent for
# that specific relocation-marketing theme. Restored. #7f0000 ("dark red
# login") has zero static references anywhere across all 3 full sites'
# pages/ directories -- still dropped, but flag to Mike before treating that
# as settled (a JS-rendered surface this check can't see would be the one
# way it's still legitimate).
ALLOWED_HOVER = {
    '#c8001f', '#ea002a', '#111111', '#1a1a1a', '#222222',  # standard reds + dark
    '#f0f0f0', '#fff', '#ffffff', '#f9fafb',                 # light hover states
    '#242424',                                                # subtle dark card hover
    '#1f5c39',                                                # healthcare-relocation.html accent (confirmed real, restored)
}

# Files to exclude from checks (prototypes, design concepts)
EXCLUDE_FILES = {"nav-concepts.html", "realtyvis-deep-dive.html", "realtyvis-manual-tasks.html", "boldtrail-deep-dive.html"}

# Fleet-canonical profile flag (2026-09-12) -- "full" sites (Gander/Avalon/Goose
# Bay) get the design-token checks (contrast, H2, hover, community coverage);
# "lean" sites (labwest/hub, no listings feed, no shared design tokens) don't.
# Injected from fleet/config/<site>.json's existing predeploy_profile key. A
# missing/null config value substitutes to a bare empty string here (fleet_lib
# maps an absent key to "", not the text "None" -- verified 2026-09-12, same
# safe pattern as the one pre-existing config-inject user, js/address-
# complete.js's key, since the token sits inside quotes), which simply never
# equals "full" below -- i.e. it silently behaves as the narrower "lean" profile.
PREDEPLOY_PROFILE = "lean"

# Internal, agent-gated, noindex tools — NOT consumer-facing MLS surfaces. They
# carry their own minimal chrome and are exempt from the consumer nav/footer/CREA
# trademark checks (the CREA Rule 6(c)(i) block is for public MLS listing display).
# Genuinely per-site (each site's own admin/tool page inventory) -- injected from
# fleet/config/<site>.json's predeploy.internal_tool_pages list. Defaults to empty
# (no exemptions) rather than crashing if the site's config carries none.
INTERNAL_TOOL_PAGES = set(_fleet_list(""))

# ═══════════════════════════════════════════
# CHECK #10 — ASSET REFERENCE HELPERS
# ═══════════════════════════════════════════
# Regex to extract any <link rel="stylesheet" href="..."> or <script src="...">
# Captures the URL value. Case-insensitive to handle mixed-case HTML.
# Covers: <link href>, <script src>, <iframe src>. iframe added 2026-04-29
# after Convention #14 silent-404 on pages/_map-embed.html surfaced 24
# broken pages across Avalon + Gander that the original v1 regex missed
# (#214). All three reference local files via either href or src; the
# regex captures the URL value regardless of attribute name on the
# specific tag. <img src> patterns are intentionally NOT covered here
# (that's Check #6's scope); same for <source src>/<video src>/<audio src>
# which haven't surfaced as a failure mode yet.
ASSET_REF_RE = re.compile(
    r'<(?:link\s+[^>]*?href|script\s+[^>]*?src|iframe\s+[^>]*?src)\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)

# External/protocol prefixes to skip — these aren't our files.
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

# ═══════════════════════════════════════════
# CLI ARGUMENTS
# ═══════════════════════════════════════════
parser = argparse.ArgumentParser(
    description="Turner Realty pre-deploy quality check",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=(
        "Examples:\n"
        "  pre-deploy-check.py --scope listings/         # listings only\n"
        "  pre-deploy-check.py --scope pages/ --exclude 'lp-*'\n"
        "  pre-deploy-check.py --warn-only --json        # CI-friendly\n"
    ),
)
parser.add_argument(
    "--scope",
    action="append",
    default=[],
    metavar="DIR",
    help="Limit to files under this directory (repeatable). Relative to site root.",
)
parser.add_argument(
    "--include",
    action="append",
    default=[],
    metavar="PATTERN",
    help="Only include files whose basename matches glob (repeatable).",
)
parser.add_argument(
    "--exclude",
    action="append",
    default=[],
    metavar="PATTERN",
    help="Skip files whose basename matches glob (repeatable).",
)
parser.add_argument(
    "--warn-only",
    action="store_true",
    help="Always exit 0 — useful when errors are on unrelated pages.",
)
parser.add_argument(
    "--json",
    dest="emit_json",
    action="store_true",
    help="Emit machine-readable JSON summary after the human report.",
)
parser.add_argument(
    "--quiet",
    action="store_true",
    help="Suppress the human-readable report; useful with --json.",
)
parser.add_argument(
    "--list-rv-surfaces",
    action="store_true",
    help="Print RealtyVis surface inventory (data-rv-block + _map-embed.html?wid=) and exit.",
)
parser.add_argument(
    "--update-rv-surfaces-allowed",
    action="store_true",
    help="Rewrite .rv-surfaces.allowed from the current scan. "
         "Use intentionally — opt-in update of the migration baseline.",
)
args = parser.parse_args()

# Build search roots based on --scope. Default = site root + pages/.
if args.scope:
    search_roots = []
    for s in args.scope:
        resolved = os.path.normpath(os.path.join(SITE, s))
        if not resolved.startswith(SITE):
            print(f"ERROR: --scope '{s}' escapes site root", file=sys.stderr)
            sys.exit(2)
        search_roots.append(resolved)
else:
    search_roots = [SITE, PAGES]


def _basename_passes(fname):
    if fname in EXCLUDE_FILES:
        return False
    for pattern in args.exclude:
        if fnmatch.fnmatch(fname, pattern):
            return False
    if args.include:
        if not any(fnmatch.fnmatch(fname, p) for p in args.include):
            return False
    return True


html_files = []
seen = set()
# When --scope is explicit we recurse into the scoped dirs (listings/ has
# subdirs per city). When no --scope is given we preserve the original
# non-recursive scan to avoid a behavior change.
recursive = bool(args.scope)
for root in search_roots:
    if os.path.isfile(root) and root.endswith(".html"):
        candidates = [root]
    elif os.path.isdir(root):
        if recursive:
            candidates = glob.glob(os.path.join(root, "**", "*.html"), recursive=True)
        else:
            candidates = glob.glob(os.path.join(root, "*.html"))
    else:
        candidates = []
    for f in candidates:
        if f in seen:
            continue
        if not _basename_passes(os.path.basename(f)):
            continue
        seen.add(f)
        html_files.append(f)
html_files.sort()

total_issues = 0
total_warnings = 0
results = {}

def add_issue(filename, severity, message):
    global total_issues, total_warnings
    if filename not in results:
        results[filename] = []
    results[filename].append((severity, message))
    if severity == "ERROR":
        total_issues += 1
    else:
        total_warnings += 1


for filepath in html_files:
    fname = os.path.basename(filepath)
    relpath = os.path.relpath(filepath, SITE)

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Light-themed pages (agent bio pages) are self-identifying via the
    # agent-profile template's own body class -- confirmed 2026-09-12 this
    # matches Gander's (already-correct) hardcoded LIGHT_THEME_PAGES set
    # exactly, 8-for-8. A hardcoded per-site filename list was the wrong
    # mechanism: BOTH Avalon's and Goose Bay's old lists were unmodified
    # copy-paste drift from Gander (listing Gander's agents, not their own --
    # dwayne-kean.html/kayla-tulk.html/etc. on sites whose real agents are
    # chris-morrison.html or karen-pomeroy.html/roberta-primmer.html), so the
    # contrast-exemption check was silently running against the wrong page on
    # 2 of 3 full sites. Deriving it from the page's own markup instead of a
    # maintained list fixes both, permanently, fleet-wide.
    is_light_page = 'class="agp-page"' in content

    # Self-deriving internal-tool detection (ported from labwest/hub's own
    # pre-existing, more robust mechanism at the 2026-09-12 canonicalization):
    # any page carrying a noindex robots meta tag is gated/internal by
    # construction, regardless of whether it's also in the per-site
    # INTERNAL_TOOL_PAGES filename list. Gander's hardcoded list alone missed
    # royallepageturner-site's agent-accountability.html (noindex, nofollow,
    # but never added to any list) -- caught by the Phase-1 dry-run, which
    # false-flagged 3 errors on it that the lean file's own check correctly
    # never raised.
    is_internal_tool = re.search(
        r'<meta\s+name="robots"\s+content="[^"]*noindex', content, re.I
    ) is not None

    # Extract style blocks
    style_blocks = '\n'.join(re.findall(r'<style[^>]*>(.*?)</style>', content, re.DOTALL))
    inline_styles = '\n'.join(re.findall(r'style="([^"]*)"', content))
    all_css = style_blocks + '\n' + inline_styles

    # ── 1. CONTRAST CHECKS (full profile only -- skip light-themed pages) ──
    if PREDEPLOY_PROFILE == "full" and not is_light_page and all_css.strip():
        # Build a map of selector → has light/cream/white background.
        # This lets us recognize when dark text is intentionally placed on a
        # light section (e.g., #faq-section-v1 with #fafaf8 background, then
        # #faq-section-v1 h2 with color: #1a1a1a). Without scope awareness the
        # check produces false positives on every light-section heading.
        LIGHT_BG_RE = re.compile(
            r'background(?:-color)?\s*:\s*'
            r'(#fff[a-f0-9]{0,5}\b|#fafa[a-f0-9]{2}\b|#f[5-9a-f][a-f0-9]{4}\b|'
            r'#e[a-f0-9]{5}\b|white\b|rgba?\(\s*2[45][0-9]\s*,)',
            re.I,
        )
        # Naive top-level rule scan — handles direct rules; @media wrappers
        # are unwrapped naturally because the regex requires no inner braces.
        rule_re = re.compile(r'([^{}@][^{}]*?)\{([^{}]*)\}')
        light_bg_selectors = set()
        rule_spans = []  # list of (selector_group, body_start, body_end)
        for rm in rule_re.finditer(all_css):
            selector_group = rm.group(1).strip()
            body = rm.group(2)
            rule_spans.append((selector_group, rm.start(2), rm.end(2)))
            if LIGHT_BG_RE.search(body):
                for sel in selector_group.split(','):
                    light_bg_selectors.add(sel.strip())

        def descends_from_light(selector_group):
            """True if any individual selector in the group descends from a
            selector that declares a light background."""
            for sel in selector_group.split(','):
                sel = sel.strip()
                for light_sel in light_bg_selectors:
                    if not light_sel:
                        continue
                    if sel == light_sel:
                        return True
                    # Descendant via whitespace, child (>), pseudo (:), or
                    # adjacent siblings (+, ~). Class/id chains that EXTEND
                    # the selector (e.g., "#x.y") shouldn't match — those
                    # are different elements, not descendants.
                    for combinator in (' ', '>', '+', '~', ':'):
                        if sel.startswith(light_sel + combinator):
                            return True
            return False

        # Dark text on dark backgrounds.
        # Negative lookbehind on \w- prevents `background-color: #1a1a1a` (a
        # legitimate dark-section *background*) from false-positiving as if it
        # were a `color: #1a1a1a` text declaration. Pre-fix bug surfaced
        # 2026-04-28 — was producing 16 false-positive ERRORs across pages
        # whose dark sections were detected as "invisible text".
        for match in re.finditer(r'(?<![\w-])color:\s*(#0a0a0a|#111111|#1a1a1a|#222222)', all_css):
            # Skip if this color lives inside a scope known to have a light bg.
            in_light_scope = False
            for selector_group, body_start, body_end in rule_spans:
                if body_start <= match.start() <= body_end:
                    if descends_from_light(selector_group):
                        in_light_scope = True
                    break
            if in_light_scope:
                continue
            # Fallback: lookback for border/shadow/light-bg hints. History:
            #   v1 → 80 chars  (initial)
            #   v2 → 600 chars (sibling rules inside same section, e.g.
            #                   `#faq-section-v1 { background: #fafaf8; ... }`
            #                   then `#faq-section-v1 h2 { color: #1a1a1a }`)
            #   v3 → 2000 chars (Convention #15 propagation 2026-04-30 #219:
            #                    Goosebay's CSS structure has wider rule
            #                    spacing — `.ab-hero { background: #f7f7f7 }`
            #                    can be 614 chars from `.ab-hero h1 { color:
            #                    #1a1a1a }` because of intervening
            #                    `.ab-hero-container` + `.ab-hero-eyebrow`
            #                    rules. 600 cut off just before parent rule
            #                    on Goosebay's about/testimonials/etc. pages,
            #                    flagging 40 false positives. 2000 catches 36
            #                    of those. Gander + stjohns flag 0 at any
            #                    distance — their CSS is denser).
            start = max(0, match.start() - 2000)
            ctx = all_css[start:match.end()]
            light_bg_hint = (
                r'border|shadow|'
                r'background[^;]*?(?:#fff|#fafa[a-f0-9]{2}|#f[5-9a-f][a-f0-9]{4}|white|rgba?\(\s*2[45][0-9])'
            )
            if not re.search(light_bg_hint, ctx, re.I):
                add_issue(relpath, "ERROR", f"Invisible text: {match.group()} — dark text on dark background")

        # White card backgrounds (excluding buttons, CTA bands, legend markers, comments)
        # Check in raw content so inline style context (class names) is preserved
        for match in re.finditer(r'background:\s*#fff\b', content):
            start = max(0, match.start() - 200)
            ctx = content[start:match.end() + 80]
            # Skip if it's a button, CTA, chart legend, small decorative element, or comment
            if not re.search(r'btn|button|cta|hover|legend|diamond|dot|marker|NEVER|<!--', ctx, re.I):
                add_issue(relpath, "WARN", f"White background (#fff) — may clash with dark theme")

    # ── 2. PLACEHOLDER CONTENT ──
    # Strip base64 data before checking (avoids false positives from image data)
    content_no_base64 = re.sub(r'data:[^"]+', '', content)
    placeholders = re.findall(r'(?i)(placeholder|lorem ipsum|TODO|FIXME|XXX)', content_no_base64)
    # Filter out HTML placeholder attributes on form inputs and class names
    real_placeholders = []
    for p in placeholders:
        if p.lower() == 'placeholder':
            # Only flag if it appears in visible text, not as an HTML attribute or class name
            for m in re.finditer(r'(?i)placeholder', content_no_base64):
                start = max(0, m.start() - 80)
                end = min(len(content_no_base64), m.end() + 30)
                ctx = content_no_base64[start:end]
                if not re.search(r'placeholder=|class=|Placeholder\'|Placeholder"|input|textarea|select', ctx, re.I):
                    real_placeholders.append(p)
                    break
        elif p.upper() == 'XXX':
            # Only flag XXX if it's in visible text (not CSS, not attributes)
            for m in re.finditer(r'(?i)\bXXX\b', content_no_base64):
                start = max(0, m.start() - 50)
                ctx = content_no_base64[start:m.end() + 50]
                if not re.search(r'style=|class=|\{.*:', ctx, re.I):
                    real_placeholders.append(p)
                    break
        else:
            real_placeholders.append(p)

    for p in real_placeholders:
        add_issue(relpath, "WARN", f"Placeholder content found: '{p}'")

    # Intentionally minimal page exclusions — bypass the meta/nav/footer
    # checks for pages that are NOT meant to be standalone consumer-facing
    # surfaces:
    #   _map-embed.html — iframe target loaded by RealtyVis listing widgets
    #   lp-*.html — Google Ads landing pages (paid traffic; deliberately
    #     stripped of nav/footer to maximize conversion)
    # Convention #15: this exclusion list lives in pre-deploy-check.py only;
    # propagate to the 4 sibling sites at next canonical-pass merge.
    is_minimal_page = (
        fname == "_map-embed.html"
        or fname == "links.html"                        # link-in-bio page (Part G 2a, 2026-09-11) -- deliberately chrome-free, same class as manage-alerts.html
        or fname.startswith("lp-")
        or fname.startswith("listing-presentation-")  # per-agent print artifact,
        or fname.startswith("pre-listing-")            # noindexed, no site chrome
        or fname.startswith("leave-behind-")            # by design (Phase 2, 2026-08-19)
        or fname in INTERNAL_TOOL_PAGES
        or is_internal_tool
    )

    # ── 3. META TAGS ──
    if '<title>' not in content or '</title>' not in content:
        add_issue(relpath, "ERROR", "Missing <title> tag")
    if 'meta name="description"' not in content and not is_minimal_page:
        add_issue(relpath, "ERROR", "Missing meta description")
    if 'og:title' not in content:
        add_issue(relpath, "WARN", "Missing og:title meta tag")
    if 'og:description' not in content:
        add_issue(relpath, "WARN", "Missing og:description meta tag")

    # ── 4. NAV + FOOTER ──
    if not is_minimal_page:
        # 'nav.js' fallback (lean profile only) added at the 2026-09-12
        # canonicalization: labwest/hub have no static nav skeleton in source at
        # all (nav.js injects it entirely at runtime, confirmed on their real
        # pages) -- the literal-class-only check false-flagged ERROR on every
        # page of both lean sites until caught by the Phase-1 dry-run against a
        # real tree. Deliberately NOT extended to the full profile: nav.js loads
        # fleet-wide on Gander/Avalon/Goose Bay too, but their generators bake a
        # real static skeleton that nav.js only enhances -- accepting bare
        # 'nav.js in content' there would silently accept the exact historical
        # regression this check exists to catch (nav.js loaded but throwing
        # before it renders anything, per the 2026-09-08 fleet review: 48/125
        # Goose Bay pages and 613 Avalon pages once rendered no nav at all).
        _no_static_nav = ('<nav class="site-nav">' not in content
                           and '<nav class="nav-main-bar">' not in content)
        if _no_static_nav and (PREDEPLOY_PROFILE == "full" or 'nav.js' not in content):
            add_issue(relpath, "ERROR", "Missing standard site-nav")
        if 'class="site-footer"' not in content and 'footer.js' not in content:
            add_issue(relpath, "ERROR", "Missing footer (neither inline nor footer.js)")

    # ── 5. BROKEN INTERNAL LINKS ──
    for match in re.finditer(r'href="([^"#]*\.html)"', content):
        href = match.group(1)
        if href.startswith("http") or href.startswith("mailto") or href.startswith("tel") or href.startswith("//"):
            continue
        file_dir = os.path.dirname(filepath)
        if href.startswith("/"):
            # Site-absolute URL — resolve from site root (same pattern as Check #10).
            target = os.path.normpath(os.path.join(SITE, href.lstrip("/")))
        else:
            # Relative URL — resolve from this file's directory.
            target = os.path.normpath(os.path.join(file_dir, href))
        if not os.path.exists(target):
            add_issue(relpath, "ERROR", f"Broken link: {href}")

    # ── 6. MISSING LOCAL IMAGES ──
    for match in re.finditer(r'src="(\.\./images/[^"]+)"', content):
        src = match.group(1)
        file_dir = os.path.dirname(filepath)
        target = os.path.normpath(os.path.join(file_dir, src))
        if not os.path.exists(target):
            add_issue(relpath, "WARN", f"Missing image: {src}")

    # ── 6b. HAND-BAKED LISTING-DETAIL LINKS (Check #23 — deploy-freeze landmine) ──
    # A static href to a specific listing-DETAIL page (…-<MLS>.html) in a hand-authored
    # file is a deploy-freeze landmine: when that listing sells, the generator sweeps its
    # detail page, the static link 404s, and the broken-link self-check (#5) HARD-BLOCKS
    # the whole deploy (Avalon's lst-hub-newest froze deploys 2026-06-24 + 06-26; a
    # build-time auto-prune now runs each build). This flags the PATTERN at author time,
    # fleet-wide. Excludes generator-managed sources: the emitted listing tree
    # (listings/<city>/… — regenerated each build), build intermediates under tools/, and
    # injector-refreshed DDF_FRAGMENT regions (stripped before scanning). WARN-only
    # (Convention #19): a human decides client-render / build-time prune / link a stable
    # index instead of a specific MLS.
    _rp23 = relpath.replace(os.sep, "/")
    if not _rp23.startswith("tools/") and not re.match(r'listings/[^/]+/', _rp23):
        _scan23 = re.sub(r"<!-- DDF_FRAGMENT:.*?<!-- /DDF_FRAGMENT:[^>]*-->", "", content, flags=re.S)
        _hard23 = re.findall(r'href="([^"]*\blistings/[^"]*-\d{6,8}\.html)"', _scan23)
        if _hard23:
            add_issue(
                relpath, "WARN",
                f"Check #23: {len(_hard23)} hardcoded listing-detail link(s) "
                f"(e.g. {_hard23[0]}) outside any DDF_FRAGMENT region — a static link to a "
                f"specific MLS goes stale when the listing sells and can freeze the deploy "
                f"(lst-hub-newest landmine class). Client-render from the live feed, rely on "
                f"the build-time prune, or link a stable index instead of a specific listing.")

    # ── 7. DESIGN SYSTEM: H2 SIZE CHECK (full profile only) ──
    # Standard h2 size: clamp(26px, 4vw, 38px)
    if PREDEPLOY_PROFILE == "full":
        h2_sizes = re.findall(r'h2\s*\{[^}]*font-size:\s*([^;]+);', all_css)
        for size in h2_sizes:
            size_clean = size.strip()
            if size_clean and 'clamp(26px' not in size_clean:
                # Allow section-specific overrides but flag non-standard
                if 'rem' in size_clean or 'px' in size_clean:
                    add_issue(relpath, "WARN", f"Non-standard H2 size: {size_clean} (standard: clamp(26px, 4vw, 38px))")

    # ── 8. HOVER COLOR CHECK (full profile only) ──
    if PREDEPLOY_PROFILE == "full":
        hover_reds = re.findall(r':hover\s*\{[^}]*background:\s*(#[0-9a-fA-F]+)', all_css)
        for color in hover_reds:
            if color.lower() in ALLOWED_HOVER:
                continue
            if color.lower() not in ALLOWED_BG_DARK:
                add_issue(relpath, "WARN", f"Non-standard hover color: {color} (standard: {HOVER_RED})")

    # ── 9. CREA COMPLIANCE BLOCK (Rule 6(c)(i)) ──
    # Every page must display the MLS®/REALTOR® trademark statement and brokerage
    # identification. Three acceptable forms:
    #   (a) the marketing-page sentinel injected by tools/inject-crea-footer.py
    #   (b) the lst-ddr block on DDF detail pages (functionally equivalent wording)
    #   (c) 'footer.js' in content, LEAN PROFILE ONLY -- labwest/hub inject the
    #       CREA aside entirely at runtime (no static footer skeleton left in
    #       source at all); added at the 2026-09-12 canonicalization after the
    #       Phase-1 dry-run false-flagged ERROR on every page of both lean
    #       sites. Deliberately NOT extended to the full profile: footer.js
    #       loads fleet-wide on Gander/Avalon/Goose Bay too, but their
    #       generators already bake the real static sentinel that footer.js
    #       only enhances -- accepting bare 'footer.js in content' there would
    #       silently accept a page that genuinely lost its static CREA block,
    #       which is exactly the regression this check exists to catch.
    # Any one passes; absence of all applicable forms is an ERROR.
    # Skip partials/fragments (filename starts with "_") — they are not pages.
    if not fname.startswith("_") and fname not in INTERNAL_TOOL_PAGES:
        _no_static_crea = ('crea-compliance:v1' not in content
                            and 'class="lst-ddr"' not in content)
        if _no_static_crea and (PREDEPLOY_PROFILE == "full" or 'footer.js' not in content):
            add_issue(relpath, "ERROR", "Missing CREA trademark/disclaimer block "
                      "(Rule 6(c)(i)) — run tools/inject-crea-footer.py --apply")

    # ── 10. ASSET REFS RESOLVE TO TRACKED FILES ──
    # Every <link rel="stylesheet" href="..."> and <script src="..."> must
    # point to a file that exists on disk AND is tracked in git. Otherwise
    # Netlify serves a 404 for the asset on deploy and the page renders
    # broken (unstyled footer, dead JS widget, etc.) — a silent-break failure
    # mode because the HTML itself still returns 200.
    # Precedent (2026-04-22): css/turner-network.css untracked on 3 sites →
    # footer strip rendered unstyled. js/turner-network.js + 3 siblings on
    # Avalon → 1500+ listing pages silently missing their footer/nav/share UI.
    # Skip partials (_foo.html) — included fragments aren't served.
    # Skip if git is unavailable (e.g., tarball install, CI setup issue).
    if TRACKED_FILES is not None and not fname.startswith("_"):
        file_dir = os.path.dirname(filepath)
        for m in ASSET_REF_RE.finditer(content):
            url = m.group(1).split("?", 1)[0].split("#", 1)[0].strip()
            if not url or url.lower().startswith(_EXTERNAL_PREFIXES):
                continue
            # Resolve the reference. Leading "/" = absolute to site root;
            # otherwise relative to the referencing HTML file's directory.
            if url.startswith("/"):
                asset_abs = os.path.normpath(os.path.join(SITE, url.lstrip("/")))
            else:
                asset_abs = os.path.normpath(os.path.join(file_dir, url))
            # Skip if the resolved path escapes the site tree.
            if not asset_abs.startswith(SITE):
                continue
            rel_to_site = os.path.relpath(asset_abs, SITE)
            if not os.path.exists(asset_abs):
                add_issue(relpath, "ERROR",
                          f"Asset missing on disk: {url} → {rel_to_site}")
            elif rel_to_site not in TRACKED_FILES:
                # Carveout for CI-managed IDX/VOW photo tree: photos under
                # images/listings/<MLS>/ are downloaded by idx-photo-sync.py
                # during the CI run and staged by the workflow's commit step
                # AFTER the generator (which fires this check) completes.
                # In CI order: photo-sync → regen+self-check (HERE) → git add
                # → commit → push. So on the regen pass, freshly-synced photos
                # are on disk but not yet in `git ls-files` output. The disk-
                # exists check above still catches genuine sync failures;
                # we just skip the tracked-in-git check for this specific
                # CI-managed path. Photos WILL be tracked by deploy time.
                # Filed 2026-05-13 after CI failure on listings/sandringham/
                # 12-mill-path-road-1297474.html surfaced via diagnostic
                # patch on _run_self_check.
                if rel_to_site.startswith("images/listings/"):
                    continue
                add_issue(relpath, "ERROR",
                          f"Asset untracked in git: {url} → {rel_to_site} "
                          "— will 404 on deploy ('git add' the file to fix)")

    # ── 13. AGENT-PHOTO ASPECT-RATIO BUG ──
    # When a CSS rule sets `aspect-ratio` on an <img> via a wrapper-class
    # descendant selector (`.foo-wrap img`, `.foo-wrap > img`, etc.) but
    # does NOT set `height: auto`, AND the matching <img> in HTML carries
    # inline width="N" height="M" HTML attributes, aspect-ratio cannot
    # resolve. The inline HTML Presentational Hints win and the image
    # renders at the literal pixel dimensions — tower-stretches.
    # Precedent: task #171 (pages/about.html .ab-agent-photo-wrap img →
    # 477fe1a, 8 agent cards rendered 272x1920 instead of 272x362),
    # task #175 (pages/property-management.html .pm-crystal-photo-wrap
    # img → c156685, Crystal Hynes photo rendered 420x1920 instead of
    # 420x560). Both fixes were a single token: `height: auto;` added
    # to the img CSS ruleset.
    # Scope (v1): inline <style> blocks only; both known instances lived
    # in page-local CSS. Cross-file CSS dependencies are out of scope.
    # Single-class-wrapper detection only — selectors like
    # `.parent .child img` are tracked under the FIRST captured class,
    # which is intentional (the at-risk wrapper is conventionally the
    # outermost class).
    if not fname.startswith("_") and style_blocks.strip():
        # Strip CSS comments before parsing — comment text inside a body
        # would otherwise false-positive on `aspect-ratio` and false-
        # negative on `height: auto`.
        css_no_comments = re.sub(r'/\*.*?\*/', '', style_blocks, flags=re.DOTALL)
        # Same rule regex shape used by Check #1 (excludes @-rules at top).
        rule_re_13 = re.compile(r'([^{}@][^{}]*?)\{([^{}]*)\}')
        # For each wrapper class targeted by a `<wrapper> img` style
        # selector, accumulate flags across ALL matching rules. A class
        # is at-risk only when the SUM of its rules sets aspect-ratio
        # without height:auto (handles cascade: one rule sets
        # aspect-ratio, another sets height:auto — final state is safe).
        class_flags_13 = {}
        # Direct-class flags (class applied directly to <img>, not on a wrapper).
        # Tracked separately so the at-risk loop can look for matching <img>
        # tags rather than wrapper-descendant <img>. Convention #13 extension
        # 2026-05-18 task #60: Mike Turner image distortion (.mt-agent-photo)
        # slipped past the wrapper-pattern regex below; this catches the
        # direct-class case.
        direct_flags_13 = {}
        for m in rule_re_13.finditer(css_no_comments):
            sel_group = m.group(1).strip()
            body = m.group(2)
            has_ar = bool(re.search(r'\baspect-ratio\s*:', body, re.IGNORECASE))
            has_ha = bool(re.search(r'\bheight\s*:\s*auto\b', body, re.IGNORECASE))
            if not has_ar and not has_ha:
                continue
            for sel in sel_group.split(','):
                sel = sel.strip()
                if not sel:
                    continue
                # Pattern A: wrapper-then-img descendant selector
                #   .foo-wrap img            (descendant)
                #   .foo-wrap > img          (direct child)
                #   .foo-wrap picture img    (multi-level descendant)
                #   .foo-wrap.special img    (compound class wrapper)
                m_wrap = re.match(
                    r'\.([a-z][\w-]*)\b[^,{}]*\bimg\s*$',
                    sel,
                    re.IGNORECASE,
                )
                if m_wrap:
                    cls = m_wrap.group(1)
                    flags = class_flags_13.setdefault(
                        cls, {"has_ar": False, "has_ha": False, "descriptor": sel}
                    )
                    if has_ar:
                        flags["has_ar"] = True
                        flags["descriptor"] = sel
                    if has_ha:
                        flags["has_ha"] = True
                    continue

                # Pattern B: bare class selector (class applied directly to img).
                # Examples that triggered today's task #60 mike-turner fix:
                #   .mt-agent-photo          (single class)
                #   .ie-agent-photo          (single class)
                #   .agent-photo.featured    (compound, both classes)
                # Restrict to common image-affixed name patterns to avoid
                # false-positives on generic layout classes that legitimately
                # set aspect-ratio (e.g. video containers, hero blocks).
                m_direct = re.match(
                    r'^\.([a-z][\w-]*(?:-(?:photo|image|img|portrait|headshot|avatar|pic))(?:\.[a-z][\w-]*)?)\s*$',
                    sel,
                    re.IGNORECASE,
                )
                if m_direct:
                    cls = m_direct.group(1).split('.')[0]  # primary class name
                    flags = direct_flags_13.setdefault(
                        cls, {"has_ar": False, "has_ha": False, "descriptor": sel}
                    )
                    if has_ar:
                        flags["has_ar"] = True
                        flags["descriptor"] = sel
                    if has_ha:
                        flags["has_ha"] = True

        at_risk_13 = {
            cls: f["descriptor"]
            for cls, f in class_flags_13.items()
            if f["has_ar"] and not f["has_ha"]
        }
        # Direct-class at-risk set — checked separately below via different
        # <img> match shape (class-on-img-tag, not class-on-wrapper).
        at_risk_direct_13 = {
            cls: f["descriptor"]
            for cls, f in direct_flags_13.items()
            if f["has_ar"] and not f["has_ha"]
        }

        # For each at-risk wrapper class, look for an <img> with both
        # inline width="N" and height="M" attributes (numeric only —
        # an explicit height="auto" would already be safe) within
        # 2000 chars after any `class="...cls..."` opening tag.
        for cls, descriptor in at_risk_13.items():
            for class_match in re.finditer(
                rf'class\s*=\s*["\'][^"\']*\b{re.escape(cls)}\b[^"\']*["\']',
                content,
                re.IGNORECASE,
            ):
                window_end = min(class_match.end() + 2000, len(content))
                window = content[class_match.end():window_end]
                img_pinned = re.search(
                    r'<img\b[^>]*?\bwidth\s*=\s*["\']?\d+["\']?'
                    r'[^>]*?\bheight\s*=\s*["\']?\d+["\']?',
                    window, re.IGNORECASE,
                ) or re.search(
                    r'<img\b[^>]*?\bheight\s*=\s*["\']?\d+["\']?'
                    r'[^>]*?\bwidth\s*=\s*["\']?\d+["\']?',
                    window, re.IGNORECASE,
                )
                if img_pinned:
                    add_issue(
                        relpath, "ERROR",
                        f"Aspect-ratio pin bug: <img> with inline "
                        f"width/height inside .{cls} wrapper. CSS rule "
                        f"'{descriptor}' sets aspect-ratio but is missing "
                        f"'height: auto' — HTML Presentational Hints will "
                        f"block aspect-ratio resolution and the image will "
                        f"tower-stretch. Fix: add 'height: auto' to the "
                        f"'{descriptor}' ruleset (precedent: task #171 / "
                        f"#175 — single-token fix).",
                    )
                    break  # one issue per at-risk class is sufficient

        # Direct-class at-risk loop (Pattern B extension 2026-05-18 task #60).
        # Look for <img class="...cls..."> tags with inline width="N" + height="N"
        # attributes. The Mike Turner bug (.mt-agent-photo on img directly)
        # slipped past the wrapper-pattern loop above because there's no
        # ".mt-agent-photo img" selector — the class IS the img target.
        for cls, descriptor in at_risk_direct_13.items():
            # Find <img> tags carrying this class directly
            img_tag_re = re.compile(
                rf'<img\b[^>]*?\bclass\s*=\s*["\'][^"\']*\b{re.escape(cls)}\b[^"\']*["\'][^>]*?>',
                re.IGNORECASE,
            )
            for img_match in img_tag_re.finditer(content):
                img_tag = img_match.group(0)
                has_w = re.search(r'\bwidth\s*=\s*["\']?\d+["\']?', img_tag, re.IGNORECASE)
                has_h = re.search(r'\bheight\s*=\s*["\']?\d+["\']?', img_tag, re.IGNORECASE)
                if has_w and has_h:
                    add_issue(
                        relpath, "ERROR",
                        f"Aspect-ratio pin bug (direct-class): <img class=\"{cls}\"> "
                        f"with inline width/height. CSS rule '{descriptor}' sets "
                        f"aspect-ratio but is missing 'height: auto' — HTML "
                        f"Presentational Hints will block aspect-ratio resolution "
                        f"and the image will tower-stretch (image renders at "
                        f"natural pixel height in a different-aspect container). "
                        f"Fix: add 'height: auto' to the '{descriptor}' ruleset "
                        f"(precedent: task #60 — Mike Turner photo distortion).",
                    )
                    break  # one issue per at-risk class is sufficient

    # ── 16. CONVENTION #44 — NETLIFY URL REWRITER FONT-FAMILY ──
    # Netlify's URL rewriter on <a> tags mangles inline-style attributes
    # containing quoted font names:
    #   style="font-family:'Raleway',sans-serif"
    # is rewritten to broken HTML quote escaping at deploy time. Browsers
    # parse the value as broken, font-family inherits to default serif/italic.
    # Affects ONLY <a> tags (the rewriter's href-processing scope); other
    # elements with quoted font names render fine.
    # Workaround: drop quotes around single-word font names — CSS spec
    # doesn't require them. font-family:Raleway,sans-serif works.
    # Precedent: task #201 — "Meet the team" link on gander.html rendered
    # serif/italic on live; fixed at 14e05d3 by dropping the quotes.
    if not fname.startswith("_"):
        for m in re.finditer(
            r'<a\b[^>]*\bstyle\s*=\s*"[^"]*font-family\s*:\s*[\'"]',
            content, re.IGNORECASE,
        ):
            snippet = m.group(0)[:140]
            add_issue(
                relpath, "ERROR",
                f"Check #16: <a> tag with quoted font-family in inline "
                f"style — Netlify URL rewriter will mangle the quote "
                f"escaping and the font will render as default serif/"
                f"italic on live. Drop quotes: "
                f"font-family:Raleway,sans-serif (no quotes around "
                f"single-word font names). Match: {snippet}"
            )

    # ── 22. NO REINTRODUCED RECHAT SDK (2026-06-19 retirement guard) ──
    # Rechat is fully retired: lead forms route to lead-receive.ts, and the
    # legacy `new BoldTrail.Sdk()` calls are served by the LOCAL js/lead-shim.js
    # drop-in. If anyone re-adds the external unpkg @rechat/sdk <script>, leads
    # would once again depend on the (cancelled) Rechat account — a silent
    # lead-loss the moment the account is gone. WARN so a stray re-add is caught.
    if not fname.startswith("_"):
        for m in re.finditer(
            r'<script[^>]+src\s*=\s*["\'][^"\']*(?:@rechat/sdk|rechat\.min\.js)',
            content, re.IGNORECASE,
        ):
            add_issue(
                relpath, "WARNING",
                "Check #22: external Rechat SDK <script src> reintroduced. "
                "Rechat is retired — use the local /js/lead-shim.js drop-in "
                "(window.BoldTrail.Sdk() routes to lead-receive.ts). Match: "
                + m.group(0)[:120]
            )

    # ── 24. COMMUNITY PAGE MUST CARRY ITS TERRITORY-AGENT CARD ──
    # Generated cmx- community pages (pages/<slug>.html for any slug in
    # tools/community-agent-map.json) must ALWAYS emit the territory-agent card
    # (build_agent_cta → data-agent-email routes the lead to that agent). The
    # card was silently dropped from 6 of 8 pages when they were unified to the
    # lean cmx- template in June (build_agent_cta was gated on a lead_capture
    # flag that only 2 canary pages carried) — the recurring "a generated page
    # overwrites hand-added content on the next regen" failure class. Now that
    # the card is config-driven (community-agent-map.json) and un-gated, this
    # check LOCKS IT IN: any future regen/edit that drops the card fails the
    # build loudly instead of silently shipping a page with no territory agent
    # (Convention #18 silent-degraded-output). ERROR from day one — baseline
    # confirmed clean 2026-07-01 (all 8 Gander community pages carry the card).
    # Convention #15: propagates to Avalon/Goosebay when each grows its own
    # tools/community-agent-map.json.
    if relpath.startswith("pages/") and fname.endswith(".html") \
            and fname[:-5] in _COMMUNITY_AGENT_SLUGS:
        if "cmx-agent-cta" not in content or "data-agent-email" not in content:
            add_issue(
                relpath, "ERROR",
                f"Check #24: community page '{fname}' is missing its territory-"
                f"agent card (expected 'cmx-agent-cta' + 'data-agent-email'). "
                f"The agent is config-driven from tools/community-agent-map.json "
                f"via build_agent_cta() — regenerate with build-community-pages.py; "
                f"never hand-edit a generated page. A missing card silently drops "
                f"the territory agent who should receive that community's leads."
            )

    # ── 17. DDF FRAGMENT REQUIRES ddf-fragment.css ──
    # When a file hosts a <!-- DDF_FRAGMENT: --> sentinel block, the
    # .ddf-fragment-grid + .lst-card* CSS rules must be loaded or the
    # cards render as unstyled stacked divs (no grid, no card chrome).
    # Those rules live ONLY in css/ddf-fragment.css today; main.css /
    # mobile-fixes.css / turner-network.css don't carry them.
    #
    # Defends against the bug class that hit task #222: 10 of 12 Gander
    # DDF-bearing pages shipped from Phase 2 Wave A (#184) and Wave B
    # (#194) without the CSS link because the throwaway batch scripts
    # added fragment markup but forgot the head <link>. Pages rendered
    # HTTP 200, no CI errors, but the consumer-facing layout was broken
    # for 2-3 days. Canonical Convention #18 silent-degraded-output.
    # Fixed at 01a885db; this check prevents recurrence.
    #
    # Convention #19 baseline-clean confirmed: post-#222 fix all 12
    # DDF-bearing pages on Gander pass this check (10 fixed in #222,
    # plus index.html + pages/gander.html which already had the link).
    # ERROR severity from day one.
    #
    # Convention #15: lands on Gander first; propagates to Avalon when
    # its DDF fragment infrastructure expands beyond the existing
    # listings/* pages (the listings/ tree already loads the styles
    # via the generator's inline <style> in head_block_simple()).
    if "<!-- DDF_FRAGMENT:" in content:
        if not re.search(
            r'<link[^>]+href\s*=\s*["\'][^"\']*\bddf-fragment\.css\b',
            content, re.IGNORECASE,
        ):
            add_issue(
                relpath, "ERROR",
                f"Check #17: file contains <!-- DDF_FRAGMENT: --> "
                f"sentinel but does not link css/ddf-fragment.css in "
                f"<head>. Cards will render as unstyled stacked divs "
                f"on live (Convention #18 silent-degraded-output, "
                f"precedent: task #222). Add: "
                f'<link rel="stylesheet" href="../css/ddf-fragment.css"> '
                f'after the existing mobile-fixes.css link (or '
                f'href="css/ddf-fragment.css" at depth 0).'
            )

    # ── 31. BoldTrailForms/RechatForms CALLED BUT LIBRARY NEVER LOADED ──
    # (renumbered from #29 at the 2026-09-12 canonicalization -- #29 was
    # already in use by the unrelated rollup-prefilter check below.)
    # 2026-08-04 site audit: 13 pages (8 agent profiles + 5 hubs) called
    # BoldTrailForms.agentContact()/.listingAlerts()/.exitIntent()/etc.
    # from a guarded `typeof BoldTrailForms !== "undefined" && ...` inline
    # script -- the guard makes it FAIL SILENTLY rather than throw, so it
    # shipped invisibly broken for an unknown length of time (no console
    # error, no failed request, just a form that renders empty and a CTA
    # band nobody can submit). A SEPARATE page (listings/new-construction/)
    # called RechatForms.newConstruction() UNGUARDED -- a hard
    # ReferenceError, RechatForms having never existed as a global anywhere
    # in this codebase since the Rechat->BoldTrail cutover.
    #
    # "Loaded" recognizes both patterns already in use fleet-wide: a static
    # <script src="...boldtrail-forms.js"> tag, OR the async dynamic-inject
    # pattern build-community-pages.py uses (`s.src = "...boldtrail-forms.js"`
    # before `document.body.appendChild(s)`).
    #
    # RechatForms.* is flagged unconditionally (ERROR) -- the identifier is
    # dead code by construction, loading the library would not fix it, the
    # call site itself must be renamed to BoldTrailForms.
    #
    # Convention #19: WARNING for the BoldTrailForms-without-load case until
    # a full-fleet baseline sweep (978 generated listing/property pages +
    # every hand-authored page) confirms zero additional pre-existing hits
    # beyond the 13 fixed in this same commit -- promote to ERROR once clean.
    if not fname.startswith("_"):
        for m in re.finditer(r'\bRechatForms\s*\.\s*\w+', content):
            add_issue(
                relpath, "ERROR",
                f"Check #31: RechatForms.* called but RechatForms has never "
                f"existed as a global in this codebase (dead reference from "
                f"the pre-cutover naming) -- this WILL throw a "
                f"ReferenceError. Rename to BoldTrailForms.* and confirm "
                f"js/boldtrail-forms.js is loaded on this page (precedent: "
                f"listings/new-construction/, 2026-08-04). Match: "
                + m.group(0)[:80]
            )
            break  # one hit is enough to diagnose; avoid noise on repeats

        bt_calls = list(re.finditer(r'\bBoldTrailForms\s*\.\s*\w+\s*\(', content))
        if bt_calls:
            loaded = bool(re.search(
                r'(?:<script[^>]+src\s*=\s*["\'][^"\']*boldtrail-forms\.js'
                r'|\.src\s*=\s*["\'][^"\']*boldtrail-forms\.js)',
                content, re.IGNORECASE,
            ))
            if not loaded:
                add_issue(
                    relpath, "WARNING",
                    f"Check #31: BoldTrailForms.{bt_calls[0].group(0).split('.')[-1].rstrip('(')}"
                    f"(...) called ({len(bt_calls)} call site(s)) but "
                    f"js/boldtrail-forms.js is not loaded anywhere on this "
                    f"page (neither a static <script src> nor the async "
                    f"dynamic-inject pattern). If the call is guarded by "
                    f"`typeof BoldTrailForms !== \"undefined\"`, it fails "
                    f"SILENTLY -- the form/CTA renders but does nothing "
                    f"(precedent: 8 agent profiles + 5 hub pages, "
                    f"2026-08-04 site audit). Add a boldtrail-forms.js "
                    f"<script> tag or remove the dead call."
                )


# ═══════════════════════════════════════════════════════════════════
# CHECK #14 — Pre-publish SEO gate
# ═══════════════════════════════════════════════════════════════════
# Catches the most common SEO regressions on cornerstone pages before
# they ship. v1 covers: title length, meta description length, H1 count,
# <img> alt coverage, canonical URL presence, Open Graph image presence.
#
# Convention #19: launches as WARNING only; promote to ERROR per rule
# after baseline-clean confirmed.
# Convention #15: lands on Gander first; reconcile across the 4 sibling
# sites at the canonical-pass merge.
# Design spec: _research/Check14_SEO_Gate_Design_Spec_2026-04-28.md
# Sign-off: Decision H closed 2026-04-28 (land with all defaults).

TITLE_RE_14 = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
META_DESC_RE_14 = re.compile(
    r'<meta\s+[^>]*name\s*=\s*["\']description["\'][^>]*content\s*=\s*["\']([^"\']*)["\']',
    re.IGNORECASE,
)
H1_RE_14 = re.compile(r"<h1\b[^>]*>", re.IGNORECASE)
IMG_RE_14 = re.compile(r"<img\b([^>]*)>", re.IGNORECASE)
ALT_ATTR_RE_14 = re.compile(r'\balt\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)
CANONICAL_RE_14 = re.compile(
    r'<link\s+[^>]*rel\s*=\s*["\']canonical["\']',
    re.IGNORECASE,
)
OG_IMAGE_RE_14 = re.compile(
    r'<meta\s+[^>]*property\s*=\s*["\']og:image["\']',
    re.IGNORECASE,
)


def _is_marketing_page_14(relpath):
    """True if path is a hand-authored marketing page (not auto-generated)."""
    if relpath.startswith("listings/"):
        return False
    if "/_partials/" in relpath or "/templates/" in relpath:
        return False
    return relpath.endswith(".html")


def check_14_seo_gate(html_files):
    """Pre-publish SEO gate — see design spec for rationale."""
    for fp in html_files:
        rel = os.path.relpath(fp, SITE)
        if not _is_marketing_page_14(rel):
            continue
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                content = fh.read()
        except (OSError, UnicodeDecodeError):
            continue

        # Rule 1 — title length
        m = TITLE_RE_14.search(content)
        if not m:
            add_issue(rel, "WARNING",
                "Check #14.1: <title> tag missing entirely. Google needs "
                "this to surface the page in SERPs.")
        else:
            title_text = m.group(1).strip()
            tlen = len(title_text)
            if tlen == 0:
                add_issue(rel, "WARNING",
                    "Check #14.1: <title> is empty. Add a 30-60 char title.")
            elif tlen > 60:
                add_issue(rel, "WARNING",
                    f"Check #14.1: title is {tlen} chars (>60); Google "
                    f"truncates around 60. Trim to fit.")
            elif tlen < 30:
                add_issue(rel, "WARNING",
                    f"Check #14.1: title is {tlen} chars (<30); under-using "
                    f"the SERP slot. Expand toward 50-60 chars.")

        # Rule 2 — meta description length
        m = META_DESC_RE_14.search(content)
        if not m:
            add_issue(rel, "WARNING",
                "Check #14.2: <meta name=\"description\"> missing. Google "
                "may auto-generate snippet from page text — usually worse "
                "for CTR than a hand-written description.")
        else:
            desc = m.group(1).strip()
            dlen = len(desc)
            if dlen == 0:
                add_issue(rel, "WARNING",
                    "Check #14.2: meta description is empty.")
            elif dlen > 160:
                add_issue(rel, "WARNING",
                    f"Check #14.2: meta description is {dlen} chars (>160); "
                    f"Google truncates around 155-160. Trim.")
            elif dlen < 70:
                add_issue(rel, "WARNING",
                    f"Check #14.2: meta description is {dlen} chars (<70); "
                    f"expand toward 140-155 chars to maximize SERP real estate.")

        # Rule 3 — H1 count
        h1_count = len(H1_RE_14.findall(content))
        if h1_count == 0:
            add_issue(rel, "WARNING",
                "Check #14.3: page has no <h1>. Add exactly one.")
        elif h1_count > 1:
            add_issue(rel, "WARNING",
                f"Check #14.3: page has {h1_count} <h1> tags; should have "
                f"exactly 1. Demote extras to <h2>.")

        # Rule 4 — <img> alt coverage
        missing_alt = 0
        for img_match in IMG_RE_14.finditer(content):
            attrs = img_match.group(1)
            alt_match = ALT_ATTR_RE_14.search(attrs)
            if not alt_match or not alt_match.group(1).strip():
                missing_alt += 1
        if missing_alt > 0:
            add_issue(rel, "WARNING",
                f"Check #14.4: {missing_alt} <img> tag(s) have missing or "
                f"empty alt attribute. Add descriptive alt text for SEO + "
                f"accessibility.")

        # Rule 5 — canonical URL
        if not CANONICAL_RE_14.search(content):
            add_issue(rel, "WARNING",
                "Check #14.5: <link rel=\"canonical\"> missing. Critical "
                "for multi-site fleet to avoid duplicate-content signals.")

        # Rule 6 — Open Graph image
        if not OG_IMAGE_RE_14.search(content):
            add_issue(rel, "WARNING",
                "Check #14.6: <meta property=\"og:image\"> missing. Hurts "
                "social-share appearance which feeds back into brand signals.")


# ═══════════════════════════════════════════════════════════════════
# CHECK #15 — JSON-LD AggregateRating canonical-drift
# ═══════════════════════════════════════════════════════════════════
# Convention #32 + #45 enforcement at static-check time. Walks every
# .html file, finds <script type="application/ld+json"> blocks, parses
# JSON, recursively searches for AggregateRating objects. Compares
# ratingValue + ratingCount + reviewCount against canonical values
# from tools/tt-fragments/emit-manifest.json (the file regenerated by
# tt-emit-fragments.py whenever the TestimonialTree corpus changes).
#
# Strict equality after rounding ratingValue to 2 decimals (matches
# shipped form: 4.9675 in manifest → "4.97" in JSON-LD).
#
# Sites without TestimonialTree integration (no emit-manifest.json on
# disk) skip the check silently. Today: Avalon, Labwest, RoyalLePageTurner.
# Future: Goosebay gains it when #158 lands; Avalon when Chris Morrison's
# TT account provisions per #159.
#
# Severity: ERROR from day one. Convention #19 baseline-clean was
# confirmed during the 2026-04-29 lunch-window Convention #32 fleet
# sweep — only 1 RED finding (index.html), swept and shipped at f059d3b.
# Before-this-check baseline is clean.
#
# Precedent: 2026-04-20 Google-era 4.9/330 numbers shipped on multiple
# surfaces, replaced fleet-wide with TestimonialTree-backed 4.97/246
# across 12+ surfaces in the 2026-04-23 testimonials canary. Today's
# index.html drift was the last surface still carrying stale numbers.
# Design spec: _research/Pre_Deploy_Check_15_16_Design_Spec_2026-04-29.md

LDJSON_RE_15 = re.compile(
    r'<script[^>]*\btype\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _find_aggregate_ratings_15(obj, results):
    """Recursively walk a parsed JSON object/array and collect every
    embedded AggregateRating dict. Handles @type as string OR list."""
    if isinstance(obj, dict):
        type_val = obj.get("@type")
        if type_val == "AggregateRating" or (
            isinstance(type_val, list) and "AggregateRating" in type_val
        ):
            results.append(obj)
        for v in obj.values():
            _find_aggregate_ratings_15(v, results)
    elif isinstance(obj, list):
        for item in obj:
            _find_aggregate_ratings_15(item, results)


def check_15_jsonld_drift(html_files):
    """JSON-LD AggregateRating canonical-drift detection."""
    # ── Conv #211 blind-spot fix (2026-07-28) ───────────────────────────────
    # This function used to `return` SILENTLY on three conditions (manifest
    # absent / unreadable / missing required fields). Every one of them
    # disables AggregateRating drift detection completely, and a silent skip is
    # INDISTINGUISHABLE from a clean pass — so Convention #32 enforcement could
    # have been OFF indefinitely with nothing to say so. That is the textbook
    # Conv #211 shape: a check reporting nothing because it covered nothing.
    #
    # Silence is CORRECT on a site with no TestimonialTree integration at all
    # (labwestrealty / royallepageturner have no tools/tt-fragments/). It is a
    # REAL PROBLEM when the fragments dir exists, because that means TT IS
    # wired here and the canonical went missing — a tt-refresh failure, or the
    # manifest dropped out of a workflow git-add list (Conv #193).
    #
    # WARN, deliberately NOT ERROR: this fires regardless of --scope, and the
    # generator self-invokes `--scope listings/` and exits non-zero on ERRORs
    # (Conv #4). An ERROR here would let a momentarily-missing manifest BREAK
    # THE SITE REGEN — the Conv #222 freeze class, where a reporting gap takes
    # the whole site down. Severity is capped on purpose.
    manifest_path = os.path.join(SITE, "tools", "tt-fragments", "emit-manifest.json")
    tt_dir = os.path.join(SITE, "tools", "tt-fragments")
    try:
        tt_wired = os.path.isdir(tt_dir) and any(
            fn.endswith(".html") for fn in os.listdir(tt_dir))
    except OSError:
        tt_wired = False

    def _uncovered_15(reason):
        """State the coverage loss out loud instead of returning silently."""
        if not tt_wired:
            return  # No TT integration on this site — silence is correct.
        add_issue("tools/tt-fragments/emit-manifest.json", "WARN",
            f"Check #15: AggregateRating drift is NOT being validated on this "
            f"run — {reason}. tools/tt-fragments/ HAS fragments, so TT is wired "
            f"on this site and the canonical should exist. Convention #32 "
            f"enforcement is OFF until it is restored: regenerate via "
            f"tt-refresh, and confirm emit-manifest.json is in the workflow's "
            f"git-add list (Conv #193).")

    if not os.path.exists(manifest_path):
        _uncovered_15("emit-manifest.json is absent")
        return

    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        _uncovered_15(f"emit-manifest.json is unreadable ({exc})")
        return

    canonical_count = manifest.get("rollup_total")
    canonical_mean = manifest.get("rollup_mean_rating")
    if canonical_count is None or canonical_mean is None:
        _uncovered_15("emit-manifest.json lacks rollup_total / rollup_mean_rating")
        return

    # Guarded because it was NOT: a non-numeric rollup_mean_rating used to
    # raise straight out of this function and crash the entire pre-deploy run,
    # which is strictly worse than the silent skip it sat next to.
    try:
        canonical_value = round(float(canonical_mean), 2)  # Match shipped 2-decimal form
    except (TypeError, ValueError):
        _uncovered_15(f"rollup_mean_rating is not numeric: {canonical_mean!r}")
        return

    # Per-agent bio pages carry their OWN per-agent AggregateRating (each agent's
    # real review count + rating), which intentionally differs from the brokerage-
    # wide canonical. Exempt them. Derived from THIS SAME manifest's own fragment
    # list (any "agent-<slug>" entry) rather than tools/agent-profiles/*.yml --
    # that directory is a Gander-hosted FLEET-WIDE roster (11 agents across all 3
    # sites) and doesn't exist at all on Avalon/Goose Bay (2026-08-12 port), and
    # most of its entries are no-ops on any single site anyway (e.g. Gander's own
    # copy lists chris-morrison/karen-pomeroy/roberta-primmer, none of whom have
    # a page here). The manifest is already the one source of truth this check
    # reads for the canonical numbers, so deriving the exemption from it too is
    # one source instead of two (Convention #148). Verified behaviorally
    # equivalent on Gander's real data before this ship: the only page the old
    # yml-derived set exempted that the manifest-derived set doesn't is
    # pages/mike-turner.html, which carries ZERO AggregateRating blocks (he has
    # no per-agent TT profile by design) -- so the exemption there was always a
    # no-op either way.
    bio_exempt = set()
    for frag in manifest.get("fragments", []):
        name = frag.get("name", "")
        if name.startswith("agent-"):
            slug = name[len("agent-"):]
            bio_exempt.add(os.path.join("pages", f"{slug}.html"))

    for fp in html_files:
        rel = os.path.relpath(fp, SITE)
        if rel in bio_exempt:
            continue
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                content = fh.read()
        except (OSError, UnicodeDecodeError):
            continue

        for m in LDJSON_RE_15.finditer(content):
            block = m.group(1).strip()
            if not block:
                continue
            try:
                data = json.loads(block)
            except json.JSONDecodeError:
                add_issue(rel, "WARN",
                    "Check #15: malformed JSON-LD block — can't validate "
                    "AggregateRating drift. Fix the JSON syntax.")
                continue

            agg_ratings = []
            _find_aggregate_ratings_15(data, agg_ratings)

            for ag in agg_ratings:
                rv = ag.get("ratingValue")
                rc = ag.get("ratingCount")
                rev_c = ag.get("reviewCount")

                # ratingValue: ship as string "4.97", manifest as float 4.9675.
                if rv is not None:
                    try:
                        rv_num = round(float(rv), 2)
                    except (TypeError, ValueError):
                        add_issue(rel, "WARN",
                            f"Check #15: AggregateRating.ratingValue "
                            f"unparseable: {rv!r}")
                    else:
                        if rv_num != canonical_value:
                            add_issue(rel, "WARN",
                                f"Check #15: AggregateRating.ratingValue "
                                f"drift — expected {canonical_value} from "
                                f"tools/tt-fragments/emit-manifest.json, "
                                f"got {rv_num}. Sync to canonical "
                                f"(Convention #32 enforcement).")

                # ratingCount: ship as string "246", manifest as int 246.
                if rc is not None:
                    try:
                        rc_num = int(str(rc).strip())
                    except (TypeError, ValueError):
                        add_issue(rel, "WARN",
                            f"Check #15: AggregateRating.ratingCount "
                            f"unparseable: {rc!r}")
                    else:
                        if rc_num != canonical_count:
                            add_issue(rel, "WARN",
                                f"Check #15: AggregateRating.ratingCount "
                                f"drift — expected {canonical_count} from "
                                f"tools/tt-fragments/emit-manifest.json, "
                                f"got {rc_num}. Sync to canonical "
                                f"(Convention #32 enforcement).")

                # reviewCount (optional sibling field, same canonical as ratingCount).
                if rev_c is not None:
                    try:
                        rev_num = int(str(rev_c).strip())
                    except (TypeError, ValueError):
                        add_issue(rel, "WARN",
                            f"Check #15: AggregateRating.reviewCount "
                            f"unparseable: {rev_c!r}")
                    else:
                        if rev_num != canonical_count:
                            add_issue(rel, "WARN",
                                f"Check #15: AggregateRating.reviewCount "
                                f"drift — expected {canonical_count} from "
                                f"tools/tt-fragments/emit-manifest.json, "
                                f"got {rev_num}. Sync to canonical "
                                f"(Convention #32 enforcement).")


# ═══════════════════════════════════════════
# CHECK #18 — ORPHAN LISTING DETAIL PAGES
# ═══════════════════════════════════════════
# Detect listing detail HTML files (`listings/<city>/<address>-<MLS>.html`)
# whose MLS does NOT appear in `tools/ddf-cache/listings.json`. These
# are orphan files: the underlying CREA DDF feed no longer carries the
# listing, but the static HTML survives on disk.
#
# Why this exists (Convention #18 silent-degraded-output): the existing
# stale-page sweep in `tools/ddf-generate-pages.py` catches orphans at
# REGEN time — but only when the generator runs against fresh ingest.
# Hand-edited or hand-created detail files survive between regens.
# Today's MLS 1296533 incident (#226) was the inverse case (cache lost
# a listing the file kept) and the fix was a manual hourly rebuild;
# this check catches the static-side mirror image at commit time.
#
# Behaviour:
# - Walks `listings/**/*.html` from the SITE root.
# - Skips index files (city rollups, /listings/ index, special rollups
#   under new-construction/ first-time-buyer/ commercial/) and the
#   /listings/discover/ canary.
# - Extracts MLS from filename via `(\d{6,8})\.html$`. Files that
#   don't match this pattern are treated as non-listing pages and
#   skipped silently (covers any future namespacing under listings/).
# - Loads `tools/ddf-cache/listings.json`. Missing or unreadable cache
#   → check skips silently (no false errors during initial bootstrap
#   on sites that don't have a DDF feed yet).
# - Flags orphans as WARN per Convention #19 (until baseline-clean
#   confirmed across the fleet, then can promote to ERROR).
#
# Severity: WARNING from day one. The expected fix is a `git rm` of
# the orphan file (the sweep handles 301-redirect emission separately
# in `_redirects`), or a manual hourly trigger if the listing is
# legitimately active on REALTOR.ca but missing from feed (the #226
# diagnosis path).

_LISTING_MLS_RE = re.compile(r'(\d{6,8})\.html$')

# Paths under listings/ that are intentionally NOT per-listing detail
# pages. Keep this list narrow — it's the intentional skip-list, not
# a false-positive mitigation.
_LISTING_SKIP_PREFIXES = (
    "listings/discover/",        # Wave-1 canary; data sidecar lives here too
)
_LISTING_SKIP_FILENAMES = frozenset({
    "index.html",                # /listings/ + per-city + per-rollup rollups
    "data.json",                 # discover-feed JSON sidecar
})


def check_18_orphan_listings():
    """Walk listings/<city>/*.html, flag files whose MLS is missing
    from the cache. Skip silently if cache is missing/unreadable.

    2026-08-12 fix: cache_path was `tools/ddf-cache/listings.json` —
    that file has not existed anywhere in the repo since the DDF->IDX
    cutover, so this check silently returned on EVERY site including
    Gander, providing zero orphan-page coverage since the cutover.
    Nothing printed, nothing warned -- the same dark-check shape as
    the sold-notice/golden-letter dedup bugs found the same day
    (Convention #211). Corrected to the real modern cache the
    generator itself uses by default: tools/idx-cache/listings-
    projected.json (see ddf-generate-pages.py main()).

    Convention #22 freshness gate (added 2026-05-06): on stjohns +
    goosebay, that cache is gitignored and only rebuilt by CI
    hourly. A stale local cache produces ~hundreds of false-positive
    orphans (892 on stjohns 2026-05-06 — every disk file added
    since the local cache snapshot). Compare local cache's
    `generated_at` against the git-tracked `deploy-manifest.json`
    timestamp; if cache is older than the manifest by >2 hours, skip
    the check with a single staleness WARN. Pulls a fresh hourly
    rebuild OR running on a fresh clone resolves staleness. Cousin
    to Convention #21 (raw-cache findings != shipping findings) —
    this is the time-axis variant of the same lesson."""
    listings_root = os.path.join(SITE, "listings")
    if not os.path.isdir(listings_root):
        return  # No listings tree on this site — skip silently

    cache_path = os.path.join(SITE, "tools", "idx-cache", "listings-projected.json")
    if not os.path.exists(cache_path):
        add_issue("tools/idx-cache/listings-projected.json", "WARN",
            "Check #18: skipped — projected cache not found on disk. "
            "Gitignored + CI-rebuilt on stjohns/goosebay (expected "
            "locally-absent there); on Gander this means idx-project-"
            "to-ddf-shape.py has not run yet. Orphan-listing-page "
            "detection provided zero coverage on this run.")
        return

    try:
        with open(cache_path, "r", encoding="utf-8") as fh:
            cache = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        add_issue("tools/idx-cache/listings-projected.json", "WARN",
            f"Check #18: skipped — cache unreadable ({e!r}). Orphan-"
            f"listing-page detection provided zero coverage on this run.")
        return

    # Convention #22 freshness gate — see docstring above.
    manifest_path = os.path.join(SITE, "tools", "ddf-cache", "deploy-manifest.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
            cache_ts = cache.get("generated_at", "")
            manifest_ts = manifest.get("generated_at", "")
            if cache_ts and manifest_ts and cache_ts < manifest_ts:
                # Compute delta in hours via simple ISO-format string parse.
                from datetime import datetime
                try:
                    c = datetime.fromisoformat(cache_ts.replace("Z", "+00:00"))
                    m = datetime.fromisoformat(manifest_ts.replace("Z", "+00:00"))
                    delta_h = (m - c).total_seconds() / 3600
                    if delta_h > 2:
                        add_issue("tools/idx-cache/listings-projected.json", "WARN",
                            f"Check #18: skipped — local cache is "
                            f"{delta_h:.1f}h older than deploy-manifest "
                            f"({cache_ts[:10]} vs {manifest_ts[:10]}). "
                            f"Cache is gitignored on stjohns + goosebay "
                            f"and rebuilt by CI hourly. Pull a fresh "
                            f"hourly rebuild output or run on a fresh "
                            f"clone to re-enable orphan detection. "
                            f"Convention #22 freshness gate.")
                        return
                except (ValueError, TypeError):
                    pass  # Timestamp parse failed — fall through to run anyway
        except (OSError, json.JSONDecodeError):
            pass  # Manifest unreadable — fall through to run anyway

    # Build the set of known MLS strings from the cache. The cache stores
    # MLS as a string; normalize via str() to be safe.
    known_mls = set()
    for listing in (cache.get("listings") or cache.get("rows") or []):
        mls = listing.get("mls")
        if mls is not None:
            known_mls.add(str(mls).strip())

    if not known_mls:
        add_issue("tools/idx-cache/listings-projected.json", "WARN",
            "Check #18: skipped — cache present but contained zero "
            "listings (envelope keys: " + str(list(cache.keys())) + "). "
            "Likely pre-ingest state. Orphan-listing-page detection "
            "provided zero coverage on this run.")
        return

    # Walk listings/ and check every .html file matching the MLS pattern.
    for root, _, files in os.walk(listings_root):
        rel_dir = os.path.relpath(root, SITE).replace(os.sep, "/") + "/"
        # Honour the skip-prefix list.
        if any(rel_dir.startswith(p) for p in _LISTING_SKIP_PREFIXES):
            continue
        for fname in files:
            if fname in _LISTING_SKIP_FILENAMES:
                continue
            if not fname.endswith(".html"):
                continue
            m = _LISTING_MLS_RE.search(fname)
            if not m:
                # Doesn't look like a per-listing detail file — skip
                # silently. (e.g. an index, a redirect stub, etc.)
                continue
            file_mls = m.group(1)
            if file_mls in known_mls:
                continue
            # Orphan: file exists, MLS not in cache.
            relpath = os.path.relpath(os.path.join(root, fname), SITE)
            add_issue(relpath, "WARN",
                f"Check #18: orphan listing detail page — MLS {file_mls} "
                f"present on disk but missing from "
                f"tools/idx-cache/listings-projected.json. Either (a) git rm this "
                f"file if the listing is genuinely off-feed, or (b) "
                f"trigger a manual hourly-rebuild workflow run if the "
                f"listing is still active on REALTOR.ca (cousin to "
                f"the #226 MLS 1296533 diagnostic walk).")


# ─────────────────────────────────────────────────────────────────
# Check #25 — community-page coverage guard
# ─────────────────────────────────────────────────────────────────
# WARN when a town with >= COVERAGE_MIN_LISTINGS active listings appears on
# NO community page. The coverage TWIN of Check #24 (agent-card guard): #24
# asserts every community page keeps its territory agent; #25 asserts every
# sizeable town is ON a community page. Prevents the "37 orphaned towns" class
# found in the 2026-07-01 audit (a new feed town with real inventory silently
# reachable only via the raw /listings/<town>/ index, never surfaced on the
# curated community pages — the primary discovery path).
#
# "Covered" = the town's city_slug is shown by some pages/<config>.html — i.e.
# it is a community-config slug, OR inside a MULTI_CITY_FRAGMENTS entry that a
# config's ddf_fragment references. Sources of truth: tools/community-config/*.yml
# (slug + ddf_fragment) + MULTI_CITY_FRAGMENTS in tools/ddf-generate-pages.py
# (AST-parsed — no execution; the generator is heavy + loads caches at import).
# Town counts come from tools/idx-cache/listings-projected.json — the SAME
# projected cache the generator groups by city_slug — which is gitignored +
# rebuilt fresh by CI, so it is absent locally → skips LOUDLY, per-reason
# (Convention #211, same 2026-08-12 pass as Check #18).
# WARN per Convention #19 (a couple of expected out-of-area HQ listings may
# surface as informational; promote to ERROR only if baseline stays clean).
#
# Two real per-site strategies for "covered" (not config-value drift -- a
# genuine architectural difference, kept as two functions rather than forced
# into one shape at the 2026-09-12 canonicalization):
#   "yaml" (Gander, Goose Bay) -- covered = shown by a tools/community-config/
#          *.yml page (directly, or via a MULTI_CITY_FRAGMENTS entry).
#   "bbox" (Avalon)            -- covered = the town's listing centroid falls
#          inside some COMMUNITY_BBOX lat/lng box (AST-parsed from
#          ddf-generate-pages.py), excluding an explicit COVERAGE_DEFERRED
#          set of towns Mike has deliberately deferred.
# Injected from fleet/config/<site>.json's predeploy block; a lean site (no
# predeploy block at all) never calls this check in the first place (full
# profile only), so these three all default safely to inert values.
COVERAGE_STRATEGY = ""
COVERAGE_MIN_LISTINGS = _fleet_int("", 999999)
COVERAGE_DEFERRED = set(_fleet_list(""))


def _parse_multi_city_fragments():
    """AST-parse MULTI_CITY_FRAGMENTS from ddf-generate-pages.py → {slug: set(city_slugs)}."""
    import ast
    out = {}
    gen = os.path.join(SITE, "tools", "ddf-generate-pages.py")
    if not os.path.exists(gen):
        return out
    try:
        tree = ast.parse(open(gen, encoding="utf-8").read())
    except (OSError, SyntaxError):
        return out

    def _str_consts(node):
        vals = set()
        containers = node.args if isinstance(node, ast.Call) else [node]
        for c in containers:
            if isinstance(c, (ast.Set, ast.List, ast.Tuple)):
                for e in c.elts:
                    if isinstance(e, ast.Constant) and isinstance(e.value, str):
                        vals.add(e.value)
        return vals

    for node in ast.walk(tree):
        # MULTI_CITY_FRAGMENTS is annotated (`...: list[dict] = [...]`), so it
        # parses as an AnnAssign, not a plain Assign — handle both.
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
            value = node.value
        else:
            continue
        if "MULTI_CITY_FRAGMENTS" not in names or not isinstance(value, ast.List):
            continue
        for elt in value.elts:
            if not isinstance(elt, ast.Dict):
                continue
            d = {}
            for k, v in zip(elt.keys, elt.values):
                if isinstance(k, ast.Constant):
                    d[k.value] = v
            slug_n, cs_n = d.get("slug"), d.get("city_slugs")
            slug = slug_n.value if isinstance(slug_n, ast.Constant) else None
            if slug and cs_n is not None:
                out[slug] = _str_consts(cs_n)
    return out


def _parse_community_bbox():
    """AST-parse COMMUNITY_BBOX from ddf-generate-pages.py -> {slug: (lat_min,
    lat_max, lng_min, lng_max)}. "bbox" strategy only (Avalon)."""
    import ast
    out = {}
    gen = os.path.join(SITE, "tools", "ddf-generate-pages.py")
    if not os.path.exists(gen):
        return out
    try:
        tree = ast.parse(open(gen, encoding="utf-8").read())
    except (OSError, SyntaxError):
        return out

    def _num(e):
        if isinstance(e, ast.Constant) and isinstance(e.value, (int, float)):
            return float(e.value)
        if (isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.USub)
                and isinstance(e.operand, ast.Constant)):
            return -float(e.operand.value)
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "COMMUNITY_BBOX" not in names or not isinstance(node.value, ast.Dict):
            continue
        for k, v in zip(node.value.keys, node.value.values):
            if (isinstance(k, ast.Constant) and isinstance(v, ast.Tuple)
                    and len(v.elts) == 4):
                vals = [_num(e) for e in v.elts]
                if None not in vals:
                    out[k.value] = tuple(vals)
    return out


def _load_community_coverage():
    """Set of city_slugs shown on some community page (a community-config slug,
    or the city_slugs of a MULTI_CITY_FRAGMENTS entry a config's ddf_fragment
    references)."""
    covered = set()
    multi = _parse_multi_city_fragments()
    cfg_dir = os.path.join(SITE, "tools", "community-config")
    if not os.path.isdir(cfg_dir):
        return covered
    for fn in os.listdir(cfg_dir):
        if not fn.endswith(".yml") or fn.startswith("_"):
            continue
        try:
            text = open(os.path.join(cfg_dir, fn), encoding="utf-8").read()
        except OSError:
            continue
        m_slug = re.search(r'^slug:\s*(\S+)', text, re.M)
        m_frag = re.search(r'^ddf_fragment:\s*(\S+)', text, re.M)
        if m_slug:
            covered.add(m_slug.group(1).strip().strip('"\''))
        if m_frag:
            x = m_frag.group(1).strip().strip('"\'')
            if x.startswith("community-"):
                x = x[len("community-"):]
            covered |= multi.get(x, {x})
    return covered


def check_25_community_coverage():
    """WARN when a sizeable town appears on no community page. Two strategies
    (see COVERAGE_STRATEGY above) share cache-loading; "covered" determination
    diverges. Skips loudly (Convention #211) when the projected cache is
    absent (gitignored; CI-fresh, local-absent — like Check #18, fixed
    2026-08-12 to state the reason instead of a bare return)."""
    cache_path = os.path.join(SITE, "tools", "idx-cache", "listings-projected.json")
    if not os.path.exists(cache_path):
        add_issue("tools/idx-cache/listings-projected.json", "WARN",
            "Check #25: skipped — projected cache not found on disk. "
            "Gitignored + CI-rebuilt (expected locally-absent there). "
            "Community-page coverage provided zero checking on this run.")
        return
    try:
        cache = json.load(open(cache_path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        add_issue("tools/idx-cache/listings-projected.json", "WARN",
            f"Check #25: skipped — cache unreadable ({e!r}). Community-"
            f"page coverage provided zero checking on this run.")
        return
    rows = cache.get("listings") or cache.get("rows") or []
    if not rows:
        add_issue("tools/idx-cache/listings-projected.json", "WARN",
            "Check #25: skipped — cache present but contained zero "
            "listings. Community-page coverage provided zero checking "
            "on this run.")
        return

    if COVERAGE_STRATEGY == "bbox":
        bbox = _parse_community_bbox()
        if not bbox:
            add_issue("tools/ddf-generate-pages.py", "WARN",
                "Check #25: skipped — COMMUNITY_BBOX could not be AST-"
                "parsed from ddf-generate-pages.py (missing or unparseable). "
                "Community-page coverage provided zero checking on this run.")
            return
        towns = {}
        for r in rows:
            s = (r.get("city_slug") or "").strip().lower()
            la, ln = r.get("latitude"), r.get("longitude")
            if not s:
                continue
            t = towns.setdefault(s, [0, 0.0, 0.0, 0])  # n, lat_sum, lng_sum, n_geo
            t[0] += 1
            if isinstance(la, (int, float)) and isinstance(ln, (int, float)):
                t[1] += la
                t[2] += ln
                t[3] += 1
        for slug, (n, lat_sum, lng_sum, n_geo) in sorted(
                towns.items(), key=lambda kv: (-kv[1][0], kv[0])):
            if n < COVERAGE_MIN_LISTINGS or slug in COVERAGE_DEFERRED or not n_geo:
                continue
            cla, cln = lat_sum / n_geo, lng_sum / n_geo
            if any(a1 <= cla <= a2 and b1 <= cln <= b2
                   for (a1, a2, b1, b2) in bbox.values()):
                continue
            add_issue(
                "tools/ddf-generate-pages.py", "WARN",
                f"Check #25: town '{slug}' has {n} active listings but its centroid "
                f"({cla:.3f}, {cln:.3f}) is inside NO COMMUNITY_BBOX — it appears on "
                f"no community-guide page. Add a bbox (+ guide page), or if coverage "
                f"is deliberately deferred add the slug to this site's "
                f"coverage_deferred config. Threshold {COVERAGE_MIN_LISTINGS}+.")
        return

    # "yaml" strategy (Gander, Goose Bay)
    counts = {}
    for r in rows:
        s = (r.get("city_slug") or "").strip().lower()
        if s:
            counts[s] = counts.get(s, 0) + 1
    if not counts:
        add_issue("tools/idx-cache/listings-projected.json", "WARN",
            "Check #25: skipped — no row in the cache carried a "
            "city_slug. Community-page coverage provided zero checking "
            "on this run.")
        return
    covered = _load_community_coverage()
    if not covered:
        add_issue("tools/community-config/", "WARN",
            "Check #25: skipped — no community configs found on this "
            "site (nothing to check coverage against).")
        return
    for slug, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if n >= COVERAGE_MIN_LISTINGS and slug not in covered:
            add_issue(
                "tools/community-config/", "WARN",
                f"Check #25: town '{slug}' has {n} active listings but is on NO "
                f"community page (reachable only via the raw /listings/{slug}/ "
                f"index). Add a tools/community-config/{slug}.yml (its own page) "
                f"or fold it into a MULTI_CITY_FRAGMENTS entry in "
                f"tools/ddf-generate-pages.py so community-page browsers can find "
                f"it. Coverage twin of Check #24. Threshold {COVERAGE_MIN_LISTINGS}+; "
                f"smaller outports intentionally fold into a nearby page.")


# ─────────────────────────────────────────────────────────────────
# Check #19 — Tawk script tag presence on consumer-facing pages
# ─────────────────────────────────────────────────────────────────
# 2026-06-11: Tawk retired on Gander — Turner Assistant (js/chat-widget.js)
# is the live-chat surface now. Either script satisfies the check (Avalon
# still runs Tawk; this file is a Conv #15 propagation candidate).
_TAWK_SCRIPT_RE = re.compile(r'<script[^>]+src\s*=\s*["\'][^"\']*js/(tawk|chat-widget)\.js')

# Files excluded from Check #19 — Tawk legitimately not present:
# - pages/_*.html        : iframe partials (e.g. _map-embed.html) — no chrome
# - pages/lp-*.html      : paid landing pages, intentionally minimal chrome
# - pages/rental-application.html : legal print form, no consumer chat
# - 404.html / robots / sitemap / etc. : non-html or non-consumer surfaces
_TAWK_SKIP_PATTERNS = (
    "pages/_",
    "pages/lp-",
    "pages/rental-application.html",
    "pages/agent-dashboard.html",  # internal-only password-gated admin
    "pages/agent-registry.html",   # internal-only agent registry tool
    "pages/office.html",           # internal-only office console (Turner Deals)
    "pages/agent-deals.html",      # internal-only agent deal workspace (Turner Deals)
    "pages/office-audit.html",     # internal-only document review workspace (Turner Deals, Ship 2)
    "pages/agent.html",            # internal-only agent hub front door (Agent Hub review, Wave A)
    "pages/agent-cma.html",        # internal-only agent CMA builder tool
    "pages/agent-market.html",     # internal-only agent market-stats leaderboards
    "pages/agent-market-talking-points.html",  # internal-only, gated market education
    "pages/agent-explaining-the-market.html",  # internal-only, gated market education
    "pages/listing-presentation-", # noindexed, per-agent print artifact -- no live chat
    "pages/pre-listing-",          # same: print artifact, not a marketing landing page
    "pages/leave-behind-",         # same: one-page print artifact
    "pages/links.html",            # link-in-bio page (Part G 2a, 2026-09-11) -- no site chrome, no chat widget
    "404.html",
)


def check_19_tawk_presence(html_files):
    """Assert that js/tawk.js is loaded on every consumer-facing HTML page.

    Site-specific: if js/tawk.js does not exist on disk, the site does not
    have Tawk and the check skips silently. This makes the rule safely
    propagable to sibling sites via Convention #15 — Tawk-less sites just
    no-op.

    Caught the 2026-05-11 sold-detail.html omission shape: new template
    that forgets the Tawk snippet. ERROR severity from day one per
    Convention #19 (baseline confirmed clean during the 2026-05-10
    rollout sweep)."""
    tawk_path = os.path.join(SITE, "js", "tawk.js")
    if not os.path.exists(tawk_path):
        return  # Site doesn't run Tawk — skip silently
    for relpath in html_files:
        # Honour skip patterns for legitimately Tawk-less pages.
        if any(p in relpath for p in _TAWK_SKIP_PATTERNS):
            continue
        full = os.path.join(SITE, relpath)
        try:
            with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
        except OSError:
            continue
        # Generic noindex-based skip (2026-09-12 canonicalization), same signal
        # as the main loop's is_internal_tool: _TAWK_SKIP_PATTERNS is a
        # hardcoded filename-prefix list that was missing "before-we-search-"
        # and "buyer-presentation-" entirely (both genuinely noindexed print
        # artifacts) -- latent/invisible on Gander only because Gander retired
        # Tawk there (this whole function self-gates to a no-op), caught by
        # the Phase-1 dry-run firing for real on Avalon, which still runs Tawk.
        if re.search(r'<meta\s+name="robots"\s+content="[^"]*noindex', content, re.I):
            continue
        if _TAWK_SCRIPT_RE.search(content):
            continue
        # Missing Tawk on a consumer-facing page.
        add_issue(relpath, "ERROR",
            f"Check #19: live-chat script missing (chat-widget.js or tawk.js). "
            f'Add <script src="{{prefix}}js/chat-widget.js" async></script> '
            f"before </body>. If this page is intentionally chat-less "
            f"(legal/print/landing/partial), add its path prefix to "
            f"_TAWK_SKIP_PATTERNS in pre-deploy-check.py.")


# Pre-compiled patterns for Check #20.
# Class-attribute on any HTML element: catches `class="x"`, `class='x y'`,
# and the rare `class="x y z"` multi-class case. We then split on whitespace
# and filter for `lst-` prefix.
_CLASS_ATTR_RE = re.compile(r'''class\s*=\s*["']([^"']+)["']''')
# CSS rule selector tokens: any `.lst-foo` selector. Matches `.lst-foo {`,
# `.lst-foo:hover`, `.lst-foo .lst-bar`, `.lst-foo[attr=…]`, etc.
_CSS_SELECTOR_RE = re.compile(r'\.(lst-[a-z0-9_-]+)')


# Conv #19/#95: this rewrite (full-tree scan, 2026-09-12) found 2 real,
# currently-live gaps the old one-sample version never saw (lst-tour-yt on
# 44 pages, lst-tour-section-2 on 1) — fixed in ddf-generate-pages.py's
# LISTING_PAGE_CSS in the same commit, but the ON-DISK tree hasn't
# regenerated yet. Shipping straight to ERROR would immediately block every
# PR's pre-deploy check (Check #20 is scope-independent — it always walks
# the whole listings/ tree) until an hourly/nightly cycle regenerates all
# 360 pages. Start at WARN; promote to ERROR once a live run's [check20]
# heartbeat shows "missing 0" (same promotion pattern already used once for
# this exact check on 2026-05-17, see the history comment below).
_CHECK20_SEVERITY = "WARN"


def check_20_listing_css_coverage(html_files):
    """Assert every `lst-*` class used on EVERY listing-detail page has a
    matching CSS selector definition somewhere that page can load.

    Convention #91 prevention. The 2026-05-12 polish-sprint Stage 3 + Stage 5
    bugs both shipped because new CSS rules landed in INDEX_PAGE_CSS but the
    HTML referencing them lives on listing-detail pages (which only inline
    LISTING_PAGE_CSS via head_block). Cards rendered unstyled in production
    for hours before visual audit caught it.

    Full-tree scan (not sample-based, as of 2026-09-12): every listing-detail
    page is read, its `lst-*` classes extracted, and checked against the CSS
    reachable from THAT page — inline <style> blocks plus external CSS files
    linked from <head> (Conv #171: a cache-bust query string after .css is
    tolerated). CSS corpora are cached by a (inline-style-hash, linked-paths)
    key so a site with one template (the common case — every fleet site has
    exactly one distinct stylesheet set across its whole listings/ tree as of
    this rewrite) parses its CSS exactly once regardless of page count.

    Why full-scan and not the sample this check shipped with: on 2026-09-11,
    flipping Gander's LISTING_AUDIO_SCOPE gate made the single ALPHABETICALLY
    FIRST sample page render the "Hear about this home" button for the first
    time — the button's CSS had been missing since the original build, and
    the one-sample design let that ship invisibly to every OTHER listing page
    for hours. A full scan of ~360 pages costs well under half a second
    (measured), so the sampling trade-off no longer earns its keep. This
    function is scope-independent — it always walks the on-disk listings/
    tree regardless of the `--scope` the caller was invoked with, exactly as
    the sample-based version was.

    Sites without a listings/ tree (lean sibling sites) skip silently, same
    as before.
    """
    listings_dir = os.path.join(SITE, "listings")
    if not os.path.isdir(listings_dir):
        return  # Site has no listings tree — silent skip (lean sibling sites)

    pages = []
    for city in sorted(os.listdir(listings_dir)):
        city_path = os.path.join(listings_dir, city)
        if not os.path.isdir(city_path):
            continue
        if city in ("discover", "sold"):
            continue  # different templates
        for fname in sorted(os.listdir(city_path)):
            if fname == "index.html":
                continue
            if not fname.endswith(".html"):
                continue
            pages.append(os.path.join(city_path, fname))

    if not pages:
        add_issue("listings/", "WARN",
            "Check #20: skipped — listings/ tree exists but no individual "
            "listing-detail page was found on disk (only city-rollup "
            "index.html files, or the tree is empty between regens). "
            "CSS-coverage validation provided zero checking on this run.")
        return

    link_re = re.compile(r'<link[^>]+href\s*=\s*["\']([^"\'?]+\.css)(?:\?[^"\']*)?["\']', re.IGNORECASE)
    style_re = re.compile(r'<style[^>]*>(.*?)</style>', re.DOTALL)

    # css_defined_by_key caches the parsed `.lst-*` selector set for a given
    # (inline-style-blob-hash, resolved-linked-css-paths) combination, so a
    # fleet with one uniform template pays the CSS-parsing cost once.
    css_defined_by_key = {}
    linked_css_seen = set()

    all_classes_used = set()
    no_classes_pages = []
    no_css_pages = []
    unreadable_pages = []
    # missing_class_set (frozenset) -> [relpath, ...]
    missing_groups = {}

    for path in pages:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                html = fh.read()
        except OSError as e:
            unreadable_pages.append((path, e))
            continue

        classes_used = set()
        for m in _CLASS_ATTR_RE.finditer(html):
            for tok in m.group(1).split():
                if tok.startswith("lst-"):
                    classes_used.add(tok)
        if not classes_used:
            no_classes_pages.append(path)
            continue
        all_classes_used |= classes_used

        inline_blobs = [m.group(1) for m in style_re.finditer(html)]
        page_dir = os.path.dirname(path)
        linked_paths = []
        for m in link_re.finditer(html):
            href = m.group(1)
            if href.startswith(("http://", "https://", "//")):
                continue
            if href.startswith("/"):
                css_path = os.path.join(SITE, href.lstrip("/"))
            else:
                css_path = os.path.normpath(os.path.join(page_dir, href))
            if os.path.isfile(css_path):
                linked_paths.append(css_path)
        linked_css_seen.update(linked_paths)

        key = (hashlib.md5("\n".join(inline_blobs).encode("utf-8")).hexdigest(),
               tuple(sorted(linked_paths)))
        classes_defined = css_defined_by_key.get(key)
        if classes_defined is None:
            css_corpus = list(inline_blobs)
            for css_path in linked_paths:
                try:
                    with open(css_path, "r", encoding="utf-8", errors="ignore") as fh:
                        css_corpus.append(fh.read())
                except OSError:
                    pass
            if not css_corpus:
                classes_defined = set()
            else:
                classes_defined = {m.group(1) for m in _CSS_SELECTOR_RE.finditer("\n".join(css_corpus))}
            css_defined_by_key[key] = classes_defined

        if not inline_blobs and not linked_paths:
            no_css_pages.append(path)
            continue

        missing = frozenset(classes_used - classes_defined)
        if missing:
            missing_groups.setdefault(missing, []).append(os.path.relpath(path, SITE))

    for path, e in unreadable_pages:
        add_issue(os.path.relpath(path, SITE), "WARN",
            f"Check #20: skipped — listing-detail page unreadable ({e!r}). "
            f"CSS-coverage validation provided zero checking on this page.")

    if no_classes_pages:
        add_issue("listings/", "WARN",
            f"Check #20: {len(no_classes_pages)} of {len(pages)} listing-"
            f"detail page(s) had no `lst-*` classes at all — unexpected on "
            f"this template; e.g. {os.path.relpath(no_classes_pages[0], SITE)}. "
            f"CSS-coverage validation skipped those pages.")

    if no_css_pages:
        add_issue("listings/", "WARN",
            f"Check #20: {len(no_css_pages)} of {len(pages)} listing-detail "
            f"page(s) had no inline <style> and no resolvable linked CSS — "
            f"e.g. {os.path.relpath(no_css_pages[0], SITE)}. CSS-coverage "
            f"validation skipped those pages.")

    css_sets = len(css_defined_by_key)
    if css_sets > 5:
        add_issue("listings/", "WARN",
            f"Check #20: {css_sets} distinct stylesheet sets found across "
            f"the listings/ tree (normally 1 per site) — possible partial-"
            f"regen drift (some pages built by an older/newer generator "
            f"pass than others).")

    # Diff. Any `lst-*` class used but not defined anywhere = Convention #91
    # trap. Group pages that share the exact same missing-class set into one
    # finding so a fleet-wide gap reports once, not once per page.
    for missing, page_list in missing_groups.items():
        missing_list = sorted(missing)
        display = ", ".join(missing_list[:5])
        if len(missing_list) > 5:
            display += f", … (+{len(missing_list) - 5} more)"
        page_list_sorted = sorted(page_list)
        example = page_list_sorted[0]
        on_n_of_m = f"on {len(page_list_sorted)} of {len(pages)} pages"

        # ERROR severity (Convention #19 baseline-clean confirmed 2026-05-17).
        # Promotion history: shipped as ERROR on 2026-05-13 commit 9d5fc66 →
        # immediately tripped CI on the on-disk listings/ tree because those
        # pages were emitted BEFORE the commit's stub-CSS additions landed in
        # the generator → demoted to WARN same day → 2026-05-17 promotion to
        # ERROR after 4 days of CI hourly cycles regenerated the full tree
        # against the new generator. Pre-promotion baseline scan: 398 listing
        # pages scanned, 0 Check #20 findings. Also caught up against the
        # 2026-05-16 per-agent widget Ship 2 (.lst-trust-* CSS added to
        # LISTING_PAGE_CSS per Convention #91) — those rules flowed through
        # the same regen cycles and are now part of the baseline. Pattern
        # banked as a Convention #19 precedent for any future ERROR-level
        # validator that depends on output from a fresh generator run: the
        # baseline check must include "have CI hourlies regenerated the on-
        # disk artifacts since the generator changed?" — not just "does the
        # new generator produce clean output." Multi-cycle wait (~24h+) is
        # the safe interval for promotion.
        add_issue(example, _CHECK20_SEVERITY,
            f"Check #20: {len(missing_list)} `lst-*` class(es) used in HTML "
            f"but undefined in any loaded CSS — Convention #91 trap (CSS "
            f"likely landed in INDEX_PAGE_CSS instead of LISTING_PAGE_CSS). "
            f"Missing: {display} — {on_n_of_m}, e.g. {example}. Search "
            f"tools/ddf-generate-pages.py for `^[A-Z_]+_CSS\\s*=` to "
            f"enumerate _CSS variables; ensure new rules live in "
            f"LISTING_PAGE_CSS (loaded by head_block) not INDEX_PAGE_CSS "
            f"(loaded by head_block_simple).")

    if not args.quiet:
        total_missing_pages = sum(len(v) for v in missing_groups.values())
        print(f"[check20] scanned {len(pages)} listing pages · "
              f"{len(all_classes_used)} distinct lst-* classes · "
              f"{css_sets} stylesheet set(s) · {len(linked_css_seen)} linked css · "
              f"missing {total_missing_pages}")


# ═══════════════════════════════════════════
# RV SURFACE SCAN (check #11) + special modes
# ═══════════════════════════════════════════
# RealtyVis surface drift detection. Two mount patterns:
#   (a) <div data-rv-block="TENANT-WIDGETID">
#   (b) <iframe src="/pages/_map-embed.html?wid=WIDGETID">
# Each detected mount is normalized to "{relpath}::{kind}:{id}" so the
# allow-list is human-greppable.
RV_BLOCK_RE = re.compile(r'data-rv-block\s*=\s*"([A-Za-z0-9\-]+)"')
RV_IFRAME_RE = re.compile(r'_map-embed\.html\?wid=([A-Za-z0-9]+)')

ALLOWED_FILE = os.path.join(SITE, ".rv-surfaces.allowed")


def _scan_rv_surfaces():
    """Scan every HTML file (not just html_files) for RV mounts.
    Returns sorted list of normalized surface IDs."""
    surfaces = set()
    for root, _, files in os.walk(SITE):
        # Skip .git, node_modules, ddf-cache, vendored deps.
        if any(skip in root for skip in (".git", "node_modules", "ddf-cache", "/dist/")):
            continue
        for fname in files:
            if not fname.endswith((".html", ".htm")):
                continue
            fp = os.path.join(root, fname)
            try:
                with open(fp, "r", encoding="utf-8") as fh:
                    content = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            rel = os.path.relpath(fp, SITE)
            for m in RV_BLOCK_RE.finditer(content):
                surfaces.add(f"{rel}::block:{m.group(1)}")
            for m in RV_IFRAME_RE.finditer(content):
                surfaces.add(f"{rel}::iframe:{m.group(1)}")
    return sorted(surfaces)


def _load_allowed():
    """Read .rv-surfaces.allowed if present. Returns set of surface IDs."""
    if not os.path.exists(ALLOWED_FILE):
        return set()
    try:
        with open(ALLOWED_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return set(data.get("surfaces", []))
    except (OSError, ValueError):
        return set()


def _write_allowed(surfaces):
    """Write the .rv-surfaces.allowed snapshot file."""
    payload = {
        "_comment": "Snapshot of RealtyVis mounts allowed at the time this file was written. "
                    "Pre-deploy-check warns on any mount NOT in this list (drift detection). "
                    "Update intentionally with --update-rv-surfaces-allowed when retiring or adding.",
        "surfaces": sorted(surfaces),
    }
    with open(ALLOWED_FILE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


# Special mode: --list-rv-surfaces — print and exit, no other checks.
if args.list_rv_surfaces:
    surfaces = _scan_rv_surfaces()
    allowed = _load_allowed()
    print("=" * 70)
    print("REALTYVIS SURFACE INVENTORY")
    print("=" * 70)
    if not surfaces:
        print("\n  (no RealtyVis mounts found)")
    else:
        print(f"Found: {len(surfaces)} surface(s)")
        if allowed:
            print(f"Allowed: {len(allowed)} (from .rv-surfaces.allowed)")
        else:
            print("Allowed: (no .rv-surfaces.allowed file — run with "
                  "--update-rv-surfaces-allowed to snapshot)")
        print()
        for s in surfaces:
            mark = "  " if s in allowed else "* "
            print(f"  {mark}{s}")
        new_surfaces = [s for s in surfaces if s not in allowed]
        if new_surfaces:
            print(f"\n  * = NEW (not in allow-list, {len(new_surfaces)} drift)")
    sys.exit(0)

# Special mode: --update-rv-surfaces-allowed — refresh snapshot, then exit.
if args.update_rv_surfaces_allowed:
    surfaces = _scan_rv_surfaces()
    _write_allowed(surfaces)
    print(f"Wrote {ALLOWED_FILE} ({len(surfaces)} surface(s) snapshotted).")
    sys.exit(0)

# Default mode: run check #11 (RV drift) as part of the normal flow.
# Non-blocking (WARN only) — this is informational protection, not a gate.
_rv_surfaces_now = _scan_rv_surfaces()
_rv_surfaces_allowed = _load_allowed()
if _rv_surfaces_allowed:  # only warn if there's a baseline to compare against
    for s in _rv_surfaces_now:
        if s not in _rv_surfaces_allowed:
            relpath, _, surface_id = s.partition("::")
            add_issue(relpath, "WARN",
                      f"NEW RealtyVis mount ({surface_id}) — not in "
                      ".rv-surfaces.allowed. If intentional, run with "
                      "--update-rv-surfaces-allowed.")

# Check #14 — pre-publish SEO gate. Runs as WARNING-only per Convention #19
# until baseline-clean confirmed; promote rules to ERROR after fleet sweep.
check_14_seo_gate(html_files)

# Check #15 — JSON-LD AggregateRating canonical-drift. WARN (see the header
# docstring for why this is WARN, not the ERROR Gander ran standalone --
# Goose Bay's baseline is not currently clean). Sites without
# tools/tt-fragments/emit-manifest.json skip silently.
check_15_jsonld_drift(html_files)

# Check #18 — orphan listing detail page detector. Runs as WARNING
# per Convention #19 until baseline-clean confirmed; promote to ERROR
# after fleet sweep. Sites without tools/ddf-cache/listings.json skip
# silently.
check_18_orphan_listings()


# Check #25 — community-page coverage guard (full profile only: lean sites
# carry no community pages/design tokens at all). WARN when a sizeable town is
# on no community page (the coverage twin of Check #24). Convention #19 — WARN
# until baseline-clean confirmed. Skips silently without the projected cache
# (gitignored; CI-fresh, local-absent).
if PREDEPLOY_PROFILE == "full":
    check_25_community_coverage()


def check_26_award_badge_no_national_compute():
    """The team-card 'achieved' award badge must render the OFFICIAL record when
    known, else a PROVINCIAL-capped compute — NEVER national tierForTeam. A national
    award (Chairman's / Top 10) is a percentile award that can only be recorded, never
    computed. The old national fallback made the badge claim a computed Diamond while
    the record chip showed the provincial Platinum for the same year (Goose Bay team
    card, 2026-07-16) — the same graphic contradicting itself. This guards that exact
    regression: in `var achieved=...`, the ternary ELSE branch (the compute fallback)
    must be tierForTeamProvincial, not tierForTeam. Pace may stay national — it's a
    labeled projection, not a claim."""
    path = os.path.join(SITE, "tools", "build-agent-dashboard.py")
    if not os.path.exists(path):
        return  # not this site's tree — skip
    try:
        src = open(path, encoding="utf-8").read()
    except OSError as e:
        add_issue("tools/build-agent-dashboard.py", "WARN",
            f"Check #26: skipped — build-agent-dashboard.py unreadable "
            f"({e!r}). Award-badge national-compute guard provided zero "
            f"checking on this run.")
        return
    for m in re.finditer(r"var\s+achieved\s*=\s*([^;]*?),\s*pace\s*=", src):
        expr = m.group(1)  # the achieved sub-expression only (pace excluded)
        if re.search(r":\s*tierForTeam\(", expr) and "tierForTeamProvincial" not in expr:
            add_issue("tools/build-agent-dashboard.py", "ERROR",
                      "award 'achieved' badge uses a national tierForTeam() compute fallback — "
                      "must be tierForTeamProvincial() (a national award is recorded, never "
                      "computed; guards the Goose Bay Diamond-vs-Platinum contradiction, 2026-07-16)")


check_26_award_badge_no_national_compute()


# Check #19 — Tawk.to live chat script tag presence detector.
# Defensive layer that prevents recurrence of the 2026-05-11 sold-detail.html
# Tawk omission (caught only after Mike eyeballed the page). Asserts every
# consumer-facing page links `js/tawk.js`. Cousin to Check #17 (DDF fragment
# requires its CSS partner) at the live-chat layer.
#
# Site-specific by design: if `js/tawk.js` doesn't exist on the site, the
# check skips silently. Tawk is currently Gander-only per Mike's directive;
# Convention #15 propagation is safe because sibling sites will silent-skip.
#
# ERROR severity from day one — Convention #19 baseline-clean confirmed
# during the 2026-05-10 rollout sweep (#333 closed the rollup gap; full
# fleet of consumer-facing pages was carrying Tawk before this check
# landed). Iframe partials, paid landing pages, and the rental application
# print form are excluded.
check_19_tawk_presence(html_files)


# Check #20 — listing-detail CSS class coverage (Convention #91 prevention).
# Full-scan (as of 2026-09-12, was sample-based): every listing-detail page's
# `lst-*` classes are checked against the CSS reachable from that page —
# inline <style> blocks OR linked external CSS files. Catches the trap where
# new CSS rules land in INDEX_PAGE_CSS instead of LISTING_PAGE_CSS —
# Convention #91 fired twice in 8 hours on 2026-05-12, and the one-sample
# design let a real gap (.lst-listen-* CSS) hide fleet-wide for hours on
# 2026-09-11 because the sample page happened not to exercise it. Severity
# is WARN pending one clean post-regen baseline, then promotes to ERROR
# (_CHECK20_SEVERITY above); sites without a listings/ tree skip silently.
check_20_listing_css_coverage(html_files)


# Check #21 — cache-bust auto-detect (Convention #106(b) reflexive guardrail).
# When a tracked js/*.js file is modified vs HEAD AND any HTML in the site
# references it via <script src="...js/<name>.js?v=stamp"> AND none of those
# HTML files have ALSO modified the stamp, emit WARN: "JS logic changed without
# cache-bust bump."
#
# Would have caught the 2026-05-19 morning auth.js shim ship (4a57b6901) at
# commit-time instead of after a 4-hour Chrome MCP diagnostic loop. Mike's
# browser + Netlify CDN both served the pre-shim auth.js under the unchanged
# ?v=20260519-phase-b1 URL.
#
# WARN-only on first ship to clear any baseline noise — promote to ERROR
# after baseline clean per Convention #19. Sites without listings/ tree
# skip silently (lean siblings).
def check_21_cache_bust_drift():
    """Walk staged JS + CSS files; verify cache-bust stamps moved too.

    Extended 2026-05-20 to cover css/*.css alongside js/*.js, since
    Convention #106(b) applies equally to both — CDN edge can serve
    stale CSS for hours after a logic change unless the stamp bumps
    too. Same underlying pattern matcher, different src/href attribute
    + asset extension.
    """
    import subprocess
    try:
        # Get list of staged + modified JS/CSS files vs HEAD
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=SITE, timeout=10
        )
        if result.returncode != 0:
            return  # Not a git repo or HEAD missing; silent skip
        changed_files = [f.strip() for f in result.stdout.split("\n") if f.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return  # git missing or hung; silent skip
    changed_assets = []  # list of (asset_path, tag, attr, ext_for_pattern)
    for f in changed_files:
        if f.startswith("js/") and f.endswith(".js"):
            changed_assets.append((f, "script", "src", "js"))
        elif f.startswith("css/") and f.endswith(".css"):
            changed_assets.append((f, "link", "href", "css"))
    if not changed_assets:
        return  # No tracked JS/CSS changes → no cache-bust risk
    import re as _re
    for asset_path, tag, attr, ext in changed_assets:
        asset_name = os.path.basename(asset_path)
        # Pattern: <script src="...<name>.js?v=STAMP"> OR
        #          <link  href="...<name>.css?v=STAMP">
        pat = _re.compile(
            r'<' + tag + r'\s+[^>]*' + attr + r'=["\'][^"\']*?'
            + _re.escape(asset_name)
            + r'\?v=([\w\-.]+)["\']',
            _re.IGNORECASE
        )
        referrers = []
        for root, dirs, files in os.walk(SITE):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".netlify")]
            for fname in files:
                if not fname.endswith((".html", ".py")):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except (OSError, UnicodeDecodeError):
                    continue
                for m in pat.finditer(content):
                    rel = os.path.relpath(fpath, SITE)
                    referrers.append((rel, m.group(1)))
        if not referrers:
            continue  # asset not referenced via cache-bust — skip
        referrer_paths = {r[0] for r in referrers}
        modified_referrers = referrer_paths & set(changed_files)
        if not modified_referrers:
            stamps = sorted({r[1] for r in referrers})
            add_issue(
                asset_path, "WARN",
                f"Convention #106(b): {asset_name} modified but no cache-bust stamp "
                f"bump detected in any of {len(referrers)} referrer(s). "
                f"Current stamp(s): {', '.join(stamps[:3])}{' …' if len(stamps) > 3 else ''}. "
                f"Browsers + CDN may serve stale {ext.upper()} until stamp changes. "
                f"Bump in same commit."
            )


check_21_cache_bust_drift()


# ── Check #27: JSON-LD SYNTAX VALIDITY ─────────────────────────────────────
# Every <script type="application/ld+json"> block must parse as JSON.
#
# WHY (2026-07-28): Search Console emailed "Unparsable structured data …
# Parsing error: Missing '}' or object member name" for avalonrealestate.ca on
# 07-22. NOTHING in the fleet validated JSON-LD syntax at build time, so a
# hand-typed JSON error surfaces as a GSC email days later instead of failing
# the deploy. GENERATED blocks are already safe by construction —
# _fleet_genutils.ja() is json.dumps-backed AND escapes "</" so a string value
# cannot close the tag — so the real exposure is hand-authored blocks in
# index.html + pages/*.html.
#
# Convention #19: this ships at ERROR only because the baseline was PROVEN
# clean first — 9,912 ld+json blocks across 7,796 HTML files on all 5 sites,
# 0 malformed, 0 empty.
#
# Convention #97: the message carries the JSON error with line/col AND a
# snippet, because a bare count is undiagnosable on an ephemeral CI runner.
#
# MALFORMED is ERROR (Google cannot parse it; the rich result is lost).
# EMPTY is WARN — Google reads an empty block as "no structured data" rather
# than a parse error, and a future JS-injected-JSON-LD placeholder would be a
# legitimate reason to have one.
#
# `import json as _json27` is function-local ON PURPOSE: the lean variants
# (labwestrealty, royallepageturner) do NOT import json at module level, so a
# module-level reference would NameError on those two while passing on the
# other three (Convention #70/#96 dependency parity). The alias also cannot
# shadow the module-level `json` on the sites that do have it.
LDJSON_RE_27 = re.compile(
    r'<script[^>]*\btype\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def check_27_jsonld_valid(html_files):
    """Every application/ld+json block must be parseable JSON."""
    import json as _json27

    for fp in html_files:
        rel = os.path.relpath(fp, SITE)
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                content = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        for idx, m in enumerate(LDJSON_RE_27.finditer(content), 1):
            block = m.group(1).strip()
            if not block:
                add_issue(rel, "WARN",
                    f"Check #27: application/ld+json block {idx} is EMPTY. "
                    f"Google reads this as no structured data. If a script "
                    f"fills it at runtime that is expected; otherwise the "
                    f"emitter produced nothing.")
                continue
            try:
                _json27.loads(block)
            except ValueError as exc:
                snippet = " ".join(block[:160].split())
                add_issue(rel, "ERROR",
                    f"Check #27: application/ld+json block {idx} is MALFORMED "
                    f"JSON — {exc}. Google cannot parse it, the rich result is "
                    f"lost, and GSC reports it as 'Unparsable structured "
                    f"data'. Block starts: {snippet}")


check_27_jsonld_valid(html_files)


def check_22_agent_roster_nap():
    """Convention #148/#174 Phase B guard. The generator + aggregator now READ
    tools/agent_roster.json (the four dict literals were removed), so a YAML NAP
    edit that wasn't synced into the roster silently ships stale agent contact
    info — the 2026-06-07 danielle-email-typo class. Assert roster NAP ==
    agent-profile YAMLs. Sibling/lean sites without the roster + loader skip
    silently (Convention #74)."""
    import os as _os
    import sys as _sys
    _td = _os.path.dirname(_os.path.abspath(__file__))
    if _td not in _sys.path:
        _sys.path.insert(0, _td)
    try:
        import agent_roster_check
    except Exception:
        return  # roster loader/check absent on this site — skip
    try:
        problems, _summary = agent_roster_check.find_problems()
    except Exception as e:
        add_issue("tools/agent_roster.json", "WARN",
                  f"agent_roster_check could not run ({e}); roster NAP not verified.")
        return
    if problems is None:
        return  # no agent_roster.json on this site — skip
    for p in problems:
        add_issue("tools/agent_roster.json", "ERROR", f"Agent roster NAP drift — {p}")


check_22_agent_roster_nap()


def check_30_roster_copies_drift():
    """Sibling guard to check_22 (Convention #148/#174): that one catches a YAML NAP
    edit that never made it into agent_roster.json. This one catches the NEXT hop —
    build-agent-dashboard.py and push-dashboard-to-supabase.py each carry their own
    hardcoded ROSTER literal (added before agent_roster_loader existed, never
    migrated), and nothing checked THOSE against the canonical roster. An agent
    added/removed/renamed in agent_roster.json could silently drift from what the
    dashboard or the Supabase pusher actually use, with check_22 staying green the
    whole time. Sibling/lean sites without these files skip silently (Conv #74)."""
    import os as _os
    import sys as _sys
    _td = _os.path.dirname(_os.path.abspath(__file__))
    if _td not in _sys.path:
        _sys.path.insert(0, _td)
    try:
        import roster_copies_check
    except Exception:
        return  # checker absent on this site — skip
    try:
        problems = roster_copies_check.find_problems()
    except Exception as e:
        add_issue("tools/roster_copies_check.py", "WARN",
                  f"roster_copies_check could not run ({e}); ROSTER copies not verified.")
        return
    for p in problems:
        add_issue("tools/agent_roster.json", "ERROR", f"Roster copy drift — {p}")


check_30_roster_copies_drift()


def check_28_sitemap_orphans():
    """Convention #182 — a repeated mechanical error (a real content page
    shipped without ever being added to sitemap.xml) needs a durable guard,
    not another manual sweep. sitemap.xml is hand-maintained on this site
    with no generator enforcing it; found twice in one evening (2026-07-29)
    — the NL Housing Market Data hub, then 30 more pages across 3 sites
    (9 Gander market-stats pages alone were invisible to sitemap-driven
    discovery). WARN, not ERROR — sitemap inclusion is more of a judgment
    call than link validity (Check #10), and a false positive here
    shouldn't block a deploy.

    A page is correctly EXCLUDED, not flagged, when:
      - its filename starts with `_` (a partial/fragment, not a real page)
      - robots.txt explicitly Disallows it (a paid-ad landing page kept
        out of discovery on purpose — e.g. the lp-* pages)
      - _redirects intercepts its exact path with a redirect (a retired
        page kept on disk but redirected elsewhere — e.g. the cg-> cmx
        community-guide migration stubs, or sold-listing-search.html)
      - it's named in tools/sitemap-excluded-pages.json — the documented
        allowlist for pages with no structural signal to auto-detect
        (auth-gated account/agent tools, tracking pixels, per-listing
        transactional forms), same pattern as .rv-surfaces.allowed

    Ships with an exclusion list corrected once already the same evening
    it was built: agent-hub/buyer-hub/seller-hub/relocate-hub/text-alerts/
    home-value/property-lookup all *looked* like utility tools by filename
    alone and were nearly excluded — reading each showed real, distinct
    content (verified non-duplicate against sell-your-home.html/
    join-our-team.html/become-a-realtor.html by comparing meta
    descriptions, not just titles). When adding a new exclusion, read the
    page before assuming a "-hub"/"-tool" filename means it isn't real
    content."""
    pages_dir = os.path.join(SITE, "pages")
    if not os.path.isdir(pages_dir):
        return  # no pages/ directory on this site (e.g. lean-profile sites)

    sitemap_path = os.path.join(SITE, "sitemap.xml")
    if not os.path.exists(sitemap_path):
        add_issue("sitemap.xml", "WARN",
            "Check #28: skipped — sitemap.xml not found, despite this site "
            "having a pages/ directory. Sitemap-orphan detection provided "
            "zero checking on this run.")
        return

    try:
        with open(sitemap_path, "r", encoding="utf-8") as fh:
            sitemap_content = fh.read()
    except OSError as e:
        add_issue("sitemap.xml", "WARN",
            f"Check #28: skipped — sitemap.xml unreadable ({e!r}). "
            f"Sitemap-orphan detection provided zero checking on this run.")
        return

    sitemap_locs = set(re.findall(r"<loc>([^<]+)</loc>", sitemap_content))
    sitemap_rel = set()
    for u in sitemap_locs:
        m = re.match(r"https?://[^/]+/(.*)$", u)
        rel = (m.group(1) if m else u).rstrip("/")
        sitemap_rel.add(rel)
        if rel.endswith(".html"):
            sitemap_rel.add(rel[:-5])

    # robots.txt Disallow rules scoped to /pages/<name> (paid landing pages)
    disallowed_stems = set()
    robots_path = os.path.join(SITE, "robots.txt")
    if os.path.exists(robots_path):
        try:
            with open(robots_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    m = re.match(r"\s*Disallow:\s*/pages/([^\s/]+)", line, re.I)
                    if m:
                        disallowed_stems.add(m.group(1))
        except OSError:
            pass

    # _redirects rules whose SOURCE is exactly a pages/<name> path (retired
    # stubs kept on disk but redirected elsewhere)
    redirected_stems = set()
    redirects_path = os.path.join(SITE, "_redirects")
    if os.path.exists(redirects_path):
        try:
            with open(redirects_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    src = line.split()[0]
                    m = re.match(r"^/pages/([^\s]+?)(?:\.html)?$", src)
                    if m:
                        redirected_stems.add(m.group(1))
        except OSError:
            pass

    # Documented allowlist for pages with no structural signal — same
    # pattern as .rv-surfaces.allowed. Missing file / bad JSON == empty
    # allowlist (Convention #74) — the check just runs with whatever
    # structural signals it does have rather than erroring out.
    excluded = {}
    excl_path = os.path.join(SITE, "tools", "sitemap-excluded-pages.json")
    if os.path.exists(excl_path):
        try:
            with open(excl_path, "r", encoding="utf-8") as fh:
                excluded = json.load(fh)
        except (OSError, json.JSONDecodeError):
            excluded = {}

    try:
        page_files = sorted(f for f in os.listdir(pages_dir) if f.endswith(".html"))
    except OSError:
        return

    for fname in page_files:
        if fname.startswith("_"):
            continue
        if fname in excluded:
            continue
        stem = fname[:-5]
        if stem in disallowed_stems or stem in redirected_stems:
            continue
        if f"pages/{fname}" in sitemap_rel or f"pages/{stem}" in sitemap_rel:
            continue
        add_issue(f"pages/{fname}", "WARN",
            f"Check #28: real content page not present in sitemap.xml — "
            f"Google may never discover it via crawl (this exact bug "
            f"class hid 31 real pages fleet-wide as of 2026-07-29). If "
            f"this page is intentionally excluded (auth-gated tool, "
            f"tracking pixel, per-listing transactional form), add it to "
            f"tools/sitemap-excluded-pages.json with a one-line reason "
            f"— but read the page first, don't assume from the filename. "
            f"Otherwise add a <url> entry to sitemap.xml.")


check_28_sitemap_orphans()


# Check #29 — rollup-prefilter field passthrough (js/listings-index.js).
#
# WHY (2026-08-05): /listings/featured/ ("Our Listings") rendered 0 cards
# for 46 days -- applyRollupPrefilter()'s 'featured' branch reads L.ours,
# but normalizeListing()'s return object never carried that key, so the
# filter always saw undefined and the page silently showed "No listings
# to show." (styled as a stuck loading state). This is the 2ND instance
# of the identical bug class: the 2026-05-24 new-construction stall was
# the same shape (idx_* fields missing from normalizeListing), and the
# fix left an in-file COMMENT documenting the rule -- which the featured
# branch, shipped a month later, walked right past. A comment is not a
# guard (banked memory); this check enforces it mechanically.
#
# Extracts every L.<field> reference inside applyRollupPrefilter()'s body
# and every <field>: key inside normalizeListing()'s return object, then
# asserts the first set is a subset of the second. WARN, not ERROR
# (Convention #19) -- verified baseline-clean against the fixed file
# before shipping at this severity.
def check_29_rollup_field_passthrough():
    js_path = os.path.join(SITE, "js", "listings-index.js")
    if not os.path.isfile(js_path):
        return  # sites without this discovery-shell architecture skip silently
    try:
        with open(js_path, "r", encoding="utf-8") as f:
            src = f.read()
    except (OSError, UnicodeDecodeError) as e:
        add_issue("js/listings-index.js", "WARN",
            f"Check #29: skipped — js/listings-index.js unreadable "
            f"({e!r}). Rollup field-passthrough validation provided zero "
            f"checking on this run.")
        return

    nl_start = src.find("function normalizeListing")
    nl_end = src.find("/* ── Rollup prefilter", nl_start) if nl_start != -1 else -1
    pref_start = src.find("function applyRollupPrefilter", nl_end) if nl_end != -1 else -1
    pref_end = src.find("/* ── Wave 2", pref_start) if pref_start != -1 else -1

    if -1 in (nl_start, nl_end, pref_start, pref_end) or not (
        nl_start < nl_end <= pref_start < pref_end
    ):
        add_issue("js/listings-index.js", "WARN",
                   "Check #29 couldn't locate normalizeListing()/"
                   "applyRollupPrefilter() by their expected anchor comments "
                   "-- skipped this check (the functions may have been "
                   "restructured; verify the passthrough rule by hand).")
        return

    normalize_body = src[nl_start:nl_end]
    prefilter_body = src[pref_start:pref_end]

    referenced = set(re.findall(r"L\.([A-Za-z_][A-Za-z0-9_]*)", prefilter_body))
    provided = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*):", normalize_body, re.MULTILINE))

    missing = sorted(referenced - provided)
    if missing:
        add_issue("js/listings-index.js", "WARN",
                   f"applyRollupPrefilter() reads {missing} from a normalized "
                   f"listing, but normalizeListing()'s return object doesn't "
                   f"carry {'that key' if len(missing) == 1 else 'those keys'}. "
                   f"Every server-projected field a rollup filter reads must "
                   f"be added to normalizeListing's return block, or that "
                   f"rollup renders 0 listings (Conv #74's fail-open exists "
                   f"for MISSING data, not for a field the code forgot to "
                   f"pass through).")


check_29_rollup_field_passthrough()


# ═══════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════
def _scope_label():
    if not args.scope:
        return "(full site)"
    return "scope=" + ",".join(args.scope)


if not args.quiet:
    print("=" * 70)
    print("TURNER REALTY — PRE-DEPLOY QUALITY CHECK  " + _scope_label())
    print("=" * 70)
    print(f"Scanned: {len(html_files)} HTML files")
    print(f"Errors: {total_issues}  |  Warnings: {total_warnings}")

    if results:
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
        if total_issues > 0 and not args.warn_only:
            print(f"❌ DEPLOY BLOCKED — {total_issues} error(s) must be fixed first.")
        elif total_issues > 0:
            print(f"⚠️  {total_issues} error(s) found — --warn-only set, not blocking.")
        else:
            print(f"⚠️  {total_warnings} warning(s) found — review recommended but deploy OK.")
    else:
        print("\n  ✅ ALL CLEAR — No issues detected. Safe to deploy.")

if args.emit_json:
    payload = {
        "scope": args.scope or ["(full)"],
        "scanned": len(html_files),
        "errors": total_issues,
        "warnings": total_warnings,
        "warn_only": args.warn_only,
        "files": {
            relpath: [{"severity": s, "message": m} for s, m in issues]
            for relpath, issues in results.items()
        },
    }
    print(json.dumps(payload, indent=2))

if total_issues > 0 and not args.warn_only:
    sys.exit(1)
sys.exit(0)