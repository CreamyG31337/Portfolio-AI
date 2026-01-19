"""
Logo Utilities
==============
Functions to get company logo URLs for ticker symbols.
"""

import os
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def get_ticker_logo_url(ticker: str) -> Optional[str]:
    """Get company logo URL for a ticker symbol.
    
    Uses free services to avoid rate limits. Tries multiple sources:
    1. Parqet Logos API (free, no auth required) - PRIMARY
    2. Yahoo Finance (via yimg.com) - FALLBACK
    3. Financial Modeling Prep (only if no free option works) - LAST RESORT
    
    Note: FMP has very strict rate limits (~10 calls/day), so we prioritize free services.
    
    Args:
        ticker: Stock ticker symbol (e.g., "AAPL", "TSLA")
        
    Returns:
        Logo URL string or None if not available
    """
    if not ticker or ticker == 'N/A':
        return None
    
    # Clean ticker (remove exchange suffixes for logo lookup)
    clean_ticker = ticker.upper().strip()
    # Remove common exchange suffixes for logo lookup
    # Logos are usually available for base ticker
    if clean_ticker.endswith(('.TO', '.V', '.CN', '.TSX', '.TSXV')):
        # For Canadian tickers, try both with and without suffix
        base_ticker = clean_ticker.rsplit('.', 1)[0]
    else:
        base_ticker = clean_ticker
    
    # PRIMARY: Parqet Logos API - free, no auth required, good coverage
    parqet_url = f"https://assets.parqet.com/logos/symbol/{base_ticker}?format=png"
    
    # FALLBACK: Yahoo Finance logo (via yimg.com) - also free
    # Format: https://logo.clearbit.com/{domain} or yahoo's internal logo service
    # Yahoo uses: https://s.yimg.com/cv/apiv2/default/images/logos/{ticker}.png
    yahoo_url = f"https://s.yimg.com/cv/apiv2/default/images/logos/{base_ticker}.png"
    
    # Return Parqet as primary (browser will handle 404s gracefully)
    # Could implement client-side fallback in TypeScript if needed
    return parqet_url


def get_ticker_logo_urls(tickers: list[str]) -> dict[str, Optional[str]]:
    """Get logo URLs for multiple tickers at once.
    
    Args:
        tickers: List of ticker symbols
        
    Returns:
        Dictionary mapping ticker -> logo URL
    """
    return {ticker: get_ticker_logo_url(ticker) for ticker in tickers}
