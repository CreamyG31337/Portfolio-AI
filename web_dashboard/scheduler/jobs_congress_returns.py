"""
Congress Trade Returns Job
==========================

Daily job that computes percentage price change for each congress trade
using yfinance adjusted close prices.

For each trade:
  pct_change = ((current_adj_close - entry_adj_close) / entry_adj_close) * 100

Entry prices are fetched once and cached in congress_trade_returns.entry_price_adj.
Current prices are refreshed daily via batch yfinance downloads.
"""

import logging
import math
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import sys

# Path setup (same pattern as jobs_congress.py)
current_dir = Path(__file__).resolve().parent
if current_dir.name == "scheduler":
    project_root = current_dir.parent.parent
else:
    project_root = current_dir.parent.parent

project_root_str = str(project_root)
if project_root_str in sys.path:
    sys.path.remove(project_root_str)
sys.path.insert(0, project_root_str)

web_dashboard_path = str(Path(__file__).resolve().parent.parent)
if web_dashboard_path in sys.path:
    sys.path.remove(web_dashboard_path)
if len(sys.path) > 1:
    sys.path.insert(1, web_dashboard_path)
else:
    sys.path.append(web_dashboard_path)

from scheduler.scheduler_core import log_job_execution

logger = logging.getLogger(__name__)

# congress_trade_returns.pct_change is NUMERIC(8, 2) -> max |value| is 999_999.99.
CTR_PCT_MAX: float = 999_999.99
# Sub-penny adjusted closes explode pct_change; skip rather than upsert junk.
ENTRY_MIN_POSITIVE: float = 1e-4


def normalize_pct_change_for_db(pct: float) -> tuple[float, bool]:
    """Clamp pct to the database column range; return (value, was_clamped).

    Avoids Postgres 22003 numeric overflow without storing NULL.
    """
    if pct > CTR_PCT_MAX:
        return round(CTR_PCT_MAX, 2), True
    if pct < -CTR_PCT_MAX:
        return round(-CTR_PCT_MAX, 2), True
    return round(pct, 2), False


# ---------------------------------------------------------------------------
# Amount range midpoint mapping
# ---------------------------------------------------------------------------
AMOUNT_MIDPOINTS: Dict[str, float] = {
    "$1 - $1,000": 500.50,
    "$1,001 - $15,000": 8000.50,
    "$15,001 - $50,000": 32500.50,
    "$50,001 - $100,000": 75000.50,
    "$100,001 - $250,000": 175000.50,
    "$250,001 - $500,000": 375000.50,
    "$500,001 - $1,000,000": 750000.50,
    "$1,000,001 - $5,000,000": 3000000.50,
    "$5,000,001 - $25,000,000": 15000000.50,
    "$10,000,001 - $25,000,000": 17500000.50,
    "$25,000,001 - $50,000,000": 37500000.50,
    "Over $1,000,000": 1500000.00,
}


def estimate_midpoint(amount_str: Optional[str]) -> Optional[float]:
    """Convert an amount range string to its midpoint dollar estimate.

    Returns None if the string doesn't match any known range.
    """
    if not amount_str:
        return None
    amount_str = amount_str.strip()
    if amount_str in AMOUNT_MIDPOINTS:
        return AMOUNT_MIDPOINTS[amount_str]
    # Fallback: try to match case-insensitively
    for key, val in AMOUNT_MIDPOINTS.items():
        if key.lower() == amount_str.lower():
            return val
    return None


# ---------------------------------------------------------------------------
# yfinance helpers
# ---------------------------------------------------------------------------
BATCH_SIZE = 50  # Tickers per yfinance.download() call
YFINANCE_DELAY = 1.0  # Seconds between batch calls


