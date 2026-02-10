#!/usr/bin/env python3
"""
Database Utilities
==================

Utility functions for database operations across Supabase and PostgreSQL.
"""

import streamlit as st
from supabase_client import SupabaseClient
from postgres_client import PostgresClient
from web_dashboard.watchlist_access import get_active_watchlist_tickers
import logging

logger = logging.getLogger(__name__)

@st.cache_resource
def get_postgres_client():
    """Get Postgres client instance"""
    try:
        return PostgresClient()
    except Exception as e:
        logger.error(f"Failed to initialize PostgresClient: {e}")
        return None

@st.cache_resource
def get_supabase_client():
    """Get Supabase client instance"""
    try:
        return SupabaseClient(use_service_role=True)
    except Exception as e:
        logger.error(f"Failed to initialize SupabaseClient: {e}")
        return None


@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_all_unique_tickers() -> list[str]:
    """
    Aggregate unique tickers from all relevant database tables.

    Returns:
        List of unique ticker symbols sorted alphabetically.
    """
    tickers: set[str] = set()

    # Get Supabase client
    sb_client = get_supabase_client()
    if sb_client:
        try:
            # From securities table
            securities = sb_client.supabase.table('securities').select('ticker').execute()
            for row in securities.data:
                if row.get('ticker'):
                    tickers.add(row['ticker'].upper())

            # From portfolio_positions
            positions = sb_client.supabase.table('portfolio_positions').select('ticker').execute()
            for row in positions.data:
                if row.get('ticker'):
                    tickers.add(row['ticker'].upper())

            # From trade_log
            trades = sb_client.supabase.table('trade_log').select('ticker').execute()
            for row in trades.data:
                if row.get('ticker'):
                    tickers.add(row['ticker'].upper())

            # From watched_tickers (active only, via shared accessor)
            try:
                watched_tickers = get_active_watchlist_tickers(sb_client)
                tickers.update(watched_tickers)
            except Exception as e:
                logger.warning(f"Error fetching watchlist tickers: {e}")

            # From congress_trades
            congress = sb_client.supabase.table('congress_trades').select('ticker').execute()
            for row in congress.data:
                if row.get('ticker'):
                    tickers.add(row['ticker'].upper())

        except Exception as e:
            logger.error(f"Error fetching tickers from Supabase: {e}")
            st.error(f"Error fetching tickers from Supabase: {e}")

    # Get PostgreSQL client for research DB
    pg_client = get_postgres_client()
    if pg_client:
        try:
            # From research_articles (unnest array)
            articles = pg_client.execute_query("""
                SELECT DISTINCT UNNEST(tickers) as ticker
                FROM research_articles
                WHERE tickers IS NOT NULL
            """)
            for row in articles:
                if row.get('ticker'):
                    tickers.add(row['ticker'].upper())

            # From social_metrics
            social = pg_client.execute_query("SELECT DISTINCT ticker FROM social_metrics")
            for row in social:
                if row.get('ticker'):
                    tickers.add(row['ticker'].upper())

        except Exception as e:
            logger.error(f"Error fetching tickers from PostgreSQL: {e}")
            st.error(f"Error fetching tickers from PostgreSQL: {e}")

    # Return sorted list
    return sorted(tickers)


@st.cache_data(ttl=300)
def fetch_dividend_log(days_lookback: int = 365, fund: str = None) -> list[dict]:
    """
    Fetch dividend log from Supabase.
    
    Args:
        days_lookback: Number of days of history to fetch (default 365)
        fund: Optional fund name to filter by
        
    Returns:
        List of dicts containing dividend records
    """
    client = get_supabase_client()
    if not client:
        return []
        
    try:
        # Calculate start date
        from datetime import datetime, timedelta
        start_date = (datetime.now() - timedelta(days=days_lookback)).date().isoformat()
        
        query = client.supabase.table('dividend_log')\
            .select('*')\
            .gte('pay_date', start_date)
        
        # Apply fund filter if provided
        if fund:
            query = query.eq('fund', fund)
            
        response = query.order('pay_date', desc=True).execute()
            
        return response.data
    except Exception as e:
        logger.error(f"Error fetching dividend log: {e}")
        st.error(f"Error fetching dividend log: {e}")
        return []

        return []
