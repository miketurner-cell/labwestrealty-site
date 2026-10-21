#!/usr/bin/env python3
"""STRICT: the Lab West listings switch is wired dark (sites, D-1012-34).

Rules, checked from the files alone (no network, no secrets):
  1. Every workflow other than pre-deploy.yml that is scheduled, dispatched or pushes to main
     must have a `switch` job (runs-on ubuntu-latest, reads vars.LABWEST_LISTINGS, unset = off)
     and every other job must `needs: switch` and gate on `needs.switch.outputs.state == 'on'`
     (or 'preview' where it says so) BEFORE any RETS login step.
  2. No workflow may reference NLAR_RETS_* secrets outside a job gated that way.
  3. pre-deploy.yml itself never references RETS or R2 secrets (it is the only workflow that
     runs while the switch is off).
Fail loud: a workflow we cannot parse is an error, not a skip (always-on #16).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows"
errors = []


def jobs_of(text):
    """Split a workflow into {job_name: block} using top-level 2-space job keys under `jobs:`."""
    m = re.search(r"^jobs:\s*$", text, re.M)
    if not m:
        return {}
    body = text[m.end():]
    parts = re.split(r"^  ([A-Za-z0-9_-]+):\s*$", body, flags=re.M)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


# Workflows that never touch NLAR and are exempt from the listings switch (rule 1), each with its own checks below.
NO_RETS_WORKFLOWS = {"market-stats-refresh.yml"}
files = sorted(WF.glob("*.yml")) if WF.is_dir() else []
if not files:
    errors.append(".github/workflows has no workflow files")

for f in files:
    text = f.read_text()
    jobs = jobs_of(text)
    if not jobs:
        errors.append(f"{f.name}: no jobs parsed")
        continue
    if f.name == "pre-deploy.yml":
        if re.search(r"NLAR_RETS|R2_[A-Z_]+|secrets\.", text):
            errors.append("pre-deploy.yml references secrets; it runs while the switch is off")
        continue
    if f.name in NO_RETS_WORKFLOWS:
        # Rule 1 exemption (sites, D-1021-31): reads a sibling's committed aggregates, never logs in to NLAR, so the listings
        # switch has nothing to guard. It must stay dispatch-only, RETS-free, and commit nothing unless asked.
        if re.search(r"NLAR_RETS|R2_[A-Z_]+", text):
            errors.append(f"{f.name}: an exempt workflow must not reference RETS or R2 secrets")
        if re.search(r"^\s+(schedule|push|pull_request):", text, re.M) or "workflow_dispatch" not in text:
            errors.append(f"{f.name}: an exempt workflow must be workflow_dispatch only")
        if not re.search(r"commit:\s*\n(?:\s+[a-z]+:.*\n)*?\s+default:\s*false", text):
            errors.append(f"{f.name}: the commit input must default to false")
        continue
    sw = jobs.get("switch")
    if sw is None:
        errors.append(f"{f.name}: no `switch` job")
        continue
    if "ubuntu-latest" not in sw or "vars.LABWEST_LISTINGS" not in sw or "off" not in sw:
        errors.append(f"{f.name}: switch job must run on ubuntu-latest and read vars.LABWEST_LISTINGS defaulting to off")
    for name, block in jobs.items():
        if name == "switch":
            continue
        if not re.search(r"needs:\s*\[?\s*switch", block):
            errors.append(f"{f.name}: job {name} does not need the switch job")
        if not re.search(r"needs\.switch\.outputs\.state\s*==\s*'(on|preview)'", block):
            errors.append(f"{f.name}: job {name} is not gated on needs.switch.outputs.state")
    # the gate must name `on`; `preview` is only allowed together with workflow_dispatch (a deliberate manual run)
    for name, block in jobs.items():
        if name == "switch":
            continue
        m = re.search(r"^\s+if:\s*(.+)$", block, re.M)
        cond = m.group(1) if m else ""
        if "state == 'on'" not in cond:
            errors.append(f"{f.name}: job {name} gate must include state == 'on'")
        if "'preview'" in cond and "workflow_dispatch" not in cond:
            errors.append(f"{f.name}: job {name} may run on preview only for workflow_dispatch")
    if re.search(r"^\s+schedule:", text, re.M) or re.search(r"^\s+push:", text, re.M):
        pass  # a schedule/push trigger is fine only because every job above is gated on state == 'on'
    # IndexNow must run only when the state is on (preview pages are noindex)
    for name, block in jobs.items():
        if "indexnow-submit" in block:
            m = re.search(r"- name: Notify IndexNow[^\n]*\n\s+if:\s*([^\n]+)", block)
            if not m or "state == 'on'" not in m.group(1) or "preview" in m.group(1):
                errors.append(f"{f.name}: the IndexNow step must be gated on state == 'on' only")
    # any RETS secret must sit inside a gated job
    for name, block in jobs.items():
        if name != "switch" and "NLAR_RETS" in block and "needs.switch.outputs.state" not in block:
            errors.append(f"{f.name}: job {name} uses RETS secrets without the gate")

if errors:
    print("labwest-switch-test FAILED:")
    for e in errors:
        print("  -", e)
    sys.exit(1)
print(f"labwest-switch-test OK: {len(files)} workflow file(s), every pulling job gated on LABWEST_LISTINGS")
