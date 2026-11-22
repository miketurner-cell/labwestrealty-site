#!/usr/bin/env python3
"""GA4 loads only on a production host (STRICT 4783, sites; SEO ask under D-1119-147, GA localhost pollution).
Offline; exits 1 on drift. Byte-identical on all 5 sites. Needs node.
  G1 js/consent.js carries the guard (GA_HOSTS + gaHostOk) and release() checks it before a gtag.js script is created
  G2 the allow-list is exactly the five production domains (bare domain; www. is stripped, nothing else)
  G3 consent.js run with a faked location (consent switch off, so the legacy "accepted" path releases gated scripts):
     no gtag.js script injected on localhost, 127.0.0.1, [::1], a Netlify deploy preview, a netlify.app host or a look-alike host;
     injected on each production host and its www. form; a non-GA gated script (Meta pixel) is unaffected by the guard"""
import json, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
fails = []
src = open(os.path.join(ROOT, "js/consent.js"), encoding="utf-8").read()

PROD = ["realestategander.com", "goosebayrealestate.ca", "avalonrealestate.ca", "labwestrealty.com", "royallepageturner.com"]
BLOCK = ["localhost", "127.0.0.1", "[::1]", "0.0.0.0", "deploy-preview-12--chipper-kulfi-d3b59b.netlify.app",
         "chipper-kulfi-d3b59b.netlify.app", "main--stjohns-turner-staging.netlify.app", "realestategander.com.evil.example",
         "evilrealestategander.com", "staging.realestategander.com", "realestategander.ca", "192.168.1.20"]

# G1
if "function gaHostOk" not in src or "GA_HOSTS" not in src:
    fails.append("G1 consent.js has no GA production-host guard")
m = re.search(r"function release\(\) \{(.*?)\n  \}\n", src, re.S)
if not m or not re.search(r"googletagmanager.*gtag.*!gaHostOk\(\)", m.group(1), re.S):
    fails.append("G1 release() does not check gaHostOk() before it creates a gtag.js script")

# G2
m = re.search(r"var GA_HOSTS = \[(.*?)\];", src, re.S)
hosts = re.findall(r"'([^']+)'", m.group(1)) if m else []
if sorted(hosts) != sorted(PROD):
    fails.append("G2 GA_HOSTS %r != production domains %r" % (hosts, PROD))

HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const code = fs.readFileSync(process.argv[2], 'utf8');
const host = process.argv[3];
const made = [], infos = [];
function el(tag) { const a = {}; return { tag, attributes: [], setAttribute(k, v) { a[k] = v; this.attributes.push({ name: k, value: v }); },
  getAttribute(k) { return a[k] === undefined ? null : a[k]; }, set src(v) { this._src = v; }, get src() { return this._src; }, text: '', parentNode: null }; }
function gated(dataSrc, cat) { const n = el('script'); n.setAttribute('type', 'text/plain'); n.setAttribute('data-consent', cat); n.setAttribute('data-src', dataSrc);
  n.parentNode = { insertBefore(s) { made.push(s); } }; n.nextSibling = null; return n; }
const nodes = [gated('https://www.googletagmanager.com/gtag/js?id=G-TEST', 'analytics'), gated('https://example.test/pixel.js', 'marketing')];
const storage = {};
const win = { location: { hostname: host, search: '', reload() {} }, localStorage: { getItem: k => storage[k] || null, setItem() {}, removeItem() {} },
  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} }, addEventListener() {}, removeEventListener() {}, innerHeight: 800 };
win.window = win;
win.document = { readyState: 'complete', querySelectorAll: () => nodes, createElement: el, addEventListener() {}, cookie: '',
  documentElement: { classList: { add() {}, remove() {} }, style: { setProperty() {}, removeProperty() {} } }, body: {}, head: { appendChild() {} } };
win.navigator = {};
win.console = { info: m => infos.push(m), log() {}, warn() {}, error() {} };
vm.runInNewContext(code, Object.assign(win, { navigator: {}, console: win.console }));
console.log(JSON.stringify({ gtag: made.filter(s => /googletagmanager/.test(s.src || '')).length, other: made.filter(s => /pixel\.js/.test(s.src || '')).length, infos }));
"""

if not shutil.which("node"):
    fails.append("G3 node not found")
else:
    with tempfile.TemporaryDirectory() as td:
        h = os.path.join(td, "h.js"); open(h, "w").write(HARNESS)
        def run(host):
            r = subprocess.run(["node", h, os.path.join(ROOT, "js/consent.js"), host], capture_output=True, text=True)
            if r.returncode != 0:
                fails.append("G3 harness failed for %s: %s" % (host, (r.stderr or r.stdout)[-300:])); return None
            return json.loads(r.stdout.strip().splitlines()[-1])
        for hn in PROD + ["www." + d for d in PROD] + [d.upper() for d in PROD[:1]]:
            o = run(hn)
            if o is not None and (o["gtag"] != 1 or o["other"] != 1):
                fails.append("G3 production host %s: gtag injected %d (want 1), other %d (want 1)" % (hn, o["gtag"], o["other"]))
        for hn in BLOCK:
            o = run(hn)
            if o is None: continue
            if o["gtag"] != 0:
                fails.append("G3 %s: gtag.js was injected" % hn)
            if o["other"] != 1:
                fails.append("G3 %s: the guard blocked a non-GA gated script (scope creep)" % hn)
            if not o["infos"]:
                fails.append("G3 %s: no console.info line on the skipped host" % hn)
        print("G3 checked %d production hosts (gtag injected) and %d blocked hosts (no gtag.js, incl. localhost, 127.0.0.1, [::1], deploy preview)" % (len(PROD) * 2 + 1, len(BLOCK)))

if fails:
    print("FAIL"); [print(" - " + f) for f in fails]; sys.exit(1)
print("OK ga-production-host-only: guard present, allow-list = %d production domains, no gtag.js on localhost / 127.0.0.1 / deploy previews" % len(PROD))
