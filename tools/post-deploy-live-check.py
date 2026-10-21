#!/usr/bin/env python3
"""post-deploy-live-check.py -- what a SIGNED-OUT visitor actually receives after a production deploy.

Authority: D-1021-07 (Mike, 2026-10-21 08:32 UTC, "Post-deploy live check (Recommended)"): an automatic check after every
production deploy on all five sites: confirm the deployed commit equals main's head (or say why not), fetch the key pages signed out
and cache-busted, fail loud on fixture/test strings, sold-price fields outside D-1020-18/-21/-24/-41, served source/data paths, and a
skipped/cancelled production build after a merge. The alert is the workflow going red (the existing GitHub Actions failure path); this
script sends nothing to anyone, writes nothing, and holds no credential.

One canonical copy (Gander tools/), byte-identical in the other four repos; the site is chosen with --site.

WHY the "deployed commit" check is content-based. The workflows hold no Netlify token, and a static site exposes no commit id. So the
check finds the latest commit that Netlify's own deploy-skip rule (netlify.toml [build] ignore, run here exactly as Netlify runs it)
would BUILD, takes the served files that commit changed, and asserts the live site serves them: non-HTML files byte-identical, HTML files
by the visible-text segments the commit added (Cloudflare and Netlify rewrite links and e-mail addresses in HTML, so bytes differ).
If the latest build commit is not head, every commit after it is one the skip rule skips (tools/, .github/ only), and the report says so.
A deploy that is still building is waited for (--wait seconds); one that never lands (cancelled "no content change", skipped, failed)
fails the run. With NETLIFY_AUTH_TOKEN + NETLIFY_SITE_ID in the environment the same run also reads the Netlify deploy record; without
them it says so on one NOTE line (no secret exists in these repos today).

The #1228 class (a commit that changes only a function's bundled data file, which the skip rule must still build) is checked directly:
any recent commit the skip rule skips that changed a file named in netlify.toml included_files fails the run.

Usage
  post-deploy-live-check.py --site gander|avalon|goosebay|labwest|hub [--repo-dir .] [--wait 0] [--since-hours 2] [--self-test]
Exit: 0 pass (WARN/NOTE lines allowed) | 1 at least one FAIL | 2 usage or internal error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

UA = "Mozilla/5.0 (compatible; TurnerPostDeployCheck/1.0; signed-out)"

# --- per-site configuration (paths verified live 2026-10-21) -------------------------------------------------
AGENT_PAGES = ["/agent/", "/agent/deals.html", "/agent/broker.html", "/agent/market.html", "/agent/office.html",
               "/agent/approvals.html", "/agent/cma.html"]
GANDER_GATES = [  # signed-out GET must be 401/403 (read endpoints that need a token; none acts on a GET)
    "/.netlify/functions/agent-home", "/.netlify/functions/broker-queue", "/.netlify/functions/approvals",
    "/.netlify/functions/deal-actions", "/.netlify/functions/portal-profile", "/.netlify/functions/contact-actions",
    "/.netlify/functions/market-data", "/.netlify/functions/sold-data?f=per-agent-prices.json",
    "/.netlify/functions/sold-data?agent=dwayne-kean", "/listings/sold/per-agent-prices.json"]
SOLD_GATES = ["/.netlify/functions/sold-data?f=per-agent-prices.json"]

SITES = {
    "gander": {"domain": "realestategander.com", "team": True, "listing_index": "/listings/",
               "pages": [("home", "/"), ("listings index", "/listings/"), ("sold index", "/listings/sold/"),
                         ("market stats", "/pages/gander-mls-market-stats.html")],
               "agent_pages": AGENT_PAGES, "gates": GANDER_GATES, "agent_redirect": False},
    "avalon": {"domain": "avalonrealestate.ca", "team": True, "listing_index": "/listings/",
               "pages": [("home", "/"), ("listings index", "/listings/"), ("sold index", "/listings/sold/"),
                         ("market stats", "/pages/cbs-market-stats.html")],
               "agent_pages": [], "gates": SOLD_GATES, "agent_redirect": True},
    "goosebay": {"domain": "goosebayrealestate.ca", "team": True, "listing_index": "/listings/",
                 "pages": [("home", "/"), ("listings index", "/listings/"), ("sold index", "/listings/sold/"),
                           ("market stats", "/pages/market-stats.html")],
                 "agent_pages": [], "gates": SOLD_GATES, "agent_redirect": True},
    "labwest": {"domain": "labwestrealty.com", "team": False, "listing_index": None,
                "pages": [("home", "/"), ("market stats", "/market-stats.html")],
                "agent_pages": [], "gates": [], "agent_redirect": True},
    "hub": {"domain": "royallepageturner.com", "team": False, "hub": True, "listing_index": None,
            "pages": [("home", "/"), ("market stats", "/market-stats")],
            "agent_pages": [], "gates": [], "agent_redirect": True},
}

# Source files that are served today. A ratchet: these are reported on every run (NOTE = harmless, WARN = decide to remove them from the
# publish dir) but do not turn the run red; ANY OTHER served source/data path is a FAIL. D-1021-29 (L2) emptied the per-site lists: the stray
# files moved out of the publish dir, so a re-appearance is a FAIL here and in GONE_PATHS below.
_AGENT_MAP = ("NOTE", "served ON PURPOSE: js/agent-card.js:25 loads ../tools/community-agent-map.json; public agent card data, with an explicit _redirects 200 allow rule")
KNOWN_PUBLIC = {
    "*": {"package.json": ("NOTE", "dependency names only, no secrets"), "package-lock.json": ("NOTE", "dependency lock, no secrets")},
    # Intended public path, per site, only where the site carries js/agent-card.js and a _redirects allow rule. Labwest and the hub do not
    # serve it and are not listed, so a 200 there is still a FAIL.
    "gander": {"tools/community-agent-map.json": _AGENT_MAP},
    "avalon": {"tools/community-agent-map.json": _AGENT_MAP},
    "goosebay": {"tools/community-agent-map.json": _AGENT_MAP},
}

# Paths that were served and must now answer anything but 200 (D-1021-29: L2 stray files, L4 agent-accountability.html, M1 function source).
# A 301 for agent-accountability.html is the intended answer, so these are fetched without following redirects.
GONE_PATHS = {
    "goosebay": ["PHOTO-NEEDS.md", "SITE_PLAN.md", "update_site.py", "server.log", "test-write.txt",
                 "IMAGE_AUDIT_2026-04-06.txt", "PAGE_IMAGE_INVENTORY.txt"],
    "labwest": ["README.md", "netlify/functions/chat.ts", "netlify/functions/sold-data.ts"],
    "hub": ["ACTIVE-LISTINGS-WORKFLOW.md", "agent-accountability.html"],
}

# --- patterns ---------------------------------------------------------------------------------------------------
FIXTURE_RE = re.compile(r"(?i:\bfixtures?\b|lorem ipsum|test@example\.|@example\.invalid)|(?-i:__[A-Z][A-Z0-9_]{3,}__|\bSYNTHETIC\b|\bDRILL[ -](?:DEAL|LEAD|ROW)\b)")
SOLD_KEY_RE = re.compile(r"""(?ix)["']?\b(close_?price|closeprice|sold_?price|soldprice|sold_?amount)\b["']?\s*[:=]\s*["']?\$?\d""")
SOLD_TEXT_RE = re.compile(r"(?i)\bsold\s+(?:for|at)\s+\$\s?\d[\d,]{4,}|\bsold\s+price\s*:?\s*\$\s?\d[\d,]{4,}")
HUB_SOLD_RE = re.compile(r"(?i)\b(?:avg\.?|average)\s+(?:sale|sold)\s+price|\bmedian\s+(?:sale|sold)?\s*price|sale[- ]to[- ]list|sold[- ]to[- ]list")
GATE_MARK_RE = re.compile(r"""(?i)id=["']view-signin|AgentGate|agent-gate\.js|sign-in required""")
SKIP_NETLIFY_RE = re.compile(r"\[\s*(?:skip\s+ci|ci\s+skip|skip\s+netlify|netlify\s+skip)\s*\]", re.I)
NOT_SERVED_PREFIX = ("tools/", ".github/", "netlify/", "_research/", "_ops/", "node_modules/", "fleet/", "scripts/", "docs/", ".claude/")
SERVED_EXT = (".html", ".css", ".js", ".json", ".xml", ".txt", ".svg", ".webmanifest", ".webp", ".png", ".jpg", ".jpeg", ".ico", ".woff2")
SOURCE_EXT = (".py", ".ts", ".sql", ".sh", ".yml", ".yaml", ".toml", ".md", ".lock", ".cfg", ".ini", ".env")


