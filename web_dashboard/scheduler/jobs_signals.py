"""
Signals Jobs
============

Jobs for calculating and storing technical signals for watchlist tickers.
"""

import logging
import math
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any, Optional

# Add parent directory to path if needed
current_dir = Path(__file__).resolve().parent
if current_dir.name == "scheduler":
    project_root = current_dir.parent.parent
else:
    project_root = current_dir.parent.parent

# Also ensure web_dashboard is in path for supabase_client imports
web_dashboard_path = str(Path(__file__).resolve().parent.parent)
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
from settings import get_signal_alert_policy, normalize_fund_type
from watchlist_access import get_active_watchlist_rows

# Initialize logger
logger = logging.getLogger(__name__)

# AI explanation settings (keep conservative to avoid long job times)
AI_EXPLANATION_ENABLED = True
AI_EXPLANATION_MIN_CONFIDENCE = 0.7
AI_EXPLANATION_SIGNALS = {"BUY", "SELL"}
AI_EXPLANATION_FEAR_LEVELS = {"HIGH", "EXTREME"}
AI_EXPLANATION_MAX_PER_RUN = 10


def _build_global_alert_policy(policies: list[dict[str, Any]]) -> dict[str, Any]:
    """Build conservative global alert policy when watchlist lacks fund scope."""
    if not policies:
        return get_signal_alert_policy(None)

    min_confidence = max(float(policy.get("min_confidence", 0.72)) for policy in policies)
    cooldown_minutes = max(int(policy.get("cooldown_minutes", 240)) for policy in policies)

    fear_sets: list[set[str]] = []
    for policy in policies:
        raw = policy.get("fear_levels", [])
        if isinstance(raw, list):
            fear_sets.append({str(level).strip().upper() for level in raw if str(level).strip()})

    if fear_sets:
        common_fear_levels = set.intersection(*fear_sets) if len(fear_sets) > 1 else fear_sets[0]
        if not common_fear_levels:
            common_fear_levels = set.union(*fear_sets)
    else:
        common_fear_levels = {"HIGH", "EXTREME"}

    return {
        "profile_key": "GLOBAL_STRICT",
        "min_confidence": min_confidence,
        "fear_levels": sorted(common_fear_levels),
        "cooldown_minutes": cooldown_minutes,
    }


def _resolve_global_alert_policy(supabase_client: Any) -> dict[str, Any]:
    """Resolve active profile policies and collapse to a conservative global gate."""
    try:
        result = supabase_client.supabase.table("funds").select(
            "fund_type, is_production"
        ).execute()
        rows = result.data or []

        production_rows = [row for row in rows if row.get("is_production") is True]
        scoped_rows = production_rows if production_rows else rows

        profile_keys = {
            normalize_fund_type(row.get("fund_type"))
            for row in scoped_rows
            if row.get("fund_type")
        }
        if profile_keys:
            policies = [get_signal_alert_policy(profile_key) for profile_key in sorted(profile_keys)]
            return _build_global_alert_policy(policies)
    except Exception as e:
        logger.warning(f"Failed to load fund profile alert policy: {e}")

    return get_signal_alert_policy(None)


