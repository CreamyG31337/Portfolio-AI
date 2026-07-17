"""
Congress Positions Job
======================

Computes closed positions from congress_trades by matching buy/sell pairs
for each (politician, ticker) combination.

For each pair:
  - Average all buy prices and all sell prices
  - Estimate dollar invested from midpoint of disclosed amount ranges
  - Compute pct_return = (avg_sell - avg_buy) / avg_buy * 100
  - Compute est_pnl = est_invested * pct_return / 100
  - Fetch SPY return over the same holding period as a reference

A "closed position" is a (politician, ticker) pair where there is at least
one Purchase AND at least one Sale transaction, both with non-null prices.
"""

import logging
import time
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import sys

# Path setup (same pattern as jobs_congress_returns.py)
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

# ---------------------------------------------------------------------------
# Amount range midpoint mapping (shared with jobs_congress_returns)
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


def estimate_midpoint(amount_str: Optional[str]) -> float:
    """Convert an amount range string to its midpoint dollar estimate. Returns 0 if unknown."""
    if not amount_str:
        return 0.0
    amount_str = amount_str.strip()
    if amount_str in AMOUNT_MIDPOINTS:
        return AMOUNT_MIDPOINTS[amount_str]
    for key, val in AMOUNT_MIDPOINTS.items():
        if key.lower() == amount_str.lower():
            return val
    return 0.0


# ---------------------------------------------------------------------------
# SPY price fetching
# ---------------------------------------------------------------------------
def _fetch_spy_returns(
    date_pairs: List[Tuple[str, str]],
) -> Dict[Tuple[str, str], float]:
    """Fetch SPY returns for a list of (start_date, end_date) pairs.

    Downloads SPY history once, then looks up each pair's dates locally.
    Returns dict of (start_date, end_date) -> pct_change.
    """
    import yfinance as yf

    if not date_pairs:
        return {}

    # Find global date range
    all_starts = []
    all_ends = []
    for start_str, end_str in date_pairs:
        try:
            all_starts.append(datetime.strptime(start_str, "%Y-%m-%d").date())
            all_ends.append(datetime.strptime(end_str, "%Y-%m-%d").date())
        except (ValueError, TypeError):
            pass

    if not all_starts or not all_ends:
        return {}

    global_start = min(all_starts) - timedelta(days=5)
    global_end = max(all_ends) + timedelta(days=5)

    logger.info("  Fetching SPY history from %s to %s...", global_start, global_end)
    try:
        data = yf.download(
            "SPY",
            start=global_start.isoformat(),
            end=global_end.isoformat(),
            auto_adjust=True,
            progress=False,
        )
        if data is None or data.empty:
            logger.warning("  No SPY data returned")
            return {}
    except Exception as e:
        logger.warning("  SPY download failed: %s", e)
        return {}

    # Build lookup
    result: Dict[Tuple[str, str], float] = {}
    for start_str, end_str in date_pairs:
        try:
            start_d = datetime.strptime(start_str, "%Y-%m-%d").date()
            end_d = datetime.strptime(end_str, "%Y-%m-%d").date()

            # Find closest date on or after start
            mask_start = data.index.date >= start_d
            if not mask_start.any():
                continue
            spy_start = data.loc[mask_start, "Close"].iloc[0]
            if hasattr(spy_start, "iloc"):
                spy_start = spy_start.iloc[0]

            # Find closest date on or after end
            mask_end = data.index.date >= end_d
            if not mask_end.any():
                # Use last available date
                spy_end_val = data["Close"].iloc[-1]
                if hasattr(spy_end_val, "iloc"):
                    spy_end_val = spy_end_val.iloc[0]
            else:
                spy_end_val = data.loc[mask_end, "Close"].iloc[0]
                if hasattr(spy_end_val, "iloc"):
                    spy_end_val = spy_end_val.iloc[0]

            spy_start_f = float(spy_start)
            spy_end_f = float(spy_end_val)

            if spy_start_f > 0:
                spy_pct = round((spy_end_f - spy_start_f) / spy_start_f * 100, 2)
                result[(start_str, end_str)] = spy_pct
        except Exception:
            pass

    logger.info("  Computed SPY returns for %d/%d date pairs", len(result), len(date_pairs))
    return result


