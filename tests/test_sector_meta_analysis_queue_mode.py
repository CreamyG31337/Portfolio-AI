"""Q4b: sector_meta_analysis on ai_task_queue.

Mirror of ``tests/test_ticker_meta_analysis_queue_mode.py`` for the sector
meta analysis scheduler job. Queue mode must:

- Select sector candidates via ``SectorMetaAnalysisService.list_sector_keys``.
- Enqueue per-sector tasks through ``enqueue_sector_meta_analysis_tasks``
  without invoking the LLM inline.
- Use the queue-managed bypass: ``get_running_ai_job`` is never consulted in
  queue mode (Q3 short-circuit).
- Continue to honor ``is_meta_analysis_phase3_sector_enabled`` so the cron
  is a no-op when the phase flag is off (matches legacy inline behavior).

Note (Q4b-specific): there is **no per-sector ``needs_refresh`` freshness
gate** because the inline path does not have one — sector meta upserts on
``(sector, run_date)`` so re-running is idempotent. Queue mode mirrors that
behavior. Per-sector freshness can be added later without breaking the
worker contract.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock


def _setup_common_patches(monkeypatch):
    """Patch the heavy dependencies shared by all queue-mode tests."""
    from web_dashboard.scheduler import jobs_sector_meta_analysis as job_module

    monkeypatch.setattr(
        job_module, "SupabaseClient", lambda use_service_role=True: SimpleNamespace()
    )
    monkeypatch.setattr(job_module, "PostgresClient", lambda: SimpleNamespace())
    monkeypatch.setattr(job_module, "log_job_execution", MagicMock())
    monkeypatch.setattr(job_module, "is_meta_analysis_phase3_sector_enabled", lambda: True)
    return job_module


def test_sector_meta_queue_mode_enqueues_all_returned_sectors(monkeypatch):
    """Queue mode mirrors the inline candidate selection: every sector
    returned by ``list_sector_keys`` is enqueued (no per-sector freshness
    gate), capped at ``_MAX_SECTORS_PER_RUN`` defensively."""
    job_module = _setup_common_patches(monkeypatch)

    fake_service = MagicMock()
    fake_service.list_sector_keys.return_value = [
        "Technology",
        "Energy",
        "Financials",
        "__UNTAGGED__",
    ]

    monkeypatch.setattr(job_module, "SectorMetaAnalysisService", lambda *args: fake_service)

    enqueue_calls = []

    def fake_enqueue(supabase, sectors, *, enqueued_by, max_attempts):
        enqueue_calls.append((supabase, list(sectors), enqueued_by, max_attempts))
        return {"attempted": len(sectors), "enqueued": len(sectors), "failed": 0}

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "sector_meta_analysis")
    monkeypatch.setenv("AI_QUEUE_MAX_ATTEMPTS", "5")

    import scheduler.ai_task_workers as workers
    import utils.job_tracking as tracking

    monkeypatch.setattr(workers, "enqueue_sector_meta_analysis_tasks", fake_enqueue)
    monkeypatch.setattr(tracking, "mark_job_started", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_completed", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_failed", MagicMock())
    # Queue mode must bypass the global AI lock entirely (Q3 contract).
    monkeypatch.setattr(
        tracking, "get_running_ai_job", MagicMock(side_effect=AssertionError)
    )

    job_module.sector_meta_analysis_job()

    # Service.run_sector_meta must NOT be called in queue mode — the worker
    # owns the LLM call now.
    fake_service.run_sector_meta.assert_not_called()

    assert len(enqueue_calls) == 1
    _, sectors_arg, enqueued_by, max_attempts = enqueue_calls[0]
    assert [s for s, _p in sectors_arg] == [
        "Technology",
        "Energy",
        "Financials",
        "__UNTAGGED__",
    ]
    # All cron sector meta tasks use the low priority so any future manual UI
    # requests (>= 1000) can jump ahead in the queue.
    assert all(p == job_module._SECTOR_META_ENQUEUE_PRIORITY for _s, p in sectors_arg)
    assert enqueued_by == "cron"
    # max_attempts must come from AIQueueConfig.from_env (=5 above).
    assert max_attempts == 5

    tracking.mark_job_started.assert_called_once()
    tracking.mark_job_completed.assert_called_once()
    tracking.mark_job_failed.assert_not_called()


def test_sector_meta_queue_mode_caps_at_max_sectors_per_run(monkeypatch):
    """Even if ``list_sector_keys`` returns more than the cap, queue mode
    must enqueue at most ``_MAX_SECTORS_PER_RUN`` tasks."""
    job_module = _setup_common_patches(monkeypatch)

    # Way more than the cap (which is 18).
    too_many = [f"Sector{i}" for i in range(40)]
    fake_service = MagicMock()
    fake_service.list_sector_keys.return_value = too_many

    monkeypatch.setattr(job_module, "SectorMetaAnalysisService", lambda *args: fake_service)

    enqueue_calls = []

    def fake_enqueue(supabase, sectors, *, enqueued_by, max_attempts):
        enqueue_calls.append(list(sectors))
        return {"attempted": len(sectors), "enqueued": len(sectors), "failed": 0}

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "sector_meta_analysis")

    import scheduler.ai_task_workers as workers
    import utils.job_tracking as tracking

    monkeypatch.setattr(workers, "enqueue_sector_meta_analysis_tasks", fake_enqueue)
    monkeypatch.setattr(tracking, "mark_job_started", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_completed", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_failed", MagicMock())
    monkeypatch.setattr(
        tracking, "get_running_ai_job", MagicMock(side_effect=AssertionError)
    )

    job_module.sector_meta_analysis_job()

    assert len(enqueue_calls) == 1
    enqueued = enqueue_calls[0]
    assert len(enqueued) == job_module._MAX_SECTORS_PER_RUN
    # Cap takes the first N (insertion order) — list_sector_keys is already
    # ordered by recent activity.
    assert [s for s, _p in enqueued] == too_many[: job_module._MAX_SECTORS_PER_RUN]


def test_sector_meta_queue_mode_marks_done_when_no_candidates(monkeypatch):
    """When ``list_sector_keys`` returns nothing, the cron must complete
    successfully with 0 enqueued (not fail, not error)."""
    job_module = _setup_common_patches(monkeypatch)

    fake_service = MagicMock()
    fake_service.list_sector_keys.return_value = []

    monkeypatch.setattr(job_module, "SectorMetaAnalysisService", lambda *args: fake_service)

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "sector_meta_analysis")

    import scheduler.ai_task_workers as workers
    import utils.job_tracking as tracking

    enqueue_mock = MagicMock(side_effect=AssertionError("must not enqueue when nothing selected"))
    monkeypatch.setattr(workers, "enqueue_sector_meta_analysis_tasks", enqueue_mock)
    monkeypatch.setattr(tracking, "mark_job_started", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_completed", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_failed", MagicMock())
    monkeypatch.setattr(
        tracking, "get_running_ai_job", MagicMock(side_effect=AssertionError)
    )

    job_module.sector_meta_analysis_job()

    enqueue_mock.assert_not_called()
    tracking.mark_job_completed.assert_called_once()
    tracking.mark_job_failed.assert_not_called()


def test_sector_meta_phase_flag_off_short_circuits_before_queue_mode(monkeypatch):
    """When ``META_ANALYSIS_PHASE3_SECTOR`` is disabled, the queue-mode branch
    must NOT run — the cron remains a no-op identical to the legacy path."""
    job_module = _setup_common_patches(monkeypatch)
    # Override phase flag to disabled.
    monkeypatch.setattr(job_module, "is_meta_analysis_phase3_sector_enabled", lambda: False)

    fake_service = MagicMock()
    monkeypatch.setattr(job_module, "SectorMetaAnalysisService", lambda *args: fake_service)

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "sector_meta_analysis")

    import scheduler.ai_task_workers as workers
    import utils.job_tracking as tracking

    enqueue_mock = MagicMock(side_effect=AssertionError("queue mode must not run when phase off"))
    monkeypatch.setattr(workers, "enqueue_sector_meta_analysis_tasks", enqueue_mock)
    monkeypatch.setattr(tracking, "mark_job_started", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_completed", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_failed", MagicMock())

    job_module.sector_meta_analysis_job()

    enqueue_mock.assert_not_called()
    fake_service.list_sector_keys.assert_not_called()


def test_legacy_mode_unchanged_when_queue_disabled(monkeypatch):
    """When ``AI_QUEUE_JOBS`` does not include ``sector_meta_analysis``, the
    legacy inline path must still call ``run_sector_meta`` per sector."""
    job_module = _setup_common_patches(monkeypatch)

    fake_service = MagicMock()
    fake_service.list_sector_keys.return_value = ["Technology"]
    fake_service.run_sector_meta.return_value = {"sector": "Technology"}

    monkeypatch.setattr(job_module, "SectorMetaAnalysisService", lambda *args: fake_service)
    monkeypatch.setattr(job_module, "get_ollama_client", lambda: SimpleNamespace())
    monkeypatch.setattr(job_module, "OllamaClient", lambda: SimpleNamespace())
    monkeypatch.setattr(job_module, "get_summarizing_model", lambda key: "qwen3.6:27b")

    # Queue mode OFF: only ticker_analysis is queue-managed, not sector meta.
    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "ticker_analysis")

    import utils.job_tracking as tracking

    monkeypatch.setattr(tracking, "mark_job_started", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_completed", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_failed", MagicMock())
    # Legacy path still consults get_running_ai_job; return None (no lock).
    monkeypatch.setattr(tracking, "get_running_ai_job", MagicMock(return_value=None))

    # Stub the supabase running-check ("is this job already running?") so the
    # legacy path proceeds past the dedupe guard.
    class _RunningCheck:
        @property
        def data(self):
            return []

    class _Table:
        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def execute(self):
            return _RunningCheck()

    class _SB:
        def __init__(self, *a, **k):
            self.supabase = SimpleNamespace(table=lambda name: _Table())

    monkeypatch.setattr(job_module, "SupabaseClient", _SB)

    job_module.sector_meta_analysis_job()

    # Legacy path must run the LLM inline for the candidate.
    fake_service.run_sector_meta.assert_called_once()
    call = fake_service.run_sector_meta.call_args
    assert call.args[0] == "Technology"
    assert call.kwargs.get("model_override") == "qwen3.6:27b"
