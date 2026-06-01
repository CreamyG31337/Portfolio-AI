"""
Daily Critical Data Backup Job
==============================

Daily snapshot of every irreplaceable Supabase table to two destinations:

1. Host-mounted directory (local copy, cron-resilient):

   * ``/app/web_dashboard/backups/daily/<YYYY-MM-DD>/trade_log/<fund_slug>_trades.csv``
   * ``/app/web_dashboard/backups/daily/<YYYY-MM-DD>/tables/<table>.csv``

   The container expects this path to be backed by a host volume
   (``/home/lance/trading-dashboard-backups`` in production). If the directory
   is missing or not writable, the job logs a warning and continues with the
   Storage upload — the Storage write is the cloud safety net.

2. Supabase Storage bucket ``daily-backups`` (private):

   * ``daily/<YYYY-MM-DD>/trade_log/<fund_slug>_trades.csv``
   * ``daily/<YYYY-MM-DD>/tables/<table>.csv``

   Bucket creation lives in
   ``web_dashboard/scripts/setup_daily_backup_bucket.py``. The Supabase MCP
   storage tools are not enabled in this environment so the bucket must exist
   before the first scheduled run.

Scope (what is and isn't backed up)
-----------------------------------

**Backed up — trade history (per fund):**
* ``trade_log`` — every fund's full trade history, one CSV per fund.

**Backed up — irreplaceable app / user / config tables (one CSV each):**
* ``user_profiles``, ``user_funds``, ``funds``
* ``fund_thesis``, ``fund_thesis_pillars``, ``fund_contributions``
* ``system_settings``, ``watched_tickers_v2``, ``ai_analysis_skip_list``
* ``contributors``, ``contributor_access``

**Explicitly NOT backed up** (operational / rebuildable / sensitive):
* AI / scheduler plumbing: ``ai_task_queue``, ``ai_analysis_queue``,
  ``apscheduler_jobs``, ``job_executions``, ``job_retry_queue``
* Derived portfolio state: ``portfolio_positions``, ``cash_balances``
  (these can be rebuilt from ``trade_log`` + contributions)
* Market / research feeds: news/articles, sentiment, social, RSS, etc.
* Public scraped data: congress/insider trades, securities metadata,
  benchmark closes, signals.
* Supabase Auth internals (never exposed via the REST API anyway).

Design choices
--------------
* Reads via ``SupabaseRepository`` (for trade history, fund-scoped) and a
  service-role ``SupabaseClient`` (for table dumps). The web container has no
  CSV files on disk and must NOT use ``DualWriteRepository``.
* Funds are enumerated directly from the ``funds`` table — production funds
  first, fallback to all if the column is unavailable. This mirrors
  ``jobs_dashboard_research.action_queue_ai_review_job``.
* Each table / trade-log payload is generated once in memory and written to
  both destinations. We never fetch twice.
* Empty trade history still writes a header-only CSV. Empty table dumps
  write a 0-byte CSV with a warning — Supabase REST does not return column
  metadata when a query yields zero rows, so we cannot synthesize a header
  from nothing. Logged loudly.
* Retention: skipped for v1. Each daily folder is small (well under 10 MB
  even with hundreds of trades and full config). 365 daily folders / year
  fits trivially in both host and Storage quotas. A follow-up can add
  age-based cleanup once we have real numbers from prod.
"""

from __future__ import annotations

import io
import logging
import re
import sys
import time
from datetime import datetime, UTC
from pathlib import Path
from typing import Any
from collections.abc import Iterable

# Make sure project root and web_dashboard are importable when APScheduler
# loads this module outside the normal Flask request context.
_current_dir = Path(__file__).resolve().parent
_project_root = _current_dir.parent.parent
_web_dashboard_path = _current_dir.parent
# Keep the repo root ahead of web_dashboard/ so top-level packages like
# data.repositories are not shadowed by modules such as web_dashboard/data.py.
for _candidate in (str(_project_root), str(_web_dashboard_path)):
    if _candidate in sys.path:
        sys.path.remove(_candidate)
for _candidate in (str(_web_dashboard_path), str(_project_root)):
    sys.path.insert(0, _candidate)

from scheduler.scheduler_core import log_job_execution  # noqa: E402

logger = logging.getLogger(__name__)

