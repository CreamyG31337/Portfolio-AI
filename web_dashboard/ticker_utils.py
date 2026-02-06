#!/usr/bin/env python3
"""
Ticker Utilities
================

Utility functions for fetching ticker information from all databases
and generating clickable links to ticker details pages.
"""

import logging
import re
import pandas as pd
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import current_app

try:
    from supabase_client import SupabaseClient
    from postgres_client import PostgresClient
except ImportError:
    # Handle case where clients might be in different path
    try:
        from web_dashboard.supabase_client import SupabaseClient
        from web_dashboard.postgres_client import PostgresClient
    except ImportError:
        # Define dummy classes or Any for type hinting if imports fail
        SupabaseClient = Any
        PostgresClient = Any

logger = logging.getLogger(__name__)


def _normalize_fund_filter(fund: Optional[str]) -> Optional[str]:
    """Normalize fund filter values from requests/UI."""
    if not fund:
        return None
    fund_value = str(fund).strip()
    if not fund_value:
        return None
    if fund_value.lower() in ("all", "all funds"):
        return None
    return fund_value


def _get_yfinance_ticker_candidates(ticker: str) -> List[str]:
    """Return yfinance symbol candidates for potentially ambiguous tickers.

    Yahoo uses dash notation for class shares and may require exchange suffixes
    for Canadian listings (e.g., TECK.B -> TECK-B.TO).
    """
    ticker_upper = ticker.upper().strip()
    candidates: List[str] = []

    def _add(symbol: Optional[str]) -> None:
        if symbol and symbol not in candidates:
            candidates.append(symbol)

    _add(ticker_upper)

    # Handle class-share notation such as BRK.B, TECK.B, TECK.B.TO
    class_match = re.match(r"^([A-Z0-9]+)\.([A-Z])(?:\.(TO|V))?$", ticker_upper)
    if class_match:
        base_symbol, share_class, exchange_suffix = class_match.groups()
        class_dash_symbol = f"{base_symbol}-{share_class}"
        _add(class_dash_symbol)
        if exchange_suffix:
            _add(f"{class_dash_symbol}.{exchange_suffix}")
        else:
            # Most dot-class Canadian symbols in this app map to TSX on Yahoo.
            _add(f"{class_dash_symbol}.TO")

    return candidates


