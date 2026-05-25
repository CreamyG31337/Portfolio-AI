"""Q4c: etf_group_analysis on ai_task_queue.

Mirror of ``tests/test_sector_meta_analysis_queue_mode.py`` for the ETF
group analysis scheduler job. Queue mode must:

- Use the legacy ``ai_analysis_queue`` discovery path
  (``queue_recent_missing_etf_analysis`` + ``get_pending_etf_analysis``) to
  find pending (ETF, date) pairs — the queue does NOT invent a new selection
  policy.
- Enqueue per-(ETF, date) tasks through ``enqueue_etf_group_analysis_tasks``
  without invoking the LLM inline.
- Forward each pending row's ``id`` to the worker via
  ``payload.legacy_queue_id`` so the worker can keep the legacy
  ``ai_analysis_queue.status`` in sync.
- Use the queue-managed bypass: ``get_running_ai_job`` is never consulted in
  queue mode (Q3 short-circuit).

Note (Q4c-specific): there is no separate per-(ETF, date) freshness gate
because the legacy discovery step already filters out pairs whose
``etf-analysis://`` article exists. Queue mode mirrors that behavior.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock


def _setup_common_patches(monkeypatch):
    """Patch the heavy dependencies shared by all queue-mode tests."""
    from web_dashboard.scheduler import jobs_etf_analysis as job_module

    monkeypatch.setattr(
        job_module, "SupabaseClient", lambda use_service_role=True: SimpleNamespace()
    )
    monkeypatch.setattr(job_module, "PostgresClient", lambda: SimpleNamespace())
    monkeypatch.setattr(
        job_module, "ResearchRepository", lambda postgres_client=None: SimpleNamespace()
    )
    monkeypatch.setattr(job_module, "log_job_execution", MagicMock())
    monkeypatch.setattr(job_module, "reset_stale_in_progress_queue", MagicMock(return_value=0))
    monkeypatch.setattr(
        job_module, "queue_recent_missing_etf_analysis", MagicMock(return_value=0)
    )
    monkeypatch.setattr(job_module, "get_etf_queue_lookback_days", lambda *a, **k: 14)
    return job_module


def test_etf_group_queue_mode_enqueues_pending_items(monkeypatch):
    """Queue mode mirrors the inline candidate selection: every row returned
    by ``get_pending_etf_analysis`` is enqueued (no per-target freshness gate),
    and each row's ``id`` is forwarded as ``legacy_queue_id`` so the worker
    can keep the legacy queue's status in sync."""
    job_module = _setup_common_patches(monkeypatch)

    pending_rows = [
        {"id": "queue-id-1", "target_key": "IWC_2026-05-23"},
        {"id": "queue-id-2", "target_key": "ARKK_2026-05-22"},
    ]
    monkeypatch.setattr(
        job_module, "get_pending_etf_analysis", MagicMock(return_value=pending_rows)
    )

    enqueue_calls = []

    def fake_enqueue(supabase, etf_groups, *, enqueued_by, max_attempts, queue_ids=None):
        enqueue_calls.append(
            (
                supabase,
                list(etf_groups),
                enqueued_by,
                max_attempts,
                dict(queue_ids or {}),
            )
        )
        return {
            "attempted": len(etf_groups),
            "enqueued": len(etf_groups),
            "failed": 0,
        }

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "etf_group_analysis")
    monkeypatch.setenv("AI_QUEUE_MAX_ATTEMPTS", "5")

    import scheduler.ai_task_workers as workers
    import utils.job_tracking as tracking

    monkeypatch.setattr(workers, "enqueue_etf_group_analysis_tasks", fake_enqueue)
    monkeypatch.setattr(tracking, "mark_job_started", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_completed", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_failed", MagicMock())
    # Queue mode must bypass the global AI lock entirely (Q3 contract).
    monkeypatch.setattr(
        tracking, "get_running_ai_job", MagicMock(side_effect=AssertionError)
    )

    job_module.etf_group_analysis_job()

    assert len(enqueue_calls) == 1
    _, groups_arg, enqueued_by, max_attempts, queue_id_map = enqueue_calls[0]

    # Order is preserved from get_pending_etf_analysis. ETF tickers are
    # uppercased; dates round-trip verbatim.
    assert [(t, d) for t, d, _p in groups_arg] == [
        ("IWC", "2026-05-23"),
        ("ARKK", "2026-05-22"),
    ]
    # All cron etf_group tasks use the low priority so any future manual
    # rebuild route (>= 1000) can jump ahead in the queue.
    assert all(p == job_module._ETF_GROUP_ENQUEUE_PRIORITY for _t, _d, p in groups_arg)
    assert enqueued_by == "cron"
    # max_attempts must come from AIQueueConfig.from_env (=5 above).
    assert max_attempts == 5
    # Each pending row's id is forwarded so the worker keeps the legacy
    # ai_analysis_queue row's status in sync.
    assert queue_id_map == {
        "IWC_2026-05-23": "queue-id-1",
        "ARKK_2026-05-22": "queue-id-2",
    }

    tracking.mark_job_started.assert_called_once()
    tracking.mark_job_completed.assert_called_once()
    tracking.mark_job_failed.assert_not_called()


