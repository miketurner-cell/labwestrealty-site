"""_search_index.py -- builds listings/search-index.json (fleet canonical, 2026-09-25; v2 2026-10-08).

The suggestions index behind the header search's typeahead on every page
that has NOT loaded the full listings feed (homepage, community pages,
listing detail pages, market-stats pages). js/site-search.js fetches it on
the first focus of a search box -- never at page load.

DATA CONTRACT: _research/search_index_contract_2026-10-08.md (workspace root;
sites owns it, redesign builds the UI; Mike D-1008-86). Any shape change bumps
"v" and changes the contract first.

Shape (v2 = v1 + p/i/ss), lists sorted so the file is byte-stable when the
data has not changed (keeps hourly commits quiet):

    { "v": 2, "generated_at", "site", "action": "/listings/",
      "photo_base": "https://.../{mls}/001.jpg",          # derived, never hardcoded
      "cities":  [[label, active, sold], ...],
      "areas":   [[label, active, sold], ...],            # [] until a feed carries subdistrict
      "streets": [[street name, city label, active], ...],
      "postal":  [[FSA, active], ...],
      "l":       [[mls, street, city, price, url, photo_override|null], ...],
      "sold_mls": "1290000,1290001,...",
      "p":  [[title, url, type, keywords], ...],          # pages from sitemap.xml
      "i":  {normalized phrase: [url, label], ...},       # "Go to" intents
      "ss": [[street, town, count, last_sold_date, url], ...],   # sold streets, NO price
      "trim": {"ss": n} }                                 # only when the size guard trimmed

VOW (CLAUDE.md, Mike 2026-05-18; D-1008-86 "Addresses and dates public, prices
after registering"): "ss" reads ONLY street/city/city_slug/sold_date from each
sold row (whitelist). No sold price, list price or house number ever reaches it.

One row adapter covers both generator row shapes: the Avalon/Goose Bay
projected rows (city_raw, city_slug, list_price, url_path, photos[],
postal_code, subdistrict) and Gander's rows (city, idx_postal_code,
idx_subdistrict, price, url; or city_slug + slug). Everything is fail-safe:
a missing field drops out of the index, it never raises (Conv #74).

CLI:
    python3 tools/_search_index.py --self-test
    python3 tools/_search_index.py --emit <site_root> [--site KEY]   # from committed data files
    python3 tools/_search_index.py --check <site_root>               # contract + size guard (CI)
"""
from __future__ import annotations

import gzip
import html
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

INDEX_VERSION = 2
INDEX_REL = Path("listings") / "search-index.json"
MAX_GZ_BYTES = 150_000

PAGE_TYPES = ("community", "stats", "tool", "guide", "agent", "service", "office", "relocation", "sold-archive")

_HOUSE_RE = re.compile(
    r"^\s*(?:(?:unit|apt|suite)\s*\S+\s*[-,]?\s*)?#?(\d+[a-z]?)(?:\s*-\s*\d+[a-z]?)?\s+(.*)$",
    re.IGNORECASE,
)
_SUBDISTRICT_CODE_RE = re.compile(r"^\s*[A-Z]{1,4}\d{0,3}\s*[-–:]\s*")
_PHOTO_RE = re.compile(r"^(.*)/(\d+)/(\d{3})\.(jpe?g|png|webp)$", re.IGNORECASE)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize(s) -> str:
    """Python twin of site-search.js normalize() (lowercase, strip accents +
    apostrophes, punctuation -> space). Used only as a grouping key here;
    the browser re-canonicalizes every label on load."""
    import unicodedata
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"['‘’`´]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm_subdistrict(v):
    """'SJ01 - East' -> 'East'; '' / None -> None."""
    s = str(v or "").strip()
    s = _SUBDISTRICT_CODE_RE.sub("", s).strip()
    return s or None


def _title(s: str) -> str:
    # Capital only after start/space/hyphen/slash/bracket -- never after an
    # apostrophe ("St. John's", not "St. John'S").
    return re.sub(r"(^|[\s\-/(])([a-z])", lambda m: m.group(1) + m.group(2).upper(), s.lower())


def _pretty(label: str) -> str:
    """Twin of site-search.js prettyLabel(): backticks -> apostrophes, an
    ALL-CAPS label or ALL-CAPS 3+ letter word -> Title case."""
    label = re.sub(r"[`´]", "’", str(label or "").strip())
    if label and label == label.upper() and re.search(r"[A-Z]", label):
        return _title(label)
    return re.sub(r"\b[A-Z][A-Z’']{2,}\b", lambda m: _title(m.group(0)), label)


SOLD_ONLY_MIN = 3
_PROVINCE_RE = re.compile(r"[\s,]+(nl|n\.l\.|nfld|newfoundland(\s+(and|&)\s+labrador)?)\.?\s*$", re.IGNORECASE)


def _strip_province(city: str) -> str:
    """'Mount Pearl, NL' -> 'Mount Pearl' (twin of site-search.js cityLabel)."""
    return _PROVINCE_RE.sub("", str(city or "")).strip()


