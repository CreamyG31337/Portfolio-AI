"""Q4 first migration: ticker_meta_analysis on ai_task_queue.

Mirror of ``tests/test_ticker_analysis_queue_mode.py`` for the meta analysis
scheduler job. Queue mode must:

- Select candidates via ``TickerMetaAnalysisService.fetch_standard_ticker_candidates``.
- Skip tickers whose digest is still fresh (``needs_refresh`` returns False)
  so cron does not enqueue immediate no-ops.
- Enqueue per-ticker tasks through ``enqueue_ticker_meta_analysis_tasks``
  without invoking the LLM inline.
- Use the queue-managed bypass: ``get_running_ai_job`` is never consulted in
  queue mode (Q3 short-circuit).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock


def _setup_common_patches(monkeypatch):
    """Patch the heavy dependencies shared by both queue-mode tests."""
    from web_dashboard.scheduler import jobs_ticker_meta_analysis as job_module

    monkeypatch.setattr(
        job_module, "SupabaseClient", lambda use_service_role=True: SimpleNamespace()
    )
    monkeypatch.setattr(job_module, "PostgresClient", lambda: SimpleNamespace())
    monkeypatch.setattr(job_module, "log_job_execution", MagicMock())
    return job_module


def test_meta_queue_mode_enqueues_only_tickers_that_need_refresh(monkeypatch):
    job_module = _setup_common_patches(monkeypatch)

    fake_service = MagicMock()
    fake_service.fetch_standard_ticker_candidates.return_value = [
        "AAPL",
        "MSFT",
        "GOOG",
        "TSLA",
    ]
    # AAPL: needs refresh; MSFT: fresh; GOOG: no standard analysis; TSLA: needs.
    needs_map = {
        "AAPL": (True, {"id": "p1"}),
        "MSFT": (False, {"id": "p2"}),
        "GOOG": (False, None),
        "TSLA": (True, {"id": "p4"}),
    }
    fake_service.needs_refresh.side_effect = lambda t: needs_map[t]

    monkeypatch.setattr(job_module, "TickerMetaAnalysisService", lambda *args: fake_service)

    enqueue_calls = []

    def fake_enqueue(supabase, tickers, *, enqueued_by, max_attempts):
        enqueue_calls.append((supabase, list(tickers), enqueued_by, max_attempts))
        return {"attempted": len(tickers), "enqueued": len(tickers), "failed": 0}

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "ticker_meta_analysis")
    monkeypatch.setenv("AI_QUEUE_MAX_ATTEMPTS", "4")

    import scheduler.ai_task_workers as workers
    import utils.job_tracking as tracking

    monkeypatch.setattr(workers, "enqueue_ticker_meta_analysis_tasks", fake_enqueue)
    monkeypatch.setattr(tracking, "mark_job_started", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_completed", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_failed", MagicMock())
    # Queue mode must bypass the global AI lock entirely (Q3 contract).
    monkeypatch.setattr(
        tracking, "get_running_ai_job", MagicMock(side_effect=AssertionError)
    )

    job_module.ticker_meta_analysis_job()

    # Service.run_meta_analysis must NOT be called in queue mode — the worker
    # owns the LLM call now.
    fake_service.run_meta_analysis.assert_not_called()

    assert len(enqueue_calls) == 1
    _, tickers_arg, enqueued_by, max_attempts = enqueue_calls[0]
    # Only AAPL and TSLA — MSFT (fresh) and GOOG (no standard) are filtered.
    assert [t for t, _p in tickers_arg] == ["AAPL", "TSLA"]
    # All cron meta tasks use the low priority so manual UI requests (>=1000)
    # can jump ahead in the queue.
    assert all(p == job_module._META_ENQUEUE_PRIORITY for _t, p in tickers_arg)
    assert enqueued_by == "cron"
    assert max_attempts == 4

    tracking.mark_job_started.assert_called_once()
    tracking.mark_job_completed.assert_called_once()
    tracking.mark_job_failed.assert_not_called()


def test_meta_queue_mode_marks_done_when_no_candidates(monkeypatch):
    """When every candidate is fresh / has no standard analysis, the cron
    must complete successfully with 0 enqueued (not fail, not error)."""
    job_module = _setup_common_patches(monkeypatch)

    fake_service = MagicMock()
    fake_service.fetch_standard_ticker_candidates.return_value = ["AAPL", "MSFT"]
    # Both fresh.
    fake_service.needs_refresh.side_effect = lambda t: (False, {"id": "p"})

    monkeypatch.setattr(job_module, "TickerMetaAnalysisService", lambda *args: fake_service)

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "ticker_meta_analysis")

    import scheduler.ai_task_workers as workers
    import utils.job_tracking as tracking

    enqueue_mock = MagicMock(side_effect=AssertionError("must not enqueue when nothing selected"))
    monkeypatch.setattr(workers, "enqueue_ticker_meta_analysis_tasks", enqueue_mock)
    monkeypatch.setattr(tracking, "mark_job_started", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_completed", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_failed", MagicMock())
    monkeypatch.setattr(
        tracking, "get_running_ai_job", MagicMock(side_effect=AssertionError)
    )

    job_module.ticker_meta_analysis_job()

    enqueue_mock.assert_not_called()
    tracking.mark_job_completed.assert_called_once()
    tracking.mark_job_failed.assert_not_called()


def test_legacy_mode_unchanged_when_queue_disabled(monkeypatch):
    """When ``AI_QUEUE_JOBS`` does not include ``ticker_meta_analysis``, the
    legacy inline path must still call ``run_meta_analysis`` per ticker."""
    job_module = _setup_common_patches(monkeypatch)

    fake_service = MagicMock()
    fake_service.fetch_standard_ticker_candidates.return_value = ["AAPL"]
    fake_service.needs_refresh.return_value = (True, {"id": "p1"})
    fake_service.run_meta_analysis.return_value = {"ticker": "AAPL"}

    monkeypatch.setattr(job_module, "TickerMetaAnalysisService", lambda *args: fake_service)
    monkeypatch.setattr(job_module, "get_ollama_client", lambda: SimpleNamespace())
    monkeypatch.setattr(job_module, "OllamaClient", lambda: SimpleNamespace())
    monkeypatch.setattr(job_module, "get_summarizing_model", lambda key: "qwen3.6:27b")

    # Queue mode OFF: only ticker_analysis is queue-managed, not meta.
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

    job_module.ticker_meta_analysis_job()

    # Legacy path must run the LLM inline for the candidate.
    fake_service.run_meta_analysis.assert_called_once()
    call = fake_service.run_meta_analysis.call_args
    assert call.args[0] == "AAPL"
    assert call.kwargs.get("force") is True