# Path inside the container where the host volume is mounted.
DEFAULT_HOST_BACKUP_ROOT = Path("/app/web_dashboard/backups/daily")

# Supabase Storage bucket (created via
# ``web_dashboard/scripts/setup_daily_backup_bucket.py``).
STORAGE_BUCKET = "daily-backups"

# Prefix used inside both the host directory and the Storage bucket so daily
# folders are siblings (easier to browse / cleanup later).
STORAGE_PREFIX = "daily"

# CSV column order for trade log. We pin this explicitly so the snapshot is
# stable across repository implementations / library upgrades.
TRADE_CSV_COLUMNS: tuple[str, ...] = (
    "trade_id",
    "timestamp",
    "ticker",
    "action",
    "shares",
    "price",
    "cost_basis",
    "pnl",
    "currency",
    "reason",
)

# Tables to snapshot wholesale every day. Order matters only for log output.
CRITICAL_APP_TABLES: tuple[str, ...] = (
    "user_profiles",
    "user_funds",
    "funds",
    "fund_thesis",
    "fund_thesis_pillars",
    "fund_contributions",
    "system_settings",
    "watched_tickers_v2",
    "ai_analysis_skip_list",
    "contributors",
    "contributor_access",
)

# Supabase REST hard-caps a single page at 1000 rows; we paginate above that.
_TABLE_PAGE_SIZE = 1000
# Generous safety cap so a runaway pagination loop can never hang the
# scheduler. None of the listed tables come anywhere near this in practice.
_TABLE_SAFETY_ROW_LIMIT = 250_000


# --------------------------------------------------------------------------- #
# Path / slug helpers
# --------------------------------------------------------------------------- #


def slugify_fund_name(fund_name: str) -> str:
    """Convert a fund name to a filesystem/URL-safe slug.

    Rules:
    * Lowercase
    * Spaces / hyphens / dots collapse to underscore
    * Strip every character that is not alphanumeric or underscore
    * Collapse repeated underscores and trim leading/trailing underscores
    * Empty result falls back to ``"unnamed_fund"`` so we never write a file
      whose name starts with the date separator.
    """
    if not fund_name:
        return "unnamed_fund"
    lowered = fund_name.strip().lower()
    replaced = re.sub(r"[\s\-\.]+", "_", lowered)
    cleaned = re.sub(r"[^a-z0-9_]", "", replaced)
    collapsed = re.sub(r"_+", "_", cleaned).strip("_")
    return collapsed or "unnamed_fund"


def _resolve_host_backup_root(date_str: str) -> Path | None:
    """Return the writable per-day host backup root, or ``None``.

    Each daily run writes under ``<root>/<YYYY-MM-DD>/``. We tolerate a
    missing mount because Supabase Storage is the authoritative cloud copy.
    """
    daily_root = DEFAULT_HOST_BACKUP_ROOT / date_str
    try:
        daily_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "Host backup root %s is not writable (mount missing?): %s",
            daily_root,
            exc,
        )
        return None
    return daily_root


# --------------------------------------------------------------------------- #
# Fund enumeration
# --------------------------------------------------------------------------- #


def _list_active_funds(client: Any) -> list[str]:
    """Return the list of fund names to back up.

    Mirrors the enumeration used by other scheduler jobs (see
    ``web_dashboard/scheduler/jobs_dashboard_research.action_queue_ai_review_job``):
    production funds first, fallback to a small sample if the
    ``is_production`` column is unset (developer / sandbox environments).
    """
    try:
        result = (
            client.supabase.table("funds")
            .select("name")
            .eq("is_production", True)
            .execute()
        )
        names = [row["name"] for row in (result.data or []) if row.get("name")]
        if names:
            return sorted(names)
    except Exception as exc:
        logger.warning("Failed to query production funds: %s", exc)

    try:
        fallback = client.supabase.table("funds").select("name").execute()
        names = [row["name"] for row in (fallback.data or []) if row.get("name")]
        return sorted(names)
    except Exception as exc:
        logger.error("Failed to enumerate funds for backup: %s", exc)
        return []


# --------------------------------------------------------------------------- #
# CSV rendering
# --------------------------------------------------------------------------- #


