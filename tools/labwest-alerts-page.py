#!/usr/bin/env python3
"""Install (or remove) the Lab West Listing Text Alerts page at pages/text-alerts.html (sites, D-1012-34, component 8).

The page is a template under tools/, so no served page exists while the switch is off. The gated rebuild runs this before the
generator. It writes the page only when tools/labwest-alerts.json says backend_ready is true (Gander's sms-subscribe and
client-alerts accept the labwest site and origin); otherwise it removes any copy, so the site never offers a sign-up whose
backend would refuse it (always-on #17).
Usage: python3 tools/labwest-alerts-page.py [--root DIR]
"""
import argparse
import json
import sys
from pathlib import Path


def alerts_ready(root: Path) -> bool:
    try:
        return json.loads((root / "tools" / "labwest-alerts.json").read_text(encoding="utf-8")).get("backend_ready") is True
    except Exception:
        return False  # fail safe: unreadable = not ready


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    a = ap.parse_args(argv)
    root = Path(a.root)
    dest = root / "pages" / "text-alerts.html"
    if not alerts_ready(root):
        if dest.exists():
            dest.unlink()
        print("[alerts-page] backend_ready is false: no text-alerts page, no alerts markup")
        return 0
    src = root / "tools" / "text-alerts.template.html"
    text = src.read_text(encoding="utf-8")
    if "data-lta-inline" not in text:
        print("[alerts-page] template lacks the signup widget", file=sys.stderr)
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    print(f"[alerts-page] wrote {dest.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
