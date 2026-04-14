"""Tests for dividend eligibility vs trade_log conventions (positive shares, SELL in reason)."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from scheduler.jobs_dividends import calculate_eligible_shares


def _client_with_trades(rows: list[dict]) -> MagicMock:
    client = MagicMock()
    execute_result = MagicMock()
    execute_result.data = rows
    chain = (
        client.supabase.table.return_value.select.return_value.eq.return_value
        .eq.return_value.lt.return_value.order.return_value.execute
    )
    chain.return_value = execute_result
    return client


def test_eligible_shares_zero_after_full_exit_before_ex_date() -> None:
    client = _client_with_trades(
        [
            {"shares": 100, "date": "2024-01-05T00:00:00", "reason": "BUY order - BUY"},
            {"shares": 100, "date": "2024-02-10T00:00:00", "reason": "Trim - SELL"},
        ]
    )
    assert calculate_eligible_shares("TEST", "FOO", date(2024, 3, 1), client) == Decimal("0")


def test_eligible_shares_partial_sell() -> None:
    client = _client_with_trades(
        [
            {"shares": 100, "date": "2024-01-05T00:00:00", "reason": "BUY order - BUY"},
            {"shares": 40, "date": "2024-02-10T00:00:00", "reason": "Trim - SELL"},
        ]
    )
    assert calculate_eligible_shares("TEST", "FOO", date(2024, 3, 1), client) == Decimal("60")


def test_eligible_shares_includes_drip_before_ex_date() -> None:
    client = _client_with_trades(
        [
            {"shares": 100, "date": "2024-01-05T00:00:00", "reason": "BUY order - BUY"},
            {"shares": 2.5, "date": "2024-02-01T00:00:00", "reason": "DRIP"},
        ]
    )
    assert calculate_eligible_shares("TEST", "FOO", date(2024, 3, 1), client) == Decimal("102.5")