def _trade_rows_to_csv_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    """Render raw ``trade_log`` Supabase rows as UTF-8 CSV bytes.

    This is the production rendering path: it consumes the dict rows that
    ``supabase-py`` returns from ``table("trade_log").select("*").execute()``
    without going through ``SupabaseRepository`` / ``TradeMapper`` /
    ``Trade``. Bypassing the domain layer avoids the
    ``ModuleNotFoundError("No module named 'data.repositories'")`` we hit in
    production -- the scheduler container had ``web_dashboard/data/`` cached
    in ``sys.modules`` from earlier imports, so the deferred
    ``from data.repositories.supabase_repository import SupabaseRepository``
    inside this job resolved to the wrong (shallow) ``data`` package.

    Output columns are pinned to ``TRADE_CSV_COLUMNS`` so the snapshot
    schema does not drift if Supabase adds new columns. Numeric values
    (shares/price/cost_basis/pnl) are passed through as the strings the
    REST API returns ("8.000000", "392.14", ...); pandas will quote/escape
    them correctly. Timestamps are normalised to the ISO-8601 ``T``-separator
    form used by the previous ``Trade.timestamp.isoformat()`` rendering, so
    downstream readers don't see a format change after this refactor.
    """
    import pandas as pd

    mapped: list[dict[str, Any]] = []
    for row in rows or []:
        ts = row.get("date")
        if isinstance(ts, str) and " " in ts and "T" not in ts:
            ts = ts.replace(" ", "T", 1)
        mapped.append(
            {
                "trade_id": row.get("id"),
                "timestamp": ts,
                "ticker": row.get("ticker"),
                "action": row.get("action"),
                "shares": row.get("shares"),
                "price": row.get("price"),
                "cost_basis": row.get("cost_basis"),
                "pnl": row.get("pnl"),
                "currency": row.get("currency"),
                "reason": row.get("reason"),
            }
        )

    df = pd.DataFrame(mapped, columns=list(TRADE_CSV_COLUMNS))
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")


def _fetch_fund_trade_rows(
    admin_client: Any, fund_name: str
) -> list[dict[str, Any]]:
    """Paginate the full ``trade_log`` for one fund with the service-role client.

    Same pagination contract as ``_fetch_full_table``: 1000-row pages,
    capped by ``_TABLE_SAFETY_ROW_LIMIT`` defensively.
    """
    all_rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        result = (
            admin_client.supabase.table("trade_log")
            .select("*")
            .eq("fund", fund_name)
            .range(offset, offset + _TABLE_PAGE_SIZE - 1)
            .execute()
        )
        rows = result.data or []
        all_rows.extend(rows)
        if len(rows) < _TABLE_PAGE_SIZE:
            break
        offset += _TABLE_PAGE_SIZE
        if offset >= _TABLE_SAFETY_ROW_LIMIT:
            logger.warning(
                "Hit safety row limit (%d) while paginating trade_log for %s",
                _TABLE_SAFETY_ROW_LIMIT,
                fund_name,
            )
            break
    return all_rows


def _trades_to_csv_bytes(trades: Iterable[Any]) -> bytes:
    """Render a list of ``Trade`` objects as UTF-8 CSV bytes.

    Test seam only. Production uses ``_trade_rows_to_csv_bytes`` against
    raw Supabase rows so we don't depend on importing
    ``data.repositories.supabase_repository`` from inside an APScheduler
    worker (see ``_trade_rows_to_csv_bytes`` docstring for the import-shadow
    bug this avoids).

    Always emits the header row, even for empty trade lists, so a snapshot
    on a fund with zero trades is still a valid, parseable CSV.
    """
    import pandas as pd

    trade_list = list(trades or [])
    if not trade_list:
        df = pd.DataFrame(columns=list(TRADE_CSV_COLUMNS))
    else:
        rows: list[dict[str, Any]] = []
        for trade in trade_list:
            rows.append(
                {
                    "trade_id": getattr(trade, "trade_id", None),
                    "timestamp": trade.timestamp.isoformat()
                    if getattr(trade, "timestamp", None) is not None
                    else None,
                    "ticker": getattr(trade, "ticker", None),
                    "action": getattr(trade, "action", None),
                    "shares": str(trade.shares)
                    if getattr(trade, "shares", None) is not None
                    else None,
                    "price": str(trade.price)
                    if getattr(trade, "price", None) is not None
                    else None,
                    "cost_basis": str(trade.cost_basis)
                    if getattr(trade, "cost_basis", None) is not None
                    else None,
                    "pnl": str(trade.pnl)
                    if getattr(trade, "pnl", None) is not None
                    else None,
                    "currency": getattr(trade, "currency", None),
                    "reason": getattr(trade, "reason", None),
                }
            )
        df = pd.DataFrame(rows, columns=list(TRADE_CSV_COLUMNS))

    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")