# --- results ----------------------------------------------------------------------------------------------------
class Report:
    def __init__(self):
        self.lines, self.fails = [], 0

    def add(self, level, name, detail=""):
        line = f"{level:4} {name}" + (f": {detail}" if detail else "")
        self.lines.append(line)
        if level == "FAIL":
            self.fails += 1
            if os.environ.get("GITHUB_ACTIONS"):
                print(f"::error::{name}: {detail}"[:900])
        print(line, flush=True)

    def passed(self, n, d=""): self.add("PASS", n, d)
    def fail(self, n, d=""): self.add("FAIL", n, d)
    def warn(self, n, d=""): self.add("WARN", n, d)
    def note(self, n, d=""): self.add("NOTE", n, d)


# --- HTTP (signed out: no cookies, no auth header, cache-busted, retried on transient errors) -------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def bust(url):
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}_cb={int(time.time())}{random.randint(1000, 9999)}"


def http_get(url, follow=True, timeout=25, retries=3, sleep=time.sleep):
    """-> (status, content_type, body_bytes, final_url). status 0 = network failure after retries."""
    last = None
    for i in range(retries):
        req = urllib.request.Request(bust(url), headers={"User-Agent": UA, "Cache-Control": "no-cache", "Pragma": "no-cache",
                                                         "Accept": "*/*"})
        opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(req, timeout=timeout) as r:
                return r.status, r.headers.get("Content-Type", ""), r.read(8_000_000), r.geturl()
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504) and i < retries - 1:
                last = e
                sleep(3)
                continue
            return e.code, (e.headers.get("Content-Type", "") if e.headers else ""), (e.read(2_000_000) if e.fp else b""), url
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if i < retries - 1:
                sleep(3)
    return 0, "", repr(last).encode()[:200], url


