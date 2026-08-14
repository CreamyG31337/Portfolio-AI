"""Tests for rescore_ticker_signals ops script."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# sys.path is set up by tests/conftest.py, which pins root before web_dashboard
# on purpose; re-inserting them here would risk shadowing root modules.
from scripts import rescore_ticker_signals as rescore  # noqa: E402


def _mock_supabase_module(sb: MagicMock) -> MagicMock:
    mod = MagicMock()
    mod.SupabaseClient.return_value.supabase = sb
    return mod


def _explainer_module(explanation: str | None) -> MagicMock:
    mod = MagicMock()
    mod.generate_signal_explanation.return_value = explanation
    return mod


def test_upsert_signals_regenerates_explanation_from_new_signals() -> None:
    """The prior row's narrative described the pre-fix numbers; it must not carry over."""
    sb = MagicMock()
    sb.table.return_value.upsert.return_value.execute.return_value = MagicMock()
    signals = {"overall_signal": "HOLD", "confidence": 0.5}
    explainer = _explainer_module("Fresh post-split note")

    with patch.dict(
        sys.modules,
        {
            "supabase_client": _mock_supabase_module(sb),
            "web_dashboard.signals.ai_explainer": explainer,
        },
    ):
        rescore._upsert_signals("MNST", signals)

    upsert_row = sb.table.return_value.upsert.call_args[0][0]
    assert upsert_row["explanation"] == "Fresh post-split note"
    explainer.generate_signal_explanation.assert_called_once_with("MNST", signals)
    # The old row is never read - nothing should have been selected from it.
    assert sb.table.return_value.select.call_count == 0


def test_upsert_signals_writes_null_explanation_when_generation_fails() -> None:
    sb = MagicMock()
    sb.table.return_value.upsert.return_value.execute.return_value = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "supabase_client": _mock_supabase_module(sb),
            "web_dashboard.signals.ai_explainer": _explainer_module(None),
        },
    ):
        rescore._upsert_signals("MNST", {"overall_signal": "HOLD", "confidence": 0.5})

    upsert_row = sb.table.return_value.upsert.call_args[0][0]
    assert upsert_row["explanation"] is None


def test_with_ai_requires_apply() -> None:
    """--with-ai alone used to be silently ignored; it must now be rejected."""
    with patch.object(sys, "argv", ["rescore", "MNST", "--with-ai"]):
        with pytest.raises(SystemExit) as excinfo:
            rescore.main()
    assert excinfo.value.code == 2


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
