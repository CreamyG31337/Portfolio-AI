"""Detail Kean/EQT and Crenshaw rows on Capitol Trades page 1."""
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

from web_fetch_client import fetch_page_via_flaresolverr
from web_dashboard.scripts.seed_congress_trades import (
    extract_trade_data_from_html,
    map_trade_to_schema,
)
from web_dashboard.utils.politician_mapping import resolve_politician_name

html = fetch_page_via_flaresolverr("https://www.capitoltrades.com/trades?pageSize=100&page=1")
raw = extract_trade_data_from_html(html)

print("=== KEAN / EQT raw+mapped ===")
for trade in raw:
    pol = trade.get("politician") or {}
    name = f"{pol.get('firstName','')} {pol.get('lastName','')}".strip()
    issuer = trade.get("issuer") or {}
    ticker = issuer.get("issuerTicker") or issuer.get("ticker")
    if "kean" in name.lower() or ticker == "EQT":
        mapped = map_trade_to_schema(trade)
        canon, bio = resolve_politician_name(mapped["politician"] if mapped else name)
        print(
            {
                "name": name,
                "ticker": ticker,
                "tx": trade.get("txDate"),
                "pub": trade.get("pubDate"),
                "type": trade.get("txType"),
                "value": trade.get("value"),
                "owner": trade.get("owner"),
                "issuer": issuer.get("issuerName"),
                "mapped": mapped,
                "canonical": canon,
                "bioguide": bio,
            }
        )

print("\n=== CRENSHAW ===")
for trade in raw:
    pol = trade.get("politician") or {}
    name = f"{pol.get('firstName','')} {pol.get('lastName','')}".strip()
    if "crenshaw" not in name.lower():
        continue
    issuer = trade.get("issuer") or {}
    mapped = map_trade_to_schema(trade)
    print(
        {
            "name": name,
            "ticker": issuer.get("issuerTicker"),
            "issuer": issuer.get("issuerName"),
            "tx": trade.get("txDate"),
            "pub": trade.get("pubDate"),
            "type": trade.get("txType"),
            "value": trade.get("value"),
            "owner": trade.get("owner"),
            "mapped_ticker": mapped.get("ticker") if mapped else None,
            "mapped_amount": mapped.get("amount") if mapped else None,
        }
    )
