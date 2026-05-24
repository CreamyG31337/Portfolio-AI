"""Unit tests for Q3 of the AI task queue roadmap (2026-05-23).

These cover ``is_queue_managed_job`` (the single source of truth for "is this
job routed through the AI task queue?") and the bypass behavior baked into
``get_running_ai_job`` so queue-managed jobs no longer wait on the global AI
mutex held by unrelated long-running jobs (e.g. a hung ``alpha_research``).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# is_queue_managed_job
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enabled_value", "jobs_value", "job_id", "expected"),
    [
        # Disabled flag short-circuits even when job is listed.
        ("false", "ticker_analysis", "ticker_analysis", False),
        ("0", "ticker_analysis", "ticker_analysis", False),
        ("", "ticker_analysis", "ticker_analysis", False),
        # Enabled + listed → True. Accept multiple truthy spellings.
        ("true", "ticker_analysis", "ticker_analysis", True),
        ("TRUE", "ticker_analysis", "ticker_analysis", True),
        ("1", "ticker_analysis", "ticker_analysis", True),
        ("yes", "ticker_analysis", "ticker_analysis", True),
        ("on", "ticker_analysis", "ticker_analysis", True),
        ("  True  ", "ticker_analysis", "ticker_analysis", True),
        # CSV with whitespace + multiple entries.
        ("true", "ticker_analysis, ticker_meta_analysis", "ticker_meta_analysis", True),
        ("true", "ticker_analysis,ticker_meta_analysis", "ticker_meta_analysis", True),
        ("true", " ticker_analysis , ticker_meta_analysis ", "ticker_analysis", True),
        ("true", "ticker_analysis,,ticker_meta_analysis", "ticker_meta_analysis", True),
        # Enabled but not listed → False (the safety case Q3 still preserves).
        ("true", "ticker_analysis", "alpha_research", False),
        ("true", "", "ticker_analysis", False),
        # Job name normalization: caller may pass extra whitespace.
        ("true", "ticker_analysis", "  ticker_analysis  ", True),
        # Case-sensitive job name matching (matches AIQueueConfig.from_env).
        ("true", "ticker_analysis", "Ticker_Analysis", False),
        # Empty / None job id is never queue-managed.
        ("true", "ticker_analysis", "", False),
        ("true", "ticker_analysis", "   ", False),
    ],
)
def test_is_queue_managed_job(monkeypatch, enabled_value, jobs_value, job_id, expected):
    from utils.job_tracking import is_queue_managed_job

    monkeypatch.setenv("AI_QUEUE_ENABLED", enabled_value)
    monkeypatch.setenv("AI_QUEUE_JOBS", jobs_value)
    assert is_queue_managed_job(job_id) is expected


def test_is_queue_managed_job_none_input(monkeypatch):
    from utils.job_tracking import is_queue_managed_job

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "ticker_analysis")
    assert is_queue_managed_job(None) is False


def test_is_queue_managed_job_missing_env_vars(monkeypatch):
    from utils.job_tracking import is_queue_managed_job

    monkeypatch.delenv("AI_QUEUE_ENABLED", raising=False)
    monkeypatch.delenv("AI_QUEUE_JOBS", raising=False)
    assert is_queue_managed_job("ticker_analysis") is False


# ---------------------------------------------------------------------------
# Parsing equivalence: utils helper must agree with AIQueueConfig.from_env
# so the single env var (`AI_QUEUE_JOBS`) controls both worker activation and
# global-lock bypass. If a future refactor changes one parsing path, this
# test fails first.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enabled_value", "jobs_value", "probe_jobs"),
    [
        ("true", "ticker_analysis", ["ticker_analysis", "alpha_research"]),
        ("True", " ticker_analysis , ticker_meta_analysis ",
         ["ticker_analysis", "ticker_meta_analysis", "sector_meta_analysis"]),
        ("0", "ticker_analysis", ["ticker_analysis"]),
        ("yes", "a,b,,c", ["a", "b", "c", "d"]),
        ("", "", ["ticker_analysis"]),
    ],
)
def test_is_queue_managed_job_matches_ai_queue_config(
    monkeypatch, enabled_value, jobs_value, probe_jobs
):
    from utils.job_tracking import is_queue_managed_job
    from scheduler.ai_task_workers import AIQueueConfig, is_ai_queue_job_enabled

    monkeypatch.setenv("AI_QUEUE_ENABLED", enabled_value)
    monkeypatch.setenv("AI_QUEUE_JOBS", jobs_value)

    # Snapshot the worker-pool view.
    cfg = AIQueueConfig.from_env()

    for job in probe_jobs:
        helper_result = is_queue_managed_job(job)
        worker_result = is_ai_queue_job_enabled(job, cfg)
        assert helper_result == worker_result, (
            f"Disagreement for job={job!r} with AI_QUEUE_ENABLED={enabled_value!r}, "
            f"AI_QUEUE_JOBS={jobs_value!r}: utils={helper_result}, worker={worker_result}"
        )


# ---------------------------------------------------------------------------
# get_running_ai_job bypass for queue-managed jobs
# ---------------------------------------------------------------------------


def test_get_running_ai_job_short_circuits_for_queue_managed(monkeypatch):
    """The 2026-05-22 incident scenario: alpha_research holds the global AI
    lock but ticker_analysis (queue-managed) should NOT skip its cron.
    """
    import utils.job_tracking as tracking

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "ticker_analysis")

    # If supabase_client were actually consulted, it would be a bug — the
    # short-circuit must happen before any DB call.
    sentinel = MagicMock(side_effect=AssertionError("supabase must not be queried"))
    with patch.object(tracking, "logger") as mock_logger:
        with patch("supabase_client.SupabaseClient", sentinel):
            result = tracking.get_running_ai_job(exclude_job_name="ticker_analysis")

    assert result is None
    sentinel.assert_not_called()
    # We log at debug level so ops can grep the bypass if needed.
    assert any(
        "queue-managed" in str(call.args[0])
        for call in mock_logger.debug.call_args_list
    )


def test_get_running_ai_job_still_checks_for_non_queue_jobs(monkeypatch):
    """ticker_meta_analysis (not in AI_QUEUE_JOBS yet) should still see the
    alpha_research lock and skip."""
    import utils.job_tracking as tracking

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "ticker_analysis")  # NOT ticker_meta_analysis

    fake_supabase = MagicMock()
    # Simulate alpha_research being the lock holder (recent started_at).
    from datetime import UTC, datetime
    started_iso = datetime.now(UTC).isoformat()
    fake_supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = [
        {
            "id": "fake-id",
            "job_name": "alpha_research",
            "started_at": started_iso,
            "completed_at": None,
        }
    ]
    fake_client = MagicMock(supabase=fake_supabase)

    with patch("supabase_client.SupabaseClient", return_value=fake_client):
        result = tracking.get_running_ai_job(exclude_job_name="ticker_meta_analysis")

    assert result == "alpha_research"


def test_get_running_ai_job_bypass_can_be_disabled(monkeypatch):
    """Admin display / diagnostics may want raw lock state; opt-out flag
    keeps that behavior available."""
    import utils.job_tracking as tracking

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "ticker_analysis")

    from datetime import UTC, datetime
    fake_supabase = MagicMock()
    fake_supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = [
        {
            "id": "fake-id",
            "job_name": "alpha_research",
            "started_at": datetime.now(UTC).isoformat(),
            "completed_at": None,
        }
    ]
    fake_client = MagicMock(supabase=fake_supabase)

    with patch("supabase_client.SupabaseClient", return_value=fake_client):
        result = tracking.get_running_ai_job(
            exclude_job_name="ticker_analysis",
            ignore_for_queue_managed=False,
        )

    assert result == "alpha_research"


def test_get_running_ai_job_no_exclude_still_queries(monkeypatch):
    """The admin "what's currently running" view passes no exclude_job_name;
    bypass must not fire in that case."""
    import utils.job_tracking as tracking

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "ticker_analysis")

    from datetime import UTC, datetime
    fake_supabase = MagicMock()
    fake_supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = [
        {
            "id": "fake-id",
            "job_name": "ticker_analysis",
            "started_at": datetime.now(UTC).isoformat(),
            "completed_at": None,
        }
    ]
    fake_client = MagicMock(supabase=fake_supabase)

    with patch("supabase_client.SupabaseClient", return_value=fake_client):
        result = tracking.get_running_ai_job()  # no exclude_job_name

    assert result == "ticker_analysis"
