from types import SimpleNamespace

import pytest

from web_dashboard.scheduler.ai_task_workers import (
    AIQueueConfig,
    AIQueueWorkerPool,
    QUEUE_JOB_SECTOR_META_ANALYSIS,
    QUEUE_JOB_TICKER_ANALYSIS,
    QUEUE_JOB_TICKER_META_ANALYSIS,
    ERROR_HOST_BUSY,
    ERROR_RATE_LIMITED,
    ERROR_TIMEOUT_GLM,
    ERROR_UNSUPPORTED_TASK,
    UnsupportedTaskError,
    build_task_handlers,
    classify_error,
    enqueue_sector_meta_analysis_tasks,
    enqueue_ticker_analysis_tasks,
    enqueue_ticker_meta_analysis_tasks,
    model_for_backend,
    ollama_base_url_for_backend,
    retry_delay_seconds,
    sector_meta_analysis_task_handler,
    should_increment_attempts,
    ticker_meta_analysis_task_handler,
)


class FakeSupabase:
    def __init__(self):
        self.calls = []

    def rpc(self, function_name, payload):
        self.calls.append((function_name, payload))
        return self

    def execute(self):
        return SimpleNamespace(data=[])


def test_ai_queue_config_from_env_parses_worker_counts_and_jobs():
    config = AIQueueConfig.from_env(
        {
            "AI_QUEUE_ENABLED": "true",
            "AI_QUEUE_JOBS": "ticker_analysis, ticker_meta_analysis",
            "AI_QUEUE_WORKERS_OLLAMA_PRIMARY": "2",
            "AI_QUEUE_WORKERS_OLLAMA_SECONDARY": "0",
            "AI_QUEUE_WORKERS_GLM": "4",
            "AI_QUEUE_LEASE_TTL_SEC": "120",
            "AI_QUEUE_HEARTBEAT_SEC": "15",
        }
    )

    assert config.enabled is True
    assert config.enabled_jobs == ("ticker_analysis", "ticker_meta_analysis")
    assert config.worker_counts["ollama_primary"] == 2
    assert config.worker_counts["ollama_secondary"] == 0
    assert config.worker_counts["glm"] == 4
    assert config.lease_ttl_sec == 120
    assert config.heartbeat_sec == 15


def test_worker_pool_does_not_start_without_registered_handlers():
    config = AIQueueConfig.from_env(
        {
            "AI_QUEUE_ENABLED": "true",
            "AI_QUEUE_JOBS": "ticker_analysis",
            "AI_QUEUE_WORKERS_OLLAMA_PRIMARY": "1",
            "AI_QUEUE_WORKERS_OLLAMA_SECONDARY": "0",
            "AI_QUEUE_WORKERS_GLM": "0",
        }
    )
    pool = AIQueueWorkerPool(config, handlers={})

    assert pool.start() is False
    assert pool.running is False


def test_lease_one_uses_backend_and_enabled_analysis_types():
    fake = SimpleNamespace(supabase=FakeSupabase())
    config = AIQueueConfig.from_env(
        {
            "AI_QUEUE_ENABLED": "true",
            "AI_QUEUE_JOBS": "ticker_analysis",
        }
    )
    pool = AIQueueWorkerPool(config)

    task = pool._lease_one(fake, "worker-1", "glm", ["ticker_analysis"])

    assert task is None
    assert fake.supabase.calls == [
        (
            "lease_ai_task",
            {
                "p_worker_id": "worker-1",
                "p_backend": "glm",
                "p_analysis_types": ["ticker_analysis"],
                "p_lease_seconds": 90,
            },
        )
    ]


def test_classify_error_matches_fallback_taxonomy():
    assert classify_error(UnsupportedTaskError("missing")) == ERROR_UNSUPPORTED_TASK
    assert classify_error(RuntimeError("hosts busy for model")) == ERROR_HOST_BUSY
    assert classify_error(RuntimeError("HTTP 429 rate limit")) == ERROR_RATE_LIMITED
    assert classify_error(TimeoutError("Z.AI timed out"), backend="glm") == ERROR_TIMEOUT_GLM


