#!/usr/bin/env python3
"""
Incremental Portfolio Rebuild - Rebuild from specific date onwards

This script rebuilds portfolio positions and metrics from a specific date forward.
Used when backdated trades are entered to recalculate affected historical data.

Can be run as a background subprocess or called directly.

Safety (F6): dry_run defaults off here but manual_rebuild.py defaults to dry-run.
Day-loss guard aborts before deletes unless --allow-day-loss is passed.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
from datetime import datetime, date, timedelta
from decimal import Decimal
from collections import defaultdict, deque
import logging
import time
from typing import Any

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / 'web_dashboard' / '.env')

# Setup logging
try:
    from web_dashboard.log_handler import setup_logging
    setup_logging(level=logging.INFO)
    logger = logging.getLogger(__name__)
    if not logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
except Exception:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)


def _snapshot_positions_dict(
    running_positions: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Deep-copy per-ticker position dicts so later mutations cannot alias history."""
    return {ticker: dict(pos) for ticker, pos in running_positions.items()}


def _apply_trade_to_positions(
    *,
    ticker: str,
    shares: Decimal,
    price: Decimal,
    action: str,
    currency: str,
    running_positions: dict[str, dict[str, Any]],
    lots_by_ticker: dict[str, deque],
) -> None:
    """Mutate running FIFO state for one trade."""
    if action == "SELL":
        remaining = shares
        while remaining > 0 and lots_by_ticker[ticker]:
            lot_shares, lot_price = lots_by_ticker[ticker][0]
            if lot_shares <= remaining:
                remaining -= lot_shares
                lots_by_ticker[ticker].popleft()
            else:
                lots_by_ticker[ticker][0] = (lot_shares - remaining, lot_price)
                remaining = Decimal("0")

        if running_positions[ticker]["shares"] > 0:
            cost_per_share = (
                running_positions[ticker]["cost"] / running_positions[ticker]["shares"]
            )
            running_positions[ticker]["shares"] -= shares
            running_positions[ticker]["cost"] -= shares * cost_per_share
            if running_positions[ticker]["shares"] < 0:
                running_positions[ticker]["shares"] = Decimal("0")
            if running_positions[ticker]["cost"] < 0:
                running_positions[ticker]["cost"] = Decimal("0")
    else:
        # BUY (and any non-SELL / non-DIVIDEND action already filtered by caller)
        lots_by_ticker[ticker].append((shares, price))
        running_positions[ticker]["shares"] += shares
        running_positions[ticker]["cost"] += shares * price
        running_positions[ticker]["currency"] = currency