def test_etf_group_queue_mode_caps_at_max_per_run(monkeypatch):
    """Even if the legacy discovery returns more than the cap, queue mode
    must enqueue at most ``_MAX_ETF_GROUPS_PER_RUN`` tasks per cron."""
    job_module = _setup_common_patches(monkeypatch)

    too_many = [
        {"id": f"q-{i}", "target_key": f"IWC_2026-05-{20 + i:02d}"}
        for i in range(20)
    ]
    monkeypatch.setattr(
        job_module, "get_pending_etf_analysis", MagicMock(return_value=too_many)
    )

    enqueue_calls = []

    def fake_enqueue(supabase, etf_groups, *, enqueued_by, max_attempts, queue_ids=None):
        enqueue_calls.append(list(etf_groups))
        return {
            "attempted": len(etf_groups),
            "enqueued": len(etf_groups),
            "failed": 0,
        }

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "etf_group_analysis")

    import scheduler.ai_task_workers as workers
    import utils.job_tracking as tracking

    monkeypatch.setattr(workers, "enqueue_etf_group_analysis_tasks", fake_enqueue)
    monkeypatch.setattr(tracking, "mark_job_started", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_completed", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_failed", MagicMock())
    monkeypatch.setattr(
        tracking, "get_running_ai_job", MagicMock(side_effect=AssertionError)
    )

    job_module.etf_group_analysis_job()

    assert len(enqueue_calls) == 1
    enqueued = enqueue_calls[0]
    assert len(enqueued) == job_module._MAX_ETF_GROUPS_PER_RUN
    # Cap takes the first N (insertion order) — get_pending_etf_analysis is
    # already ordered by holdings date desc.
    assert [(t, d) for t, d, _p in enqueued] == [
        (item["target_key"].split("_", 1)[0], item["target_key"].split("_", 1)[1])
        for item in too_many[: job_module._MAX_ETF_GROUPS_PER_RUN]
    ]


def test_etf_group_queue_mode_marks_done_when_no_candidates(monkeypatch):
    """When the legacy discovery returns nothing, the cron must complete
    successfully with 0 enqueued (not fail, not error)."""
    job_module = _setup_common_patches(monkeypatch)

    monkeypatch.setattr(
        job_module, "get_pending_etf_analysis", MagicMock(return_value=[])
    )

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "etf_group_analysis")

    import scheduler.ai_task_workers as workers
    import utils.job_tracking as tracking

    enqueue_mock = MagicMock(side_effect=AssertionError("must not enqueue when nothing selected"))
    monkeypatch.setattr(workers, "enqueue_etf_group_analysis_tasks", enqueue_mock)
    monkeypatch.setattr(tracking, "mark_job_started", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_completed", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_failed", MagicMock())
    monkeypatch.setattr(
        tracking, "get_running_ai_job", MagicMock(side_effect=AssertionError)
    )

    job_module.etf_group_analysis_job()

    enqueue_mock.assert_not_called()
    tracking.mark_job_completed.assert_called_once()
    tracking.mark_job_failed.assert_not_called()


