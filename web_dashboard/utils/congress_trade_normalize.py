"""
Shared congress-trade field normalization for FMP fetch + scraper ingest.

Keeps the unique key stable across sources:
  (politician_id, ticker, transaction_date, amount, type, owner)
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Must match DB unique constraint congress_trades_politician_ticker_date_amount_type_owner_key
CONGRESS_TRADE_UPSERT_ON_CONFLICT = "politician_id,ticker,transaction_date,amount,type,owner"

_OWNER_ALIASES = {
    "self": "Self",
    "spouse": "Spouse",
    "child": "Child",
    "dependent": "Child",
    "joint": "Joint",
    "not-disclosed": "Not-Disclosed",
    "not disclosed": "Not-Disclosed",
    "undisclosed": "Not-Disclosed",
    "unknown": "Unknown",
    "n/a": "Unknown",
    "na": "Unknown",
    "none": "Unknown",
}


def normalize_amount(amount: Any) -> str:
    """Normalize amount ranges so FMP and scraper collide on the same unique key.

    Preferred form (majority of existing rows): ``$1,001 - $15,000``
    """
    if amount is None:
        return ""
    text = str(amount).strip()
    if not text:
        return ""
    # Collapse whitespace around hyphens: "$1,001-$15,000" -> "$1,001 - $15,000"
    text = re.sub(r"\s*-\s*", " - ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_owner(owner: Any, *, default: str = "Unknown") -> str:
    """Normalize owner labels to the values already used in congress_trades."""
    if owner is None:
        return default
    text = str(owner).strip()
    if not text:
        return default
    mapped = _OWNER_ALIASES.get(text.lower())
    if mapped:
        return mapped
    # Title-case unknown-but-present values; keep hyphenated tokens stable
    return text.title() if " " in text or "-" not in text else text


def normalize_trade_type(tx_type: Any, *, default: str = "Purchase") -> str:
    """Normalize transaction type to Purchase/Sale/Exchange/Received."""
    if tx_type is None:
        return default
    text = str(tx_type).strip()
    if not text:
        return default
    lower = text.lower()
    # House PTR shorthand: P / S / S (partial)
    if lower in {"p", "purchase", "buy"} or lower.startswith("p "):
        return "Purchase"
    if lower in {"s", "sale", "sell"} or lower.startswith("s ") or lower.startswith("s("):
        return "Sale"
    if "buy" in lower or "purchase" in lower:
        return "Purchase"
    if "sell" in lower or "sale" in lower:
        return "Sale"
    if "exchange" in lower:
        return "Exchange"
    if "receive" in lower:
        return "Received"
    return default


def normalize_ticker(ticker: Any) -> str:
    """Uppercase ticker for stable unique-key matching."""
    if ticker is None:
        return ""
    return str(ticker).strip().upper()


def congress_trade_dedupe_key(
    politician_id: int,
    ticker: str,
    transaction_date: str,
    amount: str,
    trade_type: str,
    owner: str,
) -> tuple[int, str, str, str, str, str]:
    """Build the unique-key tuple used for in-batch and cross-source dedupe."""
    return (
        int(politician_id),
        normalize_ticker(ticker),
        str(transaction_date).strip(),
        normalize_amount(amount),
        normalize_trade_type(trade_type),
        normalize_owner(owner),
    )


def build_congress_trade_record(
    *,
    politician_id: int,
    ticker: str,
    transaction_date: str,
    amount: Any,
    trade_type: Any,
    owner: Any = None,
    chamber: str | None = None,
    party: str | None = None,
    state: str | None = None,
    disclosure_date: str | None = None,
    price: Any = None,
    asset_type: str | None = None,
    notes: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a congress_trades row ready for upsert (no name column)."""
    record: dict[str, Any] = {
        "politician_id": int(politician_id),
        "ticker": normalize_ticker(ticker),
        "transaction_date": str(transaction_date).strip(),
        "amount": normalize_amount(amount),
        "type": normalize_trade_type(trade_type),
        "owner": normalize_owner(owner),
    }
    if chamber is not None:
        record["chamber"] = chamber
    if party is not None:
        record["party"] = party
    if state is not None:
        record["state"] = state
    if disclosure_date is not None:
        record["disclosure_date"] = str(disclosure_date).strip()
    if price is not None:
        record["price"] = price
    if asset_type is not None:
        record["asset_type"] = asset_type
    if notes is not None:
        record["notes"] = notes
    if extra:
        for key, value in extra.items():
            if key not in record and value is not None:
                record[key] = value
    return record
