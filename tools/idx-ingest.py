#!/usr/bin/env python3
"""
Turner Realty — NLAR IDX/VOW RETS Ingester
============================================

Pulls active + sold + expired listings from NLAR's Matrix RETS server
into tools/idx-cache/. Replaces the ddf-ingest.py path once IDX/VOW
goes through bake (Convention #29 four-gate retirement).

Phase 0 (this file, 2026-05-06 evening): SKELETON ONLY.
    --probe mode: login + capability URL discovery + system metadata.
    Verifies auth + endpoint reachability + protocol shape before
    we write a single line of search/parse code.

Phase 1 (tomorrow morning): metadata pull + first Search call.
Phase 2 (tomorrow afternoon): full ingest → tools/idx-cache/listings.json
                              + sold-listings.json + expired-listings.json
                              schema-mapped to existing DDF cache shape.

Credentials:
    Read from environment OR from a .env file at workspace root.
    NEVER hard-coded. NEVER logged. NEVER committed.

    Workspace root .env (canonical, single-source for all 5 sites):
        /Users/mike/Documents/Claude/Projects/Royal Lepage Turner Website/.env

    Per-site .env (defensive fallback):
        realestategander-site/.env   (gitignored)

    Required keys:
        NLAR_RETS_USER     — RETS account username
        NLAR_RETS_PASS     — RETS account password
        NLAR_RETS_LOGIN    — login endpoint URL (default: NLAR Matrix)
        NLAR_RETS_USERAGENT — RETS UA header (optional; defaults to RLP-Turner/1.0)

RETS protocol notes (Matrix flavor):
    - Standard: RETS-1.7.2 (Matrix supports 1.5 + 1.7.2)
    - Auth: HTTP Basic over HTTPS + session cookie + RETS-Version header
    - Login response: XML with capability URLs (Search, GetMetadata,
      GetObject, Logout, etc.)
    - All subsequent calls go to those capability URLs (NOT to the login URL)
    - Session is preserved via cookie until Logout or timeout
    - Some Matrix servers require an HMAC-SHA1 RETS-UA-Authorization header
      with a per-session client password — try without first; add if 401s

Usage:
    # First run — verify auth works
    python3 tools/idx-ingest.py --probe

    # Print server's capability URLs after login
    python3 tools/idx-ingest.py --probe --json

    # Pull system metadata (resources + classes available)
    python3 tools/idx-ingest.py --metadata

    # Phase 2+ (not yet implemented):
    python3 tools/idx-ingest.py --pull active   → tools/idx-cache/listings.json
    python3 tools/idx-ingest.py --pull sold     → tools/idx-cache/sold-listings.json
    python3 tools/idx-ingest.py --pull expired  → tools/idx-cache/expired-listings.json
    python3 tools/idx-ingest.py --pull all      → all three
"""

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth


