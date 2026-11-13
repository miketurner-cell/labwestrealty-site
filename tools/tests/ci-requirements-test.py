#!/usr/bin/env python3
"""STRICT 3012 (sites, Mike D-1113-68, 2026-11-13): every third-party module a registered CI test imports is declared.

Why: a second CI box failed every Pre-deploy run with "No module named 'yaml'". The jobs run under the actions/setup-python tool-cache
interpreter, and the first box's copy had PyYAML and 46 other packages from a hand install long ago; a fresh box's had none. The dependency
was undeclared and invisible. tools/ci/requirements-ci.txt now declares it and pre-deploy.yml installs it on every runner; this test
fails when a test (or a local module a test imports) starts importing something that file does not list, so the next one is caught in
the PR that adds it and not on the next new machine.

What it reads: the files the workflow runs (strict.d registrations' "run" scripts and the python3 lines of pre-deploy.yml), then the local
modules they import, transitively. A third-party import counts when it is not guarded by try/except ImportError (or `except Exception`) and sits at module level (a guarded import is a
soft dependency the code survives losing). Declared = in requirements-ci.txt, or in the registration's own "pip" list (run_strict.py
installs those), or in SELF_MANAGED below. Offline; stdlib only (it must run before the requirements are installed).
  python3 tools/tests/ci-requirements-test.py
"""
import ast
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REQ = os.path.join(ROOT, "tools", "ci", "requirements-ci.txt")
WF = os.path.join(ROOT, ".github", "workflows", "pre-deploy.yml")
STRICT_D = os.path.join(ROOT, "tools", "tests", "strict.d")

# import name -> distribution name, where they differ
DIST = {"PIL": "pillow", "yaml": "pyyaml", "jwt": "pyjwt", "google": "google-auth", "bs4": "beautifulsoup4", "dateutil": "python-dateutil",
        "cv2": "opencv-python", "pillow_heif": "pillow-heif", "OpenSSL": "pyopenssl", "Crypto": "pycryptodome", "serial": "pyserial"}
# Installed by the test itself (it pins the version, installs into a cache dir and also fetches the browser), so not in the shared file.
SELF_MANAGED = {"playwright": "the consent / listings / VOW browser tests pip-install playwright==1.60.0 and run `playwright install chromium` themselves"}

# Names that look third-party but are this fleet's own modules that exist only in some repos (a test imports them in a branch that runs only there).
REPO_LOCAL_ELSEWHERE = {"team_claims", "agent_roster_check", "roster_copies_check", "labwest_fixtures"}

R = []
def check(name, ok, detail=""):
    R.append((name, bool(ok), detail))

def norm(s):
    return re.split(r"[<>=!~\[; ]", s.strip(), maxsplit=1)[0].lower().replace("_", "-").replace(".", "-")

def declared():
    if not os.path.isfile(REQ):
        return None
    out = set()
    for ln in open(REQ, encoding="utf-8"):
        ln = ln.split("#", 1)[0].strip()
        if ln and not ln.startswith("-"):
            out.add(norm(ln))
    return out

# every .py in the repo, by importable name
LOCAL = {}
for dp, dn, fn in os.walk(ROOT):
    dn[:] = [d for d in dn if d not in (".git", "node_modules", "_archive", "worktrees")]
    for f in fn:
        if f.endswith(".py"):
            full = os.path.join(dp, f)
            LOCAL.setdefault(f[:-3], []).append(full)
            LOCAL.setdefault(f[:-3].replace("-", "_"), []).append(full)

def entries():
    """-> {py file: set(dist names the registration installs itself)}"""
    scripts = []  # (run text, extra pip names)
    if os.path.isdir(STRICT_D):
        for f in sorted(os.listdir(STRICT_D)):
            if f[:4].isdigit() and f.endswith(".json"):
                r = json.load(open(os.path.join(STRICT_D, f), encoding="utf-8"))
                scripts.append((r.get("run", ""), {norm(p) for p in r.get("pip", [])}))
    if os.path.isfile(WF):
        run_lines = [ln for ln in open(WF, encoding="utf-8") if not ln.lstrip().startswith("#")]
        scripts.append(("".join(run_lines), set()))
    found = {}
    for text, pip in scripts:
        for m in re.findall(r"(?<![\w./-])((?:tools/)[\w./-]+\.py)\b", text):
            p = os.path.join(ROOT, m)
            if os.path.isfile(p):
                found.setdefault(p, set()).update(pip)
    return found