def _batch_download_current_prices(tickers: List[str]) -> Dict[str, Optional[float]]:
    """Batch-fetch current adjusted close prices for a list of tickers.

    Returns dict of ticker -> adjusted_close (or None if unavailable).
    """
    import yfinance as yf

    result: Dict[str, Optional[float]] = {}

    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        logger.info(
            "  Fetching current prices batch %d/%d (%d tickers)...",
            (i // BATCH_SIZE) + 1,
            (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE,
            len(batch),
        )
        try:
            data = yf.download(
                batch,
                period="5d",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if data is None or data.empty:
                for t in batch:
                    result[t] = None
                continue

            # yf.download returns MultiIndex columns when multiple tickers
            if len(batch) == 1:
                # Single ticker: columns are just 'Open', 'Close', etc.
                ticker = batch[0]
                if "Close" in data.columns and not data["Close"].dropna().empty:
                    result[ticker] = round(float(data["Close"].dropna().iloc[-1]), 4)
                else:
                    result[ticker] = None
            else:
                # Multiple tickers: columns are MultiIndex (Price, Ticker)
                for ticker in batch:
                    try:
                        if ("Close", ticker) in data.columns:
                            col = data[("Close", ticker)].dropna()
                            if not col.empty:
                                result[ticker] = round(float(col.iloc[-1]), 4)
                            else:
                                result[ticker] = None
                        else:
                            result[ticker] = None
                    except Exception:
                        result[ticker] = None

        except Exception as e:
            logger.warning("Batch download failed for %d tickers: %s", len(batch), e)
            for t in batch:
                result[t] = None

        if i + BATCH_SIZE < len(tickers):
            time.sleep(YFINANCE_DELAY)

    return result


def _fetch_entry_price_adj(ticker: str, tx_date_str: str) -> Optional[float]:
    """Fetch the adjusted close on or near the transaction date for a single ticker.

    NOTE: This is the slow single-ticker fallback. Prefer _batch_fetch_entry_prices()
    for bulk lookups.
    """
    import yfinance as yf

    try:
        d = datetime.strptime(tx_date_str[:10], "%Y-%m-%d").date()
        start = d
        end = d + timedelta(days=7)

        data = yf.download(
            ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=True,
            progress=False,
        )
        if data is None or data.empty:
            return None
        close_val = data["Close"].dropna().iloc[0]
        if hasattr(close_val, "iloc"):
            close_val = close_val.iloc[0]
        return round(float(close_val), 4)
    except Exception as e:
        logger.debug("Entry price lookup failed for %s on %s: %s", ticker, tx_date_str, e)
        return None


def _batch_fetch_entry_prices(
    trades: List[dict],
) -> Dict[int, float]:
    """Batch-fetch adjusted entry prices for many trades at once.

    Strategy: group trades by ticker, batch-download full adjusted close history
    per ticker (50 at a time), then look up each trade's date in the local DataFrame.
    This reduces ~26K individual yfinance calls to ~42 batch calls.

    Returns dict of trade_id -> adjusted_entry_price.
    """
    import yfinance as yf
    import pandas as pd
    from datetime import date as date_type

    if not trades:
        return {}

    # Group trades by ticker -> list of (trade_id, transaction_date_str)
    ticker_trades: Dict[str, List[Tuple[int, str]]] = {}
    for t in trades:
        ticker_trades.setdefault(t["ticker"], []).append(
            (t["id"], t["transaction_date"])
        )

    # Find the global earliest date so we download enough history
    all_dates = []
    for t in trades:
        try:
            all_dates.append(datetime.strptime(t["transaction_date"][:10], "%Y-%m-%d").date())
        except (ValueError, TypeError):
            pass
    if not all_dates:
        return {}

    global_start = min(all_dates) - timedelta(days=5)  # Buffer for weekends

    unique_tickers = sorted(ticker_trades.keys())
    logger.info(
        "  Batch-fetching entry prices: %d tickers, %d trades, history from %s",
        len(unique_tickers), len(trades), global_start.isoformat(),
    )

    # Download history in batches of BATCH_SIZE tickers
    # Store as dict: ticker -> DataFrame of adjusted close
    ticker_history: Dict[str, "pd.DataFrame"] = {}
    today_str = datetime.now().strftime("%Y-%m-%d")

    for i in range(0, len(unique_tickers), BATCH_SIZE):
        batch = unique_tickers[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (len(unique_tickers) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info(
            "  Entry price batch %d/%d (%d tickers)...",
            batch_num, total_batches, len(batch),
        )
        try:
            data = yf.download(
                batch,
                start=global_start.isoformat(),
                end=today_str,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if data is None or data.empty:
                continue

            if len(batch) == 1:
                # Single ticker: columns are flat ('Open', 'Close', etc.)
                ticker = batch[0]
                if "Close" in data.columns:
                    ticker_history[ticker] = data[["Close"]].dropna()
            else:
                # Multiple tickers: MultiIndex columns (Price, Ticker)
                for ticker in batch:
                    try:
                        if ("Close", ticker) in data.columns:
                            col = data[("Close", ticker)].dropna()
                            if not col.empty:
                                ticker_history[ticker] = col.to_frame(name="Close")
                    except Exception:
                        pass

        except Exception as e:
            logger.warning("  Entry price batch download failed: %s", e)

        if i + BATCH_SIZE < len(unique_tickers):
            time.sleep(YFINANCE_DELAY)

    logger.info("  Downloaded history for %d/%d tickers", len(ticker_history), len(unique_tickers))

    # Now look up each trade's entry price from the cached history
    result: Dict[int, float] = {}
    miss_count = 0

    for ticker, trade_list in ticker_trades.items():
        hist = ticker_history.get(ticker)
        if hist is None or hist.empty:
            miss_count += len(trade_list)
            continue

        for trade_id, tx_date_str in trade_list:
            try:
                d = datetime.strptime(tx_date_str[:10], "%Y-%m-%d").date()
                # Find the closest date on or after the transaction date
                # (handles weekends/holidays)
                mask = hist.index.date >= d
                if not mask.any():
                    miss_count += 1
                    continue
                close_val = hist.loc[mask, "Close"].iloc[0]
                if hasattr(close_val, "iloc"):
                    close_val = close_val.iloc[0]
                val = float(close_val)
                if val > 0:
                    result[trade_id] = round(val, 4)
                else:
                    miss_count += 1
            except Exception:
                miss_count += 1

    logger.info(
        "  Resolved %d entry prices (%d missed)",
        len(result), miss_count,
    )
    return result


# ---------------------------------------------------------------------------
# Main job
# ---------------------------------------------------------------------------
def compute_congress_trade_returns_job() -> None:
    """Daily job: compute and refresh return percentages for all congress trades."""
    job_id = "congress_trade_returns"
    start_time = time.time()

    try:
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        from supabase_client import SupabaseClient

        target_date = datetime.now(timezone.utc).date()
        mark_job_started(job_id, target_date)

        client = SupabaseClient(use_service_role=True)
        logger.info("Congress trade returns job started")

        # ------------------------------------------------------------------
        # Step 1: Fetch all trades (entry prices come from yfinance, not
        #         the congress_trades.price column which may be NULL for
        #         newer imports)
        # ------------------------------------------------------------------
        logger.info("Step 1: Fetching all congress trades...")
        # Fetch in pages of 1000 to avoid Supabase limits
        all_trades: List[dict] = []
        page_size = 1000
        offset = 0
        while True:
            resp = client.supabase.table("congress_trades") \
                .select("id, ticker, transaction_date, amount") \
                .range(offset, offset + page_size - 1) \
                .execute()
            batch = resp.data or []
            all_trades.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size

        logger.info("  Found %d trades total", len(all_trades))

        if not all_trades:
            message = "No trades found - nothing to compute"
            duration_ms = int((time.time() - start_time) * 1000)
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=message)
            return

        # ------------------------------------------------------------------
        # Step 2: Get existing return records (to avoid re-fetching entry prices)
        # ------------------------------------------------------------------
        logger.info("Step 2: Loading existing return records...")
        existing_returns: Dict[int, dict] = {}
        offset = 0
        while True:
            resp = client.supabase.table("congress_trade_returns") \
                .select("trade_id, entry_price_adj") \
                .range(offset, offset + page_size - 1) \
                .execute()
            batch = resp.data or []
            for row in batch:
                existing_returns[row["trade_id"]] = row
            if len(batch) < page_size:
                break
            offset += page_size

        logger.info("  Found %d existing return records", len(existing_returns))

        # ------------------------------------------------------------------
        # Step 3: Determine which trades need entry_price_adj lookup
        # ------------------------------------------------------------------
        trades_needing_entry = [
            t for t in all_trades
            if t["id"] not in existing_returns
            or existing_returns[t["id"]].get("entry_price_adj") is None
        ]
        logger.info("  %d trades need entry_price_adj lookup", len(trades_needing_entry))

        # Fetch entry prices using batch download (much faster than per-trade)
        entry_prices: Dict[int, float] = {}  # trade_id -> adj entry price
        if trades_needing_entry:
            logger.info("Step 3: Batch-fetching adjusted entry prices for %d trades...", len(trades_needing_entry))
            entry_prices = _batch_fetch_entry_prices(trades_needing_entry)

        # Also include already-cached entry prices
        for trade in all_trades:
            tid = trade["id"]
            if tid not in entry_prices and tid in existing_returns:
                ep = existing_returns[tid].get("entry_price_adj")
                if ep is not None:
                    entry_prices[tid] = float(ep)

        # ------------------------------------------------------------------
        # Step 4: Batch-fetch current prices for all unique tickers
        # ------------------------------------------------------------------
        unique_tickers = sorted(set(t["ticker"] for t in all_trades if t["id"] in entry_prices))
        logger.info("Step 4: Fetching current prices for %d unique tickers...", len(unique_tickers))
        current_prices = _batch_download_current_prices(unique_tickers)

        found_current = sum(1 for v in current_prices.values() if v is not None)
        logger.info("  Got current prices for %d/%d tickers", found_current, len(unique_tickers))

        # ------------------------------------------------------------------
        # Step 5: Compute returns and upsert
        # ------------------------------------------------------------------
        logger.info("Step 5: Computing returns and upserting...")
        upsert_batch: List[dict] = []
        computed = 0
        skipped = 0

        for trade in all_trades:
            tid = trade["id"]
            ticker = trade["ticker"]
            amount = trade.get("amount")

            entry_adj = entry_prices.get(tid)
            current_adj = current_prices.get(ticker)

            if entry_adj is None or current_adj is None or entry_adj == 0:
                skipped += 1
                continue

            if entry_adj < ENTRY_MIN_POSITIVE:
                skipped += 1
                logger.warning(
                    "Skipping trade %s (%s) %s: entry_price_adj %s below ENTRY_MIN %s",
                    tid,
                    ticker,
                    trade.get("transaction_date"),
                    entry_adj,
                    ENTRY_MIN_POSITIVE,
                )
                continue

            raw_pct = ((current_adj - entry_adj) / entry_adj) * 100
            if not math.isfinite(raw_pct):
                skipped += 1
                logger.warning(
                    "Skipping trade %s (%s) %s: non-finite pct (entry=%s current=%s)",
                    tid,
                    ticker,
                    trade.get("transaction_date"),
                    entry_adj,
                    current_adj,
                )
                continue
            pct, pct_clamped = normalize_pct_change_for_db(float(raw_pct))
            if pct_clamped:
                logger.warning(
                    "Clamped pct_change for trade %s (%s) %s: raw=%.2f -> %.2f "
                    "(entry=%s current=%s)",
                    tid,
                    ticker,
                    trade.get("transaction_date"),
                    raw_pct,
                    pct,
                    entry_adj,
                    current_adj,
                )
            midpoint = estimate_midpoint(amount)

            upsert_batch.append({
                "trade_id": tid,
                "entry_price_adj": float(entry_adj),
                "current_price": float(current_adj),
                "pct_change": float(pct),
                "midpoint_est": float(midpoint) if midpoint else None,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "price_source": "yfinance",
            })
            computed += 1

            # Upsert in batches of 500
            if len(upsert_batch) >= 500:
                client.supabase.table("congress_trade_returns") \
                    .upsert(upsert_batch, on_conflict="trade_id") \
                    .execute()
                logger.info("  Upserted batch of %d records (total: %d)", len(upsert_batch), computed)
                upsert_batch = []

        # Final batch
        if upsert_batch:
            client.supabase.table("congress_trade_returns") \
                .upsert(upsert_batch, on_conflict="trade_id") \
                .execute()
            logger.info("  Upserted final batch of %d records (total: %d)", len(upsert_batch), computed)

        # ------------------------------------------------------------------
        # Done
        # ------------------------------------------------------------------
        duration_ms = int((time.time() - start_time) * 1000)
        message = (
            f"Computed returns for {computed:,} trades "
            f"({skipped:,} skipped, {len(unique_tickers)} tickers) "
            f"in {duration_ms / 1000:.1f}s"
        )
        logger.info("Congress trade returns job completed: %s", message)
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=message)

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Congress trade returns job failed: {e}"
        logger.error(message, exc_info=True)
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            mark_job_failed(job_id, target_date, None, str(e), duration_ms=duration_ms)
        except Exception:
            pass


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    compute_congress_trade_returns_job()