def signal_scan_job() -> None:
    """Scan watchlist tickers and generate technical signals.
    
    This job:
    1. Gets watchlist from dynamic watchlist function
    2. For each ticker, fetches price data
    3. Calculates structure, timing, and fear/risk signals
    4. Stores results in signal_analysis table
    5. Optionally sends alerts for significant signals
    """
    job_id = 'signal_scan'
    start_time = time.time()

    # Global AI lock (signal job can generate AI explanations)
    try:
        from utils.job_tracking import get_running_ai_job
        running_ai = get_running_ai_job(exclude_job_name=job_id)
        if running_ai:
            logger.info(f"⏸️  AI lock active: {running_ai} is running. Skipping {job_id}.")
            return
    except Exception as e:
        logger.warning(f"AI lock check failed (continuing): {e}")
    
    try:
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        logger.info("Starting signal scan job...")
        
        # Mark job as started
        target_date = datetime.now(timezone.utc).date()
        mark_job_started('signal_scan', target_date)
        
        # Import dependencies (lazy imports)
        try:
            from supabase_client import SupabaseClient
            from market_data.data_fetcher import MarketDataFetcher
            from web_dashboard.signals.signal_engine import SignalEngine
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            try:
                log_job_execution(job_id, False, message, duration_ms)
            except Exception as log_error:
                logger.warning(f"Failed to log job execution: {log_error}")
            logger.error(f"❌ {message}")
            mark_job_failed('signal_scan', target_date, None, message, duration_ms=duration_ms)
            return
        
        # Initialize clients
        supabase_client = SupabaseClient(use_service_role=True)
        data_fetcher = MarketDataFetcher()
        signal_engine = SignalEngine()
        
        watchlist = get_active_watchlist_rows(supabase_client)
        
        if not watchlist:
            logger.warning("No watchlist tickers found")
            duration_ms = int((time.time() - start_time) * 1000)
            message = "No watchlist tickers to process"
            try:
                log_job_execution(job_id, True, message, duration_ms)
                mark_job_completed(
                    'signal_scan',
                    target_date,
                    None,
                    [],
                    duration_ms=duration_ms,
                    message=message,
                )
            except Exception as log_error:
                logger.warning(f"Failed to log job execution: {log_error}")
            return
        
        logger.info(f"Processing {len(watchlist)} watchlist tickers...")
        
        processed = 0
        errors = 0
        alerts_sent = 0
        ai_explanations = 0
        global_alert_policy = _resolve_global_alert_policy(supabase_client)
        logger.info(
            "Signal alert policy: profile=%s min_confidence=%.2f fear_levels=%s",
            global_alert_policy.get("profile_key", "DEFAULT"),
            float(global_alert_policy.get("min_confidence", 0.72)),
            ",".join(global_alert_policy.get("fear_levels", [])),
        )

        # Accumulate DB writes and flush in chunks (avoids N+1 PostgREST round-trips)
        signals_batch: list[dict] = []
        snapshots_batch: list[dict] = []
        
        # Pre-fetch fundamentals for all tickers to avoid N+1 queries
        fundamentals_map = {}
        all_tickers = sorted({t.get('ticker').upper() for t in watchlist if t.get('ticker')})
        if all_tickers:
            try:
                # Fetch in chunks to avoid URL length limits
                chunk_size = 50
                for i in range(0, len(all_tickers), chunk_size):
                    chunk = all_tickers[i:i + chunk_size]
                    sec_result = supabase_client.supabase.table("securities") \
                        .select("*") \
                        .in_("ticker", chunk) \
                        .execute()
                    if sec_result.data:
                        for row in sec_result.data:
                            if row.get('ticker'):
                                fundamentals_map[row['ticker'].upper()] = row
            except Exception as batch_err:
                logger.error(f"Failed to batch fetch fundamentals: {batch_err}")

        # One Research DB client for ETF look-through across the whole scan
        lookthrough_pg = None
        try:
            from postgres_client import PostgresClient
            lookthrough_pg = PostgresClient()
        except Exception as pg_err:
            logger.debug(f"PostgresClient unavailable for ETF look-through: {pg_err}")

        from web_dashboard.signals.etf_lookthrough_loader import resolve_signal_fundamentals

        # Process each ticker
        for ticker_data in watchlist:
            ticker = ticker_data.get('ticker')
            if not ticker:
                continue
            
            try:
                # Fetch price data (need 6 months for indicators)
                price_data = data_fetcher.fetch_price_data(ticker, period="6mo")
                
                if price_data.df.empty:
                    logger.warning(f"No price data for {ticker}")
                    errors += 1
                    continue

                # Get fundamentals from pre-fetched map; ETF → holdings look-through
                fundamentals = resolve_signal_fundamentals(
                    ticker.upper(),
                    fundamentals_map.get(ticker.upper()),
                    supabase_client,
                    postgres_client=lookthrough_pg,
                )
                
                # Generate signals (pass fundamentals if available)
                signals = signal_engine.evaluate(
                    ticker, price_data.df, fundamentals=fundamentals
                )
                
                # Store in database
                analysis_date = datetime.now(timezone.utc)
                
                # Check if signal should trigger alert
                should_alert = _should_alert(signals, policy=global_alert_policy)

                # Build cross-source ticker state (best-effort, only for AI candidates)
                ticker_state = None
                overall_signal = signals.get('overall_signal', 'HOLD')
                confidence = signals.get('confidence', 0.0)
                fear_level = signals.get('fear_risk', {}).get('fear_level', 'LOW')
                needs_ai = AI_EXPLANATION_ENABLED and ai_explanations < AI_EXPLANATION_MAX_PER_RUN and (
                    (overall_signal in AI_EXPLANATION_SIGNALS and confidence >= AI_EXPLANATION_MIN_CONFIDENCE)
                    or fear_level in AI_EXPLANATION_FEAR_LEVELS
                )
                if needs_ai:
                    try:
                        from web_dashboard.ticker_state import build_ticker_state, summarize_ticker_state
                        pg_client = None
                        try:
                            from postgres_client import PostgresClient
                            pg_client = PostgresClient()
                        except Exception:
                            pass
                        ticker_state = build_ticker_state(
                            ticker, supabase_client, postgres_client=pg_client
                        )
                    except Exception as state_err:
                        logger.debug(f"Could not build ticker state for {ticker}: {state_err}")

                # Optionally generate AI explanation (limited per run)
                explanation = None
                if needs_ai:
                    try:
                        from web_dashboard.signals.ai_explainer import generate_signal_explanation
                        explanation = generate_signal_explanation(
                            ticker, signals, ticker_state=ticker_state
                        )
                        if explanation:
                            ai_explanations += 1
                    except Exception as ai_error:
                        logger.warning(f"AI explanation failed for {ticker}: {ai_error}")
                
                # Queue signal analysis for batched upsert
                try:
                    signals_batch.append({
                        'ticker': ticker.upper(),
                        'analysis_date': analysis_date.isoformat(),
                        'structure_signal': signals.get('structure', {}),
                        'timing_signal': signals.get('timing', {}),
                        'fear_risk_signal': signals.get('fear_risk', {}),
                        'momentum_signal': signals.get('momentum', {}),
                        'fundamental_signal': signals.get('fundamental', {}),
                        'overall_signal': signals.get('overall_signal', 'HOLD'),
                        'confidence_score': signals.get('confidence', 0.0),
                        'explanation': explanation
                    })
                    
                    if should_alert:
                        alerts_sent += 1
                        logger.info(f"⚠️  Alert: {ticker} - {signals.get('overall_signal')} signal (confidence: {signals.get('confidence', 0):.2f})")

                    # Queue ticker state snapshot (best-effort)
                    if ticker_state:
                        try:
                            from web_dashboard.ticker_state import summarize_ticker_state
                            summary = summarize_ticker_state(ticker_state)
                            snapshots_batch.append({
                                'ticker': ticker.upper(),
                                'snapshot_date': analysis_date.isoformat(),
                                'state': ticker_state,
                                'summary': summary,
                            })
                        except Exception as snap_err:
                            logger.debug(f"Failed to queue state snapshot for {ticker}: {snap_err}")
                    
                    # Small delay to avoid rate limiting
                    time.sleep(0.5)
                    
                except Exception as queue_error:
                    logger.error(f"Error queuing signals for {ticker}: {queue_error}")
                    errors += 1
                    continue
                
            except Exception as e:
                logger.error(f"Error processing {ticker}: {e}", exc_info=True)
                errors += 1
                continue

        upsert_chunk = 200
        if signals_batch:
            for i in range(0, len(signals_batch), upsert_chunk):
                chunk = signals_batch[i : i + upsert_chunk]
                try:
                    supabase_client.supabase.table("signal_analysis").upsert(
                        chunk, on_conflict="ticker,analysis_date"
                    ).execute()
                    processed += len(chunk)
                except Exception as e:
                    logger.error(f"Failed to batch upsert signal_analysis ({len(chunk)} rows): {e}")
                    errors += len(chunk)

        if snapshots_batch:
            for i in range(0, len(snapshots_batch), upsert_chunk):
                chunk = snapshots_batch[i : i + upsert_chunk]
                try:
                    supabase_client.supabase.table("ticker_state_snapshots").upsert(
                        chunk, on_conflict="ticker,snapshot_date"
                    ).execute()
                except Exception as e:
                    logger.error(f"Failed to batch upsert ticker_state_snapshots ({len(chunk)} rows): {e}")
        
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Processed {processed} tickers, {errors} errors, {alerts_sent} alerts, {ai_explanations} AI notes"
        
        try:
            log_job_execution(job_id, True, message, duration_ms)
            mark_job_completed(
                'signal_scan',
                target_date,
                None,
                [],
                duration_ms=duration_ms,
                message=message,
            )
        except Exception as log_error:
            logger.warning(f"Failed to log job execution: {log_error}")
        
        logger.info(f"✅ Signal scan complete: {message}")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Job failed: {str(e)}"
        try:
            log_job_execution(job_id, False, message, duration_ms)
            mark_job_failed('signal_scan', target_date, None, str(e), duration_ms=duration_ms)
        except Exception as log_error:
            logger.warning(f"Failed to log job execution: {log_error}")
        logger.error(f"❌ {message}", exc_info=True)


