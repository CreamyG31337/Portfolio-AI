"""Scheduler job lifecycle finalization regression tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_social_sentiment_marks_failed_on_post_start_runtime_error():
    from web_dashboard.scheduler.jobs_social import fetch_social_sentiment_job

    with patch("utils.job_tracking.get_running_ai_job", return_value=None), patch(
        "utils.job_tracking.mark_job_started"
    ) as mark_started, patch(
        "utils.job_tracking.mark_job_completed"
    ) as mark_completed, patch(
        "utils.job_tracking.mark_job_failed"
    ) as mark_failed, patch(
        "web_dashboard.scheduler.jobs_social.log_job_execution"
    ), patch(
        "social_service.SocialSentimentService", side_effect=RuntimeError("service init failed")
    ), patch(
        "supabase_client.SupabaseClient", return_value=SimpleNamespace(supabase=MagicMock())
    ):
        fetch_social_sentiment_job()

    mark_started.assert_called_once()
    mark_failed.assert_called_once()
    mark_completed.assert_not_called()


def test_market_research_marks_failed_when_searxng_unavailable():
    from web_dashboard.scheduler.jobs_research import market_research_job

    with patch("utils.job_tracking.get_running_ai_job", return_value=None), patch(
        "utils.job_tracking.mark_job_started"
    ) as mark_started, patch(
        "utils.job_tracking.mark_job_completed"
    ) as mark_completed, patch(
        "utils.job_tracking.mark_job_failed"
    ) as mark_failed, patch(
        "web_dashboard.scheduler.jobs_research.log_job_execution"
    ), patch(
        "searxng_client.check_searxng_health", return_value=False
    ), patch(
        "utils.job_tracking.log_job_step"
    ):
        market_research_job()

    mark_started.assert_called_once()
    mark_failed.assert_called_once()
    mark_completed.assert_not_called()
