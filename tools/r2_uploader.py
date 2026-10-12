#!/usr/bin/env python3
"""
Cloudflare R2 photo uploader — shared S3-compatible client wrapper.

Single source of truth for R2 PUTs across:
    - tools/idx-photo-sync.py     (active listing photos)
    - tools/idx-sold-photo-sync.py (sold listing photos)
    - tools/r2_bulk_upload_existing.py (one-time migration)

Reads 5 env vars (all required for R2 mode; absence = R2 disabled):
    R2_ACCOUNT_ID       — Cloudflare account ID (10-char hex)
    R2_ACCESS_KEY_ID    — R2 API token access key
    R2_SECRET_ACCESS_KEY — R2 API token secret key
    R2_BUCKET_NAME      — bucket name (e.g. turner-realty-photos)
    R2_BASE_URL         — public URL prefix (e.g. https://photos.turnerrealty.ca)

The KILL SWITCH is R2_BUCKET_NAME: when unset, is_r2_enabled() returns False
and callers fall back to disk-write (Convention #74 fail-safe). This makes
per-site cutover atomic — set the secret, R2 mode activates.

Design spec: realestategander-site/_research/Cloudflare_R2_Migration_Design_Spec_2026-05-21.md
Convention #15 candidate: this module should propagate byte-symmetric to
Avalon + Goosebay tools/ directories before their cutover.

Convention #74: every public function returns a clean fail-safe shape;
no raised exceptions reach the caller. Callers check .ok / .error.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ══════════════════════════════════════════════════════════════════
#  ENVIRONMENT
# ══════════════════════════════════════════════════════════════════

_ENV = {
    "account_id": os.environ.get("R2_ACCOUNT_ID", "").strip(),
    "access_key": os.environ.get("R2_ACCESS_KEY_ID", "").strip(),
    "secret_key": os.environ.get("R2_SECRET_ACCESS_KEY", "").strip(),
    "bucket":     os.environ.get("R2_BUCKET_NAME", "").strip(),
    "base_url":   os.environ.get("R2_BASE_URL", "").strip().rstrip("/"),
}


def is_r2_enabled() -> bool:
    """Return True if all required R2 env vars are set (kill-switch check).

    The kill switch is R2_BUCKET_NAME — when unset, R2 mode is disabled and
    callers should fall back to disk-write. Convention #74 fail-safe entry
    point: this is the single check every photo-write site should branch on.
    """
    return bool(
        _ENV["bucket"]
        and _ENV["account_id"]
        and _ENV["access_key"]
        and _ENV["secret_key"]
    )


def get_base_url() -> str:
    """Return the public URL prefix for emitting consumer-facing photo URLs.

    Falls back to a Cloudflare r2.dev URL pattern if R2_BASE_URL is unset but
    bucket + account are configured (useful for Phase 1 before custom domain
    DNS cuts over). Returns empty string if R2 is fully disabled.
    """
    if _ENV["base_url"]:
        return _ENV["base_url"]
    if _ENV["account_id"] and _ENV["bucket"]:
        # Cloudflare's default public URL pattern when no custom domain set.
        # Format: https://pub-<random>.r2.dev — Mike configures this in the
        # Cloudflare dashboard if using the default URL. Documenting the
        # PATTERN here; the actual subdomain comes from R2_BASE_URL.
        return ""  # require explicit R2_BASE_URL — no guessing
    return ""


def get_bucket_name() -> str:
    return _ENV["bucket"]


# ══════════════════════════════════════════════════════════════════
#  CLIENT — lazy boto3 init
# ══════════════════════════════════════════════════════════════════

_client_singleton = None
_client_init_error: Optional[str] = None


def _get_client():
    """Lazily initialize a boto3 S3 client targeting Cloudflare R2.

    Returns (client, error_msg). On any failure (missing env, boto3 not
    installed, network DNS error during init) returns (None, error_msg)
    instead of raising — caller decides fallback behavior.
    """
    global _client_singleton, _client_init_error
    if _client_singleton is not None:
        return _client_singleton, None
    if _client_init_error is not None:
        return None, _client_init_error
    if not is_r2_enabled():
        _client_init_error = "R2 env vars not set (R2_BUCKET_NAME is kill switch)"
        return None, _client_init_error
    try:
        import boto3  # type: ignore
        from botocore.config import Config  # type: ignore
    except ImportError as e:
        _client_init_error = f"boto3 not installed: {e}. Run: pip install --user boto3"
        return None, _client_init_error
    try:
        endpoint = f"https://{_ENV['account_id']}.r2.cloudflarestorage.com"
        _client_singleton = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=_ENV["access_key"],
            aws_secret_access_key=_ENV["secret_key"],
            region_name="auto",  # R2 ignores region but boto3 requires a value
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=10,
                read_timeout=30,
            ),
        )
        return _client_singleton, None
    except Exception as e:
        _client_init_error = f"R2 client init failed: {e}"
        return None, _client_init_error


# ══════════════════════════════════════════════════════════════════
#  RESULT SHAPE — Convention #74 fail-safe
# ══════════════════════════════════════════════════════════════════

@dataclass
class R2Result:
    """Outcome of an R2 operation. Callers branch on .ok."""
    ok: bool
    key: str = ""
    bytes_uploaded: int = 0
    error: str = ""
    already_exists: bool = False  # True when head_object found a match — no PUT performed


# ══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════

def head_object(key: str) -> R2Result:
    """Check if an object exists at `key` without downloading.

    Used for idempotent upload skip. Returns .ok=True if object exists,
    .ok=False if 404 OR if R2 is disabled OR if any error.
    """
    client, err = _get_client()
    if err:
        return R2Result(ok=False, key=key, error=err)
    try:
        resp = client.head_object(Bucket=_ENV["bucket"], Key=key)
        return R2Result(
            ok=True,
            key=key,
            bytes_uploaded=resp.get("ContentLength", 0),
            already_exists=True,
        )
    except Exception as e:
        # 404 raises ClientError with Code "404" — that's the "doesn't exist"
        # signal we want to surface as ok=False without alarm. Other exceptions
        # (auth fail, network) also surface as ok=False but with .error set.
        msg = str(e)
        is_404 = "404" in msg or "Not Found" in msg or "NoSuchKey" in msg
        return R2Result(
            ok=False,
            key=key,
            error="" if is_404 else msg,
            already_exists=False,
        )


def upload_bytes(
    data: bytes,
    key: str,
    *,
    content_type: str = "image/jpeg",
    cache_control: str = "public, max-age=31536000, immutable",
    skip_if_exists: bool = True,
) -> R2Result:
    """Upload bytes to R2 at `key`. Returns R2Result.

    Default cache_control is the immutable 1-year policy for content-addressed
    numbered photos (001.jpg ... NNN.jpg). Override to
    'public, max-age=86400, must-revalidate' for hero.jpg or other revisable
    artifacts.

    skip_if_exists=True (default) calls head_object first; skips PUT if found.
    Set to False to force overwrite (used by --force mode in sync scripts).
    """
    if not data:
        return R2Result(ok=False, key=key, error="empty bytes")

    if skip_if_exists:
        head = head_object(key)
        if head.already_exists:
            return R2Result(
                ok=True,
                key=key,
                bytes_uploaded=0,
                already_exists=True,
            )

    client, err = _get_client()
    if err:
        return R2Result(ok=False, key=key, error=err)

    try:
        client.put_object(
            Bucket=_ENV["bucket"],
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl=cache_control,
        )
        return R2Result(ok=True, key=key, bytes_uploaded=len(data))
    except Exception as e:
        return R2Result(ok=False, key=key, error=str(e))


def upload_file(
    local_path: Path,
    key: str,
    *,
    content_type: str = "image/jpeg",
    cache_control: str = "public, max-age=31536000, immutable",
    skip_if_exists: bool = True,
) -> R2Result:
    """Upload a file on disk to R2. Wrapper around upload_bytes."""
    if not local_path.exists():
        return R2Result(ok=False, key=key, error=f"file not found: {local_path}")
    try:
        data = local_path.read_bytes()
    except Exception as e:
        return R2Result(ok=False, key=key, error=f"read failed: {e}")
    return upload_bytes(
        data,
        key,
        content_type=content_type,
        cache_control=cache_control,
        skip_if_exists=skip_if_exists,
    )


def delete_object(key: str) -> R2Result:
    """Delete an object from R2. Used by idx-photo-cleanup.py for VOW expiry."""
    client, err = _get_client()
    if err:
        return R2Result(ok=False, key=key, error=err)
    try:
        client.delete_object(Bucket=_ENV["bucket"], Key=key)
        return R2Result(ok=True, key=key)
    except Exception as e:
        return R2Result(ok=False, key=key, error=str(e))


def build_public_url(key: str) -> str:
    """Construct the public consumer-facing URL for an R2 key.

    Returns empty string if R2_BASE_URL is unset (callers should detect this
    and emit local-path fallback instead).
    """
    base = get_base_url()
    if not base:
        return ""
    return f"{base}/{key.lstrip('/')}"


def build_key(site_slug: str, photo_path: str) -> str:
    """Construct the canonical R2 key from site + photo path.

    Examples:
        build_key("gander",   "listings/1296426/001.jpg")
            → "gander/listings/1296426/001.jpg"
        build_key("avalon",   "listings-sold/1226254/001.jpg")
            → "avalon/listings-sold/1226254/001.jpg"
        build_key("goosebay", "listings/1297136/hero.jpg")
            → "goosebay/listings/1297136/hero.jpg"

    The site_slug is the per-site prefix (Decision A — single fleet bucket
    with site-prefix scheme). Callers derive site_slug at script init.
    """
    slug = site_slug.strip().strip("/").lower()
    path = photo_path.strip().strip("/")
    return f"{slug}/{path}"


# ══════════════════════════════════════════════════════════════════
#  HEALTH CHECK — used by --probe mode in sync scripts
# ══════════════════════════════════════════════════════════════════

def health_check() -> R2Result:
    """Verify R2 connectivity + bucket access. Returns R2Result.

    Performs a head_bucket call (lightweight, doesn't list contents).
    Used by sync scripts in --probe mode and by Mike-action setup
    verification. Convention #79: verify against authoritative source.
    """
    if not is_r2_enabled():
        return R2Result(
            ok=False,
            error="R2 not enabled (R2_BUCKET_NAME unset — kill switch off)",
        )
    client, err = _get_client()
    if err:
        return R2Result(ok=False, error=err)
    try:
        client.head_bucket(Bucket=_ENV["bucket"])
        return R2Result(
            ok=True,
            key=_ENV["bucket"],
        )
    except Exception as e:
        return R2Result(ok=False, key=_ENV["bucket"], error=str(e))


# ══════════════════════════════════════════════════════════════════
#  CLI — direct invocation for manual testing
# ══════════════════════════════════════════════════════════════════

def _main_cli() -> int:
    """Allow `python3 tools/r2_uploader.py <subcommand>` for manual testing.

    Subcommands:
        probe                 — health check (verify creds + bucket access)
        head <key>            — check if a key exists
        put <local> <key>     — upload a file
        get <key>             — print the public URL for a key
        delete <key>          — delete an object
    """
    import argparse
    ap = argparse.ArgumentParser(description="Cloudflare R2 uploader (manual CLI)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="Verify R2 connectivity + creds")

    p_head = sub.add_parser("head", help="Check if a key exists")
    p_head.add_argument("key")

    p_put = sub.add_parser("put", help="Upload a local file")
    p_put.add_argument("local")
    p_put.add_argument("key")
    p_put.add_argument("--force", action="store_true",
                       help="Overwrite even if key already exists")

    p_get = sub.add_parser("get", help="Print the public URL for a key")
    p_get.add_argument("key")

    p_del = sub.add_parser("delete", help="Delete an object")
    p_del.add_argument("key")

    args = ap.parse_args()

    if args.cmd == "probe":
        r = health_check()
        print(f"[probe] ok={r.ok} bucket={r.key} err={r.error}")
        return 0 if r.ok else 1
    if args.cmd == "head":
        r = head_object(args.key)
        print(f"[head] {args.key} exists={r.already_exists} ok={r.ok} err={r.error}")
        return 0 if r.ok else 2
    if args.cmd == "put":
        r = upload_file(
            Path(args.local).resolve(),
            args.key,
            skip_if_exists=not args.force,
        )
        print(f"[put] {args.key} ok={r.ok} bytes={r.bytes_uploaded} already={r.already_exists} err={r.error}")
        return 0 if r.ok else 1
    if args.cmd == "get":
        url = build_public_url(args.key)
        if url:
            print(url)
            return 0
        print("[get] R2_BASE_URL not set", file=sys.stderr)
        return 1
    if args.cmd == "delete":
        r = delete_object(args.key)
        print(f"[delete] {args.key} ok={r.ok} err={r.error}")
        return 0 if r.ok else 1
    return 2


if __name__ == "__main__":
    sys.exit(_main_cli())
