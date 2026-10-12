#!/usr/bin/env python3
"""STRICT 3420: the sold-page sign-in card never covers the header, has a way out, and the sold price stays gated
(redesign, D-1009-55, 2026-10-09).

Mike's review: on a signed-out /listings/sold/ (and every town sold page) js/sold-listings.js opens js/vow-gate.js's card on the 401
from the data fetch. The card was a full-screen fixed overlay at z-index 9999 over the header, with no close control: the header
could not be clicked, Escape did nothing and the phone menu button could not be tapped.

Reads js/vow-gate.js, js/sold-listings.js, js/sold-detail.js and every sold page that carries the gate markup. Offline, no browser:
  1. the card opens BELOW the header: openGate() measures the header's bottom edge (.nav-main-bar) and sets the overlay's top to it,
     and the overlay's z-index is one under the header's own (so the header and its menu stay above), re-measured on resize, load
     and when the header changes size;
  2. the card has a visible close button (.vow-x, aria-label "Close sign-in") and a "Back to listings" link to /listings/, re-added
     after every re-render (the sign-in steps replace the card's innerHTML); Escape and a click on the backdrop also close it;
  3. the gate itself is unchanged: the overlay still starts hidden, unlock() runs only from a Supabase session or the legacy token,
     vow-gate.js never reads a price, and both sold scripts still draw "Sign in to see sold price" where the price is null and the
     visitor is not signed in (the server withholds the price on a 401, so nothing signed-out carries one);
  4. every sold page with the gate markup loads vow-gate.js; outside the crawler table (SOLD_PUBLIC_RECORDS, whose price column is
     headed "Asking Price": list price only, close_price is stripped upstream) its static HTML has no price literal, and the table has
     no sold / close price column.
It proves itself first: a copy of vow-gate.js with the way-out pieces cut must fail. Exits 1 on any finding.
Lab West copy (sites, D-1012-34): no sold-detail.js here, and while the switch is off the sold page exists only as the template
tools/listings-sold-index.template.html, so that is checked too.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def gate_problems(js):
    out = []
    need = {
        "overlay placed under the header (top = header bottom)": r'gateEl\.style\.top\s*=\s*h\.top',
        "overlay z-index one under the header's": r'gateEl\.style\.zIndex\s*=\s*String\(h\.z\s*>\s*1\s*\?\s*h\.z\s*-\s*1',
        "header measured from .nav-main-bar": r'querySelector\("\.nav-main-bar"\)',
        "close button .vow-x": r'className\s*=\s*"vow-x"',
        "close button label": r'aria-label",\s*"Close sign-in"',
        "Back to listings link": r'back\.textContent\s*=\s*"Back to listings"',
        "Back to listings goes to /listings/": r'back\.href\s*=\s*"/listings/"',
        "Escape closes": r'ev\.key === "Escape"',
        "backdrop click closes": r'ev\.target === gateEl\) closeGate\(\)',
        "exit controls re-added after a re-render": r'new MutationObserver\(function \(\) \{ if \(gateIsOpen\(\)\) ensureExit',
        "re-measured on resize": r'addEventListener\("resize"',
        "re-measured when the header changes size": r'new ResizeObserver',
        "dialog role": r'setAttribute\("role",\s*"dialog"\)',
    }
    for label, rx in need.items():
        if not re.search(rx, js):
            out.append("vow-gate.js: missing " + label)
    # the gate is unchanged: starts hidden; unlock only from a session / legacy token; never reads a price
    if not re.search(r'gateEl\.style\.display\s*=\s*"none";\s*\n\s*\n?\s*(?://[^\n]*\n\s*)*function openGate', js) and \
            'gateEl.style.display = "none";\n\n  // ── Way out' not in js:
        out.append("vow-gate.js: the overlay no longer starts hidden")
    if re.search(r'close_price|sold_price|\bclosePrice\b', js):
        out.append("vow-gate.js reads a sold price")
    unlocks = [m.start() for m in re.finditer(r'\bunlock\(', js)]
    if len(unlocks) < 3:
        out.append("vow-gate.js: unlock() paths changed")
    return out


def main():
    js_path = ROOT / "js" / "vow-gate.js"
    js = js_path.read_text(encoding="utf-8")
    # self-proof
    cut = js.replace('back.textContent = "Back to listings";', "")
    cut2 = js.replace("gateEl.style.top = h.top + \"px\";", "")
    if gate_problems(js) or not gate_problems(cut) or not gate_problems(cut2):
        print("FAIL self-proof: the checker did not pass the real gate and catch a copy with the way out / header offset cut")
        print("  real gate problems:", gate_problems(js))
        return 1
    bad = 0
    for label, f in (("sold-listings.js", "js/sold-listings.js"),):
        t = (ROOT / f).read_text(encoding="utf-8")
        if "Sign in to see sold price</button>" not in t or not re.search(r"close_price == null && !isAuthedForPrices\(\)", t):
            print("FAIL %s: the signed-out price lock is gone" % label)
            bad += 1
    pages = []
    for p in [ROOT / "listings/sold/index.html", ROOT / "tools/listings-sold-index.template.html"] + sorted((ROOT / "listings/sold").glob("*/index.html")):
        if p.exists() and 'id="vow-gate"' in p.read_text(encoding="utf-8", errors="replace"):
            pages.append(p)
    if not pages:
        print("FAIL no sold page carries the gate markup")
        return 1
    price = re.compile(r"\$\s?\d{2,3},\d{3}")
    for p in pages:
        t = p.read_text(encoding="utf-8", errors="replace")
        body = re.sub(r"<(script|style)\b.*?</\1>", "", t, flags=re.S)
        table = re.search(r"<!-- SOLD_PUBLIC_RECORDS:BEGIN -->.*?<!-- SOLD_PUBLIC_RECORDS:END -->", body, re.S)
        if table:
            if re.search(r"<th>\s*(sold|close)[^<]*price|<th>\s*sold\s*for", table.group(0), re.I):
                print("FAIL %s: the crawler table has a sold price column" % p.relative_to(ROOT))
                bad += 1
            body = body.replace(table.group(0), "")
        if "js/vow-gate.js" not in t:
            print("FAIL %s: gate markup without js/vow-gate.js" % p.relative_to(ROOT))
            bad += 1
        if price.search(body):
            print("FAIL %s: a price literal in the static HTML" % p.relative_to(ROOT))
            bad += 1
    for m in gate_problems(js):
        print("FAIL " + m)
        bad += 1
    print("[sold-gate-way-out] %d sold pages with the gate, %d findings" % (len(pages), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