# =============================================================================
# Fundamentals Backfill Job
# =============================================================================

# yfinance key -> securities DB column
_YFINANCE_FUNDAMENTAL_MAP: dict[str, str] = {
    'trailingPE': 'trailing_pe',
    'dividendYield': 'dividend_yield',
    'fiftyTwoWeekHigh': 'fifty_two_week_high',
    'fiftyTwoWeekLow': 'fifty_two_week_low',
    'forwardPE': 'forward_pe',
    'priceToBook': 'price_to_book',
    'priceToSalesTrailing12Months': 'price_to_sales',
    'pegRatio': 'peg_ratio',
    'returnOnEquity': 'return_on_equity',
    'profitMargins': 'net_margin',
    'operatingMargins': 'operating_margin',
    'grossMargins': 'gross_margin',
    'revenueGrowth': 'revenue_growth',
    'earningsGrowth': 'earnings_growth',
    'currentRatio': 'current_ratio',
    'debtToEquity': 'debt_to_equity',
    'freeCashflow': 'free_cash_flow',
    'shortRatio': 'short_ratio',
    'shortPercentOfFloat': 'short_percent_of_float',
    'ebitda': 'ebitda',
    'trailingEps': 'trailing_eps',
    'forwardEps': 'forward_eps',
}

# Columns that indicate "real" fundamental data (not just trailing_pe which can
# come from basic metadata).  If none of these are populated we consider the
# ticker as needing a fundamentals refresh.
_FUNDAMENTAL_INDICATOR_COLS = [
    'forward_pe', 'price_to_book', 'return_on_equity', 'net_margin',
    'revenue_growth', 'current_ratio', 'debt_to_equity',
]