def _within1(a: str, b: str) -> bool:
    """Damerau-Levenshtein distance <= 1 (twin of site-search.js within1)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    i = 0
    while i < la and i < lb and a[i] == b[i]:
        i += 1
    if i == la or i == lb:
        return True
    if la == lb:
        if a[i + 1:] == b[i + 1:]:
            return True
        return a[i] == b[i + 1] and a[i + 1] == b[i] and a[i + 2:] == b[i + 2:]
    return a[i + 1:] == b[i:] if la > lb else b[i + 1:] == a[i:]


def _get(r: dict, *keys):
    for k in keys:
        v = r.get(k)
        if v not in (None, "", []):
            return v
    return None


def _first_photo(r: dict):
    p = _get(r, "photo")
    if isinstance(p, str):
        return p
    photos = r.get("photos") or []
    if photos:
        # Same preference as the generators' card picker: an explicit
        # preferred/cover flag wins, else the first in order.
        for ph in photos:
            if isinstance(ph, dict) and (ph.get("preferred") or ph.get("is_preferred")):
                return ph.get("url")
        p0 = photos[0]
        return p0 if isinstance(p0, str) else (p0 or {}).get("url")
    return None


def _row_url(r: dict) -> str:
    u = _get(r, "url", "url_path")
    if u:
        return str(u)
    # Gander/Goose Bay generator rows carry no url: the generators write
    # <site_root>/listings/<city_slug>/<slug>.html.
    if r.get("city_slug") and r.get("slug"):
        return f"/listings/{r['city_slug']}/{r['slug']}.html"
    return ""


def _split_street(street: str):
    m = _HOUSE_RE.match(street or "")
    return (m.group(1).lower(), m.group(2).strip()) if m else ("", (street or "").strip())


# ── street-name cleaner (2026-10-09, sites) ──────────────────────────────
# MLS street fields carry junk that the house-number split above leaves in
# the street NAME ("22 & 25 Across The Doors Road" -> "& 25 Across The Doors
# Road", "180 (lot 127-147 ) Main Road", "1136-lot 1 Thorburn Road",
# "4 &amp; 6 Foote's", "Lot # 3 Main", "# 115183 Cache River"), and those
# names became search suggestions. clean_street() html-unescapes, then
# strips civic-number lists, "&"/"and" joins, lot/parcel/unit/# prefixes and
# tails, and parenthesised lot ranges. A name the cleaner had to repair is
# kept when it ends in a street type (Road, Lane, ...) or what is left is
# plain words (each >= 2 letters, >= 4 letters in all: "Pasadena", "Cache
# River", "Second Pond"); a leftover code ("P4", "P & R") is DROPPED, never
# guessed. A repaired spelling joins a group only when a clean record in the
# same town has it (so "Elliott's"/"Elliotts" merge only through a clean
# twin); otherwise it keeps its own spelling.

_STREET_TYPE_RE = re.compile(
    r"\b(?:road|rd|street|st|drive|dr|avenue|ave|lane|ln|crescent|cres|place|pl|court|ct|way|"
    r"boulevard|blvd|highway|hwy|path|line|terrace|close|loop|hill|heights|trail|row|square|"
    r"circle|estates|landing|gardens|park|parkway|bypass|extension|walk|mews)\.?"
    r"(?:\s+(?:east|west|north|south|extension))?$"
    r"|^(?:route|highway|hwy)\s+[a-z]*-?\d+[a-z]?$",
    re.IGNORECASE,
)
_NUM_TOK = r"\d+(?:\.\d+)?[a-z]?(?:\s*/\s*\d+[a-z]?)?(?=[\s,&/\-]|$)"
_LOT_ID = r"(?:[a-z]?-?\d+[a-z]?|[a-z](?![a-z'’]))"
_CIVIC_LIST_RE = re.compile(rf"^{_NUM_TOK}(?:\s*(?:[-,&/]|\band\b|\bto\b)\s*(?:{_NUM_TOK}|[a-z](?=\s)))*\s*", re.I)
_LOT_PREFIX_RE = re.compile(
    rf"^(?:lots?|parcels?|site|box|civic(?:\s+no\.?)?|rr)\s*(?:no\.?|#)?\s*{_LOT_ID}"
    rf"(?:\s*(?:[-&,/]|\band\b)\s*{_LOT_ID})*(?:\s|$)", re.I)
_LEAD_JUNK_RES = (
    re.compile(r"^[\s.,;:&\-–\"“”]+"),                                # stray punctuation / leading "&"
    re.compile(r"^(?:and|plus)\s+(?=[\d#])", re.I),                   # "and 9 Harbour"
    re.compile(r"^#\s*[a-z]?\d+[a-z]?\s*", re.I),                     # "# 115183", "#J19"
    re.compile(r"^[\"“]?[a-z][\"”]\s+", re.I),                         # '"B" Main Street East'
    re.compile(r"^[a-z]\s*(?:&|\band\b)\s*[a-z]\s+", re.I),                 # "A and B Wights", "A&B High"
    re.compile(r"^(?:unit|apt|suite)\s*\S+\s*[-,]?\s*", re.I),         # "Unit 4 - "
    re.compile(r"^(?!no\b)[a-z]{1,2}-?\s?\d+[a-z]?\s+(?=[a-z])", re.I),  # lot codes "A10 ", "H 27 ", "L21 "
    _LOT_PREFIX_RE,
    _CIVIC_LIST_RE,
)
_PAREN_LOT_RE = re.compile(r"\(\s*(?:(?:lots?|parcels?|civic|unit)\b[^)]*|[\d\s,&/\-]+)\)", re.I)
_TAIL_RES = (
    re.compile(r"\s+lots?\s*(?:no\.?|#)?\s*\d+[a-z]?\b", re.I),        # "Keeley lot 1 Lane", "Route 350 Lot # 37427 ..."
    re.compile(r"\s+(?:unit|apt|suite)\b.*$", re.I),                    # "Curtis Unit 106"
    re.compile(r"\s*#.*$"),                                             # "Main Road # Parcel I", "Lanark #2"
)


def clean_street(street) -> tuple:
    """-> (name, repaired). name is the clean street name ("" = nothing
    usable); repaired is True when the result differs from the plain
    house-number split (i.e. the raw field carried junk)."""
    raw = str(street or "")
    _num, plain = _split_street(raw)
    s = html.unescape(html.unescape(raw)).replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = _PAREN_LOT_RE.sub(" ", s)
    for _ in range(12):
        before = s
        for rx in _LEAD_JUNK_RES:
            s = rx.sub("", s, count=1).strip()
        if s == before:
            break
    for rx in _TAIL_RES:
        s = rx.sub("", s).strip() if rx.search(s) and rx.sub("", s).strip() else s
    s = re.sub(r"\(\s*\)", " ", s)
    s = re.sub(r"^\(\s*([^()]*?)\s*\)\s*", r"\1 ", s)                 # "(Old) Southern Shore Highway"
    s = re.sub(r"\s+", " ", s).strip(" ,;:-–")
    if not re.search(r"[a-z]{2}", s, re.I):
        s = ""
    return s, normalize(s) != normalize(plain)


def _has_street_type(name: str) -> bool:
    return bool(_STREET_TYPE_RE.search(str(name or "").strip()))


_WORD_RE = re.compile(r"^[a-z][a-z'’.\-]*$", re.I)


def _is_wordlike(name: str) -> bool:
    """Plain alphabetic words: each token >= 2 letters, >= 4 letters in all
    (brackets/commas around a token ignored). "P4", "P & R" -> False."""
    toks = [t.strip("(),") for t in str(name or "").split()]
    toks = [t for t in toks if t]
    if not toks or not all(_WORD_RE.match(t) and len(re.findall(r"[a-z]", t, re.I)) >= 2 for t in toks):
        return False
    return sum(len(re.findall(r"[a-z]", t, re.I)) for t in toks) >= 4


def _resolve_streets(clean, repaired: dict, dropped: list, add):
    """Fold repaired entries in. A repaired name is kept when it has a street
    type or is plain words (_is_wordlike); else its raw strings go to
    `dropped`. It joins an existing group only when a clean record made that
    key (`clean` = the clean keys); otherwise it is grouped by its exact
    spelling. `add(key, rec)` folds one record into its group."""
    for key, recs in repaired.items():
        for rec in recs:
            name = rec[0]
            if not (_has_street_type(name) or _is_wordlike(name)):
                dropped.append(rec[-1])
            elif key in clean:
                add(key, rec)
            else:
                add((key[0] + "\x00" + name.lower(), key[1]), rec)


def _street_stats(stats, label, raw_keys, kept, dropped):
    if stats is not None:
        stats[label] = {"raw": len(raw_keys), "clean": kept,
                        "dropped": sorted(set(dropped), key=lambda x: (x[1].lower(), x[0].lower()))}


class _Label:
    """Picks the display label for a grouping key: the most frequent
    spelling that is not ALL CAPS (ALL CAPS only when nothing else exists)."""

    def __init__(self):
        self.c = Counter()

    def add(self, s):
        if s:
            self.c[str(s).strip()] += 1

    def best(self):
        if not self.c:
            return ""
        ranked = sorted(self.c.items(), key=lambda kv: (kv[0] == kv[0].upper(), -kv[1], kv[0]))
        return _pretty(ranked[0][0])


# ── v2: pages (p) ─────────────────────────────────────────────────────────

_EXCLUDE_SLUGS = {"listing-detail", "privacy-policy", "terms-of-use", "accessibility", "offline", "404"}
_TYPE_SYNONYMS = {
    "community": "community homes for sale living neighbourhood area",
    "stats": "market stats statistics prices data",
    "tool": "tool",
    "guide": "guide",
    "agent": "agent realtor",
    "service": "service",
    "office": "",
    "relocation": "relocation relocate moving",
    "sold-archive": "sold prices recently sold",
}
_SLUG_SYNONYMS = {
    "mortgage-calculator": "payment calculator",
    "home-value": "value worth evaluation appraisal estimate",
    "property-lookup": "lookup address",
    "text-alerts": "alerts listing text alerts notify",
    "get-the-app": "app download",
    "contact": "contact phone email office address",
    "about": "about us company brokerage",
    "join-our-team": "careers join jobs",
    "become-a-realtor": "careers licence",
    "sell-your-home": "sell selling list",
}
# Product names on every consumer surface (CLAUDE.md, Mike 2026-06-11).
_TITLE_OVERRIDE = {"text-alerts": "Listing Text Alerts"}
_TOOL_RE = re.compile(r"calculator|^home-value$|^property-lookup$|^text-alerts$|^get-the-app$")
_RELOC_RE = re.compile(r"relocat|^9-wing|^5-wing|^posted-to|^newcomer")
_OFFICE = {"about", "contact", "team", "awards", "testimonials", "join-our-team", "become-a-realtor",
           "agent-hub", "shelter-foundation", "masquerade-ball"}
_OFFICE_RE = re.compile(r"^first-year-realtor")
_SERVICE = {"sell-your-home", "services", "buy-a-home", "buyer-hub", "seller-hub", "first-time-buyers",
            "photography", "iguide", "video", "videos", "property-management", "tenant-placement",
            "home-inspections", "commercial", "investorsedge"}
_SERVICE_RE = re.compile(r"^sell-my-house-")
_STATS_RE = re.compile(r"market-stats|market-insights|housing-market-data")
_COMMUNITY_RE = re.compile(r"^community-guide-|^communities$|neighbourhoods")


def _slugify(s) -> str:
    return normalize(s).replace(" ", "-")


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _yml_fields(path) -> dict:
    """slug/label from a flat config yml without a YAML dependency."""
    out = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except Exception:
        return out
    for key in ("slug", "label"):
        m = re.search(rf"^{key}:\s*[\"']?([^\"'\n#]+?)[\"']?\s*(?:#.*)?$", text, re.MULTILINE)
        if m:
            out[key] = m.group(1).strip()
    out.setdefault("slug", Path(path).stem)
    return out


def _config_dir(root: Path, name: str):
    d = root / "tools" / name
    return sorted(d.glob("*.yml")) if d.is_dir() else []


def _sitemap_paths(root: Path):
    try:
        text = (root / "sitemap.xml").read_text(encoding="utf-8")
    except Exception:
        return []
    out, seen = [], set()
    for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text):
        path = re.sub(r"^https?://[^/]+", "", html.unescape(loc)) or "/"
        path = path.split("#")[0].split("?")[0]
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _page_file(root: Path, path: str):
    rel = path.lstrip("/")
    cands = [rel + "index.html"] if (rel == "" or rel.endswith("/")) else (
        [rel] if rel.endswith(".html") else [rel + ".html", rel + "/index.html"])
    for c in cands:
        f = root / c
        if f.is_file():
            return f
    return None


def _page_title(f):
    if not f:
        return ""
    try:
        head = f.read_text(encoding="utf-8", errors="replace")[:200_000]
    except Exception:
        return ""
    m = re.search(r"<title[^>]*>(.*?)</title>", head, re.IGNORECASE | re.DOTALL)
    if not m:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", head, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    t = re.sub(r"<[^>]+>", " ", m.group(1))
    t = re.sub(r"\s+", " ", html.unescape(t)).strip()
    for sep in (" | ", " — "):
        if sep in t:
            t = t.split(sep)[0].strip()
    return t


def _slug_of(path: str) -> str:
    p = path.rstrip("/")
    p = p.rsplit("/", 1)[-1]
    return re.sub(r"\.html$", "", p)


def _site_region(root: Path, site_key: str) -> dict:
    d = _read_json(root / "tools" / "regions.json") or {}
    regs = d.get("regions") or {}
    if isinstance(regs, dict):
        return regs.get(site_key) or {}
    for r in regs if isinstance(regs, list) else []:
        if isinstance(r, dict) and (r.get("site_key") == site_key or r.get("key") == site_key):
            return r
    return {}


def _roster(root: Path) -> dict:
    d = _read_json(root / "tools" / "agent_roster.json") or {}
    agents = d.get("agents") if isinstance(d, dict) else d
    out = {}
    for a in agents or []:
        if isinstance(a, dict) and a.get("slug") and a.get("name"):
            out[str(a["slug"])] = a
    return out


def _keywords(title: str, *parts) -> str:
    have = set(normalize(title).split())
    out = []
    for part in parts:
        for tok in normalize(part).split():
            if tok not in have and tok not in out:
                out.append(tok)
    return " ".join(out)


def build_pages(site_root, site_key: str):
    """-> (p rows, context dict used by build_intents). Never raises on a
    missing source: that source simply contributes nothing."""
    root = Path(site_root)
    roster = _roster(root)
    region = _site_region(root, site_key)
    stats_cfg = {f["slug"]: f for f in map(_yml_fields, _config_dir(root, "market-stats-config"))}
    comm_cfg = {f["slug"]: f for f in map(_yml_fields, _config_dir(root, "community-config") +
                                          _config_dir(root, "region-config"))}
    towns = {_slugify(t): t for t in (region.get("towns") or []) if isinstance(t, str)}

    rows = []
    missing = 0
    for path in _sitemap_paths(root):
        if path == "/":
            continue
        slug = _slug_of(path)
        if slug in _EXCLUDE_SLUGS:
            continue
        f = _page_file(root, path)
        if f is None:
            missing += 1
        title = _page_title(f)
        extra = ""
        if slug in roster and path.startswith("/pages/"):
            a = roster[slug]
            ptype, title = "agent", str(a["name"])
            extra = " ".join([str(a.get("first_name") or ""), " ".join(map(str, a.get("aliases") or []))])
        elif path.startswith("/listings/sold/") or slug.endswith("-sold"):
            ptype = "sold-archive"
        elif slug in stats_cfg or _STATS_RE.search(slug):
            ptype = "stats"
            extra = (stats_cfg.get(slug) or {}).get("label", "")
        elif slug in comm_cfg or slug in towns or _COMMUNITY_RE.search(slug):
            ptype = "community"
            extra = (comm_cfg.get(slug) or {}).get("label", "") or towns.get(slug, "")
        elif _TOOL_RE.search(slug):
            ptype = "tool"
        elif _RELOC_RE.search(slug):
            ptype = "relocation"
        elif slug in _OFFICE or _OFFICE_RE.search(slug):
            ptype = "office"
        elif slug in _SERVICE or _SERVICE_RE.search(slug):
            ptype = "service"
        else:
            ptype = "guide"
        title = _TITLE_OVERRIDE.get(slug, title)
        if not title:
            title = (comm_cfg.get(slug) or stats_cfg.get(slug) or {}).get("label") or _title(slug.replace("-", " "))
        kw = _keywords(title, slug.replace("-", " "), extra, _SLUG_SYNONYMS.get(slug, ""), _TYPE_SYNONYMS[ptype])
        rows.append([title, path, ptype, kw])

    order = {t: n for n, t in enumerate(PAGE_TYPES)}
    rows.sort(key=lambda r: (order[r[2]], r[0].lower(), r[1]))
    ctx = {"region": region, "roster": roster, "stats_cfg": stats_cfg, "missing_files": missing}
    return rows, ctx


# ── v2: intents (i) ───────────────────────────────────────────────────────

def _tel(phone: str) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) == 10:
        digits = "1" + digits
    return f"tel:+{digits}" if len(digits) == 11 else ""


def _fmt_phone(phone: str) -> str:
    d = re.sub(r"\D", "", str(phone or ""))[-10:]
    return f"{d[:3]}-{d[3:6]}-{d[6:]}" if len(d) == 10 else str(phone or "")


def build_intents(pages, ctx: dict, place_labels: dict) -> dict:
    urls = {r[1] for r in pages}
    by_slug = {}
    for r in pages:
        by_slug.setdefault(_slug_of(r[1]), r[1])
    region = ctx.get("region") or {}
    routes = region.get("routes") or {}
    out: dict = {}

    def add(keys, url, label):
        if not url or not label:
            return
        if not (url in urls or url == "/listings/sold/" or url.startswith("tel:")):
            return
        for k in keys:
            k = normalize(k)
            if k and k not in out:
                out[k] = [url, label]

    def page(*slugs):
        for s in slugs:
            if s in by_slug:
                return by_slug[s]
        return ""

    add(["value", "home value", "worth", "home worth", "whats my home worth", "what is my home worth",
         "evaluation", "home evaluation", "appraisal"], page("home-value"), "Get my home's value")
    add(["sell", "selling", "sell my house", "sell my home", "list my home"],
        routes.get("sell") if routes.get("sell") in urls else page("sell-your-home"), "Sell your home")
    add(["mortgage", "mortgage calculator", "calculator", "payment calculator", "payments"],
        page("mortgage-calculator"), "Mortgage calculator")
    add(["closing costs", "closing cost calculator"],
        page("closing-cost-calculator-nl", "nl-closing-costs-guide"), "Closing costs")
    add(["alerts", "listing alerts", "text alerts", "listing text alerts", "new listing alerts", "notify me"],
        page("text-alerts"), "Listing Text Alerts")
    add(["contact", "contact us", "email", "office", "address"], page("contact"), "Contact us")
    phone = (region.get("office") or {}).get("phone")
    if _tel(phone):
        add(["call", "phone", "phone number", "talk to someone"], _tel(phone), f"Call {_fmt_phone(phone)}")
    add(["market", "market stats", "stats", "statistics", "housing market", "market report"],
        routes.get("market") if routes.get("market") in urls else page("market-insights"), "Market stats")
    add(["sold", "sold prices", "recently sold", "sold homes"], "/listings/sold/", "Sold prices")
    for r in pages:
        if r[2] == "sold-archive" and r[1].startswith("/listings/sold/") and r[1] != "/listings/sold/":
            slug = _slug_of(r[1])
            m = re.match(r"^Sold Listings (.+?)(?:,\s*NL)?$", r[0])
            town = (place_labels.get(normalize(slug.replace("-", " "))) or (m.group(1) if m else "")
                    or _title(slug.replace("-", " ")))
            add([f"sold in {town}", f"{town} sold", f"{town} sold prices"], r[1], f"Sold in {town}")
    for slug, cfg in sorted((ctx.get("stats_cfg") or {}).items()):
        lab = cfg.get("label")
        if lab and slug in by_slug:
            add([f"{lab} market", f"{lab} market stats", f"{lab} stats"], by_slug[slug], f"{lab} market stats")
    for slug, a in sorted((ctx.get("roster") or {}).items()):
        url = f"/pages/{slug}.html"
        if url in urls:
            add([a["name"], slug.replace("-", " ")] + [str(x) for x in (a.get("aliases") or [])], url, str(a["name"]))
    add(["relocation", "relocate", "moving here"], page("relocation"), "Relocating here")
    add(["careers", "join", "join the team", "become a realtor"], page("join-our-team"), "Join our team")
    return dict(sorted(out.items()))


# ── v2: sold streets (ss) ─────────────────────────────────────────────────

def build_sold_streets(sold_rows, place_labels: dict, site_root=None, stats=None):
    """[[street, town, count, last_sold_date, url]]. Whitelist read: street,
    city, city_slug, sold_date -- never a price (VOW)."""
    root = Path(site_root) if site_root else None
    groups = defaultdict(lambda: [_Label(), _Label(), 0, "", ""])
    repaired, dropped, raw_keys = defaultdict(list), [], set()

    def add(key, rec):
        sname, city, date, ck, _raw = rec
        g = groups[key]
        g[0].add(sname)
        g[1].add(city)
        g[2] += 1
        if date > g[3]:
            g[3] = date
        g[4] = ck

    for r in sold_rows or []:
        if not isinstance(r, dict):
            continue
        street, city, slug, date = r.get("street"), r.get("city"), r.get("city_slug"), r.get("sold_date")
        date = str(date or "")[:10]
        if not _DATE_RE.match(date):
            continue                      # firm/pending rows carry no sold_date
        city = _strip_province(str(city or ""))
        ck = normalize(city)
        slug = str(slug or "") or ck.replace(" ", "-")
        if not slug:
            continue
        _num, plain = _split_street(str(street or ""))
        pk = normalize(plain)
        if not pk or pk.replace(" ", "").isdigit():
            continue
        raw_keys.add((pk, slug))
        sname, fixed = clean_street(street)
        sk = normalize(sname)
        rec = (sname, city, date, ck, (_pretty(plain), city))
        if not sk:
            dropped.append(rec[-1])
        elif fixed:
            repaired[(sk, slug)].append(rec)
        else:
            add((sk, slug), rec)
    _resolve_streets(set(groups), repaired, dropped, add)
    _street_stats(stats, "ss", raw_keys, len(groups), dropped)
    out = []
    for (sk, slug), (slab, clab, n, date, ck) in groups.items():
        town = place_labels.get(ck) or place_labels.get(normalize(slug.replace("-", " "))) or clab.best()
        has_page = bool(root and (root / "listings" / "sold" / slug / "index.html").is_file())
        url = f"/listings/sold/{slug}/" if has_page else "/listings/sold/"
        out.append([_pretty(slab.best()), town, n, date, url])
    out.sort(key=lambda x: (x[1].lower(), x[0].lower(), x[4]))
    return out


# ── index ─────────────────────────────────────────────────────────────────

def build_search_index(rows, *, site_key: str, city_name=None, sold_rows=None,
                       action: str = "/listings/", generated_at: str | None = None,
                       site_root=None, street_stats: dict | None = None) -> dict:
    """street_stats: optional dict the caller passes to receive the street
    cleaner's counts + dropped entries (emit_for_generator logs them)."""
    rows = [r for r in (rows or []) if isinstance(r, dict) and _get(r, "mls")]
    sold_rows = [r for r in (sold_rows or []) if isinstance(r, dict) and r.get("mls")]

    def city_of(r):
        c = _get(r, "city", "city_raw")
        if not c and city_name and r.get("city_slug"):
            try:
                c = city_name(r["city_slug"])
            except Exception:
                c = None
        if not c and r.get("city_slug"):
            c = str(r["city_slug"]).replace("-", " ").title()
        return _strip_province(str(c or "").strip())

    # photo_base from the first row whose photo is <base>/<mls>/<nnn>.jpg
    photo_base = ""
    for r in rows:
        p = _first_photo(r)
        m = _PHOTO_RE.match(p or "")
        if m and m.group(2) == str(r.get("mls")):
            photo_base = f"{m.group(1)}/{{mls}}/{m.group(3)}.{m.group(4)}"
            break

    cities = defaultdict(lambda: [_Label(), 0, 0])
    areas = defaultdict(lambda: [_Label(), 0, 0])
    streets = defaultdict(lambda: [_Label(), _Label(), 0])
    st_repaired, st_dropped, st_raw = defaultdict(list), [], set()

    def st_add(key, rec):
        streets[key][0].add(rec[0])
        streets[key][1].add(rec[1])
        streets[key][2] += 1

    postal = Counter()
    listing_rows = []

    for r in rows:
        mls = str(r.get("mls")).strip()
        city = city_of(r)
        ck = normalize(city)
        if ck:
            cities[ck][0].add(city)
            cities[ck][1] += 1
        area = _norm_subdistrict(_get(r, "area", "subdistrict", "idx_subdistrict"))
        if area:
            ak = normalize(area)
            areas[ak][0].add(area)
            areas[ak][1] += 1
        street = str(_get(r, "street") or "").strip()
        _num, plain = _split_street(street)
        if normalize(plain):
            st_raw.add((normalize(plain), ck))
            sname, fixed = clean_street(street)
            sk = normalize(sname)
            rec = (sname, city, (_pretty(plain), city))
            if not sk:
                st_dropped.append(rec[-1])
            elif fixed:
                st_repaired[(sk, ck)].append(rec)
            else:
                st_add((sk, ck), rec)
        pc = normalize(_get(r, "postal_code", "postal", "idx_postal_code") or "").replace(" ", "")
        if re.match(r"^[a-z]\d[a-z]", pc):
            postal[pc[:3].upper()] += 1
        price = _get(r, "price", "list_price")
        try:
            price = int(round(float(price))) if price is not None else None
        except (TypeError, ValueError):
            price = None
        if price is not None and price < 5000:   # lease rate / monthly rent, not a sale price
            price = None
        url = _row_url(r)
        photo = _first_photo(r)
        derived = photo_base.replace("{mls}", mls) if photo_base else None
        override = photo if (photo and photo != derived) else None
        shown = street
        for _ in range(3):                        # "&amp;amp;" -> "&" (display only; ids/urls untouched)
            shown = html.unescape(shown)
        listing_rows.append([mls, _pretty(shown), _pretty(city), price, url, override])

    # Sold rows only add counts. Their city field is agent-typed and noisy
    # ("Paradise NL", "Pardise"), so: strip a trailing province, fold a
    # spelling one typo away from an ACTIVE place into it, and keep a
    # sold-only place only when it has >= SOLD_ONLY_MIN sales.
    active_keys = [k for k, v in cities.items() if v[1] > 0]
    sold_only = defaultdict(lambda: [_Label(), 0])
    for r in sold_rows:
        raw_city = _strip_province(str(r.get("city") or ""))
        ck = normalize(raw_city)
        if not ck:
            continue
        if ck not in cities:
            near = [k for k in active_keys if abs(len(k) - len(ck)) <= 1 and _within1(ck, k)]
            if len(near) == 1:
                ck = near[0]
        if ck in cities:
            cities[ck][2] += 1
        else:
            sold_only[ck][0].add(raw_city)
            sold_only[ck][1] += 1
    for ck, (lab, n) in sold_only.items():
        if n >= SOLD_ONLY_MIN:
            cities[ck][0].add(lab.best())
            cities[ck][2] += n

    _resolve_streets(set(streets), st_repaired, st_dropped, st_add)
    _street_stats(street_stats, "streets", st_raw, len(streets), st_dropped)

    def place_list(d):
        out = [[v[0].best(), v[1], v[2]] for v in d.values() if v[0].best()]
        return sorted(out, key=lambda x: (-x[1], -x[2], x[0]))

    street_list = sorted(
        ([v[0].best(), v[1].best(), v[2]] for v in streets.values() if v[0].best()),
        key=lambda x: (-x[2], x[0], x[1]),
    )
    listing_rows.sort(key=lambda x: x[0])
    sold_mls = sorted({str(r["mls"]).strip() for r in sold_rows})
    city_list = place_list(cities)
    place_labels = {normalize(c[0]): c[0] for c in city_list}

    if site_root is not None:
        pages, ctx = build_pages(site_root, site_key)
        intents = build_intents(pages, ctx, place_labels)
    else:
        pages, intents = [], {}

    return {
        "v": INDEX_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "site": site_key,
        "action": action,
        "photo_base": photo_base,
        "cities": city_list,
        "areas": place_list(areas),
        "streets": street_list,
        "postal": sorted(([k, v] for k, v in postal.items()), key=lambda x: (-x[1], x[0])),
        "l": listing_rows,
        "sold_mls": ",".join(sold_mls),
        "p": pages,
        "i": intents,
        "ss": build_sold_streets(sold_rows, place_labels, site_root, street_stats),
    }


