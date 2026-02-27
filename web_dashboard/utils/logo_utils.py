"""
Logo Utilities
==============
Functions to get company logo URLs for ticker symbols.

Supports per-security overrides via the `use_alt_logo` flag on the securities table.
When the flag is set, uses Clearbit's domain-based logo API instead of the default
Parqet ticker-based API.  This solves cases where Parqet returns the wrong logo
(e.g., JPM showing Fastenal's logo).
"""

import os
from typing import Optional, Dict
from urllib.parse import urlparse
import logging

logger = logging.getLogger(__name__)


def _extract_domain(website_url: str) -> Optional[str]:
    """Extract the bare domain from a website URL.

    Handles URLs with or without scheme, e.g.:
        'https://www.jpmorganchase.com'  -> 'jpmorganchase.com'
        'www.jpmorganchase.com'          -> 'jpmorganchase.com'
        'jpmorganchase.com'              -> 'jpmorganchase.com'
    """
    if not website_url:
        return None

    url = website_url.strip()
    # Ensure scheme so urlparse works correctly
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)
        domain = parsed.hostname
        if domain:
            # Strip leading "www."
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
    except Exception:
        pass
    return None


def get_ticker_logo_url(
    ticker: str,
    use_alt: bool = False,
    website: Optional[str] = None,
) -> Optional[str]:
    """Get company logo URL for a ticker symbol.

    Default behaviour uses the Parqet Logos API (free, no auth).
    When *use_alt* is ``True``, the function returns a Clearbit
    domain-based logo URL instead (requires a valid *website*).

    Args:
        ticker:   Stock ticker symbol (e.g., "AAPL", "TSLA").
        use_alt:  If True, prefer Clearbit logo via *website* domain.
        website:  Company website URL stored in the securities table.
                  Only used when *use_alt* is True.

    Returns:
        Logo URL string, or None if not available.
    """
    if not ticker or ticker == "N/A":
        return None

    # ------------------------------------------------------------------
    # Alternative logo source (Unavatar domain-based)
    # ------------------------------------------------------------------
    if use_alt and website:
        domain = _extract_domain(website)
        if domain:
            # Unavatar - free, open-source logo aggregator (pulls from multiple sources)
            # Supports size param; returns best available logo for the domain
            # https://unavatar.io
            unavatar_url = f"https://unavatar.io/{domain}?fallback=false"
            logger.debug(
                "Using unavatar alt logo for %s (domain=%s)", ticker, domain
            )
            return unavatar_url
        else:
            logger.warning(
                "use_alt_logo is set for %s but website '%s' yielded no domain; "
                "falling back to Parqet",
                ticker,
                website,
            )

    # ------------------------------------------------------------------
    # Default logo source (Parqet ticker-based)
    # ------------------------------------------------------------------
    # Clean ticker (remove spaces, but keep exchange suffixes for Parqet)
    clean_ticker = ticker.upper().strip().replace(" ", "")

    # Parqet requires full ticker with suffix for Canadian exchanges (DRX.TO)
    # but also works with base tickers for US equities (AAPL)
    parqet_url = (
        f"https://assets.parqet.com/logos/symbol/{clean_ticker}?format=png&size=64"
    )

    return parqet_url


def get_ticker_logo_urls(tickers: list[str], websites: Dict[str, str] = None) -> Dict[str, Optional[str]]:
    """Get logo URLs for multiple tickers at once.

    If websites dictionary is provided, uses Unavatar domain-based lookup (better quality).
    Otherwise falls back to Parqet ticker-based lookup.

    Args:
        tickers: List of ticker symbols
        websites: Optional dict mapping ticker -> website URL

    Returns:
        Dictionary mapping ticker -> logo URL
    """
    results = {}
    for ticker in tickers:
        website = websites.get(ticker) if websites else None
        if website:
            # If we have a website, try using it for better quality
            results[ticker] = get_ticker_logo_url(ticker, use_alt=True, website=website)
        else:
            # Fallback to standard ticker-based lookup
            results[ticker] = get_ticker_logo_url(ticker)
    return results