def test_host_busy_does_not_increment_attempts_but_rate_limit_backs_off():
    assert should_increment_attempts(ERROR_HOST_BUSY) is False
    assert should_increment_attempts(ERROR_RATE_LIMITED) is True
    assert retry_delay_seconds(ERROR_RATE_LIMITED, attempts=2, base_delay_sec=30) == 120


def test_build_task_handlers_registers_ticker_analysis_only_when_enabled():
    assert build_task_handlers([]) == {}
    handlers = build_task_handlers([QUEUE_JOB_TICKER_ANALYSIS])

    assert list(handlers) == [QUEUE_JOB_TICKER_ANALYSIS]


def test_build_task_handlers_registers_ticker_meta_analysis_when_enabled():
    handlers = build_task_handlers([QUEUE_JOB_TICKER_META_ANALYSIS])

    assert list(handlers) == [QUEUE_JOB_TICKER_META_ANALYSIS]
    assert handlers[QUEUE_JOB_TICKER_META_ANALYSIS] is ticker_meta_analysis_task_handler


def test_build_task_handlers_registers_both_when_both_enabled():
    handlers = build_task_handlers(
        [QUEUE_JOB_TICKER_ANALYSIS, QUEUE_JOB_TICKER_META_ANALYSIS]
    )

    assert set(handlers) == {
        QUEUE_JOB_TICKER_ANALYSIS,
        QUEUE_JOB_TICKER_META_ANALYSIS,
    }
    assert handlers[QUEUE_JOB_TICKER_META_ANALYSIS] is ticker_meta_analysis_task_handler


def test_enqueue_ticker_analysis_tasks_uses_enqueue_rpc_payload():
    fake = SimpleNamespace(supabase=FakeSupabase())

    stats = enqueue_ticker_analysis_tasks(
        fake,
        [("aapl", 1000), ("msft", 100)],
        enqueued_by="manual",
        max_attempts=4,
    )

    assert stats == {"attempted": 2, "enqueued": 2, "failed": 0}
    assert [call[0] for call in fake.supabase.calls] == ["enqueue_ai_task", "enqueue_ai_task"]
    assert fake.supabase.calls[0][1] == {
        "p_analysis_type": "ticker_analysis",
        "p_target_key": "AAPL",
        "p_payload": {"ticker": "AAPL", "priority": 1000, "manual_request": True},
        "p_priority": 1000,
        "p_enqueued_by": "manual",
        "p_max_attempts": 4,
    }


def test_enqueue_ticker_meta_analysis_tasks_uses_enqueue_rpc_payload():
    fake = SimpleNamespace(supabase=FakeSupabase())

    stats = enqueue_ticker_meta_analysis_tasks(
        fake,
        [("nvda", 10), ("amat", 1000)],
        enqueued_by="cron",
        max_attempts=3,
    )

    assert stats == {"attempted": 2, "enqueued": 2, "failed": 0}
    assert [call[0] for call in fake.supabase.calls] == [
        "enqueue_ai_task",
        "enqueue_ai_task",
    ]
    assert fake.supabase.calls[0][1] == {
        "p_analysis_type": "ticker_meta_analysis",
        "p_target_key": "NVDA",
        "p_payload": {"ticker": "NVDA", "priority": 10, "manual_request": False},
        "p_priority": 10,
        "p_enqueued_by": "cron",
        "p_max_attempts": 3,
    }
    assert fake.supabase.calls[1][1] == {
        "p_analysis_type": "ticker_meta_analysis",
        "p_target_key": "AMAT",
        "p_payload": {"ticker": "AMAT", "priority": 1000, "manual_request": True},
        "p_priority": 1000,
        "p_enqueued_by": "cron",
        "p_max_attempts": 3,
    }


def test_enqueue_ticker_meta_analysis_tasks_skips_blank_targets():
    fake = SimpleNamespace(supabase=FakeSupabase())

    stats = enqueue_ticker_meta_analysis_tasks(
        fake,
        [("", 10), ("aapl", 100)],
        enqueued_by="cron",
        max_attempts=3,
    )

    assert stats == {"attempted": 2, "enqueued": 1, "failed": 1}
    assert len(fake.supabase.calls) == 1
    assert fake.supabase.calls[0][1]["p_target_key"] == "AAPL"


