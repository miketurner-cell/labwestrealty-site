#!/usr/bin/env python3
"""Consent gate: with CONSENT_BANNER on, no tracker fires before the visitor accepts (STRICT 2242, sites, D-1027-13 item 8).
Static and offline; exits 1 on drift. Byte-identical on all 5 sites.
  C1 js/consent.js and data/consent-switch.js exist; the switch is one of off|preview|on; consent.js pushes all four Consent Mode v2 types as denied
  C2 every public page: no google tag loader, FUB widget tracker or Meta pixel outside a consent gate (tools/inject-consent.py --check logic)
  C3 on every page that has a tracker or loads analytics-events.js / tawk.js, the two consent scripts come first and before the first tracker
  C4 the generator sources (tools/*.py, tools/*.html) cannot write an ungated tracker back at the next rebuild
  C5 js/analytics-events.js starts the Meta pixel only inside consentWhen('marketing', ...); js/tawk.js (if present) the same
  C6 js/footer.js carries the hidden "Cookie settings" link that consent.js shows when the banner is active"""
import importlib.util, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
fails = []


def rd(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8", errors="ignore") as fh:
        return fh.read()


# C1
cj = rd("js/consent.js") if os.path.exists(os.path.join(ROOT, "js/consent.js")) else ""
sw = rd("data/consent-switch.js") if os.path.exists(os.path.join(ROOT, "data/consent-switch.js")) else ""
m = re.search(r'TURNER_CONSENT_SWITCH\s*=\s*"(\w+)"', sw)
if not cj:
    fails.append("C1 js/consent.js missing")
if not m or m.group(1) not in ("off", "preview", "on"):
    fails.append("C1 data/consent-switch.js must set TURNER_CONSENT_SWITCH to off|preview|on")
for t in ("ad_storage", "analytics_storage", "ad_user_data", "ad_personalization"):
    if not re.search(t + r":\s*'denied'", cj):
        fails.append("C1 consent.js does not default %s to denied" % t)
print("switch value: %s" % (m.group(1) if m else "?"))

spec = importlib.util.spec_from_file_location("ic", os.path.join(ROOT, "tools", "inject-consent.py"))
ic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ic)

# C2 + C3
bad, order, seen = [], [], 0
for path, rel in ic.pages(ROOT):
    with open(path, encoding="utf-8", errors="ignore") as fh:
        t = fh.read()
    if not ic.MARKERS.search(t) and "Widget Tracker Code" not in t:
        continue
    seen += 1
    v = ic.violations(t)
    if v:
        bad.append("%s: %s" % (rel, "; ".join(sorted(set(v)))))
        continue
    a = t.find("/data/consent-switch.js")
    b = t.find("/js/consent.js")
    first = min([i for i in (t.find("googletagmanager.com/gtag/js"), t.find("Widget Tracker Code"),
                             t.find("js/analytics-events.js"), t.find("js/tawk.js")) if i >= 0] or [10**9])
    if not (0 <= a < b < first) or not re.search(r'<script src="/data/consent-switch\.js" defer></script><script src="/js/consent\.js(\?v=\w+)?" defer></script>', t):
        order.append(rel)
if seen < 5:
    fails.append("C2 scanned only %d tracker pages: scanner broken" % seen)
if bad:
    fails.append("C2 %d page(s) with an ungated tracker, first: %s" % (len(bad), bad[:3]))
if order:
    fails.append("C3 %d page(s) where the consent scripts are missing or after the first tracker, first: %s" % (len(order), order[:3]))

# C4
src_bad = []
for path, rel in ic.sources(ROOT):
    with open(path, encoding="utf-8", errors="ignore") as fh:
        t = fh.read()
    if rel == "tools/inject-fub-pixel.py" or "googletagmanager.com/gtag/js" in t or "Widget Tracker Code" in t:
        if ic.GA_LOADER.search(t) or ic.FUB_OPEN.search(t):
            src_bad.append(rel)
if src_bad:
    fails.append("C4 generator source(s) would write an ungated tracker: %s" % src_bad)

# C5
ae = rd("js/analytics-events.js")
i_cw, i_fb = ae.find("consentWhen('marketing'"), ae.find("'https://connect.facebook.net/en_US/fbevents.js'")
if not (0 <= i_cw < i_fb):
    fails.append("C5 analytics-events.js installs the Meta pixel outside consentWhen('marketing', ...)")
if os.path.exists(os.path.join(ROOT, "js/tawk.js")):
    tw = rd("js/tawk.js")
    if not (0 <= tw.find("'marketing'") < tw.find("embed.tawk.to") or "when('marketing'" in tw):
        fails.append("C5 tawk.js starts outside the consent gate")
    elif "TurnerCookieConsent" not in tw:
        fails.append("C5 tawk.js does not use TurnerCookieConsent")

# C6
if "data-consent-settings" not in rd("js/footer.js"):
    fails.append("C6 footer.js lost the Cookie settings link")

if fails:
    print("consent-gate-test FAILED")
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("consent-gate-test OK: %d tracker pages gated, consent scripts first on every one, generators + Meta pixel + Tawk gated" % seen)
