
import requests
import pandas as pd
from io import StringIO, BytesIO
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_url(name, url, provider, file_type='csv'):
    print(f"\nTesting {name} ({provider})...")
    print(f"URL: {url}")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            print(f"✅ Status 200 OK. Content-Type: {response.headers.get('Content-Type')}")
            
            try:
                if file_type == 'excel':
                    # Needed for SMH and XBI
                    df = pd.read_excel(BytesIO(response.content))
                    print(f"✅ Parsed Excel DataFrame with {len(df)} rows.")
                    print(f"Columns: {df.columns.tolist()}")
                    print(df.head(3))
                else:
                    # CSV handling
                    content = response.text
                    
                    # Global X often has garbage at top
                    if provider == 'Global X':
                        # Look for header line "Ticker,Name,..." or similar
                        lines = content.split('\n')
                        skip = 0
                        for i, line in enumerate(lines[:10]):
                            if 'Ticker' in line or 'Symbol' in line:
                                skip = i
                                break
                        df = pd.read_csv(StringIO(content), skiprows=skip)
                    
                    elif provider == 'Bitwise':
                        df = pd.read_csv(StringIO(content))
                        
                    else:
                        df = pd.read_csv(StringIO(content))
                
                    print(f"✅ Parsed CSV DataFrame with {len(df)} rows.")
                    print(f"Columns: {df.columns.tolist()}")
                    print(df.head(3))
                    
            except Exception as e:
                print(f"❌ Failed to parse {file_type}: {e}")
                if file_type == 'csv':
                    print(f"Content start: {response.text[:200]}")
        else:
            print(f"❌ Failed with status {response.status_code}")
    except Exception as e:
        print(f"❌ Exception: {e}")

# Revised URLs
urls = [
    # VanEck SMH - Confirmed Excel in previous run
    ("SMH", "https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/holdings/smh-holdings.xlsx", "VanEck", "excel"),
    
    # Global X - Try to parse properly
    ("BOTZ", "https://www.globalxetfs.com/funds/botz/?download_full_holdings=true", "Global X", "csv"),
    
    # SPDR XBI - Confirmed Excel in previous run
    ("XBI", "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xbi.xlsx", "SPDR", "excel"),
    
    # Bitwise - Try different path
    ("BITQ", "https://cn.bitwiseinvestments.com/csv/BITQ.csv", "Bitwise", "csv"), # Try CN domain or other mirror?
]

# Check openpyxl
try:
    import openpyxl
    print("✅ openpyxl is installed")
except ImportError:
    print("❌ openpyxl is NOT installed")

for name, url, provider, ftype in urls:
    test_url(name, url, provider, ftype)
