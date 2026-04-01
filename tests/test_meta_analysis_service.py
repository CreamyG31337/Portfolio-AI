"""Unit tests for TickerMetaAnalysisService (no Flask)."""

from datetime import datetime, UTC
from unittest.mock import MagicMock
from uuid import UUID


import sys
from pathlib import Path

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

from meta_analysis_service import TickerMetaAnalysisService  # noqa: E402


def _svc(pg: MagicMock, sb: MagicMock | None = None) -> TickerMetaAnalysisService:
    supabase = sb or MagicMock()
    return TickerMetaAnalysisService(ollama=None, supabase=supabase, postgres=pg)


def test_needs_refresh_true_when_no_meta() -> None:
    pg = MagicMock()
    latest_id = UUID("550e8400-e29b-41d4-a716-446655440000")
    pg.execute_query.side_effect = [
        [
            {
                "id": latest_id,
                "updated_at": datetime(2026, 4, 1, tzinfo=UTC),
            }
        ],
        [],
    ]
    svc = _svc(pg)
    need, latest = svc.needs_refresh("ABC")
    assert need is True
    assert latest["id"] == latest_id


def test_needs_refresh_false_when_meta_matches_snapshot() -> None:
    pg = MagicMock()
    aid = UUID("550e8400-e29b-41d4-a716-446655440000")
    snap = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
    pg.execute_query.side_effect = [
        [{"id": aid, "updated_at": snap}],
        [
            {
                "source_analysis_id": aid,
                "source_analysis_snapshot_at": snap,
            }
        ],
    ]
    svc = _svc(pg)
    need, _ = svc.needs_refresh("ABC")
    assert need is False


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
    sb.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )
    svc = _svc(pg, sb)
    bundle, primary = svc.build_artifact_bundle("ABC")
    assert primary is not None
    assert "Latest standard ticker_analysis" in bundle
    assert "Buy the dip" in bundle
