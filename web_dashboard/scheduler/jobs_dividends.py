"""
Dividend Processing Job
========================
Automated dividend detection and DRIP reinvestment processing.

Strategy:
1. Nasdaq API (Primary for US stocks) - Exact Payment Dates
2. YahooQuery (Secondary) - Global coverage, better Payment Dates
3. Yfinance (Fallback) - Reliable Ex-Dates (used as proxy for Pay Date if needed)
"""

import logging
import time
import requests
import json
import base64
from datetime import datetime, date, timedelta, time as dt_time
from typing import Dict, List, Optional, Tuple, NamedTuple
from decimal import Decimal
import pytz
from dataclasses import dataclass

# Add project root to path for utils imports
import sys
from pathlib import Path

# Get current directory
current_dir = Path(__file__).resolve().parent

# Logic to find project root:
# 1. If we are in 'scheduler' subdir, go up 2 levels
if current_dir.name == 'scheduler':
    project_root = current_dir.parent.parent
# 2. If we are in 'web_dashboard/scheduler', go up 2 levels
elif current_dir.parent.name == 'web_dashboard':
    project_root = current_dir.parent.parent
# 3. Fallback: go up 2 levels anyway
else:
    project_root = current_dir.parent.parent

# Also ensure web_dashboard is in path for supabase_client imports
web_dashboard_path = str(project_root / 'web_dashboard')
if web_dashboard_path not in sys.path:
    sys.path.insert(0, web_dashboard_path)

# CRITICAL: Project root must be inserted LAST (at index 0) to ensure it comes
# BEFORE web_dashboard in sys.path. This prevents web_dashboard/utils from
# shadowing the project root's utils package.
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
elif sys.path[0] != str(project_root):
    # If it is in path but not first, move it to front
    sys.path.remove(str(project_root))
    sys.path.insert(0, str(project_root))

from scheduler.scheduler_core import log_job_execution

logger = logging.getLogger(__name__)


@dataclass
class DividendEvent:
    """Standardized dividend event data."""
    ex_date: date
    pay_date: date
    amount: float
    source: str  # 'nasdaq', 'yahooquery', 'yfinance'


def is_canadian_ticker(ticker: str) -> bool:
    """Check if ticker is Canadian based on suffix."""
    ticker = ticker.upper().strip()
    canadian_suffixes = ('.TO', '.V', '.CN', '.NE', '.TSX')
    return ticker.endswith(canadian_suffixes)


def get_fund_type(fund_name: str, client) -> str:
    """Get fund type from database or fallback to config file."""
    try:
        # Try database first
        fund_result = client.supabase.table("funds")\
            .select("fund_type")\
            .eq("name", fund_name)\
            .execute()
        
        if fund_result.data and fund_result.data[0].get('fund_type'):
            return fund_result.data[0]['fund_type'].lower()
    except Exception as e:
        logger.debug(f"Could not get fund_type from database for {fund_name}: {e}")
    
    # Fallback to config file
    try:
        from utils.fund_manager import get_fund_manager
        fund_manager = get_fund_manager()
        config = fund_manager.get_fund_config(fund_name)
        if config and config.get('fund', {}).get('fund_type'):
            return config['fund']['fund_type'].lower()
    except Exception as e:
        pass
    
    # Default fallback
    return 'investment'


def calculate_withholding_tax(gross_amount: Decimal, fund_type: str, ticker: str) -> Decimal:
    """
    Apply Canadian withholding tax rules:
    - US stocks in TFSA/Personal: 15% tax
    - US stocks in RRSP: 0% tax (treaty protection)
    - Canadian stocks: 0% tax (any account)
    """
    if is_canadian_ticker(ticker):
        return Decimal('0')
    
    fund_type_lower = fund_type.lower()
    
    # Standardized Rule: RRSP gets 0% (treaty), everything else gets 15%
    if fund_type_lower == 'rrsp':
        return Decimal('0')
    
    return gross_amount * Decimal('0.15')  # Default 15% for TFSA, Investment, Margin, etc.


def get_unique_holdings(client) -> List[Tuple[str, str]]:
    """Get all unique (fund, ticker) pairs from portfolio_positions where shares > 0."""
    try:
        result = client.supabase.table("portfolio_positions")\
            .select("fund, ticker")\
            .gt("shares", 0)\
            .execute()
        
        unique_pairs = set()
        for row in result.data:
            unique_pairs.add((row['fund'], row['ticker']))
        
        return list(unique_pairs)
    except Exception as e:
        logger.error(f"Error getting unique holdings: {e}")
        return []