def is_std(top):
    """True for a standard-library module. sys.stdlib_module_names on 3.10+; on older interpreters, a module whose file sits outside site-packages."""
    names = getattr(sys, "stdlib_module_names", None)
    if names is not None:
        return top in names
    import importlib.util
    try:
        spec = importlib.util.find_spec(top)
    except (ImportError, ValueError):
        return False
    return spec is not None and "site-packages" not in (spec.origin or "") and "dist-packages" not in (spec.origin or "")

def walk_top(node):
    """ast.walk without descending into function bodies: a function-level import only runs when that function does (the tests that reach
    one stub it or never call it), while a module-level import runs on `import`. Checked 2026-11-13 against a bare interpreter running
    every registration: the module-level rule matches what actually failed."""
    yield node
    for ch in ast.iter_child_nodes(node):
        if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield from walk_top(ch)

def hard_imports(path):
    """-> (set of top-level third-party import names not guarded by try/except ImportError, set of local module paths to follow)"""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (SyntaxError, UnicodeDecodeError):
        return set(), set()
    guarded = set()
    for n in walk_top(tree):
        if isinstance(n, ast.Try) and any(h.type is not None and re.search(r"ImportError|ModuleNotFoundError|'Exception'", ast.dump(h.type)) for h in n.handlers):
            for b in n.body:
                for k in walk_top(b):
                    guarded.add(id(k))
    third, local = set(), set()
    for n in walk_top(tree):
        mods = []
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            mods = [n.module]
        for full in mods:
            top = full.split(".")[0]
            if top in LOCAL:
                local.update(LOCAL[top])
            elif id(n) not in guarded and not is_std(top) and top != "__future__" and top not in REPO_LOCAL_ELSEWHERE:
                third.add(top)
    return third, local


req = declared()
check("tools/ci/requirements-ci.txt exists (an empty list is a statement that no test needs a package)", req is not None, REQ)
_wf = "".join(ln for ln in open(WF, encoding="utf-8") if not ln.lstrip().startswith("#")) if os.path.isfile(WF) else ""
_inst = re.search(r"pip install[^\n]*-r tools/ci/requirements-ci\.txt", _wf)
_first = re.search(r"python3? tools/", _wf)
check("pre-deploy.yml installs tools/ci/requirements-ci.txt before its first python step (when the file lists anything)",
      not req or (_inst and _first and _inst.start() < _first.start()), WF)

ent = entries()
check("the scan found the registered tests (a scan that finds nothing proves nothing)", len(ent) >= 5, len(ent))
missing = {}
reached = 0
if req is not None:
    for start, pip in ent.items():
        seen, stack = set(), [start]
        while stack:
            p = stack.pop()
            if p in seen:
                continue
            seen.add(p)
            third, local = hard_imports(p)
            stack.extend(local)
            for top in third:
                dist = norm(DIST.get(top, top))
                if dist in req or dist in pip or top in SELF_MANAGED:
                    continue
                missing.setdefault(top, set()).add(os.path.relpath(p, ROOT))
        reached += len(seen)
    check("the import walk reached at least the files it started from (local modules are followed)", reached >= len(ent), (reached, len(ent)))
check("every third-party module a registered test imports is in requirements-ci.txt (or the registration's own pip list)",
      not missing, {k: sorted(v)[:3] for k, v in sorted(missing.items())})
# every requirement is still used: a stale line is a slower install on every run
if req is not None:
    used = set()
    for start in ent:
        seen, stack = set(), [start]
        while stack:
            p = stack.pop()
            if p in seen:
                continue
            seen.add(p)
            third, local = hard_imports(p)
            stack.extend(local)
            used.update(norm(DIST.get(t, t)) for t in third)
    # soft (guarded) imports also justify a line, so scan them too
    soft_ok = set()
    for p in {q for v in LOCAL.values() for q in v if "/tools/" in q}:
        try:
            for n in ast.walk(ast.parse(open(p, encoding="utf-8").read())):
                if isinstance(n, ast.Import):
                    soft_ok.update(norm(DIST.get(a.name.split(".")[0], a.name.split(".")[0])) for a in n.names)
                elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                    soft_ok.update([norm(DIST.get(n.module.split(".")[0], n.module.split(".")[0]))])
        except (SyntaxError, UnicodeDecodeError):
            pass
    stale = sorted(r for r in req if r not in used and r not in soft_ok)
    check("every line of requirements-ci.txt is imported by some tool (no dead weight in a per-run install)", not stale, stale)
check("the self-managed list is only playwright (anything else belongs in the requirements file)", set(SELF_MANAGED) == {"playwright"}, list(SELF_MANAGED))

bad = [(n, d) for n, ok, d in R if not ok]
for n, ok, d in R:
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else "  -> " + str(d)[:400]))
print("[ci-requirements] %d checks, %d failed" % (len(R), len(bad)))
sys.exit(1 if bad else 0)
