#!/usr/bin/env python3
"""Apply the Lab West listings switch state to the generated tree (sites, D-1012-34).

Run by the gated hourly/nightly workflows right after the generators, with the state the `switch` job read from
vars.LABWEST_LISTINGS:

  preview   every generated page (listings/, property/) gets <meta name="robots" content="noindex,nofollow">,
            and the generated sitemaps are NOT registered in sitemap-index.xml. Mike can look, search engines cannot.
  on        the noindex tag is removed again and the generated sitemaps are registered in sitemap-index.xml.
  off       nothing is generated, so there is nothing to do: exit 0 and touch nothing.
Both preview and on also make sure the sold-gate rewrites are at the top of _redirects (sold JSON -> sign-in function).

Idempotent. Never touches a hand-written page. Fails loud on an unknown state (always-on #16).
Usage: python3 tools/labwest-listings-state.py <off|preview|on> [--root DIR]
"""
import argparse
import re
import sys
from pathlib import Path

NOINDEX = '<meta name="robots" content="noindex,nofollow">'
GENERATED_DIRS = ("listings", "property")
GENERATED_SITEMAPS = ("sitemap-listings.xml", "sitemap-property.xml")
ORIGIN = "https://labwestrealty.com"


def generated_pages(root: Path):
    for d in GENERATED_DIRS:
        base = root / d
        if base.is_dir():
            yield from sorted(base.rglob("*.html"))


def set_noindex(path: Path, want: bool) -> bool:
    text = path.read_text(encoding="utf-8")
    has = NOINDEX in text
    if want and not has:
        if "<head>" in text:
            text = text.replace("<head>", "<head>\n" + NOINDEX, 1)
        elif re.search(r"<head[^>]*>", text):
            text = re.sub(r"(<head[^>]*>)", r"\1\n" + NOINDEX, text, count=1)
        else:
            return False
    elif not want and has:
        text = text.replace("\n" + NOINDEX, "").replace(NOINDEX, "")
    else:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def set_sitemaps(root: Path, want: bool) -> int:
    idx = root / "sitemap-index.xml"
    text = idx.read_text(encoding="utf-8")
    changed = 0
    for name in GENERATED_SITEMAPS:
        entry = f"  <sitemap>\n    <loc>{ORIGIN}/{name}</loc>\n  </sitemap>\n"
        present = f"<loc>{ORIGIN}/{name}</loc>" in text
        if want and present is False and (root / name).exists():
            text = text.replace("</sitemapindex>", entry + "</sitemapindex>")
            changed += 1
        elif not want and present:
            text = re.sub(r"[ \t]*<sitemap>\s*<loc>" + re.escape(f"{ORIGIN}/{name}") + r"</loc>\s*</sitemap>\n?", "", text)
            changed += 1
    if changed:
        idx.write_text(text, encoding="utf-8")
    return changed


REDIRECT_BEGIN = "# BEGIN lab-west-sold-gate (tools/labwest-listings-state.py; do not edit by hand)"
REDIRECT_END = "# END lab-west-sold-gate"
REDIRECT_RULES = """/listings/sold/data.json            /.netlify/functions/sold-data?f=data.json  200!
/listings/sold/detail/:shard        /.netlify/functions/sold-data?shard=:shard  200!
/listings/sold/:town/data.json      /.netlify/functions/sold-data?town=:town  200!"""


def set_sold_redirects(root: Path, want: bool) -> int:
    """Forced (200!) rewrites that send the sold JSON URLs to the sign-in function, so the static copies are never served.
    They sit at the top of _redirects (first match wins, before the generator's 301s)."""
    path = root / "_redirects"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    block = f"{REDIRECT_BEGIN}\n{REDIRECT_RULES}\n{REDIRECT_END}\n"
    has = REDIRECT_BEGIN in text
    if want and not has:
        path.write_text(block + "\n" + text, encoding="utf-8")
        return 1
    if not want and has:
        a = text.index(REDIRECT_BEGIN)
        b = text.index(REDIRECT_END) + len(REDIRECT_END)
        text = (text[:a] + text[b:].lstrip("\n")).lstrip("\n")
        path.write_text(text, encoding="utf-8")
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("state")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    a = ap.parse_args(argv)
    if a.state not in ("off", "preview", "on"):
        print(f"[state] unknown state {a.state!r}; expected off|preview|on", file=sys.stderr)
        return 2
    root = Path(a.root)
    if a.state == "off":
        print("[state] off: nothing generated, nothing changed")
        return 0
    pages = list(generated_pages(root))
    n = sum(1 for p in pages if set_noindex(p, a.state == "preview"))
    s = set_sitemaps(root, a.state == "on")
    r = set_sold_redirects(root, True)
    print(f"[state] {a.state}: {len(pages)} generated page(s), {n} changed; sitemap-index entries changed: {s}; sold redirects added: {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
