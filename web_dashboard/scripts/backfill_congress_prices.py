#!/usr/bin/env python3
"""
Backfill Missing Congress Trade Prices
=======================================

One-time script to fill NULL price values in congress_trades using yfinance.
~1,926 trades (mostly after Dec 19, 2025) are missing prices.

Usage:
    python web_dashboard/scripts/backfill_congress_prices.py
    python web_dashboard/scripts/backfill_congress_prices.py --dry-run
"""

import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Path setup
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
_web_dashboard = _script_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
if str(_web_dashboard) not in sys.path:
    sys.path.insert(0, str(_web_dashboard))

try:
    from dotenv import load_dotenv
    load_dotenv(_project_root / ".env")
    load_dotenv(_project_root / "web_dashboard" / ".env")
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Rate limit: seconds between yfinance requests
YFINANCE_DELAY = 0.25

# In-memory cache to avoid duplicate yfinance calls for same ticker+date
_price_cache: Dict[Tuple[str, str], Optional[float]] = {}


def get_close_price_for_date(ticker: str, trans_date: str) -> Optional[float]:
    """Return closing price for ticker on trans_date (YYYY-MM-DD). Cached per (ticker, date)."""
    if not ticker or not trans_date or len(trans_date) < 10:
        return None
    key = (ticker.upper(), trans_date[:10])
    if key in _price_cache:
        return _price_cache[key]
    time.sleep(YFINANCE_DELAY)
    try:
        import yfinance as yf
        d = datetime.strptime(trans_date[:10], "%Y-%m-%d").date()
        # Try up to 5 days forward in case the trade date was a weekend/holiday
        end = d + timedelta(days=5)
        t = yf.Ticker(ticker.upper())
        hist = t.history(start=d, end=end, auto_adjust=False)
        if hist is None or hist.empty:
            _price_cache[key] = None
            return None
        close = float(hist["Close"].iloc[0])
        _price_cache[key] = round(close, 2)
        return _price_cache[key]
    except Exception as e:
        logger.debug("yfinance %s %s: %s", ticker, trans_date, e)
        _price_cache[key] = None
        return None


def run_backfill(dry_run: bool = False) -> None:
    """Main backfill function."""
    from supabase_client import SupabaseClient

    client = SupabaseClient(use_service_role=True)
    logger.info("Connected to Supabase")

    # Fetch all trades with NULL price
    result = client.supabase.table("congress_trades") \
        .select("id, ticker, transaction_date") \
        .is_("price", "null") \
        .execute()

    trades = result.data or []
    logger.info("Found %d trades with NULL price", len(trades))

    if not trades:
        logger.info("Nothing to backfill!")
        return

    # Group by ticker to minimize API calls
    by_ticker: Dict[str, List[dict]] = {}
    for t in trades:
        ticker = t.get("ticker", "")
        if ticker:
            by_ticker.setdefault(ticker, []).append(t)

    logger.info("Unique tickers to look up: %d", len(by_ticker))

    updated = 0
    failed = 0
    skipped = 0

    for ticker, ticker_trades in sorted(by_ticker.items()):
        for trade in ticker_trades:
            trade_id = trade["id"]
            tx_date = trade["transaction_date"]

            price = get_close_price_for_date(ticker, tx_date)

            if price is None:
                failed += 1
                logger.debug("No price found for %s on %s (trade %d)", ticker, tx_date, trade_id)
                continue

            if dry_run:
                logger.info("[DRY RUN] Would update trade %d (%s %s) -> $%.2f", trade_id, ticker, tx_date, price)
                updated += 1
                continue

            try:
                client.supabase.table("congress_trades") \
                    .update({"price": float(price)}) \
                    .eq("id", trade_id) \
                    .execute()
                updated += 1
                if updated % 50 == 0:
                    logger.info("Progress: %d/%d updated", updated, len(trades))
            except Exception as e:
                failed += 1
                logger.warning("Failed to update trade %d: %s", trade_id, e)

    logger.info("=" * 50)
    logger.info("Backfill complete!")
    logger.info("  Updated: %d", updated)
    logger.info("  Failed (no price data): %d", failed)
    logger.info("  Total: %d", len(trades))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Backfill NULL prices in congress_trades")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be updated without writing")
    args = parser.parse_args()
    run_backfill(dry_run=args.dry_run)
