#!/usr/bin/env python3
"""STRICT 2969 (same number as Gander's gb-team-label-test.py): the Goose Bay team label is "Turner Realty Team" in this
repo's consumer-facing files (Goose Bay team label, preview, held). Static check: none of these files may say "Dynamic Duo".
Exits 1 on drift."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FILES = ['netlify/functions/chat.ts', 'js/boldtrail-forms.js', 'tools/build-community-pages.py', 'tools/build-market-stats-page.py']
fails = []
for rel in FILES:
    t = (ROOT / rel).read_text()
    bad = "dynamic duo" in t.lower()
    print(("FAIL " if bad else "PASS ") + rel + " has no Dynamic Duo")
    if bad:
        fails.append(rel)

sys.exit(1 if fails else 0)
