#!/usr/bin/env python3
"""
Turner Realty — Agent Roster Loader
===================================

The single RUNTIME source for Turner Realty agent registries. Reads the canonical
tools/agent_roster.json and reconstructs the four registries the generator +
aggregator consume — replacing the hardcoded dict literals that used to live (and
drift) in ddf-generate-pages.py (Convention #148 / #174 canonical-pass Phase B).

  reconstruct()    — the canonical builder (agent_roster_check.py imports it).
  load_registries() — what the generator/aggregator call:

      TURNER_AGENT_CARD, _TURNER_AGENT_ALIASES, TEAM_BY_AGENT, AGENT_PROFILE_SLUG = load_registries()

Phase A's agent_roster_check.py proved reconstruct(roster) reproduces every live
generator literal byte-for-byte, so this repoint leaves generator output unchanged.
"""

import json
import re
from pathlib import Path

ROSTER_PATH = Path(__file__).resolve().parent / "agent_roster.json"


def _digits(s):
    return re.sub(r"\D", "", s or "")


def reconstruct(agents):
    """Rebuild the four registries purely from the roster agent list."""
    card, aliases, team_by, slug_by = {}, {}, {}, {}
    for a in agents:
        card[a["name"]] = {
            "slug": a["slug"],
            "photo": a["photo"],
            "phone": _digits(a["phone"]),   # the card stores digits-only
            "email": a["email"],
            "title": a["card_title"],
            "team": a["team"],
        }
        for variant in a.get("aliases", []):
            aliases[variant] = a["name"]
        if a.get("in_widget"):
            team_by[a["widget_name"]] = a["team_widget"]
            slug_by[a["widget_name"]] = a["slug"]
    return card, aliases, team_by, slug_by


def load_roster(path=None):
    p = Path(path) if path else ROSTER_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def load_registries(path=None):
    """(TURNER_AGENT_CARD, _TURNER_AGENT_ALIASES, TEAM_BY_AGENT, AGENT_PROFILE_SLUG)."""
    return reconstruct(load_roster(path)["agents"])


def widget_display_maps(agents):
    """(agent_display_by_widget, team_display_by_widget).

    Maps the per-agent-widget MATCH/JOIN keys (widget_name + team_widget, which must
    stay aligned to the NLAR feed name + the aggregator by_team cache) back to the
    friendly canonical DISPLAY names (name + team). Lets the rendered widget show
    "Matt Wheaton" / "The Dynamic Duo" while every lookup, join and sold-filter slug
    stays on the keys. Convention #74: callers .get(key, key) so an unmapped key
    falls back to the matched name (current behaviour).
    """
    agent_disp, team_disp = {}, {}
    for a in agents:
        if a.get("in_widget"):
            agent_disp[a["widget_name"]] = a["name"]
            team_disp[a["team_widget"]] = a["team"]
    return agent_disp, team_disp


def load_widget_display_maps(path=None):
    """(agent_display_by_widget, team_display_by_widget) from the canonical roster."""
    return widget_display_maps(load_roster(path)["agents"])