def rebuild_fund_from_date(
    fund_name: str,
    start_date: date,
    job_id: str = None,
    *,
    dry_run: bool = False,
    allow_day_loss: bool = False,
) -> dict:
    """
    Rebuild portfolio positions and metrics from a specific date forward.

    Args:
        fund_name: Fund to rebuild
        start_date: Start date for rebuild (inclusive)
        job_id: Optional job execution ID for tracking
        dry_run: If True, plan everything but do not delete or write
        allow_day_loss: If False (default), abort when writable days < trading days
            on/after the first trade date

    Returns:
        Dict with success, dates_rebuilt, positions_updated, message, and dry_run flag
    """
    invalidate_dashboard_cache = False
    try:
        mode = "DRY-RUN" if dry_run else "APPLY"
        logger.info(
            f"Starting incremental rebuild ({mode}) for {fund_name} from {start_date}"
        )

        from web_dashboard.supabase_client import SupabaseClient
        from data.repositories.supabase_repository import SupabaseRepository
        from data.models.portfolio import Position, PortfolioSnapshot
        from market_data.data_fetcher import MarketDataFetcher
        from market_data.market_hours import MarketHours
        from utils.timezone_utils import get_trading_timezone
        import pandas as pd

        client = SupabaseClient(use_service_role=True)
        supabase = client.supabase

        # Step 1: Load trades first — avoids deleting when there is nothing to rebuild
        logger.info("Step 1: Loading trade log...")
        if job_id:
            _update_job_status(
                job_id, "running", f"Step 1 of 6: Loading trade history from {start_date}"
            )

        repository = SupabaseRepository(fund_name=fund_name)
        trades = repository.get_trade_history()

        if not trades or len(trades) == 0:
            msg = f"No trades found for fund {fund_name}"
            logger.warning(msg)
            if job_id:
                _update_job_status(job_id, "success", msg)
            return {
                "success": True,
                "dates_rebuilt": 0,
                "positions_updated": 0,
                "message": msg,
                "dry_run": dry_run,
            }

        logger.info(f"   Loaded {len(trades)} trades")

        if job_id and _check_job_cancelled(job_id):
            msg = "Rebuild cancelled due to new backdated trade"
            logger.info(msg)
            _update_job_status(job_id, "failed", msg)
            return {
                "success": False,
                "dates_rebuilt": 0,
                "positions_updated": 0,
                "message": msg,
                "dry_run": dry_run,
            }

        # Step 2 (planning): trading days + FIFO positions for EVERY trading day
        logger.info(f"Step 2: Planning positions from {start_date}...")
        if job_id:
            _update_job_status(
                job_id,
                "running",
                f"Step 2 of 6: Calculating positions for {len(trades)} trades",
            )

        market_hours = MarketHours()
        today = datetime.now().date()

        trading_days_to_rebuild: list[date] = []
        current = start_date
        while current <= today:
            if market_hours.is_trading_day(current):
                trading_days_to_rebuild.append(current)
            current += timedelta(days=1)

        logger.info(f"   Need to rebuild {len(trading_days_to_rebuild)} trading days")

        running_positions: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"shares": Decimal("0"), "cost": Decimal("0"), "currency": "USD"}
        )
        lots_by_ticker: dict[str, deque] = defaultdict(deque)

        fund_type = "investment"
        dividend_mode = ""
        try:
            ft_result = (
                supabase.table("funds")
                .select("fund_type, dividend_mode")
                .eq("name", fund_name)
                .limit(1)
                .execute()
            )
            if ft_result.data:
                fund_row = ft_result.data[0]
                if fund_row.get("fund_type"):
                    fund_type = str(fund_row["fund_type"]).lower()
                if fund_row.get("dividend_mode"):
                    dividend_mode = str(fund_row["dividend_mode"]).lower()
        except Exception:
            pass
        if dividend_mode not in ("cash", "reinvest"):
            dividend_mode = "cash" if fund_type == "rrsp" else "reinvest"
        cash_dividend_fund = dividend_mode == "cash"

        trade_data = []
        for trade in trades:
            trade_data.append(
                {
                    "Date": trade.timestamp,
                    "Ticker": trade.ticker,
                    "Shares": float(trade.shares),
                    "Price": float(trade.price),
                    "Action": trade.action if hasattr(trade, "action") else "BUY",
                    "Reason": trade.reason if hasattr(trade, "reason") else "",
                    "Currency": trade.currency if hasattr(trade, "currency") else "USD",
                }
            )
        trade_df = pd.DataFrame(trade_data)
        trade_df["Date"] = pd.to_datetime(trade_df["Date"])
        trade_df = trade_df.sort_values("Date")

        first_trade_date = trade_df["Date"].dt.date.min()

        idx_date = trade_df.columns.get_loc("Date")
        idx_ticker = trade_df.columns.get_loc("Ticker")
        idx_shares = trade_df.columns.get_loc("Shares")
        idx_price = trade_df.columns.get_loc("Price")
        idx_action = trade_df.columns.get_loc("Action")
        idx_currency = (
            trade_df.columns.get_loc("Currency") if "Currency" in trade_df.columns else -1
        )

        def _apply_row(trade: tuple) -> None:
            ticker = trade[idx_ticker]
            shares = Decimal(str(trade[idx_shares]))
            price = Decimal(str(trade[idx_price]))
            action = str(trade[idx_action]).upper()
            currency = trade[idx_currency] if idx_currency != -1 else "USD"

            # F4: skip dividends by action column only (not reason prose)
            if cash_dividend_fund and action == "DIVIDEND":
                return

            _apply_trade_to_positions(
                ticker=ticker,
                shares=shares,
                price=price,
                action=action,
                currency=str(currency or "USD"),
                running_positions=running_positions,
                lots_by_ticker=lots_by_ticker,
            )

        def _row_date(trade: tuple) -> date:
            raw = trade[idx_date]
            return raw.date() if hasattr(raw, "date") else raw

        # Advancing cursor over sorted trades: seed (< start_date) then apply
        # everything with date <= trading_day. Matches backfill's
        # trades_up_to_date (<=) semantics so off-calendar DRIPs are not dropped.
        rows = list(trade_df.itertuples(index=False, name=None))
        i = 0
        seeded = 0
        while i < len(rows) and _row_date(rows[i]) < start_date:
            _apply_row(rows[i])
            i += 1
            seeded += 1
        if seeded:
            logger.info(f"   Seeded FIFO from {seeded} trade(s) before {start_date}")

        date_positions: dict[date, dict[str, dict[str, Any]]] = {}
        for trading_day in trading_days_to_rebuild:
            while i < len(rows) and _row_date(rows[i]) <= trading_day:
                _apply_row(rows[i])
                i += 1
            date_positions[trading_day] = _snapshot_positions_dict(running_positions)

        # Step 3: Fetch prices (F1: tickers_to_price BEFORE job status update)
        logger.info("Step 3: Fetching market prices...")
        tickers_to_price: set[str] = set()
        for trading_day in trading_days_to_rebuild:
            for ticker, pos in date_positions.get(trading_day, {}).items():
                if pos["shares"] > 0:
                    tickers_to_price.add(ticker)

        if job_id:
            _update_job_status(
                job_id,
                "running",
                f"Step 4 of 6: Fetching market prices for {len(tickers_to_price)} tickers",
            )

        logger.info(f"   Fetching prices for {len(tickers_to_price)} tickers")

        fetcher = MarketDataFetcher()
        price_cache: dict[tuple[str, date], Decimal] = {}

        for ticker in tickers_to_price:
            try:
                start_dt = datetime.combine(start_date, datetime.min.time())
                end_dt = datetime.combine(today, datetime.max.time())
                result = fetcher.fetch_price_data(ticker, start=start_dt, end=end_dt)

                if result.df is not None and not result.df.empty:
                    idx_close = result.df.columns.get_loc("Close")
                    for idx, row in zip(
                        result.df.index, result.df.itertuples(index=False, name=None)
                    ):
                        price_date = idx.date() if hasattr(idx, "date") else idx
                        price = Decimal(str(row[idx_close]))
                        if price > 0:
                            price_cache[(ticker, price_date)] = price
            except Exception as e:
                logger.warning(f"Failed to fetch prices for {ticker}: {e}")

        # Step 4: Plan snapshots with carry-forward (F5); never write partial days
        trading_tz = get_trading_timezone()
        last_price_by_ticker: dict[str, Decimal] = {}
        last_price_date_by_ticker: dict[str, date] = {}
        planned_snapshots: list[tuple[date, list]] = []
        missing_price_days: dict[str, list[date]] = defaultdict(list)
        carry_forward_days: dict[str, list[tuple[date, date]]] = defaultdict(list)
        days_skipped_no_price = 0

        for trading_day in trading_days_to_rebuild:
            positions_on_day = date_positions.get(trading_day, {})
            holdings = {
                t: p for t, p in positions_on_day.items() if p["shares"] > 0
            }
            if not holdings:
                continue

            # Resolve prices for all holdings first — abort the day if any lack a price
            resolved: dict[str, Decimal] = {}
            day_ok = True
            for ticker in holdings:
                current_price = price_cache.get((ticker, trading_day))
                used_carry = False
                if current_price is None:
                    current_price = last_price_by_ticker.get(ticker)
                    used_carry = current_price is not None
                if current_price is None:
                    missing_price_days[ticker].append(trading_day)
                    day_ok = False
                    break
                if used_carry:
                    src = last_price_date_by_ticker.get(ticker, trading_day)
                    carry_forward_days[ticker].append((trading_day, src))
                resolved[ticker] = current_price

            if not day_ok:
                days_skipped_no_price += 1
                logger.error(
                    f"CRITICAL: Incomplete prices for {trading_day} — skipping entire day "
                    f"(held: {sorted(holdings)})"
                )
                continue

            snapshot_positions = []
            for ticker, pos_data in holdings.items():
                current_price = resolved[ticker]
                last_price_by_ticker[ticker] = current_price
                if (ticker, trading_day) in price_cache:
                    last_price_date_by_ticker[ticker] = trading_day
                shares = pos_data["shares"]
                cost_basis = pos_data["cost"]
                avg_price = cost_basis / shares if shares > 0 else Decimal("0")
                market_value = shares * current_price
                pnl = market_value - cost_basis
                snapshot_positions.append(
                    Position(
                        ticker=ticker,
                        shares=shares,
                        avg_price=avg_price,
                        cost_basis=cost_basis,
                        current_price=current_price,
                        market_value=market_value,
                        unrealized_pnl=pnl,
                        currency=pos_data["currency"],
                    )
                )
            planned_snapshots.append((trading_day, snapshot_positions))

        # Relevant days = trading days on/after first trade (pre-trade empties are fine)
        relevant_days = [d for d in trading_days_to_rebuild if d >= first_trade_date]
        # Days that should have holdings after first trade
        days_with_holdings = [
            d
            for d in relevant_days
            if any(
                p["shares"] > 0 for p in date_positions.get(d, {}).values()
            )
        ]
        writable_days = [d for d, _ in planned_snapshots]
        days_lost = len(days_with_holdings) - len(writable_days)

        # Count rows that would be deleted (best-effort; mocks may return 0)
        would_delete_pos = 0
        would_delete_metrics = 0
        try:
            pos_count = (
                supabase.table("portfolio_positions")
                .select("id", count="exact")
                .eq("fund", fund_name)
                .gte("date", f"{start_date}T00:00:00")
                .execute()
            )
            would_delete_pos = getattr(pos_count, "count", None) or len(
                pos_count.data or []
            )
            met_count = (
                supabase.table("performance_metrics")
                .select("id", count="exact")
                .eq("fund", fund_name)
                .gte("date", start_date.isoformat())
                .execute()
            )
            would_delete_metrics = getattr(met_count, "count", None) or len(
                met_count.data or []
            )
        except Exception as e:
            logger.warning(f"Could not count rows for dry-run summary: {e}")

        would_write_pos = sum(len(pos) for _, pos in planned_snapshots)
        summary_lines = [
            f"Fund: {fund_name}   Range: {start_date} .. {today}",
            f"Would DELETE  {would_delete_pos:,} position rows / {would_delete_metrics:,} metric rows",
            f"Would WRITE   {would_write_pos:,} position rows / {len(writable_days):,} metric days",
            f"Days covered: {len(writable_days)} of {len(days_with_holdings)} holding-days "
            f"({max(days_lost, 0)} days would be lost)",
        ]
        if carry_forward_days:
            cf_parts = []
            for t, pairs in sorted(carry_forward_days.items()):
                shown = ", ".join(f"{d}←{src}" for d, src in pairs[:5])
                extra = "..." if len(pairs) > 5 else ""
                cf_parts.append(f"{t} ({len(pairs)} days: {shown}{extra})")
            summary_lines.append("Price carry-forwards: " + "; ".join(cf_parts))
        if missing_price_days:
            miss_parts = [
                f"{t} ({len(ds)} days: {', '.join(str(x) for x in ds[:5])}"
                + ("..." if len(ds) > 5 else "")
                + ")"
                for t, ds in sorted(missing_price_days.items())
            ]
            summary_lines.append(
                "Tickers with missing prices (no prior close): " + "; ".join(miss_parts)
            )
        summary = "\n".join(summary_lines)
        logger.info("Rebuild plan:\n%s", summary)

        # F6: day-loss guard — abort BEFORE deletes
        if days_lost > 0 and not allow_day_loss:
            msg = (
                f"Aborting rebuild: would lose {days_lost} day(s) "
                f"(writable {len(writable_days)} < holding-days {len(days_with_holdings)}). "
                f"Pass allow_day_loss=True / --allow-day-loss to override.\n{summary}"
            )
            logger.error(msg)
            if job_id:
                _update_job_status(job_id, "failed", msg)
            return {
                "success": False,
                "dates_rebuilt": 0,
                "positions_updated": 0,
                "message": msg,
                "dry_run": dry_run,
                "days_lost": days_lost,
            }

        if dry_run:
            msg = f"DRY-RUN only — no deletes or writes.\n{summary}"
            logger.info(msg)
            if job_id:
                _update_job_status(job_id, "success", msg)
            return {
                "success": True,
                "dates_rebuilt": len(writable_days),
                "positions_updated": would_write_pos,
                "message": msg,
                "dry_run": True,
                "days_lost": max(days_lost, 0),
            }

        # Step 5: Deletes (only after guard passes)
        invalidate_dashboard_cache = True
        logger.info(f"Step 5: Deleting stale positions from {start_date} onwards...")
        if job_id:
            _update_job_status(
                job_id,
                "running",
                f"Step 5 of 6: Deleting stale positions from {start_date}",
            )

        delete_count_pos = 0
        delete_count_metrics = 0
        try:
            result = (
                supabase.table("portfolio_positions")
                .delete()
                .eq("fund", fund_name)
                .gte("date", f"{start_date}T00:00:00")
                .execute()
            )
            delete_count_pos = len(result.data) if result.data else 0
            logger.info(f"   Deleted {delete_count_pos} portfolio positions")

            result = (
                supabase.table("performance_metrics")
                .delete()
                .eq("fund", fund_name)
                .gte("date", start_date.isoformat())
                .execute()
            )
            delete_count_metrics = len(result.data) if result.data else 0
            logger.info(f"   Deleted {delete_count_metrics} performance metrics")
        except Exception as e:
            logger.warning(f"Error during deletion: {e}")

        # Step 6: Write planned snapshots
        logger.info("Step 6: Saving updated snapshots...")
        if job_id:
            _update_job_status(
                job_id,
                "running",
                f"Step 6 of 6: Saving {len(planned_snapshots)} snapshots",
            )

        positions_created = 0
        day_write_seconds: list[float] = []
        for idx, (trading_day, snapshot_positions) in enumerate(planned_snapshots):
            if job_id and (idx % 10 == 0 or idx == 0):
                if _check_job_cancelled(job_id):
                    msg = (
                        f"Rebuild cancelled after processing {idx} of "
                        f"{len(planned_snapshots)} days"
                    )
                    logger.info(msg)
                    _update_job_status(job_id, "failed", msg)
                    return {
                        "success": False,
                        "dates_rebuilt": idx,
                        "positions_updated": positions_created,
                        "message": msg,
                        "dry_run": False,
                    }
                if idx > 0 and idx % 10 == 0:
                    progress_pct = int((idx / len(planned_snapshots)) * 100)
                    _update_job_status(
                        job_id,
                        "running",
                        f"Step 6 of 6: Saving snapshots "
                        f"({idx}/{len(planned_snapshots)}, {progress_pct}%)",
                    )

            snapshot_time = datetime.combine(
                trading_day, datetime.min.time().replace(hour=16, minute=0)
            )
            if hasattr(trading_tz, "localize"):
                snapshot_time = trading_tz.localize(snapshot_time)
            else:
                snapshot_time = snapshot_time.replace(tzinfo=trading_tz)

            snapshot = PortfolioSnapshot(
                positions=snapshot_positions,
                timestamp=snapshot_time,
            )
            try:
                t0 = time.perf_counter()
                repository.save_portfolio_snapshot(snapshot)
                elapsed = time.perf_counter() - t0
                day_write_seconds.append(elapsed)
                positions_created += len(snapshot_positions)
                logger.info(
                    f"   Saved {trading_day} ({len(snapshot_positions)} pos) in {elapsed:.2f}s"
                )
            except Exception as e:
                logger.error(f"Failed to save snapshot for {trading_day}: {e}")
        if day_write_seconds:
            avg_s = sum(day_write_seconds) / len(day_write_seconds)
            logger.info(
                f"   Write-path timing: {len(day_write_seconds)} days, "
                f"min={min(day_write_seconds):.2f}s avg={avg_s:.2f}s "
                f"max={max(day_write_seconds):.2f}s "
                f"(fx_cache={len(getattr(repository, '_fx_cache', {}))}, "
                f"verified_tickers={len(getattr(repository, '_verified_tickers', ()))})"
            )

        # Recalculate performance_metrics for rebuilt dates
        logger.info("Recalculating performance_metrics for rebuilt dates...")
        metrics_recalculated = 0
        try:
            from scheduler.jobs_metrics import populate_performance_metrics_job

            yesterday = today - timedelta(days=1)
            historical_days = [d for d in writable_days if d <= yesterday]

            if historical_days:
                populate_performance_metrics_job(
                    from_date=min(historical_days),
                    to_date=max(historical_days),
                    fund_filter=fund_name,
                    skip_existing=False,
                )
                metrics_recalculated = len(historical_days)
                logger.info(
                    f"   Recalculated performance_metrics for {metrics_recalculated} days"
                )
            else:
                logger.info("   No historical days to recalculate (trade is from today)")
        except Exception as e:
            logger.warning(f"   Failed to recalculate performance_metrics: {e}")

        msg = (
            f"Rebuilt {len(writable_days)} days, created {positions_created} position records, "
            f"recalculated {metrics_recalculated} days of performance metrics"
        )
        logger.info(f"✅ Rebuild complete: {msg}")

        if job_id:
            _update_job_status(job_id, "success", msg)

        return {
            "success": True,
            "dates_rebuilt": len(writable_days),
            "positions_updated": positions_created,
            "metrics_recalculated": metrics_recalculated,
            "message": msg,
            "dry_run": False,
            "days_lost": max(days_lost, 0),
        }

    except Exception as e:
        error_msg = f"Rebuild failed: {str(e)}"
        logger.error(error_msg, exc_info=True)

        if job_id:
            _update_job_status(job_id, "failed", error_msg)

        return {
            "success": False,
            "dates_rebuilt": 0,
            "positions_updated": 0,
            "message": error_msg,
            "dry_run": dry_run,
        }
    finally:
        if invalidate_dashboard_cache:
            try:
                from cache_version import bump_cache_version

                bump_cache_version()
                logger.info(
                    "Bumped cache version after rebuild (invalidates dashboard chart cache)"
                )
            except Exception as bump_err:
                logger.warning(
                    f"Failed to bump cache version after rebuild: {bump_err}"
                )


