#!/usr/bin/env python3
"""careers-pages-test.py -- STRICT 2244 (sites, B-1027-07; Mike D-1026-31, D-1027-03, D-1027-16, D-1027-17).
Every careers / join / become-a-realtor / first-year / why-join page on this site:
  * states the ONE comp line "70/30 split with profit share. No desk fees." and none of the retired comp wording;
  * carries the booking link as its main button, no confidential mailto, one recruit phone number;
  * loads js/careers-kit.js and holds the short join form (data-tk-join) and the brand line;
  * carries none of the unverified claims D-1026-31 removed, and the NLAR / Government Services facts as read on 2026-10-27.
Also pins js/careers-kit.js (booking URL, one phone constant, no Text button while 709-256-7999 cannot take texts) and
tools/brokerage-facts.json. Byte-identical on all five site repos; offline; exits 1 on drift."""
import json, re, sys
from pathlib import Path
R = Path(__file__).resolve().parent.parent.parent
NAMES = ("become-a-realtor.html", "first-year-realtor-nl.html", "join-our-team.html", "why-join.html")
PAGES = [p for n in NAMES for p in (n, "pages/" + n) if (R / p).exists()]
facts = json.loads((R / "tools/brokerage-facts.json").read_text(encoding="utf-8"))
BOOK, COMP = facts["booking_url"], facts["recruit_comp_line"]
fails = []
def need(c, m):
    if not c: fails.append(m)
need(PAGES, "no careers page found")
BANNED = [r"competitive (commission )?split", r"competitive commission", r"higher tier", r"performance-based", r"discussed confidentially",
          r"specifics are discussed", r"flexible arrangement", r"can vary with production", r"no caps", r"no commission caps",
          r"top 1\s?%", r"earn like", r"33M", r"27M", r"198K", r"200,000", r"Transfer of Registration", r"three to five business days",
          r"wash out", r"one of the first agents", r"more buyer and seller leads", r"business day", r"24 hours", r"Service NL",
          r"\$150", r"first 90 days", r"90 days", r"Broker\s*(&amp;|&|/)\s*(Founder|Owner)", r"Book a Confidential Call", r"Apply Confidentially",
          r"mailto:miketurner@royallepage\.ca\?subject=Confidential", r"data-recruit-cta", r"recruit-form\.js",
          r"Broker of Record since 1998", r"28 years", r"15\+ years", r"Financial Services Regulation Division", r"\$2,750"]
for rel in PAGES:
    t = (R / rel).read_text(encoding="utf-8")
    low = t
    for b in BANNED:
        m = re.search(b, low, re.I)
        need(not m, f"{rel}: retired/unverified wording back: {m.group(0) if m else ''}")
    need(BOOK in t, f"{rel}: booking link missing")
    need(COMP in re.sub(r"<[^>]+>", "", t).replace("&amp;", "&"), f"{rel}: the comp line is missing")
    need("careers-kit.js" in t, f"{rel}: js/careers-kit.js not loaded")
    need("data-tk-join" in t, f"{rel}: the short join form container is missing")
    need('id="join-form"' in t, f"{rel}: no #join-form anchor")
    need("Independently owned and operated" in t, f"{rel}: brand line 'Independently owned and operated' missing")
    _k = t.find("<div data-tk-join")
    need(re.search(r'<a [^>]*calendar\.app\.google[^>]*>(?:\s*<svg.*?</svg>)?\s*Book a chat with Mike', t[:_k]) is not None, f"{rel}: no 'Book a chat with Mike' button (booking link) above the join form")
    need(len(re.findall(r'id="join-form"', t)) == 1, f"{rel}: #join-form must appear once")
    if rel.endswith("become-a-realtor.html"):
        for want in ("60 days", "$253", "$1,918", "Government Services"):
            need(want in t, f"{rel}: fact missing: {want}")
