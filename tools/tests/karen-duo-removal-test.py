#!/usr/bin/env python3
"""STRICT 4741 -- Karen Pomeroy and "The Dynamic Duo" are gone from every served file (D-1118-50, Mike 2026-11-18).

Fails if a tracked served file names Karen Pomeroy, her slug, her cell 709-899-1778, "Karen and Roberta" or "Dynamic Duo"
(case-sensitive, so an MLS remark saying "a dynamic duo" is not a hit). D-1118-53: dated history (the Shelter Foundation award
paragraph) keeps her name; that is the explicit allow-list below. Offline. Exits 1 on drift.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOT_SERVED = {"tools", "_research", "4-reference", ".github", "netlify", "_ops", "docs", "fleet", "node_modules", ".git", ".claude", "tests"}
EXT = {".html", ".js", ".json", ".css", ".xml", ".txt", ".svg", ".webmanifest", ".md", ".map"}
PAT = re.compile(r"Karen Pomeroy|karen-pomeroy|Karen and Roberta|Roberta and Karen|Dynamic Duo|dynamic-duo|899-1778|Karen &amp; Roberta")
HISTORY_ALLOW_PREFIX = ("pages/listing-presentation-",)   # the Shelter 2018 award paragraph (dated history, D-1118-53)
fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


hits = []
for p in ROOT.rglob("*"):
    if not p.is_file() or p.suffix not in EXT:
        continue
    rel = p.relative_to(ROOT).as_posix()
    if rel.split("/")[0] in NOT_SERVED or rel.startswith(HISTORY_ALLOW_PREFIX):
        continue
    m = PAT.search(p.read_text(encoding="utf-8", errors="ignore"))
    if m:
        hits.append(f"{rel}: {m.group(0)}")
check("no served file names Karen Pomeroy, her cell or the Dynamic Duo", not hits, "; ".join(hits[:8]))
for p in sorted((ROOT / "pages").glob("listing-presentation-*.html")):
    check(f"{p.name} (history) has no Dynamic Duo branding or cell", not re.search(r"Dynamic Duo|dynamic-duo|899-1778", p.read_text(encoding="utf-8", errors="ignore")))

print("FAILED: " + ", ".join(fails) if fails else "all checks passed")
sys.exit(1 if fails else 0)
