"""
Executive Trades Jobs
=====================

Fetch presidential / executive-branch trades from Open Cabinet JSON,
resolve equity tickers, and insert into congress_trades.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent if current_dir.name == "scheduler" else current_dir.parent.parent
project_root_str = str(project_root)
if project_root_str in sys.path:
    sys.path.remove(project_root_str)
sys.path.insert(0, project_root_str)

web_dashboard_path = str(Path(__file__).resolve().parent.parent)
if web_dashboard_path in sys.path:
    sys.path.remove(web_dashboard_path)
sys.path.insert(1, web_dashboard_path)

from scheduler.scheduler_core import log_job_execution

logger = logging.getLogger(__name__)

TRUMP_OPEN_CABINET_URL = (
    "https://raw.githubusercontent.com/tbrown034/open-cabinet/main/data/officials/"
    "trump-donald-j.json"
)
TRUMP_BIOGUIDE_ID = "EXEC-POTUS-47"
TRUMP_NAME = "Donald J. Trump"
EXECUTIVE_CHAMBER = "Executive"


def fetch_open_cabinet_payload(url: str = TRUMP_OPEN_CABINET_URL) -> dict[str, Any]:
    """Download and parse an Open Cabinet official JSON file."""
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object JSON from {url}")
    return payload


def fetch_open_cabinet_transactions(url: str = TRUMP_OPEN_CABINET_URL) -> list[dict[str, Any]]:
    """Return the transactions list from an Open Cabinet official JSON file."""
    payload = fetch_open_cabinet_payload(url)
    transactions = payload.get("transactions") or []
    if not isinstance(transactions, list):
        raise ValueError(f"Expected transactions list in {url}")
    return transactions


def get_executive_politician_id(supabase_client: Any, bioguide_id: str = TRUMP_BIOGUIDE_ID) -> Optional[int]:
    """Look up executive politician ID by bioguide_id."""
    result = (
        supabase_client.supabase.table("politicians")
        .select("id, name, party, state, chamber")
        .eq("bioguide_id", bioguide_id)
        .limit(1)
        .execute()
    )
    if result.data:
        return int(result.data[0]["id"])
    return None


def load_og_asset_cache(supabase_client: Any) -> Dict[str, dict]:
    """Load og_asset_ticker_map into memory."""
    from executive_ticker_resolver import load_og_asset_ticker_cache

    try:
        result = (
            supabase_client.supabase.table("og_asset_ticker_map")
            .select("canonical_description, ticker, source, confidence, asset_type")
            .execute()
        )
        return load_og_asset_ticker_cache(result.data or [])
    except Exception as exc:
        logger.warning("Could not load og_asset_ticker_map: %s", exc)
        return {}


def upsert_og_asset_cache_entry(
    supabase_client: Any,
    *,
    canonical_description: str,
    ticker: str,
    source: str,
    confidence: float,
    asset_type: str,
) -> None:
    """Persist a resolved description -> ticker mapping."""
    if source == "cache":
        return
    record = {
        "canonical_description": canonical_description,
        "ticker": ticker,
        "source": source,
        "confidence": confidence,
        "asset_type": asset_type,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    supabase_client.supabase.table("og_asset_ticker_map").upsert(
        record,
        on_conflict="canonical_description",
    ).execute()


def _normalize_trade_type(raw_type: Optional[str]) -> str:
    value = (raw_type or "").strip().lower()
    if "purchase" in value or "buy" in value:
        return "Purchase"
    return "Sale"


def process_executive_transactions(
    supabase_client: Any,
    transactions: List[dict[str, Any]],
    *,
    politician_id: int,
    party: Optional[str],
    state: Optional[str],
    use_yfinance: bool = False,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Resolve tickers and insert executive trades."""
    from executive_ticker_resolver import resolve_executive_asset

    cache = load_og_asset_cache(supabase_client)
    stats = {
        "total": len(transactions),
        "inserted": 0,
        "skipped_bond": 0,
        "unresolved": 0,
        "duplicates": 0,
        "errors": 0,
    }

    for txn in transactions:
        description = str(txn.get("description") or "").strip()
        if not description:
            stats["unresolved"] += 1
            continue

        resolution = resolve_executive_asset(
            description,
            open_cabinet_ticker=txn.get("ticker"),
            cache=cache,
            use_yfinance=use_yfinance,
        )

        if resolution.source == "skipped_bond":
            stats["skipped_bond"] += 1
            continue
        if not resolution.ticker:
            stats["unresolved"] += 1
            continue

        trade_date = txn.get("date")
        if not trade_date:
            stats["unresolved"] += 1
            continue

        amount = str(txn.get("amount") or "").strip()
        trade_type = _normalize_trade_type(txn.get("type"))
        owner = "Self"

        trade_record = {
            "ticker": resolution.ticker,
            "politician_id": politician_id,
            "chamber": EXECUTIVE_CHAMBER,
            "party": party,
            "state": state,
            "owner": owner,
            "transaction_date": trade_date,
            "disclosure_date": trade_date,
            "type": trade_type,
            "amount": amount,
            "asset_type": resolution.asset_type,
            "asset_description": description,
            "notes": "Source: Open Cabinet OGE 278-T",
        }

        if dry_run:
            stats["inserted"] += 1
            continue

        try:
            if resolution.source != "cache":
                upsert_og_asset_cache_entry(
                    supabase_client,
                    canonical_description=resolution.canonical_description,
                    ticker=resolution.ticker,
                    source=resolution.source,
                    confidence=resolution.confidence,
                    asset_type=resolution.asset_type,
                )
                cache[resolution.canonical_description] = {
                    "canonical_description": resolution.canonical_description,
                    "ticker": resolution.ticker,
                    "source": resolution.source,
                    "confidence": resolution.confidence,
                    "asset_type": resolution.asset_type,
                }

            result = (
                supabase_client.supabase.table("congress_trades")
                .upsert(
                    trade_record,
                    on_conflict="politician_id,ticker,transaction_date,amount,type,owner",
                )
                .execute()
            )
            if result.data:
                stats["inserted"] += 1
            else:
                stats["duplicates"] += 1
        except Exception as exc:
            stats["errors"] += 1
            logger.error(
                "Failed to insert executive trade %s / %s: %s",
                resolution.ticker,
                trade_date,
                exc,
            )

    return stats