# --- git / Netlify skip rule -----------------------------------------------------------------------------------
def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)[:80]} failed: {r.stderr.strip()[:200]}")
    return r.stdout


def ignore_script(toml_text):
    m = re.search(r'^\s*ignore\s*=\s*"""\n(.*?)"""', toml_text, re.S | re.M)
    return m.group(1) if m else None


def included_files(toml_text):
    out = []
    for m in re.finditer(r"included_files\s*=\s*\[(.*?)\]", toml_text, re.S):
        out += re.findall(r'"([^"]+)"', m.group(1))
    return sorted(set(out))


def would_build(script, repo, base, commit, message=""):
    """Netlify's ignore contract: exit 1 = build, 0 = skip. A skip token in the commit message skips the build before the script runs."""
    if SKIP_NETLIFY_RE.search(message or ""):
        return False, "skip token in the commit message"
    if script is None:
        return True, "no ignore rule"
    env = {**os.environ, "CACHED_COMMIT_REF": base, "COMMIT_REF": commit}
    r = subprocess.run(["bash", "-c", script], cwd=repo, env=env, capture_output=True, text=True)
    return r.returncode != 0, f"ignore rule exit {r.returncode}"


def recent_commits(repo, head, n=40):
    out = git(repo, "log", f"-{n}", "--format=%H%x1f%P%x1f%cI%x1f%s", head)
    rows = []
    for ln in out.splitlines():
        h, p, ts, subj = (ln.split("\x1f") + ["", "", "", ""])[:4]
        rows.append({"sha": h, "parent": p.split()[0] if p else "", "time": ts, "subject": subj})
    return rows


def changed(repo, base, commit):
    out = git(repo, "diff", "--name-status", "--no-renames", base, commit)
    res = []
    for ln in out.splitlines():
        st, _, path = ln.partition("\t")
        res.append((st[:1], path))
    return res


def is_served(path):
    # Netlify does not serve dotfiles/dot-directories (e.g. images/listings/<id>/.meta.json answers 404 by design): never a deploy probe.
    return (not path.startswith(NOT_SERVED_PREFIX) and path.lower().endswith(SERVED_EXT)
            and path not in ("package.json", "package-lock.json") and not any(seg.startswith(".") for seg in path.split("/")))


# --- HTML text segments ----------------------------------------------------------------------------------------
def segments(html):
    t = re.sub(r"(?is)<(script|style|noscript|template)\b.*?</\1>|<!--.*?-->", " ", html)
    t = re.sub(r"(?s)<[^>]+>", "\n", t)
    segs = set()
    for ln in unescape(t).splitlines():
        s = " ".join(ln.split())
        if len(s) >= 25 and "@" not in s and "email" not in s.lower() and "[" not in s:
            segs.add(s)
    return segs


def sample(items, k):
    items = sorted(items)
    if len(items) <= k:
        return items
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]


# --- checks ------------------------------------------------------------------------------------------------------
def check_pages(rep, cfg, base, get):
    """Key pages signed out: 200, no fixture/test text, no individual sold price, hub sold-derived figures."""
    fetched = {}
    for name, path in cfg["pages"]:
        st, ct, body, final = get(base + path)
        if st != 200:
            rep.fail(f"page {name} {path}", f"HTTP {st} (expected 200)")
            continue
        text = body.decode("utf-8", "replace")
        fetched[path] = text
        probs = []
        m = FIXTURE_RE.search(text)
        if m:
            probs.append(f"fixture/test text {m.group(0)!r} near {text[max(0, m.start() - 40):m.end() + 40]!r}".replace("\n", " "))
        m = SOLD_KEY_RE.search(text) or SOLD_TEXT_RE.search(text)
        if m:
            probs.append(f"individual sold price {m.group(0)[:60]!r}")
        if probs:
            rep.fail(f"page {name} {path}", "; ".join(probs))
        else:
            rep.passed(f"page {name} {path}", f"200, {len(body)} bytes, no fixture text, no individual sold price")
        if cfg.get("hub"):
            vis = " ".join(sorted(segments(text)))
            h = HUB_SOLD_RE.search(vis)
            if h:
                # D-1020-21: everything sold-derived on royallepageturner.com stays behind sign-in. Open item when written.
                lvl = rep.fail if os.environ.get("HUB_SOLD_STRICT") == "on" else rep.warn
                lvl(f"hub sold-derived figure {path}", f"{h.group(0)!r} is public (D-1020-18/-21: the hub stays gated); "
                    "WARN until HUB_SOLD_STRICT=on")
    return fetched