# ============================================================================
# DATA FETCHING LAYERS
# ============================================================================

def fetch_dividends_nasdaq(ticker: str) -> List[DividendEvent]:
    """Layer 1: Fetch dividends from Nasdaq API (US Only)."""
    # Skip Canadian/non-US tickers
    if is_canadian_ticker(ticker) or '.' in ticker:
        return []

    # Base URLs (obfuscated)
    _NASDAQ_API_ENCODED = "aHR0cHM6Ly9hcGkubmFzZGFxLmNvbQ=="
    _NASDAQ_WWW_ENCODED = "aHR0cHM6Ly93d3cubmFzZGFxLmNvbQ=="
    _NASDAQ_API = base64.b64decode(_NASDAQ_API_ENCODED).decode('utf-8')
    _NASDAQ_WWW = base64.b64decode(_NASDAQ_WWW_ENCODED).decode('utf-8')
    
    try:
        url = f"{_NASDAQ_API}/api/quote/{ticker}/dividends?assetclass=stocks"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Origin': _NASDAQ_WWW,
            'Referer': f'{_NASDAQ_WWW}/market-activity/stocks/{ticker.lower()}/dividend-history'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return []
            
        data = response.json()
        events = []
        
        if data and data.get('data') and data['data'].get('dividends'):
            rows = data['data']['dividends'].get('rows', [])
            for row in rows:
                try:
                    ex_date_str = row.get('exOrEffDate')
                    pay_date_str = row.get('paymentDate')
                    amount_str = row.get('amount', '').replace('$', '')
                    
                    if not ex_date_str or not pay_date_str:
                        continue
                        
                    ex_date = datetime.strptime(ex_date_str, '%m/%d/%Y').date()
                    pay_date = datetime.strptime(pay_date_str, '%m/%d/%Y').date()
                    amount = float(amount_str)
                    
                    events.append(DividendEvent(
                        ex_date=ex_date,
                        pay_date=pay_date,
                        amount=amount,
                        source='nasdaq'
                    ))
                except (ValueError, TypeError):
                    continue
                    
        return events
    except Exception as e:
        logger.debug(f"Nasdaq API failed for {ticker}: {e}")
        return []


def fetch_dividends_yahooquery(ticker: str) -> List[DividendEvent]:
    """Layer 2: Fetch dividends from YahooQuery (Global)."""
    try:
        from yahooquery import Ticker
        tk = Ticker(ticker)
        events = []
        
        # Method A: Calendar Events (Future/Recent)
        try:
            cal = tk.calendar_events
            if isinstance(cal, dict) and ticker in cal:
                data = cal[ticker]
                # Check for dividend date
                if 'dividendDate' in data and 'exDividendDate' in data:
                    pay_str = data['dividendDate']
                    ex_str = data['exDividendDate']
                    
                    # Yahoo timestamps are often full strings
                    # e.g. "2026-02-16 16:00:00"
                    if pay_str and ex_str:
                        pay_date = datetime.fromisoformat(str(pay_str)).date()
                        ex_date = datetime.fromisoformat(str(ex_str)).date()
                        
                        # Try to find amount from summary_detail
                        amount = 0.0
                        summary = tk.summary_detail
                        if isinstance(summary, dict) and ticker in summary:
                            amount = float(summary[ticker].get('dividendRate', 0) / 4) # Crude estimate (annual/4)
                        
                        if amount > 0:
                            events.append(DividendEvent(
                                ex_date=ex_date,
                                pay_date=pay_date,
                                amount=amount,
                                source='yahooquery_cal'
                            ))
        except Exception:
            pass

        # Method B: History (Historical Pay Dates are NOT in history, only Ex-Dates)
        # So we skip parsing history here and leave that to yfinance fallback
        
        return events
    except Exception as e:
        logger.debug(f"YahooQuery failed for {ticker}: {e}")
        return []


