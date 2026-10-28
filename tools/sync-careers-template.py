#!/usr/bin/env python3
"""sync-careers-template.py -- render fragments/careers-template.html (design 2, option A; Mike D-1027-43) into each careers page that
carries the markers, and keep that page's FAQPage JSON-LD equal to the visible FAQ. Byte-identical on all five site repos (always-on #27).

  <!-- CAREERS-TEMPLATE START eyebrow="..." h1="..." guide="..." -->  ...rendered block...  <!-- CAREERS-TEMPLATE END -->

Default = inject; --check = exit 1 if a page differs from what the fragment renders (or no page carries the markers).
Pages looked at: join-our-team.html, pages/join-our-team.html, why-join.html."""
import html, json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
PAGES = ["join-our-team.html", "pages/join-our-team.html", "why-join.html"]
FRAG = (ROOT / "fragments" / "careers-template.html").read_text(encoding="utf-8")
RX = re.compile(r"(<!-- CAREERS-TEMPLATE START ([^>]*?) -->\n)([\s\S]*?)(<!-- CAREERS-TEMPLATE END -->)")
check = "--check" in sys.argv

def render(attrs):
    a = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
    out = FRAG
    for k, ph in (("eyebrow", "{{EYEBROW}}"), ("h1", "{{H1}}"), ("guide", "{{GUIDE}}")):
        out = out.replace(ph, a[k])
    return out

def faq_jsonld(rendered):
    items = []
    for q, ans in re.findall(r"<details[^>]*><summary>(.*?)</summary><p>(.*?)</p></details>", rendered, re.S):
        items.append({"@type": "Question", "name": html.unescape(q), "acceptedAnswer": {"@type": "Answer", "text": html.unescape(ans)}})
    return json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": items}, ensure_ascii=False, indent=2)

found = bad = 0
for rel in PAGES:
    p = ROOT / rel
    if not p.exists():
        continue
    t = p.read_text(encoding="utf-8")
    m = RX.search(t)
    if not m:
        continue
    found += 1
    rendered = render(m.group(2))
    new = t[:m.start(3)] + rendered + t[m.end(3):]
    jl = '<script type="application/ld+json">\n' + faq_jsonld(rendered) + '\n</script>'
    new = re.sub(r'<script type="application/ld\+json">\s*\{[^<]*?"@type":\s*"FAQPage"[\s\S]*?</script>', lambda _m: jl, new, count=1)
    if check:
        if new != t:
            print("ERROR: %s differs from fragments/careers-template.html; run tools/sync-careers-template.py" % rel); bad += 1
    elif new != t:
        p.write_text(new, encoding="utf-8"); print("rendered " + rel)
if found == 0:
    sys.exit("ERROR: no page carries the CAREERS-TEMPLATE markers")
if bad:
    sys.exit(1)
if check:
    print("ok: %d page(s) match the careers template" % found)