def _now_iso() -> str:
    """UTC ISO timestamp without microseconds."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ─────────────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
SITE_ROOT = SCRIPT_DIR.parent
WORKSPACE_ROOT = SITE_ROOT.parent
CACHE_DIR = SCRIPT_DIR / "idx-cache"

DEFAULT_LOGIN_URL = "https://rets.nlar.mlxmatrix.com/rets/login.ashx"
DEFAULT_USER_AGENT = "RLP-Turner/1.0"
DEFAULT_RETS_VERSION = "RETS/1.7.2"

# Files to look for env credentials, in priority order.
ENV_CANDIDATES = [
    WORKSPACE_ROOT / ".env",        # canonical (workspace-root, gitignored)
    SITE_ROOT / ".env",             # per-site fallback (gitignored)
    Path.home() / ".nlar-rets.env", # home-dir fallback
]


# ─────────────────────────────────────────────────────────────────
#  CREDENTIAL LOADING (env file → os.environ → defaults)
# ─────────────────────────────────────────────────────────────────

def load_env_file(path: Path) -> dict:
    """Parse a simple KEY=VALUE .env file (no shell expansion).

    Returns {} if the file doesn't exist or is empty. Lines starting
    with # are comments. Empty lines ignored.
    """
    if not path.exists():
        return {}
    out = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Strip surrounding quotes if present
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        out[key.strip()] = value
    return out


def load_credentials() -> dict:
    """Load credentials from .env files (priority order) + os.environ override.

    Returns dict with keys: NLAR_RETS_USER, NLAR_RETS_PASS, NLAR_RETS_LOGIN,
    NLAR_RETS_USERAGENT. Missing required keys → SystemExit with helpful message.
    """
    creds = {}
    for candidate in ENV_CANDIDATES:
        if candidate.exists():
            creds.update(load_env_file(candidate))

    # os.environ overrides any .env file (CI sets via secrets.NLAR_RETS_*)
    for key in ["NLAR_RETS_USER", "NLAR_RETS_PASS", "NLAR_RETS_LOGIN",
                "NLAR_RETS_USERAGENT"]:
        if key in os.environ:
            creds[key] = os.environ[key]

    # Apply defaults
    creds.setdefault("NLAR_RETS_LOGIN", DEFAULT_LOGIN_URL)
    creds.setdefault("NLAR_RETS_USERAGENT", DEFAULT_USER_AGENT)

    # Validate required
    missing = [k for k in ["NLAR_RETS_USER", "NLAR_RETS_PASS"] if k not in creds]
    if missing:
        print(f"ERROR: missing required credential(s): {', '.join(missing)}",
              file=sys.stderr)
        print(f"", file=sys.stderr)
        print(f"Expected in one of:", file=sys.stderr)
        for c in ENV_CANDIDATES:
            exists = " (exists)" if c.exists() else " (not present)"
            print(f"  - {c}{exists}", file=sys.stderr)
        print(f"", file=sys.stderr)
        print(f"Or in environment variables (CI: secrets.NLAR_RETS_*).",
              file=sys.stderr)
        print(f"", file=sys.stderr)
        print(f"To create the canonical workspace-root .env:", file=sys.stderr)
        print(f"  cd '{WORKSPACE_ROOT}'", file=sys.stderr)
        print(f"  cat > .env <<'EOF'", file=sys.stderr)
        print(f"  NLAR_RETS_USER=<username>", file=sys.stderr)
        print(f"  NLAR_RETS_PASS=<password>", file=sys.stderr)
        print(f"  EOF", file=sys.stderr)
        print(f"  chmod 600 .env", file=sys.stderr)
        sys.exit(2)

    return creds


# ─────────────────────────────────────────────────────────────────
#  RETS LOGIN + CAPABILITY DISCOVERY
# ─────────────────────────────────────────────────────────────────

def parse_capability_response(text: str) -> dict:
    """Parse RETS login response and extract capability URLs.

    Matrix returns either XML (`<RETS-RESPONSE>...</RETS-RESPONSE>`) or
    key-value text. Both shapes are valid per RETS-1.7.2 spec.

    Returns: dict mapping capability name (lowercase) → absolute URL.
    Common capabilities: login, logout, getmetadata, search, getobject,
    action, changepassword.
    """
    capabilities = {}

    # Try XML shape first
    try:
        root = ET.fromstring(text)
        body = root.find(".//RETS-RESPONSE")
        body_text = body.text if body is not None else text
    except ET.ParseError:
        body_text = text

    # Both shapes contain key-value pairs separated by newlines
    for line in body_text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        capabilities[key.strip().lower()] = value.strip()

    return capabilities


def make_absolute(url: str, base: str) -> str:
    """Capability URLs in the response can be relative or absolute.

    Matrix typically returns absolute URLs. If relative (e.g. /rets/Search.ashx),
    rebase against the login URL's scheme + host.

    NOTE (fix 2026-05-07): the login response mixes URL capabilities (search,
    getmetadata, getobject, etc.) with SCALAR metadata (metadatatimestamp,
    metadataversion, user, broker, membername). Earlier version naively
    prepended the base URL to every value, producing garbage like
    "https://rets.nlar.mlxmatrix.com2026-04-30T15:17:11Z". Fix: only treat
    a value as URL-like if it's already absolute OR starts with "/" (path).
    Everything else (timestamps, version strings, identity tuples) is left
    unchanged.
    """
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("/"):
        from urllib.parse import urlparse
        p = urlparse(base)
        return f"{p.scheme}://{p.netloc}{url}"
    # Scalar value (not a URL) — leave as-is. Examples from Matrix:
    #   metadatatimestamp=2026-04-30T15:17:11Z
    #   metadataversion=1.00.01274
    #   user=USER_ID,NULL,NULL,NAME
    return url


# NLAR allows one RETS session per account; ReplyCode 20022 = "Additional login not
# permitted". rets_login() waits these many seconds between retries (~10.5 min total).
LOGIN_BUSY_REPLY = "20022"
LOGIN_BUSY_BACKOFF_S = (30, 60, 120, 180, 240)


def rets_login(creds: dict, *, verbose: bool = False) -> tuple:
    """Perform RETS login and return (session, capabilities, server_info).

    On success:
        - session: requests.Session with auth + cookies set
        - capabilities: dict of capability_name → absolute URL
        - server_info: dict with RETS-Version, ServerInfo, etc. (from headers)

    On auth failure: prints diagnostic + sys.exit(1).
    """
    session = requests.Session()
    session.auth = HTTPBasicAuth(creds["NLAR_RETS_USER"], creds["NLAR_RETS_PASS"])
    session.headers.update({
        "User-Agent": creds["NLAR_RETS_USERAGENT"],
        "RETS-Version": DEFAULT_RETS_VERSION,
        "Accept": "*/*",
    })

    login_url = creds["NLAR_RETS_LOGIN"]

    if verbose:
        # Log only redacted credential info — never the actual password
        user = creds["NLAR_RETS_USER"]
        pass_redacted = creds["NLAR_RETS_PASS"][:1] + "***"
        print(f"[probe] POST {login_url}", file=sys.stderr)
        print(f"[probe] User-Agent: {creds['NLAR_RETS_USERAGENT']}", file=sys.stderr)
        print(f"[probe] RETS-Version: {DEFAULT_RETS_VERSION}", file=sys.stderr)
        print(f"[probe] Auth: Basic {user}:{pass_redacted} (redacted)", file=sys.stderr)

    # 2026-09-23: NLAR allows ONE RETS session per account. A second login while
    # another job holds it answers HTTP 200 + ReplyCode 20022 "Additional login not
    # permitted". The three sites' nightly-full runs all start at 20:00 UTC, so
    # their pulls collided most nights (Avalon's rooms / open-house / sold-photo
    # pulls and Goose Bay's failing since at least 09-20). Wait for the other
    # session to finish instead of dying; every other refusal still exits at once.
    for attempt in range(len(LOGIN_BUSY_BACKOFF_S) + 1):
        try:
            response = session.get(login_url, timeout=30)
        except requests.RequestException as e:
            print(f"ERROR: connection to {login_url} failed: {e}", file=sys.stderr)
            sys.exit(1)

        if verbose:
            print(f"[probe] HTTP {response.status_code}", file=sys.stderr)
            print(f"[probe] Server: {response.headers.get('Server', '<unset>')}",
                  file=sys.stderr)
            print(f"[probe] RETS-Version (response): "
                  f"{response.headers.get('RETS-Version', '<unset>')}", file=sys.stderr)

        # 401 -> either bad creds OR Matrix wants Digest auth (try once)
        if response.status_code == 401:
            if verbose:
                print(f"[probe] 401 on Basic; retrying with Digest auth...",
                      file=sys.stderr)
            session.auth = HTTPDigestAuth(creds["NLAR_RETS_USER"],
                                           creds["NLAR_RETS_PASS"])
            response = session.get(login_url, timeout=30)
            if verbose:
                print(f"[probe] HTTP {response.status_code} (Digest retry)",
                      file=sys.stderr)

        if response.status_code != 200:
            print(f"ERROR: login HTTP {response.status_code}: "
                  f"{response.text[:200]}", file=sys.stderr)
            sys.exit(1)

        # 2026-09-19: a RETS server answers HTTP 200 even when it REFUSES the login --
        # the refusal lives in <RETS ReplyCode="..." ReplyText="...">. Unread, a
        # refused login parsed into a junk capability dict and every caller died
        # later with the undiagnosable "no search capability URL".
        _reply = re.search(r'ReplyCode="(\d+)"(?:\s+ReplyText="([^"]*)")?', response.text[:500])
        if _reply and _reply.group(1) != "0":
            _text = _reply.group(2) or "(no ReplyText)"
            if _reply.group(1) == LOGIN_BUSY_REPLY and attempt < len(LOGIN_BUSY_BACKOFF_S):
                _wait = LOGIN_BUSY_BACKOFF_S[attempt]
                print(f"[rets] login busy -- ReplyCode {LOGIN_BUSY_REPLY}: {_text}; another job "
                      f"holds the NLAR session. Retry {attempt + 1}/{len(LOGIN_BUSY_BACKOFF_S)} "
                      f"in {_wait}s", file=sys.stderr)
                time.sleep(_wait)
                continue
            print(f"ERROR: RETS login refused -- ReplyCode {_reply.group(1)}: {_text}",
                  file=sys.stderr)
            sys.exit(1)
        break

    capabilities = parse_capability_response(response.text)

    if not capabilities:
        print(f"ERROR: no capabilities parsed from login response",
              file=sys.stderr)
        print(f"Response body (first 500 chars): {response.text[:500]}",
              file=sys.stderr)
        sys.exit(1)

    # Resolve relative URLs against the login URL
    capabilities = {k: make_absolute(v, login_url) for k, v in capabilities.items()}

    server_info = {
        "rets_version": response.headers.get("RETS-Version", "unknown"),
        "server": response.headers.get("Server", "unknown"),
        "session_cookie": dict(session.cookies),
    }

    return session, capabilities, server_info


def rets_logout(session: requests.Session, capabilities: dict) -> None:
    """Polite logout to release the server-side session."""
    logout_url = capabilities.get("logout")
    if not logout_url:
        return
    try:
        session.get(logout_url, timeout=10)
    except requests.RequestException:
        pass


# ─────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────

def cmd_probe(args, creds):
    """Login, print capability URLs, logout. No search, no metadata."""
    print(f"NLAR RETS Probe — {creds['NLAR_RETS_LOGIN']}")
    print(f"User: {creds['NLAR_RETS_USER']}")
    print(f"")

    session, capabilities, server_info = rets_login(creds, verbose=args.verbose)

    print(f"✓ Login successful")
    print(f"  RETS-Version: {server_info['rets_version']}")
    print(f"  Server: {server_info['server']}")
    print(f"  Session cookie keys: {list(server_info['session_cookie'].keys())}")
    print(f"")
    print(f"Capability URLs ({len(capabilities)} total):")
    for name in sorted(capabilities):
        print(f"  {name:20s} → {capabilities[name]}")

    if args.json:
        print(f"")
        print(json.dumps({
            "login_url": creds["NLAR_RETS_LOGIN"],
            "user": creds["NLAR_RETS_USER"],
            "rets_version": server_info["rets_version"],
            "server": server_info["server"],
            "capabilities": capabilities,
        }, indent=2))

    rets_logout(session, capabilities)
    print(f"")
    print(f"✓ Logout sent. Probe complete.")
    return 0


def fetch_metadata(session, capabilities, *, mtype="METADATA-SYSTEM", resource_id="*",
                   format_="STANDARD-XML", verbose=False):
    """Issue a GetMetadata GET against the server.

    RETS GetMetadata params:
      - Type: METADATA-SYSTEM, METADATA-RESOURCE, METADATA-CLASS,
              METADATA-TABLE (fields), METADATA-LOOKUP, METADATA-OBJECT
      - ID: resource:class for METADATA-TABLE, "*" for system-wide pull
      - Format: STANDARD-XML (only — see vendor note below).

    Vendor note (banked 2026-05-07 from NLAR Matrix diagnostic):
    NLAR Matrix returns reply_code=20513 ("Format not supported") on
    COMPACT-DECODED requests for METADATA — the server only honors
    STANDARD-XML for metadata. STANDARD-XML structure is nested
    <Resource><ResourceID>Property</ResourceID>...</Resource> elements
    where each child tag is a field name and its text content is the
    value. parse_metadata_xml() handles this shape via _parse_record().

    NOTE: Search responses (not metadata) DO support COMPACT-DECODED on
    Matrix and that's what we'll use for paginated listing pulls.
    Different format requirements per call type.
    """
    url = capabilities.get("getmetadata")
    if not url:
        print("ERROR: no getmetadata capability URL", file=sys.stderr)
        sys.exit(1)
    params = {"Type": mtype, "ID": resource_id, "Format": format_}
    if verbose:
        print(f"[metadata] GET {url} params={params}", file=sys.stderr)
    try:
        r = session.get(url, params=params, timeout=60)
    except requests.RequestException as e:
        print(f"ERROR: GetMetadata request failed: {e}", file=sys.stderr)
        sys.exit(1)
    if verbose:
        print(f"[metadata] HTTP {r.status_code} ({len(r.content)} bytes)",
              file=sys.stderr)
    if r.status_code != 200:
        print(f"ERROR: GetMetadata HTTP {r.status_code}: {r.text[:300]}",
              file=sys.stderr)
        sys.exit(1)
    return r.text


def parse_metadata_xml(xml_text: str) -> dict:
    """Parse a RETS METADATA-* XML response.

    Handles BOTH RETS metadata response shapes — auto-detects which:

      (A) COMPACT shape (used by some servers + by RETS Search responses):
          <RETS><METADATA-X>
            <COLUMNS>	field1	field2	...	</COLUMNS>
            <DATA>	val1	val2	...	</DATA>
            <DATA>	...	</DATA>
          </METADATA-X></RETS>

      (B) STANDARD-XML shape (NLAR Matrix metadata — confirmed 2026-05-07):
          <RETS><METADATA><METADATA-X Version="..." Date="...">
            <Resource>            <- "record" element, varies by Type:
              <ResourceID>...</ResourceID>     Resource (METADATA-RESOURCE)
              <StandardName>...</StandardName> Class    (METADATA-CLASS)
              <KeyField>...</KeyField>         Field    (METADATA-TABLE)
              ...
            </Resource>
            <Resource>...</Resource>
          </METADATA-X></METADATA></RETS>

    Returns blocks with the same downstream-friendly structure regardless
    of input format:
        {tag, attrib, columns, rows}
        - columns: ordered list of field names
        - rows:    list of value lists, aligned to columns

    metadata_to_records() flattens these into list-of-dicts.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        return {"error": f"XML parse failed: {e}",
                "raw_first_500": xml_text[:500]}

    out = {
        "reply_code": root.get("ReplyCode"),
        "reply_text": root.get("ReplyText"),
        "blocks": [],
    }

    def _parse_compact_block(elem):
        """Parse a COMPACT-shape block (COLUMNS + DATA tab-delimited)."""
        block = {
            "tag":     elem.tag,
            "attrib":  dict(elem.attrib),
            "columns": [],
            "rows":    [],
            "format":  "COMPACT",
        }
        for child in elem:
            if child.tag == "COLUMNS":
                block["columns"] = [c for c in (child.text or "").split("\t") if c]
            elif child.tag == "DATA":
                raw = child.text or ""
                row = raw.split("\t")
                if row and row[0] == "":
                    row = row[1:]
                if row and row[-1] == "":
                    row = row[:-1]
                if row:
                    block["rows"].append(row)
        return block

    def _parse_standard_block(elem):
        """Parse a STANDARD-XML-shape block.

        elem is a METADATA-X container whose children are "record" elements
        (Resource, Class, Field, etc.) — each record's children are
        leaf-text elements where tag=field name and text=value.
        """
        records = []
        seen_columns = []  # preserve order of first appearance
        for record_elem in elem:
            # Skip non-record children (rare — defensive)
            if len(record_elem) == 0:
                continue
            record = {}
            for field_elem in record_elem:
                tag = field_elem.tag
                text = field_elem.text or ""
                # Skip nested record-element fields (e.g., ValidationLookup
                # subtrees within Resource records)
                if len(field_elem) > 0:
                    continue
                if tag not in seen_columns:
                    seen_columns.append(tag)
                record[tag] = text.strip()
            records.append(record)

        # Build aligned rows
        rows = []
        for r in records:
            rows.append([r.get(col, "") for col in seen_columns])

        return {
            "tag":     elem.tag,
            "attrib":  dict(elem.attrib),
            "columns": seen_columns,
            "rows":    rows,
            "format":  "STANDARD-XML",
        }

    def _walk(elem):
        # Detect which format this element represents
        children_tags = [c.tag for c in elem]
        if "COLUMNS" in children_tags or "DATA" in children_tags:
            # COMPACT shape
            out["blocks"].append(_parse_compact_block(elem))
            return
        # STANDARD-XML shape: METADATA-X containers have child records
        # (Resource, Class, Field). Detect: tag name starts with METADATA-
        # AND first child has its own children (record-element pattern).
        if elem.tag.startswith("METADATA-") and len(elem) > 0:
            first_child = elem[0]
            if len(first_child) > 0:
                # This is a record-bearing METADATA-X container
                out["blocks"].append(_parse_standard_block(elem))
                return
        # Otherwise recurse — handles outer wrappers like <METADATA>,
        # <SYSTEM>, etc. that just nest deeper before reaching records.
        for child in elem:
            _walk(child)

    for child in root:
        _walk(child)

    return out


