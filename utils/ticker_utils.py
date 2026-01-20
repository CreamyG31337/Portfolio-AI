"""Ticker symbol utilities.

This module provides functions for normalizing and validating ticker symbols,
including adding appropriate suffixes for different markets. Uses yfinance
to intelligently detect Canadian vs US stocks.
"""

import re
import logging
from typing import Optional, Union, List, Dict
from decimal import Decimal

logger = logging.getLogger(__name__)

# Cache for ticker corrections to avoid repeated API calls
TICKER_CORRECTION_CACHE = {}


def detect_currency_context(ticker: str, buy_price: float = None) -> str:
    """
    Detect if a ticker is likely Canadian based on context clues.
    Returns 'CAD', 'USD', or 'UNKNOWN'
    """
    # If we have a buy price, use it as a clue
    if buy_price is not None:
        # Canadian small-caps typically trade in the $1-50 range
        # US small-caps can be much higher
        if 1 <= buy_price <= 50:
            return 'CAD'  # More likely Canadian
        elif buy_price > 50:
            return 'USD'  # More likely US
    
    # Check if ticker has Canadian characteristics
    canadian_patterns = [
        # Common Canadian company name patterns
        'CAN', 'CANADA', 'NORTH', 'NORTHERN', 'WESTERN', 'EASTERN',
        'QUEBEC', 'ONTARIO', 'ALBERTA', 'BRITISH', 'COLUMBIA'
    ]
    
    ticker_upper = ticker.upper()
    for pattern in canadian_patterns:
        if pattern in ticker_upper:
            return 'CAD'
    
    return 'UNKNOWN'


def detect_and_correct_ticker(ticker: str, buy_price: float = None) -> str:
    """
    Detect if a ticker is Canadian and automatically add the appropriate suffix.
    Tests all variants (.TO, .V, and no suffix) and asks user if multiple matches found.
    
    Returns the corrected ticker symbol with appropriate suffix.
    """
    ticker = ticker.upper().strip()
    
    # Check cache first
    if ticker in TICKER_CORRECTION_CACHE:
        return TICKER_CORRECTION_CACHE[ticker]
    
    # If already has a suffix, return as-is
    if any(ticker.endswith(suffix) for suffix in ['.TO', '.V', '.CN', '.NE']):
        TICKER_CORRECTION_CACHE[ticker] = ticker
        return ticker
    
    try:
        import yfinance as yf
        import logging
        
        # Suppress all yfinance logging and warnings
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        
        # Test all variants
        variants_to_test = [
            ticker,           # No suffix (US)
            f"{ticker}.TO",   # TSX
            f"{ticker}.V",    # TSX Venture
        ]
        
        valid_matches = []
        
        for variant in variants_to_test:
            try:
                stock = yf.Ticker(variant)
                info = stock.info
                
                # Check if we get valid info (not just empty dict)
                if info and info.get('symbol') and info.get('symbol') != 'N/A':
                    exchange = info.get('exchange', '')
                    name = info.get('longName', info.get('shortName', ''))
                    
                    # Only count as valid if we have a real exchange AND a real company name
                    if (exchange and exchange != 'N/A' and 
                        name and name != 'N/A' and name != 'Unknown' and 
                        len(name) > 3):  # Real company names are longer than 3 chars
                        valid_matches.append({
                            'ticker': variant,
                            'exchange': exchange,
                            'name': name
                        })
            except Exception as e:
                # Silently skip invalid tickers - don't show 404 errors to user
                continue
        
        # If no valid matches found, return original
        if not valid_matches:
            TICKER_CORRECTION_CACHE[ticker] = ticker
            return ticker
        
        # If only one match, use it
        if len(valid_matches) == 1:
            result = valid_matches[0]['ticker']
            TICKER_CORRECTION_CACHE[ticker] = result
            logger.info(f"Auto-corrected ticker {ticker} to {result}")
            return result
        
        # Multiple matches found - ask user to choose
        print(f"\n🔍 Multiple valid tickers found for '{ticker}':")
        for i, match in enumerate(valid_matches, 1):
            print(f"  {i}. {match['ticker']} - {match['name']} ({match['exchange']})")
        
        while True:
            try:
                choice = input(f"Select ticker (1-{len(valid_matches)}) or press Enter for {ticker}: ").strip()
                if not choice:
                    # Default to original if no choice made
                    result = ticker
                    break
                
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(valid_matches):
                    result = valid_matches[choice_idx]['ticker']
                    break
                else:
                    print(f"Please enter a number between 1 and {len(valid_matches)}")
            except ValueError:
                print("Please enter a valid number")
        
        TICKER_CORRECTION_CACHE[ticker] = result
        return result
        
    except Exception as e:
        logger.warning(f"Could not detect ticker type for {ticker}: {e}")
        # Default to original ticker
        TICKER_CORRECTION_CACHE[ticker] = ticker
        return ticker


