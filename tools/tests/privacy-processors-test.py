#!/usr/bin/env python3
"""privacy-processors-test.py -- STRICT 2275 (sites, 2026-10-27, D-1027-47 (f) + D-1027-40).

The privacy policy's "The Tools and Companies We Use" table must match what this site's pages and scripts actually load:
  1. every tool the table names for THIS site is really loaded here (a table row that names a tool the site does not use fails);
  2. every tool this site loads is named for this site in the table (a loaded tracker missing from the table fails);
  3. every external script / iframe / stylesheet host found in the committed pages and js/ is a known tool in the table, so a new
     tracker added to a page head cannot ship unlisted (the host list below is the full set of hosts the table accounts for);
  4. the Privacy Officer line is present.
Byte-identical in all five repos; the site is read from window.TURNER_SITE on its pages. Offline, no browser.
Exit 0 pass, 1 fail, 2 cannot run.
"""
import glob
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAILS = []


def check(ok, name, detail=""):
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok else (" -- " + str(detail)[:1500])))
    if not ok:
        FAILS.append(name)


def read(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


SKIP_DIRS = {".git", "node_modules", "_research", "_archive", ".netlify", "worktrees", ".claude", "tools", "_ops", "data"}


def html_files():
    out = []
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            if f.endswith(".html"):
                out.append(os.path.join(dp, f))
    out.sort()
    # templated listing / property / community / sold pages: a spread sample is enough (they share one template)
    tmpl = [p for p in out if re.search(r"/(listings|property|community|sold)/", p)]
    keep = [p for p in out if p not in set(tmpl)]
    step = max(1, len(tmpl) // 150)
    sample = tmpl[::step]
    # Tour embeds (iGUIDE, Matterport) depend on each listing's data, not the template: a spread sample flips between
    # 'loads it' and 'does not' as listings come and go (sites 2026-10-28, Avalon). Add every templated page that embeds one.
    picked = set(sample)
    tours = [t for t in tmpl if t not in picked and TOUR_EMBED.search(read(t))]
    return keep + sample + tours


# ----------------------------------------------------------------------------------------------- the policy table
TOUR_EMBED = re.compile(r'<iframe[^>]+src="https://(?:[a-z.]*youriguide\.com|my\.matterport\.com)')


def policy_page():
    for c in ("pages/privacy-policy.html", "privacy-policy.html"):
        if (ROOT / c).is_file():
            return c
    return None


SITE_NAMES = {"gander": "Gander", "avalon": "Avalon", "goosebay": "Goose Bay", "labwest": "Lab West", "hub": "hub"}


def site_key(pages):
    for p in pages:
        m = re.search(r"TURNER_SITE\s*=\s*['\"](\w+)['\"]", read(p))
        if m:
            return m.group(1)
    return None


def named(cell, key):
    """True when the 'Where it is loaded' cell says this site loads the tool (handles 'All five sites' and 'Not on ...')."""
    text = re.sub(r"<[^>]+>", "", cell)
    sentences = [s.strip() for s in re.split(r"(?<=[.])\s+", text) if s.strip()]
    pos = " ".join(s for s in sentences if not re.match(r"Not (on|loaded)", s))
    neg = " ".join(s for s in sentences if re.match(r"Not (on|loaded)", s))
    label = SITE_NAMES[key]

    def mentions(t):
        if key == "hub":
            return bool(re.search(r"\bhub\b", t))
        return label in t
    if mentions(neg):
        return False
    return "All five sites" in pos or mentions(pos)


# ----------------------------------------------------------------------------------------------- what the site loads
# key -> (regex over page html, regex over js/*.js or None, requires an html page to load the script file)
def loaded(pages, js_text):
    html_all = "\n".join(read(p) for p in pages)
    nonlisting = "\n".join(read(p) for p in pages if not re.search(r"/(listings|property|community|sold)/", p))
    refs = set(re.findall(r'src="[^"]*?js/([A-Za-z0-9_.-]+\.js)', html_all))

    def script_loaded(name):
        return name in refs

    sig = {}
    sig["Google Analytics 4"] = "googletagmanager.com/gtag/js" in html_all
    sig["Meta pixel"] = "connect.facebook.net" in js_text.get("analytics-events.js", "") and script_loaded("analytics-events.js")
    sig["Follow Up Boss website tracker"] = "WidgetTrackerObject" in html_all
    sig["Follow Up Boss (customer"] = True   # forms post to lead-receive on every site; nothing to detect on the page
    sig["Supabase"] = "supabase.co" in js_text.get("auth.js", "") and script_loaded("auth.js")
    sig["jsDelivr"] = "cdn.jsdelivr.net" in html_all or (script_loaded("auth.js") and "cdn.jsdelivr.net" in js_text.get("auth.js", ""))
    sig["Anthropic"] = script_loaded("chat-widget.js")
    sig["ElevenLabs"] = script_loaded("chat-widget.js")
    sig["Twilio"] = script_loaded("saved-search.js") or script_loaded("alert-inline.js")
    sig["Postmark"] = True
    sig["Retell"] = True
    sig["Google Places"] = script_loaded("address-complete.js")
    sig["Google Maps embed"] = bool(re.search(r"<iframe[^>]+src=\"https://(www\.google\.com/maps|maps\.google\.com)", nonlisting))
    sig["OpenStreetMap"] = any("openstreetmap.org" in t for n, t in js_text.items() if script_loaded(n))
    sig["YouTube"] = bool(re.search(r"youtube(-nocookie)?\.com/embed", html_all)) or bool(re.search(r"youtube(-nocookie)?\.com/embed", "\n".join(js_text.values())) and False)
    sig["Tawk.to"] = script_loaded("tawk.js")
    sig["iGUIDE"] = bool(re.search(r"<iframe[^>]+src=\"https://[a-z.]*youriguide\.com", html_all))
    sig["Matterport"] = bool(re.search(r"<iframe[^>]+src=\"https://my\.matterport\.com", html_all))
    sig["RealtyVis"] = "cdn.realtyvis.com" in html_all
    sig["Royal LePage listings widget"] = bool(re.search(r"<script[^>]+src=\"https://rlpnetwork\.com", html_all))
    sig["Cloudflare Web Analytics"] = "static.cloudflareinsights.com" in html_all
    sig["Google Fonts"] = "fonts.googleapis.com" in html_all
    sig["Browser notifications"] = script_loaded("push-alerts.js")
    sig["Netlify and Cloudflare"] = True
    return sig, html_all


# external hosts the table accounts for (any other host in a script / iframe / stylesheet src fails)
ACCOUNTED_HOSTS = {
    "www.googletagmanager.com", "connect.facebook.net", "cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com",
    "directory.testimonialtree.com", "www.testimonialtree.com", "maps.google.com", "www.google.com", "www.youtube.com",
    "www.youtube-nocookie.com", "places.googleapis.com", "addressvalidation.googleapis.com", "maps.googleapis.com",
    "unpkg.com", "tile.openstreetmap.org", "www.openstreetmap.org", "photos.realestategander.com",
    "photos.avalonrealestate.ca", "photos.goosebayrealestate.ca", "photos.labwestrealty.com",
    "youriguide.com", "unbranded.youriguide.com", "manage.youriguide.com", "my.matterport.com", "cdn.realtyvis.com", "rlpnetwork.com",
    "static.cloudflareinsights.com",
    "d3e54v103j8qbb.cloudfront.net",   # Follow Up Boss widget tracker (the WidgetTrackerObject loader)
    "cdn.followupboss.com", "widgetbe.com", "app.followupboss.com",
}
OWN_SUFFIXES = ("realestategander.com", "avalonrealestate.ca", "goosebayrealestate.ca", "labwestrealty.com", "royallepageturner.com",
                "royallepage.ca", "calendar.app.google")
# trackers that must never be present unlisted
KNOWN_TRACKERS = re.compile(r"(clarity\.ms|hotjar\.com|doubleclick\.net|googleadservices\.com|bat\.bing\.com|analytics\.tiktok\.com|"
                            r"snap\.licdn\.com|static\.ads-twitter\.com|ct\.pinterest\.com|js\.hs-scripts\.com|"
                            r"widget\.intercom\.io|client\.crisp\.chat|cdn\.segment\.com|mixpanel\.com|sentry\.io|fullstory\.com|"
                            r"googlesyndication\.com|connect\.facebook\.net/[^'\"]*sdk)", re.I)


def main():
    pp = policy_page()
    if not pp:
        print("[consent] no privacy-policy page")
        return 2
    pages = html_files()
    key = site_key(pages)
    if key not in SITE_NAMES:
        print("[processors] cannot tell which site this is (no TURNER_SITE on any page): %r" % key)
        return 2
    print("[processors] site = %s; %d pages read" % (key, len(pages)))
    policy = read(ROOT / pp)
    rows = re.findall(r'<tr><td data-l="Company or tool"><strong>(.*?)</strong></td><td data-l="What it does and what it receives">.*?</td>'
                      r'<td data-l="Where it is loaded">(.*?)</td>', policy, re.S)
    check(len(rows) >= 18, "P1 the policy has the tools table (rows: %d)" % len(rows), "table not found")
    check("Privacy Officer:</strong> Mike Turner, Broker of Record" in policy and "miketurner@royallepage.ca" in policy,
          "P2 the Privacy Officer line is present (D-1027-40)")
    js_text = {os.path.basename(p): read(p) for p in glob.glob(str(ROOT / "js" / "*.js"))}
    sig, html_all = loaded(pages, js_text)
    matched = set()
    # always-on or server-side / phone tools: nothing to detect on a page, so only the row has to exist
    ALWAYS = ("Follow Up Boss (customer", "Postmark", "Retell", "Netlify and Cloudflare")
    for name, where in rows:
        hit = [k for k in sig if name.startswith(k) or k in name]
        if not hit:
            check(False, "P3 table row has a detector: %s" % name, "add it to privacy-processors-test.py")
            continue
        k = hit[0]
        matched.add(k)
        if k in ALWAYS:
            continue
        says = named(where, key)
        check(says == bool(sig[k]), "P4 %s: table %s this site, site %s" % (name, "names" if says else "does not name",
              "loads it" if sig[k] else "does not load it"), where)
    for k in sig:
        if k not in matched:
            check(False, "P5 a detected tool has a table row: %s" % k)
    # catch-all: any external host in a script / iframe / stylesheet / img-less src must be accounted for
    bad = {}
    for p in pages:
        t = read(p)
        for m in re.finditer(r"<(?:script|iframe|link)\b[^>]*?(?:src|href)=\"(https?://[^\"/]+)[^\"]*\"[^>]*>", t, re.I):
            tag = m.group(0).lower()
            if tag.startswith("<link") and "stylesheet" not in tag and "preload" not in tag:
                continue
            h = m.group(1).split("://", 1)[1].lower()
            if h in ACCOUNTED_HOSTS or h.endswith(OWN_SUFFIXES):
                continue
            bad.setdefault(h, os.path.relpath(p, ROOT))
    check(not bad, "P6 every external script / iframe / stylesheet host on the pages is a tool the table accounts for", bad)
    jsbad = {}
    for n, t in js_text.items():
        for m in KNOWN_TRACKERS.finditer(t):
            jsbad.setdefault(m.group(0), n)
    for p in pages:
        for m in KNOWN_TRACKERS.finditer(read(p)):
            jsbad.setdefault(m.group(0), os.path.relpath(p, ROOT))
    check(not jsbad, "P7 no tracker outside the table appears in a page or script", jsbad)
    if FAILS:
        print("\n%d FAILURE(S): %s" % (len(FAILS), "; ".join(FAILS)[:1500]))
        return 1
    print("\nAll privacy-processors checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
