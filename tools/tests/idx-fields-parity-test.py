#!/usr/bin/env python3
"""The feed field list equals Gander's, and nothing new reaches a page yet.

Sites, D-1009-29 (2026-10-09). Same file in Avalon and Goose Bay.

Background: each listing repo used to carry its own SAFE_FIELDS_ACTIVE /
NEVER_PROJECT inside tools/idx-ingest.py. They drifted (Gander 122 fields,
Avalon 97, Goose Bay 95; PendingDate, Possession and SignYN denylisted on
Avalon / Goose Bay) while the sold-data emitter on every site read those
fields, so Goose Bay's "Under contract" row was silently empty (0 of 156 sold
rows with a pending date on 2026-10-08). The lists now live in
tools/idx_fields.py.

Checks (offline, no RETS call):
  1. tools/idx_fields.py SAFE_FIELDS_ACTIVE / NEVER_PROJECT equal Gander's,
     pinned as count + SHA-256 of the sorted names, taken from
     realestategander-site tools/idx-ingest.py on origin/main 0e81cdd5b2.
     If a Gander checkout is reachable (env GANDER_IDX_INGEST, or a sibling
     realestategander-site folder), the sets are also compared against it
     directly, name by name.
  2. tools/idx-ingest.py imports both sets from idx_fields and defines no
     local copy at module level (a local copy is how the drift started).
  3. PendingDate / Possession / SignYN are kept and not denylisted.
  4. Every raw feed field the sold-data emitter (ddf-generate-pages.py
     emit_sold_data) reads is in the field list, apart from a short, named
     list of fallback names -- the check that would have caught the drift.
  5. The display hold: the first statement of the sold loop is the
     hold_sold_display_fields() call, every held name is a kept field,
     PendingDate is never held, and the function drops held keys and keeps
     exempt ones.
  6. The pin can fail: one name added or removed changes the digest.

Exit 0 = all pass; exit 1 = a finding (printed).
"""
import ast
import hashlib
import importlib.util
import os
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent

# Pinned from realestategander-site tools/idx-ingest.py, origin/main 0e81cdd5b2,
# plus the lease fields (sites, D-1009-77, 2026-10-09): TransactionType,
# LeasePrice and Leasetype kept, TransactionType off the denylist. From that
# change Gander imports the same tools/idx_fields.py (122 -> 125 kept,
# 20 -> 19 denylisted).
GANDER_SAFE_COUNT = 125
GANDER_SAFE_SHA256 = "017fbe73a4608e94dd0df3516279fa1d6986d5f8cea6cfeb1966ea04c424ef9a"
GANDER_NEVER_COUNT = 19
GANDER_NEVER_SHA256 = "be02fe1fc8cddd14ee7d128ca822f5ac44c2be86b257454b65da22dbb31fddfb"

# Names emit_sold_data reads that are not feed columns we keep: RESO-name and
# photo fallbacks in lookup chains, and keys of already-projected rows.
KNOWN_NON_FEED_READS = {
    "BathroomTotalInteger", "BedroomsTotal", "LivingArea",
    "LargePhotoURL", "MainPhotoURL", "PhotoURL", "PhotoURL_1", "PrimaryPhotoURL",
    "city", "dropdown_key", "region",
}

findings = []


def fail(msg):
    findings.append(msg)
    print(f"FAIL: {msg}")


def digest(names):
    return hashlib.sha256("\n".join(sorted(names)).encode("utf-8")).hexdigest()


def load_fields():
    spec = importlib.util.spec_from_file_location("idx_fields", TOOLS / "idx_fields.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def module_sets(path):
    """Top-level literal SAFE_FIELDS_ACTIVE / NEVER_PROJECT in a Python file."""
    out = {}
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], "id", None)
            if name in ("SAFE_FIELDS_ACTIVE", "NEVER_PROJECT"):
                try:
                    out[name] = set(ast.literal_eval(node.value))
                except ValueError:
                    out[name] = None
    return out, tree


def gander_candidates():
    env = os.environ.get("GANDER_IDX_INGEST")
    if env:
        yield Path(env)
    here = TOOLS.parent
    for base in [here.parent, here.parent.parent]:
        yield base / "realestategander-site" / "tools" / "idx-ingest.py"


f = load_fields()
safe, never = set(f.SAFE_FIELDS_ACTIVE), set(f.NEVER_PROJECT)

# 1. Pinned equality with Gander.
if len(safe) != GANDER_SAFE_COUNT or digest(safe) != GANDER_SAFE_SHA256:
    fail(f"SAFE_FIELDS_ACTIVE differs from Gander's pinned list "
         f"({len(safe)} names, sha {digest(safe)[:12]}; Gander {GANDER_SAFE_COUNT}, "
         f"{GANDER_SAFE_SHA256[:12]})")
if len(never) != GANDER_NEVER_COUNT or digest(never) != GANDER_NEVER_SHA256:
    fail(f"NEVER_PROJECT differs from Gander's pinned list "
         f"({len(never)} names, sha {digest(never)[:12]}; Gander {GANDER_NEVER_COUNT}, "
         f"{GANDER_NEVER_SHA256[:12]})")