def get_all_unique_tickers(supabase_client=None, postgres_client=None) -> List[str]:
    """
    Aggregate unique tickers from all relevant database tables.
    Flask-compatible version (no Streamlit dependencies).

    Args:
        supabase_client: Optional SupabaseClient instance
        postgres_client: Optional PostgresClient instance

    Returns:
        List of unique ticker symbols sorted alphabetically.
    """
    logger.info(f"get_all_unique_tickers called - Explicit clients: SB={bool(supabase_client)}, PG={bool(postgres_client)}")
    tickers: set[str] = set()

    # Use provided clients or try to get from current_app context
    sb_client = supabase_client
    pg_client = postgres_client
    
    # Try to resolve clients from Flask app context if not provided
    try:
        if not sb_client and current_app:
            # Try to get from app extension or attribute
            pass 
            
        # Fallback to creating new clients if needed
        if not sb_client:
            try:
                logger.info("Attempting to create implicit SupabaseClient (service_role=True)")
                sb_client = SupabaseClient(use_service_role=True)
                logger.info("Implicit SupabaseClient created successfully")
            except Exception as e:
                logger.warning(f"Failed to init SupabaseClient: {e}", exc_info=True)

        if not pg_client:
            try:
                logger.info("Attempting to create implicit PostgresClient")
                pg_client = PostgresClient()
                logger.info("Implicit PostgresClient created successfully")
            except Exception as e:
                logger.warning(f"Failed to init PostgresClient: {e}", exc_info=True)
                
    except RuntimeError:
        # standard fallback if outside request context
        pass

    # 1. Fetch from Supabase
    if sb_client:
        try:
            # From securities table
            logger.debug("Fetching tickers from Supabase: securities")
            securities = sb_client.supabase.table('securities').select('ticker').execute()
            assert hasattr(securities, 'data'), "Securities response missing 'data' attribute"
            
            if securities.data:
                count_before = len(tickers)
                tickers.update(row['ticker'].upper() for row in securities.data if row.get('ticker'))
                logger.debug(f"Added {len(tickers) - count_before} tickers from securities. Total: {len(tickers)}")
            else:
                logger.debug("No data found in securities table")

            # From portfolio_positions
            logger.debug("Fetching tickers from Supabase: portfolio_positions")
            positions = sb_client.supabase.table('portfolio_positions').select('ticker').execute()
            assert hasattr(positions, 'data'), "Positions response missing 'data' attribute"
            
            if positions.data:
                count_before = len(tickers)
                tickers.update(row['ticker'].upper() for row in positions.data if row.get('ticker'))
                logger.debug(f"Added {len(tickers) - count_before} tickers from portfolio_positions. Total: {len(tickers)}")

            # From trade_log
            logger.debug("Fetching tickers from Supabase: trade_log")
            trades = sb_client.supabase.table('trade_log').select('ticker').execute()
            assert hasattr(trades, 'data'), "Trade log response missing 'data' attribute"
            
            if trades.data:
                count_before = len(tickers)
                tickers.update(row['ticker'].upper() for row in trades.data if row.get('ticker'))
                logger.debug(f"Added {len(tickers) - count_before} tickers from trade_log. Total: {len(tickers)}")

            # From watched_tickers (active only)
            logger.debug("Fetching tickers from Supabase: watched_tickers")
            watched = sb_client.supabase.table('watched_tickers').select('ticker').eq('is_active', True).execute()
            assert hasattr(watched, 'data'), "Watched tickers response missing 'data' attribute"
            
            if watched.data:
                count_before = len(tickers)
                tickers.update(row['ticker'].upper() for row in watched.data if row.get('ticker'))
                logger.debug(f"Added {len(tickers) - count_before} tickers from watched_tickers. Total: {len(tickers)}")

            # From congress_trades
            logger.debug("Fetching tickers from Supabase: congress_trades")
            congress = sb_client.supabase.table('congress_trades').select('ticker').execute()
            assert hasattr(congress, 'data'), "Congress trades response missing 'data' attribute"
            
            if congress.data:
                count_before = len(tickers)
                tickers.update(row['ticker'].upper() for row in congress.data if row.get('ticker'))
                logger.debug(f"Added {len(tickers) - count_before} tickers from congress_trades. Total: {len(tickers)}")

        except AssertionError as ae:
            logger.error(f"Assertion failed in Supabase fetch: {ae}")
        except Exception as e:
            logger.error(f"Error fetching tickers from Supabase: {e}", exc_info=True)
    else:
        logger.warning("Skipping Supabase fetch - sb_client is None")

    # 2. Fetch from PostgreSQL (Research DB)
    if pg_client:
        try:
            # From research_articles (unnest array)
            logger.debug("Fetching tickers from Postgres: research_articles")
            articles = pg_client.execute_query("""
                SELECT DISTINCT UNNEST(tickers) as ticker
                FROM research_articles
                WHERE tickers IS NOT NULL
            """)
            if articles:
                count_before = len(tickers)
                tickers.update(row['ticker'].upper() for row in articles if row.get('ticker'))
                logger.debug(f"Added {len(tickers) - count_before} tickers from research_articles. Total: {len(tickers)}")
            else:
                logger.debug("No tickers found in research_articles")

            # From social_metrics
            logger.debug("Fetching tickers from Postgres: social_metrics")
            social = pg_client.execute_query("SELECT DISTINCT ticker FROM social_metrics")
            if social:
                count_before = len(tickers)
                tickers.update(row['ticker'].upper() for row in social if row.get('ticker'))
                logger.debug(f"Added {len(tickers) - count_before} tickers from social_metrics. Total: {len(tickers)}")
            else:
                logger.debug("No tickers found in social_metrics")

        except Exception as e:
            logger.error(f"Error fetching tickers from PostgreSQL: {e}", exc_info=True)
    else:
        logger.warning("Skipping Postgres fetch - pg_client is None")

    logger.info(f"get_all_unique_tickers finished. Returning {len(tickers)} unique tickers.")
    return sorted(tickers)


