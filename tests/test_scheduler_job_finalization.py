"""Scheduler job lifecycle finalization regression tests."""

import sys
import types
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


def test_social_sentiment_ai_marks_failed_when_ollama_unavailable():
    """social_sentiment_ai_job holds the global AI lock -- an unpaired
    mark_job_started here is the worst kind of leak, since it blocks every
    other AI job in the fleet via get_running_ai_job() until the stale-lock
    cleaner eventually fires. Ollama being down after start must call
    mark_job_failed, not leak a 'running' row.
    """
    from web_dashboard.scheduler.jobs_social import social_sentiment_ai_job

    mock_service = MagicMock()
    mock_service.ollama = None

    with patch("utils.job_tracking.get_running_ai_job", return_value=None), patch(
        "utils.job_tracking.mark_job_started"
    ) as mark_started, patch(
        "utils.job_tracking.mark_job_completed"
    ) as mark_completed, patch(
        "utils.job_tracking.mark_job_failed"
    ) as mark_failed, patch(
        "web_dashboard.scheduler.jobs_social.log_job_execution"
    ), patch(
        "social_service.SocialSentimentService", return_value=mock_service
    ):
        social_sentiment_ai_job()

    mark_started.assert_called_once()
    mark_failed.assert_called_once()
    mark_completed.assert_not_called()


def test_social_sentiment_ai_marks_failed_on_import_error():
    """Same AI-lock-holder job: a missing dependency after mark_job_started
    must also resolve to mark_job_failed, not silently leak.
    """
    from web_dashboard.scheduler.jobs_social import social_sentiment_ai_job

    # Install a stand-in module lacking SocialSentimentService so the
    # in-function ``from social_service import SocialSentimentService``
    # raises ImportError, without needing to remove the real module (which
    # may already be cached in sys.modules with real dependencies loaded).
    broken = types.ModuleType("social_service")

    with patch("utils.job_tracking.get_running_ai_job", return_value=None), patch(
        "utils.job_tracking.mark_job_started"
    ) as mark_started, patch(
        "utils.job_tracking.mark_job_completed"
    ) as mark_completed, patch(
        "utils.job_tracking.mark_job_failed"
    ) as mark_failed, patch(
        "web_dashboard.scheduler.jobs_social.log_job_execution"
    ), patch.dict(sys.modules, {"social_service": broken}):
        social_sentiment_ai_job()

    mark_started.assert_called_once()
    mark_failed.assert_called_once()
    mark_completed.assert_not_called()


def test_ticker_research_no_production_funds_marks_completed():
    """A legitimate 'nothing to do' no-op (no production funds configured)
    must resolve to mark_job_completed -- matching the opportunity_discovery
    'No results' doctrine -- not leak a running row.
    """
    from web_dashboard.scheduler.jobs_research import ticker_research_job

    fake_client = MagicMock()
    fake_client.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        SimpleNamespace(data=[])
    )

    with patch("utils.job_tracking.get_running_ai_job", return_value=None), patch(
        "utils.job_tracking.mark_job_started"
    ) as mark_started, patch(
        "utils.job_tracking.mark_job_completed"
    ) as mark_completed, patch(
        "utils.job_tracking.mark_job_failed"
    ) as mark_failed, patch(
        "web_dashboard.scheduler.jobs_research.log_job_execution"
    ), patch(
        "searxng_client.check_searxng_health", return_value=True
    ), patch(
        "searxng_client.get_searxng_client", return_value=MagicMock()
    ), patch(
        "ollama_client.get_ollama_client", return_value=MagicMock()
    ), patch(
        "research_repository.ResearchRepository", return_value=MagicMock()
    ), patch(
        "settings.get_research_domain_blacklist", return_value=[]
    ), patch(
        "supabase_client.SupabaseClient", return_value=fake_client
    ):
        ticker_research_job()

    mark_started.assert_called_once()
    mark_completed.assert_called_once()
    mark_failed.assert_not_called()


def test_newsletter_ai_processing_marks_failed_with_correct_signature():
    """Regression for a bug where the except-block called
    ``mark_job_failed(job_id, target_date, message=str(e), duration_ms=...)``
    -- an invalid call (missing the required ``fund_name``/``error``
    positionals and an unsupported ``message=`` kwarg) that raised a
    TypeError, silently swallowed by a bare ``except Exception: pass``,
    which left the job_executions row stuck in 'running' forever.

    Using ``autospec=True`` makes the mock enforce the real function
    signature, so this test fails loudly if the call shape regresses.
    """
    from web_dashboard.scheduler.jobs_newsletter import newsletter_ai_processing_job

    with patch("utils.job_tracking.get_running_ai_job", return_value=None), patch(
        "utils.job_tracking.mark_job_started"
    ) as mark_started, patch(
        "utils.job_tracking.mark_job_completed"
    ) as mark_completed, patch(
        "utils.job_tracking.mark_job_failed", autospec=True
    ) as mark_failed, patch(
        "web_dashboard.scheduler.jobs_newsletter.log_job_execution"
    ), patch(
        "newsletter_repository.NewsletterRepository", side_effect=RuntimeError("boom")
    ):
        newsletter_ai_processing_job()

    mark_started.assert_called_once()
    mark_failed.assert_called_once()
    mark_completed.assert_not_called()

    args, kwargs = mark_failed.call_args
    assert "message" not in kwargs
    assert args[0] == "newsletter_ai_processing"
    assert args[2] is None
    assert "boom" in args[3]


def test_market_research_marks_completed_when_searxng_unavailable():
    """SearXNG down is an intentional skip (usually test/config), not a failure.

    Matches alpha_research / opportunity_discovery / ticker_research doctrine.
    """
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
    mark_completed.assert_called_once()
    mark_failed.assert_not_called()


def test_performance_metrics_completes_each_date_in_range():
    """Multi-day backfill must pair mark_job_started per date.

    A prior bug only completed dates_to_process[-1], leaving N-1 rows stuck
    as status='running' after a range run.
    """
    from datetime import date

    from web_dashboard.scheduler.jobs_metrics import populate_performance_metrics_job

    d1 = date(2026, 7, 1)
    d2 = date(2026, 7, 2)
    d3 = date(2026, 7, 3)

    with patch("utils.job_tracking.mark_job_started") as mark_started, patch(
        "utils.job_tracking.mark_job_completed"
    ) as mark_completed, patch(
        "utils.job_tracking.mark_job_failed"
    ) as mark_failed, patch(
        "web_dashboard.scheduler.jobs_metrics.log_job_execution"
    ), patch(
        "supabase_client.SupabaseClient", return_value=MagicMock()
    ), patch(
        "web_dashboard.scheduler.jobs_metrics._process_performance_metrics_for_date",
        return_value=(1, 0, ["TEST"]),
    ), patch(
        "cache_version.bump_cache_version"
    ):
        populate_performance_metrics_job(from_date=d1, to_date=d3)

    assert mark_started.call_count == 3
    started_dates = [c.args[1] for c in mark_started.call_args_list]
    assert started_dates == [d1, d2, d3]

    assert mark_completed.call_count == 3
    completed_dates = [c.args[1] for c in mark_completed.call_args_list]
    assert completed_dates == [d1, d2, d3]

    mark_failed.assert_not_called()
