"""Unit tests for TickerMetaAnalysisService (no Flask)."""

from datetime import datetime, UTC
from unittest.mock import MagicMock
from uuid import UUID

import sys
from pathlib import Path

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

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
    pg_build.execute_query.side_effect = [[_STD_ROW], [], []]
    svc0 = _svc(pg_build, sb)
    bundle, _ = svc0.build_artifact_bundle("ABC")
    digest = artifact_bundle_digest(bundle)

    pg = MagicMock()
    pg.execute_query.side_effect = [
        [_STD_ROW],
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
    pg1.execute_query.side_effect = [[_STD_ROW], social_a, []]
    svc1 = _svc(pg1, sb)
    bundle_a, _ = svc1.build_artifact_bundle("ABC")
    digest_a = artifact_bundle_digest(bundle_a)

    pg2 = MagicMock()
    pg2.execute_query.side_effect = [
        [_STD_ROW],
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
    ]
    sb = MagicMock()
    _congress_empty_supabase(sb)
    svc = _svc(pg, sb)
    bundle, primary = svc.build_artifact_bundle("ABC")
    assert primary is not None
    assert "Latest standard ticker_analysis" in bundle
    assert "Buy the dip" in bundle


def test_artifact_bundle_digest_stable() -> None:
    d = artifact_bundle_digest("hello")
    assert len(d) == 64
    assert d == artifact_bundle_digest("hello")
    assert d != artifact_bundle_digest("hello!")
