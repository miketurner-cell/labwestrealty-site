#!/usr/bin/env python3
"""STRICT: tools/seo-safety-check.py catches each kind of search loss and stays quiet on a clean change.

2026-10-11 (sites, D-1011-21 item 1). Offline: builds a throwaway git repo, commits a base site, then
commits a head with one mutation per case and runs the checker between the two commits. Guards the
guard: a checker that cannot see a lost title would pass every PR (always-on #10).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(os.path.dirname(HERE), "seo-safety-check.py")
HOST = "https://example.test"

PAGE = ('<!doctype html><html><head><title>{t}</title>{d}{c}{r}</head><body><a href="/">home</a></body></html>')
D = '<meta name="description" content="A good description.">'
C = '<link rel="canonical" href="{h}/pages/a.html">'.format(h=HOST)


def page(t="Page A", d=D, c=C, r=""):
    return PAGE.format(t=t, d=d, c=c, r=r)


def home(links=("/pages/a.html", "/pages/b.html")):
    return "<html><head><title>Home</title></head><body><nav>" + "".join(f'<a href="{l}">x</a>' for l in links) + "</nav></body></html>"


def sitemap(paths=("/", "/pages/a.html", "/pages/b.html")):
    return "<urlset>" + "".join(f"<url><loc>{HOST}{p}</loc></url>" for p in paths) + "</urlset>"


BASE = {
    "index.html": home(), "pages/a.html": page(), "pages/b.html": page(t="Page B", c=C.replace("a.html", "b.html")),
    "sitemap.xml": sitemap(), "robots.txt": "User-agent: *\nDisallow: /private/\n", "netlify.toml": "", "_redirects": "",
    "tools/seo-pages.json": json.dumps({"pages": [{"path": "/"}, {"path": "/pages/a.html"}, {"path": "/pages/b.html"}]}),
}

CASES = [  # name, file edits (None deletes), expected loss kinds on /pages/a.html, expected notes substring
    ("clean-edit-body", {"pages/a.html": page().replace("home", "home page")}, set(), None),
    ("title-rewritten-is-a-note", {"pages/a.html": page(t="Page A new")}, set(), "title changed"),
    ("title-lost", {"pages/a.html": page(t="")}, {"title"}, None),
    ("description-lost", {"pages/a.html": page(d="")}, {"description"}, None),
    ("canonical-lost", {"pages/a.html": page(c="")}, {"canonical"}, None),
    ("canonical-moved", {"pages/a.html": page(c=C.replace("a.html", "b.html"))}, {"canonical"}, None),
    ("noindex-meta", {"pages/a.html": page(r='<meta name="robots" content="noindex,follow">')}, {"indexable"}, None),
    ("robots-disallow", {"robots.txt": "User-agent: *\nDisallow: /pages/\n"}, {"indexable"}, None),
    ("x-robots-header", {"netlify.toml": '[[headers]]\n  for = "/pages/*"\n  [headers.values]\n    X-Robots-Tag = "noindex"\n'}, {"indexable"}, None),
    ("sitemap-entry-dropped", {"sitemap.xml": sitemap(("/", "/pages/b.html"))}, {"sitemap"}, None),
    ("home-link-dropped", {"index.html": home(("/pages/b.html",))}, {"home-link"}, None),
    ("page-deleted", {"pages/a.html": None}, {"gone"}, None),
    ("page-deleted-with-301-is-a-note", {"pages/a.html": None, "_redirects": "/pages/a.html /pages/b.html 301!\n"}, set(), "redirected"),
    ("pretty-url-link-still-counts", {"index.html": home(("/pages/a", "/pages/b/"))}, set(), None),
]


def run(*a, cwd):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True)


def commit(repo, files, msg):
    for p, body in files.items():
        full = os.path.join(repo, p)
        if body is None:
            os.path.exists(full) and os.remove(full)
            continue
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "w").write(body)
    run("git", "add", "-A", cwd=repo)
    r = run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", msg, "--allow-empty", cwd=repo)
    assert r.returncode == 0, r.stderr
    return run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()


def main():
    bad = []
    tmp = tempfile.mkdtemp(prefix="seo-safety-")
    try:
        for name, edits, want, note in CASES:
            repo = os.path.join(tmp, name)
            os.makedirs(os.path.join(repo, "tools"))
            shutil.copy(CHECK, os.path.join(repo, "tools", "seo-safety-check.py"))
            run("git", "init", "-q", cwd=repo)
            b = commit(repo, BASE, "base")
            h = commit(repo, edits, "head")
            r = run(sys.executable, "tools/seo-safety-check.py", "--base", b, "--head", h, "--mode", "fail", cwd=repo)
            got = {l.split()[2] for l in r.stdout.splitlines() if "LOSS" in l and "/pages/a.html" in l}
            if got != want:
                bad.append(f"{name}: wanted losses {sorted(want)}, got {sorted(got)}\n{r.stdout}{r.stderr}")
            if (r.returncode == 1) != bool(want):
                bad.append(f"{name}: exit code {r.returncode} for losses {sorted(want)}")
            if note and note not in r.stdout:
                bad.append(f"{name}: expected a note containing {note!r}\n{r.stdout}")
            print(f"{'ok  ' if not any(x.startswith(name + ':') for x in bad) else 'FAIL'} {name}")
        # warn mode never fails the build, and says so loudly when it sees a loss.
        repo = os.path.join(tmp, "title-lost")
        r = run(sys.executable, "tools/seo-safety-check.py", "--base", "HEAD~1", "--head", "HEAD", "--mode", "warn", cwd=repo)
        if r.returncode != 0 or "LOSS title" not in r.stdout:
            bad.append("warn mode: must exit 0 and still print the LOSS line")
        # no base commit: loud exit 2, never a silent pass.
        solo = os.path.join(tmp, "solo")
        os.makedirs(os.path.join(solo, "tools"))
        shutil.copy(CHECK, os.path.join(solo, "tools", "seo-safety-check.py"))
        run("git", "init", "-q", cwd=solo)
        commit(solo, BASE, "only")
        r = run(sys.executable, "tools/seo-safety-check.py", cwd=solo)
        if r.returncode != 2:
            bad.append(f"no base: expected exit 2, got {r.returncode}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if bad:
        print("\nFAIL:\n" + "\n".join(bad))
        return 1
    print("seo-safety-check-test: all cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
