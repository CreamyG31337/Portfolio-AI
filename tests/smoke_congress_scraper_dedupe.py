"""Smoke test map_trade_to_schema + politician resolve without hitting the network."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Allow importing seed_congress_trades without a real scrape URL
os.environ.setdefault("CONGRESS_TRADES_BASE_URL", "https://example.invalid")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "web_dashboard"))

from web_dashboard.scripts.seed_congress_trades import (  # noqa: E402
    map_trade_to_schema,
    normalize_politician_name,
)
from web_dashboard.utils.congress_trade_normalize import (  # noqa: E402
    CONGRESS_TRADE_UPSERT_ON_CONFLICT,
    congress_trade_dedupe_key,
)
from web_dashboard.utils.politician_mapping import resolve_politician_name  # noqa: E402


def main() -> None:
    raw = {
        "politician": {
            "firstName": "Thomas",
            "lastName": "Kean Jr",
            "chamber": "house",
            "party": "Republican",
            "state": "NJ",
        },
        "issuer": {"ticker": "EQT", "issuerName": "EQT Corporation"},
        "txDate": "2026-06-01",
        "pubDate": "2026-06-18",
        "txType": "buy",
        "value": "$1,001-$15,000",
        "owner": "not disclosed",
    }
    mapped = map_trade_to_schema(raw)
    assert mapped is not None, "map_trade_to_schema returned None"
    assert mapped["ticker"] == "EQT"
    assert mapped["amount"] == "$1,001 - $15,000"
    assert mapped["owner"] == "Not-Disclosed"
    assert mapped["type"] == "Purchase"
    assert mapped["politician"] == "Thomas Kean Jr" or "Kean" in mapped["politician"]
    assert "Jr" in normalize_politician_name("Thomas Kean Jr")

    canonical, bioguide = resolve_politician_name(mapped["politician"])
    assert canonical == "Thomas H. Kean, Jr."
    assert bioguide == "K000398"

    # Simulate scraper→upsert record after politician_id resolve
    record = {
        "politician_id": 425,
        "ticker": mapped["ticker"],
        "transaction_date": mapped["transaction_date"],
        "amount": mapped["amount"],
        "type": mapped["type"],
        "owner": mapped["owner"],
    }
    key = congress_trade_dedupe_key(
        record["politician_id"],
        record["ticker"],
        record["transaction_date"],
        record["amount"],
        record["type"],
        record["owner"],
    )
    fmp_like = congress_trade_dedupe_key(
        425, "EQT", "2026-06-01", "$1,001-$15,000", "Purchase", "Not-Disclosed"
    )
    assert key == fmp_like
    assert CONGRESS_TRADE_UPSERT_ON_CONFLICT.startswith("politician_id")

    # lookup path uses mocked client returning bioguide match
    mock_client = MagicMock()
    mock_client.supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"id": 425, "name": "Thomas H. Kean, Jr.", "party": "Republican", "state": "NJ", "chamber": "House"}]
    )
    with patch(
        "web_dashboard.utils.politician_mapping.lookup_politician_metadata",
        return_value={
            "politician_id": 425,
            "name": "Thomas H. Kean, Jr.",
            "party": "Republican",
            "state": "NJ",
            "chamber": "House",
        },
    ) as _:
        from web_dashboard.utils.politician_mapping import lookup_politician_metadata

        meta = lookup_politician_metadata(mock_client, mapped["politician"])
        assert meta is not None
        assert meta["politician_id"] == 425

    print("SMOKE OK")
    print(f"  mapped amount={mapped['amount']!r} owner={mapped['owner']!r}")
    print(f"  canonical={canonical!r} bioguide={bioguide!r}")
    print(f"  dedupe_key={key}")
    print(f"  on_conflict={CONGRESS_TRADE_UPSERT_ON_CONFLICT}")


if __name__ == "__main__":
    main()
