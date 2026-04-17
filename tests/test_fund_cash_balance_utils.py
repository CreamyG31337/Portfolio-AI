"""Unit tests for fund cash balance validation helpers (no Flask)."""

import sys
from pathlib import Path

web_dashboard_path = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard_path) not in sys.path:
    sys.path.insert(0, str(web_dashboard_path))

from routes.fund_cash_balance_utils import (  # noqa: E402
    cash_amount_from_row,
    parse_put_cash_balances_body,
)


def test_cash_amount_from_row_prefers_amount() -> None:
    assert cash_amount_from_row({"amount": 12.34, "balance": 99.0}) == 12.34


def test_cash_amount_from_row_legacy_balance() -> None:
    assert cash_amount_from_row({"balance": 5.5}) == 5.5


def test_cash_amount_from_row_empty() -> None:
    assert cash_amount_from_row({}) == 0.0


def test_parse_put_requires_dict() -> None:
    amounts, err = parse_put_cash_balances_body(None)
    assert amounts is None and err is not None


def test_parse_put_requires_both_currencies() -> None:
    amounts, err = parse_put_cash_balances_body({"CAD": 1.0})
    assert amounts is None and "Both CAD and USD" in (err or "")


def test_parse_put_rejects_non_finite() -> None:
    amounts, err = parse_put_cash_balances_body({"CAD": 1.0, "USD": float("nan")})
    assert amounts is None and err is not None


def test_parse_put_accepts_negative() -> None:
    amounts, err = parse_put_cash_balances_body({"CAD": -10.0, "USD": 0.0})
    assert err is None and amounts == (-10.0, 0.0)