def _fundamental_updates_from_info(info: dict[str, Any]) -> dict[str, float]:
    """Map a yfinance info dict to {securities column: finite float}."""
    updates: dict[str, float] = {}
    for yf_key, db_col in _YFINANCE_FUNDAMENTAL_MAP.items():
        raw = info.get(yf_key)
        if raw is not None:
            try:
                val = float(raw)
                # Skip inf/nan -- yfinance sometimes returns these
                if math.isfinite(val):
                    updates[db_col] = val
            except (TypeError, ValueError):
                pass
    return updates


# Max yfinance calls per fundamentals refresh run (~1s each).  Remaining gaps
# are deferred and picked up by later runs.
_FUNDAMENTALS_MAX_PER_RUN = 400

# ETF holding tickers must look like plain US-listed symbols; this skips cash
# rows and foreign codes like "7203 JP".  The slash is allowed for share-class
# spellings like Global X / VanEck's "BF/B".
_ETF_HOLDING_TICKER_RE = re.compile(r'^[A-Z][A-Z0-9.\-/]{0,9}$')

# Share-class markers at the end of a holding name: "CLASS B", "CL B",
# "-CL A", "CLASS-A", ... (case-insensitive), capturing the class letter.
_SHARE_CLASS_NAME_RE = re.compile(r'(?:CLASS|CL)[ \-]?([A-Z])$', re.IGNORECASE)


def _yfinance_symbol_alias(ticker: str, holding_name: str | None) -> str | None:
    """yfinance-compatible alias for a share-class ticker spelling.

    - Slash form (Global X / VanEck): ``BF/B`` -> ``BF-B``.
    - Joined form (iShares): when the holding name ends in a share-class
      marker naming the same letter the ticker ends with (and the ticker has
      at least 2 characters before it), ``BRKB`` -> ``BRK-B``.

    Returns None when no alias applies.  The alias is a *fallback*: callers
    only fetch it after the as-written ticker yields no fundamentals, so a
    real ticker like FOXA ("FOX CORP CLASS A") is never blindly rewritten.
    """
    if not ticker:
        return None
    if '/' in ticker:
        return ticker.replace('/', '-')
    if holding_name:
        match = _SHARE_CLASS_NAME_RE.search(holding_name)
        if match:
            letter = match.group(1).upper()
            if ticker.endswith(letter) and len(ticker) >= 3:
                return ticker[:-1] + '-' + letter
    return None

# Fetch-skip backoff: exponential retry delay for tickers yfinance can't
# serve, so failed fundamentals fetches aren't retried every night.
_FETCH_SKIP_BASE_DELAY_DAYS = 7
_FETCH_SKIP_MAX_DELAY_DAYS = 90

_FETCH_SKIP_REASONS = ('no_yfinance_info', 'not_equity', 'no_fundamentals')


