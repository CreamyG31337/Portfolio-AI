from types import SimpleNamespace

import pytest

from web_dashboard.scheduler.ai_task_workers import (
    AIQueueConfig,
    AIQueueWorkerPool,
    QUEUE_JOB_ANALYZE_CONGRESS_TRADES,
    QUEUE_JOB_ETF_GROUP_ANALYSIS,
    QUEUE_JOB_SECTOR_META_ANALYSIS,
    QUEUE_JOB_TICKER_ANALYSIS,
    QUEUE_JOB_TICKER_META_ANALYSIS,
    ERROR_HOST_BUSY,
    ERROR_RATE_LIMITED,
    ERROR_TIMEOUT_GLM,
    ERROR_UNSUPPORTED_TASK,
    UnsupportedTaskError,
    backend_is_configured,
    build_task_handlers,
    classify_error,
    congress_trade_analysis_task_handler,
    enqueue_congress_trade_analysis_tasks,
    enqueue_etf_group_analysis_tasks,
    enqueue_sector_meta_analysis_tasks,
    enqueue_ticker_analysis_tasks,
    enqueue_ticker_meta_analysis_tasks,
    etf_group_analysis_task_handler,
    model_for_backend,
    ollama_base_url_for_backend,
    resolve_effective_worker_counts,
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


def test_resolve_effective_worker_counts_skips_unconfigured_backends(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL_AMD", raising=False)
    monkeypatch.delenv("AI_QUEUE_OLLAMA_PRIMARY_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL_2", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL_NVIDIA", raising=False)
    monkeypatch.delenv("AI_QUEUE_OLLAMA_SECONDARY_BASE_URL", raising=False)
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    monkeypatch.delenv("GLM_4_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://primary:11434")
    monkeypatch.setattr(
        "web_dashboard.scheduler.ai_task_workers.backend_is_configured",
        lambda backend: backend == "ollama_primary",
    )

    config = AIQueueConfig.from_env(
        {
            "AI_QUEUE_ENABLED": "true",
            "AI_QUEUE_JOBS": "ticker_analysis",
            "AI_QUEUE_WORKERS_OLLAMA_PRIMARY": "1",
            "AI_QUEUE_WORKERS_OLLAMA_SECONDARY": "1",
            "AI_QUEUE_WORKERS_GLM": "3",
        }
    )
    effective = resolve_effective_worker_counts(
        config,
        strict_health=False,
        probe=lambda _b: (True, "ok"),
    )
    assert effective["ollama_primary"] == 1
    assert effective["ollama_secondary"] == 0
    assert effective["glm"] == 0


def test_backend_is_configured_ollama_requires_base_url(monkeypatch):
    monkeypatch.setattr(
        "web_dashboard.scheduler.ai_task_workers.ollama_base_url_for_backend",
        lambda backend: "http://x:11434" if backend == "ollama_primary" else None,
    )
    assert backend_is_configured("ollama_primary") is True
    assert backend_is_configured("ollama_secondary") is False


def test_resolve_effective_worker_counts_strict_health_zeros_unhealthy(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://primary:11434")
    monkeypatch.setenv("OLLAMA_BASE_URL_2", "http://secondary:11434")
    monkeypatch.setenv("ZHIPU_API_KEY", "test-key")

    config = AIQueueConfig.from_env(
        {
            "AI_QUEUE_ENABLED": "true",
            "AI_QUEUE_JOBS": "ticker_analysis",
            "AI_QUEUE_WORKERS_OLLAMA_PRIMARY": "1",
            "AI_QUEUE_WORKERS_OLLAMA_SECONDARY": "1",
            "AI_QUEUE_WORKERS_GLM": "2",
        }
    )

    def probe(backend: str):
        if backend == "ollama_secondary":
            return False, "unreachable"
        return True, "ok"

    effective = resolve_effective_worker_counts(config, strict_health=True, probe=probe)
    assert effective == {
        "ollama_primary": 1,
        "ollama_secondary": 0,
        "glm": 2,
    }


def test_resolve_effective_worker_counts_non_strict_keeps_unhealthy_configured(
    monkeypatch,
):
    """Production default: warn on probe failure but still start configured workers."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://primary:11434")
    monkeypatch.setenv("OLLAMA_BASE_URL_2", "http://secondary:11434")
    monkeypatch.setenv("ZHIPU_API_KEY", "test-key")

    config = AIQueueConfig.from_env(
        {
            "AI_QUEUE_ENABLED": "true",
            "AI_QUEUE_JOBS": "ticker_analysis",
            "AI_QUEUE_WORKERS_OLLAMA_PRIMARY": "1",
            "AI_QUEUE_WORKERS_OLLAMA_SECONDARY": "1",
            "AI_QUEUE_WORKERS_GLM": "3",
        }
    )
    effective = resolve_effective_worker_counts(
        config,
        strict_health=False,
        probe=lambda _b: (False, "boot blip"),
    )
    assert effective == {
        "ollama_primary": 1,
        "ollama_secondary": 1,
        "glm": 3,
    }


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
    monkeypatch.setenv("AI_QUEUE_MODEL_GLM", "glm-5.2")
    monkeypatch.setenv("AI_QUEUE_OLLAMA_PRIMARY_BASE_URL", "http://amd:11434")
    monkeypatch.setenv("AI_QUEUE_OLLAMA_SECONDARY_BASE_URL", "http://nvidia:11434")

    assert model_for_backend("glm") == "glm-5.2"
    assert ollama_base_url_for_backend("ollama_primary") == "http://amd:11434"
    assert ollama_base_url_for_backend("ollama_secondary") == "http://nvidia:11434"


def test_model_for_backend_glm_default_uses_primary_registry(monkeypatch):
    monkeypatch.delenv("AI_QUEUE_MODEL_GLM", raising=False)
    monkeypatch.delenv("AI_PRIMARY_MODEL", raising=False)
    assert model_for_backend("glm") == "glm-5.2"


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
            "granite4.1:8b",
            [("AI_QUEUE_OLLAMA_PRIMARY_BASE_URL", "http://amd:11434")],
            "http://amd:11434",
        ),
        (
            "ollama_secondary",
            "AI_QUEUE_MODEL_OLLAMA_SECONDARY",
            "qwen3.8:27b-mtp-q4_K_M",
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


# ---------------------------------------------------------------------------
# Q4c: etf_group_analysis on the AI task queue
# ---------------------------------------------------------------------------


def test_build_task_handlers_registers_etf_group_analysis_when_enabled():
    handlers = build_task_handlers([QUEUE_JOB_ETF_GROUP_ANALYSIS])

    assert list(handlers) == [QUEUE_JOB_ETF_GROUP_ANALYSIS]
    assert handlers[QUEUE_JOB_ETF_GROUP_ANALYSIS] is etf_group_analysis_task_handler


def test_build_task_handlers_registers_all_four_when_all_enabled():
    handlers = build_task_handlers(
        [
            QUEUE_JOB_TICKER_ANALYSIS,
            QUEUE_JOB_TICKER_META_ANALYSIS,
            QUEUE_JOB_SECTOR_META_ANALYSIS,
            QUEUE_JOB_ETF_GROUP_ANALYSIS,
        ]
    )

    assert set(handlers) == {
        QUEUE_JOB_TICKER_ANALYSIS,
        QUEUE_JOB_TICKER_META_ANALYSIS,
        QUEUE_JOB_SECTOR_META_ANALYSIS,
        QUEUE_JOB_ETF_GROUP_ANALYSIS,
    }
    assert handlers[QUEUE_JOB_ETF_GROUP_ANALYSIS] is etf_group_analysis_task_handler


def test_enqueue_etf_group_analysis_tasks_uses_enqueue_rpc_payload():
    fake = SimpleNamespace(supabase=FakeSupabase())

    stats = enqueue_etf_group_analysis_tasks(
        fake,
        [("iwc", "2026-05-23", 10), ("ARKK", "2026-05-22", 10)],
        enqueued_by="cron",
        max_attempts=3,
        queue_ids={"IWC_2026-05-23": "queue-id-1"},
    )

    assert stats == {"attempted": 2, "enqueued": 2, "failed": 0}
    assert [call[0] for call in fake.supabase.calls] == [
        "enqueue_ai_task",
        "enqueue_ai_task",
    ]
    # ETF tickers are uppercased; the date string round-trips verbatim. The
    # legacy ai_analysis_queue id is forwarded via payload so the worker can
    # keep that row's status in sync.
    assert fake.supabase.calls[0][1] == {
        "p_analysis_type": "etf_group_analysis",
        "p_target_key": "IWC_2026-05-23",
        "p_payload": {
            "etf_ticker": "IWC",
            "date": "2026-05-23",
            "priority": 10,
            "legacy_queue_id": "queue-id-1",
        },
        "p_priority": 10,
        "p_enqueued_by": "cron",
        "p_max_attempts": 3,
    }
    # When no legacy queue id is mapped for the target, the payload omits
    # ``legacy_queue_id`` entirely (no None marker that would confuse the
    # handler's optional-update check).
    assert fake.supabase.calls[1][1] == {
        "p_analysis_type": "etf_group_analysis",
        "p_target_key": "ARKK_2026-05-22",
        "p_payload": {
            "etf_ticker": "ARKK",
            "date": "2026-05-22",
            "priority": 10,
        },
        "p_priority": 10,
        "p_enqueued_by": "cron",
        "p_max_attempts": 3,
    }


def test_enqueue_etf_group_analysis_tasks_skips_blank_targets():
    fake = SimpleNamespace(supabase=FakeSupabase())

    stats = enqueue_etf_group_analysis_tasks(
        fake,
        [("", "2026-05-23", 10), ("IWC", "", 10), ("IWC", "2026-05-22", 10)],
        enqueued_by="cron",
        max_attempts=3,
    )

    assert stats == {"attempted": 3, "enqueued": 1, "failed": 2}
    assert len(fake.supabase.calls) == 1
    assert fake.supabase.calls[0][1]["p_target_key"] == "IWC_2026-05-22"


def _install_etf_group_handler_fakes(monkeypatch, *, captured, return_value=None):
    """Install module stubs needed by ``etf_group_analysis_task_handler``."""
    import sys
    import types

    sentinel = return_value if return_value is not None else {"summary": "ok"}

    class _FakeETFGroupService:
        def __init__(self, ollama, supabase, repo):
            captured["service_ollama"] = ollama
            captured["service_supabase"] = supabase
            captured["service_repo"] = repo

        def analyze_group(self, etf_ticker, date, **kwargs):
            captured["etf_ticker"] = etf_ticker
            captured["date"] = date
            captured["kwargs"] = kwargs
            return sentinel

    class _FakeOllamaClient:
        def __init__(self, base_url=None, force_base_url_only=False):
            captured["ollama_base_url"] = base_url
            captured["ollama_force_base_url_only"] = force_base_url_only

    class _FakeSupabaseClient:
        def __init__(self, use_service_role=False):
            captured["supabase_service_role"] = use_service_role
            self.supabase = SimpleNamespace()

    class _FakePostgresClient:
        def __init__(self):
            captured["postgres_created"] = True

    class _FakeResearchRepository:
        def __init__(self, postgres_client=None):
            captured["repo_postgres"] = postgres_client

    fake_etf = types.ModuleType("etf_group_analysis")
    fake_etf.ETFGroupAnalysisService = _FakeETFGroupService
    fake_ollama_mod = types.ModuleType("ollama_client")
    fake_ollama_mod.OllamaClient = _FakeOllamaClient
    fake_supabase_mod = types.ModuleType("supabase_client")
    fake_supabase_mod.SupabaseClient = _FakeSupabaseClient
    fake_postgres_mod = types.ModuleType("postgres_client")
    fake_postgres_mod.PostgresClient = _FakePostgresClient
    fake_repo_mod = types.ModuleType("research_repository")
    fake_repo_mod.ResearchRepository = _FakeResearchRepository

    monkeypatch.setitem(sys.modules, "etf_group_analysis", fake_etf)
    monkeypatch.setitem(sys.modules, "ollama_client", fake_ollama_mod)
    monkeypatch.setitem(sys.modules, "supabase_client", fake_supabase_mod)
    monkeypatch.setitem(sys.modules, "postgres_client", fake_postgres_mod)
    monkeypatch.setitem(sys.modules, "research_repository", fake_repo_mod)


@pytest.mark.parametrize(
    "backend, model_env_var, model_default, base_url_env_vars, expected_base_url",
    [
        ("glm", "AI_QUEUE_MODEL_GLM", "glm-5.1", [], None),
        (
            "ollama_primary",
            "AI_QUEUE_MODEL_OLLAMA_PRIMARY",
            "granite4.1:8b",
            [("AI_QUEUE_OLLAMA_PRIMARY_BASE_URL", "http://amd:11434")],
            "http://amd:11434",
        ),
        (
            "ollama_secondary",
            "AI_QUEUE_MODEL_OLLAMA_SECONDARY",
            "qwen3.8:27b-mtp-q4_K_M",
            [("AI_QUEUE_OLLAMA_SECONDARY_BASE_URL", "http://nvidia:11434")],
            "http://nvidia:11434",
        ),
    ],
)
def test_etf_group_analysis_task_handler_backend_bound_model(
    monkeypatch, backend, model_env_var, model_default, base_url_env_vars, expected_base_url
):
    """Handler must bind the LLM call to a single backend / model so cross-backend
    fallback happens via re-leasing, not inline."""
    monkeypatch.setenv(model_env_var, model_default)
    for var, value in base_url_env_vars:
        monkeypatch.setenv(var, value)

    captured: dict[str, object] = {}
    _install_etf_group_handler_fakes(monkeypatch, captured=captured)

    task = {
        "id": "task-etf-1",
        "analysis_type": QUEUE_JOB_ETF_GROUP_ANALYSIS,
        "target_key": "IWC_2026-05-23",
        "payload": {
            "etf_ticker": "IWC",
            "date": "2026-05-23",
            "priority": 10,
        },
    }

    etf_group_analysis_task_handler(task, backend)

    assert captured["etf_ticker"] == "IWC"
    # Date is parsed into a UTC-aware datetime so the service can format it.
    from datetime import UTC as _UTC

    assert captured["date"].tzinfo is _UTC
    assert captured["date"].strftime("%Y-%m-%d") == "2026-05-23"
    assert captured["kwargs"]["model_override"] == model_default
    # Backend-bound: chain pinned to a single model so cross-backend fallback
    # happens via re-leasing.
    assert captured["kwargs"]["model_chain_override"] == [model_default]
    assert captured["supabase_service_role"] is True
    if backend == "glm":
        assert captured["ollama_base_url"] is None
    else:
        assert captured["ollama_base_url"] == expected_base_url
    assert captured["ollama_force_base_url_only"] is True


def test_etf_group_analysis_task_handler_raises_on_none_result(monkeypatch):
    """A None result must propagate so the queue can release / fail the task."""
    monkeypatch.setenv("AI_QUEUE_MODEL_GLM", "glm-5.1")

    captured: dict[str, object] = {}
    _install_etf_group_handler_fakes(monkeypatch, captured=captured)

    import sys

    class _NoneService:
        def __init__(self, *args, **kwargs):
            pass

        def analyze_group(self, *args, **kwargs):
            return None

    sys.modules["etf_group_analysis"].ETFGroupAnalysisService = _NoneService  # type: ignore[attr-defined]

    task = {
        "id": "task-etf-2",
        "analysis_type": QUEUE_JOB_ETF_GROUP_ANALYSIS,
        "target_key": "ARKK_2026-05-22",
        "payload": {"etf_ticker": "ARKK", "date": "2026-05-22"},
    }
    with pytest.raises(RuntimeError, match="etf_group_analysis returned no result"):
        etf_group_analysis_task_handler(task, "glm")


def test_etf_group_analysis_task_handler_requires_ollama_base_url(monkeypatch):
    """Non-GLM backends must error if no Ollama base URL is configured."""
    monkeypatch.delenv("AI_QUEUE_OLLAMA_PRIMARY_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL_AMD", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    captured: dict[str, object] = {}
    _install_etf_group_handler_fakes(monkeypatch, captured=captured)

    task = {
        "id": "task-etf-3",
        "analysis_type": QUEUE_JOB_ETF_GROUP_ANALYSIS,
        "target_key": "ARKK_2026-05-22",
        "payload": {"etf_ticker": "ARKK", "date": "2026-05-22"},
    }
    with pytest.raises(RuntimeError, match="No Ollama base URL configured"):
        etf_group_analysis_task_handler(task, "ollama_primary")


def test_etf_group_analysis_task_handler_blank_target_raises(monkeypatch):
    """Missing/blank target_key must raise ValueError, not silently succeed."""
    captured: dict[str, object] = {}
    _install_etf_group_handler_fakes(monkeypatch, captured=captured)

    task = {
        "id": "task-etf-4",
        "analysis_type": QUEUE_JOB_ETF_GROUP_ANALYSIS,
        "target_key": "   ",
        "payload": {},
    }
    with pytest.raises(ValueError, match="missing target_key"):
        etf_group_analysis_task_handler(task, "glm")


def test_etf_group_analysis_task_handler_invalid_date_raises(monkeypatch):
    """An unparseable date in payload (or target_key) must raise ValueError."""
    monkeypatch.setenv("AI_QUEUE_MODEL_GLM", "glm-5.1")

    captured: dict[str, object] = {}
    _install_etf_group_handler_fakes(monkeypatch, captured=captured)

    task = {
        "id": "task-etf-5",
        "analysis_type": QUEUE_JOB_ETF_GROUP_ANALYSIS,
        "target_key": "ARKK_not-a-date",
        "payload": {"etf_ticker": "ARKK", "date": "not-a-date"},
    }
    with pytest.raises(ValueError, match="invalid date"):
        etf_group_analysis_task_handler(task, "glm")


def test_build_task_handlers_registers_analyze_congress_trades_when_enabled():
    handlers = build_task_handlers([QUEUE_JOB_ANALYZE_CONGRESS_TRADES])
    assert list(handlers) == [QUEUE_JOB_ANALYZE_CONGRESS_TRADES]
    assert handlers[QUEUE_JOB_ANALYZE_CONGRESS_TRADES] is congress_trade_analysis_task_handler


def test_enqueue_congress_trade_analysis_tasks_uses_enqueue_rpc_payload():
    fake = SimpleNamespace(supabase=FakeSupabase())

    stats = enqueue_congress_trade_analysis_tasks(
        fake,
        [180719, "180725", "bad", 0, -1],
        priority=0,
        enqueued_by="manual_catchup",
        max_attempts=3,
    )

    assert stats == {"attempted": 5, "enqueued": 2, "failed": 3}
    assert [call[0] for call in fake.supabase.calls] == [
        "enqueue_ai_task",
        "enqueue_ai_task",
    ]
    assert fake.supabase.calls[0][1] == {
        "p_analysis_type": "analyze_congress_trades",
        "p_target_key": "180719",
        "p_payload": {"trade_id": 180719, "priority": 0},
        "p_priority": 0,
        "p_enqueued_by": "manual_catchup",
        "p_max_attempts": 3,
    }
    assert fake.supabase.calls[1][1]["p_target_key"] == "180725"
    assert fake.supabase.calls[1][1]["p_priority"] == 0


def test_congress_trade_analysis_task_handler_skips_when_already_scored(monkeypatch):
    """Resume-safe: if Supabase conflict_score is set, do not call LLM or write."""
    import sys
    import types

    class _Table:
        def select(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def limit(self, *_a, **_k):
            return self

        def execute(self):
            return SimpleNamespace(data=[{"id": 180719, "conflict_score": 0.55}])

    class _FakeSupabaseClient:
        def __init__(self, use_service_role=False):
            self.supabase = SimpleNamespace(table=lambda _name: _Table())

    called = {"analyze": False}

    def _boom(*_a, **_k):
        called["analyze"] = True
        raise AssertionError("analyze_trade should not run when already scored")

    fake_supabase = types.ModuleType("supabase_client")
    fake_supabase.SupabaseClient = _FakeSupabaseClient
    fake_pg = types.ModuleType("postgres_client")
    fake_pg.PostgresClient = lambda: SimpleNamespace()
    fake_ollama = types.ModuleType("ollama_client")
    fake_ollama.OllamaClient = lambda **_k: SimpleNamespace()
    fake_batch = types.ModuleType("scripts.analyze_congress_trades_batch")
    fake_batch.analyze_trade = _boom
    fake_batch.get_trade_context = _boom
    fake_batch.is_low_risk_asset = _boom
    fake_batch.sync_supabase_conflict_score = _boom

    monkeypatch.setitem(sys.modules, "supabase_client", fake_supabase)
    monkeypatch.setitem(sys.modules, "postgres_client", fake_pg)
    monkeypatch.setitem(sys.modules, "ollama_client", fake_ollama)
    monkeypatch.setitem(sys.modules, "scripts.analyze_congress_trades_batch", fake_batch)

    congress_trade_analysis_task_handler(
        {"target_key": "180719", "payload": {"trade_id": 180719}},
        "ollama_primary",
    )
    assert called["analyze"] is False
