"""Tests for rescore_ticker_signals ops script."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

WEB = Path(__file__).resolve().parent.parent / "web_dashboard"
ROOT = WEB.parent
sys.path[:0] = [str(ROOT), str(WEB)]

from scripts import rescore_ticker_signals as rescore  # noqa: E402


def _mock_supabase_module(sb: MagicMock) -> MagicMock:
    mod = MagicMock()
    mod.SupabaseClient.return_value.supabase = sb
    return mod


def test_upsert_signals_preserves_prior_explanation() -> None:
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"explanation": "Prior watchlist note"}]
    )
    sb.table.return_value.upsert.return_value.execute.return_value = MagicMock()

    with patch.dict(sys.modules, {"supabase_client": _mock_supabase_module(sb)}):
        rescore._upsert_signals("MNST", {"overall_signal": "HOLD", "confidence": 0.5})

    upsert_row = sb.table.return_value.upsert.call_args[0][0]
    assert upsert_row["explanation"] == "Prior watchlist note"


def test_upsert_signals_omits_explanation_when_no_prior() -> None:
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )
    sb.table.return_value.upsert.return_value.execute.return_value = MagicMock()

    with patch.dict(sys.modules, {"supabase_client": _mock_supabase_module(sb)}):
        rescore._upsert_signals("MNST", {"overall_signal": "HOLD", "confidence": 0.5})

    upsert_row = sb.table.return_value.upsert.call_args[0][0]
    assert "explanation" not in upsert_row


def test_run_ai_constructs_ticker_analysis_service_with_skip_list() -> None:
    mock_skip_instance = MagicMock()
    mock_ta_cls = MagicMock()
    mock_ta_cls.return_value.analyze_ticker.return_value = {
        "stance": "HOLD",
        "sentiment": "NEUTRAL",
    }
    mock_meta_cls = MagicMock()
    mock_meta_cls.return_value.run_meta_analysis.return_value = {"unified_conviction": "NEUTRAL"}

    mock_skip_mod = MagicMock()
    mock_skip_mod.AISkipListManager.return_value = mock_skip_instance
    mock_ta_mod = MagicMock()
    mock_ta_mod.TickerAnalysisService = mock_ta_cls
    mock_meta_mod = MagicMock()
    mock_meta_mod.TickerMetaAnalysisService = mock_meta_cls

    with patch.dict(
        sys.modules,
        {
            "ollama_client": MagicMock(OllamaClient=MagicMock()),
            "supabase_client": MagicMock(SupabaseClient=MagicMock(return_value=MagicMock())),
            "postgres_client": MagicMock(PostgresClient=MagicMock()),
            "ai_skip_list_manager": mock_skip_mod,
            "ticker_analysis_service": mock_ta_mod,
            "meta_analysis_service": mock_meta_mod,
        },
    ):
        rescore._run_ai("MNST")

    mock_skip_mod.AISkipListManager.assert_called_once()
    mock_ta_cls.assert_called_once()
    args = mock_ta_cls.call_args[0]
    assert len(args) == 4
    assert args[3] is mock_skip_instance