def check_listing(rep, cfg, base, fetched, get):
    idx = cfg.get("listing_index")
    if not idx:
        return
    text = fetched.get(idx, "")
    m = re.search(r'href="((?:\.\./|/)?listings/[a-z0-9-]+/[a-z0-9-]+\.html)"', text)
    if not m:
        rep.note("one listing", f"no static listing link on {idx} (JS-rendered or empty market); not sampled")
        return
    path = "/" + m.group(1).replace("../", "").lstrip("/")
    st, ct, body, final = get(base + path)
    t = body.decode("utf-8", "replace")
    probs = []
    if st != 200:
        probs.append(f"HTTP {st}")
    if FIXTURE_RE.search(t):
        probs.append("fixture/test text")
    if SOLD_KEY_RE.search(t) or SOLD_TEXT_RE.search(t):
        probs.append("individual sold price")
    if probs:
        rep.fail(f"listing {path}", "; ".join(probs))
    else:
        rep.passed(f"listing {path}", f"200, {len(body)} bytes, clean")


def check_agent_gates(rep, cfg, base, get):
    for p in cfg["agent_pages"]:
        st, ct, body, final = get(base + p)
        t = body.decode("utf-8", "replace")
        if st != 200:
            rep.fail(f"agent page {p}", f"HTTP {st}")
        elif not GATE_MARK_RE.search(t):
            rep.fail(f"agent page {p}", "served signed out WITHOUT the sign-in gate marker")
        elif SOLD_KEY_RE.search(t) or re.search(r"(?i)commission[_ ]?(?:amount|total)\s*[:=]\s*\$?\d", t):
            rep.fail(f"agent page {p}", "sign-in shell carries money/sold data")
        else:
            rep.passed(f"agent page {p}", "sign-in gate marker present, no data")
    for p in cfg["gates"]:
        st, ct, body, final = get(base + p, follow=False)
        if st in (401, 403):
            rep.passed(f"gate {p}", f"HTTP {st}")
        else:
            rep.fail(f"gate {p}", f"signed-out GET returned HTTP {st} {body[:60]!r} (expected 401/403)")
    if cfg.get("agent_redirect"):
        st, ct, body, final = get(base + "/agent/", follow=False)
        if st in (301, 302, 308):
            rep.passed("agent hop /agent/", f"HTTP {st}")
        else:
            rep.warn("agent hop /agent/", f"HTTP {st}, expected a redirect to Gander")


def source_candidates(repo):
    tracked = git(repo, "ls-files").splitlines()
    top = [f for f in tracked if "/" not in f and (f.lower().endswith(SOURCE_EXT) or f in ("package.json", "package-lock.json")) and f != "netlify.toml"]
    top.append("netlify.toml")
    deep = [f for f in tracked if f.startswith(("tools/", "netlify/", ".github/", "_research/", "_ops/"))
            and f.lower().endswith(SOURCE_EXT + (".json", ".ts"))]
    return sorted(set(top)), sample(deep, 14)


def check_source_paths(rep, cfg, base, repo, get):  # cfg["key"] is the site key
    top, deep = source_candidates(repo)
    probes = top + deep + [".git/config", ".git/HEAD", ".env", ".env.local", "node_modules/.package-lock.json"]
    bad = 0
    for rel in probes:
        st, ct, body, final = get(base + "/" + rel)
        if st != 200:
            continue
        html = "html" in ct.lower()
        local = os.path.join(repo, rel)
        same = False
        if os.path.exists(local):
            with open(local, "rb") as f:
                head = f.read(200)
            same = bool(head.strip()) and head.strip()[:80] in body
        if html and not same and not rel.startswith(".git"):
            continue   # an HTML 200 that is not the file itself is a page fallback, not the source
        known = {**KNOWN_PUBLIC["*"], **KNOWN_PUBLIC.get(cfg["key"], {})}.get(rel)
        if known:
            (rep.warn if known[0] == "WARN" else rep.note)(f"served source path /{rel}", f"KNOWN public (not a new leak): {known[1]}")
            continue
        bad += 1
        rep.fail(f"served source path /{rel}", f"HTTP 200 {ct.split(';')[0]}, {len(body)} bytes: a source/data file is publicly served")
    if not bad:
        rep.passed("served source paths", f"{len(probes)} source/data paths probed, none served (known-public ones are NOTEd)")