def fetch_dividends_yfinance(ticker: str) -> List[DividendEvent]:
    """Layer 3: Fallback to Yfinance (Ex-Date only)."""
    try:
        import yfinance as yf
        # Suppress yfinance warnings
        import logging as yf_logging
        yf_logging.getLogger("yfinance").setLevel(logging.ERROR)
        
        stock = yf.Ticker(ticker)
        dividends = stock.dividends
        
        if dividends is None or dividends.empty:
            return []
        
        events = []
        for date_idx, amount in dividends.items():
            # Convert pandas Timestamp to date
            if hasattr(date_idx, 'date'):
                ex_date = date_idx.date()
            else:
                ex_date = date_idx
            
            # FALLBACK: Use Ex-Date as Pay-Date since real Pay-Date is missing
            pay_date = ex_date
            
            events.append(DividendEvent(
                ex_date=ex_date,
                pay_date=pay_date,
                amount=float(amount),
                source='yfinance_fallback'
            ))
            
        return events
    except Exception as e:
        logger.debug(f"Yfinance failed for {ticker}: {e}")
        return []


def fetch_dividend_data(ticker: str) -> List[DividendEvent]:
    """
    Master fetcher using 3-layer strategy.
    Returns list of dividends found.
    """
    # 1. Try Nasdaq (US Only)
    events = fetch_dividends_nasdaq(ticker)
    if events:
        return events
        
    # 2. Try YahooQuery (Global - Precision for upcoming/recent)
    yq_events = fetch_dividends_yahooquery(ticker)
    
    # 3. Try Yfinance (Fallback - History)
    # We fetch this even if YahooQuery succeeded, because YahooQuery 
    # often only has the *next* dividend, but we might need history (backfill).
    yf_events = fetch_dividends_yfinance(ticker)
    
    if not yq_events and not yf_events:
        return []

    # Merge strategies: 
    # Start with Yfinance (better history)
    # Override with YahooQuery (better precision for recent/future)
    merged_map = {e.ex_date: e for e in yf_events}
    
    for yq_evt in yq_events:
        # Update or add (YahooQuery data is preferred for Pay Date accuracy)
        merged_map[yq_evt.ex_date] = yq_evt
        
    return list(merged_map.values())


def calculate_eligible_shares(fund: str, ticker: str, ex_date: date, client) -> Decimal:
    """
    Calculate shares owned on day BEFORE ex_date.
    Formula: Sum(shares) where date < ex_date
    Note: In trade_log schema, shares is signed (positive=BUY, negative=SELL)
    """
    try:
        # Convert ex_date to datetime for comparison
        ex_datetime = datetime.combine(ex_date, dt_time(0, 0, 0))
        ex_datetime_str = ex_datetime.isoformat()
        
        # Get all trades before ex_date
        trades_result = client.supabase.table("trade_log")\
            .select("shares, date")\
            .eq("fund", fund)\
            .eq("ticker", ticker)\
            .lt("date", ex_datetime_str)\
            .order("date")\
            .execute()
        
        net_shares = Decimal('0')
        
        for trade in trades_result.data:
            shares = Decimal(str(trade.get('shares', 0) or 0))
            # Shares is already signed in trade_log (positive=buy, negative=sell)
            net_shares += shares
        
        return max(net_shares, Decimal('0'))
    except Exception as e:
        logger.error(f"Error shares calc for {fund}/{ticker}: {e}")
        return Decimal('0')


def get_price_on_date(ticker: str, target_date: date) -> Optional[Decimal]:
    """Get closing price for ticker on target_date."""
    try:
        from market_data.data_fetcher import MarketDataFetcher
        
        market_fetcher = MarketDataFetcher()
        
        # Try finding price for up to 3 days (in case of weekends/holidays)
        for i in range(4):
            check_date = target_date + timedelta(days=i)
            start_dt = datetime.combine(check_date, dt_time(0, 0, 0))
            end_dt = datetime.combine(check_date, dt_time(23, 59, 59, 999999))
            
            result = market_fetcher.fetch_price_data(ticker, start=start_dt, end=end_dt)
            
            if result and result.df is not None and not result.df.empty:
                return Decimal(str(result.df['Close'].iloc[-1]))
                
        return None
    except Exception as e:
        logger.warning(f"Error getting price for {ticker}: {e}")
        return None