compared = False
for cand in gander_candidates():
    if not cand.is_file():
        continue
    g_sets, _ = module_sets(cand)
    g_fields = cand.parent / "idx_fields.py"
    if not g_sets and g_fields.is_file():  # Gander moved to the shared file too
        g_sets, _ = module_sets(g_fields)
        cand = g_fields
    if not g_sets.get("SAFE_FIELDS_ACTIVE"):
        continue
    for name, ours in (("SAFE_FIELDS_ACTIVE", safe), ("NEVER_PROJECT", never)):
        theirs = g_sets.get(name) or set()
        if ours != theirs:
            fail(f"{name} differs from {cand}: only here {sorted(ours - theirs)}, "
                 f"only in Gander {sorted(theirs - ours)}")
    print(f"  compared directly against {cand}")
    compared = True
    break
if not compared:
    print("  no Gander checkout reachable; pinned digests used (set GANDER_IDX_INGEST to compare directly)")

# 2. idx-ingest.py uses the shared sets, with no local copy.
ingest_sets, ingest_tree = module_sets(TOOLS / "idx-ingest.py")
if ingest_sets:
    fail(f"tools/idx-ingest.py defines its own {sorted(ingest_sets)} -- edit tools/idx_fields.py instead")
imports = {
    a.name for n in ingest_tree.body if isinstance(n, ast.ImportFrom) and n.module == "idx_fields"
    for a in n.names
}
if not {"SAFE_FIELDS_ACTIVE", "NEVER_PROJECT"} <= imports:
    fail("tools/idx-ingest.py does not import SAFE_FIELDS_ACTIVE and NEVER_PROJECT from idx_fields")

# 3. The three fields that were denylisted here, and the lease fields (D-1009-77).
for name in ("PendingDate", "Possession", "SignYN", "TransactionType", "LeasePrice", "Leasetype"):
    if name not in safe or name in never:
        fail(f"{name} must be kept (in SAFE_FIELDS_ACTIVE, not in NEVER_PROJECT)")

# 4 + 5. The sold-data emitter.
gen_tree = ast.parse((TOOLS / "ddf-generate-pages.py").read_text(encoding="utf-8"))
emit = next((n for n in gen_tree.body
             if isinstance(n, ast.FunctionDef) and n.name == "emit_sold_data"), None)
if emit is None:
    fail("ddf-generate-pages.py has no emit_sold_data()")
else:
    reads = set()
    for n in ast.walk(emit):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get" and isinstance(n.func.value, ast.Name)
                and n.func.value.id in ("r", "pr") and n.args
                and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
            reads.add(n.args[0].value)
    missing = sorted(reads - safe - KNOWN_NON_FEED_READS)
    if missing:
        fail(f"emit_sold_data reads feed fields that idx-ingest never keeps: {missing}")
    if len(reads) < 50:
        fail(f"emit_sold_data: only {len(reads)} r.get()/pr.get() reads found -- the scan is blind")

    loop = next((n for n in ast.walk(emit)
                 if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == "r"
                 and isinstance(n.iter, ast.Name) and n.iter.id == "cache_rows"), None)
    first = loop.body[0] if loop else None
    ok = (isinstance(first, ast.Assign) and isinstance(first.value, ast.Call)
          and getattr(first.value.func, "id", "") == "hold_sold_display_fields"
          and getattr(first.targets[0], "id", "") == "r")
    if not ok:
        fail("the first statement of emit_sold_data's `for r in cache_rows:` loop must be "
             "`r = hold_sold_display_fields(r, SOLD_DISPLAY_HOLD_EXEMPT)`")

hold = set(f.SOLD_DISPLAY_HOLD)
if not hold <= safe:
    fail(f"SOLD_DISPLAY_HOLD names fields that are not kept: {sorted(hold - safe)}")
if "PendingDate" in hold:
    fail("PendingDate must not be held -- filling the Under contract row is the point")
sample = {"MLSNumber": "1", "Roof": "Metal", "PendingDate": "2026-09-01", "Vendor": "X"}
held = f.hold_sold_display_fields(sample)
if "Roof" in held or "Vendor" in held or held.get("PendingDate") != "2026-09-01" or "MLSNumber" not in held:
    fail(f"hold_sold_display_fields() wrong without exemption: {held}")
held = f.hold_sold_display_fields(sample, {"Vendor"})
if held.get("Vendor") != "X" or "Roof" in held:
    fail(f"hold_sold_display_fields() wrong with exemption: {held}")

# 6. The pin can fail.
if digest(safe | {"InjectedField"}) == GANDER_SAFE_SHA256 or digest(safe - {"Roof"}) == GANDER_SAFE_SHA256:
    fail("the digest pin cannot detect a one-name change")

if findings:
    print(f"\n{len(findings)} finding(s). Fix tools/idx_fields.py (shared, byte-identical in "
          f"Avalon and Goose Bay) to match Gander's tools/idx-ingest.py.")
    sys.exit(1)
print(f"PASS idx-fields parity: {len(safe)} kept / {len(never)} denylisted fields = Gander's; "
      f"{len(hold)} new fields held off the sold pages; PendingDate kept and shown.")
