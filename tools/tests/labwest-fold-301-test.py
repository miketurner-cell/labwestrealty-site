#!/usr/bin/env python3
"""STRICT 4750 -- Lab West folds into royallepageturner.com: one-hop 301s (sites, D-1118-71). Offline. Exits 1 on drift.

Reads tools/rollup/labwest-301-map.csv (SEO's map). Checks: every 301 row is in _redirects with the exact target and
status 301! (www rows host-specific), except rows targeting /join-our-team#labrador-west, which are HELD and must NOT be
redirected yet; no chains (no target path on this site is itself redirected); LEAVE paths are never redirected; /agent keeps
its KEEP rule; the only catch-alls are the two D-1119-87 ones, last, to the Lab West page; kept-served files have 200 pass-through rules.
"""
import csv
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
HOLD = "#labrador-west"
HOSTS = {"labwestrealty.com", "www.labwestrealty.com"}
fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


rules = {}  # (host, path) -> (target, status); host '' = any host
for ln in (ROOT / "_redirects").read_text().splitlines():
    ln = ln.strip()
    if not ln or ln.startswith("#"):
        continue
    parts = ln.split()
    if len(parts) < 3:
        continue
    src, dst, st = parts[0], parts[1], parts[2]
    if src.startswith("http"):
        u = urlparse(src)
        rules[(u.netloc, u.path or "/")] = (dst, st)
    else:
        rules[("", src)] = (dst, st)

rows = list(csv.DictReader(open(ROOT / "tools/rollup/labwest-301-map.csv")))
ship = [r for r in rows if r["action"] == "301" and not r["target_url"].endswith(HOLD)]
held = [r for r in rows if r["action"] == "301" and r["target_url"].endswith(HOLD)]
# D-1119-80 (c): the 4 why-join rows now ship (to /join-our-team, no #labrador-west anchor): 54 ship, 0 held.
check("map has 59 x 301 rows (59 ship, 0 held)", len(ship) == 59 and len(held) == 0, f"{len(ship)}/{len(held)}")

bad = []
for r in ship:
    u = urlparse(r["source_url"])
    key = (u.netloc if u.netloc == "www.labwestrealty.com" else "", u.path or "/")
    got = rules.get(key)
    if got != (r["target_url"], "301!"):
        bad.append((r["source_url"], got))
check("every shipped 301 row is present, exact target, 301!", not bad, str(bad[:3]))

hb = [r["source_url"] for r in held
      if rules.get(("www.labwestrealty.com" if urlparse(r["source_url"]).netloc.startswith("www") else "", urlparse(r["source_url"]).path))]
check("held rows (target #labrador-west) are not redirected yet", not hb, str(hb))

host_sites = ("labwestrealty.com", "www.labwestrealty.com")
chains = []
for (h, p), (dst, st) in rules.items():
    u = urlparse(dst)
    if st.startswith("301") and (u.netloc in host_sites or (not u.netloc and dst.startswith("/"))):
        if ("", u.path) in rules and not dst.startswith("/.netlify"):
            chains.append((p, dst))
for r in ship:
    u = urlparse(r["target_url"])
    if u.netloc in host_sites:
        chains.append(r["target_url"])
check("no chains: no target on this site is itself redirected", not chains, str(chains[:3]))

leave = ["/.netlify/functions/x", "/robots.txt", "/sitemap.xml", "/sitemap-index.xml", "/googlef17627a5b2522f03.html",
         "/45ca068ef0440f52c7b5bf2618184366.txt"]
# D-1119-87: kept-served files have only a pass-through 200 rule (never a 301) and it sits before the catch-all.
lv = [p for p in leave for h in ("", "www.labwestrealty.com") if (h, p) in rules and rules[(h, p)][1] != "200"]
check("kept-served paths are never redirected (only 200 pass-through)", not lv, str(lv))
check("kept-served pass-through rules exist", all(("", p) in rules for p in leave[1:5] + leave[5:]))
leave_rows = {urlparse(r["source_url"] if r["source_url"].startswith("http") else "https://x/" + r["source_url"]).path for r in rows if r["action"] == "LEAVE"}
check("map LEAVE rows exist (5)", sum(1 for r in rows if r["action"] == "LEAVE") == 5)
check("/agent KEEP rule intact", rules.get(("", "/agent")) == ("https://realestategander.com/agent/", "301!"))
hubwild = [k for k, v in rules.items() if "*" in k[1] and "royallepageturner.com" in v[0]]
check("only the two D-1119-87 catch-alls point at the hub", sorted(hubwild) == [("", "/*"), ("www.labwestrealty.com", "/*")], str(hubwild))
lines = [l.split() for l in (ROOT / "_redirects").read_text().splitlines() if l.strip() and not l.strip().startswith("#")]
check("catch-alls are the last two rules, apex last", [l[0] for l in lines[-2:]] == ["https://www.labwestrealty.com/*", "/*"] and lines[-1][2] == "301!" and lines[-1][1] == "https://royallepageturner.com/pages/labrador-west")
check("/tools/* and /netlify/* stay 404!", rules.get(("", "/tools/*"), ("", ""))[1] == "404!" and rules.get(("", "/netlify/*"), ("", ""))[1] == "404!")

print("FAIL: %d" % len(fails) if fails else "OK")
sys.exit(1 if fails else 0)