def test_backend_model_and_host_mapping(monkeypatch):
    monkeypatch.setenv("AI_QUEUE_MODEL_GLM", "glm-5.1")
    monkeypatch.setenv("AI_QUEUE_OLLAMA_PRIMARY_BASE_URL", "http://amd:11434")
    monkeypatch.setenv("AI_QUEUE_OLLAMA_SECONDARY_BASE_URL", "http://nvidia:11434")

    assert model_for_backend("glm") == "glm-5.1"
    assert ollama_base_url_for_backend("ollama_primary") == "http://amd:11434"
    assert ollama_base_url_for_backend("ollama_secondary") == "http://nvidia:11434"


def test_ticker_meta_analysis_task_handler_uses_backend_bound_model(monkeypatch):
    """Handler should construct the GLM-bound Ollama client and pin the
    chain to a single backend model so cross-backend fallback happens via
    the queue, not inline."""
    import sys
    import types

    monkeypatch.setenv("AI_QUEUE_MODEL_GLM", "glm-5.1")

    captured: dict[str, object] = {}

    class _FakeMetaService:
        def __init__(self, ollama, supabase, postgres):
            captured["service_ollama"] = ollama

        def run_meta_analysis(self, ticker, **kwargs):
            captured["ticker"] = ticker
            captured["kwargs"] = kwargs
            return {"ticker": ticker, "stance": "BUY"}

    class _FakeOllamaClient:
        def __init__(self, base_url=None, force_base_url_only=False):
            captured["ollama_base_url"] = base_url
            captured["ollama_force_base_url_only"] = force_base_url_only

    class _FakeSupabaseClient:
        def __init__(self, use_service_role=False):
            captured["supabase_service_role"] = use_service_role

    class _FakePostgresClient:
        def __init__(self):
            captured["postgres_created"] = True

    fake_meta = types.ModuleType("meta_analysis_service")
    fake_meta.TickerMetaAnalysisService = _FakeMetaService
    fake_ollama_mod = types.ModuleType("ollama_client")
    fake_ollama_mod.OllamaClient = _FakeOllamaClient
    fake_supabase_mod = types.ModuleType("supabase_client")
    fake_supabase_mod.SupabaseClient = _FakeSupabaseClient
    fake_postgres_mod = types.ModuleType("postgres_client")
    fake_postgres_mod.PostgresClient = _FakePostgresClient

    monkeypatch.setitem(sys.modules, "meta_analysis_service", fake_meta)
    monkeypatch.setitem(sys.modules, "ollama_client", fake_ollama_mod)
    monkeypatch.setitem(sys.modules, "supabase_client", fake_supabase_mod)
    monkeypatch.setitem(sys.modules, "postgres_client", fake_postgres_mod)

    task = {
        "id": "task-1",
        "analysis_type": QUEUE_JOB_TICKER_META_ANALYSIS,
        "target_key": "aapl",
        "payload": {"ticker": "AAPL", "priority": 10, "manual_request": False},
    }

    ticker_meta_analysis_task_handler(task, "glm")

    assert captured["ticker"] == "AAPL"
    # Backend-bound model: chain pinned to the single GLM model so worker
    # never falls back inline to Ollama (cross-backend retry is queue-level).
    assert captured["kwargs"]["model_override"] == "glm-5.1"
    assert captured["kwargs"]["model_chain_override"] == ["glm-5.1"]
    assert captured["kwargs"]["force"] is True
    assert captured["kwargs"]["requested_by"] is None
    # GLM backend uses force_base_url_only=True with no base_url override
    # (matches ticker_analysis handler).
    assert captured["ollama_force_base_url_only"] is True
    assert captured["ollama_base_url"] is None
    assert captured["supabase_service_role"] is True


