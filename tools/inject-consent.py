#!/usr/bin/env python3
"""
Turner Realty -- consent gate injector (byte-identical on all 5 sites)
=====================================================================
Mike D-1027-13 item 8 / QA H8; plan _research/Consent_Banner_Plan_2026-10-27.md.

Makes every tracker on a page inert until js/consent.js releases it:
  * Google tag loader   <script async src="https://www.googletagmanager.com/gtag/js?id=X"></script>
        -> <script async type="text/plain" data-consent="analytics" data-src="...gtag/js?id=X"></script>
  * Follow Up Boss widget tracker (the block under <!-- begin Widget Tracker Code -->)
        -> its <script> gets type="text/plain" data-consent="marketing"
  * the two consent scripts (/data/consent-switch.js, /js/consent.js, both defer) are inserted right after <head>
    on any page that has a tracker or loads js/analytics-events.js (Meta pixel) / js/tawk.js (Tawk chat).
The Meta pixel (js/analytics-events.js) and Tawk (js/tawk.js) gate themselves through TurnerConsent.when().
Inline gtag('config') snippets are left alone: they only queue to dataLayer and fire nothing.

With the switch off (data/consent-switch.js) consent.js releases everything at once, so visitors see no change.

Usage:
    python3 tools/inject-consent.py            # dry run, prints counts
    python3 tools/inject-consent.py --apply    # write pages + generator sources
    python3 tools/inject-consent.py --check    # exit 1 if any page/source still has an ungated tracker
Idempotent. Pages: every *.html outside tools/, netlify/, dot dirs, _* dirs/files and agent/ (the signed-in app never
carried trackers). Sources: tools/*.py and tools/*.html (not tools/tests, tools/internal, this file).
"""
import os
import re
import sys

TAGS = '<script src="/data/consent-switch.js" defer></script><script src="/js/consent.js" defer></script>'

GA_LOADER = re.compile(
    r'<script(?P<a1>\s+async)?\s+src="(?P<url>https://www\.googletagmanager\.com/gtag/js\?id=[^"]+)"(?P<a2>\s+async)?\s*>\s*</script>')
GA_GATED = '<script async type="text/plain" data-consent="analytics" data-src="%s"></script>'
# the FUB block: <script> directly after the begin-comment (page text or a python string literal)
FUB_OPEN = re.compile(r'(begin Widget Tracker Code -->(?:\\n)?[\'"]?\s*\n\s*[\'"]?)<script>')
FUB_GATED = r'\1<script type="text/plain" data-consent="marketing">'
HEAD_OPEN = re.compile(r'<head(?:\s[^>]*)?>', re.I)
MARKERS = re.compile(r'googletagmanager\.com/gtag/js|WidgetTrackerObject|js/analytics-events\.js|js/tawk\.js')

SKIP_DIRS = {'tools', 'netlify', 'node_modules', 'feed-cache', 'agent', 'supabase'}
SKIP_PAGES = {'agent/registry.html'}


def gate_text(text, source):
    """Return text with trackers gated. source=True for generator sources (python strings / templates)."""
    out = GA_LOADER.sub(lambda m: (TAGS if source else '') + GA_GATED % m.group('url'), text)
    out = FUB_OPEN.sub(FUB_GATED, out)
    if not source and MARKERS.search(out) and '/js/consent.js' not in out:
        m = HEAD_OPEN.search(out)
        if m:
            out = out[:m.end()] + TAGS + out[m.end():]
    return out


def source_fix(text):
    """Sources: GA literal already preceded by TAGS must not get a second copy."""
    t = gate_text(text, True)
    return t.replace(TAGS + TAGS, TAGS)


def pages(root):
    for d, ds, fs in os.walk(root):
        rel_d = os.path.relpath(d, root).replace(os.sep, '/')
        ds[:] = [x for x in ds if not x.startswith('.') and not x.startswith('_') and x not in SKIP_DIRS and x != 'worktrees']
        for f in fs:
            if f.endswith('.html') and not f.startswith('_'):
                rel = (rel_d + '/' + f) if rel_d != '.' else f
                if rel in SKIP_PAGES:
                    continue
                yield os.path.join(d, f), rel


def sources(root):
    t = os.path.join(root, 'tools')
    for f in sorted(os.listdir(t)) if os.path.isdir(t) else []:
        p = os.path.join(t, f)
        if os.path.isfile(p) and (f.endswith('.py') or f.endswith('.html')) and f != 'inject-consent.py':
            yield p, 'tools/' + f
    hub = os.path.join(t, '_market-hub-shell')
    if os.path.isdir(hub):
        for f in sorted(os.listdir(hub)):
            if f.endswith('.html'):
                yield os.path.join(hub, f), 'tools/_market-hub-shell/' + f


def violations(text):
    """Ungated trackers left in text (pages)."""
    v = []
    for m in re.finditer(r'<script[^>]*googletagmanager\.com/gtag/js[^>]*>', text):
        if 'type="text/plain"' not in m.group(0) or 'data-src=' not in m.group(0):
            v.append('ungated google tag loader')
    for m in re.finditer(r'begin Widget Tracker Code -->\s*<script([^>]*)>', text):
        if 'data-consent="marketing"' not in m.group(1):
            v.append('ungated FUB tracker')
    if MARKERS.search(text) and '/js/consent.js' not in text:
        v.append('tracker/analytics-events without consent.js')
    return v


def main(argv):
    root = os.getcwd()
    apply_ = '--apply' in argv
    check = '--check' in argv
    changed = bad = 0
    for path, rel in list(pages(root)) + list(sources(root)):
        is_src = rel.startswith('tools/')
        try:
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
        except (UnicodeDecodeError, OSError):
            continue
        if not MARKERS.search(text) and 'Widget Tracker Code' not in text:
            continue
        new = source_fix(text) if is_src else gate_text(text, False)
        if check:
            left = violations(text) if not is_src else (
                ['ungated source literal'] if (GA_LOADER.search(text) or FUB_OPEN.search(text)) else [])
            if left:
                bad += 1
                if bad <= 10:
                    print('UNGATED %s: %s' % (rel, ', '.join(sorted(set(left)))))
            continue
        if new != text:
            changed += 1
            if apply_:
                with open(path, 'w', encoding='utf-8') as fh:
                    fh.write(new)
    if check:
        print('consent gate check: %d file(s) with ungated trackers' % bad)
        return 1 if bad else 0
    print('%s %d file(s)' % ('rewrote' if apply_ else 'would rewrite', changed))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
