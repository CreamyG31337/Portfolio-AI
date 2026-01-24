"""
Company Description Fetcher
============================

Reusable module for fetching and storing company descriptions from yfinance.
Stores descriptions in the description column (used for both ETFs and stocks).
Can be called from jobs, API endpoints, or other modules.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def fetch_company_description(ticker: str) -> Optional[str]:
    """
    Fetch company description from yfinance.
    
    Args:
        ticker: Ticker symbol (e.g., "AAPL", "XMA.TO")
        
    Returns:
        Company description string (longBusinessSummary) or None if not available
    """
    try:
        import yfinance as yf
        
        ticker_upper = ticker.upper().strip()
        logger.debug(f"Fetching company description for {ticker_upper} from yfinance")
        
        stock = yf.Ticker(ticker_upper)
        info = stock.info
        
        if not info:
            logger.warning(f"No yfinance info available for {ticker_upper}")
            return None
        
        # Try longBusinessSummary first (most detailed)
        description = info.get('longBusinessSummary')
        
        # Fallback to shorter description if available
        if not description:
            description = info.get('longDescription') or info.get('description')
        
        if description:
            # Clean up the description (remove extra whitespace)
            description = description.strip()
            logger.debug(f"Successfully fetched description for {ticker_upper} ({len(description)} chars)")
            return description
        else:
            logger.debug(f"No description field available for {ticker_upper}")
            return None
            
    except Exception as e:
        logger.warning(f"Failed to fetch company description for {ticker}: {e}")
        return None


def ensure_company_description(
    ticker: str,
    supabase_client,
    force_refresh: bool = False
) -> Optional[str]:
    """
    Ensure company description exists in database, fetching from yfinance if needed.
    
    This function:
    1. Checks if description exists in securities table (description column)
    2. If missing or force_refresh=True, fetches from yfinance
    3. Updates the database with the description (stores in description column)
    4. Returns the description
    
    Note: Uses description column for both ETFs and company descriptions.
    
    Args:
        ticker: Ticker symbol (e.g., "AAPL", "XMA.TO")
        supabase_client: SupabaseClient instance
        force_refresh: If True, always fetch fresh data from yfinance
        
    Returns:
        Company description string or None if not available
    """
    try:
        ticker_upper = ticker.upper().strip()
        
        # Check if description already exists in database
        if not force_refresh:
            try:
                result = supabase_client.supabase.table("securities") \
                    .select("description") \
                    .eq("ticker", ticker_upper) \
                    .execute()
                
                if result.data and len(result.data) > 0:
                    existing_desc = result.data[0].get('description')
                    if existing_desc and existing_desc.strip():
                        logger.debug(f"Using existing description for {ticker_upper} from database")
                        return existing_desc.strip()
            except Exception as e:
                logger.warning(f"Error checking existing description for {ticker_upper}: {e}")
        
        # Fetch from yfinance
        logger.info(f"Fetching company description for {ticker_upper} from yfinance")
        description = fetch_company_description(ticker_upper)
        
        if description:
            # Store in database (using description column)
            try:
                # Check if ticker exists
                check_result = supabase_client.supabase.table("securities") \
                    .select("ticker") \
                    .eq("ticker", ticker_upper) \
                    .execute()
                
                if check_result.data and len(check_result.data) > 0:
                    # Update existing record
                    supabase_client.supabase.table("securities") \
                        .update({
                            "description": description,
                            "last_updated": datetime.now(timezone.utc).isoformat()
                        }) \
                        .eq("ticker", ticker_upper) \
                        .execute()
                    logger.info(f"✅ Updated company description for {ticker_upper} in database")
                else:
                    # Insert new record (minimal, just ticker and description)
                    supabase_client.supabase.table("securities") \
                        .insert({
                            "ticker": ticker_upper,
                            "description": description,
                            "last_updated": datetime.now(timezone.utc).isoformat()
                        }) \
                        .execute()
                    logger.info(f"✅ Inserted company description for {ticker_upper} in database")
            except Exception as e:
                logger.error(f"Error storing company description for {ticker_upper}: {e}")
                # Still return the description even if DB update fails
        else:
            logger.warning(f"No company description available for {ticker_upper}")
        
        return description
        
    except Exception as e:
        logger.error(f"Error ensuring company description for {ticker}: {e}")
        return None


def batch_fetch_descriptions(
    tickers: list[str],
    supabase_client,
    force_refresh: bool = False
) -> Dict[str, Optional[str]]:
    """
    Batch fetch company descriptions for multiple tickers.
    
    Args:
        tickers: List of ticker symbols
        supabase_client: SupabaseClient instance
        force_refresh: If True, always fetch fresh data from yfinance
        
    Returns:
        Dictionary mapping ticker -> description (or None)
    """
    results = {}
    
    for ticker in tickers:
        try:
            description = ensure_company_description(ticker, supabase_client, force_refresh)
            results[ticker.upper().strip()] = description
        except Exception as e:
            logger.warning(f"Error fetching description for {ticker}: {e}")
            results[ticker.upper().strip()] = None
    
    return results