def _fetch_basic_info(ticker_upper: str, supabase_client: Optional[SupabaseClient]) -> Dict[str, Any]:
    """Fetch basic info from securities table, falling back to yfinance."""
    result = {'basic_info': None, 'found': False}
    
    if not supabase_client:
        # Fallback to yfinance if no client, just to return data structure
        # But usually client is needed for DB cache. We can try yfinance anyway.
        pass

    # 1. Try DB
    if supabase_client:
        try:
            sec_result = supabase_client.supabase.table("securities")\
                .select("*")\
                .eq("ticker", ticker_upper)\
                .execute()
            
            if sec_result.data and len(sec_result.data) > 0:
                result['basic_info'] = sec_result.data[0]
                result['found'] = True

                # Add logo URL
                try:
                    from web_dashboard.utils.logo_utils import get_ticker_logo_url
                    logo_url = get_ticker_logo_url(ticker_upper)
                    if logo_url:
                        result['basic_info']['logo_url'] = logo_url
                except Exception as e:
                    logger.warning(f"Error fetching logo URL for {ticker_upper}: {e}")
                
                # Fetch description if missing
                if not result['basic_info'].get('description'):
                    try:
                        from web_dashboard.utils.company_description import ensure_company_description
                        description = ensure_company_description(ticker_upper, supabase_client, force_refresh=False)
                        if description:
                            result['basic_info']['description'] = description
                    except Exception as e:
                        logger.debug(f"Could not fetch company description for {ticker_upper}: {e}")
        except Exception as e:
            logger.warning(f"Error fetching basic info for {ticker_upper}: {e}")

    # 2. Fallback to yfinance
    if not result['basic_info']:
        try:
            import yfinance as yf
            yf_candidates = _get_yfinance_ticker_candidates(ticker_upper)
            logger.info(f"Looking up {ticker_upper} from Yahoo Finance candidates: {yf_candidates}")

            info = None
            for yf_symbol in yf_candidates:
                try:
                    ticker_obj = yf.Ticker(yf_symbol)
                    candidate_info = ticker_obj.info
                    if candidate_info and candidate_info.get("symbol"):
                        info = candidate_info
                        logger.info(f"Yahoo Finance lookup succeeded for {ticker_upper} via {yf_symbol}")
                        break
                except Exception as candidate_error:
                    logger.debug(f"Yahoo Finance lookup failed for candidate {yf_symbol}: {candidate_error}")
            
            if info and info.get('symbol'):
                # Extract fields
                company_name = (info.get('longName') or info.get('shortName') or info.get('displayName') or ticker_upper)
                sector = (info.get('sector') or info.get('sectorDisp') or info.get('sectorKey'))
                industry = (info.get('industry') or info.get('industryDisp') or info.get('industryKey'))
                currency = info.get('currency') or info.get('financialCurrency') or 'USD'
                exchange = (info.get('exchange') or info.get('exchangeName') or info.get('fullExchangeName'))
                trailing_pe = info.get('trailingPE')
                company_description = (info.get('longBusinessSummary') or info.get('longDescription') or info.get('description'))
                
                result['basic_info'] = {
                    'ticker': ticker_upper,
                    'company_name': company_name,
                    'sector': sector if sector else None,
                    'industry': industry if industry else None,
                    'currency': currency,
                    'exchange': exchange if exchange else None,
                    'trailing_pe': trailing_pe,
                    'description': company_description.strip() if company_description else None
                }
                
                # Add logo URL
                try:
                    from web_dashboard.utils.logo_utils import get_ticker_logo_url
                    logo_url = get_ticker_logo_url(ticker_upper)
                    if logo_url:
                        result['basic_info']['logo_url'] = logo_url
                except Exception as e:
                    logger.warning(f"Error fetching logo URL for {ticker_upper}: {e}")
                
                result['found'] = True
                
                # Save to database
                if supabase_client:
                    try:
                        supabase_client.supabase.table("securities").insert(result['basic_info']).execute()
                        logger.info(f"Saved ticker {ticker_upper} ({company_name}) to securities table from yfinance")
                    except Exception as insert_error:
                        logger.warning(f"Could not save {ticker_upper} to database: {insert_error}")
            else:
                logger.warning(f"Could not find ticker information for {ticker_upper} in yfinance")
        except Exception as e:
            logger.warning(f"Error fetching from yfinance for {ticker_upper}: {e}")

    # 3. Enrich incomplete info
    if result['basic_info'] and (result['basic_info'].get('sector') is None or result['basic_info'].get('industry') is None or result['basic_info'].get('trailing_pe') is None):
        try:
            import yfinance as yf
            yf_candidates = _get_yfinance_ticker_candidates(ticker_upper)
            logger.info(f"Re-fetching {ticker_upper} from Yahoo Finance candidates due to incomplete data: {yf_candidates}")

            info = None
            for yf_symbol in yf_candidates:
                try:
                    ticker_obj = yf.Ticker(yf_symbol)
                    candidate_info = ticker_obj.info
                    if candidate_info and candidate_info.get("symbol"):
                        info = candidate_info
                        logger.info(f"Yahoo Finance enrichment succeeded for {ticker_upper} via {yf_symbol}")
                        break
                except Exception as candidate_error:
                    logger.debug(f"Yahoo Finance enrichment failed for candidate {yf_symbol}: {candidate_error}")
            
            if info and info.get('symbol'):
                sector = result['basic_info'].get('sector') or info.get('sector') or info.get('sectorDisp') or info.get('sectorKey')
                industry = result['basic_info'].get('industry') or info.get('industry') or info.get('industryDisp') or info.get('industryKey')
                trailing_pe = result['basic_info'].get('trailingPE') or info.get('trailingPE')
                
                if sector or industry or trailing_pe:
                    updates = {}
                    if sector:
                        result['basic_info']['sector'] = sector
                        updates['sector'] = sector
                    if industry:
                        result['basic_info']['industry'] = industry
                        updates['industry'] = industry
                    if trailing_pe:
                        result['basic_info']['trailing_pe'] = trailing_pe
                        updates['trailing_pe'] = trailing_pe
                    
                    if supabase_client and updates:
                        try:
                            supabase_client.supabase.table("securities").update(updates).eq('ticker', ticker_upper).execute()
                            logger.info(f"Updated {ticker_upper} with enriched data from yfinance: {list(updates.keys())}")
                        except Exception as update_error:
                            logger.warning(f"Could not update {ticker_upper}: {update_error}")
        except Exception as e:
            logger.warning(f"Error re-fetching data for {ticker_upper}: {e}")

    return result