def _fetch_etf_holding_candidates() -> dict[str, dict[str, Any]]:
    """Top holdings of every tracked ETF, as fundamentals-refresh candidates.

    One window-function query over etf_holdings_log (Research DB): for each
    ETF's latest snapshot, take holdings in weight_percent desc order until
    the cumulative weight reaches 80% of that ETF's total, capped at 100
    holdings per ETF.

    Returns:
        {holding_ticker: {'max_weight': float, 'holding_name': str | None}}
        where max_weight is the ticker's highest weight in any ETF.
    """
    from postgres_client import PostgresClient

    pc = PostgresClient()
    rows = pc.execute_query(
        """
        WITH latest_per_etf AS (
            SELECT etf_ticker, MAX(date) AS latest_date
            FROM etf_holdings_log
            GROUP BY etf_ticker
        ),
        per_holding AS (
            SELECT
                h.etf_ticker,
                h.holding_ticker,
                MAX(h.holding_name) AS holding_name,
                SUM(h.weight_percent) AS weight_percent
            FROM etf_holdings_log h
            JOIN latest_per_etf l
              ON l.etf_ticker = h.etf_ticker
             AND l.latest_date = h.date
            WHERE h.shares_held > 0
              AND h.holding_ticker IS NOT NULL
            GROUP BY h.etf_ticker, h.holding_ticker
        ),
        cumulative AS (
            SELECT
                etf_ticker,
                holding_ticker,
                holding_name,
                weight_percent,
                SUM(weight_percent) OVER w AS cum_weight,
                SUM(weight_percent) OVER (PARTITION BY etf_ticker) AS total_weight,
                ROW_NUMBER() OVER w AS rn
            FROM per_holding
            WINDOW w AS (PARTITION BY etf_ticker ORDER BY weight_percent DESC, holding_ticker ASC)
        )
        SELECT etf_ticker, holding_ticker, holding_name, weight_percent
        FROM cumulative
        WHERE rn <= 100
          AND cum_weight - weight_percent < 0.8 * total_weight
        """
    )

    candidates: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        raw_ticker = row.get('holding_ticker')
        if not raw_ticker or not isinstance(raw_ticker, str):
            continue
        ticker_clean = raw_ticker.strip()
        if not _ETF_HOLDING_TICKER_RE.match(ticker_clean):
            logger.debug(f"Skipping non-US ETF holding ticker: {raw_ticker!r}")
            continue
        ticker = ticker_clean.upper()
        try:
            weight = float(row.get('weight_percent') or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        existing = candidates.get(ticker)
        if existing is None or weight > existing['max_weight']:
            candidates[ticker] = {
                'max_weight': weight,
                'holding_name': row.get('holding_name'),
            }
    return candidates


def _find_fundamental_gaps(
    supabase_client, tickers: list[str]
) -> tuple[set[str], set[str]]:
    """Batch-check which tickers are missing key fundamental columns.

    Returns:
        (gaps, missing): tickers that have a securities row with no indicator
        columns populated, and tickers with no securities row at all.
    """
    gaps: set[str] = set()
    missing: set[str] = set()
    chunk_size = 50
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            # Only select the columns we need to check
            select_cols = "ticker," + ",".join(_FUNDAMENTAL_INDICATOR_COLS)
            result = supabase_client.supabase.table("securities") \
                .select(select_cols) \
                .in_("ticker", chunk) \
                .execute()

            existing_map = {}
            if result.data:
                for row in result.data:
                    existing_map[row.get('ticker', '').upper()] = row

            for t in chunk:
                row = existing_map.get(t)
                if not row:
                    missing.add(t)
                    continue

                # Check if any indicator column is populated
                has_fundamentals = any(
                    row.get(col) is not None
                    for col in _FUNDAMENTAL_INDICATOR_COLS
                )
                if not has_fundamentals:
                    gaps.add(t)
        except Exception as e:
            logger.warning(f"Error checking fundamental gaps for chunk: {e}")
            # If we can't check, add the whole chunk to be safe
            gaps.update(chunk)
    return gaps, missing


def _fetch_skip_retry_after(failure_count: int, now: Optional[datetime] = None) -> datetime:
    """Exponential backoff for repeated fundamentals-fetch failures:
    7 days * 2**(failure_count - 1), capped at 90 days."""
    if now is None:
        now = datetime.now(timezone.utc)
    count = max(1, int(failure_count))
    delay_days = min(
        _FETCH_SKIP_BASE_DELAY_DAYS * 2 ** (count - 1),
        _FETCH_SKIP_MAX_DELAY_DAYS,
    )
    return now + timedelta(days=delay_days)


def _parse_timestamptz(value: Any) -> Optional[datetime]:
    """Parse a timestamptz from PostgREST (ISO string) or a datetime."""
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str) and value:
        try:
            ts = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    else:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _load_fetch_skips(
    supabase_client, tickers: list[str]
) -> dict[str, dict[str, Any]]:
    """Existing fundamentals_fetch_skips rows for the given tickers, by ticker.

    Best-effort: if the table is missing (migration not yet applied) or any
    query fails, log a warning and return {} so the job runs without skips.
    """
    skips: dict[str, dict[str, Any]] = {}
    chunk_size = 200  # PostgREST caps responses at 1000 rows
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            result = supabase_client.supabase.table("fundamentals_fetch_skips") \
                .select("ticker,reason,failure_count,first_failed_at,retry_after") \
                .in_("ticker", chunk) \
                .execute()
            for row in result.data or []:
                ticker = (row.get('ticker') or '').upper()
                if ticker:
                    skips[ticker] = row
        except Exception as e:
            logger.warning(
                f"Could not load fundamentals_fetch_skips, continuing without "
                f"skips: {e}"
            )
            return {}
    return skips


