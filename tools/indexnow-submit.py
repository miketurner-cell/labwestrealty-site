#!/usr/bin/env python3
"""
IndexNow submitter — pings api.indexnow.org (forwards to Bing + other
participating engines) with the URLs that changed in the most recent
Turner DDF Bot commit, so new/updated/removed listings are picked up in
minutes instead of waiting for a crawl.

Design notes:
  * Key: read from the single <32-hex>.txt file at the site root (the
    public IndexNow ownership file). No GitHub secret needed — the key
    is public by IndexNow design.
  * Change set (default mode): only submit when the current HEAD is a
    Turner DDF Bot commit, and submit exactly the .html paths that commit
    touched (listings/, index.html, pages/). If HEAD isn't a bot commit
    (a no-op cycle where nothing was committed), submit nothing.
  * --all mode: submit every URL in sitemap-listings.xml (one-time
    bulk registration / backfill).
  * Convention #74 fail-safe: ANY error prints a diagnostic and exits 0.
    IndexNow is a best-effort hint — it must never break a deploy.

Usage:
  indexnow-submit.py --host realestategander.com [--all] [--root .]
"""
import argparse, glob, json, os, re, subprocess, sys, urllib.request, urllib.error

ENDPOINT = "https://api.indexnow.org/indexnow"
BOT_AUTHORS = {"Turner DDF Bot"}
KEY_RE = re.compile(r"^[0-9a-fA-F]{8,128}$")
BATCH = 10000


def log(msg):
    print(f"[indexnow] {msg}", flush=True)


def find_key(root):
    for path in sorted(glob.glob(os.path.join(root, "*.txt"))):
        name = os.path.splitext(os.path.basename(path))[0]
        if KEY_RE.match(name):
            try:
                body = open(path, encoding="utf-8").read().strip()
            except OSError:
                continue
            if body == name:
                return name
    return None


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args],
                          capture_output=True, text=True).stdout.strip()


def path_to_url(host, p):
    if p == "index.html":
        return f"https://{host}/"
    if p.endswith("/index.html"):
        return f"https://{host}/{p[:-len('index.html')]}"
    return f"https://{host}/{p}"


def changed_urls(root, host, max_age):
    import time
    author = git(root, "log", "-1", "--format=%an")
    if author not in BOT_AUTHORS:
        log(f"HEAD author is '{author}', not a bot commit — nothing changed this run.")
        return []
    try:
        age = time.time() - int(git(root, "log", "-1", "--format=%ct"))
    except ValueError:
        age = 0
    if age > max_age:
        log(f"HEAD is a stale bot commit ({int(age)}s old > {max_age}s) — no commit this run; skipping.")
        return []
    out = git(root, "diff", "--name-only", "HEAD~1", "HEAD", "--",
              "listings", "index.html", "pages")
    urls = []
    for line in out.splitlines():
        line = line.strip()
        if line.endswith(".html"):
            urls.append(path_to_url(host, line))
    return urls


def sitemap_urls(root):
    urls = []
    for sm in ("sitemap-listings.xml", "sitemap.xml"):
        fp = os.path.join(root, sm)
        if os.path.exists(fp):
            try:
                txt = open(fp, encoding="utf-8").read()
            except OSError:
                continue
            urls += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", txt)
    return urls


def submit(host, key, urls):
    urls = list(dict.fromkeys(urls))  # de-dup, preserve order
    if not urls:
        log("no URLs to submit.")
        return
    key_location = f"https://{host}/{key}.txt"
    for i in range(0, len(urls), BATCH):
        batch = urls[i:i + BATCH]
        payload = json.dumps({
            "host": host, "key": key, "keyLocation": key_location,
            "urlList": batch,
        }).encode("utf-8")
        req = urllib.request.Request(
            ENDPOINT, data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                log(f"submitted {len(batch)} URLs -> HTTP {r.status}")
        except urllib.error.HTTPError as e:
            log(f"HTTP {e.code} on {len(batch)} URLs: {e.read()[:200]!r}")
        except Exception as e:
            log(f"submit error ({type(e).__name__}): {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--root", default=".")
    ap.add_argument("--all", action="store_true",
                    help="submit every sitemap URL (bulk backfill)")
    ap.add_argument("--max-age-seconds", type=int, default=1200,
                    help="only submit if HEAD bot commit is newer than this")
    a = ap.parse_args()
    try:
        key = find_key(a.root)
        if not key:
            log("no IndexNow key file at site root — skipping.")
            return
        urls = sitemap_urls(a.root) if a.all else changed_urls(a.root, a.host, a.max_age_seconds)
        log(f"{len(urls)} candidate URL(s) ({'sitemap' if a.all else 'changed'}).")
        submit(a.host, key, urls)
    except Exception as e:
        log(f"fatal (ignored, Convention #74): {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