def _fetch_portfolio_data(ticker_upper: str, supabase_client: Optional[SupabaseClient], fund_filter: Optional[str]) -> Dict[str, Any]:
    """Fetch portfolio positions and trades."""
    result = {'portfolio_data': None, 'found': False}
    if not supabase_client:
        return result

    try:
        # Get current positions
        pos_query = supabase_client.supabase.table("portfolio_positions").select("*").eq("ticker", ticker_upper)
        if fund_filter:
            pos_query = pos_query.eq("fund", fund_filter)
        pos_result = pos_query.order("date", desc=True).limit(100).execute()

        # Get trade history
        trade_query = supabase_client.supabase.table("trade_log").select("*").eq("ticker", ticker_upper)
        if fund_filter:
            trade_query = trade_query.eq("fund", fund_filter)
        trade_result = trade_query.order("date", desc=True).limit(100).execute()

        if pos_result.data or trade_result.data:
            result['portfolio_data'] = {
                'positions': pos_result.data if pos_result.data else [],
                'trades': trade_result.data if trade_result.data else [],
                'has_positions': len(pos_result.data) > 0 if pos_result.data else False,
                'has_trades': len(trade_result.data) > 0 if trade_result.data else False
            }
            result['found'] = True
    except Exception as e:
        logger.warning(f"Error fetching portfolio data for {ticker_upper}: {e}")
    
    return result


def _fetch_research_articles(ticker_upper: str, postgres_client: Optional[PostgresClient]) -> Dict[str, Any]:
    """Fetch research articles."""
    result = {'research_articles': [], 'found': False}
    if not postgres_client:
        return result

    try:
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        query = """
            SELECT id, title, url, summary, source, published_at, fetched_at,
                   relevance_score, sentiment, sentiment_score, article_type
            FROM research_articles
            WHERE (tickers @> ARRAY[%s]::text[] OR ticker = %s)
            AND fetched_at >= %s
            ORDER BY fetched_at DESC
            LIMIT 50
        """
        articles = postgres_client.execute_query(
            query,
            (ticker_upper, ticker_upper, thirty_days_ago.isoformat())
        )

        if articles:
            result['research_articles'] = articles
            result['found'] = True
    except Exception as e:
        logger.warning(f"Error fetching research articles for {ticker_upper}: {e}")
    
    return result


def _fetch_social_sentiment(ticker_upper: str, postgres_client: Optional[PostgresClient]) -> Dict[str, Any]:
    """Fetch social sentiment metrics."""
    result = {'social_sentiment': None, 'found': False}
    if not postgres_client:
        return result

    try:
        query = """
            SELECT DISTINCT ON (platform)
                ticker, platform, volume, sentiment_label, sentiment_score,
                bull_bear_ratio, created_at
            FROM social_metrics
            WHERE ticker = %s
            ORDER BY platform, created_at DESC
            LIMIT 10
        """
        sentiment_data = postgres_client.execute_query(query, (ticker_upper,))

        query_alerts = """
            SELECT DISTINCT ON (platform, sentiment_label)
                ticker, platform, sentiment_label, sentiment_score, created_at
            FROM social_metrics
            WHERE ticker = %s
              AND sentiment_label IN ('EUPHORIC', 'FEARFUL', 'BULLISH')
              AND created_at > NOW() - INTERVAL '24 hours'
            ORDER BY platform, sentiment_label, created_at DESC
            LIMIT 10
        """
        alerts = postgres_client.execute_query(query_alerts, (ticker_upper,))

        if sentiment_data or alerts:
            result['social_sentiment'] = {
                'latest_metrics': sentiment_data if sentiment_data else [],
                'alerts': alerts if alerts else []
            }
            result['found'] = True
    except Exception as e:
        logger.warning(f"Error fetching social sentiment for {ticker_upper}: {e}")
    
    return result