# ---------------------------------------------------------------------------
# Main job
# ---------------------------------------------------------------------------
def compute_congress_positions_job() -> None:
    """Compute closed positions from congress_trades and upsert into congress_positions."""
    job_id = "congress_positions"
    start_time = time.time()

    try:
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        from supabase_client import SupabaseClient

        target_date = datetime.now(timezone.utc).date()
        mark_job_started(job_id, target_date)

        client = SupabaseClient(use_service_role=True)
        logger.info("Congress positions job started")

        # ------------------------------------------------------------------
        # Step 1: Fetch all purchase and sale trades with prices
        # ------------------------------------------------------------------
        logger.info("Step 1: Fetching all purchase and sale trades...")
        all_trades: List[dict] = []
        page_size = 1000
        offset = 0
        while True:
            resp = client.supabase.table("congress_trades") \
                .select("id, politician_id, ticker, type, transaction_date, price, amount") \
                .in_("type", ["Purchase", "Sale"]) \
                .neq("quality_status", "garbage") \
                .not_.is_("price", "null") \
                .order("politician_id") \
                .order("ticker") \
                .order("transaction_date") \
                .range(offset, offset + page_size - 1) \
                .execute()
            batch = resp.data or []
            all_trades.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size

        logger.info("  Fetched %d trades (purchases + sales with prices)", len(all_trades))

        # ------------------------------------------------------------------
        # Step 2: Group by (politician_id, ticker) and compute position stats
        # ------------------------------------------------------------------
        logger.info("Step 2: Computing position-level aggregations...")

        # Group trades
        groups: Dict[Tuple[int, str], List[dict]] = {}
        for trade in all_trades:
            key = (trade["politician_id"], trade["ticker"])
            groups.setdefault(key, []).append(trade)

        positions: List[dict] = []
        date_pairs_needed: List[Tuple[str, str]] = []

        for (politician_id, ticker), trades in groups.items():
            buys = [t for t in trades if t["type"] == "Purchase"]
            sells = [t for t in trades if t["type"] == "Sale"]

            # Only closed positions (has both buys and sells)
            if not buys or not sells:
                continue

            buy_prices = [float(t["price"]) for t in buys if t["price"]]
            sell_prices = [float(t["price"]) for t in sells if t["price"]]

            if not buy_prices or not sell_prices:
                continue

            avg_buy = sum(buy_prices) / len(buy_prices)
            avg_sell = sum(sell_prices) / len(sell_prices)

            if avg_buy <= 0:
                continue

            pct_return = round((avg_sell - avg_buy) / avg_buy * 100, 2)

            # Estimate invested amount from purchase midpoints
            est_invested = sum(estimate_midpoint(t.get("amount")) for t in buys)

            est_pnl = round(est_invested * pct_return / 100, 2) if est_invested > 0 else 0.0

            # Date range
            buy_dates = sorted(t["transaction_date"] for t in buys if t.get("transaction_date"))
            sell_dates = sorted(t["transaction_date"] for t in sells if t.get("transaction_date"))

            first_buy = buy_dates[0] if buy_dates else None
            last_sell = sell_dates[-1] if sell_dates else None

            days_held = None
            if first_buy and last_sell:
                try:
                    fb = datetime.strptime(str(first_buy)[:10], "%Y-%m-%d").date()
                    ls = datetime.strptime(str(last_sell)[:10], "%Y-%m-%d").date()
                    days_held = (ls - fb).days
                    if days_held < 0:
                        days_held = 0  # Sell before buy (data quirk)
                except (ValueError, TypeError):
                    pass

            position = {
                "politician_id": politician_id,
                "ticker": ticker,
                "status": "closed",
                "buy_count": len(buys),
                "sell_count": len(sells),
                "first_buy_date": str(first_buy)[:10] if first_buy else None,
                "last_sell_date": str(last_sell)[:10] if last_sell else None,
                "avg_buy_price": round(avg_buy, 4),
                "avg_sell_price": round(avg_sell, 4),
                "pct_return": pct_return,
                "est_invested": round(est_invested, 2),
                "est_pnl": est_pnl,
                "days_held": days_held,
                "spy_pct_change": None,
                "last_computed": datetime.now(timezone.utc).isoformat(),
            }
            positions.append(position)

            # Collect date pairs for SPY lookup
            if first_buy and last_sell:
                fb_str = str(first_buy)[:10]
                ls_str = str(last_sell)[:10]
                date_pairs_needed.append((fb_str, ls_str))

        logger.info("  Computed %d closed positions", len(positions))

        # ------------------------------------------------------------------
        # Step 3: Fetch SPY returns for holding periods
        # ------------------------------------------------------------------
        logger.info("Step 3: Fetching SPY returns for %d date pairs...", len(date_pairs_needed))
        unique_date_pairs = list(set(date_pairs_needed))
        spy_returns = _fetch_spy_returns(unique_date_pairs)

        # Apply SPY returns to positions
        spy_applied = 0
        for pos in positions:
            fb = pos.get("first_buy_date")
            ls = pos.get("last_sell_date")
            if fb and ls:
                spy_pct = spy_returns.get((fb, ls))
                if spy_pct is not None:
                    pos["spy_pct_change"] = spy_pct
                    spy_applied += 1

        logger.info("  Applied SPY returns to %d/%d positions", spy_applied, len(positions))

        # ------------------------------------------------------------------
        # Step 4: Upsert into congress_positions
        # ------------------------------------------------------------------
        logger.info("Step 4: Upserting %d positions...", len(positions))
        UPSERT_BATCH = 500

        for i in range(0, len(positions), UPSERT_BATCH):
            batch = positions[i:i + UPSERT_BATCH]
            client.supabase.table("congress_positions") \
                .upsert(batch, on_conflict="politician_id,ticker") \
                .execute()
            total_so_far = min(i + UPSERT_BATCH, len(positions))
            if total_so_far < len(positions):
                logger.info("  Upserted batch of %d records (total: %d)", len(batch), total_so_far)

        logger.info("  Upserted all %d positions", len(positions))

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        wins = sum(1 for p in positions if p["pct_return"] > 0)
        losses = len(positions) - wins
        elapsed = time.time() - start_time

        message = (
            f"Congress positions job completed: {len(positions)} closed positions "
            f"({wins} wins, {losses} losses, SPY ref for {spy_applied}) in {elapsed:.1f}s"
        )
        logger.info(message)

        duration_ms = int(elapsed * 1000)
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        mark_job_completed(
            job_id,
            target_date,
            None,
            [],
            duration_ms=duration_ms,
            message=message,
        )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Congress positions job failed: {e}"
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
    compute_congress_positions_job()
