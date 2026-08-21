"""Tests for dividend eligibility vs trade_log conventions (positive shares, SELL in reason)."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from scheduler.jobs_dividends import calculate_eligible_shares


from unittest.mock import patch


@patch("supabase_pagination.fetch_all_rows")
def test_eligible_shares_zero_after_full_exit_before_ex_date(mock_fetch) -> None:
    mock_fetch.return_value = [
        {"shares": 100, "date": "2024-01-05T00:00:00", "reason": "BUY order - BUY"},
        {"shares": 100, "date": "2024-02-10T00:00:00", "reason": "Trim - SELL"},
    ]
    client = MagicMock()
    assert calculate_eligible_shares("TEST", "FOO", date(2024, 3, 1), client) == Decimal("0")


@patch("supabase_pagination.fetch_all_rows")
def test_eligible_shares_partial_sell(mock_fetch) -> None:
    mock_fetch.return_value = [
        {"shares": 100, "date": "2024-01-05T00:00:00", "reason": "BUY order - BUY"},
        {"shares": 40, "date": "2024-02-10T00:00:00", "reason": "Trim - SELL"},
    ]
    client = MagicMock()
    assert calculate_eligible_shares("TEST", "FOO", date(2024, 3, 1), client) == Decimal("60")


@patch("supabase_pagination.fetch_all_rows")
def test_eligible_shares_includes_drip_before_ex_date(mock_fetch) -> None:
    mock_fetch.return_value = [
        {"shares": 100, "date": "2024-01-05T00:00:00", "reason": "BUY order - BUY"},
        {"shares": 2.5, "date": "2024-02-01T00:00:00", "reason": "DRIP"},
    ]
    client = MagicMock()
    assert calculate_eligible_shares("TEST", "FOO", date(2024, 3, 1), client) == Decimal("102.5")