def metadata_to_records(blocks: list) -> list:
    """Convert raw column/row blocks into list-of-dict records for easy lookup."""
    records = []
    for block in blocks:
        cols = block.get("columns", [])
        for row in block.get("rows", []):
            rec = dict(zip(cols, row))
            rec["_block_tag"] = block["tag"]
            rec["_block_attrib"] = block["attrib"]
            records.append(rec)
    return records


def cmd_metadata(args, creds):
    """Pull system + resource + class + field metadata. Writes idx-cache/idx-metadata.json.

    Sequence:
      1. METADATA-SYSTEM            — top-level resource list
      2. METADATA-RESOURCE          — for each resource
      3. METADATA-CLASS             — classes available per resource
      4. METADATA-TABLE Property:*  — field definitions per (resource, class)
      5. (optional) METADATA-LOOKUP — enum value lookups per field

    Output:
      tools/idx-cache/idx-metadata.json — single consolidated dump
      tools/idx-cache/idx-metadata-summary.txt — human-readable summary
    """
    session, capabilities, server_info = rets_login(creds, verbose=args.verbose)

    print(f"NLAR RETS Metadata Pull")
    print(f"User: {creds['NLAR_RETS_USER']}")
    print(f"Server: {server_info['server']}")
    print(f"Schema timestamp: {capabilities.get('metadatatimestamp', '<unknown>')}")
    print(f"Schema version:   {capabilities.get('metadataversion', '<unknown>')}")
    print(f"")

    metadata_dump = {
        "fetched_at": _now_iso(),
        "server_info": server_info,
        "capabilities": capabilities,
        "metadata": {},
    }

    # 1. SYSTEM — what resources are available?
    print(f"[1/4] METADATA-SYSTEM ...")
    system_xml = fetch_metadata(session, capabilities, mtype="METADATA-SYSTEM",
                                 resource_id="*", verbose=args.verbose)
    system_parsed = parse_metadata_xml(system_xml)
    metadata_dump["metadata"]["SYSTEM"] = system_parsed
    print(f"      reply_code={system_parsed.get('reply_code')} "
          f"blocks={len(system_parsed.get('blocks', []))}")

    # 2. RESOURCE — full list of resources (Property, Member, Office, etc.)
    print(f"[2/4] METADATA-RESOURCE ...")
    resource_xml = fetch_metadata(session, capabilities, mtype="METADATA-RESOURCE",
                                   resource_id="0", verbose=args.verbose)
    resource_parsed = parse_metadata_xml(resource_xml)
    metadata_dump["metadata"]["RESOURCE"] = resource_parsed
    resources = metadata_to_records(resource_parsed.get("blocks", []))
    print(f"      {len(resources)} resources: "
          f"{', '.join(sorted({r.get('ResourceID', '?') for r in resources}))}")

    # 3. CLASS — classes per resource (typically Property has Residential,
    #    Commercial, Land, MultiFamily, etc.)
    print(f"[3/4] METADATA-CLASS ...")
    class_dump = {}
    for resource in sorted({r.get("ResourceID") for r in resources if r.get("ResourceID")}):
        try:
            class_xml = fetch_metadata(session, capabilities, mtype="METADATA-CLASS",
                                        resource_id=resource, verbose=args.verbose)
            class_parsed = parse_metadata_xml(class_xml)
            class_dump[resource] = class_parsed
            class_recs = metadata_to_records(class_parsed.get("blocks", []))
            class_names = sorted({c.get("ClassName", "?") for c in class_recs})
            print(f"      {resource:20s} → {len(class_recs)} classes: "
                  f"{', '.join(class_names)}")
        except SystemExit:
            print(f"      {resource}: GetMetadata failed (skipping)")
    metadata_dump["metadata"]["CLASS"] = class_dump

    # 4. TABLE (fields) — field definitions per (resource, class).
    #    For first run, focus on Property:* to understand the listing schema.
    print(f"[4/4] METADATA-TABLE Property:* (field definitions) ...")
    table_dump = {}
    property_classes = []
    if "Property" in class_dump:
        property_class_recs = metadata_to_records(
            class_dump["Property"].get("blocks", [])
        )
        property_classes = sorted({c.get("ClassName") for c in property_class_recs
                                    if c.get("ClassName")})
    for cls in property_classes:
        rid = f"Property:{cls}"
        try:
            table_xml = fetch_metadata(session, capabilities, mtype="METADATA-TABLE",
                                        resource_id=rid, verbose=args.verbose)
            table_parsed = parse_metadata_xml(table_xml)
            table_dump[rid] = table_parsed
            field_recs = metadata_to_records(table_parsed.get("blocks", []))
            field_names = sorted({f.get("SystemName") for f in field_recs
                                   if f.get("SystemName")})
            print(f"      Property:{cls:18s} → {len(field_recs)} fields")
            if args.verbose:
                # Print first 15 fields as sanity check
                preview = ", ".join(field_names[:15])
                print(f"           sample: {preview}{'...' if len(field_names)>15 else ''}")
        except SystemExit:
            print(f"      Property:{cls}: GetMetadata failed (skipping)")
    metadata_dump["metadata"]["TABLE"] = table_dump

    # Write the dump
    cache_dir = SCRIPT_DIR / "idx-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_json = cache_dir / "idx-metadata.json"
    out_summary = cache_dir / "idx-metadata-summary.txt"

    out_json.write_text(json.dumps(metadata_dump, indent=2, default=str),
                         encoding="utf-8")

    # Human-readable summary
    summary_lines = [
        "NLAR RETS Schema Summary",
        f"Fetched at:        {metadata_dump['fetched_at']}",
        f"Schema timestamp:  {capabilities.get('metadatatimestamp', '<unknown>')}",
        f"Schema version:    {capabilities.get('metadataversion', '<unknown>')}",
        "",
        "Resources:",
    ]
    for r in resources:
        summary_lines.append(f"  - {r.get('ResourceID', '?'):20s} "
                              f"{r.get('Description', '')}")
    summary_lines.append("")
    summary_lines.append("Property classes:")
    for cls in property_classes:
        rid = f"Property:{cls}"
        recs = metadata_to_records(table_dump.get(rid, {}).get("blocks", []))
        summary_lines.append(f"  - {cls:25s} ({len(recs)} fields)")
    out_summary.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    rets_logout(session, capabilities)

    print(f"")
    print(f"✓ Metadata pulled successfully")
    print(f"  Full dump:    {out_json.relative_to(SITE_ROOT)} "
          f"({out_json.stat().st_size:,} bytes)")
    print(f"  Summary:      {out_summary.relative_to(SITE_ROOT)}")
    return 0


