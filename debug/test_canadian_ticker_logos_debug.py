"""
Comprehensive debug script for testing Canadian ticker logo fetching.

Tests multiple APIs and ticker formats to find working logos for Canadian tickers like DRX.TO.
"""
import sys
from pathlib import Path
import requests
from typing import Optional, Dict, List, Tuple
from urllib.parse import quote

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from web_dashboard.utils.logo_utils import get_ticker_logo_url


def check_url_exists(url: str, timeout: int = 5) -> Tuple[bool, int, Optional[str]]:
    """Check if a URL returns a valid image (not 404).
    
    Returns:
        (exists, status_code, content_type)
    """
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        status = response.status_code
        content_type = response.headers.get('Content-Type', '')
        
        # 200-299 means success, 301-308 are redirects (we follow them)
        exists = 200 <= status < 300
        return exists, status, content_type
    except requests.exceptions.RequestException as e:
        return False, 0, str(e)


def test_parqet_api(ticker: str, base_ticker: str) -> Dict[str, any]:
    """Test Parqet API with different formats."""
    results = {}
    
    # Format 1: Base ticker only (current implementation)
    url1 = f"https://assets.parqet.com/logos/symbol/{base_ticker}?format=png&size=64"
    exists1, status1, ct1 = check_url_exists(url1)
    results['parqet_base'] = {
        'url': url1,
        'exists': exists1,
        'status': status1,
        'content_type': ct1
    }
    
    # Format 2: Full ticker with suffix
    url2 = f"https://assets.parqet.com/logos/symbol/{ticker}?format=png&size=64"
    exists2, status2, ct2 = check_url_exists(url2)
    results['parqet_full'] = {
        'url': url2,
        'exists': exists2,
        'status': status2,
        'content_type': ct2
    }
    
    # Format 3: URL-encoded ticker
    url3 = f"https://assets.parqet.com/logos/symbol/{quote(ticker)}?format=png&size=64"
    exists3, status3, ct3 = check_url_exists(url3)
    results['parqet_encoded'] = {
        'url': url3,
        'exists': exists3,
        'status': status3,
        'content_type': ct3
    }
    
    return results


def test_yahoo_finance(ticker: str, base_ticker: str) -> Dict[str, any]:
    """Test Yahoo Finance logo URLs."""
    results = {}
    
    # Format 1: Base ticker (current fallback)
    url1 = f"https://s.yimg.com/cv/apiv2/default/images/logos/{base_ticker}.png"
    exists1, status1, ct1 = check_url_exists(url1)
    results['yahoo_base'] = {
        'url': url1,
        'exists': exists1,
        'status': status1,
        'content_type': ct1
    }
    
    # Format 2: Full ticker
    url2 = f"https://s.yimg.com/cv/apiv2/default/images/logos/{ticker}.png"
    exists2, status2, ct2 = check_url_exists(url2)
    results['yahoo_full'] = {
        'url': url2,
        'exists': exists2,
        'status': status2,
        'content_type': ct2
    }
    
    # Format 3: Alternative Yahoo format
    url3 = f"https://logo.clearbit.com/{base_ticker.lower()}.com"
    exists3, status3, ct3 = check_url_exists(url3)
    results['yahoo_clearbit'] = {
        'url': url3,
        'exists': exists3,
        'status': status3,
        'content_type': ct3
    }
    
    return results


def test_companieslogo_api(ticker: str, base_ticker: str) -> Dict[str, any]:
    """Test CompaniesLogo.com API (requires API key, but test URL format)."""
    results = {}
    
    # Format: https://companieslogo.com/img/original/{ticker}.png
    # Note: This requires API key, but we can test the URL format
    url1 = f"https://companieslogo.com/img/original/{base_ticker}.png"
    exists1, status1, ct1 = check_url_exists(url1)
    results['companieslogo_base'] = {
        'url': url1,
        'exists': exists1,
        'status': status1,
        'content_type': ct1,
        'note': 'May require API key'
    }
    
    url2 = f"https://companieslogo.com/img/original/{ticker}.png"
    exists2, status2, ct2 = check_url_exists(url2)
    results['companieslogo_full'] = {
        'url': url2,
        'exists': exists2,
        'status': status2,
        'content_type': ct2,
        'note': 'May require API key'
    }
    
    return results


