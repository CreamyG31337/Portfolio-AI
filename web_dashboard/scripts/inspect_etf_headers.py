
import requests
import logging

logging.basicConfig(level=logging.INFO)

urls = [
    ("SMH", "https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/holdings/smh-holdings.xlsx"),
    ("BOTZ", "https://www.globalxetfs.com/funds/botz/?download_full_holdings=true"),
]

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

for name, url in urls:
    print(f"\n--- Checking {name} ---")
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('Content-Type')}")
        print("First 2000 chars:")
        print(resp.text[:2000])
    except Exception as e:
        print(f"Error: {e}")
