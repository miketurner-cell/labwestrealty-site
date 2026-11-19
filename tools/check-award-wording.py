#!/usr/bin/env python3
"""Award-wording guard (D-1008-66, 2026-10-08).

Fails (exit 1) when a served page carries award wording the Royal LePage record
does not support, or lists awards without the trademark notice:

  - "Atlantic" as an award region (the record's region is "East Coast")
  - "Lead Manager of the Year" (not in any published Royal LePage list)
  - "brokerage by units" (the #43 rank is the Turner Realty Team's, in the
    National Chairman's Club, not a brokerage rank)
  - Executive Circle with 2022 (record: East Coast 2023, 2024, 2025)
  - Award of Excellence "2023-2025" (record: Michael Turner 2022-2025)
  - a page that names an award but lacks "rlp.ca/notices"
  - award leftovers with no source (D-1008-91, 2026-10-08): "104 deals", "178 sales", "97.95%",
    "5 Wing Military Relocation", the Shelter Foundation "$50M+"

There is no existing test pattern or workflow in this repo that runs page
checks, so this stands alone: python3 tools/check-award-wording.py
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AWARD_WORDS = re.compile(
    r"chairman|top ten|top 10|executive circle|award of excellence|best in tech|"
    r"brokerage of the year|top 1%|\baward", re.I)
AWARD_NAMES = re.compile(
    r"chairman.{0,3}s club|top ten|executive circle|award of excellence|best in tech|"
    r"brokerage of the year", re.I)
DASH = r"[–—-]|&ndash;|&mdash;"

RULES = [
    ("'Atlantic' used with an award (record region is East Coast)",
     lambda line: re.search("atlantic", line, re.I) and AWARD_WORDS.search(line)),
    ("'Lead Manager of the Year' (not in any published Royal LePage list)",
     lambda line: re.search(r"lead manager of the year", line, re.I)),
    ("'brokerage by units' (#43 is the Turner Realty Team's Chairman's Club rank)",
     lambda line: re.search(r"brokerage by units", line, re.I)),
    ("Executive Circle with 2022 (record: East Coast 2023, 2024, 2025)",
     lambda line: re.search(r"executive circle", line, re.I) and re.search(r"2022", line)),
    ("Award of Excellence 2023-2025 (record: Michael Turner 2022-2025)",
     lambda line: re.search(r"award of excellence", line, re.I)
     and re.search(r"2023\s*(?:%s)\s*2025" % DASH, line)),
    # Award leftovers with no source (Mike, D-1008-91, 2026-10-08: keep a claim only where the Shelter Foundation's own
    # site, the agent's royallepage.ca profile or the RLP award record supports it).
    ("'104 deals' (undated whole-brokerage figure, no source; D-1008-91)",
     lambda line: re.search(r"(?<![\d,.])104\s+deals\b", line, re.I)),
    ("'178 sales' (unsourced 2025 market figure; D-1008-91)",
     lambda line: re.search(r"(?<![\d,.])178\s+(?:residential\s+)?sales\b", line, re.I)),
    ("'97.95%' (unsourced 2025 sale-to-list figure; D-1008-91)",
     lambda line: re.search(r"(?<![\d.])97\.95\s?%", line)),
    ("'5 Wing Military Relocation' (5 Wing personnel cannot buy or sell; D-1008-38/91)",
     lambda line: re.search(r"5\s+Wing\s+Military\s+Relocation", line)),
    ("Shelter Foundation '$50M+' (the Foundation says more than $57 million; D-1008-91)",
     lambda line: re.search(r"\$\s?50\s?M\+", line)),
]
for _bad in ("closed 104 deals", "a 97.95% ratio", "178 residential sales",
             "5 Wing Military Relocation", "$50M+ raised"):
    assert any(test(_bad) for _, test in RULES), f"self-check: should flag {_bad!r}"
for _good in ("1,104 deals", "97.9%", "$57M+", "BGRS closed 1 October 2026"):
    assert not any(test(_good) for _, test in RULES), f"self-check: should pass {_good!r}"

problems = []
files = sorted(glob.glob(os.path.join(ROOT, "*.html")) + glob.glob(os.path.join(ROOT, "pages", "*.html")))
for path in files:
    rel = os.path.relpath(path, ROOT)
    text = open(path, encoding="utf-8").read()
    for n, line in enumerate(text.splitlines(), 1):
        for label, test in RULES:
            if test(line):
                problems.append(f"{rel}:{n}: {label}")
    if AWARD_NAMES.search(text) and "rlp.ca/notices" not in text:
        problems.append(f"{rel}: names an award but lacks the rlp.ca/notices trademark notice")

if problems:
    print("AWARD WORDING CHECK FAILED")
    for p in problems:
        print("  " + p)
    sys.exit(1)
print(f"award wording check OK ({len(files)} pages)")
