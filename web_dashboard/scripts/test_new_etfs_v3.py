
import requests
import pandas as pd
from io import StringIO, BytesIO
import logging

logging.basicConfig(level=logging.INFO)

# Known alternative patterns for these providers
urls = [
    # Global X often uses these direct paths which bypass the ?download param
    ("BOTZ", "https://www.globalxetfs.com/content/files/BOTZ-holdings.csv", "Global X", "csv"),
    ("LIT", "https://www.globalxetfs.com/content/files/LIT-holdings.csv", "Global X", "csv"),
    
    # SSGA XBI - Try the link that worked in browser logic previously
    ("XBI", "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xbi.xlsx", "SPDR", "excel"),
    
    # VanEck - Try without the /holdings/ part locally or other common paths
    ("SMH", "https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/holdings/smh-holdings.xlsx", "VanEck", "excel"),
]

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

for name, url, provider, ftype in urls:
    print(f"\nTesting {name} ... {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            ct = resp.headers.get('Content-Type', '')
            print(f"✅ OK. Type: {ct}")
            if 'html' in ct:
                print("⚠️  Warning: Content-Type is HTML, likely not the file.")
                continue
                
            if ftype == 'excel':
                try:
                    df = pd.read_excel(BytesIO(resp.content))
                    print(f"✅ SUCCESS: Parsed Excel with {len(df)} rows")
                    print(df.columns.tolist())
                except Exception as e:
                    print(f"❌ Failed to parse Excel: {e}")
            else:
                try:
                    # Global X CSVs have garbage at the top, usually starts at line 3
                    content = resp.text
                    df = pd.read_csv(StringIO(content), skiprows=2)
                    print(f"✅ SUCCESS: Parsed CSV with {len(df)} rows")
                    print(df.columns.tolist())
                except:
                    try:
                        # Try standard read
                        df = pd.read_csv(StringIO(resp.text))
                        print(f"✅ SUCCESS: Parsed CSV (standard) with {len(df)} rows")
                    except Exception as e:
                        print(f"❌ Failed to parse CSV: {e}")
        else:
            print(f"❌ Failed: {resp.status_code}")
    except Exception as e:
        print(f"❌ Error: {e}")
