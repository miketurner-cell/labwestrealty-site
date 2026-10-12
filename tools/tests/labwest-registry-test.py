#!/usr/bin/env python3
"""STRICT: the Lab West test set is complete and the raw feed stays private (sites, D-1012-34, component 13).

  1. Every test file under tools/tests/ is a step in .github/workflows/pre-deploy.yml (a test nobody runs protects nothing).
  2. _redirects forces /tools/* to 404, so the projected cache and every other tools file stay private; no browser JS requests
     the projected cache URL (the chat function reads a bundled copy).
  3. Every workflow other than pre-deploy.yml is dispatch-only: no `schedule:` and no push trigger (the cadence is the box's,
     added only after Mike's flip).
  4. No workflow, script or config sets or names a repo variable LABWEST_LISTINGS value of on/preview (the flip is Mike's).
Fails loud on a missing file.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
errors = []

wf = (ROOT / ".github" / "workflows" / "pre-deploy.yml").read_text()
for t in sorted((ROOT / "tools" / "tests").iterdir()):
    if t.is_file() and t.suffix in (".py", ".mjs") and not t.name.startswith("_") and t.name != "labwest_fixtures.py":
        if t.name not in wf:
            errors.append(f"1: {t.name} is not run by pre-deploy.yml")

red = (ROOT / "_redirects").read_text()
if not re.search(r"^/tools/\*\s+/404\.html\s+404!", red, re.M):
    errors.append("2: _redirects does not force /tools/* to 404")
for p in (ROOT / "js").glob("*.js"):
    if re.search(r"""['"]/tools/idx-cache/listings-projected\.json['"]""", p.read_text(encoding="utf-8", errors="ignore")):
        errors.append(f"2: js/{p.name} requests the projected cache URL")

for p in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
    if p.name == "pre-deploy.yml":
        continue
    t = p.read_text()
    if re.search(r"^\s*schedule:", t, re.M) or re.search(r"^\s*push:", t, re.M) or re.search(r"^\s*pull_request", t, re.M):
        errors.append(f"3: {p.name} has a schedule, push or pull_request trigger")

for p in list((ROOT / ".github").rglob("*")) + list((ROOT / "tools").glob("*")):
    if p.is_file() and p.suffix in (".yml", ".py", ".json", ".sh"):
        t = p.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"gh variable set\s+LABWEST_LISTINGS|gh api[^\n]*variables[^\n]*LABWEST_LISTINGS", t) and "test" not in p.name:
            errors.append(f"4: {p.relative_to(ROOT)} sets the LABWEST_LISTINGS switch")

if errors:
    print("labwest-registry-test FAILED:")
    for e in errors:
        print("  -", e)
    sys.exit(1)
print("labwest-registry-test OK: every test is run in CI, raw feed private, workflows dispatch-only, switch never set")
