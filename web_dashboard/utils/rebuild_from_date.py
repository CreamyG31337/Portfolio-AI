#!/usr/bin/env python3
"""
Incremental Portfolio Rebuild - Rebuild from specific date onwards

This script rebuilds portfolio positions and metrics from a specific date forward.
Used when backdated trades are entered to recalculate affected historical data.

Can be run as a background subprocess or called directly.
"""

import sys
import os
from pathlib import Path
from datetime import datetime, date, timedelta
from decimal import Decimal
from collections import defaultdict, deque
import logging
from utils.trade_reason import is_dividend_reason

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / 'web_dashboard' / '.env')

# Setup logging - use proper file handler setup
# Try to use the log handler setup if available, otherwise fall back to basicConfig
try:
    from web_dashboard.log_handler import setup_logging
    setup_logging(level=logging.INFO)
    logger = logging.getLogger(__name__)
    # Ensure this module's logger is configured
    if not logger.handlers:
        # If setup_logging didn't attach handlers, use basicConfig as fallback
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
except Exception:
    # Fallback to basicConfig if log_handler setup fails
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)


def rebuild_fund_from_date(fund_name: str, start_date: date, job_id: str = None) -> dict:
    """
    Rebuild portfolio positions and metrics from a specific date forward.
    
    This performs an incremental rebuild by:
    1. Deleting positions/metrics from start_date onwards
    2. Re-processing all trades to recalculate positions
    3. Saving updated snapshots for affected dates
    
    Args:
        fund_name: Fund to rebuild
        start_date: Start date for rebuild (inclusive)
        job_id: Optional job execution ID for tracking
        
    Returns:
        Dict with {'success': bool, 'dates_rebuilt': int, 'positions_updated': int, 'message': str}
    """
    invalidate_dashboard_cache = False
    try:
        logger.info(f"Starting incremental rebuild for {fund_name} from {start_date}")
        
        # Import dependencies
        from web_dashboard.supabase_client import SupabaseClient
        from data.repositories.supabase_repository import SupabaseRepository
        from data.models.portfolio import Position, PortfolioSnapshot
        from market_data.data_fetcher import MarketDataFetcher
        from market_data.market_hours import MarketHours
        from utils.market_holidays import MarketHolidays
        from utils.timezone_utils import get_trading_timezone
        import pandas as pd
        
        # Initialize Supabase client (service role for admin operations)
        client = SupabaseClient(use_service_role=True)
        supabase = client.supabase
        
        # Step 1: Load trades first — avoids deleting positions/metrics when there is nothing to rebuild
        logger.info("Step 1: Loading trade log...")
        if job_id:
            _update_job_status(job_id, 'running', f'Step 1 of 6: Loading trade history from {start_date}')
        
        repository = SupabaseRepository(fund_name=fund_name)
        trades = repository.get_trade_history()
        
        if not trades or len(trades) == 0:
            msg = f"No trades found for fund {fund_name}"
            logger.warning(msg)
            if job_id:
                _update_job_status(job_id, 'success', msg)
            return {
                'success': True,
                'dates_rebuilt': 0,
                'positions_updated': 0,
                'message': msg
            }
        
        logger.info(f"   Loaded {len(trades)} trades")
        
        # Check for cancellation before destructive deletes
        if job_id and _check_job_cancelled(job_id):
            msg = "Rebuild cancelled due to new backdated trade"
            logger.info(msg)
            _update_job_status(job_id, 'failed', msg)
            return {
                'success': False,
                'dates_rebuilt': 0,
                'positions_updated': 0,
                'message': msg
            }
        
        # Step 2: Delete stale data (after we know trades exist)
        invalidate_dashboard_cache = True
        logger.info(f"Step 2: Deleting stale positions from {start_date} onwards...")
        if job_id:
            _update_job_status(job_id, 'running', f'Step 2 of 6: Deleting stale positions from {start_date}')
        
        delete_count_pos = 0
        delete_count_metrics = 0
        
        try:
            # Delete positions
            result = supabase.table("portfolio_positions").delete()\
                .eq("fund", fund_name)\
                .gte("date", f"{start_date}T00:00:00")\
                .execute()
            delete_count_pos = len(result.data) if result.data else 0
            logger.info(f"   Deleted {delete_count_pos} portfolio positions")
            
            # Delete performance metrics
            result = supabase.table("performance_metrics").delete()\
                .eq("fund", fund_name)\
                .gte("date", start_date.isoformat())\
                .execute()
            delete_count_metrics = len(result.data) if result.data else 0
            logger.info(f"   Deleted {delete_count_metrics} performance metrics")
        except Exception as e:
            logger.warning(f"Error during deletion: {e}")
        
        # Step 3: Rebuild positions using FIFO
        logger.info(f"Step 3: Rebuilding positions from {start_date}...")
        if job_id:
            _update_job_status(job_id, 'running', f'Step 3 of 6: Calculating positions for {len(trades)} trades')
        
        # Get trading days from start_date onwards
        market_hours = MarketHours()
        today = datetime.now().date()
        
        # Get all trading days we need to rebuild
        trading_days_to_rebuild = []
        current = start_date
        while current <= today:
            if market_hours.is_trading_day(current):
                trading_days_to_rebuild.append(current)
            current += timedelta(days=1)
        
        logger.info(f"   Need to rebuild {len(trading_days_to_rebuild)} trading days")
        
        # Calculate positions for each day using FIFO
        # We need to process ALL trades from beginning to maintain FIFO integrity
        running_positions = defaultdict(lambda: {
            'shares': Decimal('0'),
            'cost': Decimal('0'),
            'currency': 'USD'
        })
        lots_by_ticker = defaultdict(deque)  # FIFO lot tracking
        
        # Determine if this fund reinvests dividends as shares or
        # receives them as cash.
        fund_type = 'investment'
        dividend_mode = ''
        try:
            ft_result = supabase.table("funds").select("fund_type, dividend_mode")\
                .eq("name", fund_name).limit(1).execute()
            if ft_result.data:
                fund_row = ft_result.data[0]
                if fund_row.get('fund_type'):
                    fund_type = str(fund_row['fund_type']).lower()
                if fund_row.get('dividend_mode'):
                    dividend_mode = str(fund_row['dividend_mode']).lower()
        except Exception:
            pass
        if dividend_mode not in ('cash', 'reinvest'):
            # Legacy fallback during rollout
            dividend_mode = 'cash' if fund_type == 'rrsp' else 'reinvest'
        cash_dividend_fund = dividend_mode == 'cash'

        # Convert trades to DataFrame for easier processing
        trade_data = []
        for trade in trades:
            trade_data.append({
                'Date': trade.timestamp,
                'Ticker': trade.ticker,
                'Shares': float(trade.shares),
                'Price': float(trade.price),
                'Action': trade.action if hasattr(trade, 'action') else 'BUY',
                'Reason': trade.reason if hasattr(trade, 'reason') else '',
                'Currency': trade.currency if hasattr(trade, 'currency') else 'USD'
            })
        trade_df = pd.DataFrame(trade_data)
        trade_df['Date'] = pd.to_datetime(trade_df['Date'])
        trade_df = trade_df.sort_values('Date')
        
        # Build positions day by day
        date_positions = {}
        all_dates = sorted(trade_df['Date'].dt.date.unique())
        
        idx_ticker = trade_df.columns.get_loc("Ticker")
        idx_shares = trade_df.columns.get_loc("Shares")
        idx_price = trade_df.columns.get_loc("Price")
        idx_action = trade_df.columns.get_loc("Action")
        idx_reason = trade_df.columns.get_loc("Reason") if "Reason" in trade_df.columns else -1
        idx_currency = trade_df.columns.get_loc("Currency") if "Currency" in trade_df.columns else -1

        for trading_day in all_dates:
            day_trades = trade_df[trade_df['Date'].dt.date == trading_day]

            for trade in day_trades.itertuples(index=False, name=None):
                ticker = trade[idx_ticker]
                shares = Decimal(str(trade[idx_shares]))
                price = Decimal(str(trade[idx_price]))
                action = str(trade[idx_action]).upper()
                reason = str(
                    (trade[idx_reason] if idx_reason != -1 else "") or ""
                ).upper()

                # Skip dividend events for cash-dividend funds.
                if cash_dividend_fund and is_dividend_reason(reason):
                    continue
                
                if action == 'SELL':
                    # FIFO sell - consume lots
                    remaining = shares
                    while remaining > 0 and lots_by_ticker[ticker]:
                        lot_shares, lot_price = lots_by_ticker[ticker][0]
                        if lot_shares <= remaining:
                            remaining -= lot_shares
                            lots_by_ticker[ticker].popleft()
                        else:
                            lots_by_ticker[ticker][0] = (lot_shares - remaining, lot_price)
                            remaining = Decimal('0')
                    
                    # Update running positions
                    if running_positions[ticker]['shares'] > 0:
                        cost_per_share = running_positions[ticker]['cost'] / running_positions[ticker]['shares']
                        running_positions[ticker]['shares'] -= shares
                        running_positions[ticker]['cost'] -= shares * cost_per_share
                        # Prevent negative
                        if running_positions[ticker]['shares'] < 0:
                            running_positions[ticker]['shares'] = Decimal('0')
                        if running_positions[ticker]['cost'] < 0:
                            running_positions[ticker]['cost'] = Decimal('0')
                else:
                    # BUY - add lot
                    lots_by_ticker[ticker].append((shares, price))
                    running_positions[ticker]['shares'] += shares
                    running_positions[ticker]['cost'] += shares * price
                    running_positions[ticker]['currency'] = (
                        trade[idx_currency] if idx_currency != -1 else "USD"
                    )
            
            # Store positions snapshot for this date
            date_positions[trading_day] = dict(running_positions)
        
        # Step 4: Fetch current prices for positions we need to rebuild
        logger.info("Step 4: Fetching current prices...")
        if job_id:
            _update_job_status(job_id, 'running', f'Step 4 of 6: Fetching market prices for {len(tickers_to_price)} tickers')
        
        # Get unique tickers that have positions in rebuild period
        tickers_to_price = set()
        for trading_day in trading_days_to_rebuild:
            if trading_day in date_positions:
                for ticker in date_positions[trading_day]:
                    if date_positions[trading_day][ticker]['shares'] > 0:
                        tickers_to_price.add(ticker)
        
        logger.info(f"   Fetching prices for {len(tickers_to_price)} tickers")
        
        # Fetch prices - NO FALLBACKS, exact prices only
        fetcher = MarketDataFetcher()
        price_cache = {}  # (ticker, date) -> price
        
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

        # Step 5: Save snapshots for rebuild dates (TRADING DAYS ONLY)
        logger.info("Step 5: Saving updated snapshots...")
        if job_id:
            _update_job_status(job_id, 'running', f'Step 5 of 6: Saving {len(trading_days_to_rebuild)} snapshots')
        
        positions_created = 0
        trading_tz = get_trading_timezone()
        
        for idx, trading_day in enumerate(trading_days_to_rebuild):
            # Check for cancellation periodically (every 10 days or at start)
            if job_id and (idx % 10 == 0 or idx == 0):
                if _check_job_cancelled(job_id):
                    msg = f"Rebuild cancelled after processing {idx} of {len(trading_days_to_rebuild)} days"
                    logger.info(msg)
                    _update_job_status(job_id, 'failed', msg)
                    return {
                        'success': False,
                        'dates_rebuilt': idx,
                        'positions_updated': positions_created,
                        'message': msg
                    }
                # Update progress every 10 days
                if idx > 0 and idx % 10 == 0:
                    progress_pct = int((idx / len(trading_days_to_rebuild)) * 100)
                    _update_job_status(job_id, 'running', f'Step 5 of 6: Saving snapshots ({idx}/{len(trading_days_to_rebuild)}, {progress_pct}%)')
            
            if trading_day not in date_positions:
                continue
                
            positions_on_day = date_positions[trading_day]
            snapshot_positions = []
            
            for ticker, pos_data in positions_on_day.items():
                if pos_data['shares'] <= 0:
                    continue
                
                # Get EXACT price for this trading day - no fallbacks
                current_price = price_cache.get((ticker, trading_day))
                if current_price is None:
                    logger.error(f"CRITICAL: No price for {ticker} on TRADING DAY {trading_day} - skipping position")
                    continue
                
                # Create Position object
                shares = pos_data['shares']
                cost_basis = pos_data['cost']
                avg_price = cost_basis / shares if shares > 0 else Decimal('0')
                market_value = shares * current_price
                pnl = market_value - cost_basis
                
                position = Position(
                    ticker=ticker,
                    shares=shares,
                    avg_price=avg_price,
                    cost_basis=cost_basis,
                    current_price=current_price,
                    market_value=market_value,
                    unrealized_pnl=pnl,
                    currency=pos_data['currency']
                )
                snapshot_positions.append(position)
            
            if snapshot_positions:
                # Create snapshot timestamp (4pm ET on trading day)
                snapshot_time = datetime.combine(trading_day, datetime.min.time().replace(hour=16, minute=0))
                
                # Handle timezone localization compatible with both pytz and zoneinfo
                if hasattr(trading_tz, 'localize'):
                    snapshot_time = trading_tz.localize(snapshot_time)
                else:
                    snapshot_time = snapshot_time.replace(tzinfo=trading_tz)
                
                snapshot = PortfolioSnapshot(
                    positions=snapshot_positions,
                    timestamp=snapshot_time
                )
                
                # Save to database
                try:
                    repository.save_portfolio_snapshot(snapshot)
                    positions_created += len(snapshot_positions)
                except Exception as e:
                    logger.error(f"Failed to save snapshot for {trading_day}: {e}")
        
        # Step 6: Recalculate performance_metrics for rebuilt dates
        # The deletion in Step 2 removed stale metrics; now regenerate them
        # from the freshly rebuilt portfolio_positions.
        logger.info("Step 6: Recalculating performance_metrics for rebuilt dates...")
        if job_id:
            _update_job_status(job_id, 'running', f'Step 6 of 6: Recalculating performance metrics for {len(trading_days_to_rebuild)} days')
        
        metrics_recalculated = 0
        try:
            from scheduler.jobs_metrics import populate_performance_metrics_job
            
            # Exclude today — the daily job handles today after market close
            yesterday = today - timedelta(days=1)
            historical_days = [d for d in trading_days_to_rebuild if d <= yesterday]
            
            if historical_days:
                populate_performance_metrics_job(
                    from_date=min(historical_days),
                    to_date=max(historical_days),
                    fund_filter=fund_name,
                    skip_existing=False  # Force recalc since we just rebuilt positions
                )
                metrics_recalculated = len(historical_days)
                logger.info(f"   Recalculated performance_metrics for {metrics_recalculated} days")
            else:
                logger.info("   No historical days to recalculate (trade is from today)")
        except Exception as e:
            logger.warning(f"   Failed to recalculate performance_metrics: {e}")
            # Non-fatal — the startup gap detection will catch this later
        
        # Success
        msg = (
            f"Rebuilt {len(trading_days_to_rebuild)} days, created {positions_created} position records, "
            f"recalculated {metrics_recalculated} days of performance metrics"
        )
        logger.info(f"✅ Rebuild complete: {msg}")
        
        if job_id:
            _update_job_status(job_id, 'success', msg)
        
        return {
            'success': True,
            'dates_rebuilt': len(trading_days_to_rebuild),
            'positions_updated': positions_created,
            'metrics_recalculated': metrics_recalculated,
            'message': msg
        }
        
    except Exception as e:
        error_msg = f"Rebuild failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        if job_id:
            _update_job_status(job_id, 'failed', error_msg)
        
        return {
            'success': False,
            'dates_rebuilt': 0,
            'positions_updated': 0,
            'message': error_msg
        }
    finally:
        if invalidate_dashboard_cache:
            try:
                from cache_version import bump_cache_version
                bump_cache_version()
                logger.info("Bumped cache version after rebuild (invalidates dashboard chart cache)")
            except Exception as bump_err:
                logger.warning(f"Failed to bump cache version after rebuild: {bump_err}")


