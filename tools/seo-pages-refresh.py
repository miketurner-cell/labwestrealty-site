#!/usr/bin/env python3
"""Rebuild tools/seo-pages.json -- the pages that matter in search for tools/seo-safety-check.py.

2026-10-11 (sites, D-1011-21 item 1). Offline: reads files in this checkout, never calls GSC.
The list is the union of
  sitemap  every URL in sitemap.xml (the hand-kept page sitemap; listing and property
           sitemaps churn hourly and are left out)
  digest   pages the weekly SEO digests name (_research/digests/*.md -- gainers/losers)
  gsc      tools/seo-cache/gsc-pages.json when present: {"pages": [{"page": URL, "clicks": n,
           "impressions": n}, ...]} -- written by the weekly digest workflow (see PR body);
           this is how real GSC click/impression pages reach the list without PR CI holding creds
  pinned   entries already in the file marked "pinned": true (hand additions survive a refresh)
Only paths that exist as a file here (or are covered by _redirects) are kept, so the list never
fails the check for a page that was never built.

  python3 tools/seo-pages-refresh.py            # rewrite tools/seo-pages.json
  python3 tools/seo-pages-refresh.py --check    # exit 1 when the committed file is stale
"""
import glob
import json
import os
import re
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib import util as _u  # noqa: E402

_spec = _u.spec_from_file_location("seo_safety_check", os.path.join(os.path.dirname(os.path.abspath(__file__)), "seo-safety-check.py"))
chk = _u.module_from_spec(_spec)
_spec.loader.exec_module(chk)

ROOT = chk.ROOT
OUT = os.path.join(ROOT, "tools", "seo-pages.json")
SKIP = re.compile(r"^/(property|agent|agent-sales|search|app)(/|$)|/detail(\.html)?$|^/listings/[^/]+/[^/]+\.html$")  # listing detail pages churn hourly


def exists(path):
    src = chk.DirSource(ROOT)
    return chk.read_page(src, path)[1] is not None or chk.redirect_for(src, path) is not None


def main():
    src = chk.DirSource(ROOT)
    sm = src.read("sitemap.xml") or ""
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sm)
    if not locs:
        print("[seo-pages-refresh] sitemap.xml has no <loc> -- refusing to write an empty list", file=sys.stderr)
        return 2
    host = urlparse(locs[0]).netloc
    entries = {}

    def add(path, source, **extra):
        path = urlparse(path).path or "/"
        if SKIP.search(path) or not exists(path):
            return
        e = entries.setdefault(path, {"path": path, "source": source})
        for k, v in extra.items():
            e[k] = v

    for loc in locs:
        add(loc, "sitemap")
    for f in sorted(glob.glob(os.path.join(ROOT, "_research", "digests", "*.md"))):
        for m in re.finditer(r"https?://" + re.escape(host) + r"(/[^\s)*\]]*)", open(f, encoding="utf-8").read()):
            add(m.group(1), "digest")
    gp = os.path.join(ROOT, "tools", "seo-cache", "gsc-pages.json")
    if os.path.isfile(gp):
        for r in json.load(open(gp)).get("pages", []):
            if urlparse(r["page"]).netloc in ("", host):
                add(r["page"], "gsc", clicks=r.get("clicks"), impressions=r.get("impressions"))
    if os.path.isfile(OUT):
        for e in json.load(open(OUT)).get("pages", []):
            if isinstance(e, dict) and e.get("pinned"):
                entries[e["path"]] = e
    entries.setdefault("/", {"path": "/", "source": "sitemap"})
    out = {"_doc": "Pages that matter in search, checked by tools/seo-safety-check.py. Rebuild: python3 tools/seo-pages-refresh.py. "
                   "Add a page by hand with \"pinned\": true. Sources: sitemap, digest, gsc, pinned.",
           "site": "https://" + host,
           "pages": sorted(entries.values(), key=lambda e: e["path"])}
    if os.path.isfile(OUT):  # a refresh never changes the mode
        out["mode"] = json.load(open(OUT)).get("mode", "warn")
    else:
        out["mode"] = "warn"
    head = json.dumps({k: v for k, v in out.items() if k != "pages"}, indent=1, ensure_ascii=False)[:-2]
    text = head + ',\n "pages": [\n' + ",\n".join("  " + json.dumps(e, ensure_ascii=False) for e in out["pages"]) + "\n ]\n}\n"
    if "--check" in sys.argv:
        cur = open(OUT, encoding="utf-8").read() if os.path.isfile(OUT) else ""
        if cur != text:
            print("[seo-pages-refresh] tools/seo-pages.json is stale -- run tools/seo-pages-refresh.py")
            return 1
        print("[seo-pages-refresh] up to date")
        return 0
    open(OUT, "w", encoding="utf-8").write(text)
    print(f"[seo-pages-refresh] wrote {len(out['pages'])} pages "
          f"({sum(1 for e in out['pages'] if e['source']=='digest')} from digests, "
          f"{sum(1 for e in out['pages'] if e['source']=='gsc')} from GSC)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
