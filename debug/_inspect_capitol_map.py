"""Inspect mapped Capitol Trades page-1 records without writing to DB."""
from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

os.environ["CONGRESS_TRADES_BASE_URL"] = "https://www.capitoltrades.com/trades"

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "web_dashboard"))

from dotenv import load_dotenv

load_dotenv(project_root / "web_dashboard" / ".env")

from web_fetch_client import fetch_page_via_flaresolverr
from web_dashboard.scripts.seed_congress_trades import (
    extract_trade_data_from_html,
    map_trade_to_schema,
)
from web_dashboard.utils.politician_mapping import resolve_politician_name

url = "https://www.capitoltrades.com/trades?pageSize=100&page=1"
html = fetch_page_via_flaresolverr(url)
assert html
raw = extract_trade_data_from_html(html)
print(f"raw={len(raw)}")
print("raw keys sample:", sorted((raw[0] or {}).keys())[:40])
print("raw[0]=", {k: raw[0].get(k) for k in list(raw[0])[:20]})

mapped_ok = []
skipped = Counter()
for trade in raw:
    mapped = map_trade_to_schema(trade)
    if not mapped:
        skipped["map_failed"] += 1
        continue
    if not mapped.get("ticker"):
        skipped["no_ticker"] += 1
        continue
    name = mapped.get("politician") or ""
    canonical, bioguide = resolve_politician_name(name)
    mapped["_canonical"] = canonical
    mapped["_bioguide"] = bioguide
    mapped_ok.append(mapped)

print(f"mapped_ok={len(mapped_ok)} skipped={dict(skipped)}")
tickers = Counter(m["ticker"] for m in mapped_ok)
print("top tickers:", tickers.most_common(10))
print("dates:", sorted({m["transaction_date"] for m in mapped_ok})[:5], "...", sorted({m["transaction_date"] for m in mapped_ok})[-5:])
kean = [m for m in mapped_ok if "kean" in (m.get("politician") or "").lower() or "kean" in (m.get("_canonical") or "").lower()]
eqt = [m for m in mapped_ok if m["ticker"] == "EQT"]
print(f"kean_on_page={len(kean)} eqt_on_page={len(eqt)}")
for m in mapped_ok[:5]:
    print(
        f"  {m['transaction_date']} {m['type']:9} {m['ticker']:6} {m['amount']:20} {m['owner']:14} {m['politician']} -> {m['_canonical']}"
    )
