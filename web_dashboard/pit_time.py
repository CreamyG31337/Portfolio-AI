"""Point-in-time SQL helpers (AQuA transfer Phase 1).

Analysis lookbacks prefer immutable ``available_at`` when the column exists.

The whole point of these helpers is to stop late-ingested rows leaking backwards
into historical windows, so the failure mode that matters is *failing open*:
quietly falling back to the mutable ``fetched_at`` / ``created_at`` clock and
reporting nothing. Two rules follow from that, and both are load-bearing:

1. **Only successful probes are cached.** A transient connection error must not
   pin support to False for the life of the process. Previously one pool hiccup
   during the first analysis after a deploy disabled point-in-time filtering
   until restart, silently.
2. **A negative probe is re-checked.** ``ALTER TABLE`` can land while the app is
   running, so "column absent" is cached only briefly; "column present" is
   permanent, because a column that exists does not disappear under a live app.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Seconds to trust a *negative* probe. Short enough that applying the migration on
# a running app takes effect without a restart, long enough that a table missing
# the column does not re-query information_schema on every lookback.
_NEGATIVE_TTL_SECONDS = 300.0

# table -> (has_column, checked_at_monotonic). Positive results store None for the
# timestamp and are never re-probed.
_column_cache: dict[str, tuple[bool, float | None]] = {}


def reset_pit_column_cache() -> None:
    """Drop memoized probe results. Call between tests that use different clients."""
    _column_cache.clear()


def _has_available_at(postgres: Any, table: str) -> bool:
    cached = _column_cache.get(table)
    if cached is not None:
        present, checked_at = cached
        if present or checked_at is None:
            return present
        if (time.monotonic() - checked_at) < _NEGATIVE_TTL_SECONDS:
            return False

    try:
        rows = postgres.execute_query(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = 'available_at'
            LIMIT 1
            """,
            (table,),
        )
    except Exception:
        # Do NOT cache. Caching this is what turns one transient error into a
        # process-lifetime silent downgrade of every point-in-time lookback.
        logger.warning(
            "available_at probe failed for %s; falling back to the mutable "
            "ingest clock for this call only",
            table,
            exc_info=True,
        )
        return False

    present = bool(rows)
    _column_cache[table] = (present, None if present else time.monotonic())
    return present


def research_articles_have_available_at(postgres: Any) -> bool:
    return _has_available_at(postgres, "research_articles")


def social_metrics_have_available_at(postgres: Any) -> bool:
    return _has_available_at(postgres, "social_metrics")


def article_as_of_expr(postgres: Any) -> str:
    """SQL expression for "when did we first know this article", for lookbacks."""
    if research_articles_have_available_at(postgres):
        return _coalesce_expr(postgres, "research_articles", "available_at", "fetched_at")
    return "fetched_at"


def social_as_of_expr(postgres: Any) -> str:
    """SQL expression for "when did we first know this metric", for lookbacks."""
    if social_metrics_have_available_at(postgres):
        return _coalesce_expr(postgres, "social_metrics", "available_at", "created_at")
    return "created_at"


def _is_naive_timestamp(postgres: Any, table: str, column: str) -> bool:
    """True when the column is TIMESTAMP WITHOUT TIME ZONE.

    Probed rather than assumed: the two legacy ingest clocks disagree in prod.
    ``research_articles.fetched_at`` is naive while ``social_metrics.created_at`` is
    already timestamptz, and the checked-in schema files describe both as naive.
    """
    key = f"{table}.{column}.is_naive"
    cached = _column_cache.get(key)
    if cached is not None:
        return cached[0]

    try:
        rows = postgres.execute_query(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            LIMIT 1
            """,
            (table, column),
        )
    except Exception:
        logger.warning(
            "type probe failed for %s.%s; assuming timestamptz (no cast)",
            table,
            column,
            exc_info=True,
        )
        return False

    if not rows:
        return False
    raw = rows[0]
    value = raw.get("data_type") if isinstance(raw, dict) else raw[0]
    naive = str(value or "").strip().lower() == "timestamp without time zone"
    _column_cache[key] = (naive, None)
    return naive


def _coalesce_expr(postgres: Any, table: str, available_col: str, fallback_col: str) -> str:
    """COALESCE the PIT column with the legacy ingest clock, without a silent cast.

    ``available_at`` is TIMESTAMPTZ. When the fallback column is *naive* TIMESTAMP a
    bare COALESCE resolves to timestamptz and reinterprets the naive value in the
    session TimeZone, shifting every lookback boundary by the server's UTC offset --
    roughly 8 hours on a Vancouver-local server, silently moving rows across the
    boundary this module exists to enforce. Those columns store UTC (the repository
    stamps ``tzinfo=utc`` on read), so the cast is pinned explicitly.

    When the fallback is *already* timestamptz the cast must be omitted: applied to a
    timestamptz, ``AT TIME ZONE 'UTC'`` performs the opposite conversion and strips
    the zone. It happens to round-trip while the server runs UTC, which is exactly the
    kind of accident that breaks the day someone changes ``TimeZone``.
    """
    if _is_naive_timestamp(postgres, table, fallback_col):
        return f"COALESCE({available_col}, {fallback_col} AT TIME ZONE 'UTC')"
    return f"COALESCE({available_col}, {fallback_col})"
