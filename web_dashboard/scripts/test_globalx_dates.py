import requests
from datetime import datetime

# Test Global X date-based URL pattern
today = datetime.now()
date_str = today.strftime('%Y%m%d')

urls_to_test = [
    ("BOTZ_TODAY", f"https://assets.globalxetfs.com/funds/holdings/botz_full-holdings_{date_str}.csv"),
    ("LIT_TODAY", f"https://assets.globalxetfs.com/funds/holdings/lit_full-holdings_{date_str}.csv"),
    ("BOTZ_YESTERDAY", "https://assets.globalxetfs.com/funds/holdings/botz_full-holdings_20260122.csv"),
]

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

for name, url in urls_to_test:
    print(f"\nTesting {name}...")
    print(f"URL: {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            print(f"✅ SUCCESS! Got {len(resp.text)} chars")
            lines = resp.text.split('\n')[:5]
            for line in lines:
                print(f"  {line[:100]}")
        else:
            print(f"❌ Status: {resp.status_code}")
    except Exception as e:
        print(f"❌ Error: {e}")