def _flush_fetch_skip_writes(
    supabase_client, upserts: list[dict[str, Any]], deletes: list[str]
) -> None:
    """Batch-write recorded fetch skips (best-effort; failures only log)."""
    chunk_size = 200
    try:
        for i in range(0, len(upserts), chunk_size):
            supabase_client.supabase.table("fundamentals_fetch_skips") \
                .upsert(upserts[i:i + chunk_size]) \
                .execute()
        for i in range(0, len(deletes), chunk_size):
            supabase_client.supabase.table("fundamentals_fetch_skips") \
                .delete() \
                .in_("ticker", deletes[i:i + chunk_size]) \
                .execute()
    except Exception as e:
        logger.warning(f"Could not record fundamentals fetch skips: {e}")


def _flush_symbol_alias_writes(
    supabase_client, upserts: list[dict[str, Any]]
) -> None:
    """Record share-class aliases that fetched successfully (best-effort;
    failures only log) so the ETF holdings panel can link holdings to the
    Yahoo symbol."""
    chunk_size = 200
    try:
        for i in range(0, len(upserts), chunk_size):
            supabase_client.supabase.table("ticker_symbol_aliases") \
                .upsert(upserts[i:i + chunk_size]) \
                .execute()
    except Exception as e:
        logger.warning(f"Could not record ticker symbol aliases: {e}")


