#!/usr/bin/env python3
"""site-copy-fixes-test.py -- STRICT 2243 (sites, 2026-10-27, B-1027-07, Mike D-1027-01). Same file in all five site repos.

D-1027-01 (Mike, 2026-10-27) site-copy fixes, pinned so they cannot drift back:
  1. office@avalonrealestate.ca (no MX; bounced) appears nowhere in the repo (served HTML, JS, generators, data).
  2. The retired response-time promises are gone from served HTML, JS and generators: only the one sentence from
     js/reply-promise.js is allowed ("Our receptionist answers 24/7, and an agent calls you back the same day.").
     Careers/join/become-a-realtor pages and the careers-only thank-you in js/boldtrail-forms.js belong to the
     careers builder (D-1026-31) and are skipped here (listed in SKIP_CAREERS).
  3. No link to the retired realestategander.royallepage.ca site on a served page.
  4. Per-site copy: Gander (Kayla's contact card follows tools/site-config.json leave_contact; text-alerts links are
     root-relative because /text-alerts is a rewrite; the stale Musgrace fragment is gone), Avalon (no "Royal LePage
     Central"), Goose Bay (no BoldTrail/RealtyVis in terms/accessibility), Lab West (no "no office yet").
Generated listing pages (listings/) are rewritten hourly from the generators, which are scanned; they are not scanned here.
Offline. Exits 1 on drift.
"""
import json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
fails = []
def check(ok, msg):
    if not ok:
        fails.append(msg)

SKIP_DIRS = {"listings", "tests", "_research", "_archive", "node_modules", ".git", "seo-cache", "feed-cache", "idx-cache",
             "ddf-cache", ".github", "build-status", "runbooks", "retell", "fixtures"}
EXTS = (".html", ".js", ".py", ".ts", ".tmpl", ".yml", ".yaml")
SKIP_CAREERS = re.compile(r"(^|/)(join-our-team|become-a-realtor|first-year[^/]*|why-join|agent-training|labrador-west)\.html$|(^|/)recruit[^/]*$")
SKIP_FILES = {
    "tools/nctf-data-quality-snapshot.py": "a sender (From) address of an internal report, not site copy; changing it is a mail-config change (reported to Mike)",
}

def files():
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith(".")]
        rel_dir = os.path.relpath(dp, ROOT)
        for f in fn:
            if f.endswith(EXTS):
                yield os.path.normpath(os.path.join(rel_dir, f))

def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8", errors="ignore") as fh:
        return fh.read()

PROMISE = "Our receptionist answers 24/7, and an agent calls you back the same day."
rp = os.path.join(ROOT, "js", "reply-promise.js")
check((not os.path.isfile(rp)) or PROMISE in read("js/reply-promise.js"), "js/reply-promise.js does not carry the D-1027-01 sentence")

OLD = [
    (re.compile(r"office@avalonrealestate\.ca", re.I), "office@avalonrealestate.ca (no MX) -> cmorrison@royallepage.ca", False),
    (re.compile(r"licensed agents? (?:is|are) always available|licensed agents? available 24 hours|Agent by Phone\s*(?:—|&mdash;|-)\s*24 Hours", re.I), "old 24-hour agent line", True),
    (re.compile(r"we typically respond to inquiries within 24 hours|(?<![\w'])(?:we|we'll|we’ll) reply within one business hour|Same-day reply\.", re.I), "old reply promise", True),
    (re.compile(r"realestategander\.royallepage\.ca", re.I), "link to the retired realestategander.royallepage.ca site", True),
    (re.compile(r"href=.https?://(?:www\.)?homebasenl\.com|building-more-housing-that-is-affordable"), "dead partner link (homebasenl.com site 404s; NLHC building-more-housing page 404s)", False),
    (re.compile(r"Royal LePage Central\b"), "'Royal LePage Central' (the brokerage is Royal LePage Turner Realty, Gander)", True),
    (re.compile(r"No Turner office or agent is in Labrador West yet|no Turner agent in Labrador West yet"), "Lab West 'no office yet' line", True),
]
WINDOW_RE = re.compile(r"within one business hour|data-reply-window")
n = 0
for rel in files():
    r = rel.replace(os.sep, "/")
    if r in SKIP_FILES or r.startswith("tools/tests/") or r == "js/reply-promise.js":
        continue
    t = read(r)
    n += 1
    for rx, why, careers_skip in OLD:
        if careers_skip and SKIP_CAREERS.search(r):
            continue
        m = rx.search(t)
        if m:
            check(False, "%s: %s (%r)" % (r, why, m.group(0)[:60]))
    if WINDOW_RE.search(t) and r not in ("js/boldtrail-forms.js",) and not SKIP_CAREERS.search(r) and not r.startswith("tools/"):
        # only js/boldtrail-forms.js may keep the careers-only window; accessibility statement says "two business days", unaffected
        m = WINDOW_RE.search(t)
        check(False, "%s: old 'within one business hour' window (%r)" % (r, m.group(0)))
check(n > 20, "scope looks wrong: only %d files scanned" % n)

# --- per-site ---------------------------------------------------------------------------------
def has(rel):
    return os.path.isfile(os.path.join(ROOT, rel))

for rel in ("pages/terms-of-use.html", "pages/accessibility.html"):
    if has(rel) and "goosebay" in read(rel).lower():
        t = read(rel)
        check("RealtyVis" not in t and "<strong>BoldTrail" not in t and "RealtyVis, BoldTrail" not in t,
              "%s: names RealtyVis/BoldTrail (the CRM is Follow Up Boss)" % rel)

if has("tools/site-config.json") and has("pages/contact.html"):   # Gander
    cfg = json.loads(read("tools/site-config.json")).get("leave_contact", {}).get("kayla-tulk", {})
    check(bool(cfg), "tools/site-config.json: leave_contact.kayla-tulk is missing")
    m = re.search(r'<a href="tel:(\d+)" class="team-member-phone"( data-leave-contact="kayla-tulk")?>([^<]+)</a>(?:(?!</div>).)*?kaylatulk@', read("pages/contact.html"), re.S)
    check(bool(m), "pages/contact.html: Kayla Tulk's card phone line not found")
    if m and cfg:
        want = cfg["office_phone"] if cfg.get("on_leave") else cfg["own_phone"]
        check(m.group(3).strip() == want, "pages/contact.html: Kayla's card shows %r, tools/site-config.json says %r (on_leave=%s)" % (m.group(3).strip(), want, cfg.get("on_leave")))
        check((m.group(2) is not None), "pages/contact.html: Kayla's phone line lost its data-leave-contact marker")
    check(not has("tools/page-fragments/community-musgrace-harbout.html"), "tools/page-fragments/community-musgrace-harbout.html is back (D-1026-26: the town is Musgrave Harbour)")
    if has("pages/text-alerts.html"):
        bad = re.findall(r'<a href="(?!/|#|https?:|mailto:|tel:)([a-z0-9-]+\.html)"', read("pages/text-alerts.html"))
        check(not bad, "pages/text-alerts.html: relative page links break because /text-alerts is a rewrite (use /pages/<name>.html): %s" % bad[:5])

if fails:
    print("FAIL site-copy-fixes-test:")
    for x in fails[:60]:
        print(" -", x)
    sys.exit(1)
print("ok site-copy-fixes-test: %d files scanned" % n)
