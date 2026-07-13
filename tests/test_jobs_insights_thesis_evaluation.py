"""Tests for insights thesis evaluation job (advisory llm_reply)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from web_dashboard.scheduler.jobs_insights_thesis_evaluation import (
    insights_thesis_evaluation_job,
)


@patch("web_dashboard.scheduler.jobs_insights_thesis_evaluation.log_job_execution")
def test_insights_thesis_evaluation_posts_llm_reply_without_disposition_flip(mock_log) -> None:
    thesis_id = str(uuid4())
    detail = {
        "id": thesis_id,
        "ticker": "MSFT",
        "title": "Cloud moat",
        "disposition": "bullish",
        "intent": "monitor",
        "last_reviewed_at": "2026-01-01T00:00:00+00:00",
        "entries": [{"entry_kind": "opening", "body": "Scale advantages."}],
    }

    postgres = MagicMock()

    with patch(
        "utils.job_tracking.get_running_ai_job",
        return_value=None,
    ), patch(
        "utils.job_tracking.mark_job_started",
    ), patch(
        "utils.job_tracking.mark_job_completed",
    ), patch(
        "postgres_client.PostgresClient",
        return_value=postgres,
    ), patch(
        "ollama_client.get_ollama_client",
        return_value=MagicMock(),
    ), patch(
        "ollama_client.collect_with_summary_model_chain",
        return_value=(
            '{"verdict":"HOLDS","one_liner":"Still coherent.","suggested_disposition":"bearish","suggested_intent":"seek_exit"}',
            "test-model",
        ),
    ), patch(
        "settings.get_summarizing_model",
        return_value="test-model",
    ), patch(
        "user_insights_service.list_theses_due",
        return_value=[{
            "id": thesis_id,
            "ticker": "MSFT",
            "is_weak": False,
            "review_status": "stale",
        }],
    ), patch(
        "user_insights_service.get_thesis_detail",
        return_value=detail,
    ) as mock_detail, patch(
        "user_insights_service.add_llm_reply",
        return_value={"entry_id": str(uuid4()), "thesis": detail},
    ) as mock_reply, patch(
        "user_insights_service.add_evidence",
        return_value={},
    ), patch(
        "ticker_analysis_service.extract_json",
        side_effect=lambda s: {
            "verdict": "HOLDS",
            "one_liner": "Still coherent.",
            "suggested_disposition": "bearish",
            "suggested_intent": "seek_exit",
        },
    ):
        # Research excerpt query (ticker_analysis / meta) — empty is fine.
        postgres.execute_query.return_value = []
        insights_thesis_evaluation_job()

    mock_reply.assert_called_once()
    kwargs = mock_reply.call_args.kwargs
    assert kwargs["thesis_id"] == thesis_id
    assert kwargs["metadata"]["verdict"] == "HOLDS"
    assert kwargs["metadata"]["suggested_disposition"] == "bearish"
    # Job only inserts llm_reply; never flips disposition via add_entry/update.
    assert mock_detail.call_count >= 2  # before + after invariant check
    mock_log.assert_called()
    assert mock_log.call_args[0][1] is True


@patch("web_dashboard.scheduler.jobs_insights_thesis_evaluation.log_job_execution")
def test_insights_thesis_evaluation_skips_when_ai_lock_held(mock_log) -> None:
    with patch(
        "utils.job_tracking.get_running_ai_job",
        return_value="ticker_meta_analysis",
    ), patch(
        "user_insights_service.list_theses_due",
    ) as mock_due:
        insights_thesis_evaluation_job()
    mock_due.assert_not_called()
    mock_log.assert_not_called()