def lookup_ticker_suffix_candidates(ticker: str, currency: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Look up ticker suffix candidates without user prompts (UI-friendly version).
    
    Tests all variants (.TO, .V, .CN, .NE, and base ticker) and returns valid matches.
    When currency is CAD, filters for Canadian exchanges.
    
    Args:
        ticker: Base ticker symbol (without suffix)
        currency: Optional currency hint ('CAD' or 'USD') to filter results
        
    Returns:
        List of dictionaries with keys: 'ticker', 'exchange', 'name'
        Each dict represents a valid ticker variant found via yfinance
    """
    ticker = ticker.upper().strip()
    
    # If already has a suffix, return empty list (nothing to look up)
    if any(ticker.endswith(suffix) for suffix in ['.TO', '.V', '.CN', '.NE']):
        return []
    
    # Cache key for lookup results
    cache_key = f"lookup_{ticker}_{currency or 'any'}"
    if cache_key in TICKER_CORRECTION_CACHE:
        cached_result = TICKER_CORRECTION_CACHE[cache_key]
        if isinstance(cached_result, list):
            return cached_result
    
    valid_matches = []
    
    try:
        import yfinance as yf
        
        # Suppress all yfinance logging and warnings
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        
        # Test all variants - prioritize Canadian suffixes if currency is CAD
        if currency and currency.upper() == 'CAD':
            variants_to_test = [
                f"{ticker}.TO",   # TSX
                f"{ticker}.V",    # TSX Venture
                f"{ticker}.CN",  # CSE
                f"{ticker}.NE",  # NEO
                ticker,          # Base (US) - check last
            ]
        else:
            variants_to_test = [
                ticker,          # Base (US)
                f"{ticker}.TO",  # TSX
                f"{ticker}.V",   # TSX Venture
                f"{ticker}.CN",  # CSE
                f"{ticker}.NE",  # NEO
            ]
        
        for variant in variants_to_test:
            try:
                stock = yf.Ticker(variant)
                info = stock.info
                
                # Check if we get valid info (not just empty dict)
                if info and info.get('symbol') and info.get('symbol') != 'N/A':
                    exchange = info.get('exchange', '')
                    name = info.get('longName', info.get('shortName', ''))
                    
                    # Only count as valid if we have a real exchange AND a real company name
                    if (exchange and exchange != 'N/A' and 
                        name and name != 'N/A' and name != 'Unknown' and 
                        len(name) > 3):  # Real company names are longer than 3 chars
                        
                        # If currency is CAD, filter for Canadian exchanges
                        if currency and currency.upper() == 'CAD':
                            canadian_exchanges = ['TOR', 'TSX', 'TSXV', 'CSE', 'NEO', 'TORONTO']
                            exchange_upper = exchange.upper()
                            is_canadian = (
                                variant.endswith(('.TO', '.V', '.CN', '.NE')) or
                                any(can_ex in exchange_upper for can_ex in canadian_exchanges) or
                                info.get('country', '').upper() == 'CANADA'
                            )
                            if not is_canadian:
                                continue
                        
                        valid_matches.append({
                            'ticker': variant,
                            'exchange': exchange,
                            'name': name
                        })
            except Exception:
                # Silently skip invalid tickers - don't show 404 errors
                continue
        
        # Cache the results
        TICKER_CORRECTION_CACHE[cache_key] = valid_matches
        return valid_matches
        
    except Exception as e:
        logger.warning(f"Could not lookup ticker suffixes for {ticker}: {e}")
        # Return empty list on error
        TICKER_CORRECTION_CACHE[cache_key] = []
        return []


def normalize_ticker_symbol(ticker: str, currency: str = "CAD", buy_price: Union[float, Decimal, None] = None) -> str:
    """Normalize ticker symbol using intelligent detection.
    
    Args:
        ticker: Raw ticker symbol from user input
        currency: Currency code (CAD or USD) - used as hint
        buy_price: Optional buy price for context clues
        
    Returns:
        Normalized ticker symbol with appropriate suffix
        
    Examples:
        normalize_ticker_symbol("VEE", "CAD", 44.59) -> "VEE.TO"
        normalize_ticker_symbol("AAPL", "USD", 150.0) -> "AAPL"
        normalize_ticker_symbol("VEE.TO", "CAD") -> "VEE.TO"  # Already normalized
    """
    if not ticker:
        return ticker
    
    # Use the intelligent detection function
    return detect_and_correct_ticker(ticker, buy_price)


def is_canadian_ticker(ticker: str) -> bool:
    """Check if ticker is Canadian based on suffix.
    
    Args:
        ticker: Ticker symbol to check
        
    Returns:
        True if Canadian ticker, False otherwise
    """
    if not ticker:
        return False
    
    ticker = ticker.upper().strip()
    return (ticker.endswith('.TO') or 
            ticker.endswith('.V') or 
            ticker.endswith('.CN') or
            ticker.endswith('.TSX'))


def is_us_ticker(ticker: str) -> bool:
    """Check if ticker is US based on format.
    
    Args:
        ticker: Ticker symbol to check
        
    Returns:
        True if US ticker, False otherwise
    """
    if not ticker:
        return False
    
    ticker = ticker.upper().strip()
    return (not is_canadian_ticker(ticker) and 
            not ticker.startswith('^') and
            not ticker.endswith('.L'))  # London Stock Exchange


def get_ticker_currency(ticker: str) -> str:
    """Get currency for ticker based on suffix.
    
    Args:
        ticker: Ticker symbol
        
    Returns:
        Currency code ('CAD' or 'USD')
    """
    if is_canadian_ticker(ticker):
        return 'CAD'
    elif is_us_ticker(ticker):
        return 'USD'
    else:
        # Default to USD for unknown formats
        return 'USD'


def validate_ticker_format(ticker: str) -> bool:
    """Validate ticker symbol format.
    
    Args:
        ticker: Ticker symbol to validate
        
    Returns:
        True if valid format, False otherwise
    """
    if not ticker or not isinstance(ticker, str):
        return False
    
    ticker = ticker.strip().upper()
    if not ticker:
        return False
    
    # Valid tickers: start with a letter; allow letters/digits/dot/dash afterwards
    pattern = r"^[A-Za-z][A-Za-z0-9\.-]*$"
    return bool(re.fullmatch(pattern, ticker))


def get_company_name(ticker: str, currency: str = None) -> str:
    """Get company name for ticker symbol with Canadian suffix support and caching.

    Order of resolution:
    1) Read from persisted name cache (PriceCache)
    2) Try different ticker variants (.TO, .V, no suffix) with yfinance based on currency
    3) Persist successful lookups to cache

    Args:
        ticker: Ticker symbol
        currency: Optional currency hint ('CAD' or 'USD') to determine which exchange to prioritize

    Returns:
        Company name or 'Unknown' if not found
    """
    if not ticker:
        return 'Unknown'

    try:
        from market_data.price_cache import PriceCache
        pc = PriceCache()
        key = ticker.upper().strip()
        
        # Create a cache key that includes currency to avoid mixing CAD/USD tickers
        # For example: "WEB:CAD" vs "WEB:USD"
        cache_key = f"{key}:{currency.upper()}" if currency else key
        
        cached = pc.get_company_name(cache_key)
        if cached:
            logger.debug(f"Found cached company name for {cache_key}: {cached}")
            return cached
    except Exception:
        pc = None
        key = ticker.upper().strip()
        cache_key = key

    # Try different ticker variants for better coverage
    name = 'Unknown'
    successful_ticker = key

    # Use currency-based logic to determine which variants to try first
    variants_to_try = []
    
    # Determine if this is a Canadian ticker
    is_likely_canadian = key.endswith(('.TO', '.V', '.CN'))  # Already has Canadian suffix
    
    # If currency is provided explicitly, use it (this is the primary source of truth)
    if currency:
        if currency.upper() == 'CAD':
            is_likely_canadian = True
        elif currency.upper() == 'USD':
            is_likely_canadian = False
    # Otherwise, try to infer from portfolio data as fallback
    elif not is_likely_canadian:
        try:
            import pandas as pd
            import glob
            
            # Load currency from portfolio files as fallback
            portfolio_files = glob.glob('trading_data/funds/*/llm_portfolio_update.csv')
            currency_cache = {}
            
            for file_path in portfolio_files:
                try:
                    df = pd.read_csv(file_path)
                    if 'Ticker' in df.columns and 'Currency' in df.columns:
                        latest_entries = df.groupby('Ticker').last()
                        for ticker, row in latest_entries.iterrows():
                            currency_cache[ticker] = row['Currency']
                except Exception:
                    continue
            
            inferred_currency = currency_cache.get(key)
            if inferred_currency == 'CAD':
                is_likely_canadian = True
            elif inferred_currency == 'USD':
                is_likely_canadian = False
        except Exception:
            pass

    if any(key.endswith(suffix) for suffix in ['.TO', '.V', '.CN', '.NE']):
        # Has suffix - try with suffix first, then without
        variants_to_try = [key, key.rsplit('.', 1)[0]]
    elif is_likely_canadian:
        # Likely Canadian - try Canadian suffixes first
        variants_to_try = [f"{key}.TO", f"{key}.V", key]
    else:
        # Unknown - try all variants and prefer ones with explicit country info
        variants_to_try = [key, f"{key}.TO", f"{key}.V"]

    try:
        import yfinance as yf
        import logging

        # Suppress all yfinance logging and warnings
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)

        # Store all valid candidates to choose the best one
        candidates = []
        
        for variant in variants_to_try:
            try:
                stock = yf.Ticker(variant)
                info = stock.info

                # Check for valid company name
                if info and (info.get('longName') or info.get('shortName')):
                    candidate_name = info.get('longName') or info.get('shortName')
                    country = info.get('country', '')

                    # Make sure it's not just "N/A" or generic
                    if (candidate_name and
                        candidate_name != 'N/A' and
                        candidate_name != 'Unknown' and
                        len(candidate_name.strip()) > 3):  # Real names are longer than 3 chars

                        candidates.append({
                            'name': candidate_name.strip(),
                            'variant': variant,
                            'country': country
                        })
                        logger.debug(f"Found candidate for {key}: {candidate_name.strip()} (using {variant}, country: {country})")

            except Exception as e:
                # Continue to next variant if this one fails
                logger.debug(f"Failed to get info for {variant}: {e}")
                continue
        
        # Choose the best candidate based on currency preference
        if candidates:
            best = None
            
            # If we know we want a Canadian ticker, prioritize Canadian variants
            if is_likely_canadian:
                for candidate in candidates:
                    if candidate['variant'].endswith(('.TO', '.V', '.CN')) or candidate['country'] == 'Canada':
                        best = candidate
                        logger.debug(f"Selected Canadian variant: {best['variant']}")
                        break
            # If we know we want a US ticker, prioritize US variants (avoid Canadian)
            elif is_likely_canadian is False:  # Explicitly False (not just None/unknown)
                for candidate in candidates:
                    if not candidate['variant'].endswith(('.TO', '.V', '.CN')) and candidate['country'] != 'Canada':
                        best = candidate
                        logger.debug(f"Selected US variant: {best['variant']}")
                        break
            
            # If no preference or no match found, prefer variants with explicit country info
            if not best:
                for candidate in candidates:
                    if candidate['country'] and candidate['country'] != 'N/A':
                        best = candidate
                        logger.debug(f"Selected variant with country info: {best['variant']} ({best['country']})")
                        break
            
            # Fall back to first valid candidate
            if not best:
                best = candidates[0]
                logger.debug(f"Selected first valid candidate: {best['variant']}")
            
            name = best['name']
            successful_ticker = best['variant']

    except Exception as e:
        logger.debug(f"Error during company name lookup for {key}: {e}")

    # Persist to cache if available and we found a name (use currency-aware cache key)
    try:
        if name != 'Unknown' and pc is not None:
            pc.cache_company_name(cache_key, name)
            pc.save_persistent_cache()
            logger.debug(f"Cached company name for {cache_key}: {name}")
    except Exception as e:
        logger.debug(f"Could not cache company name for {cache_key}: {e}")

    return name
