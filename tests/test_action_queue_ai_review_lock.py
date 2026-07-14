"""AI-lock retry for action_queue_ai_review."""

from __future__ import annotations

from unittest.mock import patch

from web_dashboard.scheduler.jobs_dashboard_research import action_queue_ai_review_job


@patch("web_dashboard.scheduler.jobs_dashboard_research.log_job_execution")
def test_action_queue_ai_review_schedules_retry_on_ai_lock(mock_log) -> None:
    with patch(
        "utils.job_tracking.get_running_ai_job",
        return_value="ticker_meta_analysis",
    ), patch(
        "web_dashboard.scheduler.jobs_dashboard_research._schedule_action_queue_ai_review_after_ai_lock",
    ) as mock_retry:
        action_queue_ai_review_job()
    mock_retry.assert_called_once_with("ticker_meta_analysis")
    mock_log.assert_called_once()
    assert "skipped_ai_lock" in mock_log.call_args[0][2]