def test_etf_group_queue_mode_skips_invalid_target_keys(monkeypatch):
    """A row whose target_key cannot be split into ETF + date must be
    skipped (logged + dropped), not enqueued and not crash the cron."""
    job_module = _setup_common_patches(monkeypatch)

    # First row is malformed (no underscore); second is valid.
    pending_rows = [
        {"id": "q-bad", "target_key": "MALFORMED"},
        {"id": "q-good", "target_key": "IWC_2026-05-23"},
    ]
    monkeypatch.setattr(
        job_module, "get_pending_etf_analysis", MagicMock(return_value=pending_rows)
    )

    enqueue_calls = []

    def fake_enqueue(supabase, etf_groups, *, enqueued_by, max_attempts, queue_ids=None):
        enqueue_calls.append(list(etf_groups))
        return {
            "attempted": len(etf_groups),
            "enqueued": len(etf_groups),
            "failed": 0,
        }

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "etf_group_analysis")

    import scheduler.ai_task_workers as workers
    import utils.job_tracking as tracking

    monkeypatch.setattr(workers, "enqueue_etf_group_analysis_tasks", fake_enqueue)
    monkeypatch.setattr(tracking, "mark_job_started", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_completed", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_failed", MagicMock())
    monkeypatch.setattr(
        tracking, "get_running_ai_job", MagicMock(side_effect=AssertionError)
    )

    job_module.etf_group_analysis_job()

    assert len(enqueue_calls) == 1
    # Only the valid row gets enqueued.
    assert [(t, d) for t, d, _p in enqueue_calls[0]] == [("IWC", "2026-05-23")]


def test_legacy_mode_unchanged_when_queue_disabled(monkeypatch):
    """When ``AI_QUEUE_JOBS`` does not include ``etf_group_analysis``, the
    legacy inline path must still call ``analyze_group`` per pending item."""
    job_module = _setup_common_patches(monkeypatch)

    pending_rows = [{"id": "q-1", "target_key": "IWC_2026-05-23"}]
    monkeypatch.setattr(
        job_module, "get_pending_etf_analysis", MagicMock(return_value=pending_rows)
    )

    fake_service = MagicMock()
    fake_service.analyze_group.return_value = {"summary": "ok"}
    monkeypatch.setattr(job_module, "ETFGroupAnalysisService", lambda *args: fake_service)
    monkeypatch.setattr(job_module, "get_ollama_client", lambda: SimpleNamespace())
    monkeypatch.setattr(job_module, "mark_analysis_started", MagicMock())
    monkeypatch.setattr(job_module, "mark_analysis_completed", MagicMock())
    monkeypatch.setattr(job_module, "mark_analysis_failed", MagicMock())

    # Queue mode OFF: only ticker_analysis is queue-managed, not etf_group.
    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "ticker_analysis")

    import utils.job_tracking as tracking

    monkeypatch.setattr(tracking, "mark_job_started", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_completed", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_failed", MagicMock())
    # Legacy path still consults get_running_ai_job; return None (no lock).
    monkeypatch.setattr(tracking, "get_running_ai_job", MagicMock(return_value=None))
    monkeypatch.setattr(tracking, "log_job_step", MagicMock())

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

    job_module.etf_group_analysis_job()

    # Legacy path must run the LLM inline for the candidate.
    fake_service.analyze_group.assert_called_once()
    args, kwargs = fake_service.analyze_group.call_args
    assert args[0] == "IWC"
    # Legacy path does not pin the model_chain_override — preserves multi-model
    # fallback for non-queue callers (this is the Q4a/Q4b/Q4c contract).
    assert "model_chain_override" not in kwargs
