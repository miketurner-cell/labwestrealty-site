#!/usr/bin/env python3
"""STRICT: Lab West listing pages (sites, D-1012-34, component 4) -- dark while off, correct when generated.

A. OFF PROOF on the committed tree. While the switch has never been turned on there is no listings/ or property/
   tree, no generated sitemap, sitemap-index.xml and robots.txt name only the recruiting sitemap, and no hand-written
   page links to /listings or /property. (Once listings/ is committed -- after the flip -- this part reports "flipped" and
   skips: the point is to prove nothing leaks BEFORE the flip.)
B. GENERATED TREE. Copies the repo to a temp dir, runs the real projector and generator over synthetic feed rows
   (tools/tests/fixtures/labwest-feed-rows.json) and checks: only Labrador City + Wabush homes; the lease row is absent;
   a Turner-listed home says "Listed by Mike Turner", another brokerage's home names Mike as the contact and never
   "Listed by"; the contact is miketurner@royallepage.ca / 709-256-7999 only; no Goose Bay office, Dynamic Duo or A0P
   text; the broker JSON-LD has no address; every local href/src resolves; no sold price anywhere.
C. STATE SCRIPT. preview adds noindex to every generated page and registers no sitemap; on registers the generated
   sitemaps and removes the noindex; off touches nothing; a second run changes nothing.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
errors = []


def check(c, m):
    if not c:
        errors.append(m)


# ---------------------------------------------------------------- A
if (ROOT / "listings").is_dir():
    print("A. off proof: skipped (listings/ is committed: the switch has been flipped)")
else:
    check(not (ROOT / "property").exists(), "A: property/ exists while the switch has never been on")
    check(not (ROOT / "home-preview.html").exists(), "A: home-preview.html exists while off")
    check("lwh-" not in (ROOT / "index.html").read_text(), "A: the committed index.html carries the new homepage while off")
    check("sold-data" not in (ROOT / "_redirects").read_text(), "A: _redirects routes sold data while off")
    check(not (ROOT / "pages").exists() and not (ROOT / "sitemap-pages.xml").exists(), "A: pages/ or sitemap-pages.xml exists while off")
    for sm in ("sitemap-listings.xml", "sitemap-property.xml"):
        check(not (ROOT / sm).exists(), f"A: {sm} exists while off")
    idx = (ROOT / "sitemap-index.xml").read_text()
    check(re.findall(r"<loc>([^<]+)</loc>", idx) == ["https://labwestrealty.com/sitemap.xml"], "A: sitemap-index.xml names more than the recruiting sitemap")
    check("listings" not in (ROOT / "sitemap.xml").read_text() and "/property" not in (ROOT / "sitemap.xml").read_text(), "A: sitemap.xml lists a listing or property URL")
    robots = (ROOT / "robots.txt").read_text()
    check("sitemap-listings" not in robots and "sitemap-property" not in robots, "A: robots.txt names a generated sitemap")
    for p in ROOT.glob("*.html"):
        t = p.read_text(encoding="utf-8")
        for m in re.finditer(r'(?:href|src|action)="([^"]*)"', t):
            u = m.group(1)
            if re.match(r"^(?:https://labwestrealty\.com)?/?(?:\.\./)*(?:listings|property)(?:/|$|\.|\?)", u):
                check(False, f"A: {p.name} links to {u}")
    print("A. off proof: committed tree has no listings, no property pages, no generated sitemap, no links to them")

# ---------------------------------------------------------------- B, C
tmp = Path(tempfile.mkdtemp(prefix="lwtest-"))
try:
    work = tmp / "site"
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", ".claude", "node_modules", "__pycache__", "listings", "property"))
    rows = json.loads((ROOT / "tools/tests/fixtures/labwest-feed-rows.json").read_text())["rows"]
    cache = work / "tools" / "idx-cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "listings.json").write_text(json.dumps({"fetched_at": "2026-10-12T18:00:00Z", "rows": rows}))
    # sold cache: Lab West sales plus filler rows so it clears the generator's 1 MB suspect-cache floor (the real cache is the whole board)
    sold_rows = json.loads((ROOT / "tools/tests/fixtures/labwest-sold-rows.json").read_text())["rows"]
    filler = [dict(sold_rows[2], MLSNumber=str(1000000 + i), StreetName="Filler", CityText="Gander", PostalCode="A1V 1L6",
                   Subdistrict="Gander and Area", Latitude="48.95", Longitude="-54.6", PublicRemarks="x" * 400) for i in range(4000)]
    (cache / "sold-listings.json").write_text(json.dumps({"fetched_at": "2026-10-12T00:00:00Z", "rows": sold_rows + filler}))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "R2_BASE_URL": "https://photos.example.test"}
    r = subprocess.run([sys.executable, "tools/idx-project-to-ddf-shape.py"], cwd=work, env=env, capture_output=True, text=True)
    check(r.returncode == 0, f"B: projector failed: {r.stderr[-300:]}")
    r = subprocess.run([sys.executable, "tools/labwest-sold-shell.py"], cwd=work, env=env, capture_output=True, text=True)
    check(r.returncode == 0, f"B: sold shell install failed: {r.stderr[-200:]}")
    r = subprocess.run([sys.executable, "tools/ddf-generate-pages.py"], cwd=work, env=env, capture_output=True, text=True)
    check(r.returncode == 0, f"B: generator failed (exit {r.returncode}): {(r.stdout + r.stderr)[-600:]}")
    check("self-check passed" in r.stdout, "B: the generator's own listings pre-deploy self-check did not pass")

    L = work / "listings"
    pages = sorted(L.rglob("*.html"))
    check(len(pages) > 8, f"B: too few generated pages ({len(pages)})")
    detail = {p.name: p for p in L.glob("*/*-13000*.html")}
    mls = sorted(re.search(r"-(\d{7})\.html", n).group(1) for n in detail)
    check(mls == ["1300001", "1300002", "1300004", "1300005", "1300007", "1300008", "1300009"], f"B: detail page set wrong: {mls}")
    check("1300003" not in mls, "B: the lease row (McGregor, 1300003) has a page")
    check("1300006" not in mls, "B: a Goose Bay row has a page")
    check(not any("3-mcgregor" in str(p) for p in pages), "B: the lease street appears in a page path")
    allhtml = {p: p.read_text(encoding="utf-8") for p in pages}
    joined = "\n".join(allhtml.values())
    check("McGregor" not in joined, "B: the lease row appears on a page")

    ours = next(t for p, t in allhtml.items() if "1300002" in p.name)
    other = next(t for p, t in allhtml.items() if "1300001" in p.name)
    check("Listed by" in ours and "Mike Turner" in ours, "B: a Turner-listed home must say Listed by Mike Turner")
    check("Listed by" not in other.split("lst-cta-agent")[1][:400] if "lst-cta-agent" in other else False, "B: another brokerage's home must not say Listed by")
    check("Questions about this home?" in other and "Mike Turner" in other, "B: another brokerage's home must name Mike as the contact")
    check("Century 21" in other, "B: the listing brokerage must still be shown (CREA)")
    for needle in ("Dynamic Duo", "goosebay", "Goose Bay", "896-5001", "A0P 1", "karen", "roberta", "goosebay@royallepage.ca"):
        check(needle.lower() not in joined.lower(), f"B: generated pages contain {needle!r}")
    check("miketurner@royallepage.ca" in joined and "709-256-7999" in joined, "B: Mike's contact is missing")
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", joined))
    check(emails <= {"miketurner@royallepage.ca"}, f"B: unexpected email addresses in generated pages: {sorted(emails - {'miketurner@royallepage.ca'})}")
    check(not re.search(r"close_?price|ClosePrice", joined), "B: a close price field reached a page")

    # JSON-LD broker block has no address
    for p, t in allhtml.items():
        if p.name.startswith("14-grenfell"):
            for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', t, re.S):
                d = json.loads(m.group(1))
                la = d.get("listingAgent")
                if la:
                    check("address" not in json.dumps(la).lower(), "B: listingAgent JSON-LD carries an address")
                    check(la.get("name") == "Mike Turner" and "Royal LePage Turner Realty" in json.dumps(la), "B: listingAgent must be Mike + brokerage")
                    break
            else:
                check(False, "B: no listingAgent JSON-LD on a detail page")

    # sold surface: ungated facts only, no sold price anywhere in any generated file (CREA 5(k) / VOW)
    gen_files = [p for d in ("listings", "property") for p in (work / d).rglob("*") if p.is_file() and p.suffix in (".html", ".json", ".xml")]
    blob = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in gen_files)
    for sr in sold_rows:
        cp = int(float(sr["ClosePrice"]))
        check(str(cp) not in blob.replace(",", "") or str(cp) in {str(int(float(x["ListPrice"]))) for x in sold_rows}, f"B: a sold price ({cp}) appears in a generated file")
    check(not re.search(r'"close_price"|"sold_price"|"sa_ratio"', blob), "B: a sold-price key reached a generated file")
    sold_index = (work / "listings" / "sold" / "index.html").read_text()
    check("sold-public-table" in sold_index and "/property/labrador-city/" in sold_index, "B: the sold index must list recent sales with property links")
    check("Hamilton" not in sold_index and "Goose" not in sold_index and "896-5001" not in sold_index, "B: Goose Bay text in the sold shell")
    check(len(list((work / "property").rglob("*.html"))) >= 20, "B: too few property (sold record) pages")
    sdata = json.loads((work / "listings" / "sold" / "data.json").read_text())
    check(len(sdata["rows"]) == 28, f"B: sold data.json should hold the 28 published in-scope sales, has {len(sdata['rows'])}")
    check(all(r.get("city_slug") in ("labrador-city", "wabush") for r in sdata["rows"]), "B: a sold row outside Labrador City / Wabush")

    # homepage (component 7): built from the generated data only; the default output is a preview copy, never index.html
    idx_before = (work / "index.html").read_bytes()
    r = subprocess.run([sys.executable, "tools/build-labwest-home.py"], cwd=work, env=env, capture_output=True, text=True)
    check(r.returncode == 0, f"B: homepage builder failed: {(r.stdout + r.stderr)[-300:]}")
    check((work / "index.html").read_bytes() == idx_before, "B: the homepage builder touched index.html without --out index.html")
    home = work / "home-preview.html"
    check(home.exists(), "B: no home-preview.html")
    if home.exists():
        ht = home.read_text(encoding="utf-8")
        plain = re.sub(r"<style.*?</style>|<script.*?</script>", "", ht, flags=re.S)
        # for sale = rows that are not pending; the fixture has 6 for sale + 1 under contract among the in-scope homes
        check(re.search(r"<b>6</b><span>homes for sale \(1 more under contract\)", plain) is not None, "B: homepage for-sale/pending counts differ from the projected rows")
        sold_year = [x for x in sdata["rows"] if (x.get("sold_date") or "") >= "2025-10-12"]
        check(f"<b>{len(sold_year)}</b><span>sold in the last 12 months" in plain, f"B: homepage sold-in-12-months count is not {len(sold_year)}")
        check("Source: NLAR MLS" in plain and "as of Oct 12, 2026" in plain, "B: homepage must show its source and the feed date")
        check("Listed at $" in plain and "see what it sold for when you register" in plain, "B: sold cards must show the asking price and the register prompt")
        check("McGregor" not in ht, "B: the lease row appears on the homepage")
        for needle in ("Dynamic Duo", "goosebay", "Goose Bay", "896-5001", "Hamilton", "204 Airport"):
            check(needle.lower() not in ht.lower(), f"B: homepage contains {needle!r}")
        for sr in sold_rows:
            check(str(int(float(sr["ClosePrice"]))) not in ht.replace(",", "") or str(int(float(sr["ClosePrice"]))) in {str(int(float(x["ListPrice"]))) for x in sold_rows}, "B: a sold price is on the homepage")
        allhtml[home] = ht
    r = subprocess.run([sys.executable, "tools/build-labwest-home.py", "--out", "index.html"], cwd=work, env=env, capture_output=True, text=True)
    check(r.returncode == 0 and (work / "index.html").read_bytes() != idx_before, "B: --out index.html must write the new homepage")
    (work / "index.html").write_bytes(idx_before)  # restore the recruiting page for the rest of the checks

    # every local href/src resolves
    miss = set()
    for p, t in allhtml.items():
        for m in re.finditer(r'(?:href|src)="([^"#?]+?)(?:\?[^"]*)?"', t):
            u = m.group(1)
            if u.startswith(("http", "//", "mailto", "tel", "data:", "javascript")):
                continue
            tgt = (work / u.lstrip("/")) if u.startswith("/") else (p.parent / u)
            tgt = tgt.resolve()
            if u.endswith("/"):
                tgt = tgt / "index.html"
            if not tgt.exists() and not tgt.with_name(tgt.name + ".html").exists():  # Netlify pretty URLs: /property/x/y -> y.html
                miss.add(u)
    check(not miss, f"B: dead local links in generated pages: {sorted(miss)[:8]}")

    # the no-address test also passes on the generated tree
    r = subprocess.run([sys.executable, str(work / "tools/tests/labwest-no-address-test.py")], capture_output=True, text=True)
    check(r.returncode == 0, f"B: no-address test fails on the generated tree: {r.stdout[-400:]}")

    # alerts (component 8): off by default, and only when the backend is ready
    check("alert-inline" not in joined and "data-lta" not in joined and "saved-search.js" not in joined and "save-nudge.js" not in joined,
          "B: alerts markup or scripts are emitted while backend_ready is false")
    check(not (work / "pages" / "text-alerts.html").exists(), "B: a text-alerts page exists while backend_ready is false")
    flag = work / "tools" / "labwest-alerts.json"
    flag_off = flag.read_text()
    flag.write_text(json.dumps({"backend_ready": True}))
    r = subprocess.run([sys.executable, "tools/labwest-alerts-page.py"], cwd=work, env=env, capture_output=True, text=True)
    check(r.returncode == 0 and (work / "pages" / "text-alerts.html").exists(), f"B: text-alerts page not installed when ready: {r.stderr[-200:]}")
    r = subprocess.run([sys.executable, "tools/ddf-generate-pages.py"], cwd=work, env=env, capture_output=True, text=True)
    check(r.returncode == 0, "B: generator failed with alerts ready")
    ready_html = "\n".join(p.read_text(encoding="utf-8") for p in (work / "listings").rglob("*.html"))
    check("alert-inline.js" in ready_html and "data-lta-inline" in ready_html and "Listing Text Alerts" in ready_html, "B: alerts markup missing when ready")
    check("window.TURNER_SITE='labwest'" in ready_html, "B: pages must set TURNER_SITE to labwest before the alert scripts")
    ta = (work / "pages" / "text-alerts.html").read_text(encoding="utf-8")
    check("Listing Text Alerts" in ta and "data-lta-inline" in ta and "TURNER_SITE='labwest'" in ta, "B: text-alerts page lacks the widget or the site id")
    for needle in ("Goose Bay", "goosebay", "Hamilton", "896-5001", "Dynamic Duo"):
        check(needle.lower() not in ta.lower(), f"B: text-alerts page contains {needle!r}")
    import re as _re
    for txt in (ta, ready_html):
        plain_t = _re.sub(r"<style.*?</style>|<script.*?</script>", "", txt, flags=_re.S)
        check(not _re.search(r"(?<!Listing )(?<!Listing\xa0)\b(?:sms|text) alerts\b", plain_t, _re.I), "B: a bare 'text alerts' or 'SMS alerts' name (use Listing Text Alerts)")
    subprocess.run([sys.executable, "tools/labwest-listings-state.py", "preview"], cwd=work, check=True, capture_output=True)
    check("/text-alerts   /pages/text-alerts.html   200" in (work / "_redirects").read_text(), "B: the /text-alerts redirect is missing while the page exists")
    flag.write_text(flag_off)
    shutil.rmtree(work / "pages" / "text-alerts.html", ignore_errors=True) if (work / "pages" / "text-alerts.html").is_dir() else (work / "pages" / "text-alerts.html").unlink()
    r = subprocess.run([sys.executable, "tools/ddf-generate-pages.py"], cwd=work, env=env, capture_output=True, text=True)
    check(r.returncode == 0, "B: generator failed after resetting alerts")
    subprocess.run([sys.executable, "tools/labwest-listings-state.py", "preview"], cwd=work, check=True, capture_output=True)
    check("/text-alerts" not in (work / "_redirects").read_text(), "B: the /text-alerts redirect stays after the page is gone")

    # ------------------------------------------------------------ C
    idx0 = (work / "sitemap-index.xml").read_text()
    red0 = (work / "_redirects").read_text()
    st = [sys.executable, str(work / "tools/labwest-listings-state.py")]
    r0 = subprocess.run(st + ["off", "--root", str(work)], capture_output=True, text=True)
    check(r0.returncode == 0 and (work / "sitemap-index.xml").read_text() == idx0, "C: off must change nothing")
    subprocess.run(st + ["preview", "--root", str(work)], check=True, capture_output=True)
    gen = [p for p in work.glob("listings/**/*.html")]
    check('content="noindex,nofollow"' in (work / "home-preview.html").read_text(), "C: preview must noindex home-preview.html")
    check(all('<meta name="robots" content="noindex,nofollow">' in p.read_text() for p in gen), "C: preview must noindex every generated page")
    check((work / "sitemap-index.xml").read_text() == idx0, "C: preview must not register sitemaps")
    red1 = (work / "_redirects").read_text()
    check(red1.count("lab-west-sold-gate") == 2 and "/listings/sold/data.json            /.netlify/functions/sold-data?f=data.json  200!" in red1, "C: preview must put the sold-gate rewrites in _redirects")
    check(red1.endswith(red0.lstrip("\n")) or red0 in red1, "C: the sold-gate block must not remove existing redirects")
    snap = {p: p.read_text() for p in gen}
    subprocess.run(st + ["preview", "--root", str(work)], check=True, capture_output=True)
    check(all(p.read_text() == snap[p] for p in gen), "C: preview is not idempotent")
    subprocess.run(st + ["on", "--root", str(work)], check=True, capture_output=True)
    check(all("noindex" not in p.read_text() for p in gen), "C: on must remove the noindex tag")
    check(not (work / "home-preview.html").exists(), "C: on must remove the preview homepage (index.html is the homepage then)")
    on_idx = (work / "sitemap-index.xml").read_text()
    check("https://labwestrealty.com/sitemap-listings.xml" in on_idx and "https://labwestrealty.com/sitemap.xml" in on_idx, "C: on must register the listings sitemap and keep the recruiting one")
    subprocess.run(st + ["on", "--root", str(work)], check=True, capture_output=True)
    check((work / "sitemap-index.xml").read_text() == on_idx, "C: on is not idempotent")
    subprocess.run(st + ["preview", "--root", str(work)], check=True, capture_output=True)
    check((work / "sitemap-index.xml").read_text() == idx0, "C: going back to preview must deregister the sitemaps")
    r = subprocess.run(st + ["bogus", "--root", str(work)], capture_output=True, text=True)
    check(r.returncode == 2, "C: an unknown state must fail loud")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if errors:
    print("labwest-listings-test FAILED:")
    for e in errors:
        print("  -", e)
    sys.exit(1)
print("labwest-listings-test OK: dark while off; homes-only, no leases, Mike as contact, no address; state script")