# ─────────────────────────────────────────────────────────────────
#  SEARCH (Phase 2 — listing pull)
# ─────────────────────────────────────────────────────────────────

# DMQL2 query templates per pull type — VALIDATED 2026-05-07 against live
# NLAR Matrix server.
#
# Smoke test confirmed: single-value uses no pipe; pipe is only for
# multi-value OR-within-field. Status field uses single-letter codes
# in queries (A=Active, S=Sold, X=Expired, W=Withdrawn, STCAN=Cancelled).
# Response COMPACT-DECODED returns the long names (Status='Active') not codes.
DMQL_QUERIES = {
    # 2026-07-17: widened A → A,UC,STCOS (task-#57 port; Mike 2026-05-18 +
    # re-affirmed 2026-07-15: "Under contract should stay on the site") —
    # conditional listings render with the "Accepted Offer with Conditions"
    # badge instead of vanishing. Matches Gander/Avalon. STFRM is NOT pulled:
    # it returns zero rows from this feed (the 07-15 vocabulary dump: A/UC/S).
    "active":           "(Status=|A,UC,STCOS)",
    "active_incr":      "(Status=|A,UC,STCOS),(MatrixModifiedDT={since}+)",
    "sold_backfill":    "(Status=S)",  # NO date filter — all 22 years
    "sold_incr":        "(Status=S),(MatrixModifiedDT={since}+)",
    "expired_incr":     "(Status=|X,W,STCAN),(MatrixModifiedDT={since}+)",
    "photo_incr":       "(PhotoModificationTimestamp={since}+)",
}