def _check_job_cancelled(job_id: str) -> bool:
    """
    Check if a job has been cancelled.
    
    Args:
        job_id: Job execution ID to check (can be string or int)
        
    Returns:
        True if job is cancelled (status is 'failed' with cancellation message), False otherwise
    """
    try:
        from web_dashboard.supabase_client import SupabaseClient
        
        client = SupabaseClient(use_service_role=True)
        # Convert to int if it's a string
        job_id_int = int(job_id) if isinstance(job_id, str) else job_id
        result = client.supabase.table("job_executions").select("status, error_message").eq("id", job_id_int).execute()
        
        if result.data and len(result.data) > 0:
            job = result.data[0]
            status = job.get("status")
            error_message = job.get("error_message", "")
            
            # Check if status is 'failed' and error_message indicates cancellation
            if status == "failed" and "Cancelled:" in str(error_message):
                return True
        
        return False
        
    except Exception as e:
        logger.warning(f"Could not check job cancellation status: {e}")
        return False


def _update_job_status(job_id: str, status: str, message: str):
    """Update job execution status in database."""
    try:
        from web_dashboard.supabase_client import SupabaseClient
        from datetime import datetime, timezone
        client = SupabaseClient(use_service_role=True)
        
        # Convert to int if it's a string
        job_id_int = int(job_id) if isinstance(job_id, str) else job_id
        
        update_data = {
            'status': status
        }
        
        if status in ('success', 'failed'):
            update_data['completed_at'] = datetime.now(timezone.utc).isoformat()
            if status == 'failed':
                update_data['error_message'] = message  # Use error_message instead of output
        
        client.supabase.table("job_executions").update(update_data).eq('id', job_id_int).execute()
    except Exception as e:
        logger.warning(f"Could not update job status: {e}")


def main():
    """CLI entry point for running as subprocess."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Rebuild portfolio from specific date')
    parser.add_argument('fund_name', help='Fund name to rebuild')
    parser.add_argument('start_date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--job-id', help='Job execution ID for tracking')
    
    args = parser.parse_args()
    
    try:
        start_date = datetime.fromisoformat(args.start_date).date()
    except ValueError:
        print(f"Error: Invalid date format '{args.start_date}'. Use YYYY-MM-DD")
        sys.exit(1)
    
    result = rebuild_fund_from_date(args.fund_name, start_date, args.job_id)
    
    print(f"\n{result['message']}")
    print(f"Dates rebuilt: {result['dates_rebuilt']}")
    print(f"Positions updated: {result['positions_updated']}")
    
    sys.exit(0 if result['success'] else 1)


if __name__ == '__main__':
    main()
