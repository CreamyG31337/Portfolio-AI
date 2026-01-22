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
    
    Caching-friendly design:
    - Returns stable URLs (no cache-busting parameters)
    - Browser caching handles image storage
    - Future: Can easily add server-side file caching by checking static/logos/{ticker}.png
      and downloading if missing, then returning /assets/logos/{ticker}.png instead
    
    Args:
        ticker: Stock ticker symbol (e.g., "AAPL", "TSLA")
        
    Returns:
        Logo URL string or None if not available
    """
    if not ticker or ticker == 'N/A':
        return None
    
    # Clean ticker (remove spaces, but keep exchange suffixes for Parqet)
    # Parqet requires the full ticker with suffix for Canadian tickers (e.g., DRX.TO)
    # but also works with base ticker for US tickers (e.g., AAPL)
    clean_ticker = ticker.upper().strip().replace(' ', '')  # Remove spaces (e.g., "SYM UQ" -> "SYMUQ")
    
    # For Parqet: Use full ticker (with suffix if present)
    # Testing shows Parqet needs full ticker for Canadian exchanges (DRX.TO works, DRX doesn't)
    # But also works fine with US tickers without suffix (AAPL works)
    parqet_ticker = clean_ticker
    
    # For Yahoo Finance fallback: Try base ticker (Yahoo typically doesn't have Canadian tickers with suffix)
    # Extract base ticker for Yahoo fallback
    if '.' in clean_ticker:
        parts = clean_ticker.rsplit('.', 1)
        if len(parts) == 2 and parts[1] in ('TO', 'V', 'CN', 'TSX', 'TSXV', 'NE', 'NEO'):
            base_ticker = parts[0]
        else:
            base_ticker = clean_ticker
    else:
        base_ticker = clean_ticker
    
    # PRIMARY: Parqet Logos API - free, no auth required, good coverage
    # Using size=64 for smaller file sizes (5-10KB vs 10-15KB for 100x100)
    # Stable URL pattern - no cache-busting, browser will cache effectively
    # IMPORTANT: Parqet requires full ticker with suffix for Canadian tickers (e.g., DRX.TO)
    parqet_url = f"https://assets.parqet.com/logos/symbol/{parqet_ticker}?format=png&size=64"
    
    # FALLBACK: Yahoo Finance logo (via yimg.com) - also free
    # Format: https://logo.clearbit.com/{domain} or yahoo's internal logo service
    # Yahoo uses: https://s.yimg.com/cv/apiv2/default/images/logos/{ticker}.png
    # Note: Yahoo typically uses base ticker (without suffix) for both US and Canadian
    yahoo_url = f"https://s.yimg.com/cv/apiv2/default/images/logos/{base_ticker}.png"
    
    # Return Parqet as primary (browser will handle 404s gracefully)
    # Client-side fallback in TypeScript handles Yahoo Finance if Parqet fails
    return parqet_url


def get_ticker_logo_urls(tickers: list[str]) -> dict[str, Optional[str]]:
    """Get logo URLs for multiple tickers at once.
    
    Args:
        tickers: List of ticker symbols
        
    Returns:
        Dictionary mapping ticker -> logo URL
    """
    return {ticker: get_ticker_logo_url(ticker) for ticker in tickers}