# How far back the VOW lookback window goes for the consumer-facing cache.
# Per Mike's plan: 2-year rolling window for sold data ("drop a day, add a
# day to keep the 2-year limit"). The all-history cache (sold-listings-full.json)
# has no expiry.
VOW_LOOKBACK_DAYS = 730

# Matrix's max page size — confirmed 1000 in the wild. Server may cap at
# 5000 for some accounts; if you see "MaxRowsLimitExceeded" errors, drop
# this back to 500 and re-run.
SEARCH_PAGE_SIZE = 1000

# ─────────────────────────────────────────────────────────────────
#  RECORD PROJECTION — Matrix → IDX cache shape
# ─────────────────────────────────────────────────────────────────

# SAFE_FIELDS allowlist + NEVER_PROJECT denylist: shared fleet field list.
# Since 2026-10-09 (sites, D-1009-29) both sets live in tools/idx_fields.py,
# copied verbatim from Gander's idx-ingest.py so all three listing sites keep
# the same feed columns (Avalon kept 97 and Goose Bay 95 of Gander's 122, and
# denylisted PendingDate / Possession / SignYN). Edit the shared file, never a
# local copy here; tools/tests/idx-fields-parity-test.py pins the lists.
# No RETS Select is sent (fields="*"), so the lists filter columns
# client-side only and do not change the request.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from idx_fields import SAFE_FIELDS_ACTIVE, NEVER_PROJECT  # noqa: E402


def _is_truthy(val):
    """Matrix returns Booleans as '1'/'0' strings; empty = not set.

    Convention #21 defensive: missing values treated as False.
    """
    return str(val or "").strip() in ("1", "Y", "y", "true", "True", "TRUE")


def _passes_vow_filter(record):
    """Check VOW eligibility per CREA rule.

    Three Booleans must ALL be truthy for a listing to be displayable.
    Smoke-test note (2026-05-07): IDXOptInYN often empty on legitimate
    listings; the two Publish* fields are the real gates in practice.
    """
    return (_is_truthy(record.get("PublishToInternetSitesYN"))
            and _is_truthy(record.get("PublishToPublicSitesYN")))


def _passes_required_fields(record, *, sold=False):
    """Defensive layer (Convention #21 layer 4 cousin).

    Active listings need: MLSNumber, ListPrice (>0 OK to skip — render-time
        fallback says "Contact for price")
    Sold listings need:   MLSNumber, ClosePrice (>0), CloseDate
    """
    if not record.get("MLSNumber"):
        return False
    if sold:
        cp = str(record.get("ClosePrice", "")).strip()
        cd = str(record.get("CloseDate", "")).strip()
        try:
            if not cp or float(cp) <= 0:
                return False
        except (TypeError, ValueError):
            return False
        if not cd:
            return False
    return True


def _normalize_longitude(record):
    """Convention #21 layer 1: defensive longitude sign-flip correction.

    Some listings have positive Longitude (sign error — should be negative for
    Canada). Detected by: Longitude > 0. Correction: negate.
    """
    try:
        lng = float(record.get("Longitude", 0) or 0)
    except (TypeError, ValueError):
        return record
    if lng > 0:
        record = dict(record)
        record["Longitude"] = str(-lng)
    return record


def project_record(raw_record):
    """Project a Matrix record to the IDX cache shape.

    Applies SAFE_FIELDS allowlist + NEVER_PROJECT denylist + sign-flip
    correction. Returns dict ready to write to listings.json /
    sold-listings.json / sold-listings-full.json.

    Convention #21 defensive layers all live here:
    - Allowlist gates which fields ship at all
    - Denylist redacts even if accidentally added
    - Sign-flip correction for longitude
    """
    raw_record = _normalize_longitude(raw_record)
    return {
        k: v for k, v in raw_record.items()
        if k in SAFE_FIELDS_ACTIVE and k not in NEVER_PROJECT
    }


# ─────────────────────────────────────────────────────────────────
#  DUAL-CACHE WRITE — sold listings split by VOW window
# ─────────────────────────────────────────────────────────────────

def _load_cache(path):
    """Load a JSON cache as {mls: record} dict. Empty {} if missing.

    Cache files are stored as either a list (legacy shape) or
    {fetched_at, count, rows: [...]} envelope. Normalize to dict-by-MLS
    for O(1) upsert.
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"WARN: {path} is not valid JSON; treating as empty",
              file=sys.stderr)
        return {}
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("rows", [])
    else:
        rows = []
    return {r.get("MLSNumber"): r for r in rows if r.get("MLSNumber")}


def _save_cache(path, cache_dict, *, pull_type="unknown"):
    """Persist cache dict back to disk in the {fetched_at, count, rows: [...]}
    envelope shape that downstream tools expect.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "fetched_at": _now_iso(),
        "pull_type":  pull_type,
        "count":      len(cache_dict),
        "rows":       sorted(cache_dict.values(),
                              key=lambda r: r.get("MLSNumber", "")),
    }, indent=2, default=str), encoding="utf-8")


def _vow_cutoff_iso():
    """ISO date string for today minus VOW_LOOKBACK_DAYS."""
    from datetime import timedelta
    return (datetime.now(timezone.utc) -
            timedelta(days=VOW_LOOKBACK_DAYS)).strftime("%Y-%m-%d")


