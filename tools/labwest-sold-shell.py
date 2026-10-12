#!/usr/bin/env python3
"""Install the Lab West sold-listings shell at listings/sold/index.html (sites, D-1012-34).

The shell is a template under tools/ (not under listings/), so no served page exists while the switch is off. The gated
rebuild runs this right before ddf-generate-pages.py, which then fills the SOLD_PUBLIC_RECORDS block and derives the
per-town sold pages from it. Always overwrites: the generator rewrites the block on every run, and a hand edit of the
generated page would be lost anyway.
Usage: python3 tools/labwest-sold-shell.py [--root DIR]
"""
import argparse
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    a = ap.parse_args(argv)
    root = Path(a.root)
    src = root / "tools" / "listings-sold-index.template.html"
    if not src.exists():
        print(f"[sold-shell] template missing: {src}", file=sys.stderr)
        return 1
    text = src.read_text(encoding="utf-8")
    for marker in ("<!-- SOLD_PUBLIC_RECORDS:BEGIN -->", "<!-- SOLD_PUBLIC_RECORDS:END -->", "/js/sold-listings.js"):
        if marker not in text:
            print(f"[sold-shell] template lacks {marker!r}", file=sys.stderr)
            return 1
    # The sold-alerts opt-in banner posts to Gander and files saved searches by site; until tools/labwest-alerts.json says the
    # backend knows labwest, the shell carries neither script (always-on #17).
    import json as _json, re as _re
    try:
        ready = _json.loads((root / "tools" / "labwest-alerts.json").read_text(encoding="utf-8")).get("backend_ready") is True
    except Exception:
        ready = False
    if not ready:
        text = _re.sub(r'<script src="/js/(?:saved-search|sold-alerts-optin)\.js[^>]*></script>\n?', "", text)
    dest = root / "listings" / "sold" / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    print(f"[sold-shell] wrote {dest.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
