"""Unit tests for TickerMetaAnalysisService (no Flask)."""

from datetime import date, datetime, UTC
from unittest.mock import MagicMock
from uuid import UUID

import pytest
import sys
from pathlib import Path

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))


@pytest.fixture(autouse=True)
def _disable_phase3_sector_prior(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 3c bundle block is tested explicitly; keep legacy tests stable."""
    monkeypatch.setenv("META_ANALYSIS_PHASE3_SECTOR", "false")

from meta_analysis_service import (  # noqa: E402
    TickerMetaAnalysisService,
    artifact_bundle_digest,
)


_STD_ROW = {
    "id": UUID("550e8400-e29b-41d4-a716-446655440000"),
    "updated_at": datetime(2026, 4, 1, tzinfo=UTC),
    "analysis_date": None,
    "summary": "Buy the dip",
    "analysis_text": "Details here",
    "stance": "BUY",
    "sentiment": "BULLISH",
    "sentiment_score": 0.8,
    "confidence_score": 0.7,
    "reasoning": "Because",
}


def _congress_empty_supabase(sb: MagicMock) -> None:
    sb.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )


def _svc(pg: MagicMock, sb: MagicMock | None = None) -> TickerMetaAnalysisService:
    supabase = sb or MagicMock()
    return TickerMetaAnalysisService(ollama=None, supabase=supabase, postgres=pg)


def test_needs_refresh_true_when_no_meta() -> None:
    pg = MagicMock()
    pg.execute_query.side_effect = [
        [_STD_ROW],
        [],
        [],
        [],
        [],
    ]
    sb = MagicMock()
    _congress_empty_supabase(sb)
    svc = _svc(pg, sb)
    need, latest = svc.needs_refresh("ABC")
    assert need is True
    assert latest is not None
    assert latest["id"] == _STD_ROW["id"]


def test_needs_refresh_false_when_digest_matches() -> None:
    sb = MagicMock()
    _congress_empty_supabase(sb)
    pg_build = MagicMock()
    pg_build.execute_query.side_effect = [[_STD_ROW], [], [], []]
    svc0 = _svc(pg_build, sb)
    bundle, _ = svc0.build_artifact_bundle("ABC")
    digest = artifact_bundle_digest(bundle)

    pg = MagicMock()
    pg.execute_query.side_effect = [
        [_STD_ROW],
        [],
        [],
        [],
        [{"artifact_bundle_digest": digest, "source_analysis_id": str(_STD_ROW["id"])}],
    ]
    svc = _svc(pg, sb)
    need, primary = svc.needs_refresh("ABC")
    assert need is False
    assert primary is not None


def test_needs_refresh_true_when_social_snippet_changes() -> None:
    """Non–ticker_analysis inputs change bundle text → digest mismatch → refresh."""
    sb = MagicMock()
    _congress_empty_supabase(sb)
    social_a = [
        {
            "summary": "Social A",
            "reasoning": "r",
            "key_themes": [],
            "sentiment_label": "BULLISH",
            "sentiment_score": 0.5,
            "confidence_score": 0.5,
            "platform": "reddit",
            "analyzed_at": datetime(2026, 4, 2, 12, 0, 0, tzinfo=UTC),
        }
    ]
    social_b = [
        {
            "summary": "Social B changed",
            "reasoning": "r",
            "key_themes": [],
            "sentiment_label": "BEARISH",
            "sentiment_score": -0.5,
            "confidence_score": 0.5,
            "platform": "reddit",
            "analyzed_at": datetime(2026, 4, 2, 13, 0, 0, tzinfo=UTC),
        }
    ]

    pg1 = MagicMock()
    pg1.execute_query.side_effect = [[_STD_ROW], [], social_a, []]
    svc1 = _svc(pg1, sb)
    bundle_a, _ = svc1.build_artifact_bundle("ABC")
    digest_a = artifact_bundle_digest(bundle_a)

    pg2 = MagicMock()
    pg2.execute_query.side_effect = [
        [_STD_ROW],
        [],
        social_b,
        [],
        [{"artifact_bundle_digest": digest_a}],
    ]
    svc2 = _svc(pg2, sb)
    need, _ = svc2.needs_refresh("ABC")
    assert need is True


def test_needs_refresh_false_when_no_standard_analysis() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = []
    sb = MagicMock()
    _congress_empty_supabase(sb)
    svc = _svc(pg, sb)
    need, latest = svc.needs_refresh("XYZ")
    assert need is False
    assert latest is None


def test_build_artifact_bundle_empty_without_standard_analysis() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = []
    svc = _svc(pg)
    bundle, primary = svc.build_artifact_bundle("XYZ")
    assert bundle == ""
    assert primary is None


def test_build_artifact_bundle_includes_standard_block() -> None:
    pg = MagicMock()
    pg.execute_query.side_effect = [
        [
            {
                "id": UUID("550e8400-e29b-41d4-a716-446655440000"),
                "updated_at": datetime(2026, 4, 1, tzinfo=UTC),
                "analysis_date": None,
                "summary": "Buy the dip",
                "analysis_text": "Details here",
                "stance": "BUY",
                "sentiment": "BULLISH",
                "sentiment_score": 0.8,
                "confidence_score": 0.7,
                "reasoning": "Because",
            }
        ],
        [],
        [],
        [],
    ]
    sb = MagicMock()
    _congress_empty_supabase(sb)
    svc = _svc(pg, sb)
    bundle, primary = svc.build_artifact_bundle("ABC")
    assert primary is not None
    assert "Latest standard ticker_analysis" in bundle
    assert "Buy the dip" in bundle


def test_build_artifact_bundle_omits_signal_and_brief_when_phase1_disabled(monkeypatch) -> None:
    monkeypatch.delenv("META_ANALYSIS_PHASE1_SIGNAL_FUSION", raising=False)
    monkeypatch.setenv("META_ANALYSIS_PHASE1_SIGNAL_FUSION", "false")
    pg = MagicMock()
    pg.execute_query.side_effect = [[_STD_ROW], [], []]
    sb = MagicMock()
    _congress_empty_supabase(sb)
    svc = _svc(pg, sb)
    bundle, _ = svc.build_artifact_bundle("ABC")
    assert "Technical signal snapshot" not in bundle
    assert "Latest market regime context" not in bundle
    sb.supabase.table.assert_called()


def test_build_artifact_bundle_includes_signal_snapshot() -> None:
    pg = MagicMock()
    pg.execute_query.side_effect = [[_STD_ROW], [], [], []]
    sb = MagicMock()
    _congress_empty_supabase(sb)
    sb.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[
            {
                "analysis_date": "2026-04-02T10:00:00+00:00",
                "overall_signal": "BUY",
                "confidence_score": 0.81,
                "structure_signal": {"trend": "UP"},
                "timing_signal": {"timing": "EARLY"},
                "fear_risk_signal": {"fear_level": "LOW"},
                "momentum_signal": {"bias": "BULLISH", "composite_score": 0.73},
                "fundamental_signal": {"bias": "NEUTRAL", "composite_score": 0.51},
            }
        ]
    )
    svc = _svc(pg, sb)
    bundle, _ = svc.build_artifact_bundle("ABC")
    assert "Technical signal snapshot (latest)" in bundle
    assert "overall_signal: BUY" in bundle


def test_build_artifact_bundle_includes_normalized_market_regime() -> None:
    mb = {
        "brief_date": date(2026, 5, 10),
        "headline": "Indices mixed",
        "narrative": "Tests mixed tape.",
        "regime_json": {
            "risk_tone": "NEUTRAL",
            "leadership_note": "Mega caps firm",
            "caveats": ["light volume"],
        },
        "updated_at": datetime(2026, 5, 10, 22, 0, tzinfo=UTC),
    }
    pg = MagicMock()
    pg.execute_query.side_effect = [[_STD_ROW], [mb], [], []]
    sb = MagicMock()
    _congress_empty_supabase(sb)
    sb.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )
    svc = _svc(pg, sb)
    bundle, _ = svc.build_artifact_bundle("ABC")
    assert "Latest market regime context" in bundle
    assert "risk_regime: NEUTRAL" in bundle
    assert "breadth_proxy: UNCLEAR" in bundle
    assert "volatility_state: UNKNOWN" in bundle
    assert "regime_as_of:" in bundle
    assert "Mega caps firm" in bundle


def test_save_meta_falls_back_to_stance_and_confidence() -> None:
    pg = MagicMock()
    sb = MagicMock()
    svc = _svc(pg, sb)
    response = {
        "stance": "BULLISH",
        "confidence": 0.66,
        "contradictions": ["x"],
        "what_changed_vs_last_run": "N/A",
        "action_items": ["verify"],
        "narrative": "n",
    }
    svc._save_meta("ABC", _STD_ROW, response, "m", None, "digest")
    args = pg.execute_update.call_args[0][1]
    assert args[3] == "BULLISH"
    assert args[4] == 0.66


def test_artifact_bundle_digest_stable() -> None:
    d = artifact_bundle_digest("hello")
    assert len(d) == 64
    assert d == artifact_bundle_digest("hello")
    assert d != artifact_bundle_digest("hello!")


def test_fetch_standard_ticker_candidates_reads_standard_rows_only() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = [
        {"ticker": "tsla"},
        {"ticker": "AAPL"},
        {"ticker": None},
        {"ticker": " "},
        {"ticker": "TSLA"},
    ]
    svc = _svc(pg)

    tickers = svc.fetch_standard_ticker_candidates(limit=10)

    assert tickers == ["TSLA", "AAPL"]
    query, params = pg.execute_query.call_args[0]
    assert "FROM ticker_analysis" in query
    assert "analysis_type = 'standard'" in query
    assert "updated_at DESC" in query
    assert params == (10,)


def test_build_artifact_bundle_includes_sector_prior(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("META_ANALYSIS_PHASE3_SECTOR", "true")
    sector_row = {
        "sector": "Health Care",
        "run_date": date(2026, 5, 19),
        "sector_stance": "MIXED",
        "momentum_state": "UNKNOWN",
        "news_pressure": "MIXED",
        "rotation_rank": 2,
        "confidence": 0.55,
        "key_drivers": ["ETF flows mixed"],
        "risk_flags": ["policy headline risk"],
        "as_of": "2026-05-19T20:00:00Z",
        "updated_at": datetime(2026, 5, 19, 20, 0, tzinfo=UTC),
    }
    pg = MagicMock()
    pg.execute_query.side_effect = [
        [_STD_ROW],  # standard analyses
        [],  # market brief (phase1)
        [sector_row],  # sector_meta prior (phase3c)
        [],  # social
        [],  # articles
    ]
    sb = MagicMock()
    _congress_empty_supabase(sb)

    def _table(name: str) -> MagicMock:
        chain = MagicMock()
        if name == "securities":
            chain.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[{"sector": "Health Care"}]
            )
        else:
            chain.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[]
            )
        return chain

    sb.supabase.table.side_effect = _table
    svc = _svc(pg, sb)
    bundle, _ = svc.build_artifact_bundle("ABC")
    assert "Sector rotation prior" in bundle
    assert "mapped_sector: Health Care" in bundle
    assert "sector_stance: MIXED" in bundle
    assert "rotation_rank: 2" in bundle
    assert "ETF flows mixed" in bundle