def check_gone_paths(rep, cfg, base, repo, get):
    """D-1021-29: every path in GONE_PATHS, and every tracked netlify/ file (function source), must not be served (HTTP 200)."""
    paths = list(GONE_PATHS.get(cfg["key"], []))
    tracked = [f for f in git(repo, "ls-files", "netlify/").splitlines() if f.lower().endswith((".ts", ".js", ".mjs", ".json"))]
    paths += [f for f in sample(tracked, 40) if f not in paths]
    bad = 0
    for rel in paths:
        st, ct, body, final = get(base + "/" + rel, follow=False)
        if st == 200:
            bad += 1
            rep.fail(f"removed path /{rel} is served again", f"HTTP 200 {ct.split(';')[0]}, {len(body)} bytes (D-1021-29: stray/source files must 404)")
    if not bad:
        rep.passed("removed paths stay removed", f"{len(paths)} stray/function-source paths, none answers 200")


def _older(ts, cutoff):
    try:
        return cutoff is not None and dt.datetime.fromisoformat(ts.replace("Z", "+00:00")) < cutoff
    except ValueError:
        return False


def check_deploy(rep, cfg, base, repo, get, wait, since_hours, head_ref, sleep=time.sleep, now=time.time):
    head = git(repo, "rev-parse", head_ref).strip()
    toml = os.path.join(repo, "netlify.toml")
    ttext = open(toml).read() if os.path.exists(toml) else ""
    script, inc = ignore_script(ttext), included_files(ttext)
    rows = recent_commits(repo, head)
    if not rows:
        rep.fail("deployed commit", "no commits found")
        return
    cutoff = None
    try:
        cutoff = dt.datetime.fromisoformat(rows[0]["time"].replace("Z", "+00:00")) - dt.timedelta(hours=since_hours)
    except ValueError:
        pass
    # 1. the deploy-skip rule vs a function's bundled data (#1228 class)
    gap = []
    for r in rows:
        if not r["parent"] or _older(r["time"], cutoff):
            continue
        build, why = would_build(script, repo, r["parent"], r["sha"], r["subject"])
        if build or SKIP_NETLIFY_RE.search(r["subject"]):
            continue
        for st, p in changed(repo, r["parent"], r["sha"]):
            if st != "D" and any(fnmatch.fnmatch(p, g) for g in inc):
                gap.append(f"{r['sha'][:7]} changes {p}")
    if gap:
        rep.fail("skip rule vs bundled data", "the deploy-skip rule SKIPS commit(s) that change a function's bundled data file "
                 "(#1228 class: a merge that never reaches the live function): " + "; ".join(gap[:5]) + ". Build by hand and extend the rule")
    else:
        rep.passed("skip rule vs bundled data", f"no skipped commit in the last {since_hours:g}h changed an included_files path ({len(inc)} patterns)")
    # 2. the latest commit Netlify would build must be live
    build_commit = None
    for r in rows:
        if not r["parent"] or would_build(script, repo, r["parent"], r["sha"], r["subject"])[0]:
            build_commit = r
            break
    if not build_commit:
        rep.warn("deployed commit", "no build-triggering commit in the last 40; live content not compared")
        return
    skipped_after = rows[:rows.index(build_commit)]
    bc = build_commit["sha"]
    files = [(st, p) for st, p in changed(repo, build_commit["parent"], bc) if is_served(p)] if build_commit["parent"] else []
    adds = [p for st, p in files if st in ("A", "M") and not any(fnmatch.fnmatch(p, g) for g in inc)]   # included_files = gated function data
    if not adds:
        rep.passed("deployed commit", f"latest build commit {bc[:7]} ({build_commit['subject'][:60]!r}) changed no served file "
                   "(function/config change); live content cannot be compared here")
    else:
        pick = sample(adds, 10)
        deadline = now() + wait
        while True:
            pending = []
            for p in pick:
                ok, detail = compare_file(repo, base, bc, build_commit["parent"], head, p, get)
                if not ok:
                    pending.append(f"{p} ({detail})")
            if not pending or now() >= deadline:
                break
            print(f"     {len(pending)}/{len(pick)} sampled files not live yet; waiting (build in progress?) ...", flush=True)
            sleep(30)
        if pending:
            rep.fail("deployed commit", f"main head {head[:7]}; latest build-triggering commit {bc[:7]} "
                     f"({build_commit['time']}, {build_commit['subject'][:60]!r}) is NOT live after {wait}s: "
                     f"{len(pending)} of {len(pick)} sampled files differ: " + "; ".join(pending[:4]) +
                     ". Causes: build still running, cancelled ('no content change'), skipped by a skip token, or failed. "
                     "Read the Netlify deploy record and trigger a build")
        else:
            why = ("it is head" if bc == head else
                   f"head {head[:7]} is {len(skipped_after)} commit(s) later, all skipped by the deploy-skip rule "
                   f"(tools/.github only or a skip token): {', '.join(r['sha'][:7] for r in skipped_after[:5])}")
            rep.passed("deployed commit", f"live serves build commit {bc[:7]} ({len(pick)} of {len(adds)} changed served files "
                       f"match); main head = {head[:7]}: {why}")
    api_deploy_record(rep, bc)


