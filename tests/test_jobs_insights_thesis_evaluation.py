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
        "user_insights_service.should_skip_thesis_eval",
        return_value=(False, "digest123", ""),
    ), patch(
        "stance_history.record_stance_safe",
        return_value=True,
    ) as mock_ledger, patch(
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
    assert kwargs["metadata"]["research_digest"] == "digest123"
    mock_ledger.assert_called_once()
    assert mock_ledger.call_args.kwargs["source"] == "thesis_ai_review"
    assert mock_ledger.call_args.kwargs["stance"] == "BEARISH"
    # Job only inserts llm_reply; never flips disposition via add_entry/update.
    assert mock_detail.call_count >= 2  # before + after invariant check
    mock_log.assert_called()
    assert mock_log.call_args[0][1] is True
    assert "skipped_digest=0" in mock_log.call_args[0][2]


@patch("web_dashboard.scheduler.jobs_insights_thesis_evaluation.log_job_execution")
def test_insights_thesis_evaluation_skips_unchanged_digest(mock_log) -> None:
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

    with patch(
        "utils.job_tracking.get_running_ai_job",
        return_value=None,
    ), patch(
        "utils.job_tracking.mark_job_started",
    ), patch(
        "utils.job_tracking.mark_job_completed",
    ), patch(
        "postgres_client.PostgresClient",
        return_value=MagicMock(),
    ), patch(
        "ollama_client.get_ollama_client",
        return_value=MagicMock(),
    ), patch(
        "ollama_client.collect_with_summary_model_chain",
    ) as mock_llm, patch(
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
    ), patch(
        "user_insights_service.should_skip_thesis_eval",
        return_value=(True, "same", "research_digest_unchanged"),
    ), patch(
        "user_insights_service.add_llm_reply",
    ) as mock_reply:
        insights_thesis_evaluation_job()

    mock_llm.assert_not_called()
    mock_reply.assert_not_called()
    assert mock_log.call_args[0][1] is True
    assert "skipped_digest=1" in mock_log.call_args[0][2]
    assert "replies=0" in mock_log.call_args[0][2]


@patch("web_dashboard.scheduler.jobs_insights_thesis_evaluation.log_job_execution")
def test_insights_thesis_evaluation_archives_weak_after_insufficient_streak(mock_log) -> None:
    thesis_id = str(uuid4())
    opening = {"entry_kind": "opening", "body": "[WEAK CONTEXT] thin", "metadata": {}}
    prior_insuff = [
        {"entry_kind": "llm_reply", "metadata": {"verdict": "INSUFFICIENT_DATA"}}
        for _ in range(2)
    ]
    detail_before = {
        "id": thesis_id,
        "ticker": "GLO.TO",
        "title": "[WEAK CONTEXT] thin",
        "disposition": "neutral",
        "intent": "monitor",
        "last_reviewed_at": "2026-01-01T00:00:00+00:00",
        "entries": [opening, *prior_insuff],
        "is_weak": True,
    }
    detail_after = {
        **detail_before,
        "entries": [
            *detail_before["entries"],
            {"entry_kind": "llm_reply", "metadata": {"verdict": "INSUFFICIENT_DATA"}},
        ],
    }

    with patch(
        "utils.job_tracking.get_running_ai_job",
        return_value=None,
    ), patch(
        "utils.job_tracking.mark_job_started",
    ), patch(
        "utils.job_tracking.mark_job_completed",
    ), patch(
        "postgres_client.PostgresClient",
        return_value=MagicMock(execute_query=MagicMock(return_value=[])),
    ), patch(
        "ollama_client.get_ollama_client",
        return_value=MagicMock(),
    ), patch(
        "ollama_client.collect_with_summary_model_chain",
        return_value=(
            '{"verdict":"INSUFFICIENT_DATA","one_liner":"Too thin."}',
            "test-model",
        ),
    ), patch(
        "settings.get_summarizing_model",
        return_value="test-model",
    ), patch(
        "user_insights_service.list_theses_due",
        return_value=[{
            "id": thesis_id,
            "ticker": "GLO.TO",
            "is_weak": True,
            "review_status": "due_for_review",
        }],
    ), patch(
        "user_insights_service.get_thesis_detail",
        side_effect=[detail_before, detail_after],
    ), patch(
        "user_insights_service.should_skip_thesis_eval",
        return_value=(False, "d1", ""),
    ), patch(
        "user_insights_service.add_llm_reply",
        return_value={"entry_id": str(uuid4()), "thesis": detail_after},
    ), patch(
        "user_insights_service.add_evidence",
        return_value={},
    ), patch(
        "user_insights_service.archive_thesis",
        return_value=detail_after,
    ) as mock_arch, patch(
        "ticker_analysis_service.extract_json",
        return_value={"verdict": "INSUFFICIENT_DATA", "one_liner": "Too thin."},
    ):
        insights_thesis_evaluation_job()

    mock_arch.assert_called_once()
    assert mock_arch.call_args.kwargs["system"] is True
    assert "archived_weak=1" in mock_log.call_args[0][2]


@patch("web_dashboard.scheduler.jobs_insights_thesis_evaluation.log_job_execution")
def test_insights_thesis_evaluation_skips_when_ai_lock_held(mock_log) -> None:
    with patch(
        "utils.job_tracking.get_running_ai_job",
        return_value="ticker_meta_analysis",
    ), patch(
        "web_dashboard.scheduler.jobs_insights_thesis_evaluation._schedule_insights_eval_after_ai_lock",
    ) as mock_retry, patch(
        "user_insights_service.list_theses_due",
    ) as mock_due:
        insights_thesis_evaluation_job()
    mock_due.assert_not_called()
    mock_retry.assert_called_once_with("ticker_meta_analysis")
    mock_log.assert_called_once()
    assert "skipped_ai_lock" in mock_log.call_args[0][2]
