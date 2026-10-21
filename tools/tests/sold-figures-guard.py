#!/usr/bin/env python3
"""STRICT: no sold-derived dollar figure on a Lab West or hub page, in its committed data, or in what its generators write
(sites, D-1021-12; security report 2026-10-21 finding H3).

Why: these two repos are PUBLIC and carry no signed-in reader, and the sold price is VOW data (NLAR rules; Trestle agreement).
labwestrealty.com/market-stats.html showed 54 dollar figures computed from close prices (averages, medians, volumes), and the
nightly pipeline committed the same numbers to the repo as live-aggregates.json. What may stay: counts of sales, days on market,
active-listing figures. What may not: anything computed from ClosePrice.

This file is byte-identical in labwestrealty-site and royallepageturner-site (the hub); the generator block runs only where
tools/tests/labwest_fixtures.py exists (Lab West). Same logic, two repos, because the two repos cannot import each other in CI.

Rules, over every git-tracked .html .js .json .xml .txt .md .yml .yaml (not tools/tests, .github, .claude, *.py):
  A. a sold-price METRIC PHRASE anywhere in the file (for .js only the data keys avg_price, median_price, total_volume, ...) (average/median/mean sale price, avg_price, total volume, sale-to-list,
     sold-to-ask, price per square foot, ppsf, ...)   [raw text, so chart labels and JSON keys are caught]
  B. a DOLLAR FIGURE in the visible text of an .html page whose surrounding sentence is about sales (sold, sales, sale price,
     average, median, volume, closed)   [explicit, justified exceptions in ALLOW below]
  C. in a tracked .json file, a key that holds a close price (close_price, sold_price, ClosePrice ...)
Generated output (Lab West only): the aggregator, market-stats builder and community builder run over synthetic sold rows in a temp
copy, and pages/*.html plus live-aggregates.json go through A, B and C.

Run: python3 tools/tests/sold-figures-guard.py [--root DIR] [--list]     (--list prints every finding; exit code unchanged)
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

EXTS = {".html", ".js", ".json", ".xml", ".txt", ".md", ".yml", ".yaml"}
SKIP_PARTS = ("tools/tests/", ".github/", ".claude/", "node_modules/")

# A. metric phrases (case-insensitive). Each is a figure computed from close prices.
METRIC = re.compile(
    r"(?:avg|average|mean|median)[\s_-]*(?:sale[\s_-]*|sold[\s_-]*|selling[\s_-]*)?price"
    r"|total[\s_-]*(?:sales[\s_-]*)?volume|volume\s*\(\s*\$\s*[KkMm]?\s*\)"
    r"|(?:sale|sold)[\s_-]*to[\s_-]*(?:list|ask)"
    r"|price[\s_-]+per[\s_-]+(?:square|sq)|\$\s?/\s?(?:sq|sf)|ppsf|avg_sa\b",
    re.I)

# .js files are logic, not copy: js/sold-listings.js legitimately computes a ratio for a signed-in reader from rows the gate returns. For
# .js only these data keys count (a bundled data file such as regions-data.js must not carry them).
METRIC_JS_KEYS = re.compile(r"\b(?:avg_price|median_price|total_volume|avg_sa|median_ppsf|avg_sale_price|median_sold_price|ppsf)\b")

# C. keys that hold a close price in tracked JSON
CLOSE_KEY = re.compile(r"^(?:close_?price|sold_?price|sale_?price|closeprice)$", re.I)

# B. a dollar figure, and the words that make the sentence around it a statement about sales
DOLLAR = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s?[KkMm]?\b")
SALES_WORDS = re.compile(r"\b(?:sold|sales?|sale price|closed|closing price|average|averages|median|volume|avg)\b", re.I)

# Justified exceptions: (file suffix, text that must be in the matched window). Empty on purpose: a dollar figure that is not a sold
# price (a licensing cost, a list price) does not sit next to sales words. Add an entry only with the reason beside it.
ALLOW = []


def strip_html(raw):
    t = re.sub(r"<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->", " ", raw, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = (t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&mdash;", "-").replace("&ndash;", "-")
         .replace("&rsquo;", "'").replace("&reg;", ""))
    return re.sub(r"\s+", " ", t)


def tracked_files(root):
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=True).stdout.split("\n")
        files = [root / f for f in out if f]
    except Exception:
        files = [p for p in root.rglob("*") if p.is_file() and ".git/" not in p.as_posix()]
    res = []
    for p in files:
        rel = p.relative_to(root).as_posix()
        if p.suffix.lower() in EXTS and not any(s in "/" + rel or rel.startswith(s) for s in SKIP_PARTS) and p.exists():
            res.append(p)
    return res


def walk_keys(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield path + "/" + str(k), str(k)
            yield from walk_keys(v, path + "/" + str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk_keys(v, path + f"[{i}]")


def scan_file(rel, raw):
    """Return a list of (rule, snippet) findings for one file's text."""
    found = []
    if rel.endswith(".html"):  # class names in a style block (.ms-ppsf-val) are not figures
        raw_a = re.sub(r"<style\b.*?</style>", " ", raw, flags=re.S | re.I)
    else:
        raw_a = raw
    for m in (METRIC_JS_KEYS if rel.endswith(".js") else METRIC).finditer(raw_a):
        a = max(0, m.start() - 40)
        found.append(("A", re.sub(r"\s+", " ", raw_a[a:m.end() + 40])))
    suffix = rel.rsplit("/", 1)[-1]
    if rel.endswith(".json"):
        try:
            for path, k in walk_keys(json.loads(raw)):
                if CLOSE_KEY.match(k):
                    found.append(("C", path))
        except ValueError:
            pass
    if rel.endswith(".html"):
        text = strip_html(raw)
        for m in DOLLAR.finditer(text):
            win = text[max(0, m.start() - 140): m.end() + 140]
            if not SALES_WORDS.search(win):
                continue
            if any(rel.endswith(f) and needle.lower() in win.lower() for f, needle in ALLOW):
                continue
            found.append(("B", re.sub(r"\s+", " ", win[100:200])))
    return found