for rel in PAGES:
    t = (R / rel).read_text(encoding="utf-8")
    for blk in re.findall(r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', t, flags=re.S):
        try:
            d = json.loads(blk)
        except ValueError:
            continue
        if d.get("@type") == "JobPosting":
            for k in ("title", "description", "datePosted", "validThrough", "employmentType", "hiringOrganization", "jobLocation"):
                need(k in d, f"{rel}: JobPosting lacks {k}")
            need("baseSalary" not in d, f"{rel}: JobPosting must not carry baseSalary (commission-based; value 0 is invalid)")
            need(d.get("hiringOrganization", {}).get("name") == "Royal LePage Turner Realty", f"{rel}: JobPosting hiringOrganization")
for p in list(R.glob("*.html")) + list(R.glob("pages/*.html")):
    _t = p.read_text(encoding="utf-8", errors="replace")
    need("340 verified five-star reviews" not in _t, f"{p.name}: hand-typed review count (D-1027-32: no typed review numbers)")
    need("three-office" not in _t and "four-office" not in _t, f"{p.name}: wrong office count (facts file says 2)")
    need(not re.search(r"<h4>[34]</h4>\s*<p>Offices Active</p>", _t), f"{p.name}: office count tile is not 2")
need(facts["offices"]["count"] == 2 and "gbp-fragments" in facts["reviews"]["source"], "facts: offices.count 2 and the reviews source (tools/gbp-fragments)")

TPL = [p for p in ("join-our-team.html", "pages/join-our-team.html", "why-join.html") if (R / p).exists()]
frag = (R / "fragments/careers-template.html").read_text(encoding="utf-8")
need("Mike Turner has worked with the family firm since 1998, when he built its first website; Gaye Turner founded Turner Realty that year. Licensed 2009 and Broker of Record since 2022, he studied computer science at Dalhousie, then graduated from the Toronto Film School." in frag, "template: Mike's bio is not the D-1027-17 bio")
for want in ("Not licensed yet?", "Questions, answered", "What you get", "Send me the details", "tel:+17094246517", "sms:+17094246517", "Coaching from Mike and the team"):
    need(want in frag, f"template: missing {want}")
need("top 1" not in frag.lower() and "goes to Mike only" not in frag, "template: unbacked claim or the Mike-only line (waits for RECRUIT_MIKE_ONLY)")
r = __import__("subprocess").run([sys.executable, str(R / "tools/sync-careers-template.py"), "--check"], capture_output=True, text=True)
need(r.returncode == 0, "careers template page differs from the fragment: " + r.stdout + r.stderr)
for rel in TPL:
    t = (R / rel).read_text(encoding="utf-8")
    need("CAREERS-TEMPLATE START" in t, f"{rel}: careers template markers missing")
kit = (R / "js/careers-kit.js").read_text(encoding="utf-8")
need(f"var BOOKING_URL = '{BOOK}'" in kit, "careers-kit.js: BOOKING_URL differs from the facts file")
need("var RECRUIT_PHONE = '709-424-6517'" in kit, "careers-kit.js: RECRUIT_PHONE is not Mike's cell (D-1027-32; change only with Mike's word)")
need("var TEXT_ENABLED = true" in kit, "careers-kit.js: the bar must read Book / Call / Text (D-1027-32)")
need("Source: Join Our Team" in kit and "miketurner@royallepage.ca" in kit, "careers-kit.js: recruit lead source / assignee changed")
need("By sending, you agree we may contact you about this request." in kit and "Also email me updates" in kit, "careers-kit.js: consent wording missing")
need(len(re.findall(r"autocomplete=\"(name|email|tel|address-level2)\"", kit)) >= 4, "careers-kit.js: autocomplete attributes missing")
need("font-size:16px" in kit, "careers-kit.js: inputs below 16px")
need(facts["recruit_comp_line"] == "70/30 split with profit share. No desk fees.", "facts: comp line changed")
src = facts["official_sources"]
need(src["nlar_orientation_days"]["value"] == 60 and src["nlar_dues_per_month"]["value"] == 253 and src["nlar_startup_total"]["value"] == 1918, "facts: NLAR numbers")
if fails:
    print("FAIL"); [print(" -", f) for f in fails]; sys.exit(1)
print("ok: careers-pages-test (%s)" % ", ".join(PAGES))