def fetch_executive_trades_job() -> None:
    """Poll Open Cabinet for executive trades and insert resolved equity rows."""
    job_id = "executive_trades"
    start_time = time.time()

    try:
        from utils.job_tracking import mark_job_completed, mark_job_failed, mark_job_started
        from supabase_client import SupabaseClient

        logger.info("Starting executive trades fetch job...")
        target_date = datetime.now(timezone.utc).date()
        mark_job_started(job_id, target_date)

        supabase_client = SupabaseClient(use_service_role=True)
        politician_row = (
            supabase_client.supabase.table("politicians")
            .select("id, party, state")
            .eq("bioguide_id", TRUMP_BIOGUIDE_ID)
            .limit(1)
            .execute()
        )
        if not politician_row.data:
            raise RuntimeError(
                f"Executive politician not found (bioguide_id={TRUMP_BIOGUIDE_ID}). "
                "Run migration add_executive_trades_support.sql first."
            )

        politician_id = int(politician_row.data[0]["id"])
        party = politician_row.data[0].get("party")
        state = politician_row.data[0].get("state")

        transactions = fetch_open_cabinet_transactions()
        stats = process_executive_transactions(
            supabase_client,
            transactions,
            politician_id=politician_id,
            party=party,
            state=state,
            use_yfinance=False,
        )

        duration_ms = int((time.time() - start_time) * 1000)
        message = (
            f"Executive trades: inserted={stats['inserted']}, "
            f"skipped_bond={stats['skipped_bond']}, unresolved={stats['unresolved']}, "
            f"duplicates={stats['duplicates']}, errors={stats['errors']}"
        )
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        mark_job_completed(job_id, target_date, message)
        logger.info(message)

    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Executive trades job failed: {exc}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(job_id, datetime.now(timezone.utc).date(), message)
        except Exception:
            pass
        logger.error(message, exc_info=True)
        raise