def _fetch_congress_trades(ticker_upper: str, supabase_client: Optional[SupabaseClient], postgres_client: Optional[PostgresClient]) -> Dict[str, Any]:
    """Fetch congress trades and analysis."""
    result = {'congress_trades': [], 'found': False}
    if not supabase_client:
        return result

    try:
        congress_result = supabase_client.supabase.table("congress_trades_enriched")\
            .select("*")\
            .eq("ticker", ticker_upper)\
            .order("transaction_date", desc=True)\
            .execute()

        if congress_result.data:
            trades = congress_result.data
            analysis_map = {}
            if postgres_client:
                trade_ids = [trade.get("id") for trade in trades if trade.get("id") is not None]
                if trade_ids:
                    try:
                        analysis_rows = postgres_client.execute_query(
                            "SELECT trade_id, conflict_score, reasoning "
                            "FROM congress_trades_analysis "
                            "WHERE trade_id = ANY(%s)",
                            (trade_ids,)
                        )
                        for row in analysis_rows:
                            analysis_map[row["trade_id"]] = row
                    except Exception as e:
                        logger.warning(f"Error fetching congress trade analysis for {ticker_upper}: {e}")

            formatted_trades = []
            for trade in trades:
                trade_id = trade.get("id")
                analysis = analysis_map.get(trade_id, {})
                conflict_score = analysis.get("conflict_score")
                reasoning = analysis.get("reasoning") or ""

                if conflict_score is not None:
                    score_val = float(conflict_score)
                    if score_val >= 0.7:
                        score_display = f"🔴 {score_val:.2f}"
                    elif score_val >= 0.3:
                        score_display = f"🟡 {score_val:.2f}"
                    else:
                        score_display = f"🟢 {score_val:.2f}"
                else:
                    score_display = "⚪ N/A"

                reasoning_short = reasoning[:120] + "..." if reasoning and len(reasoning) > 120 else reasoning

                formatted_trade = dict(trade)
                formatted_trade["score_display"] = score_display
                formatted_trade["analysis_reasoning"] = reasoning
                formatted_trade["analysis_reasoning_short"] = reasoning_short
                formatted_trades.append(formatted_trade)

            result['congress_trades'] = formatted_trades
            result['found'] = True
    except Exception as e:
        logger.warning(f"Error fetching congress trades for {ticker_upper}: {e}")

    return result


def _fetch_insider_trades(ticker_upper: str, supabase_client: Optional[SupabaseClient]) -> Dict[str, Any]:
    """Fetch insider trades."""
    result = {'insider_trades': [], 'found': False}
    if not supabase_client:
        return result

    try:
        from web_dashboard.utils.logo_utils import get_ticker_logo_url

        insider_result = supabase_client.supabase.table("insider_trades")\
            .select("ticker, insider_name, insider_title, transaction_date, disclosure_date, "
                    "type, shares, price_per_share, value, shares_held_after, percent_change, notes, created_at")\
            .eq("ticker", ticker_upper)\
            .order("transaction_date", desc=True)\
            .limit(50)\
            .execute()

        if insider_result.data:
            logo_url = get_ticker_logo_url(ticker_upper)
            formatted_trades = []
            for trade in insider_result.data:
                formatted_trade = dict(trade)
                formatted_trade["_logo_url"] = logo_url
                formatted_trades.append(formatted_trade)

            result['insider_trades'] = formatted_trades
            result['found'] = True
    except Exception as e:
        logger.warning(f"Error fetching insider trades for {ticker_upper}: {e}")
    
    return result


def _fetch_watchlist_status(ticker_upper: str, supabase_client: Optional[SupabaseClient]) -> Dict[str, Any]:
    """Fetch watchlist status."""
    result = {'watchlist_status': None, 'found': False}
    if not supabase_client:
        return result

    try:
        watchlist_result = supabase_client.supabase.table("watched_tickers")\
            .select("*")\
            .eq("ticker", ticker_upper)\
            .execute()

        if watchlist_result.data and len(watchlist_result.data) > 0:
            result['watchlist_status'] = watchlist_result.data[0]
            result['found'] = True
    except Exception as e:
        logger.warning(f"Error fetching watchlist status for {ticker_upper}: {e}")

    return result


def get_ticker_info(
    ticker: str,
    supabase_client=None,
    postgres_client=None,
    fund: Optional[str] = None
) -> Dict[str, Any]:
    """Get comprehensive ticker information from all databases.

    Aggregates ticker data from multiple sources (Supabase and Postgres) including
    basic security info, portfolio data, research articles, social sentiment,
    congress trades, and watchlist status.

    Args:
        ticker: Ticker symbol (e.g., "AAPL", "XMA.TO")
        supabase_client: Optional SupabaseClient instance for accessing securities,
            positions, trades, congress data, and watchlist
        postgres_client: Optional PostgresClient instance for accessing research
            articles and social sentiment metrics
        fund: Optional fund name to filter portfolio data (positions/trades)

    Returns:
        Dictionary with structure described in docstring.
    """
    ticker_upper = ticker.upper().strip()
    result = {
        'ticker': ticker_upper,
        'basic_info': None,
        'portfolio_data': None,
        'research_articles': [],
        'social_sentiment': None,
        'congress_trades': [],
        'insider_trades': [],
        'watchlist_status': None,
        'found': False
    }

    fund_filter = _normalize_fund_filter(fund)

    # Execute fetches in parallel using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = {
            executor.submit(_fetch_basic_info, ticker_upper, supabase_client): 'basic_info',
            executor.submit(_fetch_portfolio_data, ticker_upper, supabase_client, fund_filter): 'portfolio_data',
            executor.submit(_fetch_research_articles, ticker_upper, postgres_client): 'research_articles',
            executor.submit(_fetch_social_sentiment, ticker_upper, postgres_client): 'social_sentiment',
            executor.submit(_fetch_congress_trades, ticker_upper, supabase_client, postgres_client): 'congress_trades',
            executor.submit(_fetch_insider_trades, ticker_upper, supabase_client): 'insider_trades',
            executor.submit(_fetch_watchlist_status, ticker_upper, supabase_client): 'watchlist_status'
        }

        for future in as_completed(futures):
            try:
                partial_result = future.result()
                if partial_result:
                    # Update result with data from partial result
                    # Skip 'found' key during merge, handle it separately
                    for key, value in partial_result.items():
                        if key != 'found':
                            result[key] = value

                    # Update found flag if any partial result found data
                    if partial_result.get('found'):
                        result['found'] = True

            except Exception as e:
                task_name = futures[future]
                logger.error(f"Error in task {task_name} for {ticker_upper}: {e}", exc_info=True)

    return result


