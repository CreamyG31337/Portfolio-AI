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
        pass

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
        Dictionary with the following structure:
        {
            'ticker': str,  # Uppercase ticker symbol
            'found': bool,  # True if any data found for this ticker
            'basic_info': dict | None,  # From securities table
                {
                    'ticker': str,
                    'company_name': str,
                    'sector': str,
                    'industry': str,
                    'currency': str,  # 'USD', 'CAD', etc.
                    'exchange': str,   # 'NASDAQ', 'NYSE', 'TSX', etc.
                    'description': str  # Company business description (or ETF fund description)
                }
            'portfolio_data': dict | None,
                {
                    'positions': list[dict],  # Latest 100 positions
                    'trades': list[dict],     # Latest 100 trades
                    'has_positions': bool,
                    'has_trades': bool
                }
            'research_articles': list[dict],  # Last 30 days, limit 50
                [
                    {
                        'id': int,
                        'title': str,
                        'url': str,
                        'summary': str,
                        'source': str,
                        'published_at': datetime,
                        'fetched_at': datetime,
                        'relevance_score': float,
                        'sentiment': str,  # 'positive', 'negative', 'neutral'
                        'sentiment_score': float,
                        'article_type': str
                    }
                ]
            'social_sentiment': dict | None,
                {
                    'latest_metrics': list[dict],  # Latest per platform
                    'alerts': list[dict]           # Extreme alerts (24h)
                }
            'congress_trades': list[dict],  # Last 30 days, limit 50
                [
                    {
                        'ticker': str,
                        'politician': str,
                        'chamber': str,  # 'House' or 'Senate'
                        'party': str,
                        'type': str,     # 'Purchase' or 'Sale'
                        'amount': str,
                        'transaction_date': date
                    }
                ]
            'watchlist_status': dict | None,
                {
                    'ticker': str,
                    'priority_tier': str,  # 'A', 'B', or 'C'
                    'source': str,
                    'is_active': bool
                }
        }
    
    Example:
        >>> from supabase_client import SupabaseClient
        >>> from postgres_client import PostgresClient
        >>> 
        >>> sb_client = SupabaseClient()
        >>> pg_client = PostgresClient()
        >>> 
        >>> # Get info for Apple
        >>> info = get_ticker_info("AAPL", sb_client, pg_client)
        >>> print(info['basic_info']['company_name'])
        'Apple Inc.'
        >>> print(f"Found {len(info['research_articles'])} articles")
        Found 15 articles
        >>> 
        >>> # Canadian ticker
        >>> info = get_ticker_info("XMA.TO", sb_client, pg_client)
        >>> print(info['basic_info']['exchange'])
        'TSX'
    
    Note:
        - Function makes 6 separate database queries (can be slow for large datasets)
        - Returns empty lists/None for missing data rather than raising exceptions
        - All timestamps should be timezone-aware (UTC)
        - Warnings logged for individual query failures (doesn't fail entire function)
    """
    ticker_upper = ticker.upper().strip()
    result = {
        'ticker': ticker_upper,
        'basic_info': None,
        'portfolio_data': None,
        'research_articles': [],
        'social_sentiment': None,
        'congress_trades': [],
        'watchlist_status': None,
        'found': False
    }
    
    # 1. Get basic info from securities table
    if supabase_client:
        try:
            sec_result = supabase_client.supabase.table("securities")\
                .select("*")\
                .eq("ticker", ticker_upper)\
                .execute()
            
            if sec_result.data and len(sec_result.data) > 0:
                result['basic_info'] = sec_result.data[0]
                # Add logo URL for frontend display
                try:
                    from web_dashboard.utils.logo_utils import get_ticker_logo_url
                    logo_url = get_ticker_logo_url(ticker_upper)
                    if logo_url:
                        result['basic_info']['logo_url'] = logo_url
                except Exception as e:
                    logger.warning(f"Error fetching logo URL for {ticker_upper}: {e}")
                
                # If no description exists, try to fetch it (async, won't block)
                if not result['basic_info'].get('description'):
                    try:
                        from web_dashboard.utils.company_description import ensure_company_description
                        description = ensure_company_description(ticker_upper, supabase_client, force_refresh=False)
                        if description:
                            result['basic_info']['description'] = description
                    except Exception as e:
                        logger.debug(f"Could not fetch company description for {ticker_upper}: {e}")
                
                result['found'] = True
        except Exception as e:
            logger.warning(f"Error fetching basic info for {ticker_upper}: {e}")
    
    # If no basic info found, try fetching from yfinance
    if not result['basic_info']:
        try:
            import yfinance as yf
            logger.info(f"Looking up {ticker_upper} from Yahoo Finance...")
            ticker_obj = yf.Ticker(ticker_upper)
            info = ticker_obj.info
            
            if info and info.get('symbol'):
                # Extract fields with multiple fallback attempts
                company_name = (
                    info.get('longName') or 
                    info.get('shortName') or 
                    info.get('displayName') or 
                    ticker_upper
                )
                
                # Sector - try multiple fields
                sector = (
                    info.get('sector') or 
                    info.get('sectorDisp') or 
                    info.get('sectorKey')
                )
                
                # Industry - try multiple fields
                industry = (
                    info.get('industry') or 
                    info.get('industryDisp') or 
                    info.get('industryKey')
                )
                
                # Currency
                currency = info.get('currency') or info.get('financialCurrency') or 'USD'
                
                # Exchange
                exchange = (
                    info.get('exchange') or 
                    info.get('exchangeName') or 
                    info.get('fullExchangeName')
                )
                
                # Get company description from yfinance
                company_description = (
                    info.get('longBusinessSummary') or 
                    info.get('longDescription') or 
                    info.get('description')
                )
                
                # Create basic_info structure from yfinance data
                result['basic_info'] = {
                    'ticker': ticker_upper,
                    'company_name': company_name,
                    'sector': sector if sector else None,
                    'industry': industry if industry else None,
                    'currency': currency,
                    'exchange': exchange if exchange else None,
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
                
                # Save to database for future lookups
                if supabase_client:
                    try:
                        supabase_client.supabase.table("securities").insert(result['basic_info']).execute()
                        logger.info(f"Saved ticker {ticker_upper} ({company_name}) to securities table from yfinance")
                    except Exception as insert_error:
                        # If insert fails (e.g., duplicate), just log it - we still have the data
                        logger.warning(f"Could not save {ticker_upper} to database: {insert_error}")
            else:
                logger.warning(f"Could not find ticker information for {ticker_upper} in yfinance")
        except Exception as e:
            logger.warning(f"Error fetching from yfinance for {ticker_upper}: {e}")
    
    # If we have basic_info but it's incomplete (None values for sector/industry), try to enrich from yfinance
    if result['basic_info'] and (result['basic_info'].get('sector') is None or result['basic_info'].get('industry') is None):
        try:
            import yfinance as yf
            logger.info(f"Re-fetching {ticker_upper} from yfinance due to incomplete data")
            
            ticker_obj = yf.Ticker(ticker_upper)
            info = ticker_obj.info
            
            if info and info.get('symbol'):
                # Try to get missing fields
                sector = result['basic_info'].get('sector') or info.get('sector') or info.get('sectorDisp') or info.get('sectorKey')
                industry = result['basic_info'].get('industry') or info.get('industry') or info.get('industryDisp') or info.get('industryKey')
                
                # Update if we got new data
                if sector or industry:
                    result['basic_info']['sector'] = sector
                    result['basic_info']['industry'] = industry
                    
                    # Update database
                    if supabase_client:
                        try:
                            supabase_client.supabase.table("securities")\
                                .update({'sector': sector, 'industry': industry})\
                                .eq('ticker', ticker_upper)\
                                .execute()
                            logger.info(f"Updated {ticker_upper} with sector/industry from yfinance")
                        except Exception as update_error:
                            logger.warning(f"Could not update {ticker_upper}: {update_error}")
        except Exception as e:
            logger.warning(f"Error re-fetching data for {ticker_upper}: {e}")
    
    fund_filter = _normalize_fund_filter(fund)

    # 2. Get portfolio data (positions and trades)
    if supabase_client:
        try:
            # Get current positions
            pos_query = supabase_client.supabase.table("portfolio_positions")\
                .select("*")\
                .eq("ticker", ticker_upper)
            if fund_filter:
                pos_query = pos_query.eq("fund", fund_filter)
            pos_result = pos_query.order("date", desc=True).limit(100).execute()
            
            # Get trade history
            trade_query = supabase_client.supabase.table("trade_log")\
                .select("*")\
                .eq("ticker", ticker_upper)
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
    
    # 3. Get research articles (last 30 days)
    if postgres_client:
        try:
            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
            query = """
                SELECT id, title, url, summary, source, published_at, fetched_at,
                       relevance_score, sentiment, sentiment_score, article_type
                FROM research_articles
                WHERE tickers @> ARRAY[%s]::text[]
                   OR ticker = %s
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
    
    # 4. Get social sentiment (latest metrics)
    if postgres_client:
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
            
            # Get extreme alerts (last 24 hours) - deduplicated by platform and sentiment_label
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
    
    # 5. Get congress trades (all trades for this ticker)
    if supabase_client:
        try:
            congress_result = supabase_client.supabase.table("congress_trades_enriched")\
                .select("*")\
                .eq("ticker", ticker_upper)\
                .order("transaction_date", desc=True)\
                .execute()
            
            if congress_result.data:
                result['congress_trades'] = congress_result.data
                result['found'] = True
        except Exception as e:
            logger.warning(f"Error fetching congress trades for {ticker_upper}: {e}")
    
    # 6. Get watchlist status
    if supabase_client:
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
        logger.info(f"Fetching {ticker_upper} price history from yfinance (last {days} days)")
        
        # Add buffer days to ensure we get data
        buffer_start = start_date - timedelta(days=5)
        buffer_end = end_date + timedelta(days=2)
        
        ticker_obj = yf.Ticker(ticker_upper)
        data = ticker_obj.history(start=buffer_start, end=buffer_end, auto_adjust=False)
        
        if data.empty:
            logger.warning(f"No yfinance data available for {ticker_upper}")
            return pd.DataFrame()
        
        # Convert to DataFrame
        data = data.reset_index()
        data['Date'] = pd.to_datetime(data['Date'])
        
        # Filter to date range
        data = data[(data['Date'] >= start_date) & (data['Date'] <= end_date)]
        
        if data.empty:
            logger.warning(f"No yfinance data in date range for {ticker_upper}")
            return pd.DataFrame()
        
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
            logger.info(f"Using yfinance data for {ticker_upper}: {len(result_df)} data points")
            return result_df
        
    except Exception as e:
        logger.error(f"Error fetching from yfinance for {ticker_upper}: {e}")
    
    return pd.DataFrame()


def get_ticker_external_links(ticker: str, exchange: Optional[str] = None) -> Dict[str, str]:
    """Generate external links to financial websites for a ticker.
    
    Creates links to major financial data sources including Yahoo Finance,
    TradingView, Finviz, Seeking Alpha, MarketWatch, StockTwits, Reddit, and
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
            'Seeking Alpha': str,
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
    
    # Seeking Alpha - uses EXCHANGE:TICKER format for Canadian stocks
    if is_canadian and canadian_exchange:
        links['Seeking Alpha'] = f"https://seekingalpha.com/symbol/{canadian_exchange}:{base_ticker}"
    else:
        links['Seeking Alpha'] = f"https://seekingalpha.com/symbol/{base_ticker}"
    
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