def _check_job_cancelled(job_id: str) -> bool:
    """Return True if job is cancelled (failed with Cancelled: message)."""
    try:
        from web_dashboard.supabase_client import SupabaseClient

        client = SupabaseClient(use_service_role=True)
        job_id_int = int(job_id) if isinstance(job_id, str) else job_id
        result = (
            client.supabase.table("job_executions")
            .select("status, error_message")
            .eq("id", job_id_int)
            .execute()
        )

        if result.data and len(result.data) > 0:
            job = result.data[0]
            status = job.get("status")
            error_message = job.get("error_message", "")
            if status == "failed" and "Cancelled:" in str(error_message):
                return True

        return False

    except Exception as e:
        logger.warning(f"Could not check job cancellation status: {e}")
        return False


def _update_job_status(job_id: str, status: str, message: str) -> None:
    """Update job execution status in database."""
    try:
        from web_dashboard.supabase_client import SupabaseClient
        from datetime import timezone

        client = SupabaseClient(use_service_role=True)
        job_id_int = int(job_id) if isinstance(job_id, str) else job_id

        update_data: dict[str, Any] = {"status": status}

        if status in ("success", "failed"):
            update_data["completed_at"] = datetime.now(timezone.utc).isoformat()
            if status == "failed":
                update_data["error_message"] = message

        client.supabase.table("job_executions").update(update_data).eq(
            "id", job_id_int
        ).execute()
    except Exception as e:
        logger.warning(f"Could not update job status: {e}")


