"""_fleet_config.py — per-section config loader for the fleet site generators.

Tier-1 fleet-canonical (synced byte-identical to <site>/tools/_fleet_config.py by
tools/fleet-sync.py). Convergence Inc 3 (2026-06-23): the generators carried per-site
*scalar* literals (site_origin, r2_site_slug, …) hardcoded in their CONFIG block — the
same value-drift that the 3-way generator divergence keeps re-growing. This loader reads
the per-repo tools/_fleet_config.json (per-site DATA, NOT synced — exactly like
tools/agent_roster.json) so each generator sources those scalars from one place. The
config VALUES are unchanged from the literals they replace, so generator output is
byte-identical (Convention #87 no-op gate). Pattern mirrors agent_roster_loader.py.

This is the substrate the later increments build on: it's what lets per-site values
(R2_SITE_SLUG → _viewpoint_photos; footer/nav templates) move out of the generator
bodies so the bodies themselves can converge to one shared form.

CI-safe: the JSON lives in the same tools/ dir as the generator, so a GitHub Actions
checkout of just the site repo finds it. The workspace fleet/config/<site>.json is a
management artifact invisible to CI — DON'T point the generator at it. Seed the per-repo
JSON from the workspace fleet/config so the management layer and the runtime artifact agree.

NEVER hand-edit per-site copies; edit fleet/canonical/tools/_fleet_config.py + fleet-sync.
The per-site _fleet_config.json IS hand-maintained per repo (it's DATA, like agent_roster.json).
"""
from __future__ import annotations
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "_fleet_config.json"


def load_site_config(path=None) -> dict:
    """Return the per-site config dict for this repo.

    Keys (Inc 3): site_key, site_origin, r2_site_slug. Later increments add more
    (gtag_id, region, office NAP, postal prefixes) as each value-family migrates.
    Strict by design — a missing config file is a build error, not a silent
    fallback (it ships in the same commit as the generator change, so it's always
    present; mirrors agent_roster_loader.py's strict read).
    """
    p = Path(path) if path else CONFIG_PATH
    return json.loads(p.read_text(encoding="utf-8"))
