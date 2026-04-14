"""
Logo Utilities
==============
Functions to get company logo URLs for ticker symbols.

Supports per-security overrides via the `use_alt_logo` flag on the securities table.
When the flag is set, uses Clearbit's domain-based logo API instead of the default
Parqet ticker-based API.  This solves cases where Parqet returns the wrong logo
(e.g., JPM showing Fastenal's logo).
"""

from typing import Optional
from urllib.parse import urlparse
import logging
import re

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


def _is_class_share_without_exchange(ticker: str) -> bool:
    """Return True for symbols like BRK.B or TECK.B (without .TO/.V/etc)."""
    ticker_upper = ticker.upper().strip()
    if ticker_upper.endswith((".TO", ".V", ".CN", ".TSX", ".TSXV", ".NE", ".NEO")):
        return False
    return bool(re.match(r"^[A-Z0-9]+\.[A-Z]$", ticker_upper))


def _class_share_with_tsx_suffix(ticker: str) -> Optional[str]:
    """Convert class-share ticker to Yahoo/Parqet TSX style when applicable.

    Example: TECK.B -> TECK-B.TO
    """
    ticker_upper = ticker.upper().strip()
    match = re.match(r"^([A-Z0-9]+)\.([A-Z])$", ticker_upper)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}.TO"


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
    # Alternative logo source (Clearbit domain-based)
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
    # For class-share symbols without explicit exchange suffix (e.g., TECK.B),
    # Parqet coverage can be inconsistent. If we have website data, prefer
    # domain-based unavatar to avoid logo misses while keeping use_alt optional.
    if website and _is_class_share_without_exchange(ticker):
        domain = _extract_domain(website)
        if domain:
            return f"https://unavatar.io/{domain}?fallback=false"

    # For class-share symbols without exchange suffix, prefer TSX style variant
    # that has better logo coverage in Parqet (e.g., TECK.B -> TECK-B.TO).
    tsx_class_share = _class_share_with_tsx_suffix(ticker)
    if tsx_class_share:
        ticker = tsx_class_share

    # Clean ticker: remove spaces, convert class shares dots to hyphens
    try:
        from utils.ticker_utils import normalize_ticker_for_yahoo
        ticker = normalize_ticker_for_yahoo(ticker)
    except ImportError:
        pass

    clean_ticker = ticker.upper().strip().replace(" ", "")

    # Parqet requires full ticker with suffix for Canadian exchanges (DRX.TO)
    # but also works with base tickers for US equities (AAPL)
    parqet_url = (
        f"https://assets.parqet.com/logos/symbol/{clean_ticker}?format=png&size=64"
    )

    return parqet_url


def get_ticker_logo_urls(tickers: list[str]) -> dict[str, Optional[str]]:
    """Get logo URLs for multiple tickers at once (default Parqet source).

    Args:
        tickers: List of ticker symbols

    Returns:
        Dictionary mapping ticker -> logo URL
    """
    return {ticker: get_ticker_logo_url(ticker) for ticker in tickers}
