"""Unit tests for debug/apply_stock_split.py helpers. No DB or network."""

from __future__ import annotations

from decimal import Decimal

import pytest

from debug.apply_stock_split import (
    SplitApplyError,
    adjust_trade_for_split,
    assert_fund_writable,
    implied_open_shares,
    plan_split_updates,
)


def test_rrsp_buy_adjusts_2_for_1() -> None:
    shares, price = adjust_trade_for_split(Decimal("26"), Decimal("62.70"), Decimal("2"))
    assert (shares, price) == (Decimal("52"), Decimal("31.35"))
    assert shares * price == Decimal("26") * Decimal("62.70")


def test_tfsa_fractional_preserves_notional_to_the_cent() -> None:
    shares = Decimal("0.978538")
    price = Decimal("62.70")
    new_shares, new_price = adjust_trade_for_split(shares, price, Decimal("2"))
    assert new_shares == Decimal("1.957076")
    old_notional = (shares * price).quantize(Decimal("0.01"))
    new_notional = (new_shares * new_price).quantize(Decimal("0.01"))
    assert new_notional == old_notional
    assert new_shares / Decimal("2") == shares


def test_ratio_less_than_one_raises() -> None:
    with pytest.raises(SplitApplyError, match="ratio"):
        adjust_trade_for_split(Decimal("10"), Decimal("20"), Decimal("0.5"))


def test_zero_rows_refused() -> None:
    with pytest.raises(SplitApplyError, match="zero rows"):
        plan_split_updates([], Decimal("2"))


def test_production_fund_refused_without_override() -> None:
    with pytest.raises(SplitApplyError, match="production"):
        assert_fund_writable(is_production=True, i_know_this_is_prod=False)
    assert_fund_writable(is_production=True, i_know_this_is_prod=True)
    assert_fund_writable(is_production=False, i_know_this_is_prod=False)


def test_main_dry_run_allows_production_without_override() -> None:
    """4.2 dry-run must work on prod funds; the override is apply-only."""
    from unittest.mock import MagicMock, patch

    fund_row = {"name": "RRSP Lance Webull", "is_production": True}
    trade_row = {
        "id": "00000000-0000-0000-0000-000000000001",
        "date": "2025-09-03T00:00:00+00:00",
        "action": "BUY",
        "shares": "26",
        "price": "62.70",
        "cost_basis": "1630.20",
        "pnl": "0",
    }
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[fund_row]
    )
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=[trade_row]
    )
    mock_client = MagicMock()
    mock_client.supabase = mock_sb
    with patch("web_dashboard.supabase_client.SupabaseClient", return_value=mock_client):
        from debug.apply_stock_split import main

        rc = main(
            [
                "--fund",
                "RRSP Lance Webull",
                "--ticker",
                "MNST",
                "--ratio",
                "2",
                "--dry-run",
            ]
        )
    assert rc == 0
    mock_sb.table.return_value.update.assert_not_called()


def test_implied_open_rrsp_path() -> None:
    rows = [
        {"date": "2025-09-03", "action": "BUY", "shares_before": Decimal("26")},
        {"date": "2025-12-19", "action": "SELL", "shares_before": Decimal("13")},
    ]
    assert implied_open_shares(rows, "shares_before") == Decimal("13")
