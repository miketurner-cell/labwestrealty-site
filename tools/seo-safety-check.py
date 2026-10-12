#!/usr/bin/env python3
"""SEO safety check -- does this change cost a search page anything it had?

2026-10-11 (sites, D-1011-21 item 1; Mike chose "SEO safety check on PRs").
Compares the pages that matter in search (tools/seo-pages.json) as they were at
BASE with the same pages at HEAD, straight from the static HTML. For each listed
page it reports a LOSS when HEAD no longer has what BASE had:

  title        <title> present at base, empty or gone at head
  description  <meta name="description"> present at base, empty or gone at head
  canonical    <link rel="canonical"> present at base, gone or pointing at a
               different page at head
  indexable    page was indexable at base and now carries noindex (robots meta,
               X-Robots-Tag in netlify.toml / _headers) or a robots.txt Disallow
  sitemap      the page's URL was in a sitemap*.xml at base and is gone at head
  home-link    the homepage (header nav included) linked to the page at base and
               no longer does
  gone         the file is gone at head with no redirect (a 301 is a NOTE, not a loss)

A changed title / description is reported as a NOTE (a rewrite is not a loss).
A page absent at BASE has no baseline and is skipped (counted).

Offline, stdlib only, Python 3.10+. No browser: the sites are static HTML.
No GSC call: the page list is a committed file (see tools/seo-pages-refresh.py).

Usage:
  python3 tools/seo-safety-check.py                   # CI/auto: base = PR base or HEAD~1, head = working tree
  python3 tools/seo-safety-check.py --base origin/main --head WORKTREE
  python3 tools/seo-safety-check.py --base abc123 --head def456 --mode fail
  SEO_SAFETY_MODE=fail ...                            # mode: warn (default, exit 0) | fail (exit 1 on a loss);
                                                      # also settable as "mode" in tools/seo-pages.json

Exit: 0 clean (or warn mode), 1 loss in fail mode, 2 cannot run (no base, no list).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from html.parser import HTMLParser
from urllib.parse import unquote, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST_PATH = "tools/seo-pages.json"


# ---------------------------------------------------------------- sources
class GitSource:
    def __init__(self, ref, repo=ROOT):
        self.ref, self.repo, self.cache = ref, repo, {}
        self.label = ref

    def read(self, path):
        path = path.lstrip("/")
        if path not in self.cache:
            r = subprocess.run(["git", "-C", self.repo, "show", f"{self.ref}:{path}"],
                               capture_output=True)
            self.cache[path] = r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None
        return self.cache[path]

    def listdir_root(self):
        r = subprocess.run(["git", "-C", self.repo, "ls-tree", "--name-only", self.ref],
                           capture_output=True, text=True)
        return r.stdout.split() if r.returncode == 0 else []


class DirSource:
    def __init__(self, root=ROOT):
        self.root, self.label = root, "WORKTREE"

    def read(self, path):
        p = os.path.join(self.root, path.lstrip("/"))
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()

    def listdir_root(self):
        return os.listdir(self.root)


# ---------------------------------------------------------------- parsing
class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self._in_title, self._title_done = "", False, False
        self.description = None
        self.canonical = None
        self.robots = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title" and not self._title_done:
            self._in_title = True
        elif tag == "meta":
            n = a.get("name", "").lower()
            if n == "description" and self.description is None:
                self.description = a.get("content", "").strip()
            elif n in ("robots", "googlebot"):
                self.robots.append(a.get("content", "").lower())
        elif tag == "link" and "canonical" in a.get("rel", "").lower().split():
            if self.canonical is None:
                self.canonical = a.get("href", "").strip()
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self._in_title, self._title_done = False, True

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def parse_html(text):
    p = PageParser()
    try:
        p.feed(text)
    except Exception:  # malformed HTML must not crash the gate; the fields just stay empty
        pass
    p.title = re.sub(r"\s+", " ", p.title).strip()
    return p


def norm(path):
    """Compare key for a URL path: no query, no index.html, no .html, no trailing slash."""
    path = unquote(urlparse(path).path or "/")
    path = re.sub(r"/index\.html$", "/", path)
    path = re.sub(r"\.html$", "", path)
    if len(path) > 1:
        path = path.rstrip("/")
    return path or "/"


def candidates(path):
    p = urlparse(path).path or "/"
    if p.endswith("/"):
        return [p.lstrip("/") + "index.html"]
    return [p.lstrip("/"), p.lstrip("/") + ".html", p.lstrip("/") + "/index.html"]


def read_page(src, path):
    for c in candidates(path):
        t = src.read(c)
        if t is not None:
            return c, t
    return None, None


def redirect_for(src, path):
    """(status, target) when _redirects sends this path somewhere (301/302/307/308), else None."""
    t = src.read("_redirects")
    if not t:
        return None
    for line in t.splitlines():
        line = line.split("#")[0].strip()
        parts = line.split()
        if len(parts) < 2 or "*" in parts[0] or ":" in parts[0]:
            continue
        if norm(parts[0]) == norm(path):
            status = re.sub(r"\D", "", parts[2]) if len(parts) > 2 else "301"
            if status in ("301", "302", "307", "308"):
                return status, parts[1]
    return None


# ---- robots.txt
def robots_blocked(src, path):
    t = src.read("robots.txt")
    if not t:
        return False
    groups, cur, seen_rule = [], None, False
    for raw in t.splitlines():
        line = raw.split("#")[0].strip()
        if ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            if cur is None or seen_rule:
                cur, seen_rule = {"uas": [], "rules": []}, False
                groups.append(cur)
            cur["uas"].append(v.lower())
        elif k in ("allow", "disallow") and cur is not None:
            seen_rule = True
            if v:
                cur["rules"].append((k, v))
    use = [g for g in groups if "googlebot" in g["uas"]] or [g for g in groups if "*" in g["uas"]]
    best = None  # (length, allowed)
    full = urlparse(path).path or "/"
    for g in use:
        for kind, pat in g["rules"]:
            rx = re.escape(pat).replace(r"\*", ".*")
            if rx.endswith(r"\$"):
                rx = rx[:-2] + "$"
            if re.match(rx, full):
                cand = (len(pat), kind == "allow")
                if best is None or cand[0] > best[0] or (cand[0] == best[0] and cand[1]):
                    best = cand
    return bool(best and not best[1])


# ---- X-Robots-Tag in netlify.toml / _headers
def _glob(pat, full):
    pat = pat.strip().strip('"').strip("'")
    rx = re.escape(pat).replace(r"\*", ".*")
    rx = re.sub(r"\\:[A-Za-z_]+", "[^/]+", rx)
    return re.fullmatch(rx, full) is not None


def _header_blocks(src):
    out = []
    toml = src.read("netlify.toml") or ""
    for blk in re.split(r"(?m)^\[\[headers\]\]", toml)[1:]:
        blk = re.split(r"(?m)^\[\[?(?!headers)", blk)[0]
        m = re.search(r'(?m)^\s*for\s*=\s*"([^"]+)"', blk)
        if m:
            out.append((m.group(1), blk))
    cur, buf = None, []
    for line in (src.read("_headers") or "").splitlines():
        if line and not line[0].isspace() and not line.startswith("#"):
            if cur:
                out.append((cur, "\n".join(buf)))
            cur, buf = line.strip(), []
        elif cur:
            buf.append(line)
    if cur:
        out.append((cur, "\n".join(buf)))
    return out


def xrobots_noindex(src, path):
    full = urlparse(path).path or "/"
    for pat, hdrs in _header_blocks(src):
        if re.search(r"(?i)x-robots-tag[^\n]*noindex", hdrs) and _glob(pat, full):
            return True
    return False


# ---- sitemaps
def sitemap_paths(src):
    paths = set()
    for name in src.listdir_root():
        if re.fullmatch(r"sitemap[A-Za-z0-9_.-]*\.xml", name):
            for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", src.read(name) or ""):
                paths.add(norm(loc))
    return paths


# ---------------------------------------------------------------- one side
def snapshot(src, pages):
    snap = {"sitemap": sitemap_paths(src), "pages": {}}
    home = src.read("index.html") or ""
    snap["home_links"] = {norm(h) for h in parse_html(home).links
                          if not re.match(r"(?i)^(mailto|tel|javascript|#)", h)
                          and (h.startswith("/") or h.startswith("http"))}
    for pg in pages:
        f, text = read_page(src, pg)
        if text is None:
            snap["pages"][pg] = None
            continue
        p = parse_html(text)
        noindex = [why for why, hit in (
            ("meta robots noindex", any("noindex" in r for r in p.robots)),
            ("X-Robots-Tag noindex", xrobots_noindex(src, pg)),
            ("robots.txt Disallow", robots_blocked(src, pg))) if hit]
        snap["pages"][pg] = {"file": f, "title": p.title, "description": p.description or "",
                             "canonical": p.canonical, "noindex": noindex}
    return snap


def compare(base_src, head_src, cfg):
    pages = [e["path"] if isinstance(e, dict) else e for e in cfg["pages"]]
    b, h = snapshot(base_src, pages), snapshot(head_src, pages)
    losses, notes, skipped = [], [], 0
    for pg in pages:
        bp, hp = b["pages"][pg], h["pages"][pg]
        if bp is None:
            skipped += 1
            continue
        if hp is None:
            rd = redirect_for(head_src, pg)
            if rd:
                notes.append((pg, f"redirected {rd[0]} -> {rd[1]} (page's own checks skipped)"))
            else:
                losses.append((pg, "gone", f"{bp['file']} no longer exists and no redirect covers {pg}"))
            continue
        if bp["title"] and not hp["title"]:
            losses.append((pg, "title", f"lost <title> {bp['title'][:60]!r}"))
        elif bp["title"] != hp["title"]:
            notes.append((pg, f"title changed: {bp['title'][:50]!r} -> {hp['title'][:50]!r}"))
        if bp["description"] and not hp["description"]:
            losses.append((pg, "description", "lost meta description"))
        elif bp["description"] != hp["description"]:
            notes.append((pg, "meta description changed"))
        if bp["canonical"]:
            if not hp["canonical"]:
                losses.append((pg, "canonical", f"lost canonical {bp['canonical']}"))
            elif norm(bp["canonical"]) != norm(hp["canonical"]) or \
                    urlparse(bp["canonical"]).netloc != urlparse(hp["canonical"]).netloc:
                losses.append((pg, "canonical", f"canonical {bp['canonical']} -> {hp['canonical']}"))
        gained = [w for w in hp["noindex"] if w not in bp["noindex"]]
        if not bp["noindex"] and gained:
            losses.append((pg, "indexable", "now blocked from the index: " + ", ".join(gained)))
        if norm(pg) in b["sitemap"] and norm(pg) not in h["sitemap"]:
            losses.append((pg, "sitemap", "URL dropped from the sitemap"))
        if norm(pg) != "/" and norm(pg) in b["home_links"] and norm(pg) not in h["home_links"]:
            losses.append((pg, "home-link", "homepage/nav no longer links to it"))
    return {"checked": len(pages) - skipped, "skipped_no_baseline": skipped,
            "losses": losses, "notes": notes}


# ---------------------------------------------------------------- CLI
def git_ok(*args):
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True)


def _auto_base_once():
    if os.environ.get("GITHUB_EVENT_NAME") == "pull_request" and \
            git_ok("rev-parse", "-q", "--verify", "HEAD^2").returncode == 0:
        return "HEAD^1"  # actions/checkout merge commit: ^1 = base branch tip, ^2 = PR head
    return "HEAD~1" if git_ok("rev-parse", "-q", "--verify", "HEAD~1").returncode == 0 else None


def auto_base():
    b = _auto_base_once()
    if b is None and git_ok("rev-parse", "--is-shallow-repository").stdout.strip() == "true":
        # CI checks out one commit; fetch the parent(s) so the comparison has a base. Failure falls through to exit 2.
        r = git_ok("fetch", "--no-tags", "--quiet", "--deepen=2", "origin")
        if r.returncode != 0:
            print(f"[seo-safety] deepen failed: {r.stderr.strip()[:200]}", file=sys.stderr)
        b = _auto_base_once()
    return b


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", help="git ref to compare against (default: auto)")
    ap.add_argument("--head", default="WORKTREE", help="git ref, or WORKTREE (default)")
    ap.add_argument("--pages", default=LIST_PATH)
    ap.add_argument("--mode", choices=["warn", "fail"], help="default: $SEO_SAFETY_MODE, else \"mode\" in the page list, else warn")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    lp = a.pages if os.path.isabs(a.pages) else os.path.join(ROOT, a.pages)
    base = a.base or auto_base()
    if not base:
        print("[seo-safety] CANNOT RUN: no base commit (shallow checkout and the deepen fetch failed)", file=sys.stderr)
        return 2
    head_src = DirSource() if a.head == "WORKTREE" else GitSource(a.head)
    base_src = GitSource(base)
    raw = None
    if os.path.isfile(lp):  # the checked-out list; dry runs pass --pages <file> to pin one list for every commit
        raw = open(lp, encoding="utf-8").read()
    if raw is None:
        print(f"[seo-safety] CANNOT RUN: {a.pages} not found", file=sys.stderr)
        return 2
    cfg = json.loads(raw)
    a.mode = a.mode or os.environ.get("SEO_SAFETY_MODE") or cfg.get("mode") or "warn"
    if a.mode not in ("warn", "fail"):
        print(f"[seo-safety] CANNOT RUN: mode {a.mode!r} is not warn|fail", file=sys.stderr)
        return 2
    res = compare(base_src, head_src, cfg)
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print(f"[seo-safety] mode={a.mode} base={base} head={head_src.label} "
              f"pages={len(cfg['pages'])} checked={res['checked']} no-baseline={res['skipped_no_baseline']} "
              f"losses={len(res['losses'])} notes={len(res['notes'])}")
        gha = os.environ.get("GITHUB_ACTIONS")
        for pg, kind, msg in res["losses"]:
            tag = ("::error::" if a.mode == "fail" else "::warning::") if gha else ""
            print(f"{tag}[seo-safety] LOSS {kind:<11} {pg}  {msg}")
        for pg, msg in res["notes"][:25]:
            print(f"[seo-safety] note {pg}  {msg}")
        if len(res["notes"]) > 25:
            print(f"[seo-safety] ... {len(res['notes']) - 25} more notes")
        if res["checked"] == 0:
            print("[seo-safety] WARNING: zero pages had a baseline -- the check proved nothing", file=sys.stderr)
        if not res["losses"]:
            print("[seo-safety] OK: no listed search page lost its title, description, canonical, index status, "
                  "sitemap entry or homepage link")
    return 1 if (res["losses"] and a.mode == "fail") else 0


if __name__ == "__main__":
    sys.exit(main())