def scan_tree(root, label=""):
    findings = []
    for p in tracked_files(root):
        rel = p.relative_to(root).as_posix()
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for rule, snip in scan_file(rel, raw):
            findings.append((rel, rule, snip))
    return findings


def scan_generated(root):
    """Lab West only: run the real pipeline over the synthetic sold rows and scan what it writes."""
    sys.path.insert(0, str(root / "tools" / "tests"))
    import labwest_fixtures  # noqa: E402
    rows = labwest_fixtures.sold_full_rows()
    tmp = Path(tempfile.mkdtemp(prefix="soldguard-"))
    findings = []
    try:
        work = tmp / "site"
        shutil.copytree(root, work, ignore=shutil.ignore_patterns(".git", ".claude", "node_modules", "__pycache__", "listings", "property", "pages"))
        cache = work / "tools" / "idx-cache"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "sold-listings-full.json").write_text(json.dumps({"fetched_at": "2026-10-11T20:00:00Z", "rows": rows}))
        for args in (["tools/idx-stats-aggregator.py"], ["tools/build-market-stats-page.py", "--all"], ["tools/build-community-pages.py", "--all"]):
            r = subprocess.run([sys.executable, *args], cwd=work, capture_output=True, text=True)
            if r.returncode != 0:
                findings.append(("generated", "X", f"{args[0]} failed: {(r.stdout + r.stderr)[-200:]}"))
        outs = [cache / "live-aggregates.json", *sorted((work / "pages").glob("*.html"))]
        if not (work / "pages" / "market-stats.html").exists():
            findings.append(("generated", "X", "pages/market-stats.html was not written, so it could not be checked"))
        for p in outs:
            if not p.exists():
                findings.append(("generated", "X", f"{p.name} was not written"))
                continue
            rel = "generated/" + p.name
            raw = p.read_text(encoding="utf-8")
            for rule, snip in scan_file(rel, raw):
                findings.append((rel, rule, snip))
            if p.suffix == ".json":
                # the aggregates must carry no price-bearing key at any depth (counts and days on market only)
                for path, k in walk_keys(json.loads(raw)):
                    if re.search(r"price|volume|ppsf|(^|_)sa($|_)|at_100", k, re.I):
                        findings.append((rel, "C", path))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return findings


def load_debt(root):
    """Known, owned findings per file (hub only, while its pages are fixed): {"market-stats.html": 12}. A ratchet: a file may not
    gain findings, and a file whose count drops must have its number lowered here, so debt cannot hide a new figure."""
    p = root / "tools" / "tests" / "sold-figures-known-debt.json"
    if not p.exists():
        return {}
    return {k: int(v) for k, v in json.loads(p.read_text()).items() if not k.startswith("_")}


def apply_debt(findings, debt):
    by_file = {}
    for f in findings:
        by_file.setdefault(f[0], []).append(f)
    out, notes = [], []
    for rel, items in by_file.items():
        if rel in debt and len(items) == debt[rel]:
            notes.append(f"{rel}: {len(items)} known finding(s) (baseline)")
            continue
        if rel in debt:
            notes.append(f"{rel}: {len(items)} finding(s) but the baseline says {debt[rel]}: lower the baseline when you remove figures, never raise it")
        out.extend(items)
    for rel, n in debt.items():
        if rel not in by_file and n:
            out.append((rel, "X", f"baseline lists {n} finding(s) but the file is clean: delete its baseline entry"))
    return out, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--no-generated", action="store_true")
    a = ap.parse_args()
    root = Path(a.root).resolve()
    findings = scan_tree(root)
    n_static = len(findings)
    if (root / "tools" / "tests" / "labwest_fixtures.py").exists() and not a.no_generated:
        findings += scan_generated(root)
    n_gen = len(findings) - n_static
    raw_total = len(findings)
    findings, notes = apply_debt(findings, load_debt(root))
    files = sorted({f[0] for f in findings})
    print(f"sold-figures-guard: {raw_total} raw finding(s) ({n_static} in tracked files, {n_gen} in generated output); "
          f"{len(findings)} not covered by the known-debt baseline, across {len(files)} file(s)")
    for n in notes:
        print("  note:", n)
    if findings:
        shown = findings if a.list else findings[:25]
        for rel, rule, snip in shown:
            print(f"  [{rule}] {rel}: {snip[:150]}")
        if len(findings) > len(shown):
            print(f"  ... {len(findings) - len(shown)} more (run with --list)")
        print("FAILED: a sold-derived figure (average, median, volume, sale-to-list, price per square foot, close price) may not appear on a public page, in committed data, or in generator output.")
        sys.exit(1)
    print("sold-figures-guard OK: counts and days on market only")


if __name__ == "__main__":
    main()
