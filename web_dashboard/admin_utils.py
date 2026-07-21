#!/usr/bin/env python3
"""Admin caching and status helpers for Flask routes."""

from __future__ import annotations

import logging
import sys
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from dashboard_constants import CACHE_VERSION
from dashboard_data_clients import get_user_scoped_supabase_client
from flask_cache_utils import cache_data

try:
    import log_handler  # noqa: F401 - register PERF log level
except ImportError:
    pass

logger = logging.getLogger(__name__)


def get_admin_supabase_client():
    """Service-role Supabase client for admin scripts without a user session."""
    from supabase_client import SupabaseClient

    return SupabaseClient(use_service_role=True)


def _admin_supabase_client():
    """User-scoped client for admin UI reads; service role when no Flask request."""
    return get_user_scoped_supabase_client() or get_admin_supabase_client()


@contextmanager
def perf_timer(operation_name: str, log_to_console: bool = True):
    """Time an operation and log at PERF level."""
    start_time = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start_time
        if log_to_console:
            logger.perf(f"⏱️ {operation_name}: {round(elapsed * 1000, 2)}ms")


@cache_data(ttl=60)
def get_cached_funds() -> List[Dict[str, Any]]:
    """Get all funds from database with caching."""
    with perf_timer("get_cached_funds"):
        client = _admin_supabase_client()
        if not client:
            return []
        try:
            with perf_timer("DB: funds.select", log_to_console=False):
                from supabase_pagination import fetch_all_rows
                return fetch_all_rows(client, "funds", select="*", order="name")
        except Exception as e:
            logger.error(f"Error loading funds: {e}")
            return []


@cache_data(ttl=60)
def get_cached_fund_names() -> List[str]:
    """Get fund names only (lighter query)."""
    funds = get_cached_funds()
    return [f["name"] for f in funds]


@cache_data(ttl=60)
def get_cached_users() -> List[Dict[str, Any]]:
    """Get all users with their fund assignments."""
    with perf_timer("get_cached_users"):
        client = _admin_supabase_client()
        if not client:
            return []
        try:
            with perf_timer("DB: list_users_with_funds RPC", log_to_console=False):
                result = client.supabase.rpc("list_users_with_funds").execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error loading users: {e}")
            return []


@cache_data(ttl=60)
def get_cached_contributors() -> List[Dict[str, Any]]:
    """Get all contributors from database."""
    with perf_timer("get_cached_contributors"):
        client = _admin_supabase_client()
        if not client:
            return []
        try:
            with perf_timer("DB: contributors.select", log_to_console=False):
                result = (
                    client.supabase.table("contributors")
                    .select("id, name, email")
                    .order("name")
                    .execute()
                )
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error loading contributors: {e}")
            return []


@cache_data(ttl=60)
def get_fund_statistics_batched(
    fund_names: List[str],
    _cache_version: str = CACHE_VERSION,
) -> Dict[str, Dict[str, int]]:
    """Position and trade counts for multiple funds in batched queries."""
    if not fund_names:
        return {}

    client = _admin_supabase_client()
    if not client:
        return {fund: {"positions": 0, "trades": 0} for fund in fund_names}

    stats = {fund: {"positions": 0, "trades": 0} for fund in fund_names}

    try:
        with perf_timer("DB: portfolio_positions.count(batched)", log_to_console=False):
            all_positions: List[Dict[str, Any]] = []
            batch_size = 1000
            offset = 0

            while True:
                result = (
                    client.supabase.table("portfolio_positions")
                    .select("fund")
                    .in_("fund", fund_names)
                    .range(offset, offset + batch_size - 1)
                    .execute()
                )

                if not result.data:
                    break

                all_positions.extend(result.data)

                if len(result.data) < batch_size:
                    break

                offset += batch_size
                if offset > 50000:
                    logger.warning(
                        "Reached 50,000 row safety limit in get_fund_statistics_batched "
                        "positions pagination"
                    )
                    break

            if all_positions:
                position_counts = Counter(pos["fund"] for pos in all_positions)
                for fund, count in position_counts.items():
                    if fund in stats:
                        stats[fund]["positions"] = count

        with perf_timer("DB: trade_log.count(batched)", log_to_console=False):
            all_trades: List[Dict[str, Any]] = []
            batch_size = 1000
            offset = 0

            while True:
                result = (
                    client.supabase.table("trade_log")
                    .select("fund")
                    .in_("fund", fund_names)
                    .range(offset, offset + batch_size - 1)
                    .execute()
                )

                if not result.data:
                    break

                all_trades.extend(result.data)

                if len(result.data) < batch_size:
                    break

                offset += batch_size
                if offset > 50000:
                    logger.warning(
                        "Reached 50,000 row safety limit in get_fund_statistics_batched "
                        "trades pagination"
                    )
                    break

            if all_trades:
                trade_counts = Counter(trade["fund"] for trade in all_trades)
                for fund, count in trade_counts.items():
                    if fund in stats:
                        stats[fund]["trades"] = count

    except Exception as e:
        logger.error(f"Error getting batched fund statistics: {e}", exc_info=True)

    return stats


@cache_data(ttl=300)
def get_postgres_status_cached(
    _cache_version: str = CACHE_VERSION,
) -> Tuple[bool, Optional[Dict[str, int]]]:
    """Postgres connection status and research_articles stats."""
    try:
        from postgres_client import PostgresClient

        pg_client = PostgresClient()
        if not pg_client.test_connection():
            return False, None

        stats_result = pg_client.execute_query("SELECT COUNT(*) as count FROM research_articles")
        recent_result = pg_client.execute_query(
            """
            SELECT COUNT(*) as count
            FROM research_articles
            WHERE fetched_at >= NOW() - INTERVAL '7 days'
            """
        )

        stats = {
            "total": stats_result[0]["count"] if stats_result else 0,
            "recent_7d": recent_result[0]["count"] if recent_result else 0,
        }
        return True, stats
    except ImportError:
        return False, None
    except Exception as e:
        logger.error(f"Error getting Postgres status: {e}", exc_info=True)
        return False, None


@cache_data(ttl=300)
def get_system_status_cached(_cache_version: str = CACHE_VERSION) -> Dict[str, Any]:
    """System status: Supabase, exchange rates, Postgres."""
    client = _admin_supabase_client()
    status: Dict[str, Any] = {
        "supabase_connected": False,
        "exchange_rates": None,
        "postgres_connected": False,
        "postgres_stats": None,
        "errors": [],
    }

    if not client:
        status["errors"].append("Supabase client not available")
        return status

    try:
        with perf_timer("DB: user_profiles connection test (cached)", log_to_console=False):
            client.supabase.table("user_profiles").select("user_id").limit(1).execute()
        status["supabase_connected"] = True
    except Exception as e:
        status["errors"].append(f"Supabase connection error: {e}")

    try:
        with perf_timer("DB: exchange_rates.select (cached)", log_to_console=False):
            rates_result = (
                client.supabase.table("exchange_rates")
                .select("timestamp")
                .order("timestamp", desc=True)
                .limit(1)
                .execute()
            )
        if rates_result.data:
            status["exchange_rates"] = rates_result.data[0]["timestamp"]
    except Exception as e:
        status["errors"].append(f"Exchange rates error: {e}")

    status["postgres_connected"], status["postgres_stats"] = get_postgres_status_cached()

    return status
