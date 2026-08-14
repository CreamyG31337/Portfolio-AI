"""
Embedded AI task queue workers.

Provides feature-flagged worker lifecycle, queue RPC calls, error classification,
and handlers for jobs that have migrated to the AI task queue.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

BackendName = str
TaskHandler = Callable[[Mapping[str, Any], BackendName], None]

BACKEND_OLLAMA_PRIMARY = "ollama_primary"
BACKEND_OLLAMA_SECONDARY = "ollama_secondary"
BACKEND_GLM = "glm"
DEFAULT_BACKENDS = (BACKEND_OLLAMA_PRIMARY, BACKEND_OLLAMA_SECONDARY, BACKEND_GLM)

ERROR_HOST_BUSY = "host_busy"
ERROR_TIMEOUT_OLLAMA = "timeout_ollama"
ERROR_TIMEOUT_GLM = "timeout_glm"
ERROR_MODEL_NOT_FOUND = "model_not_found"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_BAD_JSON = "bad_json"
ERROR_SCHEMA_VIOLATION = "schema_violation"
ERROR_DELISTED_OR_NOT_FOUND = "delisted_or_not_found"
ERROR_UNSUPPORTED_TASK = "unsupported_task"
ERROR_UNKNOWN = "unknown"

QUEUE_JOB_TICKER_ANALYSIS = "ticker_analysis"
QUEUE_JOB_TICKER_META_ANALYSIS = "ticker_meta_analysis"
QUEUE_JOB_SECTOR_META_ANALYSIS = "sector_meta_analysis"
QUEUE_JOB_ETF_GROUP_ANALYSIS = "etf_group_analysis"
QUEUE_JOB_EXECUTIVE_TICKER_RESOLVE = "executive_ticker_resolve"
QUEUE_JOB_ANALYZE_CONGRESS_TRADES = "analyze_congress_trades"
QUEUE_JOB_YOUTUBE_TRANSCRIPT_SUMMARY = "youtube_transcript_summary"
QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS = "social_sentiment_analysis"

TERMINAL_ERROR_CLASSES = {
    ERROR_SCHEMA_VIOLATION,
    ERROR_DELISTED_OR_NOT_FOUND,
    ERROR_UNSUPPORTED_TASK,
}


class UnsupportedTaskError(RuntimeError):
    """Raised when a leased task has no registered handler."""


@dataclass(frozen=True)
class AIQueueConfig:
    """Runtime configuration for embedded AI task queue workers."""

    enabled: bool
    enabled_jobs: tuple[str, ...]
    worker_counts: Dict[str, int]
    lease_ttl_sec: int
    heartbeat_sec: int
    poll_idle_sec: float
    backoff_base_sec: int
    max_attempts: int

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "AIQueueConfig":
        source = env if env is not None else os.environ
        return cls(
            enabled=_env_bool(source.get("AI_QUEUE_ENABLED"), default=False),
            enabled_jobs=_split_csv(source.get("AI_QUEUE_JOBS", "")),
            worker_counts={
                BACKEND_OLLAMA_PRIMARY: _env_int(
                    source.get("AI_QUEUE_WORKERS_OLLAMA_PRIMARY"), 1, minimum=0
                ),
                BACKEND_OLLAMA_SECONDARY: _env_int(
                    source.get("AI_QUEUE_WORKERS_OLLAMA_SECONDARY"), 1, minimum=0
                ),
                BACKEND_GLM: _env_int(source.get("AI_QUEUE_WORKERS_GLM"), 3, minimum=0),
            },
            lease_ttl_sec=_env_int(source.get("AI_QUEUE_LEASE_TTL_SEC"), 90, minimum=1),
            heartbeat_sec=_env_int(source.get("AI_QUEUE_HEARTBEAT_SEC"), 30, minimum=1),
            poll_idle_sec=float(
                _env_int(source.get("AI_QUEUE_POLL_IDLE_SEC"), 2, minimum=1)
            ),
            backoff_base_sec=_env_int(source.get("AI_QUEUE_BACKOFF_BASE_SEC"), 30, minimum=0),
            max_attempts=_env_int(source.get("AI_QUEUE_MAX_ATTEMPTS"), 3, minimum=1),
        )


def _env_bool(value: Optional[str], *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(value: Optional[str], default: int, *, minimum: int) -> int:
    try:
        parsed = int(str(value).strip()) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def is_ai_queue_job_enabled(job_name: str, config: Optional[AIQueueConfig] = None) -> bool:
    """Return True when ``job_name`` should use the AI task queue."""

    cfg = config or AIQueueConfig.from_env()
    return cfg.enabled and job_name in cfg.enabled_jobs


def _first_env(*names: str) -> Optional[str]:
    for name in names:
        value = os.getenv(name, "").strip().rstrip("/")
        if value:
            return value
    return None


def backend_is_configured(backend: str) -> bool:
    """True when env has enough config to run this backend (URL or API key).

    Missing secondary Ollama / GLM config is common for single-host OSS installs;
    those backends simply start with zero workers. Fully configured deployments
    (primary + secondary + GLM) are unchanged.
    """

    if backend == BACKEND_GLM:
        try:
            from glm_config import get_zhipu_api_key

            return bool(get_zhipu_api_key())
        except Exception:
            return bool(
                os.getenv("ZHIPU_API_KEY", "").strip()
                or os.getenv("GLM_4_API_KEY", "").strip()
            )
    if backend in (BACKEND_OLLAMA_PRIMARY, BACKEND_OLLAMA_SECONDARY):
        return bool(ollama_base_url_for_backend(backend))
    return False


def probe_backend_health(
    backend: str,
    *,
    timeout_sec: float = 3.0,
) -> tuple[bool, str]:
    """Lightweight reachability check. Returns ``(ok, detail)``.

    Ollama: ``GET {base}/api/tags``. GLM: API key present (no network call).
    """

    if backend == BACKEND_GLM:
        if backend_is_configured(backend):
            return True, "ZHIPU/GLM API key present"
        return False, "ZHIPU_API_KEY / GLM_4_API_KEY not set"

    base_url = ollama_base_url_for_backend(backend)
    if not base_url:
        return False, f"no Ollama base URL configured for {backend}"

    try:
        import requests

        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout_sec)
        if resp.status_code >= 400:
            return False, f"{base_url} returned HTTP {resp.status_code}"
        return True, f"{base_url} ok"
    except Exception as exc:
        return False, f"{base_url} unreachable: {exc}"


def resolve_effective_worker_counts(
    config: AIQueueConfig,
    *,
    strict_health: Optional[bool] = None,
    probe: Optional[Callable[[str], tuple[bool, str]]] = None,
) -> Dict[str, int]:
    """Apply config counts, then drop backends that are not configured.

    When ``AI_QUEUE_STRICT_BACKEND_HEALTH`` is truthy (or ``strict_health=True``),
    also drop backends that fail a health probe. Default is non-strict so a
    transient blip at scheduler boot does not disable a configured host.
    """

    if strict_health is None:
        strict_health = _env_bool(os.getenv("AI_QUEUE_STRICT_BACKEND_HEALTH"), default=False)
    probe_fn = probe or (lambda b: probe_backend_health(b))

    effective: Dict[str, int] = {}
    for backend, count in config.worker_counts.items():
        requested = max(0, int(count))
        if requested <= 0:
            effective[backend] = 0
            continue
        if not backend_is_configured(backend):
            logger.info(
                "AI queue: skipping %s workers for %s (not configured)",
                requested,
                backend,
            )
            effective[backend] = 0
            continue
        if strict_health:
            ok, detail = probe_fn(backend)
            if not ok:
                logger.warning(
                    "AI queue: skipping %s workers for %s (health check failed: %s)",
                    requested,
                    backend,
                    detail,
                )
                effective[backend] = 0
                continue
        else:
            ok, detail = probe_fn(backend)
            if not ok:
                logger.warning(
                    "AI queue: starting %s workers for %s despite health warning: %s",
                    requested,
                    backend,
                    detail,
                )
        effective[backend] = requested
    return effective


def model_for_backend(backend: str) -> str:
    """Resolve the single model a backend-bound worker should use."""

    if backend == BACKEND_GLM:
        override = os.getenv("AI_QUEUE_MODEL_GLM", "").strip()
        if override:
            return override
        try:
            from model_registry import get_primary_model

            return get_primary_model()
        except ImportError:
            return "glm-5.2"
    if backend == BACKEND_OLLAMA_SECONDARY:
        try:
            from model_registry import get_ollama_queue_secondary_model

            return get_ollama_queue_secondary_model()
        except ImportError:
            return "qwen3.6:27b-heretic"
    try:
        from model_registry import get_ollama_queue_primary_model

        return get_ollama_queue_primary_model()
    except ImportError:
        return "granite4.1:8b"


def ollama_base_url_for_backend(backend: str) -> Optional[str]:
    """Resolve the Ollama base URL for a backend-bound worker."""

    if backend == BACKEND_OLLAMA_SECONDARY:
        return _first_env(
            "AI_QUEUE_OLLAMA_SECONDARY_BASE_URL",
            "OLLAMA_BASE_URL_NVIDIA",
            "OLLAMA_BASE_URL_2",
        )
    if backend == BACKEND_OLLAMA_PRIMARY:
        return _first_env(
            "AI_QUEUE_OLLAMA_PRIMARY_BASE_URL",
            "OLLAMA_BASE_URL_AMD",
            "OLLAMA_BASE_URL",
        )
    return None


def classify_error(exc: BaseException, *, backend: Optional[str] = None) -> str:
    """Classify a task failure into the queue fallback taxonomy."""

    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    backend_name = (backend or "").lower()

    if isinstance(exc, UnsupportedTaskError):
        return ERROR_UNSUPPORTED_TASK

    if "ollamahostbusyerror" in name or "hosts busy" in message:
        return ERROR_HOST_BUSY

    if "429" in message or "rate limit" in message or "rate_limited" in message:
        return ERROR_RATE_LIMITED

    if (
        "model not found" in message
        or "not found: model" in message
        or ("404" in message and "model" in message)
    ):
        return ERROR_MODEL_NOT_FOUND

    if "delisted" in message or "no such ticker" in message or "ticker not found" in message:
        return ERROR_DELISTED_OR_NOT_FOUND

    if "schema" in message or "constraint" in message or "violates" in message:
        return ERROR_SCHEMA_VIOLATION

    if "json" in message or "decode" in message or "parse" in message:
        return ERROR_BAD_JSON

    if isinstance(exc, TimeoutError) or "timeout" in message or "timed out" in message:
        if backend_name == BACKEND_GLM or "glm" in message or "z.ai" in message or "zai" in message:
            return ERROR_TIMEOUT_GLM
        return ERROR_TIMEOUT_OLLAMA

    return ERROR_UNKNOWN


def should_increment_attempts(error_class: str) -> bool:
    """Return whether this failure should count against max attempts."""

    return error_class != ERROR_HOST_BUSY


def retry_delay_seconds(error_class: str, *, attempts: int, base_delay_sec: int) -> int:
    """Return queue backoff delay for a non-terminal failure."""

    if error_class != ERROR_RATE_LIMITED:
        return 0
    return base_delay_sec * max(1, 2 ** max(0, attempts))


class AIQueueWorkerPool:
    """Threaded worker pool for leased AI tasks."""

    def __init__(
        self,
        config: AIQueueConfig,
        *,
        handlers: Optional[Mapping[str, TaskHandler]] = None,
        client_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.config = config
        self.handlers = dict(handlers or {})
        self.client_factory = client_factory or self._default_client_factory
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return any(thread.is_alive() for thread in self._threads)

    def start(self) -> bool:
        """Start worker threads when the feature flag and handlers are configured."""

        with self._lock:
            if self.running:
                logger.info("AI task workers already running")
                return False
            if not self.config.enabled:
                logger.info("AI task workers disabled (AI_QUEUE_ENABLED is false)")
                return False

            analysis_types = self._enabled_analysis_types()
            if not analysis_types:
                logger.info(
                    "AI task workers not started: no enabled queue jobs have registered handlers"
                )
                return False

            self._stop_event.clear()
            self._threads = []
            effective_counts = resolve_effective_worker_counts(self.config)
            for backend, count in effective_counts.items():
                for ordinal in range(count):
                    thread = threading.Thread(
                        target=self._worker_loop,
                        name=f"ai-task-{backend}-{ordinal + 1}",
                        args=(backend, ordinal + 1, analysis_types),
                        daemon=True,
                    )
                    thread.start()
                    self._threads.append(thread)

            if not self._threads:
                logger.warning(
                    "AI task workers not started: no backends configured/healthy "
                    "(check OLLAMA_BASE_URL and/or ZHIPU_API_KEY)"
                )
                return False

            logger.info(
                "Started %d AI task worker(s) for jobs=%s backends=%s",
                len(self._threads),
                ",".join(analysis_types),
                ",".join(
                    f"{backend}:{count}"
                    for backend, count in effective_counts.items()
                    if count > 0
                ),
            )
            return True

    def stop(self, *, wait: bool = True, timeout: float = 5.0) -> None:
        """Signal workers to stop and optionally wait for thread exit."""

        self._stop_event.set()
        if wait:
            for thread in list(self._threads):
                thread.join(timeout=timeout)

    def _enabled_analysis_types(self) -> tuple[str, ...]:
        return tuple(job for job in self.config.enabled_jobs if job in self.handlers)

    def _worker_loop(
        self,
        backend: str,
        ordinal: int,
        analysis_types: Sequence[str],
    ) -> None:
        worker_id = self._worker_id(backend, ordinal)
        try:
            client = self.client_factory()
        except Exception as exc:
            logger.error("AI task worker %s failed to create Supabase client: %s", worker_id, exc)
            return

        while not self._stop_event.is_set():
            try:
                task = self._lease_one(client, worker_id, backend, analysis_types)
                if not task:
                    self._stop_event.wait(self.config.poll_idle_sec)
                    continue
                self._run_task(client, task, worker_id, backend)
            except Exception as exc:
                logger.warning("AI task worker %s loop error: %s", worker_id, exc, exc_info=True)
                self._stop_event.wait(self.config.poll_idle_sec)

    def _run_task(
        self,
        client: Any,
        task: Mapping[str, Any],
        worker_id: str,
        backend: str,
    ) -> None:
        task_id = str(task.get("id") or "")
        analysis_type = str(task.get("analysis_type") or "")
        handler = self.handlers.get(analysis_type)
        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"ai-task-heartbeat-{task_id[:8]}",
            args=(client, task_id, worker_id, heartbeat_stop),
            daemon=True,
        )
        heartbeat_thread.start()

        try:
            if handler is None:
                raise UnsupportedTaskError(f"No handler registered for {analysis_type!r}")
            try:
                from ai_audit import set_audit_context

                set_audit_context(
                    ai_task_id=task_id,
                    ai_task_backend=backend,
                    ai_task_analysis_type=analysis_type,
                )
            except Exception as exc:
                logger.debug("Failed to set AI task audit context: %s", exc)
            handler(task, backend)
        except Exception as exc:
            self._handle_failure(client, task, worker_id, backend, exc)
        else:
            self._complete_task(client, task_id, worker_id)
        finally:
            try:
                from ai_audit import clear_audit_context

                clear_audit_context()
            except Exception as exc:
                logger.debug("Failed to clear AI task audit context: %s", exc)
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1.0)

    def _heartbeat_loop(
        self,
        client: Any,
        task_id: str,
        worker_id: str,
        stop_event: threading.Event,
    ) -> None:
        while not stop_event.wait(self.config.heartbeat_sec):
            try:
                self._rpc(
                    client,
                    "heartbeat_ai_task",
                    {
                        "p_task_id": task_id,
                        "p_worker_id": worker_id,
                        "p_lease_seconds": self.config.lease_ttl_sec,
                    },
                )
            except Exception as exc:
                logger.warning("AI task heartbeat failed for task=%s: %s", task_id, exc)

    def _handle_failure(
        self,
        client: Any,
        task: Mapping[str, Any],
        worker_id: str,
        backend: str,
        exc: BaseException,
    ) -> None:
        task_id = str(task.get("id") or "")
        attempts = int(task.get("attempts") or 0)
        error_class = classify_error(exc, backend=backend)
        if error_class in TERMINAL_ERROR_CLASSES:
            self._fail_task(client, task_id, worker_id, error_class, str(exc))
            return

        self._release_task(
            client,
            task_id,
            worker_id,
            error_class,
            str(exc),
            increment_attempts=should_increment_attempts(error_class),
            delay_seconds=retry_delay_seconds(
                error_class,
                attempts=attempts,
                base_delay_sec=self.config.backoff_base_sec,
            ),
        )

    def _lease_one(
        self,
        client: Any,
        worker_id: str,
        backend: str,
        analysis_types: Sequence[str],
    ) -> Optional[Mapping[str, Any]]:
        result = self._rpc(
            client,
            "lease_ai_task",
            {
                "p_worker_id": worker_id,
                "p_backend": backend,
                "p_analysis_types": list(analysis_types),
                "p_lease_seconds": self.config.lease_ttl_sec,
            },
        )
        rows = getattr(result, "data", None) or []
        return rows[0] if rows else None

    def _complete_task(self, client: Any, task_id: str, worker_id: str) -> None:
        self._rpc(client, "complete_ai_task", {"p_task_id": task_id, "p_worker_id": worker_id})

    def _release_task(
        self,
        client: Any,
        task_id: str,
        worker_id: str,
        error_class: str,
        error_message: str,
        *,
        increment_attempts: bool,
        delay_seconds: int,
    ) -> None:
        self._rpc(
            client,
            "release_ai_task",
            {
                "p_task_id": task_id,
                "p_worker_id": worker_id,
                "p_error_class": error_class,
                "p_error_message": error_message,
                "p_increment_attempts": increment_attempts,
                "p_delay_seconds": delay_seconds,
            },
        )

    def _fail_task(
        self,
        client: Any,
        task_id: str,
        worker_id: str,
        error_class: str,
        error_message: str,
    ) -> None:
        self._rpc(
            client,
            "fail_ai_task",
            {
                "p_task_id": task_id,
                "p_worker_id": worker_id,
                "p_error_class": error_class,
                "p_error_message": error_message,
            },
        )

    @staticmethod
    def _rpc(client: Any, function_name: str, payload: Mapping[str, Any]) -> Any:
        return client.supabase.rpc(function_name, dict(payload)).execute()

    @staticmethod
    def _worker_id(backend: str, ordinal: int) -> str:
        return f"{socket.gethostname()}:{os.getpid()}:{backend}:{ordinal}"

    @staticmethod
    def _default_client_factory() -> Any:
        from supabase_client import SupabaseClient

        return SupabaseClient(use_service_role=True)


def enqueue_ai_task(
    supabase_client: Any,
    *,
    analysis_type: str,
    target_key: str,
    payload: Optional[Mapping[str, Any]] = None,
    priority: int = 0,
    enqueued_by: str = "cron",
    max_attempts: int = 3,
) -> Mapping[str, Any]:
    """Enqueue or update one active AI task via the Supabase RPC."""

    result = supabase_client.supabase.rpc(
        "enqueue_ai_task",
        {
            "p_analysis_type": analysis_type,
            "p_target_key": target_key,
            "p_payload": dict(payload or {}),
            "p_priority": priority,
            "p_enqueued_by": enqueued_by,
            "p_max_attempts": max_attempts,
        },
    ).execute()
    data = getattr(result, "data", None)
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


def enqueue_ticker_analysis_tasks(
    supabase_client: Any,
    tickers: Sequence[tuple[str, int]],
    *,
    enqueued_by: str = "cron",
    max_attempts: int = 3,
) -> Dict[str, int]:
    """Enqueue one ``ticker_analysis`` task per selected ticker."""

    stats = {"attempted": 0, "enqueued": 0, "failed": 0}
    for ticker, priority in tickers:
        stats["attempted"] += 1
        ticker_upper = str(ticker).upper().strip()
        if not ticker_upper:
            stats["failed"] += 1
            continue
        try:
            payload = {
                "ticker": ticker_upper,
                "priority": int(priority),
                "manual_request": int(priority) >= 1000,
            }
            enqueue_ai_task(
                supabase_client,
                analysis_type=QUEUE_JOB_TICKER_ANALYSIS,
                target_key=ticker_upper,
                payload=payload,
                priority=int(priority),
                enqueued_by=enqueued_by,
                max_attempts=max_attempts,
            )
            stats["enqueued"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.warning("Failed to enqueue ticker_analysis task for %s: %s", ticker_upper, exc)
    return stats


def ticker_analysis_task_handler(task: Mapping[str, Any], backend: str) -> None:
    """Run one ticker analysis task on the assigned backend."""

    ticker = str(task.get("target_key") or "").upper().strip()
    if not ticker:
        raise ValueError("ticker_analysis task missing target_key")

    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    model = model_for_backend(backend)

    from ai_skip_list_manager import AISkipListManager
    from ollama_client import OllamaClient
    from postgres_client import PostgresClient
    from supabase_client import SupabaseClient
    from ticker_analysis_service import TickerAnalysisService

    supabase = SupabaseClient(use_service_role=True)
    postgres = PostgresClient()
    if backend == BACKEND_GLM:
        ollama = OllamaClient(force_base_url_only=True)
    else:
        base_url = ollama_base_url_for_backend(backend)
        if not base_url:
            raise RuntimeError(f"No Ollama base URL configured for backend={backend}")
        ollama = OllamaClient(base_url=base_url, force_base_url_only=True)

    service = TickerAnalysisService(
        ollama,
        supabase,
        postgres,
        AISkipListManager(supabase),
    )
    try:
        result = service.analyze_ticker(
            ticker,
            model_override=model,
            model_chain_override=[model],
        )
        if not result:
            raise RuntimeError(f"ticker_analysis returned no result for {ticker} on {backend}")
        if bool(payload.get("manual_request")):
            service.mark_manual_request_complete(ticker, success=True)
    except Exception as exc:
        if bool(payload.get("manual_request")):
            service.mark_manual_request_complete(ticker, success=False, error_message=str(exc)[:500])
        raise


def enqueue_ticker_meta_analysis_tasks(
    supabase_client: Any,
    tickers: Sequence[tuple[str, int]],
    *,
    enqueued_by: str = "cron",
    max_attempts: int = 3,
) -> Dict[str, int]:
    """Enqueue one ``ticker_meta_analysis`` task per selected ticker.

    Mirrors :func:`enqueue_ticker_analysis_tasks`. Callers should pass tuples of
    ``(ticker, priority)``; manual UI requests should use ``priority >= 1000``
    so they jump ahead of cron-enqueued meta tasks (matching the convention
    already established for ``ticker_analysis``).
    """

    stats = {"attempted": 0, "enqueued": 0, "failed": 0}
    for ticker, priority in tickers:
        stats["attempted"] += 1
        ticker_upper = str(ticker).upper().strip()
        if not ticker_upper:
            stats["failed"] += 1
            continue
        try:
            payload = {
                "ticker": ticker_upper,
                "priority": int(priority),
                "manual_request": int(priority) >= 1000,
            }
            enqueue_ai_task(
                supabase_client,
                analysis_type=QUEUE_JOB_TICKER_META_ANALYSIS,
                target_key=ticker_upper,
                payload=payload,
                priority=int(priority),
                enqueued_by=enqueued_by,
                max_attempts=max_attempts,
            )
            stats["enqueued"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.warning(
                "Failed to enqueue ticker_meta_analysis task for %s: %s",
                ticker_upper,
                exc,
            )
    return stats


def ticker_meta_analysis_task_handler(task: Mapping[str, Any], backend: str) -> None:
    """Run one ticker meta analysis task on the assigned backend.

    Mirrors :func:`ticker_analysis_task_handler`: the worker is bound to a
    single backend / model so cross-backend fallback happens via re-leasing
    instead of inline chain attempts. ``force=True`` is intentional: the
    scheduler already filtered candidates via ``needs_refresh`` at enqueue
    time, so the worker should always recompute meta to capture the latest
    artifact bundle.
    """

    ticker = str(task.get("target_key") or "").upper().strip()
    if not ticker:
        raise ValueError("ticker_meta_analysis task missing target_key")

    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    model = model_for_backend(backend)

    from meta_analysis_service import TickerMetaAnalysisService
    from ollama_client import OllamaClient
    from postgres_client import PostgresClient
    from supabase_client import SupabaseClient

    supabase = SupabaseClient(use_service_role=True)
    postgres = PostgresClient()
    if backend == BACKEND_GLM:
        ollama = OllamaClient(force_base_url_only=True)
    else:
        base_url = ollama_base_url_for_backend(backend)
        if not base_url:
            raise RuntimeError(f"No Ollama base URL configured for backend={backend}")
        ollama = OllamaClient(base_url=base_url, force_base_url_only=True)

    service = TickerMetaAnalysisService(ollama, supabase, postgres)
    requested_by = payload.get("requested_by") if isinstance(payload, dict) else None
    result = service.run_meta_analysis(
        ticker,
        requested_by=str(requested_by) if requested_by else None,
        model_override=model,
        model_chain_override=[model],
        force=True,
    )
    if not result:
        raise RuntimeError(
            f"ticker_meta_analysis returned no result for {ticker} on {backend}"
        )


def enqueue_sector_meta_analysis_tasks(
    supabase_client: Any,
    sectors: Sequence[tuple[str, int]],
    *,
    enqueued_by: str = "cron",
    max_attempts: int = 3,
) -> Dict[str, int]:
    """Enqueue one ``sector_meta_analysis`` task per selected sector key.

    Mirrors :func:`enqueue_ticker_meta_analysis_tasks` but the
    ``target_key`` is the sector label (or ``__UNTAGGED__`` for the catch-all
    bucket emitted by :meth:`SectorMetaAnalysisService.list_sector_keys`).

    TODO: manual route to be added if/when a manual rebuild UI exists for
    sectors. Today only the nightly cron path enqueues these tasks, so the
    ``priority >= 1000`` "manual_request" branch from the ticker-side
    helpers is intentionally omitted — callers can add it later without a
    payload-shape change because ``payload`` is already free-form JSON.
    """

    stats = {"attempted": 0, "enqueued": 0, "failed": 0}
    for sector_key, priority in sectors:
        stats["attempted"] += 1
        key = str(sector_key).strip()
        if not key:
            stats["failed"] += 1
            continue
        try:
            payload = {
                "sector": key,
                "priority": int(priority),
            }
            enqueue_ai_task(
                supabase_client,
                analysis_type=QUEUE_JOB_SECTOR_META_ANALYSIS,
                target_key=key,
                payload=payload,
                priority=int(priority),
                enqueued_by=enqueued_by,
                max_attempts=max_attempts,
            )
            stats["enqueued"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.warning(
                "Failed to enqueue sector_meta_analysis task for %s: %s",
                key,
                exc,
            )
    return stats


def sector_meta_analysis_task_handler(task: Mapping[str, Any], backend: str) -> None:
    """Run one sector meta analysis task on the assigned backend.

    Mirrors :func:`ticker_meta_analysis_task_handler`: the worker is bound to a
    single backend / model so cross-backend fallback happens via re-leasing
    instead of an inline chain. The scheduler queue-mode path is responsible
    for candidate selection (today: every sector returned by
    :meth:`SectorMetaAnalysisService.list_sector_keys`), so the worker just
    synthesizes the requested sector and persists the result.
    """

    sector_key = str(task.get("target_key") or "").strip()
    if not sector_key:
        raise ValueError("sector_meta_analysis task missing target_key")

    model = model_for_backend(backend)

    from ollama_client import OllamaClient
    from postgres_client import PostgresClient
    from sector_meta_analysis_service import SectorMetaAnalysisService
    from supabase_client import SupabaseClient

    supabase = SupabaseClient(use_service_role=True)
    postgres = PostgresClient()
    if backend == BACKEND_GLM:
        ollama = OllamaClient(force_base_url_only=True)
    else:
        base_url = ollama_base_url_for_backend(backend)
        if not base_url:
            raise RuntimeError(f"No Ollama base URL configured for backend={backend}")
        ollama = OllamaClient(base_url=base_url, force_base_url_only=True)

    service = SectorMetaAnalysisService(ollama, supabase, postgres)
    result = service.run_sector_meta(
        sector_key,
        model_override=model,
        model_chain_override=[model],
    )
    if not result:
        raise RuntimeError(
            f"sector_meta_analysis returned no result for {sector_key} on {backend}"
        )


def enqueue_etf_group_analysis_tasks(
    supabase_client: Any,
    etf_groups: Sequence[tuple[str, str, int]],
    *,
    enqueued_by: str = "cron",
    max_attempts: int = 3,
    queue_ids: Mapping[str, str] | None = None,
) -> dict[str, int]:
    """Enqueue one ``etf_group_analysis`` task per (ETF, date) pair.

    Mirrors :func:`enqueue_sector_meta_analysis_tasks`. Each input tuple is
    ``(etf_ticker, date_str, priority)`` where ``date_str`` is ISO ``YYYY-MM-DD``.
    The ``target_key`` is the legacy ``ai_analysis_queue`` shape
    ``f"{ETF}_{date_str}"`` so cross-checking against the existing per-day
    queue rows is trivial. ETF tickers are uppercased; date strings round-trip
    verbatim.

    ``queue_ids`` (optional) maps ``target_key`` → ``ai_analysis_queue.id`` so
    the worker can keep the legacy resumability log in sync (mark
    ``completed`` on success / ``failed`` on raise). Missing entries cause the
    handler to skip the legacy update (no-op, no error).

    TODO: a manual rebuild route (priority ≥ 1000) is intentionally omitted —
    today only the nightly cron path enqueues these tasks. Add a
    ``manual_request`` branch later without a payload-shape change because
    ``payload`` is already free-form JSON.
    """

    stats: dict[str, int] = {"attempted": 0, "enqueued": 0, "failed": 0}
    queue_id_map = dict(queue_ids or {})
    for etf_ticker, date_str, priority in etf_groups:
        stats["attempted"] += 1
        etf_upper = str(etf_ticker).upper().strip()
        date_clean = str(date_str).strip()
        if not etf_upper or not date_clean:
            stats["failed"] += 1
            continue
        target_key = f"{etf_upper}_{date_clean}"
        try:
            payload: dict[str, Any] = {
                "etf_ticker": etf_upper,
                "date": date_clean,
                "priority": int(priority),
            }
            queue_id = queue_id_map.get(target_key)
            if queue_id:
                payload["legacy_queue_id"] = str(queue_id)
            enqueue_ai_task(
                supabase_client,
                analysis_type=QUEUE_JOB_ETF_GROUP_ANALYSIS,
                target_key=target_key,
                payload=payload,
                priority=int(priority),
                enqueued_by=enqueued_by,
                max_attempts=max_attempts,
            )
            stats["enqueued"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.warning(
                "Failed to enqueue etf_group_analysis task for %s: %s",
                target_key,
                exc,
            )
    return stats


def etf_group_analysis_task_handler(task: Mapping[str, Any], backend: str) -> None:
    """Run one ETF group analysis task on the assigned backend.

    Mirrors :func:`sector_meta_analysis_task_handler`: the worker is bound to
    a single backend / model so cross-backend fallback happens via re-leasing
    instead of an inline chain. The scheduler queue-mode path is responsible
    for candidate selection (the legacy ``ai_analysis_queue`` table); the
    worker just re-runs ``analyze_group`` and persists the resulting research
    article.

    The legacy ``ai_analysis_queue`` resumability row (when its id is in the
    payload) is updated to ``completed`` on success and ``failed`` on raise so
    the existing audit/retry log stays in sync. The handler still re-raises
    on failure so the task queue worker classifies the error and releases /
    fails the lease normally.
    """

    target_key = str(task.get("target_key") or "").strip()
    if not target_key:
        raise ValueError("etf_group_analysis task missing target_key")

    payload_raw = task.get("payload")
    payload: dict[str, Any] = dict(payload_raw) if isinstance(payload_raw, dict) else {}

    etf_ticker = str(payload.get("etf_ticker") or "").upper().strip()
    date_str = str(payload.get("date") or "").strip()
    if not etf_ticker or not date_str:
        # Fall back to parsing the target_key when payload is incomplete (e.g.
        # legacy enqueues that pre-date this handler). Format: ``ETF_YYYY-MM-DD``.
        parts = target_key.split("_", 1)
        if len(parts) == 2:
            etf_ticker = etf_ticker or parts[0].upper()
            date_str = date_str or parts[1]
    if not etf_ticker or not date_str:
        raise ValueError(
            f"etf_group_analysis task has unparseable target_key={target_key!r}"
        )

    from datetime import datetime as _datetime
    from datetime import UTC as _UTC

    try:
        analysis_date = _datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_UTC)
    except ValueError as exc:
        raise ValueError(
            f"etf_group_analysis task has invalid date={date_str!r}"
        ) from exc

    model = model_for_backend(backend)

    from etf_group_analysis import ETFGroupAnalysisService
    from ollama_client import OllamaClient
    from postgres_client import PostgresClient
    from research_repository import ResearchRepository
    from supabase_client import SupabaseClient

    supabase = SupabaseClient(use_service_role=True)
    postgres = PostgresClient()
    repo = ResearchRepository(postgres_client=postgres)

    if backend == BACKEND_GLM:
        ollama = OllamaClient(force_base_url_only=True)
    else:
        base_url = ollama_base_url_for_backend(backend)
        if not base_url:
            raise RuntimeError(f"No Ollama base URL configured for backend={backend}")
        ollama = OllamaClient(base_url=base_url, force_base_url_only=True)

    service = ETFGroupAnalysisService(ollama, supabase, repo)

    legacy_queue_id = payload.get("legacy_queue_id")
    legacy_queue_id_str: str | None = (
        str(legacy_queue_id) if legacy_queue_id else None
    )

    try:
        result = service.analyze_group(
            etf_ticker,
            analysis_date,
            model_override=model,
            model_chain_override=[model],
        )
        if not result:
            raise RuntimeError(
                f"etf_group_analysis returned no result for {etf_ticker} on {date_str}"
            )
        if legacy_queue_id_str:
            _mark_legacy_etf_queue_outcome(
                supabase, legacy_queue_id_str, success=True
            )
    except Exception as exc:
        if legacy_queue_id_str:
            _mark_legacy_etf_queue_outcome(
                supabase,
                legacy_queue_id_str,
                success=False,
                error=str(exc)[:500],
            )
        raise


def enqueue_executive_ticker_tasks(
    supabase_client: Any,
    names: Sequence[tuple[str, str, int]],
    *,
    enqueued_by: str = "cron",
    max_attempts: int = 3,
) -> Dict[str, int]:
    """Enqueue one ``executive_ticker_resolve`` task per unresolved OGE name.

    ``names`` is a sequence of ``(canonical_name, raw_description, priority)``.
    ``canonical_name`` is the ``og_asset_ticker_map`` cache key (also used as the
    task ``target_key`` for dedupe); ``raw_description`` is the original OGE asset
    text fed to the LLM prompt.
    """

    stats = {"attempted": 0, "enqueued": 0, "failed": 0}
    for canonical_name, raw_description, priority in names:
        stats["attempted"] += 1
        key = str(canonical_name or "").strip()
        if not key:
            stats["failed"] += 1
            continue
        try:
            payload = {
                "canonical_description": key,
                "description": str(raw_description or "").strip(),
                "priority": int(priority),
            }
            enqueue_ai_task(
                supabase_client,
                analysis_type=QUEUE_JOB_EXECUTIVE_TICKER_RESOLVE,
                target_key=key,
                payload=payload,
                priority=int(priority),
                enqueued_by=enqueued_by,
                max_attempts=max_attempts,
            )
            stats["enqueued"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.warning(
                "Failed to enqueue executive_ticker_resolve task for %s: %s",
                key,
                exc,
            )
    return stats


def executive_ticker_resolve_task_handler(
    task: Mapping[str, Any], backend: str
) -> None:
    """Resolve one OGE asset description to a ticker via LLM on the given backend.

    The worker is bound to a single backend/model (GLM or an Ollama host), so
    the pool already spreads these tasks across backends in parallel. A validated
    hit is cached in ``og_asset_ticker_map`` with ``source='llm'``; a confident
    "no ticker" answer marks the task done without a write. Transient LLM/infra
    failures raise :class:`LLMResolutionError` so the queue retries.
    """

    target_key = str(task.get("target_key") or "").strip()
    if not target_key:
        raise ValueError("executive_ticker_resolve task missing target_key")

    payload_raw = task.get("payload")
    payload: dict[str, Any] = dict(payload_raw) if isinstance(payload_raw, dict) else {}
    description = str(payload.get("description") or "").strip() or target_key

    model = model_for_backend(backend)

    from executive_ticker_resolver import resolve_from_llm
    from ollama_client import OllamaClient
    from supabase_client import SupabaseClient

    from scheduler.jobs_executive import upsert_og_asset_cache_entry

    if backend == BACKEND_GLM:
        ollama = OllamaClient(force_base_url_only=True)
    else:
        base_url = ollama_base_url_for_backend(backend)
        if not base_url:
            raise RuntimeError(f"No Ollama base URL configured for backend={backend}")
        ollama = OllamaClient(base_url=base_url, force_base_url_only=True)

    result = resolve_from_llm(description, ollama_client=ollama, model=model)
    if not result:
        logger.info(
            "executive_ticker_resolve: no validated ticker for %r on %s",
            target_key,
            backend,
        )
        return

    ticker, asset_type, confidence = result
    supabase = SupabaseClient(use_service_role=True)
    from executive_ticker_resolver import classify_oge_asset_type

    product_type = classify_oge_asset_type(description)
    upsert_og_asset_cache_entry(
        supabase,
        canonical_description=target_key,
        ticker=ticker,
        source="llm",
        confidence=confidence,
        asset_type=product_type,
    )
    logger.info(
        "executive_ticker_resolve: %r -> %s (%.2f, %s) via %s",
        target_key,
        ticker,
        confidence,
        product_type,
        backend,
    )


def _mark_legacy_etf_queue_outcome(
    supabase: Any,
    queue_id: str,
    *,
    success: bool,
    error: str | None = None,
) -> None:
    """Update the legacy ``ai_analysis_queue`` row's status from the worker.

    Best-effort: any exception is logged and swallowed so the queue worker's
    primary success/failure signal remains the ``ai_task_queue`` outcome.
    Mirrors the legacy job's :func:`mark_analysis_completed` /
    :func:`mark_analysis_failed` behavior, including the ``retry_count``
    increment on failure.
    """
    try:
        from datetime import datetime as _datetime
        from datetime import UTC as _UTC

        if success:
            supabase.supabase.table("ai_analysis_queue").update(
                {
                    "status": "completed",
                    "completed_at": _datetime.now(_UTC).isoformat(),
                }
            ).eq("id", queue_id).execute()
            return

        # Failure: increment retry_count and write last error.
        cur = (
            supabase.supabase.table("ai_analysis_queue")
            .select("retry_count")
            .eq("id", queue_id)
            .limit(1)
            .execute()
        )
        prev = 0
        if cur.data:
            prev = int(cur.data[0].get("retry_count") or 0)
        supabase.supabase.table("ai_analysis_queue").update(
            {
                "status": "failed",
                "error_message": (error or "")[:500],
                "retry_count": prev + 1,
            }
        ).eq("id", queue_id).execute()
    except Exception as exc:
        logger.warning(
            "Failed to update legacy ai_analysis_queue row %s: %s", queue_id, exc
        )


_worker_pool: Optional[AIQueueWorkerPool] = None


def start_ai_task_workers(
    *,
    config: Optional[AIQueueConfig] = None,
    handlers: Optional[Mapping[str, TaskHandler]] = None,
) -> bool:
    """Start the singleton embedded AI task worker pool."""

    global _worker_pool
    pool = AIQueueWorkerPool(config or AIQueueConfig.from_env(), handlers=handlers)
    started = pool.start()
    if started:
        _worker_pool = pool
    return started


def stop_ai_task_workers(*, wait: bool = True) -> None:
    """Stop the singleton embedded AI task worker pool if it exists."""

    global _worker_pool
    if _worker_pool is None:
        return
    _worker_pool.stop(wait=wait)
    _worker_pool = None


def get_ai_task_worker_pool() -> Optional[AIQueueWorkerPool]:
    """Return the current singleton worker pool, if started."""

    return _worker_pool


def enqueue_congress_trade_analysis_tasks(
    supabase_client: Any,
    trade_ids: Sequence[int],
    *,
    priority: int = 0,
    enqueued_by: str = "cron",
    max_attempts: int = 3,
) -> Dict[str, int]:
    """Enqueue one ``analyze_congress_trades`` task per trade id.

    Catch-up bulk should use low ``priority`` (default 0) so ticker/meta/ETF
    work (higher priority) leases first. ``target_key`` is the string trade id
    for active-row dedupe on re-enqueue.
    """

    stats = {"attempted": 0, "enqueued": 0, "failed": 0}
    total = len(trade_ids)
    progress_every = 500
    for raw_id in trade_ids:
        stats["attempted"] += 1
        try:
            trade_id = int(raw_id)
        except (TypeError, ValueError):
            stats["failed"] += 1
            continue
        if trade_id <= 0:
            stats["failed"] += 1
            continue
        target_key = str(trade_id)
        try:
            enqueue_ai_task(
                supabase_client,
                analysis_type=QUEUE_JOB_ANALYZE_CONGRESS_TRADES,
                target_key=target_key,
                payload={"trade_id": trade_id, "priority": int(priority)},
                priority=int(priority),
                enqueued_by=enqueued_by,
                max_attempts=max_attempts,
            )
            stats["enqueued"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.warning(
                "Failed to enqueue analyze_congress_trades task for trade_id=%s: %s",
                trade_id,
                exc,
            )
        if total > progress_every and stats["attempted"] % progress_every == 0:
            logger.info(
                "Enqueue progress: %s/%s attempted (enqueued=%s failed=%s)",
                stats["attempted"],
                total,
                stats["enqueued"],
                stats["failed"],
            )
    return stats


def congress_trade_analysis_task_handler(task: Mapping[str, Any], backend: str) -> None:
    """Score one congress trade on the assigned backend; sync Supabase conflict_score."""

    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    raw_id = payload.get("trade_id") or task.get("target_key")
    try:
        trade_id = int(raw_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"analyze_congress_trades task missing trade_id (target_key={task.get('target_key')!r})"
        ) from exc

    model = model_for_backend(backend)

    from ollama_client import OllamaClient
    from postgres_client import PostgresClient
    from scripts.analyze_congress_trades_batch import (
        analyze_trade,
        get_trade_context,
        is_low_risk_asset,
        sync_supabase_conflict_score,
    )
    from supabase_client import SupabaseClient

    supabase = SupabaseClient(use_service_role=True)
    postgres = PostgresClient()

    existing = (
        supabase.supabase.table("congress_trades")
        .select("id,conflict_score")
        .eq("id", trade_id)
        .limit(1)
        .execute()
    )
    rows = existing.data or []
    if not rows:
        raise ValueError(f"congress trade id={trade_id} not found")
    if rows[0].get("conflict_score") is not None:
        logger.info(
            "analyze_congress_trades trade_id=%s already scored (%.3f); skipping",
            trade_id,
            float(rows[0]["conflict_score"]),
        )
        return

    trade_resp = (
        supabase.supabase.table("congress_trades_enriched")
        .select("*")
        .eq("id", trade_id)
        .limit(1)
        .execute()
    )
    trade_rows = trade_resp.data or []
    if not trade_rows:
        raise ValueError(f"congress trade id={trade_id} missing from enriched view")
    trade = trade_rows[0]
    if trade.get("quality_status") == "garbage":
        logger.info(
            "analyze_congress_trades trade_id=%s is quarantine garbage; skipping",
            trade_id,
        )
        return

    if backend == BACKEND_GLM:
        ollama = OllamaClient(force_base_url_only=True)
    else:
        base_url = ollama_base_url_for_backend(backend)
        if not base_url:
            raise RuntimeError(f"No Ollama base URL configured for backend={backend}")
        ollama = OllamaClient(base_url=base_url, force_base_url_only=True)

    context = get_trade_context(supabase, trade)
    is_low_risk, filter_reason = is_low_risk_asset(context)
    if is_low_risk:
        analysis = {
            "conflict_score": 0.0,
            "confidence_score": 1.0,
            "reasoning": f"Auto-filtered: {filter_reason}",
        }
        model_used = "auto-filter"
    else:
        analysis = analyze_trade(
            ollama,
            context,
            model,
            model_chain_override=[model],
        )
        model_used = model

    if not analysis or "conflict_score" not in analysis:
        raise RuntimeError(
            f"analyze_congress_trades returned no score for trade_id={trade_id} on {backend}"
        )

    score = float(analysis["conflict_score"])
    confidence = float(analysis.get("confidence_score", 0.75))
    reasoning = analysis.get("reasoning", "No reasoning provided")

    postgres.execute_update(
        """
        INSERT INTO congress_trades_analysis
            (trade_id, conflict_score, confidence_score, reasoning, model_used, analysis_version)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (trade_id, model_used, analysis_version)
        DO UPDATE SET
            conflict_score = EXCLUDED.conflict_score,
            confidence_score = EXCLUDED.confidence_score,
            reasoning = EXCLUDED.reasoning,
            analyzed_at = NOW()
        """,
        (trade_id, score, confidence, reasoning, model_used, 1),
    )
    sync_supabase_conflict_score(supabase, trade_id, score)
    logger.info(
        "analyze_congress_trades scored trade_id=%s conflict=%.2f confidence=%.2f backend=%s model=%s",
        trade_id,
        score,
        confidence,
        backend,
        model_used,
    )


def enqueue_youtube_transcript_summary_tasks(
    supabase_client: Any,
    videos: Sequence[Mapping[str, Any]],
    *,
    priority: int = 5,
    enqueued_by: str = "cron",
    max_attempts: int = 3,
) -> Dict[str, int]:
    """Enqueue one ``youtube_transcript_summary`` task per landed transcript row.

    Phase K2: the article body is already persisted by the ingest path; the task
    only carries identifiers so the worker can re-read the row and fill in
    summary / CoT fields / tickers. ``target_key`` is the 11-char video id, which
    the ``(analysis_type, target_key)`` active-dedupe index uses to collapse a
    re-enqueue while a task is still pending or leased.

    Transcripts are long (an hour-long call is ~16k summarizer tokens even after
    truncation), so cron-enqueued tasks use a modest priority below ticker/meta
    work — the point of queueing them is to keep them off the inline AI lock, not
    to outrank the nightly analysis chain.
    """

    stats = {"attempted": 0, "enqueued": 0, "failed": 0}
    for video in videos:
        stats["attempted"] += 1
        video_id = str(video.get("video_id") or "").strip()
        article_id = str(video.get("article_id") or "").strip()
        if not video_id or not article_id:
            stats["failed"] += 1
            logger.warning(
                "Skipping youtube_transcript_summary enqueue: missing video_id/article_id (%r)",
                video,
            )
            continue
        try:
            payload: Dict[str, Any] = {
                "video_id": video_id,
                "article_id": article_id,
                "url": str(video.get("url") or ""),
                "expected_tickers": list(video.get("expected_tickers") or []),
                "priority": int(priority),
            }
            if video.get("youtube_source_id") is not None:
                payload["youtube_source_id"] = int(video["youtube_source_id"])
            enqueue_ai_task(
                supabase_client,
                analysis_type=QUEUE_JOB_YOUTUBE_TRANSCRIPT_SUMMARY,
                target_key=video_id,
                payload=payload,
                priority=int(priority),
                enqueued_by=enqueued_by,
                max_attempts=max_attempts,
            )
            stats["enqueued"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.warning(
                "Failed to enqueue youtube_transcript_summary task for %s: %s",
                video_id,
                exc,
            )
    return stats


def youtube_transcript_summary_task_handler(task: Mapping[str, Any], backend: str) -> None:
    """Summarize + ticker-extract one already-saved ``YouTube Transcript`` row.

    Mirrors the other handlers: bound to a single backend/model so cross-backend
    fallback happens by re-leasing rather than an inline chain. The row's
    ``content`` (cleaned captions) is read back from Research Postgres, so a
    retry never needs to re-hit YouTube — which matters because YouTube
    rate-limits caption fetches by IP for hours once tripped.
    """

    payload_raw = task.get("payload")
    payload: Dict[str, Any] = dict(payload_raw) if isinstance(payload_raw, dict) else {}
    video_id = str(payload.get("video_id") or task.get("target_key") or "").strip()
    article_id = str(payload.get("article_id") or "").strip()
    if not video_id:
        raise ValueError("youtube_transcript_summary task missing video_id/target_key")

    from ollama_client import OllamaClient
    from postgres_client import PostgresClient
    from research_repository import ResearchRepository
    from yt_captions import watch_url_for
    from yt_articles import enrich_saved_transcript, is_issuer_channel

    postgres = PostgresClient()
    repo = ResearchRepository(postgres_client=postgres)

    url = str(payload.get("url") or "") or watch_url_for(video_id)
    if article_id:
        rows = postgres.execute_query(
            "SELECT id, title, content, source_metadata FROM research_articles WHERE id = %s",
            (article_id,),
        )
    else:
        rows = postgres.execute_query(
            "SELECT id, title, content, source_metadata FROM research_articles WHERE url = %s",
            (url,),
        )
    if not rows:
        # Terminal: the row was deleted (or retention pruned it) between enqueue
        # and lease. Nothing to enrich and retrying cannot help.
        raise ValueError(
            f"youtube_transcript_summary: no research_articles row for video {video_id}"
        )

    row = rows[0]
    content = str(row.get("content") or "")
    if not content.strip():
        raise ValueError(
            f"youtube_transcript_summary: empty content for video {video_id}"
        )

    meta = row.get("source_metadata") or {}
    if isinstance(meta, str):
        try:
            import json as _json

            meta = _json.loads(meta)
        except Exception:
            meta = {}
    duration_s = None
    if isinstance(meta, dict) and meta.get("duration_s") is not None:
        try:
            duration_s = int(meta["duration_s"])
        except (TypeError, ValueError):
            duration_s = None

    queue_model = model_for_backend(backend)
    if backend == BACKEND_GLM:
        ollama = OllamaClient(force_base_url_only=True)
    else:
        base_url = ollama_base_url_for_backend(backend)
        if not base_url:
            raise RuntimeError(f"No Ollama base URL configured for backend={backend}")
        ollama = OllamaClient(base_url=base_url, force_base_url_only=True)

    def _summarize(
        text: str,
        *,
        article_type: str = "",
        model: str | None = None,
    ) -> Any:
        # Prefer size-aware model from summarize_transcript (GLM for long bodies);
        # fall back to the queue backend's assigned model for short transcripts.
        return ollama.generate_summary(
            text,
            model=model if model is not None else queue_model,
            article_type=article_type,
        )

    enrich_saved_transcript(
        research_repo=repo,
        article_id=str(row["id"]),
        title=str(row.get("title") or ""),
        content=content,
        expected_tickers=[str(t) for t in (payload.get("expected_tickers") or [])],
        owned_tickers=_production_holdings_tickers(),
        duration_s=duration_s,
        # ``normalize_transcript`` stamped alpha_mechanism into source_metadata,
        # so the ticker-lead decision does not need the youtube_sources row here.
        issuer_channel=is_issuer_channel(meta if isinstance(meta, dict) else None),
        ollama_client=ollama,
        summarize_fn=_summarize,
    )
    logger.info(
        "youtube_transcript_summary enriched %s (article=%s) via %s/%s",
        video_id,
        row["id"],
        backend,
        queue_model,
    )


def _production_holdings_tickers() -> list[str]:
    """Tickers held by production funds, for relevance scoring. Empty on failure."""

    try:
        from supabase_client import SupabaseClient

        client = SupabaseClient(use_service_role=True)
        funds = (
            client.supabase.table("funds")
            .select("name")
            .eq("is_production", True)
            .execute()
        )
        names = [f["name"] for f in (funds.data or [])]
        if not names:
            return []
        positions = (
            client.supabase.table("latest_positions")
            .select("ticker")
            .in_("fund", names)
            .execute()
        )
        return sorted({str(p["ticker"]) for p in (positions.data or []) if p.get("ticker")})
    except Exception as exc:
        logger.warning("Could not load production holdings for relevance scoring: %s", exc)
        return []


def enqueue_social_sentiment_analysis_tasks(
    supabase_client: Any,
    session_ids: Sequence[int],
    *,
    priority: int = 0,
    enqueued_by: str = "cron",
    max_attempts: int = 3,
) -> Dict[str, int]:
    """Enqueue one ``social_sentiment_analysis`` task per sentiment session.

    Backfill bulk should use low ``priority`` (default 0) so cron work leases
    first. ``target_key`` is the string session id, giving active-row dedupe
    when the same session is enqueued twice.
    """

    stats = {"attempted": 0, "enqueued": 0, "failed": 0}
    total = len(session_ids)
    progress_every = 500
    for raw_id in session_ids:
        stats["attempted"] += 1
        try:
            session_id = int(raw_id)
        except (TypeError, ValueError):
            stats["failed"] += 1
            continue
        if session_id <= 0:
            stats["failed"] += 1
            continue
        try:
            enqueue_ai_task(
                supabase_client,
                analysis_type=QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS,
                target_key=str(session_id),
                payload={"session_id": session_id, "priority": int(priority)},
                priority=int(priority),
                enqueued_by=enqueued_by,
                max_attempts=max_attempts,
            )
            stats["enqueued"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.warning(
                "Failed to enqueue social_sentiment_analysis task for session_id=%s: %s",
                session_id,
                exc,
            )
        if total > progress_every and stats["attempted"] % progress_every == 0:
            logger.info(
                "Enqueue progress: %s/%s attempted (enqueued=%s failed=%s)",
                stats["attempted"],
                total,
                stats["enqueued"],
                stats["failed"],
            )
    return stats


def social_sentiment_analysis_task_handler(task: Mapping[str, Any], backend: str) -> None:
    """Analyze one sentiment session on the assigned backend."""

    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    raw_id = payload.get("session_id") or task.get("target_key")
    try:
        session_id = int(raw_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "social_sentiment_analysis task missing session_id "
            f"(target_key={task.get('target_key')!r})"
        ) from exc

    model = model_for_backend(backend)

    from ollama_client import OllamaClient
    from social_service import SocialSentimentService

    if backend == BACKEND_GLM:
        # glm-* model ids route to Z.AI transport inside OllamaClient.
        client = OllamaClient(force_base_url_only=True)
    else:
        base_url = ollama_base_url_for_backend(backend)
        if not base_url:
            raise RuntimeError(f"No Ollama base URL configured for backend={backend}")
        client = OllamaClient(base_url=base_url, force_base_url_only=True)

    service = SocialSentimentService(ollama_client=client)
    service.analyze_sentiment_session(session_id, ollama=client, model=model)

    # The service retires every session it is done with, including ones it can
    # never analyze. Still pending means this attempt failed, so raise and let
    # the queue apply its own backoff and attempt accounting.
    rows = service.postgres.execute_query(
        "SELECT needs_ai_analysis FROM sentiment_sessions WHERE id = %s",
        (session_id,),
    )
    if not rows:
        raise ValueError(f"sentiment session id={session_id} not found")
    if rows[0]["needs_ai_analysis"]:
        raise RuntimeError(
            f"social_sentiment_analysis produced no result for session {session_id} "
            f"on {backend}"
        )


def build_task_handlers(enabled_jobs: Iterable[str] = ()) -> Dict[str, TaskHandler]:
    """Build handlers for queue-managed jobs that are enabled in config."""

    jobs = set(enabled_jobs)
    handlers: Dict[str, TaskHandler] = {}
    if QUEUE_JOB_TICKER_ANALYSIS in jobs:
        handlers[QUEUE_JOB_TICKER_ANALYSIS] = ticker_analysis_task_handler
    if QUEUE_JOB_TICKER_META_ANALYSIS in jobs:
        handlers[QUEUE_JOB_TICKER_META_ANALYSIS] = ticker_meta_analysis_task_handler
    if QUEUE_JOB_SECTOR_META_ANALYSIS in jobs:
        handlers[QUEUE_JOB_SECTOR_META_ANALYSIS] = sector_meta_analysis_task_handler
    if QUEUE_JOB_ETF_GROUP_ANALYSIS in jobs:
        handlers[QUEUE_JOB_ETF_GROUP_ANALYSIS] = etf_group_analysis_task_handler
    if QUEUE_JOB_EXECUTIVE_TICKER_RESOLVE in jobs:
        handlers[QUEUE_JOB_EXECUTIVE_TICKER_RESOLVE] = (
            executive_ticker_resolve_task_handler
        )
    if QUEUE_JOB_ANALYZE_CONGRESS_TRADES in jobs:
        handlers[QUEUE_JOB_ANALYZE_CONGRESS_TRADES] = congress_trade_analysis_task_handler
    if QUEUE_JOB_YOUTUBE_TRANSCRIPT_SUMMARY in jobs:
        handlers[QUEUE_JOB_YOUTUBE_TRANSCRIPT_SUMMARY] = (
            youtube_transcript_summary_task_handler
        )
    if QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS in jobs:
        handlers[QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS] = (
            social_sentiment_analysis_task_handler
        )
    return handlers


def build_noop_handlers(enabled_jobs: Iterable[str] = ()) -> Dict[str, TaskHandler]:
    """Backward-compatible alias for tests/old callers; use ``build_task_handlers``."""

    return build_task_handlers(enabled_jobs)