def get_ticker_price_history(
    ticker: str,
    supabase_client=None,
    days: int = 90,
    fund: Optional[str] = None
) -> pd.DataFrame:
    """Get historical price data for a ticker from portfolio_positions or yfinance.
    
    Fetches price history for the last N days, using portfolio_positions table
    if available, otherwise falling back to yfinance API.
    
    Args:
        ticker: Ticker symbol (e.g., "AAPL")
        supabase_client: Optional SupabaseClient instance
        days: Number of days to look back (default: 90 for 3 months)
        fund: Optional fund name to filter portfolio data
        
    Returns:
        DataFrame with columns: date, price, normalized (baseline 100)
        Empty DataFrame if no data available
    """
    ticker_upper = ticker.upper().strip()
    result_df = pd.DataFrame()
    fund_filter = _normalize_fund_filter(fund)
    
    # Calculate date range
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    
    # Try portfolio_positions first
    if supabase_client:
        try:
            pos_query = supabase_client.supabase.table("portfolio_positions")\
                .select("date, price")\
                .eq("ticker", ticker_upper)\
                .gte("date", start_date.isoformat())
            if fund_filter:
                pos_query = pos_query.eq("fund", fund_filter)
            pos_result = pos_query.order("date").execute()
            
            if pos_result.data and len(pos_result.data) >= 10:
                # We have enough data from portfolio_positions
                df = pd.DataFrame(pos_result.data)
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date')
                
                # Normalize to baseline 100 using first price
                if len(df) > 0 and df['price'].iloc[0] > 0:
                    baseline_price = float(df['price'].iloc[0])
                    df['normalized'] = (df['price'].astype(float) / baseline_price) * 100
                    result_df = df[['date', 'price', 'normalized']].copy()
                    logger.info(f"Using portfolio_positions data for {ticker_upper}: {len(result_df)} data points")
                    return result_df
        except Exception as e:
            logger.warning(f"Error fetching from portfolio_positions for {ticker_upper}: {e}")
    
    # Fallback to yfinance if insufficient portfolio data
    try:
        import yfinance as yf
        yf_candidates = _get_yfinance_ticker_candidates(ticker_upper)
        logger.info(
            f"Fetching {ticker_upper} price history from Yahoo Finance candidates: {yf_candidates} (last {days} days)"
        )
        
        # Add buffer days to ensure we get data
        buffer_start = start_date - timedelta(days=5)
        buffer_end = end_date + timedelta(days=2)

        for yf_symbol in yf_candidates:
            try:
                ticker_obj = yf.Ticker(yf_symbol)
                data = ticker_obj.history(start=buffer_start, end=buffer_end, auto_adjust=False)

                if data.empty:
                    logger.debug(f"No Yahoo Finance data for candidate {yf_symbol}")
                    continue

                # Convert to DataFrame
                data = data.reset_index()
                data['Date'] = pd.to_datetime(data['Date'])

                # Filter to date range
                data = data[(data['Date'] >= start_date) & (data['Date'] <= end_date)]

                if data.empty:
                    logger.debug(f"No Yahoo Finance data in date range for candidate {yf_symbol}")
                    continue

                # Use Close price
                df = pd.DataFrame({
                    'date': data['Date'],
                    'price': data['Close']
                })
                df = df.sort_values('date')

                # Normalize to baseline 100 using first price
                if len(df) > 0 and df['price'].iloc[0] > 0:
                    baseline_price = float(df['price'].iloc[0])
                    df['normalized'] = (df['price'].astype(float) / baseline_price) * 100
                    result_df = df[['date', 'price', 'normalized']].copy()
                    logger.info(
                        f"Using Yahoo Finance data for {ticker_upper} via {yf_symbol}: {len(result_df)} data points"
                    )
                    return result_df
            except Exception as candidate_error:
                logger.debug(
                    f"Error fetching Yahoo Finance price history for candidate {yf_symbol}: {candidate_error}"
                )

        logger.warning(f"No Yahoo Finance data available for any candidate of {ticker_upper}")
        
    except Exception as e:
        logger.error(f"Error fetching from yfinance for {ticker_upper}: {e}")
    
    return pd.DataFrame()


