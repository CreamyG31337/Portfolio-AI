
import requests
import pandas as pd
from io import StringIO
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_url(name, url, provider):
    print(f"\nTesting {name} ({provider})...")
    print(f"URL: {url}")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            print(f"✅ Status 200 OK. Content-Type: {response.headers.get('Content-Type')}")
            # print(f"First 500 chars:\n{response.text[:500]}")
            
            # Try to parse CSV
            try:
                # Some might need skiprows
                if provider == 'VanEck':
                    # VanEck usually has headers
                    df = pd.read_csv(StringIO(response.text))
                elif provider == 'Global X':
                    # Global X usually has headers then data, line 3
                     df = pd.read_csv(StringIO(response.text), skiprows=2)
                elif provider == 'SPDR':
                     df = pd.read_csv(StringIO(response.text), skiprows=4)
                elif provider == 'Bitwise':
                     df = pd.read_csv(StringIO(response.text))
                else:
                    df = pd.read_csv(StringIO(response.text))
                
                print(f"✅ Parsed DataFrame with {len(df)} rows.")
                print(f"Columns: {df.columns.tolist()}")
                print(df.head(3))
            except Exception as e:
                print(f"❌ Failed to parse CSV: {e}")
                print(f"Content start: {response.text[:200]}")
        else:
            print(f"❌ Failed with status {response.status_code}")
    except Exception as e:
        print(f"❌ Exception: {e}")

# URLs to test
urls = [
    # VanEck SMH 
    ("SMH", "https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/holdings/smh-holdings.csv", "VanEck"),
    
    # Global X 
    ("BOTZ", "https://www.globalxetfs.com/funds/botz/?download_full_holdings=true", "Global X"),
    ("LIT", "https://www.globalxetfs.com/funds/lit/?download_full_holdings=true", "Global X"),
    
    # SPDR XBI (Excel)
    ("XBI", "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xbi.xlsx", "SPDR"),
    
    # Bitwise BITQ
    ("BITQ", "https://bitwiseinvestments.com/csv/BITQ.csv", "Bitwise"),
    ("BITQ_ALT", "https://bitwiseinvestments.com/funds/BITQ/holdings.csv", "Bitwise"),
]

for name, url, provider in urls:
    test_url(name, url, provider)
