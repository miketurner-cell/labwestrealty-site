#!/usr/bin/env python3
"""Goose Bay office phone on served pages (STRICT 4237, D-1117-15; same test file as Gander's).

Mike 2026-11-17 (D-1117-15, standing): 709-349-7008 is the Goose Bay number on every page of every
site and in structured data; 709-896-5001 is retired as a web phone. The office fax 709-896-0073
(D-1115-14 (1)) stays and is allowed. Fails if any tracked served page (*.html, js/*.js, netlify functions) still
carries 896-5001 in any form (tel:, visible text, JSON-LD telephone). Also pins the 3 JSON-LD
office telephones. Usage: gb-office-phone-test.py [REF]  (REF defaults to the working tree).
"""
import re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ref = sys.argv[1] if len(sys.argv) > 1 else None
PAT = r"896[^0-9]{0,3}5001"
cmd = ["git", "grep", "-nE", PAT] + ([ref] if ref else []) + ["--", "*.html", "js/*.js", "netlify/functions/*.ts"]
r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
hits = [l for l in r.stdout.splitlines() if l.strip()]
print(f"served-page hits of 896-5001: {len(hits)}")
for h in hits[:20]:
    print("  " + h[:160])
bad = len(hits)
if not ref:
    for page in ("index.html", "home-v2/index.html", "pages/about.html"):
        if not (ROOT / page).exists():
            continue
        t = (ROOT / page).read_text(encoding="utf-8")
        if "subOrganization" not in t:
            continue
        i = t.find("Happy Valley-Goose Bay")
        m = re.search(r'"telephone":\s*"([^"]+)"', t[i:]) if i >= 0 else None
        if not m or m.group(1) != "709-349-7008":
            print(f"FAIL {page}: Goose Bay JSON-LD telephone is {m.group(1) if m else None}")
            bad += 1
sys.exit(1 if bad else 0)