def test_yfinance_logo(ticker: str) -> Dict[str, any]:
    """Test yfinance library for logo URLs."""
    results = {}
    
    try:
        import yfinance as yf
        import logging
        
        # Suppress yfinance warnings
        logging.getLogger("yfinance").setLevel(logging.ERROR)
        
        ticker_obj = yf.Ticker(ticker)
        info = ticker_obj.info
        
        # yfinance sometimes has logo URLs in info
        logo_url = info.get('logo_url') or info.get('logo') or info.get('image')
        
        if logo_url:
            exists, status, ct = check_url_exists(logo_url)
            results['yfinance'] = {
                'url': logo_url,
                'exists': exists,
                'status': status,
                'content_type': ct,
                'source': 'yfinance.info'
            }
        else:
            results['yfinance'] = {
                'url': None,
                'exists': False,
                'status': None,
                'content_type': None,
                'note': 'No logo_url in yfinance info'
            }
            
            # Also check if company name is available (for debugging)
            company_name = info.get('longName') or info.get('shortName') or info.get('name')
            results['yfinance']['company_name'] = company_name
            
    except Exception as e:
        results['yfinance'] = {
            'url': None,
            'exists': False,
            'status': None,
            'content_type': None,
            'error': str(e)
        }
    
    return results


def test_alternative_apis(ticker: str, base_ticker: str) -> Dict[str, any]:
    """Test various alternative logo APIs."""
    results = {}
    
    # Test 1: Finnhub (requires API key, but test format)
    # Format: https://static.finnhub.io/logo/{ticker}.png
    url1 = f"https://static.finnhub.io/logo/{base_ticker}.png"
    exists1, status1, ct1 = check_url_exists(url1)
    results['finnhub'] = {
        'url': url1,
        'exists': exists1,
        'status': status1,
        'content_type': ct1,
        'note': 'May require API key'
    }
    
    # Test 2: Polygon.io (requires API key)
    # Format: https://api.polygon.io/v2/reference/financials?ticker={ticker}
    # (Not a direct logo URL, but they have company data)
    results['polygon'] = {
        'url': None,
        'exists': False,
        'note': 'Polygon.io requires API key and doesn\'t have direct logo endpoint'
    }
    
    # Test 3: Alpha Vantage (requires API key)
    results['alphavantage'] = {
        'url': None,
        'exists': False,
        'note': 'Alpha Vantage doesn\'t have logo endpoint'
    }
    
    # Test 4: IEX Cloud (requires API key)
    # Format: https://storage.googleapis.com/iex/api/logos/{ticker}.png
    url4 = f"https://storage.googleapis.com/iex/api/logos/{base_ticker}.png"
    exists4, status4, ct4 = check_url_exists(url4)
    results['iex'] = {
        'url': url4,
        'exists': exists4,
        'status': status4,
        'content_type': ct4,
        'note': 'IEX Cloud - may require API key'
    }
    
    return results


def test_ticker_variants(ticker: str) -> Dict[str, str]:
    """Generate all possible ticker variants to test."""
    variants = {}
    
    # Original
    variants['original'] = ticker
    
    # Remove suffix
    if '.' in ticker:
        base = ticker.rsplit('.', 1)[0]
        variants['base'] = base
    
    # Different Canadian exchange suffixes
    if '.' in ticker:
        base = ticker.rsplit('.', 1)[0]
        variants['to'] = f"{base}.TO"
        variants['v'] = f"{base}.V"
        variants['cn'] = f"{base}.CN"
        variants['ne'] = f"{base}.NE"
    else:
        # Add suffixes if no suffix exists
        variants['to'] = f"{ticker}.TO"
        variants['v'] = f"{ticker}.V"
        variants['cn'] = f"{ticker}.CN"
        variants['ne'] = f"{ticker}.NE"
    
    return variants


