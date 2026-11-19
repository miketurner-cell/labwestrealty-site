#!/usr/bin/env python3
"""STRICT 4779 -- Karen, Roberta and the Dynamic Duo old URLs go in ONE hop to the hub's Goose Bay page (D-1119-122).

Offline checks:
  1. every _redirects rule for a karen/roberta/duo path is a 301! to https://royallepageturner.com/pages/happy-valley-goose-bay
     (no on-site target, so no chain), and the core old paths are all present;
  2. no sitemap lists those URLs (a sitemap must not list a redirect);
  3. no served .html page carries RealEstateAgent/Person JSON-LD, or a schema name/brand, naming them.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HUB = "https://royallepageturner.com/pages/happy-valley-goose-bay"
fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


rules = [l.split() for l in (ROOT / "_redirects").read_text().splitlines()
         if l.strip() and not l.startswith("#") and re.search(r"karen|roberta|duo|pomeroy|primmer", l.split()[0], re.I)
         and "/listings/" not in l.split()[0]]
check("redirect rules found for the former agents", len(rules) >= 5, len(rules))
bad = [r for r in rules if len(r) < 3 or r[1] != HUB or not r[2].startswith("301")]
check("every old path is a single 301 to the hub Goose Bay page", not bad, bad[:3])
have = {r[0] for r in rules}
need = {"/karen-pomeroy", "/pages/karen-pomeroy.html", "/roberta-primmer", "/pages/roberta-primmer.html", "/pages/dynamic-duo.html"}
check("core old paths are covered", need <= have, need - have)

PAT = re.compile(r"karen-pomeroy|roberta-primmer|dynamic-duo|Dynamic Duo|Karen Pomeroy|Roberta Primmer", re.I)
hits = [p.name for p in ROOT.glob("sitemap*.xml") if PAT.search(p.read_text(errors="ignore"))]
check("no sitemap lists them", not hits, hits)

LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
bad_pages = []
skip = {"tools", "_research", "4-reference", ".git", "node_modules", "_wt", "worktrees", ".claude", "_archive", "pages"}
for p in ROOT.rglob("*.html"):
    rel = p.relative_to(ROOT)
    if rel.parts[0] in skip and not (rel.parts[0] == "pages"):
        continue
    t = p.read_text(errors="ignore")
    for m in LD.finditer(t):
        if re.search(r"Karen Pomeroy|Roberta Primmer|Dynamic Duo|Pomeroy|Primmer", m.group(1)):
            bad_pages.append(str(rel))
check("no JSON-LD names them (RealEstateAgent, Person, name, brand)", not bad_pages, bad_pages[:5])
if fails:
    print("FAILED:", "; ".join(fails))
    sys.exit(1)
print("ok")