def _dumps(index: dict) -> str:
    return json.dumps(index, ensure_ascii=False, separators=(",", ":"))


def _gz_len(text: str) -> int:
    return len(gzip.compress(text.encode("utf-8"), 9))


def fit_budget(index: dict, max_gz: int = MAX_GZ_BYTES) -> dict:
    """Trim rule (contract section 5): over budget -> drop ss rows with
    count == 1, oldest first, the fewest that fit; record trim.ss. Loud."""
    if _gz_len(_dumps(index)) <= max_gz:
        index.pop("trim", None)
        return index
    ss = index.get("ss") or []
    cands = sorted((n for n, r in enumerate(ss) if r[2] == 1), key=lambda n: (ss[n][3], n))

    def without(k):
        drop = set(cands[:k])
        d = dict(index, ss=[r for n, r in enumerate(ss) if n not in drop])
        d["trim"] = {"ss": k}
        return d

    lo, hi = 0, len(cands)
    if _gz_len(_dumps(without(hi))) > max_gz:
        return without(hi)          # still over: --check fails CI loudly
    while lo < hi:
        mid = (lo + hi) // 2
        if _gz_len(_dumps(without(mid))) <= max_gz:
            hi = mid
        else:
            lo = mid + 1
    return without(lo)


def _body_without_timestamp(index: dict) -> str:
    d = dict(index)
    d.pop("generated_at", None)
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def write_search_index(site_root, index: dict) -> dict:
    """Writes listings/search-index.json. Keeps the old generated_at when the
    content is unchanged so an unchanged feed produces no git diff."""
    path = Path(site_root) / INDEX_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        if _body_without_timestamp(old) == _body_without_timestamp(index):
            index = dict(index, generated_at=old.get("generated_at", index.get("generated_at")))
    except Exception:
        pass
    text = _dumps(index)
    path.write_text(text, encoding="utf-8")
    gz = _gz_len(text)
    return {"path": str(INDEX_REL), "bytes": len(text.encode("utf-8")), "gz_bytes": gz,
            "cities": len(index["cities"]), "streets": len(index["streets"]),
            "listings": len(index["l"]), "sold": index["sold_mls"].count(",") + (1 if index["sold_mls"] else 0),
            "pages": len(index.get("p") or []), "intents": len(index.get("i") or {}),
            "sold_streets": len(index.get("ss") or []), "trim": (index.get("trim") or {}).get("ss", 0)}