def get_ticker_external_links(ticker: str, exchange: Optional[str] = None) -> Dict[str, str]:
    """Generate external links to financial websites for a ticker.
    
    Creates links to major financial data sources including Yahoo Finance,
    TradingView, Finviz, MarketWatch, StockTwits, Reddit, and
    Google Finance. Handles both US and Canadian tickers appropriately.
    
    Args:
        ticker: Ticker symbol (e.g., "AAPL", "XMA.TO", "SHOP.V")
        exchange: Optional exchange code for more specific routing.
            Supported: 'NASDAQ', 'NYSE', 'TSX', 'TSXV', 'AMEX'
        
    Returns:
        Dictionary mapping site names to full URLs:
        {
            'Yahoo Finance': str,
            'TradingView': str,
            'Finviz': str,
            'Symbol Research': str,
            'MarketWatch': str,
            'StockTwits': str,
            'Reddit (WSB)': str,
            'Google Finance': str
        }
    
    Example:
        >>> links = get_ticker_external_links("AAPL", "NASDAQ")
        >>> print(links['Yahoo Finance'])
        'https://finance.yahoo.com/quote/AAPL'
        >>> print(links['TradingView'])
        'https://www.tradingview.com/symbols/NASDAQ-AAPL/'
        >>> 
        >>> # Canadian ticker
        >>> links = get_ticker_external_links("XMA.TO", "TSX")
        >>> print(links['TradingView'])
        'https://www.tradingview.com/symbols/TSX-XMA/'
        >>> print(links['MarketWatch'])
        'https://www.marketwatch.com/investing/stock/TSX:XMA'
    
    Note:
        - Canadian ticker suffixes (.TO, .V) are automatically detected
        - Base ticker extracted for sites that don't support suffixes
        - MarketWatch uses TSX:TICKER format for Canadian stocks
        - Finviz doesn't support Canadian tickers well (may not work)
        - All URLs are properly formatted and URL-safe
    """
    ticker_upper = ticker.upper().strip()
    
    # Handle Canadian tickers
    base_ticker = ticker_upper
    is_canadian = False
    canadian_exchange = None
    if '.TO' in ticker_upper:
        base_ticker = ticker_upper.replace('.TO', '')
        is_canadian = True
        canadian_exchange = 'TSX'
        exchange = exchange or 'TSX'
    elif '.V' in ticker_upper:
        base_ticker = ticker_upper.replace('.V', '')
        is_canadian = True
        canadian_exchange = 'TSXV'
        exchange = exchange or 'TSXV'
    
    links = {}
    
    # Yahoo Finance - supports .TO/.V suffixes
    links['Yahoo Finance'] = f"https://finance.yahoo.com/quote/{ticker_upper}"
    
    # TradingView - uses EXCHANGE-TICKER format
    if exchange:
        # Try to map exchange to TradingView format
        exchange_map = {
            'NASDAQ': 'NASDAQ',
            'NYSE': 'NYSE',
            'TSX': 'TSX',
            'TSXV': 'TSXV',
            'AMEX': 'AMEX'
        }
        tv_exchange = exchange_map.get(exchange, exchange)
        links['TradingView'] = f"https://www.tradingview.com/symbols/{tv_exchange}-{base_ticker}/"
    else:
        links['TradingView'] = f"https://www.tradingview.com/symbols/{base_ticker}/"
    
    # Finviz - doesn't support Canadian tickers well
    # For Canadian stocks, this will likely not work, but we include it anyway
    # Users can manually search if needed
    if is_canadian:
        # Finviz doesn't support Canadian exchanges, so this link may not work
        # But we include it for consistency - users will see it doesn't work
        links['Finviz'] = f"https://finviz.com/quote.ashx?t={base_ticker}"
    else:
        links['Finviz'] = f"https://finviz.com/quote.ashx?t={base_ticker}"
    
    # Symbol research - uses EXCHANGE:TICKER format for Canadian stocks
    import os
    symbol_base_url = os.getenv("SYMBOL_ARTICLE_BASE_URL", "")
    if symbol_base_url:
        if is_canadian and canadian_exchange:
            links['Symbol Research'] = f"{symbol_base_url}/symbol/{canadian_exchange}:{base_ticker}"
        else:
            links['Symbol Research'] = f"{symbol_base_url}/symbol/{base_ticker}"
    
    # MarketWatch - uses EXCHANGE:TICKER format for Canadian stocks
    if is_canadian and canadian_exchange:
        links['MarketWatch'] = f"https://www.marketwatch.com/investing/stock/{canadian_exchange}:{base_ticker}"
    else:
        links['MarketWatch'] = f"https://www.marketwatch.com/investing/stock/{base_ticker}"
    
    # StockTwits - uses base ticker (without .TO/.V suffix) for all stocks including Canadian
    # StockTwits doesn't support .TO/.V suffixes, so we use the base ticker
    links['StockTwits'] = f"https://stocktwits.com/symbol/{base_ticker}"
    
    # Reddit (wallstreetbets search) - use full ticker for better search results
    links['Reddit (WSB)'] = f"https://www.reddit.com/r/wallstreetbets/search/?q={ticker_upper}&restrict_sr=1"
    
    # Google Finance - supports .TO/.V suffixes
    links['Google Finance'] = f"https://www.google.com/finance/quote/{ticker_upper}"
    
    return links


