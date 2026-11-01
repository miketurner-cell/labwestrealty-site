#!/usr/bin/env python3
"""Cloud sun-1 SEO (2026-11-01, "hub and Lab West titles only"): every indexable Lab West page has a <title> of at
most 60 characters, no two indexable pages share a title, and become-a-realtor.html leads with the town.
Run: python3 tools/tests/cloud-labwest-titles-test.py   Exit 0 = all pass."""
import html, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*.html"], capture_output=True, text=True, check=True).stdout.split()
fail, seen = [], {}
for rel in files:
    if re.match(r"(_research|tools|fragments)/", rel) or re.fullmatch(r"google[0-9a-f]+\.html", rel):
        continue
    s = (ROOT / rel).read_text(encoding="utf8", errors="replace")
    if re.search(r'name="robots" content="noindex', s):
        continue
    m = re.search(r"<title>(.*?)</title>", s, re.S)
    t = html.unescape(" ".join(m.group(1).split())) if m else ""
    if not t or len(t) > 60:
        fail.append(f"{rel}: title {len(t)} chars: {t!r}")
    if t in seen:
        fail.append(f"{rel}: same title as {seen[t]}: {t!r}")
    seen.setdefault(t, rel)
br = (ROOT / "become-a-realtor.html").read_text(encoding="utf8")
og = re.search(r'<meta property="og:title" content="([^"]*)"', br)
title = html.unescape(re.search(r"<title>(.*?)</title>", br).group(1))
if not title.startswith("Labrador West") or not og or html.unescape(og.group(1)) != title:
    fail.append(f"become-a-realtor: title {title!r} / og:title {og and og.group(1)!r}")
if fail:
    print("FAIL cloud-labwest-titles-test:")
    for f in fail:
        print("  -", f)
    sys.exit(1)
print(f"ok cloud-labwest-titles-test ({len(seen)} indexable titles)")
