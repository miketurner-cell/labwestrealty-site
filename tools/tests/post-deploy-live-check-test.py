#!/usr/bin/env python3
"""STRICT 3874: the post-deploy live check (D-1021-07) works offline and cannot become a second alert channel or a writer.

Mike, 2026-10-21 08:32 UTC (D-1021-07): "Post-deploy live check (Recommended)": an automatic check after every production deploy on
all five sites; alert through the existing failure channel only (no new Telegram/e-mail noise). Byte-identical in the five repos.
Asserts: the script's own offline self-test passes (git-backed scenarios, fake HTTP); the workflow triggers on push to main and on a
schedule, is read-only (contents: read), names a valid --site, uses no secret except the optional NETLIFY_AUTH_TOKEN, and neither the
workflow nor the script can send anything (no Telegram/Postmark/Twilio/SMTP/Slack, no POST/PUT/DELETE).
  python3 tools/tests/post-deploy-live-check-test.py     Exit 0 = all pass."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R = []


def check(name, ok, detail=""):
    R.append((name, bool(ok), detail))


script = ROOT / "tools" / "post-deploy-live-check.py"
wf = ROOT / ".github" / "workflows" / "post-deploy-live-check.yml"
check("script exists", script.exists())
# Byte-identity across the five repos (D-1021-07 "byte-identical in the five repos"): the script's sha256 must equal the one recorded in
# tools/post-deploy-live-check.sha256, and that file is the same in all five repos. Editing the script in one repo without the hash (or in only
# one repo, since the other four keep the old hash) is caught here. To change the script: edit it, regenerate the hash with
#   shasum -a 256 tools/post-deploy-live-check.py | cut -d' ' -f1 > tools/post-deploy-live-check.sha256
# and land the same two files in gander, avalon, goosebay, labwest and hub.
import hashlib
_hf = ROOT / "tools" / "post-deploy-live-check.sha256"
check("script sha256 matches tools/post-deploy-live-check.sha256 (fleet byte-identical copy)",
      script.exists() and _hf.exists() and hashlib.sha256(script.read_bytes()).hexdigest() == _hf.read_text().split()[0],
      "re-sync all five repos if you changed the script")
if script.exists():
    r = subprocess.run([sys.executable, str(script), "--self-test"], capture_output=True, text=True)
    bad = [ln for ln in r.stdout.splitlines() if ln.startswith("FAIL  ")]
    check("script --self-test passes", r.returncode == 0 and not bad, (r.stdout + r.stderr)[-400:] if r.returncode else "")
    src = script.read_text()
    check("script never sends: no Telegram/Postmark/Twilio/SMTP/Slack/Resend", not re.search(r"(?i)telegram|postmark|twilio|smtplib|hooks\.slack|resend\.com|sendgrid|mailgun", src))
    check("script is GET-only", not re.search(r"""(?i)method\s*=\s*["'](POST|PUT|PATCH|DELETE)|urlopen\([^)]*data\s*=|\.post\(""", src))
    check("script writes no file", not re.search(r"""open\([^)]*,\s*["'][wa]""", src.split("def self_test")[0]))
    envs = set(re.findall(r"os\.environ(?:\.get)?\(?\[?\s*[\"']([A-Z0-9_]+)", src.split("def self_test")[0]))
    check("script reads only its own env names and no heartbeat table", envs <= {"NETLIFY_AUTH_TOKEN", "NETLIFY_SITE_ID", "HUB_SOLD_STRICT", "GITHUB_ACTIONS"}
          and "system_heartbeats" not in src, str(envs))
pre = ROOT / ".github" / "workflows" / "pre-deploy.yml"
if wf.exists():
    t = wf.read_text()
    check("workflow runs on push to main", re.search(r"(?m)^  push:\s*\n\s+branches: \[main\]", t))
    check("workflow has a schedule", re.search(r"(?m)^  schedule:\s*\n\s+- cron: \"[^\"]+\"", t))
    check("workflow is read-only", re.search(r"(?m)^permissions:\s*\n  contents: read\s*$", t) and "write" not in re.sub(r"#.*", "", t).split("permissions:")[1].split("concurrency")[0])
    body = t
elif pre.exists() and "  live-check:" in pre.read_text():
    # Lab West: labwest-registry-test.py keeps every workflow but pre-deploy.yml dispatch-only, so the check is a push-only job there.
    pt = pre.read_text()
    body = "  live-check:" + pt.split("  live-check:", 1)[1]
    check("live-check job runs only on push", "if: github.event_name == 'push'" in body)
    check("pre-deploy.yml is read-only", re.search(r"(?m)^permissions:\s*\n  contents: read\s*$", pt) and "write" not in re.sub(r"#.*", "", pt).split("permissions:")[1].split("jobs:")[0])
else:
    body = ""
    check("a post-deploy-live-check workflow or a pre-deploy.yml live-check job exists", False)
if body:
    sites = re.findall(r"--site (gander|avalon|goosebay|labwest|hub)\b", body)
    check("workflow names exactly one valid --site", len(sites) == 1, str(sites))
    secrets = set(re.findall(r"secrets\.([A-Z0-9_]+)", re.sub(r"(?m)#.*$", "", body)))
    check("only the optional NETLIFY_AUTH_TOKEN secret is referenced", secrets <= {"NETLIFY_AUTH_TOKEN"}, str(secrets))
    check("workflow has no alert channel", not re.search(r"(?i)telegram|postmark|twilio|sendgrid|hooks\.slack|mail\b|heartbeat", re.sub(r"(?m)^\s*#.*$", "", body)))
    check("push runs wait for the deploy", "WAIT=1200" in body or "--wait 1200" in body)
fails = [(n, d) for n, ok, d in R if not ok]
for n, ok, d in R:
    print(("PASS  " if ok else "FAIL  ") + n + (f"  [{d}]" if d and not ok else ""))
sys.exit(1 if fails else 0)