def insert_drip_transaction(
    fund: str, ticker: str, evt: DividendEvent,
    fund_type: str, client
) -> bool:
    """Insert DRIP transaction into DB."""
    try:
        # 1. Calc Shares
        eligible_shares = calculate_eligible_shares(fund, ticker, evt.ex_date, client)
        if eligible_shares <= 0:
            return False
            
        # 2. Calc Amounts
        gross_amount = eligible_shares * Decimal(str(evt.amount))
        withholding_tax = calculate_withholding_tax(gross_amount, fund_type, ticker)
        net_amount = gross_amount - withholding_tax
        
        if net_amount <= 0:
            return False
            
        # 3. Get Price & Reinvest
        drip_price = get_price_on_date(ticker, evt.pay_date)
        if not drip_price:
            logger.warning(f"Could not get price for {ticker} on {evt.pay_date}")
            return False
            
        reinvested_shares = net_amount / drip_price
        currency = 'CAD' if is_canadian_ticker(ticker) else 'USD'
        
        # 3.5. Ensure ticker exists in securities table (required for FK constraint)
        if not client.ensure_ticker_in_securities(ticker, currency):
            logger.warning(f"Failed to ensure ticker {ticker} in securities table, continuing anyway")

        # 4. Insert Trade Log
        # Use 4 PM ET market close
        et_tz = pytz.timezone('America/New_York')
        pay_dt = datetime.combine(evt.pay_date, dt_time(16, 0))
        et_dt = et_tz.localize(pay_dt)
        utc_dt = et_dt.astimezone(pytz.UTC)
        
        trade_entry = {
            'fund': fund,
            'date': utc_dt.isoformat(),
            'ticker': ticker,
            'shares': float(reinvested_shares),
            'price': float(drip_price),
            'cost_basis': float(net_amount),
            'pnl': 0.0,
            'reason': 'DRIP',
            'currency': currency
        }
        
        # Ensure ticker exists in securities table before inserting trade
        try:
            client.ensure_ticker_in_securities(ticker, currency)
        except Exception as e:
            logger.warning(f"Error ensuring ticker {ticker} in securities: {e}")
            # Continue anyway, let the insert fail if FK constraint violation

        trade_res = client.supabase.table("trade_log").insert(trade_entry).execute()
        if not trade_res.data:
            return False
        
        trade_id = trade_res.data[0]['id']
        
        # 5. Insert Dividend Log
        div_entry = {
            'fund': fund,
            'ticker': ticker,
            'ex_date': evt.ex_date.isoformat(),
            'pay_date': evt.pay_date.isoformat(),
            'gross_amount': float(gross_amount),
            'withholding_tax': float(withholding_tax),
            'net_amount': float(net_amount),
            'reinvested_shares': float(reinvested_shares),
            'drip_price': float(drip_price),
            'is_verified': (evt.source == 'nasdaq'), # Verify if from official source
            'trade_log_id': trade_id,
            'currency': currency
        }
        
        client.supabase.table("dividend_log").insert(div_entry).execute()
        
        logger.info(f"✅ DRIP {fund}/{ticker}: {reinvested_shares:.4f} shares @ ${drip_price} (Source: {evt.source})")
        return True
        
    except Exception as e:
        logger.error(f"DRIP Insert Failed {fund}/{ticker}: {e}")
        return False


