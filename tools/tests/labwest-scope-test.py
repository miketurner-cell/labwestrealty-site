#!/usr/bin/env python3
"""STRICT: Lab West feed scope, lease drop and site config (sites, D-1012-34, component 2).

Offline. Builds synthetic raw feed rows (shape taken from the 2026-10-12 feed sample) and runs the
real projector. Checks:
  1. Labrador City (A2V) and Wabush (A0R) rows are in scope; the Subdistrict "Labrador City / Wabush"
     is in scope; coastal Labrador on A0R (Nain), Goose Bay (A0P) and the island are out.
  2. TransactionType LEASE is dropped at projection and counted; SALE and blank type stay.
  3. Projected rows carry scope labwest, city slugs labrador-city / wabush, and R2 photo URLs under labwest/.
  4. idx_fields.py is the fleet field list (TransactionType kept) and _fleet_config.json names labwest.
  5. The projector source carries no Lab West street address.
"""
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
errors = []


def check(cond, msg):
    if not cond:
        errors.append(msg)


spec = importlib.util.spec_from_file_location("proj", TOOLS / "idx-project-to-ddf-shape.py")
proj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proj)


def row(mls, city, postal, tt=None, sub=None, status="Active"):
    r = {"MLSNumber": mls, "StreetNumber": "1", "StreetName": "Test", "CityText": city, "City": "",
         "PostalCode": postal, "ListPrice": "250000.00", "PropertyType": "Residential",
         "PropertySubType": "Single Family", "ListingContractDate": "2026-10-05", "Status": status,
         "ListOfficeName": "Royal LePage Turner Realty 2014 Inc - Labrador", "PhotoCount": "3",
         "MatrixModifiedDT": "2099-01-01T00:00:00"}
    if tt is not None:
        r["TransactionType"] = tt
    if sub is not None:
        r["Subdistrict"] = sub
    return r


rows = [
    row("1001", "Labrador City", "A2V 2T1"),
    row("1002", "Wabush", "A0R 1B0"),
    row("1003", "Labrador", "A2V 1A1", sub="Labrador City / Wabush"),
    row("1004", "Nain", "A0P 1L0"),
    row("1005", "Hopedale", "A0P 1G0"),
    row("1006", "Happy Valley-Goose Bay", "A0P 1C0"),
    row("1007", "Gander", "A1V 1L6"),
    row("1008", "Hebron", "A0R 1K0"),                  # coastal A0R, not a Lab West town
    row("1009", "Wabush", "A0R 1B0", tt="LEASE"),
    row("1010", "Labrador City", "A2V 2T1", tt="SALE"),
    row("1011", "Labrador City", "", tt=None),          # no postal: falls back to the town name
]
scope = {r["MLSNumber"]: proj.in_scope(r) for r in rows}
check(scope["1001"] and scope["1002"] and scope["1003"] and scope["1010"] and scope["1011"], f"Lab West rows must be in scope: {scope}")
check(not any(scope[k] for k in ("1004", "1005", "1006", "1007", "1008")), f"out-of-scope rows leaked in: {scope}")
check(proj.is_lease_row(rows[8]) and not proj.is_lease_row(rows[9]) and not proj.is_lease_row(rows[0]), "lease detection wrong")

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    (td / "in.json").write_text(json.dumps({"fetched_at": "2026-10-12T00:00:00Z", "rows": rows}))
    out = td / "out.json"
    env = {"R2_BASE_URL": "https://photos.example.test", "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, str(TOOLS / "idx-project-to-ddf-shape.py"), "--in", str(td / "in.json"),
                        "--out", str(out), "--site-root", str(td)], capture_output=True, text=True, env=env)
    check(r.returncode == 0, f"projector failed: {r.stderr[-300:]}")
    if r.returncode == 0:
        d = json.loads(out.read_text())
        mls = sorted(x["mls"] for x in d["listings"])
        check(mls == ["1001", "1002", "1003", "1010", "1011"], f"projected set wrong: {mls}")
        check(d.get("scope") == "labwest", "payload scope must be labwest")
        check(d.get("skipped_lease") == 1, f"lease count wrong: {d.get('skipped_lease')}")
        slugs = {x["mls"]: x["city_slug"] for x in d["listings"]}
        check(slugs.get("1001") == "labrador-city" and slugs.get("1002") == "wabush", f"city slugs wrong: {slugs}")
        urls = [p["url"] for x in d["listings"] for p in x["photos"]]
        check(urls and all("/labwest/listings/" in u for u in urls), "photo URLs must sit under the labwest/ R2 prefix")

cfg = json.loads((TOOLS / "_fleet_config.json").read_text())
check(cfg.get("site_key") == "labwest" and cfg.get("r2_site_slug") == "labwest", "tools/_fleet_config.json must name labwest")
spec2 = importlib.util.spec_from_file_location("idxf", TOOLS / "idx_fields.py")
idxf = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(idxf)
check("TransactionType" in idxf.SAFE_FIELDS_ACTIVE and "TransactionType" not in idxf.NEVER_PROJECT, "TransactionType must be a kept field")
check("Subdistrict" in idxf.SAFE_FIELDS_ACTIVE, "Subdistrict must be a kept field (scope uses it)")

src = (TOOLS / "idx-project-to-ddf-shape.py").read_text()
check(not re.search(r"\d+\s+(Hamilton|Airport|Avalon|Humphrey|Loring)\b", src), "street address in projector")

if errors:
    print("labwest-scope-test FAILED:")
    for e in errors:
        print("  -", e)
    sys.exit(1)
print("labwest-scope-test OK: scope, lease drop, slugs, R2 prefix, config")
