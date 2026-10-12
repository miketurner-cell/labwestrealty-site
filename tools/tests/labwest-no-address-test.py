#!/usr/bin/env python3
"""STRICT: no Lab West street address anywhere (sites, D-1012-34; always-on #33/#34).

Lab West has no physical office. The brokerage contact is Mike Turner, Broker of Record, Royal LePage Turner Realty,
miketurner@royallepage.ca, 709-256-7999 -- no street address. This fails when:
  1. a hand-written site file (root *.html, js/, css/, tools/ configs and generators; not tests, caches or the generated
     listings/ and property/ trees) puts a street address within one line of "Labrador City", "Wabush" or "Lab West";
  2. a non-listing JSON-LD block (Organization, LocalBusiness, RealEstateAgent...) carries a PostalAddress;
  3. in generated pages (when present), the broker contact surfaces -- listingAgent JSON-LD, the agent card, the print
     footer, the site footer -- carry a street address. (The home's own address on a listing page is the property, not
     the office, and is not checked here.)
Also the known other-office addresses (Goose Bay, Gander HQ) must not appear in generated pages.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
errors = []

STREET = re.compile(
    r"\b\d{1,5}[A-Za-z]?\s+(?:[A-Z][A-Za-z.'-]*\s+){1,3}"
    r"(?:Street|St\.?|Avenue|Ave\.?|Drive|Dr\.?|Road|Rd\.?|Boulevard|Blvd\.?|Crescent|Cres\.?|Place|Pl\.?|Court|Ct\.?|Lane|Ln\.?|Way|Terrace|Trail|Loop)\b"
)
AREA = re.compile(r"Labrador City|Wabush|Lab(?:rador)? West", re.I)
SKIP_DIRS = {".git", ".claude", "node_modules", "listings", "property", "tests", "idx-cache", "ddf-cache", "ddf-fragments", "images"}
OTHER_OFFICES = ("204 Airport Blvd", "371 Hamilton River", "1 Loring Drive", "Hamilton River Road")


def generated_page_files():
    """pages/ files the nightly generates (market statistics, one per community YAML). They show real sold homes' own
    addresses (notable sales), like listing pages, so they get the broker-contact-block checks, not the place-name heuristic."""
    names = {"market-stats.html"}
    cfg = ROOT / "tools" / "community-config"
    if cfg.is_dir():
        names |= {p.stem + ".html" for p in cfg.glob("*.yml")}
    return {ROOT / "pages" / n for n in names}


GEN_PAGES = generated_page_files()


def files():
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix not in (".html", ".js", ".css", ".json", ".py", ".txt", ".xml", ".md", ".toml"):
            continue
        rel = p.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p in GEN_PAGES:
            continue  # checked below with the generated trees
        yield p, rel


GANDER_HQ = re.compile(r"204 Airport Bou?l(?:evard|\\.|vd)?", re.I)


def postal_nodes(obj):
    if isinstance(obj, dict):
        if obj.get("@type") == "PostalAddress":
            yield obj
        for v in obj.values():
            yield from postal_nodes(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from postal_nodes(v)


def lab_west_postal(node):
    if not str(node.get("streetAddress", "")).strip():
        return False  # a town-only address (a Place for Labrador City or Wabush) is not a street address
    loc = str(node.get("addressLocality", ""))
    pc = str(node.get("postalCode", "")).upper().replace(" ", "")
    return bool(AREA.search(loc)) or pc.startswith(("A2V", "A0R"))


for p, rel in files():
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        continue
    for i, line in enumerate(text.splitlines(), 1):
        if AREA.search(line) and STREET.search(GANDER_HQ.sub("", line)):
            # a street name that is only a feed/test fixture or code comment is not caught: be strict, report it
            errors.append(f"{rel}:{i}: street address next to a Lab West place name: {line.strip()[:120]}")
    if p.suffix == ".html":
        for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', text, re.S):
            try:
                d = json.loads(m.group(1))
            except Exception:
                continue
            for node in (d if isinstance(d, list) else [d]):
                if isinstance(node, dict) and node.get("@type") not in ("RealEstateListing", "BreadcrumbList"):
                    for pa in postal_nodes(node):
                        if lab_west_postal(pa):
                            errors.append(f"{rel}: JSON-LD {node.get('@type')} carries a Lab West PostalAddress")

# generated pages, when present
gen_files = []
for d in ("listings", "property"):
    base = ROOT / d
    if base.is_dir():
        gen_files += list(base.rglob("*.html"))
gen_files += [p for p in GEN_PAGES if p.is_file()]
if gen_files:
    for p in gen_files:
        text = p.read_text(encoding="utf-8")
        rel = p.relative_to(ROOT)
        for bad in OTHER_OFFICES:
            if bad in text:
                errors.append(f"{rel}: other office address {bad!r}")
        for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', text, re.S):
            try:
                d_ = json.loads(m.group(1))
            except Exception:
                continue
            if isinstance(d_, dict) and d_.get("@type") in ("Organization", "LocalBusiness", "RealEstateAgent", "Person", "ContactPage", "AboutPage"):
                for pa in postal_nodes(d_):
                    if str(pa.get("streetAddress", "")).strip():
                        errors.append(f"{rel}: JSON-LD {d_.get('@type')} carries a street address")
            la = d_.get("listingAgent") if isinstance(d_, dict) else None
            if la and "PostalAddress" in json.dumps(la):
                errors.append(f"{rel}: listingAgent carries a PostalAddress")
        for cls in ("lst-cta-agent", "lst-print-footer", "site-footer", "vp-office"):
            for m in re.finditer(r'class="[^"]*\b' + cls + r'\b[^"]*"[^>]*>(.*?)</(?:div|footer)>', text, re.S):
                if STREET.search(re.sub(r"<[^>]+>", " ", m.group(1))):
                    errors.append(f"{rel}: street address inside .{cls}")

if errors:
    print("labwest-no-address-test FAILED:")
    for e in errors[:40]:
        print("  -", e)
    sys.exit(1)
print("labwest-no-address-test OK: no Lab West street address in site files or generated broker contact blocks")
