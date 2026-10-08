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
]

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
