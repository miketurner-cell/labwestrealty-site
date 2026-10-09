#!/usr/bin/env python3
"""Unsourced-claims guard (D-1009-67, 2026-10-09).

Mike: "Remove until sourced": these Lab West claims come back only with a
cited source (always-on #35: never fabricate statistics; deriving one is
fabricating it). Fails (exit 1) when a served page carries one of them on a
line without a citation:

  - "underserved" / "under-served" market claims
    (e.g. "One of Canada's Most Underserved Real Estate Markets")
  - a "Growing" stat tile (<div class="stat-num">Growing</div>)
  - the population figure "10,000" for Labrador City + Wabush
  - an "average brokerage commission" percentage (e.g. "~4.5%")
  - an agent income estimate such as "~$73K–$100K annually"

A line counts as cited when it carries data-source="..." or a <cite> element
naming the source. The NLAR MLS market figures on market-stats.html are
sourced (hero source line + data disclaimer) and are not matched here.

Lab West has no CI, so run it by hand before merging:
    python3 tools/check-unsourced-claims.py
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CITED = re.compile(r'data-source="[^"]+"|<cite\b', re.I)
DASH = r"(?:[–—-]|&ndash;|&mdash;)"

RULES = [
    ("'underserved' market claim", re.compile(r"under-?served", re.I)),
    ("'Growing' stat tile", re.compile(r'class="stat-num">\s*Growing\s*<', re.I)),
    ("population '10,000' (Lab City + Wabush)",
     re.compile(r"(?:population[^<]{0,40}10,000|10,000[^<]{0,20}residents|"
                r'stat-num">\s*10,000\s*<)', re.I)),
    ("average brokerage commission percentage",
     re.compile(r"\d+(?:\.\d+)?\s*%\s*average brokerage commission|"
                r"average brokerage commission[^<]{0,20}\d+(?:\.\d+)?\s*%", re.I)),
    ("agent income estimate ($NK-$NK annually)",
     re.compile(r"\$\d+K\s*" + DASH + r"\s*\$\d+K\s*(?:annually|a year|per year)", re.I)),
]


def main():
    pages = sorted(p for p in glob.glob(os.path.join(ROOT, "**", "*.html"), recursive=True)
                   if os.sep + "_archive" + os.sep not in p and os.sep + "tools" + os.sep not in p)
    findings = []
    for path in pages:
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if CITED.search(line):
                    continue
                for label, rx in RULES:
                    if rx.search(line):
                        findings.append(f"{os.path.relpath(path, ROOT)}:{n}: {label} without a cited source")
    if findings:
        print("unsourced claims FOUND (add data-source=\"...\" or <cite> with the source, or remove):")
        for f in findings:
            print("  " + f)
        sys.exit(1)
    print(f"unsourced claims check OK ({len(pages)} pages)")


if __name__ == "__main__":
    main()