def fundamentals_refresh_job() -> None:
    """Backfill / refresh fundamental columns in the securities table.

    This job:
    1. Gets watchlist tickers from the shared watchlist function
    2. Adds the top holdings of tracked ETFs (Research DB etf_holdings_log)
       so ETF look-through fundamentals have enough coverage
    3. Identifies tickers that are missing key fundamental columns
    4. Fetches fresh data from yfinance and updates the securities table
       (ETF holdings with no securities row are inserted when yfinance
       confirms quoteType == EQUITY; watchlist tickers stay skipped)
    5. Processes in batches with rate-limiting to stay under yfinance limits,
       capped at _FUNDAMENTALS_MAX_PER_RUN yfinance calls per run

    Designed to run once daily.  Fundamentals change at most quarterly, so
    we skip tickers whose fundamentals were refreshed within the last 7 days.
    """
    job_id = 'fundamentals_refresh'
    start_time = time.time()

    try:
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed

        logger.info("Starting fundamentals refresh job...")
        target_date = datetime.now(timezone.utc).date()
        mark_job_started(job_id, target_date)

        # Lazy imports
        try:
            from supabase_client import SupabaseClient
            import yfinance as yf
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            msg = f"Missing dependency: {e}"
            try:
                log_job_execution(job_id, False, msg, duration_ms)
            except Exception:
                pass
            logger.error(f"❌ {msg}")
            try:
                mark_job_failed(job_id, target_date, None, msg, duration_ms=duration_ms)
            except Exception:
                pass
            return

        supabase_client = SupabaseClient(use_service_role=True)
        watchlist = get_active_watchlist_rows(supabase_client)

        watchlist_tickers = sorted({
            t.get('ticker', '').upper() for t in (watchlist or []) if t.get('ticker')
        })
        logger.info(f"Checking fundamentals for {len(watchlist_tickers)} watchlist tickers...")

        # Watchlist gaps first (priority)
        watchlist_gaps, _watchlist_missing = _find_fundamental_gaps(
            supabase_client, watchlist_tickers
        )
        # Watchlist tickers with no securities row stay skipped: the metadata
        # refresh job or ensure_ticker will create them.

        # ETF holding gaps: candidates from the Research DB, excluding any
        # ticker already handled (or deliberately skipped) via the watchlist.
        try:
            etf_candidates = _fetch_etf_holding_candidates()
            logger.info(
                f"ETF look-through: {len(etf_candidates)} distinct holding tickers "
                f"from tracked ETFs"
            )
        except Exception as e:
            logger.warning(
                f"Could not load ETF holdings from Research DB, continuing with "
                f"watchlist only: {e}"
            )
            etf_candidates = {}

        watchlist_set = set(watchlist_tickers)
        etf_tickers = [t for t in etf_candidates if t not in watchlist_set]
        etf_gaps, etf_missing = _find_fundamental_gaps(supabase_client, etf_tickers)

        # Order ETF holding gaps by their highest weight in any ETF
        etf_ordered = sorted(
            list(etf_gaps) + list(etf_missing),
            key=lambda t: etf_candidates[t]['max_weight'],
            reverse=True,
        )

        total_gaps = len(watchlist_gaps) + len(etf_ordered)
        if not total_gaps:
            duration_ms = int((time.time() - start_time) * 1000)
            msg = (
                f"No fundamentals gaps: {len(watchlist_tickers)} watchlist tickers "
                f"and {len(etf_candidates)} ETF holding tickers checked"
            )
            try:
                log_job_execution(job_id, True, msg, duration_ms)
                mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=msg)
            except Exception:
                pass
            logger.info(f"✅ {msg}")
            return

        logger.info(
            f"📊 {total_gaps} tickers need fundamental data "
            f"({len(watchlist_gaps)} watchlist, {len(etf_ordered)} ETF holdings)"
        )

        # Work list: watchlist gaps first, then ETF holding gaps by weight.
        # Drop tickers suppressed by fetch-skip backoff BEFORE the per-run cap
        # so they don't eat the yfinance budget, then cap the remaining work.
        work: list[tuple[str, bool]] = [(t, False) for t in sorted(watchlist_gaps)]
        work += [(t, True) for t in etf_ordered]

        run_now = datetime.now(timezone.utc)
        fetch_skip_rows = _load_fetch_skips(supabase_client, sorted({t for t, _ in work}))
        active_skips = {
            t for t, row in fetch_skip_rows.items()
            if (ts := _parse_timestamptz(row.get('retry_after'))) is not None
            and ts > run_now
        }
        suppressed = 0
        if active_skips:
            suppressed = len([t for t, _ in work if t in active_skips])
            work = [(t, is_etf) for t, is_etf in work if t not in active_skips]
            logger.info(
                f"⏭️  {suppressed} tickers suppressed by fetch-skip backoff "
                f"(of {len(fetch_skip_rows)} tracked)"
            )

        deferred = max(0, len(work) - _FUNDAMENTALS_MAX_PER_RUN)
        work = work[:_FUNDAMENTALS_MAX_PER_RUN]

        wl_counts = {'updated': 0, 'skipped': 0, 'errors': 0}
        etf_counts = {'updated': 0, 'inserted': 0, 'skipped': 0, 'errors': 0}
        alias_successes = 0

        # Batched fetch-skip writes (collected during the loop, flushed once)
        skip_upserts: list[dict[str, Any]] = []
        skip_deletes: list[str] = []
        skip_reason_counts = {reason: 0 for reason in _FETCH_SKIP_REASONS}

        # Successful share-class aliases, flushed to ticker_symbol_aliases
        # once after the loop (BRKB -> BRK-B) for the holdings link fixup.
        alias_upserts: list[dict[str, Any]] = []

        def _record_skip(ticker: str, reason: str) -> None:
            prev_row = fetch_skip_rows.get(ticker) or {}
            try:
                prev_count = int(prev_row.get('failure_count') or 0)
            except (TypeError, ValueError):
                prev_count = 0
            count = prev_count + 1
            first_failed = prev_row.get('first_failed_at') or run_now
            if isinstance(first_failed, datetime):
                first_failed = first_failed.isoformat()
            skip_upserts.append({
                'ticker': ticker,
                'reason': reason,
                'failure_count': count,
                'first_failed_at': first_failed,
                'last_failed_at': run_now.isoformat(),
                'retry_after': _fetch_skip_retry_after(count, run_now).isoformat(),
            })
            skip_reason_counts[reason] += 1

        for ticker, is_etf in work:
            counts = etf_counts if is_etf else wl_counts
            try:
                holding_name = (
                    etf_candidates.get(ticker, {}).get('holding_name')
                    if is_etf else None
                )
                alias = _yfinance_symbol_alias(ticker, holding_name)

                if '/' in ticker:
                    # yfinance raises on a slash ("BF/B" -> 404 YFException), so
                    # skip the as-written call and let the alias fetch below run.
                    info = {}
                else:
                    info = yf.Ticker(ticker).info or {}
                updates = _fundamental_updates_from_info(info)

                # Share-class fallback: ETF holdings files spell share-class
                # tickers in ways yfinance won't serve (BRKB, BF/B).  When the
                # as-written spelling fills none of the indicator columns,
                # retry under the alias (BRK-B, BF-B); any write still lands
                # on the holding's own spelling, which the look-through
                # loader looks up by.
                if alias and not any(col in updates for col in _FUNDAMENTAL_INDICATOR_COLS):
                    time.sleep(1.0)  # extra yfinance call, extra rate-limit sleep
                    alias_info = yf.Ticker(alias).info or {}
                    alias_updates = _fundamental_updates_from_info(alias_info)
                    if any(col in alias_updates for col in _FUNDAMENTAL_INDICATOR_COLS):
                        info, updates = alias_info, alias_updates
                        alias_successes += 1
                        alias_upserts.append({
                            'ticker': ticker,
                            'yahoo_symbol': alias,
                            'updated_at': run_now.isoformat(),
                        })
                        logger.info(
                            f"ℹ️  {ticker}: fetched fundamentals via share-class alias {alias}"
                        )

                if not info or info.get('quoteType') is None:
                    logger.debug(f"No yfinance info for {ticker}, skipping")
                    counts['skipped'] += 1
                    _record_skip(ticker, 'no_yfinance_info')
                    time.sleep(0.3)
                    continue

                if is_etf and ticker in etf_missing:
                    # No securities row: insert only when yfinance confirms an
                    # equity (skips ETFs, warrants, and other non-equity types).
                    if info.get('quoteType') != 'EQUITY':
                        counts['skipped'] += 1
                        _record_skip(ticker, 'not_equity')
                        logger.debug(
                            f"ETF holding {ticker} is {info.get('quoteType')}, not inserting"
                        )
                        time.sleep(1.0)
                        continue

                    row: dict[str, Any] = {'ticker': ticker}
                    company_name = (
                        info.get('longName')
                        or info.get('shortName')
                        or etf_candidates.get(ticker, {}).get('holding_name')
                    )
                    if company_name:
                        row['company_name'] = company_name
                    row.update(updates)
                    supabase_client.supabase.table("securities") \
                        .upsert(row) \
                        .execute()
                    etf_counts['inserted'] += 1
                    logger.debug(f"✅ Inserted securities row for ETF holding {ticker}")
                elif updates:
                    supabase_client.supabase.table("securities") \
                        .update(updates) \
                        .eq("ticker", ticker) \
                        .execute()
                    counts['updated'] += 1
                    logger.debug(f"✅ Updated {len(updates)} fundamental fields for {ticker}")
                else:
                    counts['skipped'] += 1
                    logger.debug(f"No fundamental data available from yfinance for {ticker}")

                # A fetch that fills at least one indicator column clears any
                # previous skip; otherwise record one (still keeping whatever
                # partial updates we got, e.g. trailing_pe).
                if any(col in updates for col in _FUNDAMENTAL_INDICATOR_COLS):
                    if ticker in fetch_skip_rows:
                        skip_deletes.append(ticker)
                else:
                    _record_skip(ticker, 'no_fundamentals')

                # Rate-limit: ~1 second between yfinance calls
                time.sleep(1.0)

            except Exception as e:
                # Transient (network etc.) errors are NOT recorded as skips
                counts['errors'] += 1
                logger.warning(f"Error fetching fundamentals for {ticker}: {e}")
                time.sleep(0.5)

        if skip_upserts or skip_deletes:
            _flush_fetch_skip_writes(supabase_client, skip_upserts, skip_deletes)
        if alias_upserts:
            _flush_symbol_alias_writes(supabase_client, alias_upserts)

        duration_ms = int((time.time() - start_time) * 1000)
        msg = (
            f"Fundamentals refresh: watchlist {wl_counts['updated']} updated, "
            f"{wl_counts['skipped']} skipped, {wl_counts['errors']} errors "
            f"(of {len(watchlist_gaps)} gaps); "
            f"ETF holdings {etf_counts['updated']} updated, {etf_counts['inserted']} inserted, "
            f"{etf_counts['skipped']} skipped, {etf_counts['errors']} errors "
            f"(of {len(etf_ordered)} gaps); "
            f"{deferred} deferred by per-run cap; "
            f"{suppressed} suppressed by backoff; "
            f"{alias_successes} via share-class alias; "
            f"skips recorded: {skip_reason_counts['no_yfinance_info']} no_yfinance_info, "
            f"{skip_reason_counts['not_equity']} not_equity, "
            f"{skip_reason_counts['no_fundamentals']} no_fundamentals"
        )
        try:
            log_job_execution(job_id, True, msg, duration_ms)
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=msg)
        except Exception:
            pass
        logger.info(f"✅ {msg}")

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        msg = f"Fundamentals refresh failed: {e}"
        try:
            log_job_execution(job_id, False, msg, duration_ms)
            mark_job_failed(job_id, target_date, None, str(e), duration_ms=duration_ms)
        except Exception:
            pass
        logger.error(f"❌ {msg}", exc_info=True)


def _should_alert(signals: dict[str, Any], policy: Optional[dict[str, Any]] = None) -> bool:
    """Determine if alert should be sent for this signal.
    
    Args:
        signals: Signal analysis dictionary
        policy: Optional alert policy thresholds
    
    Returns:
        True if alert should be sent
    """
    if policy is None:
        policy = get_signal_alert_policy(None)

    overall = signals.get('overall_signal', 'HOLD')
    confidence = signals.get('confidence', 0.0)
    fear_level = str(signals.get('fear_risk', {}).get('fear_level', 'LOW')).upper()
    min_confidence = float(policy.get("min_confidence", 0.72))
    fear_levels = {
        str(level).strip().upper()
        for level in policy.get("fear_levels", ["HIGH", "EXTREME"])
    }
    
    # Alert on strong signals or high fear
    return (
        (overall in ['BUY', 'SELL'] and confidence >= min_confidence) or
        fear_level in fear_levels
    )