def print_results(ticker: str, results: Dict[str, Dict[str, any]]):
    """Print formatted test results."""
    print(f"\n{'='*80}")
    print(f"TESTING TICKER: {ticker}")
    print(f"{'='*80}\n")
    
    # Group results by API
    for api_name, api_results in results.items():
        print(f"\n{api_name.upper().replace('_', ' ')}:")
        print("-" * 80)
        
        if isinstance(api_results, dict):
            for format_name, format_result in api_results.items():
                if isinstance(format_result, dict):
                    url = format_result.get('url', 'N/A')
                    exists = format_result.get('exists', False)
                    status = format_result.get('status', 'N/A')
                    if status is None:
                        status = 'N/A'
                    ct = format_result.get('content_type', 'N/A')
                    note = format_result.get('note', '')
                    error = format_result.get('error', '')
                    
                    status_icon = "[OK]" if exists else "[FAIL]"
                    status_str = str(status) if status != 'N/A' else 'N/A'
                    print(f"  {status_icon} {format_name:20} | Status: {status_str:>5} | {url}")
                    if ct and ct != 'N/A':
                        print(f"    Content-Type: {ct}")
                    if note:
                        print(f"    Note: {note}")
                    if error:
                        print(f"    Error: {error}")
                else:
                    print(f"  {format_name}: {format_result}")
        else:
            print(f"  {api_results}")


def main():
    """Main test function."""
    # Test tickers - focus on Canadian ones
    test_tickers = [
        'DRX.TO',      # User's example
        'AAPL',        # US ticker (control)
        'SHOP.TO',     # Large Canadian company
        'XMA.TO',      # Medium Canadian company
        'NXT.V',       # TSXV ticker
        'AC.TO',       # Air Canada
        'CNR.TO',      # Canadian National Railway
    ]
    
    print("="*80)
    print("CANADIAN TICKER LOGO DEBUG SCRIPT")
    print("="*80)
    print("\nThis script tests multiple APIs and formats to find working logos.")
    print("It will check if URLs actually return valid images (not just generate URLs).\n")
    
    for ticker in test_tickers:
        ticker_upper = ticker.upper().strip()
        
        # Get base ticker (current implementation logic)
        if '.' in ticker_upper:
            parts = ticker_upper.rsplit('.', 1)
            if len(parts) == 2 and parts[1] in ('TO', 'V', 'CN', 'TSX', 'TSXV', 'NE', 'NEO'):
                base_ticker = parts[0]
            else:
                base_ticker = ticker_upper
        else:
            base_ticker = ticker_upper
        
        # Test all APIs
        results = {}
        
        print(f"\n{'='*80}")
        print(f"Testing: {ticker_upper} (base: {base_ticker})")
        print(f"{'='*80}")
        
        # Test current implementation
        current_url = get_ticker_logo_url(ticker_upper)
        if current_url:
            exists, status, ct = check_url_exists(current_url)
        else:
            exists, status, ct = False, None, None
        results['current_implementation'] = {
            'url': current_url or 'None',
            'exists': exists,
            'status': status or 'N/A',
            'content_type': ct or 'N/A'
        }
        
        # Test Parqet with different formats
        results['parqet'] = test_parqet_api(ticker_upper, base_ticker)
        
        # Test Yahoo Finance
        results['yahoo'] = test_yahoo_finance(ticker_upper, base_ticker)
        
        # Test yfinance library
        results['yfinance'] = test_yfinance_logo(ticker_upper)
        
        # Test alternative APIs
        results['alternatives'] = test_alternative_apis(ticker_upper, base_ticker)
        
        # Test CompaniesLogo
        results['companieslogo'] = test_companieslogo_api(ticker_upper, base_ticker)
        
        # Print results
        print_results(ticker_upper, results)
        
        # Summary for this ticker
        print(f"\n{'-'*80}")
        print("SUMMARY:")
        working_urls = []
        for api_name, api_results in results.items():
            if isinstance(api_results, dict):
                for format_name, format_result in api_results.items():
                    if isinstance(format_result, dict) and format_result.get('exists'):
                        working_urls.append((f"{api_name}.{format_name}", format_result.get('url')))
        
        if working_urls:
            print(f"[OK] Found {len(working_urls)} working logo URL(s):")
            for name, url in working_urls:
                print(f"   - {name}: {url}")
        else:
            print("[FAIL] No working logo URLs found for this ticker")
        print(f"{'-'*80}\n")
    
    print("\n" + "="*80)
    print("TESTING COMPLETE")
    print("="*80)
    print("\nRecommendations:")
    print("1. If Parqet works with base ticker, current implementation is correct")
    print("2. If Parqet works with full ticker, we should update logo_utils.py")
    print("3. If yfinance has logo URLs, we could use those as a fallback")
    print("4. If no free APIs work, consider paid services like CompaniesLogo.com or Benzinga")
    print("="*80)


if __name__ == "__main__":
    main()