def test_ticker_meta_analysis_task_handler_raises_on_none_result(monkeypatch):
    """A None result from run_meta_analysis must propagate as a failure so
    the queue records the attempt and the worker can release the task."""
    import sys
    import types

    monkeypatch.setenv("AI_QUEUE_MODEL_GLM", "glm-5.1")

    class _FakeMetaService:
        def __init__(self, ollama, supabase, postgres):
            pass

        def run_meta_analysis(self, ticker, **kwargs):
            return None

    fake_meta = types.ModuleType("meta_analysis_service")
    fake_meta.TickerMetaAnalysisService = _FakeMetaService
    fake_ollama_mod = types.ModuleType("ollama_client")
    fake_ollama_mod.OllamaClient = lambda **kwargs: None
    fake_supabase_mod = types.ModuleType("supabase_client")
    fake_supabase_mod.SupabaseClient = lambda **kwargs: None
    fake_postgres_mod = types.ModuleType("postgres_client")
    fake_postgres_mod.PostgresClient = lambda: None

    monkeypatch.setitem(sys.modules, "meta_analysis_service", fake_meta)
    monkeypatch.setitem(sys.modules, "ollama_client", fake_ollama_mod)
    monkeypatch.setitem(sys.modules, "supabase_client", fake_supabase_mod)
    monkeypatch.setitem(sys.modules, "postgres_client", fake_postgres_mod)

    import pytest

    task = {
        "id": "task-2",
        "analysis_type": QUEUE_JOB_TICKER_META_ANALYSIS,
        "target_key": "MSFT",
        "payload": {},
    }
    with pytest.raises(RuntimeError, match="ticker_meta_analysis returned no result"):
        ticker_meta_analysis_task_handler(task, "glm")