def render_ticker_link(
    ticker: str,
    display_text: Optional[str] = None,
    use_page_link: bool = True
) -> str:
    """Generate a clickable ticker link for Streamlit markdown rendering.
    
    Creates markdown-formatted links that navigate to the ticker details page.
    Note: Only works in markdown contexts (st.markdown, st.write with markdown),
    NOT in st.dataframe() or AgGrid.
    
    Args:
        ticker: Ticker symbol (e.g., "AAPL", "TSLA")
        display_text: Optional text to display for the link.
            If None, displays the ticker symbol itself.
        use_page_link: If True, uses Streamlit's page navigation format.
            If False, uses query parameter format (legacy).
        
    Returns:
        Markdown link string in format: "[display](url)"
    
    Example:
        >>> link = render_ticker_link("AAPL")
        >>> print(link)
        '[AAPL](ticker_details?ticker=AAPL)'
        >>> 
        >>> # Custom display text
        >>> link = render_ticker_link("AAPL", "Apple Inc.")
        >>> print(link)
        '[Apple Inc.](ticker_details?ticker=AAPL)'
        >>> 
        >>> # Use in Streamlit markdown
        >>> import streamlit as st
        >>> st.markdown(f"View details for {render_ticker_link('AAPL')}")
    
    Warning:
        This does NOT work in st.dataframe() or AgGrid - the markdown
        will display as plain text. For tables, consider:
        - st.data_editor() with LinkColumn (Streamlit 1.29+)
        - Separate "View Details" button column
        - Custom HTML table with unsafe_allow_html=True
    """
    ticker_upper = ticker.upper().strip()
    display = display_text if display_text else ticker_upper
    
    if use_page_link:
        # Use Streamlit page_link format
        # Format: ticker_details?ticker=AAPL
        return f"[{display}](ticker_details?ticker={ticker_upper})"
    else:
        # Fallback to query parameter format
        return f"[{display}](?ticker={ticker_upper})"


def make_tickers_clickable(text: str) -> str:
    """Find ticker patterns in text and convert them to clickable links.
    
    Args:
        text: Text that may contain ticker symbols
        
    Returns:
        Text with tickers converted to markdown links
    """
    # Pattern for ticker symbols (1-5 uppercase letters, optionally with .TO, .V, etc.)
    ticker_pattern = r'\b([A-Z]{1,5}(?:\.(?:TO|V|CN|NE|TSX))?)\b'
    
    # False positives to exclude (common words, technical terms, financial/business acronyms)
    false_positives = {
        # Common words
        'I', 'A', 'AN', 'THE', 'IS', 'IT', 'TO', 'BE', 'OR', 'OF', 'IN',
        'ON', 'AT', 'BY', 'FOR', 'AS', 'WE', 'HE', 'MY', 'ME', 'US', 'SO',
        'DO', 'GO', 'NO', 'UP', 'IF', 'AM', 'PM', 'OK', 'TV', 'PC',
        # Technical terms
        'AI', 'API', 'URL', 'HTTP', 'HTTPS', 'PDF', 'CSV', 'JSON', 'XML', 'HTML',
        'SQL', 'REST', 'SOAP', 'SSH', 'FTP', 'VPN', 'DNS', 'IP',
        # Financial/Business acronyms
        'SEC', 'ETF', 'IPO', 'CEO', 'CFO', 'CTO', 'COO', 'CMO', 'CIO',
        'PE', 'PS', 'EPS', 'ROI', 'ROE', 'ROA', 'EBIT', 'FCF',
        'LLC', 'INC', 'LTD', 'CORP', 'PLC', 'GAAP', 'FDA', 'FTC',
        'IR', 'PR', 'HR', 'IT', 'RD', 'QA', 'VC', 'MA', 'USD', 'CAD',
        'YOY', 'MOM', 'QOQ', 'YTD', 'MTD', 'EOD', 'AUM', 'NAV'
    }
    
    def replace_ticker(match):
        ticker = match.group(1)
        base_ticker = ticker.split('.')[0]
        
        # Skip false positives
        if base_ticker in false_positives:
            return ticker
        
        # Convert to link
        return render_ticker_link(ticker, ticker, use_page_link=True)
    
    # Replace all ticker patterns
    result = re.sub(ticker_pattern, replace_ticker, text)
    
    return result