def read_sold_rows(site_root):
    """Fail-safe read of the committed listings/sold/data.json rows."""
    try:
        d = json.loads((Path(site_root) / "listings" / "sold" / "data.json").read_text(encoding="utf-8"))
        return d.get("rows") or []
    except Exception:
        return []


def emit_for_generator(site_root, rows, *, site_key, city_name=None, verbose=False):
    """The one call each ddf-generate-pages.py makes. Never raises."""
    try:
        sold = read_sold_rows(site_root)
        if not sold:
            print("[GEN] search-index: listings/sold/data.json missing or empty -> sold_mls and ss are empty")
        st = {}
        idx = build_search_index(rows, site_key=site_key, city_name=city_name,
                                 sold_rows=sold, site_root=site_root, street_stats=st)
        for key, label in (("streets", "streets"), ("ss", "sold streets")):
            c = st.get(key) or {"raw": 0, "clean": 0, "dropped": []}
            print(f"[search-index] {label}: {c['raw']} raw → {c['clean']} clean, {len(c['dropped'])} dropped")
            if verbose and c["dropped"]:
                for name, town in c["dropped"]:
                    print(f"[search-index]   dropped {label}: {name} ({town})")
        if not idx["p"]:
            print("[GEN] search-index: no pages read from sitemap.xml -> p and i are empty")
        idx = fit_budget(idx)
        s = write_search_index(site_root, idx)
        print(f"[GEN] search-index v{INDEX_VERSION}: {s['listings']} listings, {s['cities']} places, "
              f"{s['streets']} streets, {s['sold']} sold MLS, {s['pages']} pages, {s['intents']} intents, "
              f"{s['sold_streets']} sold streets -> {s['path']} "
              f"({s['bytes']:,} B, {s['gz_bytes']:,} B gz)")
        if s["trim"]:
            print(f"[GEN] search-index TRIMMED: dropped {s['trim']} single-sale sold streets (oldest first) "
                  f"to fit the {MAX_GZ_BYTES:,} B gz budget")
        if s["gz_bytes"] > MAX_GZ_BYTES:
            print(f"[GEN] search-index WARNING: {s['gz_bytes']:,} B gz exceeds the {MAX_GZ_BYTES:,} B budget")
        return s
    except Exception as e:  # noqa: BLE001 -- Conv #74: never break a regen
        print(f"[GEN] search-index skipped: {e!r}")
        return None


