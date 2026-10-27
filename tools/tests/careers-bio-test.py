#!/usr/bin/env python3
"""careers-bio-test.py -- STRICT 2245 (sites, B-1027-07; Mike D-1027-17, 2026-10-27). One bio for Mike Turner on every site:
with the family firm (Turner Realty, founded by Gaye Turner in 1998) since 1998 and built its first website that year; licensed 2009;
Broker of Record since 2022; studied computer science at Dalhousie, then graduated from the Toronto Film School.
Checks tools/brokerage-facts.json and every public page (not listing/property pages) for the retired variants:
"Broker of Record since 1998", a Broker of Record start year other than 2022, a licensed-since year other than 2009,
"Broker/Owner" or "Broker & Founder" for Mike, a number of years ("28 years", "15+ years") given as Mike's own tenure,
and "computer science" / "Film School" stated without the other half of the education line. Byte-identical on all five repos; offline."""
import json, re, sys
from pathlib import Path
R = Path(__file__).resolve().parent.parent.parent
fails = []
def need(c, m):
    if not c: fails.append(m)
facts = json.loads((R / "tools/brokerage-facts.json").read_text(encoding="utf-8"))["mike_turner"]
need(facts["with_family_firm_since"] == 1998 and facts["firm_founded"] == 1998 and facts["licensed"] == 2009 and facts["broker_of_record_since"] == 2022, "facts file: bio years changed")
need("Dalhousie" in facts["education"] and "Toronto Film School" in facts["education"], "facts file: education line")
SKIP = ("listings/", "property/", "_archive/", "_research/", "_ops/", ".claude/", "node_modules/", "fleet/")
BIO_NAMES = {"mike-turner.html", "about.html", "team.html", "about-turner.html", "become-a-realtor.html", "first-year-realtor-nl.html",
             "join-our-team.html", "why-join.html", "index.html"}
pages = [p for p in R.rglob("*.html") if not any(str(p.relative_to(R)).startswith(s) for s in SKIP)]
need(pages, "no pages found")
for p in pages:
    rel = str(p.relative_to(R))
    t = p.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)\b[\s\S]*?</\1>", "", t))).replace("&amp;", "&")
    for m in re.finditer(r"Broker of Record since (\d{4})", text):
        need(m.group(1) == "2022", f"{rel}: Broker of Record since {m.group(1)}")
    for bad in ("28 years in the business", "Broker & Founder", "Broker of Record for 28"):
        need(bad not in text, f"{rel}: retired bio wording: {bad}")
    if p.name in BIO_NAMES:
        need("Broker/Owner" not in text, f"{rel}: Broker/Owner (Mike is Broker of Record)")
        for m in re.finditer(r"(?:Mike (?:Turner )?(?:has been |was )?[Ll]icen[cs]ed (?:in|since)|earning his licence in|Licensed since|licensed since) (\d{4})(?= and (?:has served as )?Broker|\. Broker|$|[.,;])", text):
            if "Broker" in text[m.end():m.end() + 40] or "Mike" in text[max(0, m.start() - 12):m.end()] or "earning his" in m.group(0):
                need(m.group(1) == "2009", f"{rel}: Mike licensed {m.group(1)}")
        if re.search(r"computer science", text, re.I):
            need("Dalhousie" in text and "Toronto Film School" in text, f"{rel}: computer science without 'Dalhousie' and 'Toronto Film School'")
        if "Mike" in text and re.search(r"Mike[^.]{0,100}15\+ years|15\+ years[^.]{0,60}Mike", text):
            need(False, f"{rel}: '15+ years' as Mike's tenure")
if fails:
    print("FAIL"); [print(" -", f) for f in sorted(set(fails))]; sys.exit(1)
print("ok: careers-bio-test (%d pages)" % len(pages))