def _rows_to_csv_bytes(rows: list[dict[str, Any]]) -> tuple[bytes, bool]:
    """Render a list of row dicts (as returned by Supabase) to CSV bytes.

    Returns ``(payload, has_header)``. ``has_header`` is ``False`` when the
    input was empty — the caller logs a warning so operators know the
    snapshot doesn't carry column metadata.

    Column order: union of keys across all rows, with the keys from the
    first row appearing first to match REST API output ordering. This is
    deterministic per-run for a given table.
    """
    import pandas as pd

    if not rows:
        return b"", False

    # Preserve first-row column order, then append any keys that only appear
    # in later rows (rare but possible with sparse JSON columns).
    ordered: list[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                ordered.append(key)

    df = pd.DataFrame(rows, columns=ordered)
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8"), True


# --------------------------------------------------------------------------- #
# Destination writers
# --------------------------------------------------------------------------- #


def _write_host_backup(
    backup_root: Path | None,
    subdir: str,
    filename: str,
    payload: bytes,
) -> tuple[bool, str | None]:
    """Write ``payload`` to ``<backup_root>/<subdir>/<filename>``.

    Returns ``(success, warning_message)``. ``warning_message`` is ``None``
    when the write succeeded (or was intentionally skipped — see
    ``backup_root is None``).
    """
    if backup_root is None:
        return False, "host volume not mounted"

    target_dir = backup_root / subdir
    target = target_dir / filename
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        logger.info("Wrote host backup %s (%d bytes)", target, len(payload))
        return True, None
    except OSError as exc:
        msg = f"host write failed for {target}: {exc}"
        logger.warning(msg)
        return False, msg


def _upload_to_storage(
    supabase_client: Any,
    object_path: str,
    payload: bytes,
) -> tuple[bool, str | None]:
    """Upload ``payload`` to ``STORAGE_BUCKET`` at ``object_path``.

    Uses ``upsert=true`` so re-runs on the same UTC day idempotently
    overwrite the previous snapshot. Returns ``(success, warning_message)``.
    """
    try:
        bucket = supabase_client.storage.from_(STORAGE_BUCKET)
    except Exception as exc:
        msg = f"could not open storage bucket '{STORAGE_BUCKET}': {exc}"
        logger.warning(msg)
        return False, msg

    file_options = {
        "content-type": "text/csv",
        "upsert": "true",
    }
    try:
        bucket.upload(path=object_path, file=payload, file_options=file_options)
        logger.info(
            "Uploaded %s to storage bucket '%s' (%d bytes)",
            object_path,
            STORAGE_BUCKET,
            len(payload),
        )
        return True, None
    except Exception as exc:
        message = str(exc).lower()
        if "bucket" in message and ("not found" in message or "does not exist" in message):
            warning = (
                f"storage bucket '{STORAGE_BUCKET}' missing — run "
                f"web_dashboard/scripts/setup_daily_backup_bucket.py"
            )
            logger.warning(warning)
            return False, warning
        warning = f"storage upload failed for {object_path}: {exc}"
        logger.warning(warning)
        return False, warning


def _write_both_destinations(
    *,
    supabase_client: Any,
    backup_root: Path | None,
    host_subdir: str,
    storage_subdir: str,
    filename: str,
    payload: bytes,
    label: str,
) -> tuple[bool, bool, list[str]]:
    """Write ``payload`` to host AND storage. Returns ``(host_ok, storage_ok, warnings)``."""
    warnings: list[str] = []

    host_ok, host_warn = _write_host_backup(
        backup_root, host_subdir, filename, payload
    )
    if not host_ok and host_warn:
        warnings.append(f"{label}: {host_warn}")

    storage_path = f"{storage_subdir}/{filename}"
    storage_ok, storage_warn = _upload_to_storage(
        supabase_client, storage_path, payload
    )
    if not storage_ok and storage_warn:
        warnings.append(f"{label}: {storage_warn}")

    return host_ok, storage_ok, warnings


# --------------------------------------------------------------------------- #
# Trade-log per-fund backup
# --------------------------------------------------------------------------- #


def _backup_fund_trade_log(
    fund_name: str,
    *,
    backup_root: Path | None,
    date_str: str,
    admin_client: Any | None = None,
    repository_factory: Any | None = None,
) -> tuple[int, bool, bool, list[str]]:
    """Back up a single fund's trade log to both destinations.

    Args:
        fund_name: Fund name as stored in the ``funds`` table.
        backup_root: Resolved per-day host backup root, or ``None`` if the
            volume mount is unavailable. We still attempt the Storage upload.
        date_str: ``YYYY-MM-DD`` date stamp used as the day folder name.
        admin_client: Service-role Supabase client used to query the
            ``trade_log`` table directly. Production callers must pass this
            so we can avoid importing ``data.repositories.supabase_repository``
            from inside the APScheduler worker -- that deferred import was
            resolving against the wrong ``data`` package in the container and
            raising ``ModuleNotFoundError('No module named ...repositories')``
            on every run.
        repository_factory: Test seam ONLY. When provided, the function uses
            the legacy repository-based path (returning ``Trade`` objects via
            ``get_trade_history()``) so the existing test fakes keep working.
            Production callers must leave this ``None`` and pass
            ``admin_client``.

    Returns:
        ``(row_count, host_ok, storage_ok, warnings)``.
    """
    warnings: list[str] = []
    fund_slug = slugify_fund_name(fund_name)
    filename = f"{fund_slug}_trades.csv"
    host_subdir = "trade_log"
    storage_subdir = f"{STORAGE_PREFIX}/{date_str}/trade_log"

    if repository_factory is not None:
        # Test path: keep the Trade-object rendering so existing fakes work.
        repo = repository_factory(fund_name)
        try:
            trades = repo.get_trade_history()
        except Exception as exc:
            warnings.append(f"{fund_name}: trade fetch failed ({exc!r})")
            logger.error(
                "Trade fetch failed for fund %s: %s", fund_name, exc, exc_info=True
            )
            return 0, False, False, warnings

        row_count = len(trades or [])
        if row_count == 0:
            logger.info(
                "Fund %s has no trades — writing header-only snapshot %s",
                fund_name,
                filename,
            )
        payload = _trades_to_csv_bytes(trades or [])
        supabase_client = repo.supabase
    else:
        # Production path: direct service-role query, no SupabaseRepository.
        if admin_client is None:
            warnings.append(
                f"{fund_name}: trade fetch skipped (no admin_client provided)"
            )
            logger.error(
                "Trade fetch for %s skipped: admin_client must be provided in "
                "production callers when repository_factory is None",
                fund_name,
            )
            return 0, False, False, warnings
        try:
            rows = _fetch_fund_trade_rows(admin_client, fund_name)
        except Exception as exc:
            warnings.append(f"{fund_name}: trade fetch failed ({exc!r})")
            logger.error(
                "Trade fetch failed for fund %s: %s", fund_name, exc, exc_info=True
            )
            return 0, False, False, warnings

        row_count = len(rows)
        if row_count == 0:
            logger.info(
                "Fund %s has no trades — writing header-only snapshot %s",
                fund_name,
                filename,
            )
        payload = _trade_rows_to_csv_bytes(rows)
        supabase_client = admin_client.supabase

    host_ok, storage_ok, write_warnings = _write_both_destinations(
        supabase_client=supabase_client,
        backup_root=backup_root,
        host_subdir=host_subdir,
        storage_subdir=storage_subdir,
        filename=filename,
        payload=payload,
        label=f"trade_log:{fund_name}",
    )
    warnings.extend(write_warnings)

    return row_count, host_ok, storage_ok, warnings


# --------------------------------------------------------------------------- #
# Critical-table backup
# --------------------------------------------------------------------------- #


def _fetch_full_table(client: Any, table_name: str) -> list[dict[str, Any]]:
    """Paginate a full ``SELECT *`` for a table, respecting Supabase's 1000-row cap.

    Stops at ``_TABLE_SAFETY_ROW_LIMIT`` rows defensively.
    """
    all_rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        result = (
            client.supabase.table(table_name)
            .select("*")
            .range(offset, offset + _TABLE_PAGE_SIZE - 1)
            .execute()
        )
        rows = result.data or []
        all_rows.extend(rows)
        if len(rows) < _TABLE_PAGE_SIZE:
            break
        offset += _TABLE_PAGE_SIZE
        if offset >= _TABLE_SAFETY_ROW_LIMIT:
            logger.warning(
                "Hit safety row limit (%d) while paginating %s — "
                "snapshot will be truncated",
                _TABLE_SAFETY_ROW_LIMIT,
                table_name,
            )
            break
    return all_rows


def _backup_table(
    table_name: str,
    *,
    admin_client: Any,
    backup_root: Path | None,
    date_str: str,
) -> tuple[int, bool, bool, list[str]]:
    """Snapshot one critical table to both destinations.

    Returns ``(row_count, host_ok, storage_ok, warnings)``.
    """
    warnings: list[str] = []
    filename = f"{table_name}.csv"
    host_subdir = "tables"
    storage_subdir = f"{STORAGE_PREFIX}/{date_str}/tables"

    try:
        rows = _fetch_full_table(admin_client, table_name)
    except Exception as exc:
        warnings.append(f"table:{table_name}: fetch failed ({exc})")
        logger.error(
            "Failed to fetch %s for backup: %s", table_name, exc, exc_info=True
        )
        return 0, False, False, warnings

    payload, has_header = _rows_to_csv_bytes(rows)
    if not has_header:
        # Truly empty table: Supabase REST doesn't expose column metadata
        # without a sample row, so we write an empty 0-byte CSV and warn
        # rather than silently producing a misleading "ok" snapshot.
        warnings.append(
            f"table:{table_name}: empty table — wrote 0-byte CSV "
            f"(no column metadata available from Supabase REST)"
        )
        logger.warning(
            "Table %s is empty — wrote 0-byte CSV (no schema discovery)",
            table_name,
        )

    host_ok, storage_ok, write_warnings = _write_both_destinations(
        supabase_client=admin_client.supabase,
        backup_root=backup_root,
        host_subdir=host_subdir,
        storage_subdir=storage_subdir,
        filename=filename,
        payload=payload,
        label=f"table:{table_name}",
    )
    warnings.extend(write_warnings)

    return len(rows), host_ok, storage_ok, warnings


# --------------------------------------------------------------------------- #
# Top-level scheduled job
# --------------------------------------------------------------------------- #


def daily_critical_data_backup_job(
    repository_factory: Any | None = None,
    admin_client_factory: Any | None = None,
) -> None:
    """Daily snapshot: every fund's trade log + every critical app/config table.

    Args:
        repository_factory: Test seam. Production callers leave this ``None``
            so the real ``SupabaseRepository`` is used per fund.
        admin_client_factory: Test seam. Callable returning the
            service-role Supabase client (must expose ``.supabase.table(...)``
            and ``.supabase.storage``). When ``None``, a real
            ``SupabaseClient(use_service_role=True)`` is created.
    """
    job_id = "daily_critical_data_backup"
    start_time = time.time()
    target_date = datetime.now(UTC).date()
    date_str = target_date.strftime("%Y-%m-%d")

    try:
        from utils.job_tracking import (
            mark_job_started,
            mark_job_completed,
            mark_job_failed,
        )
    except Exception as exc:  # pragma: no cover - import-time safety net
        logger.error("Could not import job_tracking helpers: %s", exc, exc_info=True)
        return

    try:
        mark_job_started(job_id, target_date)
    except Exception as exc:
        logger.warning("Could not mark %s as started: %s", job_id, exc)

    try:
        if admin_client_factory is not None:
            admin_client = admin_client_factory()
        else:
            from supabase_client import SupabaseClient

            admin_client = SupabaseClient(use_service_role=True)

        funds = _list_active_funds(admin_client)

        backup_root = _resolve_host_backup_root(date_str)
        if backup_root is None:
            logger.warning(
                "Host backup root unavailable — only Supabase Storage copies "
                "will be written this run."
            )

        # ---- 1. Per-fund trade-log snapshots ---------------------------- #

        fund_host_ok = 0
        fund_storage_ok = 0
        fund_total_failures: list[str] = []
        all_warnings: list[str] = []
        processed_funds: list[str] = []

        if not funds:
            logger.warning(
                "No funds returned from funds table — skipping trade_log section"
            )

        for fund_name in funds:
            try:
                _row_count, host_ok, storage_ok, warnings = _backup_fund_trade_log(
                    fund_name,
                    backup_root=backup_root,
                    date_str=date_str,
                    admin_client=admin_client,
                    repository_factory=repository_factory,
                )
            except Exception as exc:
                logger.error(
                    "Unhandled error backing up fund %s: %s",
                    fund_name,
                    exc,
                    exc_info=True,
                )
                fund_total_failures.append(fund_name)
                all_warnings.append(
                    f"trade_log:{fund_name}: unhandled error ({exc!r})"
                )
                continue

            processed_funds.append(fund_name)
            all_warnings.extend(warnings)
            if host_ok:
                fund_host_ok += 1
            if storage_ok:
                fund_storage_ok += 1
            if not host_ok and not storage_ok:
                fund_total_failures.append(fund_name)

        # ---- 2. Critical-table snapshots -------------------------------- #

        table_host_ok = 0
        table_storage_ok = 0
        table_total_failures: list[str] = []
        processed_tables: list[str] = []

        for table_name in CRITICAL_APP_TABLES:
            try:
                _row_count, host_ok, storage_ok, warnings = _backup_table(
                    table_name,
                    admin_client=admin_client,
                    backup_root=backup_root,
                    date_str=date_str,
                )
            except Exception as exc:
                logger.error(
                    "Unhandled error backing up table %s: %s",
                    table_name,
                    exc,
                    exc_info=True,
                )
                table_total_failures.append(table_name)
                all_warnings.append(
                    f"table:{table_name}: unhandled error ({exc!r})"
                )
                continue

            processed_tables.append(table_name)
            all_warnings.extend(warnings)
            if host_ok:
                table_host_ok += 1
            if storage_ok:
                table_storage_ok += 1
            if not host_ok and not storage_ok:
                table_total_failures.append(table_name)

        # ---- 3. Summary + tracking -------------------------------------- #

        duration_ms = int((time.time() - start_time) * 1000)

        # Trade-log is the marquee artifact, so the summary leads with it.
        # When something went wrong we also tack on the first couple of
        # warnings (truncated) so the persisted ``error_message`` carries the
        # real exception text instead of just the fund/table names. The
        # 500-char store-side cap means later warnings may be cut off, which
        # is fine -- the header + the first warning is what we actually need
        # to diagnose container-only failures.
        summary = (
            f"Backed up trade_log for {len(processed_funds)} funds "
            f"({fund_host_ok}_host + {fund_storage_ok}_storage) "
            f"and {len(processed_tables)} critical tables "
            f"({table_host_ok}_host + {table_storage_ok}_storage); "
            f"trade_log failures: "
            f"{fund_total_failures if fund_total_failures else 'none'}; "
            f"table failures: "
            f"{table_total_failures if table_total_failures else 'none'}"
        )
        if all_warnings:
            first_warnings = " | ".join(w[:200] for w in all_warnings[:2])
            summary = f"{summary}; first warnings: {first_warnings}"

        # Failure means BOTH destinations missed for that item. Partial
        # successes (one destination ok, one warned) still count as job
        # success because we have a usable copy somewhere.
        any_failures = bool(fund_total_failures or table_total_failures)

        if any_failures:
            log_job_execution(job_id, success=False, message=summary, duration_ms=duration_ms)
            mark_job_failed(
                job_id,
                target_date,
                None,
                summary,
                duration_ms=duration_ms,
            )
            logger.error("❌ %s completed with failures: %s", job_id, summary)
        else:
            log_job_execution(job_id, success=True, message=summary, duration_ms=duration_ms)
            mark_job_completed(
                job_id,
                target_date,
                None,
                processed_funds,
                duration_ms=duration_ms,
                message=summary,
            )
            logger.info("✅ %s: %s in %.2fs", job_id, summary, duration_ms / 1000)

        if all_warnings:
            for warning in all_warnings[:40]:
                logger.warning("%s warning: %s", job_id, warning)

    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"{job_id} failed: {exc}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            mark_job_failed(job_id, target_date, None, str(exc), duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("❌ %s", message, exc_info=True)
