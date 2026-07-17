"""Probe Capitol Trades page 1 via FlareSolverr — no DB writes."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["CONGRESS_TRADES_BASE_URL"] = "https://www.capitoltrades.com/trades"

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "web_dashboard"))

from dotenv import load_dotenv

load_dotenv(project_root / "web_dashboard" / ".env")

from web_fetch_client import fetch_page_via_flaresolverr, get_web_fetch_client
from web_dashboard.scripts.seed_congress_trades import extract_trade_data_from_html

BASE = os.environ["CONGRESS_TRADES_BASE_URL"]
url = f"{BASE}?pageSize=50&page=1"
print(f"Fetching {url}")
client = get_web_fetch_client()
print(f"FlareSolverr healthy={client.check_health()} url={client.flaresolverr_url}")
html = fetch_page_via_flaresolverr(url)
if not html:
    print("FAIL: empty HTML from FlareSolverr")
    sys.exit(1)
print(f"HTML bytes={len(html)}")
trades = extract_trade_data_from_html(html) or []
print(f"Parsed trades={len(trades)}")
if not trades:
    print("FAIL: no trades parsed")
    print("has __NEXT_DATA__", "__NEXT_DATA__" in html)
    sys.exit(1)
sample = trades[0]
pol = sample.get("politician") or {}
issuer = sample.get("issuer") or {}
print(
    "sample:",
    pol.get("firstName"),
    pol.get("lastName"),
    issuer.get("ticker") or sample.get("symbol") or sample.get("ticker"),
    sample.get("txDate") or sample.get("pubDate"),
    sample.get("txType"),
)
print("PROBE OK")
