#!/usr/bin/env python3
"""Restore a single table from a ``daily-backups`` snapshot.

Companion to ``web_dashboard/scheduler/jobs_daily_backup.py``. This script is
the **only** supported restore path; the daily backup job itself is write-only.

============================================================================
                          DANGER — READ THIS FIRST
============================================================================
This is a one-environment project. The only Supabase project the codebase
talks to IS production. There is no staging copy. A bad restore destroys
real user/fund/thesis/contribution data with no undo.

Defaults are deliberately paranoid:

* Default mode is **dry-run**. You must pass ``--apply`` to actually write.
* You must pass ``--confirm-restore PROD`` AS WELL. Both are required.
* Restore is **table-at-a-time**. There is no "restore everything" verb.
* Restore is **source-at-a-time**. You pick host or storage explicitly.
* Default strategy is ``upsert`` (idempotent on the table's primary key).
  ``--strategy truncate-and-replace`` deletes existing rows first and is
  gated behind a third confirmation flag (``--allow-truncate``).
* No flag combination skips the diff preview.

============================================================================
                              QUICK REFERENCE
============================================================================

# 1. List available snapshots (read-only):
python web_dashboard/scripts/restore_daily_backup.py --list-snapshots --source storage
python web_dashboard/scripts/restore_daily_backup.py --list-snapshots --source host

# 2. Preview a restore (read-only — no DB writes, just diff against current):
python web_dashboard/scripts/restore_daily_backup.py \\
    --table funds --date 2026-05-24 --source storage

# 3. Apply an upsert restore (idempotent, keyed on PK; no row deletion):
python web_dashboard/scripts/restore_daily_backup.py \\
    --table funds --date 2026-05-24 --source storage \\
    --apply --confirm-restore PROD

# 4. Apply a truncate-and-replace restore (DESTRUCTIVE — deletes rows
#    that exist in prod but not in the snapshot):
python web_dashboard/scripts/restore_daily_backup.py \\
    --table funds --date 2026-05-24 --source storage \\
    --apply --confirm-restore PROD \\
    --strategy truncate-and-replace --allow-truncate

============================================================================
                          OPERATIONAL NOTES
============================================================================
* Restoring ``trade_log`` is NOT supported by this script. Trade log
  snapshots are per-fund CSVs and the table is the system of record for
  cash balances / positions / dividends — restoring it would require
  matching repository updates and is outside the scope of an automated
  recovery tool. If you need to recover a trade log, use the snapshot CSV
  for evidence and re-enter the trades manually through the admin UI.
* ``user_profiles.id`` and ``user_funds.user_id`` are foreign keys to
  Supabase Auth users. This script will *not* recreate auth users; it only
  upserts the public-schema rows. If a user was deleted from auth.users,
  the upsert will fail and the script will report it.
* Empty-table snapshots (0-byte CSVs) cannot be safely used to restore a
  truncate-and-replace because we have no way to distinguish "the table
  was empty" from "we lost the column metadata". The script refuses to
  proceed in that case unless you also pass ``--allow-empty-snapshot``.
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Bootstrap so we can reuse SupabaseClient and the daily-backup constants.
# --------------------------------------------------------------------------- #

_HERE = Path(__file__).resolve().parent
_WEB_DASHBOARD = _HERE.parent
_PROJECT_ROOT = _WEB_DASHBOARD.parent
for _candidate in (str(_PROJECT_ROOT), str(_WEB_DASHBOARD)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Whitelist + primary keys.
#
# IMPORTANT: keep this in sync with CRITICAL_APP_TABLES in
# web_dashboard/scheduler/jobs_daily_backup.py. Any table backed up by the
# daily job that you intend to restore MUST be listed here with its primary
# key column(s); otherwise the script refuses to operate on it.
# --------------------------------------------------------------------------- #

# Verified against information_schema in production on 2026-05-24.
TABLE_PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "user_profiles": ("id",),
    "user_funds": ("id",),
    "funds": ("id",),
    "fund_thesis": ("id",),
    "fund_thesis_pillars": ("id",),
    "fund_contributions": ("id",),
    "system_settings": ("key",),
    "watched_tickers_v2": ("fund", "ticker"),
    "ai_analysis_skip_list": ("id",),
    "contributors": ("id",),
    "contributor_access": ("id",),
}

# Trade log is intentionally excluded — see operational notes in the docstring.
EXPLICITLY_UNSUPPORTED_TABLES: frozenset[str] = frozenset({"trade_log"})

DEFAULT_HOST_BACKUP_ROOT = Path("/app/web_dashboard/backups/daily")
STORAGE_BUCKET = "daily-backups"
STORAGE_PREFIX = "daily"


# --------------------------------------------------------------------------- #
# Source loaders
# --------------------------------------------------------------------------- #


def _load_csv_bytes_from_host(date_str: str, table: str) -> bytes:
    target = DEFAULT_HOST_BACKUP_ROOT / date_str / "tables" / f"{table}.csv"
    if not target.exists():
        raise FileNotFoundError(
            f"Host snapshot not found at {target}. "
            f"Either the date is wrong, the host volume is not mounted in this "
            f"container, or that snapshot was never written."
        )
    return target.read_bytes()


def _load_csv_bytes_from_storage(client: Any, date_str: str, table: str) -> bytes:
    object_path = f"{STORAGE_PREFIX}/{date_str}/tables/{table}.csv"
    try:
        payload = client.storage.from_(STORAGE_BUCKET).download(object_path)
    except Exception as exc:
        raise FileNotFoundError(
            f"Storage object {STORAGE_BUCKET}/{object_path} could not be "
            f"downloaded: {exc}"
        ) from exc
    if not isinstance(payload, bytes | bytearray):
        raise RuntimeError(
            f"Unexpected payload type from storage download: {type(payload)!r}"
        )
    return bytes(payload)


def _list_snapshots_host() -> list[str]:
    if not DEFAULT_HOST_BACKUP_ROOT.exists():
        return []
    return sorted(
        p.name
        for p in DEFAULT_HOST_BACKUP_ROOT.iterdir()
        if p.is_dir() and len(p.name) == 10 and p.name[4] == "-" and p.name[7] == "-"
    )


def _list_snapshots_storage(client: Any) -> list[str]:
    try:
        listing = client.storage.from_(STORAGE_BUCKET).list(STORAGE_PREFIX)
    except Exception as exc:
        raise RuntimeError(f"storage.list({STORAGE_PREFIX!r}) failed: {exc}") from exc
    dates: set[str] = set()
    for item in listing or []:
        name = (
            item.get("name")
            if isinstance(item, dict)
            else getattr(item, "name", None)
        )
        if isinstance(name, str) and len(name) == 10 and name[4] == "-" and name[7] == "-":
            dates.add(name)
    return sorted(dates)


# --------------------------------------------------------------------------- #
# CSV parsing
# --------------------------------------------------------------------------- #


def _parse_csv(payload: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """Return ``(header, rows)`` parsed from CSV bytes.

    Rows are returned as ``dict[str, str]`` (raw strings, no type coercion).
    Empty payload returns ``([], [])`` — the caller must decide whether that's
    acceptable.
    """
    if not payload:
        return [], []
    text = payload.decode("utf-8")
    reader = csv.reader(io.StringIO(text))
    header = next(reader, [])
    if not header:
        return [], []
    rows: list[dict[str, str]] = []
    for raw in reader:
        rows.append({header[i]: raw[i] if i < len(raw) else "" for i in range(len(header))})
    return header, rows


# --------------------------------------------------------------------------- #
# Type coercion: CSV is all strings; Supabase upsert needs proper types so
# numeric / boolean / null / json columns survive the round-trip.
# --------------------------------------------------------------------------- #


def _coerce_cell(value: str) -> Any:
    """Best-effort coercion of a CSV string back to a JSON-compatible value.

    Rules (in order):
    * ``""`` → ``None`` (Supabase treats empty string and NULL differently for
      some columns; the daily-backup writer emits ``""`` for NULL via pandas).
    * ``"True"`` / ``"False"`` → ``bool``.
    * Looks-like-int / looks-like-float → number.
    * Looks-like-JSON object/array (starts with ``{`` or ``[``) → parsed JSON.
    * Otherwise: return string unchanged.

    This is intentionally conservative — anything ambiguous stays a string and
    the upsert will succeed if the column is text. If a coerced value collides
    with a column type, Postgres will reject the row and the script reports it.
    """
    if value == "":
        return None
    if value == "True":
        return True
    if value == "False":
        return False
    # int
    if value.lstrip("-").isdigit():
        try:
            return int(value)
        except ValueError:
            pass
    # float
    try:
        if "." in value or "e" in value or "E" in value:
            return float(value)
    except ValueError:
        pass
    # json
    if value and value[0] in "[{":
        try:
            import json as _json

            return _json.loads(value)
        except Exception:
            pass
    return value


def _coerce_row(row: dict[str, str]) -> dict[str, Any]:
    return {k: _coerce_cell(v) for k, v in row.items()}


# --------------------------------------------------------------------------- #
# Diff against current table state
# --------------------------------------------------------------------------- #


def _row_pk(row: dict[str, Any], pk: tuple[str, ...]) -> tuple[Any, ...]:
    return tuple(row.get(col) for col in pk)


def _fetch_current_rows(client: Any, table: str) -> list[dict[str, Any]]:
    """Page through the current table contents."""
    page_size = 1000
    safety = 250_000
    out: list[dict[str, Any]] = []
    start = 0
    while True:
        end = start + page_size - 1
        result = client.table(table).select("*").range(start, end).execute()
        batch = list(result.data or [])
        out.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
        if start >= safety:
            raise RuntimeError(
                f"Bailed out reading {table}: exceeded safety cap of {safety:,} rows"
            )
    return out


def _diff_summary(
    snapshot_rows: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
    pk: tuple[str, ...],
) -> dict[str, Any]:
    snap_by_pk = {_row_pk(r, pk): r for r in snapshot_rows}
    curr_by_pk = {_row_pk(r, pk): r for r in current_rows}

    new_keys = sorted(snap_by_pk.keys() - curr_by_pk.keys())
    missing_in_snapshot = sorted(curr_by_pk.keys() - snap_by_pk.keys())
    common = snap_by_pk.keys() & curr_by_pk.keys()

    changed: list[tuple[Any, ...]] = []
    for k in common:
        if snap_by_pk[k] != curr_by_pk[k]:
            changed.append(k)
    changed.sort()

    return {
        "snapshot_rows": len(snapshot_rows),
        "current_rows": len(current_rows),
        "would_insert": new_keys,
        "would_update": changed,
        "in_db_but_not_in_snapshot": missing_in_snapshot,
    }


def _print_diff(diff: dict[str, Any], table: str, strategy: str) -> None:
    print(f"\n=== Diff preview for table '{table}' ===")
    print(f"Snapshot rows: {diff['snapshot_rows']}")
    print(f"Current rows:  {diff['current_rows']}")
    print(f"Would INSERT (in snapshot, not in DB):     {len(diff['would_insert'])}")
    print(f"Would UPDATE (PK match, content differs):  {len(diff['would_update'])}")
    extra = diff["in_db_but_not_in_snapshot"]
    if strategy == "truncate-and-replace":
        print(
            f"Would DELETE (in DB, not in snapshot):     {len(extra)}  "
            f"(strategy=truncate-and-replace)"
        )
    else:
        print(
            f"Would PRESERVE (in DB, not in snapshot):   {len(extra)}  "
            f"(strategy=upsert; pass --strategy truncate-and-replace to delete)"
        )
    # Show the first few PKs of each bucket so an operator can sanity-check.
    def _sample(items: Iterable[Any]) -> str:
        head = list(items)[:5]
        return ", ".join(repr(x) for x in head) + (", ..." if len(list(items)) > 5 else "")

    if diff["would_insert"]:
        print(f"  Sample inserts: {_sample(diff['would_insert'])}")
    if diff["would_update"]:
        print(f"  Sample updates: {_sample(diff['would_update'])}")
    if extra:
        print(f"  Sample extras:  {_sample(extra)}")
    print()


# --------------------------------------------------------------------------- #
# Apply
# --------------------------------------------------------------------------- #


def _apply_upsert(
    client: Any, table: str, snapshot_rows: list[dict[str, Any]], pk: tuple[str, ...]
) -> None:
    if not snapshot_rows:
        print("No rows to upsert (snapshot is empty).")
        return
    on_conflict = ",".join(pk)
    batch_size = 500
    sent = 0
    for i in range(0, len(snapshot_rows), batch_size):
        batch = snapshot_rows[i : i + batch_size]
        client.table(table).upsert(batch, on_conflict=on_conflict).execute()
        sent += len(batch)
        print(f"  upserted {sent}/{len(snapshot_rows)}")


def _apply_truncate_and_replace(
    client: Any,
    table: str,
    snapshot_rows: list[dict[str, Any]],
    extra_pks: list[tuple[Any, ...]],
    pk: tuple[str, ...],
) -> None:
    """Delete rows present in DB but not in snapshot, then upsert the rest.

    We deliberately do NOT issue a single ``DELETE FROM table`` — that would
    nuke FK references that the snapshot can't fully describe. Per-row deletes
    keyed on the primary key are slower but correctness-preserving.
    """
    deleted = 0
    for key in extra_pks:
        query = client.table(table).delete()
        for col, val in zip(pk, key, strict=False):
            query = query.eq(col, val)
        query.execute()
        deleted += 1
        if deleted % 100 == 0:
            print(f"  deleted {deleted}/{len(extra_pks)}")
    if extra_pks:
        print(f"  deleted {deleted}/{len(extra_pks)} rows present in DB but not in snapshot")
    _apply_upsert(client, table, snapshot_rows, pk)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="restore_daily_backup",
        description=(
            "Restore a single Supabase table from a daily-backup snapshot. "
            "Read-only by default. Read the docstring at the top of this "
            "file before running with --apply."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--table",
        choices=sorted(TABLE_PRIMARY_KEYS),
        help="Table to restore (must be one of the daily-backup tables).",
    )
    p.add_argument("--date", help="Snapshot date in YYYY-MM-DD form.")
    p.add_argument(
        "--source",
        choices=("host", "storage"),
        help="Where to read the snapshot from. Pick one explicitly.",
    )
    p.add_argument(
        "--strategy",
        choices=("upsert", "truncate-and-replace"),
        default="upsert",
        help=(
            "Default 'upsert' is idempotent on PK and never deletes rows. "
            "'truncate-and-replace' deletes rows present in DB but absent "
            "from the snapshot (also requires --allow-truncate)."
        ),
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Required to actually write. Default is dry-run (no DB writes).",
    )
    p.add_argument(
        "--confirm-restore",
        default="",
        help=(
            "Required when --apply is set. Must be the literal string 'PROD'. "
            "This is a deliberate forcing function so you cannot trip a "
            "restore by tab-completion."
        ),
    )
    p.add_argument(
        "--allow-truncate",
        action="store_true",
        help=(
            "Required when --strategy=truncate-and-replace AND --apply are set. "
            "Without this flag a truncate-and-replace --apply is rejected even "
            "if --confirm-restore=PROD."
        ),
    )
    p.add_argument(
        "--allow-empty-snapshot",
        action="store_true",
        help=(
            "Required to proceed when the snapshot CSV is 0 bytes (table was "
            "empty when backed up). Without this, an empty snapshot is treated "
            "as a likely operator error and the script aborts."
        ),
    )
    p.add_argument(
        "--list-snapshots",
        action="store_true",
        help="List available snapshot dates from --source and exit. Read-only.",
    )
    return p


def _ensure_env() -> None:
    if not os.getenv("SUPABASE_URL"):
        print("ERROR: SUPABASE_URL must be set", file=sys.stderr)
        sys.exit(1)
    if not (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")):
        print(
            "ERROR: SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY) must be "
            "set; restore needs the service-role key",
            file=sys.stderr,
        )
        sys.exit(1)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    _ensure_env()

    from supabase_client import SupabaseClient

    sb = SupabaseClient(use_service_role=True).supabase

    if args.list_snapshots:
        if args.source == "host":
            dates = _list_snapshots_host()
        elif args.source == "storage":
            dates = _list_snapshots_storage(sb)
        else:
            print("ERROR: --list-snapshots requires --source host|storage", file=sys.stderr)
            return 2
        if not dates:
            print(f"(no snapshots found for source={args.source})")
        else:
            print(f"Available snapshots from source={args.source}:")
            for d in dates:
                print(f"  {d}")
        return 0

    # Required arg checks for the actual restore path.
    missing = [name for name in ("table", "date", "source") if not getattr(args, name)]
    if missing:
        parser.error(f"missing required argument(s): {', '.join('--' + m for m in missing)}")
    assert args.table is not None and args.date is not None and args.source is not None

    if args.table in EXPLICITLY_UNSUPPORTED_TABLES:
        print(
            f"ERROR: --table={args.table!r} is not supported by this script. "
            f"See the operational notes in the script docstring.",
            file=sys.stderr,
        )
        return 2

    pk = TABLE_PRIMARY_KEYS[args.table]

    # 1. Load the snapshot.
    print(
        f"Loading snapshot: source={args.source} date={args.date} table={args.table} ..."
    )
    if args.source == "host":
        payload = _load_csv_bytes_from_host(args.date, args.table)
    else:
        payload = _load_csv_bytes_from_storage(sb, args.date, args.table)

    header, raw_rows = _parse_csv(payload)
    if not header:
        if args.allow_empty_snapshot:
            print(
                "WARNING: snapshot is empty (0 bytes / no header). Proceeding "
                "because --allow-empty-snapshot was passed."
            )
        else:
            print(
                "ERROR: snapshot is empty (0 bytes / no header). The daily "
                "backup job emits 0-byte CSVs for empty tables because "
                "Supabase REST returns no column metadata for empty result "
                "sets. If the source table really was empty on that date AND "
                "you understand that a truncate-and-replace would wipe the "
                "current table contents, re-run with --allow-empty-snapshot.",
                file=sys.stderr,
            )
            return 2

    snapshot_rows = [_coerce_row(r) for r in raw_rows]
    print(f"Snapshot: {len(snapshot_rows)} row(s), columns={header}")

    # Sanity check that the snapshot includes the primary-key columns.
    for col in pk:
        if header and col not in header:
            print(
                f"ERROR: snapshot does not contain primary-key column "
                f"{col!r} for table {args.table!r}. Refusing to proceed; "
                f"this would not be a valid restore.",
                file=sys.stderr,
            )
            return 2

    # 2. Diff against current state.
    print(f"Reading current state of {args.table} ...")
    current_rows = _fetch_current_rows(sb, args.table)
    diff = _diff_summary(snapshot_rows, current_rows, pk)
    _print_diff(diff, args.table, args.strategy)

    # 3. Dry-run gate.
    if not args.apply:
        print("Dry-run only (no --apply). Nothing was written. Exit 0.")
        return 0

    # 4. Confirmation gate.
    if args.confirm_restore != "PROD":
        print(
            "ERROR: --apply was passed but --confirm-restore PROD was not. "
            "This is intentional friction. Re-run with both flags if you "
            "really want to write to production.",
            file=sys.stderr,
        )
        return 2

    if args.strategy == "truncate-and-replace" and not args.allow_truncate:
        print(
            "ERROR: --strategy=truncate-and-replace requires --allow-truncate. "
            "This is intentional friction because truncate-and-replace "
            "deletes rows present in the DB but absent from the snapshot.",
            file=sys.stderr,
        )
        return 2

    # 5. Apply.
    print(
        f"\n=== APPLYING {args.strategy.upper()} restore on table "
        f"'{args.table}' ===\n"
    )
    try:
        if args.strategy == "upsert":
            _apply_upsert(sb, args.table, snapshot_rows, pk)
        else:
            _apply_truncate_and_replace(
                sb,
                args.table,
                snapshot_rows,
                diff["in_db_but_not_in_snapshot"],
                pk,
            )
    except Exception as exc:
        print(f"\nERROR during apply: {exc}", file=sys.stderr)
        print(
            "Restore aborted mid-flight. The DB may be in a partially-applied "
            "state — re-run with --apply (no --strategy change) to retry the "
            "upsert path; it is idempotent on PK.",
            file=sys.stderr,
        )
        return 3

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