_FORBIDDEN_KEY_RE = re.compile(r"close|sold_?price|soldprice", re.IGNORECASE)


def _forbidden_keys(obj, path="$"):
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if path != "$.i" and _FORBIDDEN_KEY_RE.search(str(k)):
                found.append(f"{path}.{k}")
            found += _forbidden_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for n, v in enumerate(obj):
            found += _forbidden_keys(v, f"{path}[{n}]")
    return found


def validate(d: dict, text: str | None = None) -> list:
    """Contract checks (section 6). Returns a list of problems."""
    problems = []
    if not isinstance(d, dict):
        return ["not an object"]
    if d.get("v") != INDEX_VERSION or not isinstance(d.get("v"), int):
        problems.append(f"v is {d.get('v')!r}, expected {INDEX_VERSION}")
    for k in ("v", "site", "action", "cities", "streets", "postal", "l", "sold_mls", "p", "i", "ss"):
        if k not in d:
            problems.append(f"missing key {k}")
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", str(d.get("generated_at") or "")):
        problems.append(f"generated_at not ISO UTC: {d.get('generated_at')!r}")
    for n, r in enumerate(d.get("p") or []):
        if not (isinstance(r, list) and len(r) == 4 and all(isinstance(x, str) for x in r)
                and r[2] in PAGE_TYPES and r[1].startswith("/")):
            problems.append(f"p[{n}] malformed: {r!r}")
            break
    i = d.get("i")
    if not isinstance(i, dict):
        problems.append("i is not an object")
    else:
        for k, v in i.items():
            if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, str) and x for x in v)
                    and (v[0].startswith("/") or v[0].startswith("tel:")) and k == normalize(k)):
                problems.append(f"i[{k!r}] malformed: {v!r}")
                break
    for n, r in enumerate(d.get("ss") or []):
        if not (isinstance(r, list) and len(r) == 5 and isinstance(r[0], str) and r[0]
                and isinstance(r[1], str) and isinstance(r[2], int) and not isinstance(r[2], bool)
                and r[2] > 0 and isinstance(r[3], str) and _DATE_RE.match(r[3])
                and isinstance(r[4], str) and r[4].startswith("/listings/sold/")):
            problems.append(f"ss[{n}] malformed: {r!r}")
            break
    bad = _forbidden_keys(d)
    if bad:
        problems.append(f"price-like key(s) present: {bad[:5]}")
    text = text if text is not None else _dumps(d)
    gz = _gz_len(text)
    if gz > MAX_GZ_BYTES:
        problems.append(f"{gz:,} B gz > {MAX_GZ_BYTES:,} B budget")
    if not d.get("l"):
        problems.append("no listings")
    return problems