def _load_region_filter():
    """Load this site's canonical page-scope filter -- in_scope() from
    idx-project-to-ddf-shape.py -- so region-scoped counting below can
    never drift from what the projection step actually emits (Convention
    #148: derive, never hand-copy the region rules). Returns None on ANY
    failure (missing module, missing in_scope, or a smoke-test row that
    fails to classify as in-region) so the caller falls back to feed-wide
    counting -- a broken filter must never SUPPRESS a real deploy
    (Convention #74, 2026-08-24 region-scoped skip-gate)."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "idx_projection", SCRIPT_DIR / "idx-project-to-ddf-shape.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = mod.in_scope
        if fn({"PostalCode": "A2V 2T1"}) is not True:
            raise ValueError("in_scope smoke-test row did not classify as in-region")
        return fn
    except Exception as e:
        print(f"  WARN: region filter unavailable ({e}) -- "
              f"skip-gate counts feed-wide", file=sys.stderr)
        return None


def _in_region_change(new_row, old_row, in_scope):
    """True if EITHER side of a change is in-region (covers a listing
    moving into or out of a site's scope). Any per-row exception counts as
    in-region -- fail-open, Convention #74."""
    try:
        return bool((new_row and in_scope(new_row)) or (old_row and in_scope(old_row)))
    except Exception:
        return True


def upsert_active(record, cache):
    """Upsert a single active listing into the active cache.

    Defensive layers + VOW filter applied. Returns the listing's MLS
    number if upserted (still truthy, so `if upsert_active(...)` at
    every call site keeps working unchanged), or None if filtered out.
    The MLS is what lets the caller compare the new value against a
    prior snapshot to distinguish a genuine change from a re-fetch of
    identical content (2026-08-24 skip-gate fix).
    """
    if not _passes_required_fields(record):
        return None
    if not _passes_vow_filter(record):
        return None
    projected = project_record(record)
    mls = projected.get("MLSNumber")
    if not mls:
        return None
    cache[mls] = projected
    return mls


def upsert_sold(record, cache_full, cache_consumer, vow_cutoff):
    """Upsert a sold listing into BOTH caches.

    cache_full always gets the record (no expiry — drives market-stats
    aggregator over 22-year history).

    cache_consumer only gets it if CloseDate >= vow_cutoff (VOW 2-year
    rolling window — drives Sold Listing Search + Recently Sold widget).

    Returns dict {full: bool, consumer: bool} indicating whether each
    cache was written.
    """
    if not _passes_required_fields(record, sold=True):
        return {"full": False, "consumer": False}
    if not _passes_vow_filter(record):
        return {"full": False, "consumer": False}
    projected = project_record(record)
    mls = projected.get("MLSNumber")
    if not mls:
        return {"full": False, "consumer": False}

    # Always upsert to full cache
    cache_full[mls] = projected
    written = {"full": True, "consumer": False}

    # Conditionally upsert to consumer cache
    close_date = str(projected.get("CloseDate", "")).strip()
    if close_date and close_date >= vow_cutoff:
        cache_consumer[mls] = projected
        written["consumer"] = True

    return written


def expire_consumer_cache(cache_consumer, vow_cutoff):
    """Drop records from cache_consumer where CloseDate < vow_cutoff.

    The "drop a day" half of "drop a day, add a day." Operates in-place.
    Returns count dropped.
    """
    expired = [
        mls for mls, r in cache_consumer.items()
        if not r.get("CloseDate") or str(r["CloseDate"]).strip() < vow_cutoff
    ]
    for mls in expired:
        del cache_consumer[mls]
    return len(expired)


def search_paginated(session, capabilities, *, resource="Property",
                     class_name="ResidentialProperty", query="(MlsStatus=|Active)",
                     fields="*", limit_per_page=SEARCH_PAGE_SIZE,
                     verbose=False):
    """Issue paginated RETS Search calls against the given resource:class.

    Yields parsed-row dicts as they come in. Caller consumes via:
        for row in search_paginated(session, capabilities, ...):
            ...

    DMQL2 query examples:
        (MlsStatus=|Active)                              all active
        (MlsStatus=|Active),(City=Gander)                active in Gander
        (MlsStatus=|Closed),(CloseDate=2024-05-07+)      sold since 2024-05-07
        (PostalCode=A0J*)                                A0J postal range
    """
    url = capabilities.get("search")
    if not url:
        print("ERROR: no search capability URL", file=sys.stderr)
        sys.exit(1)

    offset = 1  # RETS is 1-indexed
    total_yielded = 0

    while True:
        params = {
            "SearchType": resource,
            "Class": class_name,
            "Query": query,
            "QueryType": "DMQL2",
            "Format": "COMPACT-DECODED",
            "Limit": str(limit_per_page),
            "Offset": str(offset),
            "Count": "1" if offset == 1 else "0",  # only count once
            "StandardNames": "0",  # use Matrix system names (validated against schema)
        }
        if fields and fields != "*":
            params["Select"] = fields

        if verbose:
            print(f"[search] GET {url} offset={offset} query={query[:80]}",
                  file=sys.stderr)

        try:
            r = session.get(url, params=params, timeout=120)
        except requests.RequestException as e:
            print(f"ERROR: Search request failed: {e}", file=sys.stderr)
            sys.exit(1)

        if r.status_code != 200:
            print(f"ERROR: Search HTTP {r.status_code}: {r.text[:300]}",
                  file=sys.stderr)
            sys.exit(1)

        # RETS Search response is XML wrapping COLUMNS + DATA tab-delimited blocks
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError as e:
            print(f"ERROR: Search XML parse failed: {e}", file=sys.stderr)
            print(f"Response (first 500 chars): {r.text[:500]}", file=sys.stderr)
            sys.exit(1)

        reply_code = root.get("ReplyCode")
        reply_text = root.get("ReplyText", "")

        # ReplyCode 20201 = "No Records Found" (clean end-of-pagination)
        if reply_code == "20201":
            if verbose:
                print(f"[search] reply 20201 (no records) — done", file=sys.stderr)
            return

        if reply_code not in ("0", None):
            print(f"ERROR: Search reply_code={reply_code} reply_text={reply_text!r}",
                  file=sys.stderr)
            sys.exit(1)

        columns = []
        page_rows = 0
        for child in root:
            if child.tag == "COLUMNS":
                columns = [c for c in (child.text or "").split("\t") if c]
            elif child.tag == "DATA":
                values = (child.text or "").split("\t")
                # Strip leading/trailing empty entries (Matrix sometimes wraps in tabs)
                if values and values[0] == "":
                    values = values[1:]
                if values and values[-1] == "":
                    values = values[:-1]
                row = dict(zip(columns, values))
                yield row
                page_rows += 1

        total_yielded += page_rows

        if verbose:
            print(f"[search] page yielded {page_rows} rows "
                  f"(total: {total_yielded})", file=sys.stderr)

        # If we got fewer than the page size, we're done
        if page_rows < limit_per_page:
            return

        # Server signals more results via MAXROWS element in some implementations,
        # but the safe approach is to advance offset until we get a short page
        offset += page_rows


def cmd_pull(args, creds):
    """Pull listings (active / sold / expired) → tools/idx-cache/*.json.

    Phase 2 — full dual-cache logic against validated NLAR Matrix schema.

    Modes (combined with --pull):
        --pull active                      : full active pull, replace cache
        --pull active --incremental        : daily upsert by MatrixModifiedDT
        --pull sold --backfill             : 22-year all-history one-shot
        --pull sold --incremental          : daily upsert + VOW expiry sweep
        --pull expired --incremental       : defensive expiry detection
        --pull all                         : active_incr + sold_incr + expired_incr

    Cache files written:
        tools/idx-cache/listings.json              (active, all displayable)
        tools/idx-cache/sold-listings.json         (sold, 2yr VOW window)
        tools/idx-cache/sold-listings-full.json    (sold, all 22 years)
        tools/idx-cache/expired-listings.json      (defensive — orphan detection)
    """
    cache_dir = SCRIPT_DIR / "idx-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # ─── Rooms pull — separate RETS resource (PropertySubTable:Room) ────
    # Convention #15 propagation from realestategander-site canonical at
    # Client Full parity ship 2026-05-11. See Gander generator + design
    # spec for full rationale. Output: tools/idx-cache/rooms-listings.json
    # keyed by Listing_MUI. Convention #74 fail-safe: missing/empty cache
    # = no rooms section render (silent).
    if args.pull == "rooms":
        session, capabilities, server_info = rets_login(creds, verbose=args.verbose)
        print(f"Login OK")
        print(f"")
        print(f"=== rooms ===")
        rooms_query = "(MatrixModifiedDT=2000-01-01T00:00:00+)"
        print(f"  resource: PropertySubTable:Room")
        print(f"  query: {rooms_query}")
        all_rooms = []
        try:
            for row in search_paginated(session, capabilities,
                                         resource="PropertySubTable",
                                         class_name="Room",
                                         query=rooms_query,
                                         verbose=args.verbose):
                all_rooms.append(row)
        except SystemExit:
            print(f"  ✗ Rooms search failed", file=sys.stderr)
            rets_logout(session, capabilities)
            return 1

        print(f"  fetched: {len(all_rooms):,} room records from server")
        if all_rooms:
            sample = all_rooms[0]
            print(f"  first-record keys ({len(sample)}): {sorted(sample.keys())}")
            print(f"  first-record sample: {dict(list(sample.items())[:10])}")

        by_mui = {}
        for r in all_rooms:
            mui = (r.get("MUI") or r.get("Matrix_Unique_ID")
                   or r.get("Listing_MUI") or r.get("ListingMUI")
                   or r.get("Property_MUI") or r.get("PropertyMUI")
                   or r.get("Parent_MUI") or r.get("ParentMUI")
                   or r.get("Listing_Key") or r.get("ListingKey")
                   or r.get("MLSNumber"))
            if not mui:
                continue
            by_mui.setdefault(str(mui), []).append({
                "floor":  r.get("RoomLevel") or r.get("Floor") or r.get("FloorName") or r.get("Level") or "",
                "room":   r.get("RoomType") or r.get("RoomName") or r.get("Room") or r.get("Type") or "",
                "length": r.get("RoomLength") or r.get("Length") or "",
                "width":  r.get("RoomWidth") or r.get("Width") or "",
                "size":   r.get("RoomSize") or r.get("Dimensions") or r.get("RoomDimensions") or "",
                "order":  r.get("InputEntryOrder") or r.get("Order") or r.get("RoomOrder") or r.get("Display_Order") or "",
            })

        rooms_path = cache_dir / "rooms-listings.json"
        rooms_path.write_text(json.dumps({
            "fetched_at": _now_iso(),
            "pull_type":  "rooms",
            "room_count": len(all_rooms),
            "listing_count": len(by_mui),
            "by_mui":     by_mui,
        }, indent=2, default=str), encoding="utf-8")

        print(f"  cache: {len(all_rooms):,} rooms grouped into "
              f"{len(by_mui):,} listings")
        print(f"  written: {rooms_path.relative_to(SITE_ROOT)} "
              f"({rooms_path.stat().st_size:,} bytes)")
        rets_logout(session, capabilities)
        print(f"")
        print(f"✓ Rooms pull complete.")
        if args.json:
            print(json.dumps({
                "rooms_fetched": len(all_rooms),
                "listings_with_rooms": len(by_mui),
            }, indent=2))
        return 0

    # Determine which pull operations to run
    pull_ops = []
    if args.pull == "all":
        pull_ops = ["active_incr", "sold_incr", "expired_incr"]
    elif args.pull == "active":
        pull_ops = ["active_incr" if args.incremental else "active"]
    elif args.pull == "sold":
        if args.backfill:
            pull_ops = ["sold_backfill"]
        elif args.incremental:
            pull_ops = ["sold_incr"]
        else:
            print("ERROR: --pull sold requires --backfill OR --incremental",
                  file=sys.stderr)
            return 2
    elif args.pull == "expired":
        pull_ops = ["expired_incr"]
    elif args.pull == "audit":
        pull_ops = ["sold_audit"]

    # Compute incremental "since" timestamp
    from datetime import timedelta
    since_dt = datetime.now(timezone.utc) - timedelta(days=1)
    since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%S")

    session, capabilities, server_info = rets_login(creds, verbose=args.verbose)
    print(f"Login OK")
    print(f"")

    summary = {"fetched_at": _now_iso(), "results": {}}

    for op in pull_ops:
        # Resolve query template
        if op == "sold_audit":
            # Audit = re-run backfill, save to shadow file for diff
            query_key = "sold_backfill"
        else:
            query_key = op
        query = DMQL_QUERIES[query_key].format(since=since_iso)

        print(f"=== {op} ===")
        print(f"  query: {query}")

        # Pull rows
        rows = []
        try:
            for row in search_paginated(session, capabilities,
                                         resource="Property",
                                         class_name="Listing",
                                         query=query,
                                         verbose=args.verbose):
                rows.append(row)
        except SystemExit:
            print(f"  ✗ Search failed for {op}", file=sys.stderr)
            continue

        print(f"  fetched: {len(rows)} rows from server")

        # Apply per-op cache logic
        if op in ("active", "active_incr"):
            # 2026-08-24: content-aware counting -- the skip-regen gate reads
            # `upserted` and only skips a cycle when it is 0. Before this fix
            # every row that survived the VOW/required-field filter counted
            # as "upserted" regardless of whether its content actually
            # changed since the prior pull -- so on a full (`active`) pull
            # `upserted` was always ~= the whole feed size, the gate never
            # skipped, and every 15-min cycle regenerated + committed +
            # deployed. `prev` is the pre-pull snapshot; a row only counts
            # as upserted when its projected content differs from `prev`.
            # `removed` (op=="active" only -- a full pull can see a listing
            # vanish; an incremental pull structurally cannot, since it only
            # ever touches rows the feed says were modified) is a genuine
            # change too (a delisting) and must also trigger a regen.
            cache_path = cache_dir / "listings.json"
            prev = _load_cache(cache_path)
            cache = {} if op == "active" else dict(prev)
            upserted, unchanged, skipped = 0, 0, 0
            upserted_in_region, removed_in_region = 0, 0
            region_fn = _load_region_filter()
            for r in rows:
                mls = upsert_active(r, cache)
                if mls is None:
                    skipped += 1
                elif cache[mls] != prev.get(mls):
                    upserted += 1
                    if region_fn is not None and _in_region_change(
                            cache[mls], prev.get(mls), region_fn):
                        upserted_in_region += 1
                else:
                    unchanged += 1
            removed = [m for m in prev if m not in cache] if op == "active" else []
            if region_fn is not None:
                removed_in_region = sum(
                    1 for m in removed
                    if _in_region_change(None, prev[m], region_fn))
            _save_cache(cache_path, cache, pull_type=op)
            region_note = (f" in_region={upserted_in_region}/{removed_in_region}"
                           if region_fn is not None else " in_region=unavailable")
            print(f"  cache: upserted={upserted} unchanged={unchanged} "
                  f"removed={len(removed)} skipped={skipped}{region_note} "
                  f"(VOW/required-field filter)")
            print(f"  total in cache: {len(cache)} active listings")
            print(f"  written: {cache_path.relative_to(SITE_ROOT)} "
                  f"({cache_path.stat().st_size:,} bytes)")
            summary["results"][op] = {
                "fetched": len(rows), "upserted": upserted,
                "unchanged": unchanged, "removed": len(removed),
                "skipped": skipped, "total_in_cache": len(cache),
            }
            if region_fn is not None:
                summary["results"][op]["upserted_in_region"] = upserted_in_region
                summary["results"][op]["removed_in_region"] = removed_in_region

        elif op in ("sold_backfill", "sold_incr"):
            cache_full_path = cache_dir / "sold-listings-full.json"
            cache_consumer_path = cache_dir / "sold-listings.json"

            if op == "sold_backfill":
                # Replace caches entirely
                cache_full = {}
                cache_consumer = {}
            else:
                # Upsert into existing
                cache_full = _load_cache(cache_full_path)
                cache_consumer = _load_cache(cache_consumer_path)

            vow_cutoff = _vow_cutoff_iso()
            upserted_full, upserted_consumer, skipped = 0, 0, 0
            for r in rows:
                result = upsert_sold(r, cache_full, cache_consumer, vow_cutoff)
                if result["full"]:
                    upserted_full += 1
                else:
                    skipped += 1
                if result["consumer"]:
                    upserted_consumer += 1

            # Apply VOW expiry to consumer cache (the "drop a day" pass)
            expired = expire_consumer_cache(cache_consumer, vow_cutoff)

            _save_cache(cache_full_path, cache_full, pull_type=op + "_full")
            _save_cache(cache_consumer_path, cache_consumer,
                         pull_type=op + "_consumer")

            print(f"  cache full:     upserted={upserted_full} skipped={skipped}")
            print(f"  cache consumer: upserted={upserted_consumer} expired={expired}")
            print(f"  total full:     {len(cache_full)} sold listings (22yr history)")
            print(f"  total consumer: {len(cache_consumer)} sold listings (2yr VOW window)")
            print(f"  written: {cache_full_path.relative_to(SITE_ROOT)} "
                  f"({cache_full_path.stat().st_size:,} bytes)")
            print(f"           {cache_consumer_path.relative_to(SITE_ROOT)} "
                  f"({cache_consumer_path.stat().st_size:,} bytes)")
            summary["results"][op] = {
                "fetched": len(rows),
                "upserted_full": upserted_full,
                "upserted_consumer": upserted_consumer,
                "expired_consumer": expired,
                "total_full": len(cache_full),
                "total_consumer": len(cache_consumer),
            }

        elif op == "expired_incr":
            cache_path = cache_dir / "expired-listings.json"
            cache = _load_cache(cache_path)
            upserted = 0
            for r in rows:
                projected = project_record(r)
                mls = projected.get("MLSNumber")
                if mls:
                    cache[mls] = projected
                    upserted += 1
            _save_cache(cache_path, cache, pull_type=op)
            print(f"  upserted={upserted} total_in_cache={len(cache)}")
            print(f"  written: {cache_path.relative_to(SITE_ROOT)}")
            summary["results"][op] = {
                "fetched": len(rows), "upserted": upserted,
                "total_in_cache": len(cache),
            }

        elif op == "sold_audit":
            # Audit = full re-pull, write to shadow file, diff against
            # incremental cache, surface drift
            shadow_path = cache_dir / "sold-listings-full.json.audit-shadow"
            shadow_cache = {}
            for r in rows:
                projected = project_record(r)
                mls = projected.get("MLSNumber")
                if mls:
                    shadow_cache[mls] = projected
            _save_cache(shadow_path, shadow_cache, pull_type="audit")

            existing_path = cache_dir / "sold-listings-full.json"
            existing_cache = _load_cache(existing_path)

            shadow_keys = set(shadow_cache.keys())
            existing_keys = set(existing_cache.keys())

            in_shadow_not_existing = shadow_keys - existing_keys
            in_existing_not_shadow = existing_keys - shadow_keys

            print(f"  audit comparison:")
            print(f"    shadow (fresh full pull):     {len(shadow_cache)} records")
            print(f"    existing (incremental cache): {len(existing_cache)} records")
            print(f"    missing from existing (shadow has, existing doesn't): "
                  f"{len(in_shadow_not_existing)}")
            print(f"    extra in existing (existing has, shadow doesn't): "
                  f"{len(in_existing_not_shadow)}")
            drift_pct = (len(in_shadow_not_existing) + len(in_existing_not_shadow)) \
                        / max(len(shadow_cache), 1) * 100
            print(f"    drift: {drift_pct:.2f}%")
            if drift_pct > 2.0:
                print(f"    ⚠ drift > 2% — investigate (Convention #18 silent-degraded gate)")
            summary["results"][op] = {
                "shadow_count": len(shadow_cache),
                "existing_count": len(existing_cache),
                "missing_from_existing": len(in_shadow_not_existing),
                "extra_in_existing": len(in_existing_not_shadow),
                "drift_pct": drift_pct,
            }

        print(f"")

    # Convention #74 — always write structured stats for skip-regen gate
    # Workflow reads this to decide whether to run expensive regen
    try:
        stats_path = cache_dir / "last-pull-stats.json"
        stats_path.write_text(json.dumps(summary, indent=2, default=str))
        print(f"  wrote stats: {stats_path.relative_to(SITE_ROOT)}")
    except Exception as e:
        # Fail-safe: don't break the pipeline if stats write fails
        print(f"  WARN: stats write failed: {e}", file=sys.stderr)

    rets_logout(session, capabilities)

    print(f"✓ Pull complete.")
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("--probe", action="store_true",
                    help="Verify login + capability discovery only. No search.")
    ap.add_argument("--metadata", action="store_true",
                    help="Pull system metadata (resources + classes + fields).")
    ap.add_argument("--pull", choices=["active", "sold", "expired", "all", "audit", "rooms"],
                    help="Pull listings of the given type into tools/idx-cache/. "
                         "'rooms' pulls PropertySubTable:Room (per-listing room-by-room "
                         "dimensions, joined into listings by Listing_MUI in the generator).")
    ap.add_argument("--backfill", action="store_true",
                    help="(With --pull sold) one-shot backfill of all-history "
                         "sold cache. Replaces caches entirely.")
    ap.add_argument("--incremental", action="store_true",
                    help="(With --pull active|sold|expired) daily upsert by "
                         "MatrixModifiedDT. Default for --pull all.")
    ap.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON summary.")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="Verbose request/response logging (credentials redacted).")
    args = ap.parse_args(argv)

    if not any([args.probe, args.metadata, args.pull]):
        ap.print_help()
        return 2

    creds = load_credentials()

    if args.probe:
        return cmd_probe(args, creds)
    if args.metadata:
        return cmd_metadata(args, creds)
    if args.pull:
        return cmd_pull(args, creds)


if __name__ == "__main__":
    sys.exit(main())