def test_ticker_meta_analysis_task_handler_requires_ollama_base_url(monkeypatch):
    """Non-GLM backends must error if no Ollama base URL is configured for the
    backend; this prevents a worker from silently using the default host."""
    import sys
    import types

    monkeypatch.delenv("AI_QUEUE_OLLAMA_PRIMARY_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL_AMD", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    class _FakeMetaService:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Service should not be constructed when base URL missing")

        def run_meta_analysis(self, *args, **kwargs):
            raise AssertionError

    fake_meta = types.ModuleType("meta_analysis_service")
    fake_meta.TickerMetaAnalysisService = _FakeMetaService
    fake_ollama_mod = types.ModuleType("ollama_client")
    fake_ollama_mod.OllamaClient = lambda **kwargs: None
    fake_supabase_mod = types.ModuleType("supabase_client")
    fake_supabase_mod.SupabaseClient = lambda **kwargs: None
    fake_postgres_mod = types.ModuleType("postgres_client")
    fake_postgres_mod.PostgresClient = lambda: None

    monkeypatch.setitem(sys.modules, "meta_analysis_service", fake_meta)
    monkeypatch.setitem(sys.modules, "ollama_client", fake_ollama_mod)
    monkeypatch.setitem(sys.modules, "supabase_client", fake_supabase_mod)
    monkeypatch.setitem(sys.modules, "postgres_client", fake_postgres_mod)

    import pytest

    task = {
        "id": "task-3",
        "analysis_type": QUEUE_JOB_TICKER_META_ANALYSIS,
        "target_key": "MSFT",
        "payload": {},
    }
    with pytest.raises(RuntimeError, match="No Ollama base URL configured"):
        ticker_meta_analysis_task_handler(task, "ollama_primary")


# ---------------------------------------------------------------------------
# Q4b: sector_meta_analysis on the AI task queue
# ---------------------------------------------------------------------------


def test_build_task_handlers_registers_sector_meta_analysis_when_enabled():
    handlers = build_task_handlers([QUEUE_JOB_SECTOR_META_ANALYSIS])

    assert list(handlers) == [QUEUE_JOB_SECTOR_META_ANALYSIS]
    assert handlers[QUEUE_JOB_SECTOR_META_ANALYSIS] is sector_meta_analysis_task_handler


def test_build_task_handlers_registers_all_three_when_all_enabled():
    handlers = build_task_handlers(
        [
            QUEUE_JOB_TICKER_ANALYSIS,
            QUEUE_JOB_TICKER_META_ANALYSIS,
            QUEUE_JOB_SECTOR_META_ANALYSIS,
        ]
    )

    assert set(handlers) == {
        QUEUE_JOB_TICKER_ANALYSIS,
        QUEUE_JOB_TICKER_META_ANALYSIS,
        QUEUE_JOB_SECTOR_META_ANALYSIS,
    }
    assert handlers[QUEUE_JOB_SECTOR_META_ANALYSIS] is sector_meta_analysis_task_handler


def test_enqueue_sector_meta_analysis_tasks_uses_enqueue_rpc_payload():
    fake = SimpleNamespace(supabase=FakeSupabase())

    stats = enqueue_sector_meta_analysis_tasks(
        fake,
        [("Technology", 10), ("__UNTAGGED__", 10)],
        enqueued_by="cron",
        max_attempts=3,
    )

    assert stats == {"attempted": 2, "enqueued": 2, "failed": 0}
    assert [call[0] for call in fake.supabase.calls] == [
        "enqueue_ai_task",
        "enqueue_ai_task",
    ]
    # Sector keys are NOT uppercased (unlike tickers) — they are free-form
    # labels that come straight from research_articles.sector. Verify the
    # target_key preserves the original casing.
    assert fake.supabase.calls[0][1] == {
        "p_analysis_type": "sector_meta_analysis",
        "p_target_key": "Technology",
        "p_payload": {"sector": "Technology", "priority": 10},
        "p_priority": 10,
        "p_enqueued_by": "cron",
        "p_max_attempts": 3,
    }
    assert fake.supabase.calls[1][1] == {
        "p_analysis_type": "sector_meta_analysis",
        "p_target_key": "__UNTAGGED__",
        "p_payload": {"sector": "__UNTAGGED__", "priority": 10},
        "p_priority": 10,
        "p_enqueued_by": "cron",
        "p_max_attempts": 3,
    }


def test_enqueue_sector_meta_analysis_tasks_skips_blank_targets():
    fake = SimpleNamespace(supabase=FakeSupabase())

    stats = enqueue_sector_meta_analysis_tasks(
        fake,
        [("", 10), ("   ", 10), ("Energy", 10)],
        enqueued_by="cron",
        max_attempts=3,
    )

    assert stats == {"attempted": 3, "enqueued": 1, "failed": 2}
    assert len(fake.supabase.calls) == 1
    assert fake.supabase.calls[0][1]["p_target_key"] == "Energy"


def _install_sector_meta_handler_fakes(monkeypatch, *, captured, return_value=None):
    """Install module stubs needed by ``sector_meta_analysis_task_handler``."""
    import sys
    import types

    sentinel = return_value if return_value is not None else {"sector": "ok"}

    class _FakeSectorService:
        def __init__(self, ollama, supabase, postgres):
            captured["service_ollama"] = ollama
            captured["service_supabase"] = supabase
            captured["service_postgres"] = postgres

        def run_sector_meta(self, sector_key, **kwargs):
            captured["sector_key"] = sector_key
            captured["kwargs"] = kwargs
            return sentinel

    class _FakeOllamaClient:
        def __init__(self, base_url=None, force_base_url_only=False):
            captured["ollama_base_url"] = base_url
            captured["ollama_force_base_url_only"] = force_base_url_only

    class _FakeSupabaseClient:
        def __init__(self, use_service_role=False):
            captured["supabase_service_role"] = use_service_role

    class _FakePostgresClient:
        def __init__(self):
            captured["postgres_created"] = True

    fake_sector = types.ModuleType("sector_meta_analysis_service")
    fake_sector.SectorMetaAnalysisService = _FakeSectorService
    fake_ollama_mod = types.ModuleType("ollama_client")
    fake_ollama_mod.OllamaClient = _FakeOllamaClient
    fake_supabase_mod = types.ModuleType("supabase_client")
    fake_supabase_mod.SupabaseClient = _FakeSupabaseClient
    fake_postgres_mod = types.ModuleType("postgres_client")
    fake_postgres_mod.PostgresClient = _FakePostgresClient

    monkeypatch.setitem(sys.modules, "sector_meta_analysis_service", fake_sector)
    monkeypatch.setitem(sys.modules, "ollama_client", fake_ollama_mod)
    monkeypatch.setitem(sys.modules, "supabase_client", fake_supabase_mod)
    monkeypatch.setitem(sys.modules, "postgres_client", fake_postgres_mod)


@pytest.mark.parametrize(
    "backend, model_env_var, model_default, base_url_env_vars, expected_base_url",
    [
        ("glm", "AI_QUEUE_MODEL_GLM", "glm-5.1", [], None),
        (
            "ollama_primary",
            "AI_QUEUE_MODEL_OLLAMA_PRIMARY",
            "granite3.3:8b",
            [("AI_QUEUE_OLLAMA_PRIMARY_BASE_URL", "http://amd:11434")],
            "http://amd:11434",
        ),
        (
            "ollama_secondary",
            "AI_QUEUE_MODEL_OLLAMA_SECONDARY",
            "qwen3.6:27b",
            [("AI_QUEUE_OLLAMA_SECONDARY_BASE_URL", "http://nvidia:11434")],
            "http://nvidia:11434",
        ),
    ],
)
def test_sector_meta_analysis_task_handler_backend_bound_model(
    monkeypatch, backend, model_env_var, model_default, base_url_env_vars, expected_base_url
):
    """Handler must bind the LLM call to a single backend / model so cross-backend
    fallback happens via re-leasing, not inline."""
    monkeypatch.setenv(model_env_var, model_default)
    for var, value in base_url_env_vars:
        monkeypatch.setenv(var, value)

    captured: dict[str, object] = {}
    _install_sector_meta_handler_fakes(monkeypatch, captured=captured)

    task = {
        "id": "task-sector-1",
        "analysis_type": QUEUE_JOB_SECTOR_META_ANALYSIS,
        "target_key": "Technology",
        "payload": {"sector": "Technology", "priority": 10},
    }

    sector_meta_analysis_task_handler(task, backend)

    assert captured["sector_key"] == "Technology"
    assert captured["kwargs"]["model_override"] == model_default
    # Backend-bound: chain is pinned to a single model so the worker never
    # falls back inline to another backend.
    assert captured["kwargs"]["model_chain_override"] == [model_default]
    assert captured["supabase_service_role"] is True
    # GLM uses force_base_url_only=True with no explicit base URL; Ollama
    # backends pass the resolved base URL plus force_base_url_only=True.
    if backend == "glm":
        assert captured["ollama_base_url"] is None
    else:
        assert captured["ollama_base_url"] == expected_base_url
    assert captured["ollama_force_base_url_only"] is True


def test_sector_meta_analysis_task_handler_raises_on_none_result(monkeypatch):
    """A None result from run_sector_meta must propagate so the queue records
    the attempt and the worker can release the task for retry."""
    monkeypatch.setenv("AI_QUEUE_MODEL_GLM", "glm-5.1")

    captured: dict[str, object] = {}
    _install_sector_meta_handler_fakes(monkeypatch, captured=captured, return_value={"_skip": True})

    # Override the service to return None instead.
    import sys

    class _NoneService:
        def __init__(self, *args, **kwargs):
            pass

        def run_sector_meta(self, *args, **kwargs):
            return None

    sys.modules["sector_meta_analysis_service"].SectorMetaAnalysisService = _NoneService  # type: ignore[attr-defined]

    task = {
        "id": "task-sector-2",
        "analysis_type": QUEUE_JOB_SECTOR_META_ANALYSIS,
        "target_key": "Energy",
        "payload": {},
    }
    with pytest.raises(RuntimeError, match="sector_meta_analysis returned no result"):
        sector_meta_analysis_task_handler(task, "glm")


def test_sector_meta_analysis_task_handler_requires_ollama_base_url(monkeypatch):
    """Non-GLM backends must error if no Ollama base URL is configured."""
    monkeypatch.delenv("AI_QUEUE_OLLAMA_PRIMARY_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL_AMD", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    captured: dict[str, object] = {}
    _install_sector_meta_handler_fakes(monkeypatch, captured=captured)

    task = {
        "id": "task-sector-3",
        "analysis_type": QUEUE_JOB_SECTOR_META_ANALYSIS,
        "target_key": "Energy",
        "payload": {},
    }
    with pytest.raises(RuntimeError, match="No Ollama base URL configured"):
        sector_meta_analysis_task_handler(task, "ollama_primary")


def test_sector_meta_analysis_task_handler_blank_target_raises(monkeypatch):
    """Missing/blank target_key must raise ValueError, not silently succeed."""
    captured: dict[str, object] = {}
    _install_sector_meta_handler_fakes(monkeypatch, captured=captured)

    task = {
        "id": "task-sector-4",
        "analysis_type": QUEUE_JOB_SECTOR_META_ANALYSIS,
        "target_key": "   ",
        "payload": {},
    }
    with pytest.raises(ValueError, match="missing target_key"):
        sector_meta_analysis_task_handler(task, "glm")