def compare_file(repo, base, commit, parent, head, path, get):
    """(ok, detail). Non-HTML exact (then whitespace-normalised); HTML by the visible text the commit added."""
    def show(ref, p):
        return subprocess.run(["git", "-C", repo, "show", f"{ref}:{p}"], capture_output=True).stdout
    want = show(head, path)
    if not want:
        return True, "deleted since"
    st, ct, body, final = get(base + "/" + path)
    if st in (401, 403):
        return True, "gated (sign-in), not compared"
    if st != 200:
        return False, f"HTTP {st}"
    fin, req_ = urllib.parse.urlparse(final).path, "/" + path

    def norm(s):
        s = s.rstrip("/")
        return s[:-5] if s.endswith(".html") else s
    if norm(fin) != norm(req_) and not (req_.endswith("/index.html") and fin.rstrip("/") == req_[:-len("index.html")].rstrip("/")):
        return True, "redirected, not compared"
    if path.lower().endswith(".html"):
        new = segments(want.decode("utf-8", "replace"))
        old = segments(show(parent, path).decode("utf-8", "replace")) if parent else set()
        live = segments(body.decode("utf-8", "replace"))
        added = sample(new - old, 12)
        if added:
            miss = [s for s in added if s not in live]
            return (not miss or len(miss) <= len(added) // 10), (f"{len(miss)} of {len(added)} added text lines missing" if miss else "")
        removed = sample(old - new, 12)
        stale = [s for s in removed if s in live]
        return (not stale), (f"{len(stale)} removed text lines still live" if stale else "")
    if hashlib.sha256(body).digest() == hashlib.sha256(want).digest() or b"".join(body.split()) == b"".join(want.split()):
        return True, ""
    return False, "bytes differ"


def api_deploy_record(rep, bc, opener=None):
    token, site_id = os.environ.get("NETLIFY_AUTH_TOKEN", ""), os.environ.get("NETLIFY_SITE_ID", "")
    if not (token and site_id):
        rep.note("netlify deploy record", "not read: no NETLIFY_AUTH_TOKEN/NETLIFY_SITE_ID in this repo (no secret exists; the content check above stands in)")
        return
    req = urllib.request.Request(f"https://api.netlify.com/api/v1/sites/{site_id}/deploys?per_page=15",
                                 headers={"Authorization": "Bearer " + token, "User-Agent": UA})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=25) as r:
            deploys = json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001 -- never print the request (it carries the token)
        rep.warn("netlify deploy record", f"API read failed ({type(e).__name__}); the content check above stands")
        return
    mine = [d for d in deploys if (d.get("commit_ref") or "") == bc and d.get("context") == "production"]
    if not mine:
        rep.fail("netlify deploy record", f"no production deploy record for build commit {bc[:7]} in the last 15 deploys (never started or skipped)")
        return
    d = mine[0]
    if d.get("state") == "ready":
        rep.passed("netlify deploy record", f"{bc[:7]} deploy {str(d.get('id'))[:8]} state=ready")
    else:
        rep.fail("netlify deploy record", f"{bc[:7]} deploy state={d.get('state')} {(d.get('error_message') or '')[:120]!r}")