def process_dividends_job(lookback_days: int = 7) -> None:
    """Daily job to detect and process dividend reinvestments."""
    import sys
    job_id = 'dividend_processing'
    start_time = time.time()
    
    # IMMEDIATE logging - use print() as fallback since it always works
    print(f"[{__name__}] process_dividends_job() STARTED (lookback_days={lookback_days})", file=sys.stderr, flush=True)
    try:
        logger.info(f"process_dividends_job() started (lookback_days={lookback_days})")
    except:
        pass  # Logger might not be ready yet
    
    # Import job tracking at the start
    from datetime import timezone
    target_date = datetime.now(timezone.utc).date()
    
    try:
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        print(f"[{__name__}] Marking job as started in database...", file=sys.stderr, flush=True)
        mark_job_started(job_id, target_date)
        print(f"[{__name__}] Job marked as started successfully", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[{__name__}] WARNING: Could not mark job started: {e}", file=sys.stderr, flush=True)
        logger.warning(f"Could not mark job started: {e}")
    
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        
        print(f"[{__name__}] Starting dividend processing job (3-Layer Strategy, lookback={lookback_days}d)...", file=sys.stderr, flush=True)
        logger.info(f"Starting dividend processing job (3-Layer Strategy, lookback={lookback_days}d)...")
        
        holdings = get_unique_holdings(client)
        if not holdings:
            duration_ms = int((time.time()-start_time)*1000)
            log_job_execution(job_id, True, "No active holdings", duration_ms)
            try:
                mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms)
                logger.debug(f"Marked job as completed in database (no holdings)")
            except Exception as db_error:
                # CRITICAL: Log this prominently - if this fails, executions won't show in UI
                logger.error(f"❌ CRITICAL: Failed to mark job as completed in database: {db_error}")
                logger.error(f"  Job executed successfully but execution won't appear in UI")
                logger.error(f"  Error type: {type(db_error).__name__}")
                logger.error(f"  Error details: {str(db_error)[:500]}")
                import traceback
                logger.error(f"  Full traceback:\n{traceback.format_exc()}")
                # Don't re-raise - job succeeded, just logging failed
            return
            
        # Get already processed dividends (key: fund, ticker, pay_date)
        processed_res = client.supabase.table("dividend_log").select("fund, ticker, pay_date, ex_date").execute()
        processed_keys = set()
        for row in processed_res.data:
            # Track both pay_date and ex_date to avoid duplicates
            processed_keys.add((row['fund'], row['ticker'], row['pay_date']))
            processed_keys.add((row['fund'], row['ticker'], row['ex_date']))
            
        stats = {'processed': 0, 'skipped': 0, 'errors': 0}
        
        # Lookback window
        today = date.today()
        lookback = today - timedelta(days=lookback_days)
        
        for fund, ticker in holdings:
            try:
                # 1. Fetch Data
                events = fetch_dividend_data(ticker)
                if not events:
                    continue
                    
                fund_type = get_fund_type(fund, client)
                
                # 2. Process Events
                for evt in events:
                    # Filter: Pay date must be in recent window (or today)
                    if not (lookback <= evt.pay_date <= today):
                        continue
                        
                    # Check Duplicate
                    if (fund, ticker, evt.pay_date.isoformat()) in processed_keys:
                        continue
                    if (fund, ticker, evt.ex_date.isoformat()) in processed_keys:
                        continue
                        
                    # Process
                    success = insert_drip_transaction(fund, ticker, evt, fund_type, client)
                    if success:
                        stats['processed'] += 1
                        # Add to processed set to prevent double counting in same run
                        processed_keys.add((fund, ticker, evt.pay_date.isoformat()))
                    else:
                        stats['skipped'] += 1
                        
            except Exception as e:
                logger.error(f"Error processing {ticker}: {e}")
                stats['errors'] += 1
                
        duration = int((time.time() - start_time) * 1000)
        msg = f"Processed {stats['processed']}, Skipped {stats['skipped']}, Errors {stats['errors']}"
        print(f"[{__name__}] Job completed: {msg} (duration: {duration}ms)", file=sys.stderr, flush=True)
        log_job_execution(job_id, True, msg, duration)
        try:
            print(f"[{__name__}] Marking job as completed in database...", file=sys.stderr, flush=True)
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration)
            print(f"[{__name__}] Job marked as completed in database successfully", file=sys.stderr, flush=True)
            logger.debug(f"Marked job as completed in database")
        except Exception as db_error:
            # CRITICAL: Log this prominently - if this fails, executions won't show in UI
            error_msg = f"CRITICAL: Failed to mark job as completed in database: {db_error}"
            print(f"[{__name__}] ❌ {error_msg}", file=sys.stderr, flush=True)
            logger.error(f"❌ CRITICAL: Failed to mark job as completed in database: {db_error}")
            logger.error(f"  Job executed successfully but execution won't appear in UI")
            logger.error(f"  Error type: {type(db_error).__name__}")
            logger.error(f"  Error details: {str(db_error)[:500]}")
            import traceback
            traceback.print_exc(file=sys.stderr)
            logger.error(f"  Full traceback:\n{traceback.format_exc()}")
            # Don't re-raise - job succeeded, just logging failed
        logger.info(f"✅ {msg}")
        
    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        log_job_execution(job_id, False, str(e), duration)
        try:
            mark_job_failed(job_id, target_date, None, str(e), duration_ms=duration)
            logger.debug(f"Marked job as failed in database")
        except Exception as db_error:
            logger.error(f"Failed to mark job as failed in database: {db_error}")
            logger.error(f"  This means the execution won't appear in the UI. Error details: {str(db_error)[:300]}")
            # Don't re-raise here - the original error is more important
        logger.error(f"❌ Job Failed: {e}")