def check(site_root) -> int:
    path = Path(site_root) / INDEX_REL
    try:
        text = path.read_text(encoding="utf-8")
        d = json.loads(text)
    except Exception as e:
        print(f"[search-index] FAIL: cannot read {path}: {e}")
        return 1
    problems = validate(d, text)
    for p in problems:
        print(f"[search-index] FAIL: {p}")
    if not problems:
        print(f"[search-index] OK v{d['v']}: {len(d['l'])} listings, {len(d['cities'])} places, "
              f"{len(d['streets'])} streets, {len(d['p'])} pages, {len(d['i'])} intents, "
              f"{len(d['ss'])} sold streets, {len(text):,} B / {_gz_len(text):,} B gz")
    return 1 if problems else 0


def _self_test() -> int:
    fails = 0

    def ok(name, cond, detail=""):
        nonlocal fails
        if not cond:
            fails += 1
            print(f"FAIL {name} {detail}")

    avalon_rows = [
        {"mls": "1300001", "street": "12 Torbay Road", "city_raw": "St. John's", "city_slug": "st-johns",
         "postal_code": "A1B 3C0", "list_price": 429900.0, "url_path": "/listings/st-johns/12-torbay-road-1300001.html",
         "photos": [{"url": "https://photos.example/avalon/listings/1300001/001.jpg"}], "subdistrict": "SJ01 - East"},
        {"mls": "1300002", "street": "88 Torbay Road", "city_raw": "St John's", "city_slug": "st-johns",
         "postal_code": "A1A2B3", "list_price": 350000, "url_path": "/listings/st-johns/88-torbay-road-1300002.html",
         "photos": [{"url": "https://photos.example/avalon/listings/1300002/001.jpg"}]},
        {"mls": "1300003", "street": "Unit 4 - 100 Topsail Rd", "city_raw": "ST. JOHN`S", "city_slug": "st-johns",
         "postal_code": "A1N 4P2", "list_price": None, "url_path": "/listings/st-johns/x-1300003.html",
         "photos": [{"url": "https://cdn.other/odd.jpg"}]},
    ]
    avalon_rows.append({"mls": "1300004", "street": "5 Pearl Lane", "city_raw": "Mount Pearl, NL", "city_slug": "mount-pearl",
                        "postal_code": "A1N 1A1", "list_price": 300000, "url_path": "/listings/mount-pearl/x-1300004.html"})
    gander_rows = [
        {"mls": "1301245", "street": "37 Read Street", "city": "Gander", "idx_postal_code": "A1V 1K4",
         "price": 280000, "url": "/listings/gander/37-read-street-1301245.html", "idx_subdistrict": "Gander and Area"},
    ]
    sold = [{"mls": "1290000", "city": "St. John's"}, {"mls": "1290001", "city": "Paradise"},
            {"mls": "1290002", "city": "Paradise"}, {"mls": "1290003", "city": "Paradise"},
            {"mls": "1290004", "city": "St Johns NL"}, {"mls": "1290005", "city": "Gandr"},
            {"mls": "1290006", "city": "Nowhere Cove"}]
    idx = build_search_index(avalon_rows + gander_rows, site_key="avalon", sold_rows=sold, generated_at="T")
    for k in ("v", "site", "action", "photo_base", "cities", "areas", "streets", "postal", "l", "sold_mls", "p", "i", "ss"):
        ok(f"key {k}", k in idx)
    ok("v is integer 2", idx["v"] == 2 and isinstance(idx["v"], int), idx["v"])
    stj = [c for c in idx["cities"] if normalize(c[0]) in ("st johns",)]
    ok("St. John's spellings merged (incl. sold 'St Johns NL')", len(stj) == 1 and stj[0][1] == 3 and stj[0][2] == 2, idx["cities"])
    ok("sold typo folded into active place", any(c[0] == "Gander" and c[2] == 1 for c in idx["cities"]), idx["cities"])
    ok("rare sold-only place dropped", not any(c[0] == "Nowhere Cove" for c in idx["cities"]), idx["cities"])
    ok("merged label not ALL CAPS", stj and stj[0][0] in ("St. John's", "St John's"), stj)
    ok("Unit 4 - 100 Topsail Rd street split", any(s[0] == "Topsail Rd" for s in idx["streets"]), idx["streets"])
    ok("Torbay Road grouped", any(s[0] == "Torbay Road" and s[2] == 2 for s in idx["streets"]), idx["streets"])
    ok("photo_base derived", idx["photo_base"] == "https://photos.example/avalon/listings/{mls}/001.jpg", idx["photo_base"])
    rows_by = {r[0]: r for r in idx["l"]}
    ok("no override for template photo", rows_by["1300001"][5] is None)
    ok("override for odd photo", rows_by["1300003"][5] == "https://cdn.other/odd.jpg")
    ok("null price kept null", rows_by["1300003"][3] is None)
    ok("gander url + price", rows_by["1301245"][4].endswith("1301245.html") and rows_by["1301245"][3] == 280000)
    ok("postal FSAs", dict((p[0], p[1]) for p in idx["postal"]).get("A1B") == 1, idx["postal"])
    ok("subdistrict normalized", [a[0] for a in idx["areas"]] == ["East", "Gander and Area"] or
       sorted(a[0] for a in idx["areas"]) == ["East", "Gander and Area"], idx["areas"])
    ok("_norm_subdistrict", _norm_subdistrict("SJ01 - East") == "East" and _norm_subdistrict("") is None)
    ok("province suffix stripped", any(c[0] == "Mount Pearl" for c in idx["cities"]) and
       not any(c[0].endswith("NL") for c in idx["cities"]), idx["cities"])
    ok("sold mls", idx["sold_mls"].split(",") == [f"129000{i}" for i in range(7)], idx["sold_mls"])
    ok("sold-only city with >=3 sales kept", any(c[0] == "Paradise" and c[1] == 0 and c[2] == 3 for c in idx["cities"]), idx["cities"])
    lease = build_search_index([{"mls": "1301999", "street": "650 TOPSAIL Road", "city_raw": "ST. JOHN`S",
                                 "list_price": 18, "url_path": "/x-1301999.html"}], site_key="avalon", generated_at="T")
    lr = lease["l"][0]
    ok("street title-cased", lr[1] == "650 Topsail Road", lr)
    ok("city apostrophe kept lower-case", lr[2] == "St. John’s", lr)
    ok("lease rate dropped as price", lr[3] is None, lr)
    slugrow = build_search_index([{"mls": "1302000", "street": "1 A St", "city_slug": "gander", "slug": "1-a-st-1302000",
                                   "list_price": 1e5}], site_key="gander", generated_at="T")
    ok("url from city_slug + slug", slugrow["l"][0][4] == "/listings/gander/1-a-st-1302000.html", slugrow["l"])
    idx2 = build_search_index(list(reversed(avalon_rows + gander_rows)), site_key="avalon", sold_rows=sold, generated_at="T")
    ok("deterministic", json.dumps(idx, sort_keys=True) == json.dumps(idx2, sort_keys=True))
    ok("normalize", normalize("ST. JOHN`S") == normalize("St John's") == "st johns")

    # ss: whitelist read, no price, firm/pending skipped, town spelling merged
    sold2 = [
        {"mls": "1", "street": "12 Torbay Road", "city": "St Johns", "city_slug": "st-johns", "sold_date": "2026-05-01",
         "close_price": 777111, "sold_price": 777222, "list_price": 777333},
        {"mls": "2", "street": "40 TORBAY ROAD", "city": "St. John's", "city_slug": "st-johns", "sold_date": "2026-09-30",
         "close_price": 777444},
        {"mls": "3", "street": "9 Elm St", "city": "Gander", "city_slug": "gander", "sold_date": "",
         "state": "firm_pending"},
        {"mls": "4", "street": "358 - 376 Portugal Cove", "city": "St. John's", "city_slug": "st-johns",
         "sold_date": "2026-06-12T02:00:00Z"},
    ]
    i3 = build_search_index(avalon_rows, site_key="avalon", sold_rows=sold2, generated_at="2026-10-08T00:00:00Z")
    ss = {r[0]: r for r in i3["ss"]}
    ok("ss Torbay Road grouped with count 2 + newest date",
       "Torbay Road" in ss and ss["Torbay Road"][2] == 2 and ss["Torbay Road"][3] == "2026-09-30", i3["ss"])
    ok("ss town uses the cities spelling", ss.get("Torbay Road", [0, ""])[1] in ("St. John's", "St John's"), i3["ss"])
    ok("ss skips firm/pending (no sold_date)", "Elm St" not in ss, i3["ss"])
    ok("ss range house numbers stripped", "Portugal Cove" in ss, i3["ss"])
    ok("ss url is the sold archive", all(r[4].startswith("/listings/sold/") for r in i3["ss"]), i3["ss"])
    blob = _dumps(i3)
    ok("no sold price value reaches the index", not any(s in blob for s in ("777111", "777222", "777333", "777444")))
    ok("validate() passes a built index", validate(i3) == [], validate(i3))
    bad = dict(i3, v=1)
    ok("validate() rejects v=1", any("v is" in p for p in validate(bad)))
    bad2 = dict(i3, ss=[["X", "Y", 1, "2026-01-01", "/listings/sold/", 500000]])
    ok("validate() rejects an ss row with a 6th (price) field", any("ss[0]" in p for p in validate(bad2)))
    bad3 = dict(i3, extra={"close_price": 1})
    ok("validate() rejects a close_price key", any("price-like" in p for p in validate(bad3)))

    # budget trim: oldest single-sale streets go first, recorded in trim.ss
    big = dict(i3, ss=[[f"S{n:05d}x{n * 7919 % 100003}", "Town", 1 if n % 3 else 2, f"2025-{1 + n % 12:02d}-01",
                        "/listings/sold/"] for n in range(6000)])
    fitted = fit_budget(big, max_gz=_gz_len(_dumps(big)) - 5000)
    ok("trim records how many rows it dropped", fitted.get("trim", {}).get("ss", 0) > 0, fitted.get("trim"))
    ok("trim keeps every multi-sale street", all(r in fitted["ss"] for r in big["ss"] if r[2] == 2))
    ok("no trim key when under budget", "trim" not in fit_budget(dict(i3)))
    print(f"_search_index self-test: {'OK' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


def _emit_from_committed(site_root, site_key=None) -> int:
    root = Path(site_root)
    if not site_key:
        try:
            site_key = json.loads((root / "tools" / "_fleet_config.json").read_text())["site_key"]
        except Exception:
            site_key = root.name
    proj = root / "tools" / "idx-cache" / "listings-projected.json"
    data = root / "listings" / "data.json"
    src = proj if proj.exists() else data
    d = json.loads(src.read_text(encoding="utf-8"))
    rows = d.get("listings") or d.get("rows") or []
    s = emit_for_generator(root, rows, site_key=site_key)
    return 0 if s else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--self-test"]:
        sys.exit(_self_test())
    if a[:1] == ["--check"] and len(a) >= 2:
        sys.exit(check(a[1]))
    if a[:1] == ["--emit"] and len(a) >= 2:
        key = a[a.index("--site") + 1] if "--site" in a else None
        sys.exit(_emit_from_committed(a[1], key))
    print(__doc__)
    sys.exit(2)
