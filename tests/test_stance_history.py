"""Tests for stance_history ledger helper."""

import json
from unittest.mock import MagicMock

from web_dashboard.stance_history import (
    format_prior_stance_for_meta_bundle,
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


def test_record_stance_serializes_evidence_metadata() -> None:
    """G1 provenance: evidence manifest survives JSON serialization into metadata."""
    pg = MagicMock()
    pg.execute_query.return_value = []
    pg.execute_update.return_value = 1

    evidence = {
        "article_ids": ["11111111-1111-1111-1111-111111111111"],
        "artifact_types": ["standard_analysis", "articles", "social"],
    }
    inserted = record_stance(
        pg,
        ticker="ABC",
        source="ticker_meta_analysis",
        stance="BULLISH",
        confidence=0.7,
        metadata={"contradictions_count": 2, "evidence": evidence},
    )

    assert inserted is True
    # Insert positional args: metadata json is the last bound parameter.
    insert_args = pg.execute_update.call_args[0][1]
    metadata_json = insert_args[-1]
    assert isinstance(metadata_json, str)
    parsed = json.loads(metadata_json)
    assert parsed["evidence"] == evidence
    assert parsed["contradictions_count"] == 2


def test_record_stance_metadata_none_when_empty() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = []
    pg.execute_update.return_value = 1

    record_stance(pg, ticker="ABC", source="ticker_analysis", stance="BUY")

    insert_args = pg.execute_update.call_args[0][1]
    assert insert_args[-1] is None


def test_format_prior_stance_empty_history_returns_none() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = []
    assert format_prior_stance_for_meta_bundle(pg, "COST") is None


def test_format_prior_stance_flip_and_track_record() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = [
        {
            "stance": "BEARISH",
            "confidence": 0.6,
            "as_of": "2026-07-15",
            "source": "ticker_meta_analysis",
        },
        {
            "stance": "BULLISH",
            "confidence": 0.7,
            "as_of": "2026-07-14",
            "source": "ticker_meta_analysis",
        },
    ]
    track = {
        "horizon_days": 30,
        "hit_rate_by_source": {"ticker_meta_analysis": 0.5},
        "avg_excess_by_source": {"ticker_meta_analysis": -1.2},
        "counts_by_source": {
            "ticker_meta_analysis": {"scored": 100, "hits": 50, "misses": 50, "unscoreable": 0}
        },
    }
    block = format_prior_stance_for_meta_bundle(pg, "cost", track_summary=track)
    assert block is not None
    assert "### Prior stance and track record" in block
    assert "stance=BEARISH" in block
    assert "(FLIP)" in block
    assert "hit_rate=50.0%" in block
    # Labelled directional so the meta bundle cannot mislead the LLM into reading
    # a correct bearish call's negative raw excess as a bad outcome.
    assert "mean_directional_excess=-1.20" in block
    assert "source calibration" in block