def main() -> None:
    """CLI entry point for running as subprocess."""
    import argparse

    parser = argparse.ArgumentParser(description="Rebuild portfolio from specific date")
    parser.add_argument("fund_name", help="Fund name to rebuild")
    parser.add_argument("start_date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--job-id", help="Job execution ID for tracking")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only — do not delete or write",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete/write (required unless --dry-run)",
    )
    parser.add_argument(
        "--allow-day-loss",
        action="store_true",
        help="Allow writing fewer days than the holding-day span",
    )

    args = parser.parse_args()

    try:
        start_date = datetime.fromisoformat(args.start_date).date()
    except ValueError:
        print(f"Error: Invalid date format '{args.start_date}'. Use YYYY-MM-DD")
        sys.exit(1)

    if args.apply and args.dry_run:
        print("Error: pass only one of --dry-run / --apply")
        sys.exit(1)

    # Subprocess default: apply when --job-id is present (background rebuild path),
    # otherwise require explicit --apply (interactive safety).
    if args.job_id and not args.dry_run:
        dry_run = False
    elif args.apply:
        dry_run = False
    else:
        dry_run = True

    result = rebuild_fund_from_date(
        args.fund_name,
        start_date,
        args.job_id,
        dry_run=dry_run,
        allow_day_loss=args.allow_day_loss,
    )

    print(f"\n{result['message']}")
    print(f"Dates rebuilt: {result['dates_rebuilt']}")
    print(f"Positions updated: {result['positions_updated']}")
    print(f"Dry run: {result.get('dry_run')}")

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
