"""Tests for stance_history ledger helper."""

from unittest.mock import MagicMock

from web_dashboard.stance_history import (
    is_directional_stance,
    record_stance,
)


def test_is_directional_stance_buy_sell() -> None:
    assert is_directional_stance("BUY") is True
    assert is_directional_stance("SELL") is True
    assert is_directional_stance("BULLISH") is True


def test_is_directional_stance_excludes_risk_watch() -> None:
    assert is_directional_stance("RISK") is False
    assert is_directional_stance("WATCH") is False


def test_is_directional_stance_excludes_hold() -> None:
    # HOLD can never be a hit or miss under the excess-return rule;
    # scoring it would only inflate denominators.
    assert is_directional_stance("HOLD") is False


def test_record_stance_inserts_when_no_prior_row() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = []
    pg.execute_update.return_value = 1

    inserted = record_stance(
        pg,
        ticker="abc",
        source="ticker_analysis",
        stance="BUY",
        confidence=0.8,
    )

    assert inserted is True
    pg.execute_update.assert_called_once()
    args = pg.execute_update.call_args[0][1]
    assert args[0] == "ABC"
    assert args[2] == "ticker_analysis"
    assert args[3] == "BUY"


def test_record_stance_skips_when_unchanged() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = [{"stance": "BUY"}]

    inserted = record_stance(
        pg,
        ticker="ABC",
        source="ticker_analysis",
        stance="BUY",
    )

    assert inserted is False
    pg.execute_update.assert_not_called()


def test_record_stance_inserts_when_changed() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = [{"stance": "BUY"}]
    pg.execute_update.return_value = 1

    inserted = record_stance(
        pg,
        ticker="ABC",
        source="ticker_analysis",
        stance="SELL",
        fund_key="TEST",
    )

    assert inserted is True
    pg.execute_update.assert_called_once()


def test_record_stance_inserts_when_confidence_changes() -> None:
    # Same stance but moved confidence must be recorded — confidence drift is
    # the raw material for calibration analysis.
    pg = MagicMock()
    pg.execute_query.return_value = [{"stance": "BUY", "confidence": 0.5}]
    pg.execute_update.return_value = 1

    inserted = record_stance(
        pg,
        ticker="ABC",
        source="ticker_analysis",
        stance="BUY",
        confidence=0.9,
    )

    assert inserted is True
    pg.execute_update.assert_called_once()


def test_record_stance_dedupes_per_fund_key() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = []
    pg.execute_update.return_value = 1

    record_stance(
        pg,
        ticker="ABC",
        source="action_queue_ai_review",
        fund_key="FundA",
        stance="BUY",
    )

    query_args = pg.execute_query.call_args[0][1]
    assert query_args == ("ABC", "action_queue_ai_review", "FundA")
