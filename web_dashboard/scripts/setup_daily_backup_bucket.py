#!/usr/bin/env python3
"""One-time setup: create the private Supabase Storage bucket used by the
``daily_critical_data_backup_job`` scheduler job.

Why this exists
---------------
The Supabase MCP available to the agent in this repo does **not** expose
storage administration tools (no ``list_storage_buckets`` /
``create_storage_bucket`` in the MCP tool surface). Buckets therefore have to
be created either:

1. Manually in the Supabase Dashboard
   (Storage -> Create bucket -> name=``daily-backups``, public=off), or
2. By running this script once with the service-role key.

Operator usage (Windows / PowerShell)
-------------------------------------
Run **once** after deploy, with the production environment loaded::

    .\\venv\\Scripts\\activate
    $env:SUPABASE_URL = "<prod URL>"
    $env:SUPABASE_SECRET_KEY = "<service-role key>"
    python web_dashboard\\scripts\\setup_daily_backup_bucket.py

It is **idempotent**: re-running after the bucket exists is a no-op that
simply prints a confirmation. Safe to run from CI or by hand.

What the daily backup job writes here
-------------------------------------
* ``daily/<YYYY-MM-DD>/trade_log/<fund_slug>_trades.csv`` — per-fund trade history
* ``daily/<YYYY-MM-DD>/tables/<table>.csv`` — per-table snapshots of
  ``user_profiles``, ``user_funds``, ``funds``, ``fund_thesis``,
  ``fund_thesis_pillars``, ``fund_contributions``, ``system_settings``,
  ``watched_tickers_v2``, ``ai_analysis_skip_list``, ``contributors``,
  ``contributor_access``.

The bucket is created **private** (``public=False``). The scheduled job uses
the service-role key, which bypasses RLS. Public read access is intentionally
NOT granted -- trade history and fund/contributor data are sensitive.

Bucket configuration
--------------------
* Bucket name:        ``daily-backups``
* Public read:        ``False``
* File size limit:    ``None`` (server default)
* Allowed mime types: ``None`` (server default; the job uploads ``text/csv``
                       but the bucket is not locked to that so future jobs
                       could reuse it for ``.parquet`` / compressed snapshots
                       without re-running this script).

Exit codes
----------
* ``0``  bucket exists at end of run (created or pre-existing)
* ``1``  required env vars missing
* ``2``  unexpected error while creating bucket
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure web_dashboard is importable so we can reuse SupabaseClient.
_HERE = Path(__file__).resolve().parent
_WEB_DASHBOARD = _HERE.parent
if str(_WEB_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(_WEB_DASHBOARD))

BUCKET_NAME = "daily-backups"


def main() -> int:
    if not os.getenv("SUPABASE_URL"):
        print("ERROR: SUPABASE_URL must be set in the environment", file=sys.stderr)
        return 1
    if not (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")):
        print(
            "ERROR: SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY) must be "
            "set; bucket creation requires the service-role key",
            file=sys.stderr,
        )
        return 1

    from supabase_client import SupabaseClient

    client = SupabaseClient(use_service_role=True).supabase

    try:
        existing = client.storage.list_buckets()
    except Exception as exc:
        print(f"ERROR: storage.list_buckets() failed: {exc}", file=sys.stderr)
        return 2

    def _bucket_name(item: object) -> str:
        if isinstance(item, dict):
            return str(item.get("name") or item.get("id") or "")
        return str(getattr(item, "name", "") or getattr(item, "id", "") or "")

    existing_names = {_bucket_name(b) for b in (existing or [])}

    if BUCKET_NAME in existing_names:
        print(f"OK: bucket '{BUCKET_NAME}' already exists (no action needed)")
        return 0

    try:
        client.storage.create_bucket(
            BUCKET_NAME,
            options={"public": False},
        )
    except Exception as exc:
        message = str(exc).lower()
        if "already exists" in message or "duplicate" in message:
            print(f"OK: bucket '{BUCKET_NAME}' already exists (per server)")
            return 0
        print(f"ERROR: failed to create bucket '{BUCKET_NAME}': {exc}", file=sys.stderr)
        return 2

    print(f"OK: created private bucket '{BUCKET_NAME}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