# --- offline self-test --------------------------------------------------------------------------------------------
def self_test():
    import shutil
    import tempfile
    ok = True

    def chk(name, cond):
        nonlocal ok
        print(("PASS  " if cond else "FAIL  ") + name)
        ok = ok and bool(cond)

    chk("fixture text is caught", FIXTURE_RE.search("September 2026 NLAR, fixture") and FIXTURE_RE.search("<p>Lorem ipsum</p>"))
    chk("a normal page is not a fixture", not FIXTURE_RE.search("<p>Fixed-rate mortgage on a fixer-upper</p>"))
    chk("close_price key caught", SOLD_KEY_RE.search('{"close_price": 245000}') and SOLD_KEY_RE.search("ClosePrice=245000"))
    chk("area average is not an individual sold price", not SOLD_KEY_RE.search("Avg Sale Price $381K") and not SOLD_TEXT_RE.search("Avg Sale Price $381K"))
    chk("'Sold for $245,000' caught", SOLD_TEXT_RE.search("Sold for $245,000"))
    chk("hub sold-derived caught", HUB_SOLD_RE.search("Avg Sale Price $381K") and HUB_SOLD_RE.search("Sale-to-list 98%"))
    chk("included_files parsed", included_files('[functions]\n included_files = ["a/*.json", "tools/x.json"]\n') == ["a/*.json", "tools/x.json"])
    chk("segments drop emails, short lines, scripts",
        segments("<p>Short</p><script>var a='long text that is long enough to count here';</script><p>This is a long visible sentence here.</p>"
                 "<p>Mail us at office@x.com now please ok</p>") == {"This is a long visible sentence here."})
    chk("skip token regex", SKIP_NETLIFY_RE.search("x [skip ci]") and SKIP_NETLIFY_RE.search("[skip netlify]") and not SKIP_NETLIFY_RE.search("[skip actions]"))

    toml = ('[build]\n  ignore = """\n[ -z "$CACHED_COMMIT_REF" ] && exit 1\nD=$(git diff --name-only "$CACHED_COMMIT_REF" "$COMMIT_REF") || exit 1\n'
            'echo "$D" | grep -qvE "^(tools/|\\.github/)" && exit 1\nexit 0\n"""\n[functions.f]\n  included_files = ["tools/data/*.json"]\n')
    d = tempfile.mkdtemp()
    envg = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    try:
        def g(*a):
            subprocess.run(["git", "-C", d, *a], check=True, capture_output=True, env=envg)
        g("init", "-q", "-b", "main")
        os.makedirs(os.path.join(d, "pages"))
        os.makedirs(os.path.join(d, "tools/data"))
        w = lambda p, s: open(os.path.join(d, p), "w").write(s)  # noqa: E731
        w("netlify.toml", toml)
        w("pages/a.html", "<p>The first version of the page text is long enough.</p>")
        w("tools/data/x.json", "{}")
        g("add", "-A"); g("commit", "-qm", "base")
        w("pages/a.html", "<p>The first version of the page text is long enough.</p><p>A brand new paragraph that was added by the commit.</p>")
        g("add", "-A"); g("commit", "-qm", "content change")
        c1 = git(d, "rev-parse", "HEAD").strip()
        w("tools/other.py", "x=1\n")
        g("add", "-A"); g("commit", "-qm", "tools only")
        c2 = git(d, "rev-parse", "HEAD").strip()
        w("tools/data/x.json", '{"a":1}')
        g("add", "-A"); g("commit", "-qm", "bundled data only")
        script = ignore_script(toml)
        chk("rule builds a content change", would_build(script, d, c1 + "~1", c1)[0] is True)
        chk("rule skips a tools-only change", would_build(script, d, c1, c2)[0] is False)
        chk("skip token in message skips", would_build(script, d, c1, c2, "x [skip ci]")[0] is False)
        live_ok = {"/pages/a.html": (200, "text/html", b"<p>The first version of the page text is long enough.</p><p>A brand new paragraph that was added by the commit.</p>", "https://x.test/pages/a.html")}
        live_stale = {"/pages/a.html": (200, "text/html", b"<p>The first version of the page text is long enough.</p>", "https://x.test/pages/a.html")}

        def mkget(table):
            return lambda url, follow=True: table.get(urllib.parse.urlparse(url).path, (404, "text/html", b"nf", url))
        chk("html delta present live -> ok", compare_file(d, "https://x.test", c1, c1 + "~1", "HEAD", "pages/a.html", mkget(live_ok))[0])
        chk("html delta missing live -> not ok", not compare_file(d, "https://x.test", c1, c1 + "~1", "HEAD", "pages/a.html", mkget(live_stale))[0])
        rep = Report()
        check_deploy(rep, {}, "https://x.test", d, mkget(live_ok), 0, 48, "HEAD")
        chk("bundled-data gap is a FAIL", any(l.startswith("FAIL skip rule vs bundled data") for l in rep.lines))
        chk("deployed commit passes when the build commit is live", any(l.startswith("PASS deployed commit") and "later" in l for l in rep.lines))
        rep2 = Report()
        check_deploy(rep2, {}, "https://x.test", d, mkget(live_stale), 0, 48, "HEAD")
        chk("deployed commit FAILS when the build commit is not live", any(l.startswith("FAIL deployed commit") for l in rep2.lines))
        rep3 = Report()
        os.environ.pop("NETLIFY_AUTH_TOKEN", None)
        api_deploy_record(rep3, c1)
        chk("no token -> one NOTE, no FAIL", rep3.fails == 0 and rep3.lines[0].startswith("NOTE"))
        os.environ["NETLIFY_AUTH_TOKEN"], os.environ["NETLIFY_SITE_ID"] = "tok-not-real", "site"

        class R:
            def __init__(s, b): s.b = b
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s): return s.b
        rep4 = Report()
        api_deploy_record(rep4, c1, opener=lambda req, timeout=0: R(json.dumps([{"commit_ref": c1, "context": "production", "state": "error",
                          "error_message": "Canceled build due to no content change", "id": "abcdef12345"}]).encode()))
        chk("cancelled deploy record is a FAIL and never echoes the token", rep4.fails == 1 and "tok-not-real" not in " ".join(rep4.lines))
        os.environ.pop("NETLIFY_AUTH_TOKEN")
        os.environ.pop("NETLIFY_SITE_ID")
        table = {"/": (200, "text/html", b"<h1>Home</h1><p>NLAR, fixture</p>", "u"), "/agent/": (200, "text/html", b'<div id="view-signin-gate"></div>', "u"),
                 "/g": (200, "application/json", b'{"deals":[1]}', "u"), "/g2": (401, "application/json", b"{}", "u")}
        gt = lambda url, follow=True: table.get(urllib.parse.urlparse(url).path, (404, "", b"", url))  # noqa: E731
        rep5 = Report()
        check_pages(rep5, {"pages": [("home", "/")]}, "https://x.test", gt)
        chk("fixture text on a key page is a FAIL", rep5.fails == 1)
        rep6 = Report()
        check_agent_gates(rep6, {"agent_pages": ["/agent/"], "gates": ["/g", "/g2"]}, "https://x.test", gt)
        chk("gate endpoint returning data is a FAIL; 401 and the gate marker pass",
            rep6.fails == 1 and any(l.startswith("PASS gate /g2") for l in rep6.lines) and any(l.startswith("PASS agent page /agent/") for l in rep6.lines))
        rep7 = Report()
        gone = {"/PHOTO-NEEDS.md": (200, "text/markdown", b"# notes", "u"), "/agent-accountability.html": (301, "text/html", b"", "u")}
        check_gone_paths(rep7, {"key": "goosebay"}, "https://x.test", d, lambda url, follow=True: gone.get(urllib.parse.urlparse(url).path, (404, "text/html", b"nf", url)))
        chk("a removed path answering 200 is a FAIL; 404 and 301 pass", rep7.fails == 1 and "PHOTO-NEEDS.md" in " ".join(rep7.lines))
        rep8 = Report()
        check_gone_paths(rep8, {"key": "hub"}, "https://x.test", d, lambda url, follow=True: gone.get(urllib.parse.urlparse(url).path, (404, "text/html", b"nf", url)))
        chk("hub agent-accountability.html 301 is not a FAIL", rep8.fails == 0)
        chk("no per-site KNOWN_PUBLIC entry is left for a path that GONE_PATHS lists", not any(p in KNOWN_PUBLIC.get(k, {}) for k, v in GONE_PATHS.items() for p in v))
        _sc = globals()["source_candidates"]
        globals()["source_candidates"] = lambda repo: ([], ["tools/community-agent-map.json"])
        try:
            amap = lambda url, follow=True: (200, "application/json", b'{"agents": []}', url) if url.endswith("tools/community-agent-map.json") else (404, "text/html", b"nf", url)
            ok_sites = []
            for k in ("gander", "avalon", "goosebay", "labwest", "hub"):
                rep9 = Report()
                check_source_paths(rep9, {"key": k}, "https://x.test", d, amap)
                ok_sites.append((k, rep9.fails))
        finally:
            globals()["source_candidates"] = _sc
        chk("community-agent-map.json (js/agent-card.js) is a NOTE on gander/avalon/goosebay and still a FAIL on labwest/hub",
            ok_sites == [("gander", 0), ("avalon", 0), ("goosebay", 0), ("labwest", 1), ("hub", 1)])
        chk("a dotfile path (images/listings/1/.meta.json) is never a served-file probe; a normal asset still is",
            not is_served("images/listings/1/.meta.json") and not is_served(".well-known/x.json") and is_served("images/listings/1/a.json"))
        chk("every site config has a domain and pages", all(c["domain"] and c["pages"] for c in SITES.values()))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site", choices=sorted(SITES))
    ap.add_argument("--repo-dir", default=".")
    ap.add_argument("--wait", type=int, default=0, help="seconds to wait for a build-triggering commit to go live (push runs: 900)")
    ap.add_argument("--since-hours", type=float, default=2.0, help="window for the skip-rule vs bundled-data check")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.site:
        ap.error("--site is required")
    cfg, rep = {**SITES[a.site], "key": a.site}, Report()
    base, repo = "https://" + cfg["domain"], os.path.abspath(a.repo_dir)
    print(f"post-deploy live check (D-1021-07): {cfg['domain']} signed out, cache-busted, {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}", flush=True)
    try:
        fetched = check_pages(rep, cfg, base, http_get)
        check_listing(rep, cfg, base, fetched, http_get)
        check_agent_gates(rep, cfg, base, http_get)
        check_source_paths(rep, cfg, base, repo, http_get)
        check_gone_paths(rep, cfg, base, repo, http_get)
        check_deploy(rep, cfg, base, repo, http_get, a.wait, a.since_hours, a.head)
    except Exception as e:  # noqa: BLE001 -- fail loud, never a silent green (always-on #7)
        rep.fail("check crashed", f"{type(e).__name__}: {str(e)[:200]}")
    warns = sum(1 for ln in rep.lines if ln.startswith("WARN"))
    print(f"RESULT {a.site}: {'FAIL' if rep.fails else 'PASS'} ({rep.fails} fail, {warns} warn)")
    return 1 if rep.fails else 0


if __name__ == "__main__":
    sys.exit(main())
