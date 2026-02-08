#!/usr/bin/env python3
"""
Reprocess ETF holdings/articles from saved raw files.

Uses files in ``web_dashboard/logs/etf_raw_data/YYYY-MM-DD`` to rebuild:
- ETF holdings snapshots
- ETF Change research articles

This avoids network fetch/parsing drift when a prior run produced bad output.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import patch

# Add web_dashboard to import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from postgres_client import PostgresClient
from research_repository import ResearchRepository
from scheduler.jobs_etf_watchtower import (
    ETF_CONFIGS,
    calculate_diff,
    fetch_ark_holdings,
    fetch_direxion_holdings,
    fetch_globalx_holdings,
    fetch_ishares_holdings,
    fetch_spdr_holdings,
    fetch_vaneck_holdings,
    get_previous_holdings,
    log_significant_changes,
    save_holdings_snapshot,
    upsert_etf_metadata,
    upsert_securities_metadata,
)
from supabase_client import SupabaseClient


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class _FakeResponse:
    def __init__(self, content: bytes, is_xlsx: bool) -> None:
        self.content = content
        self.status_code = 200
        self.headers = {
            "Content-Type": (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                if is_xlsx
                else "text/csv"
            )
        }

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def raise_for_status(self) -> None:
        return None


def _load_holdings_from_raw(etf_ticker: str, target_date: datetime):
    config = ETF_CONFIGS[etf_ticker]
    provider = config["provider"]
    raw_dir = Path(__file__).resolve().parent.parent / "logs" / "etf_raw_data" / target_date.strftime("%Y-%m-%d")

    ext = ".xlsx" if provider in {"SPDR", "VanEck"} else ".csv"
    file_path = raw_dir / f"{etf_ticker}{ext}"
    if not file_path.exists():
        logger.warning(f"Raw file not found for {etf_ticker}: {file_path}")
        return None

    content = file_path.read_bytes()
    fake_response = _FakeResponse(content=content, is_xlsx=(ext == ".xlsx"))

    with patch("scheduler.jobs_etf_watchtower.requests.get", return_value=fake_response):
        if provider == "ARK":
            return fetch_ark_holdings(etf_ticker, config["url"], target_date)
        if provider == "iShares":
            return fetch_ishares_holdings(etf_ticker, config["url"], target_date)
        if provider == "SPDR":
            return fetch_spdr_holdings(etf_ticker, config["url"], target_date)
        if provider == "Global X":
            return fetch_globalx_holdings(etf_ticker, config["url"], target_date)
        if provider == "Direxion":
            return fetch_direxion_holdings(etf_ticker, config["url"], target_date)
        if provider == "VanEck":
            return fetch_vaneck_holdings(etf_ticker, config["url"], target_date)
    return None


def _delete_existing_articles(repo: ResearchRepository, etf_ticker: str, target_date: datetime) -> int:
    rows = repo.client.execute_query(
        """
        SELECT id
        FROM research_articles
        WHERE article_type = 'ETF Change'
          AND title LIKE %s
          AND DATE(fetched_at) = %s
        """,
        (f"{etf_ticker} Daily Holdings Update%", target_date.strftime("%Y-%m-%d")),
    )
    for row in rows:
        repo.delete_article(str(row["id"]))
    return len(rows)


def reprocess_for_date(target_date: datetime, tickers: Optional[list[str]]) -> int:
    db = SupabaseClient(use_service_role=True)
    pc = PostgresClient()
    repo = ResearchRepository()

    to_process = [t for t in (tickers or ETF_CONFIGS.keys()) if t in ETF_CONFIGS]
    processed = 0

    for etf_ticker in to_process:
        logger.info(f"=== Reprocessing {etf_ticker} ({target_date.strftime('%Y-%m-%d')}) ===")
        holdings = _load_holdings_from_raw(etf_ticker, target_date)
        if holdings is None or holdings.empty:
            logger.warning(f"Skipping {etf_ticker}: no parsed holdings")
            continue

        deleted = _delete_existing_articles(repo, etf_ticker, target_date)
        if deleted:
            logger.info(f"Deleted {deleted} existing ETF Change article(s) for {etf_ticker}")

        previous = get_previous_holdings(pc, etf_ticker, target_date)
        if not previous.empty:
            changes = calculate_diff(holdings, previous, etf_ticker)
            if changes:
                ratio = len(changes) / len(holdings) if len(holdings) else 1
                if ratio <= 0.9:
                    log_significant_changes(
                        repo,
                        changes,
                        etf_ticker,
                        source_url=ETF_CONFIGS[etf_ticker].get("url"),
                    )
                else:
                    logger.warning(
                        f"Skipped article for {etf_ticker}: {len(changes)}/{len(holdings)} changes ({ratio:.1%})"
                    )
        else:
            logger.info(f"No previous snapshot for {etf_ticker}; skipping article creation")

        upsert_etf_metadata(db, etf_ticker, ETF_CONFIGS[etf_ticker]["provider"])
        upsert_securities_metadata(db, holdings, ETF_CONFIGS[etf_ticker]["provider"])
        save_holdings_snapshot(pc, etf_ticker, holdings, target_date)
        processed += 1

    logger.info(f"Reprocessing complete. Processed {processed}/{len(to_process)} ETFs.")
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description="Reprocess ETF holdings/articles from saved raw files")
    parser.add_argument("--date", required=True, help="Date folder in YYYY-MM-DD format under logs/etf_raw_data")
    parser.add_argument("--etf", nargs="*", help="Optional ETF ticker list (default: all configured)")
    args = parser.parse_args()

    target_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    tickers = [t.upper() for t in args.etf] if args.etf else None
    reprocess_for_date(target_date, tickers)


if __name__ == "__main__":
    main()
