"""Pure helpers for fund cash balance API (no Flask imports)."""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple


def cash_amount_from_row(row: Dict[str, Any]) -> float:
    """Read numeric cash from a cash_balances row (amount preferred, balance legacy)."""
    if row.get("amount") is not None:
        return float(row["amount"])
    if row.get("balance") is not None:
        return float(row["balance"])
    return 0.0


def parse_put_cash_balances_body(data: Any) -> Tuple[Optional[Tuple[float, float]], Optional[str]]:
    """
    Validate PUT body for cash balances. Requires both CAD and USD as finite numbers.
    Returns ((cad, usd), None) on success or (None, error_message).
    """
    if not isinstance(data, dict):
        return None, "Request body must be a JSON object"
    if "CAD" not in data or "USD" not in data:
        return None, "Both CAD and USD amounts are required"
    try:
        cad = float(data["CAD"])
        usd = float(data["USD"])
    except (TypeError, ValueError):
        return None, "CAD and USD must be numeric"
    if not math.isfinite(cad) or not math.isfinite(usd):
        return None, "CAD and USD must be finite numbers"
    return (cad, usd), None
