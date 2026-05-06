#!/usr/bin/env python3
"""
Ollama API Client
=================

HTTP client for interacting with Ollama API running in Docker.
Supports streaming responses for real-time chat.
"""

import os
import json
import logging
import time
import threading
from typing import Any, Callable, Dict, Generator, List, Optional, Sequence, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from env_loader import load_project_dotenv

from glm_transport import (
    glm_chat_completion,
    glm_chat_completion_text,
    glm_raw_indicates_transport_failure,
    glm_should_try_cheap_fallback,
)
from summary_common import get_summary_system_prompt, parse_summary_response
from prompt_safety import (
    contains_instruction_like_text,
    prepare_untrusted_for_prompt,
    sanitize_for_llm,
)

# Load .env from repo root and web_dashboard (cwd-independent)
load_project_dotenv()

logger = logging.getLogger(__name__)

# Default configuration from environment variables
# Priority: Docker env vars > .env file > Python defaults
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
_explicit_ollama_model = os.getenv("OLLAMA_MODEL", "").strip()
if _explicit_ollama_model:
    OLLAMA_MODEL = _explicit_ollama_model
else:
    try:
        from model_registry import get_primary_model

        OLLAMA_MODEL = get_primary_model()
    except ImportError:
        OLLAMA_MODEL = "glm-5.1"
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
OLLAMA_ENABLED = os.getenv("OLLAMA_ENABLED", "true").lower() == "true"
# Z.AI / GLM HTTP read timeout (seconds). Article summarization uses this; see docs/GLM_ZAI_SUMMARY_TIMING.md.
GLM_TIMEOUT = int(os.getenv("GLM_TIMEOUT", "180"))
# json_mode GLM calls (e.g. LLM-as-judge, structured output) often need longer wall time than chat.
# Effective timeout is max(GLM_TIMEOUT, this value) when json_mode is True on _query_glm.
GLM_JSON_MODE_MIN_TIMEOUT = int(os.getenv("GLM_JSON_MODE_MIN_TIMEOUT", "360"))

# Keep summarization output bounded so prompt + article + output fits model context.
SUMMARY_MIN_PREDICT = 256
SUMMARY_DEFAULT_PREDICT = 1024
SUMMARY_CONTEXT_MARGIN = 256


class OllamaHostBusyError(RuntimeError):
    """Every candidate Ollama base URL had no free per-host inference slot (see env tuning below)."""


_HOST_SLOTS: Dict[str, threading.Semaphore] = {}
_HOST_SLOTS_GUARD = threading.Lock()


def _max_concurrent_per_host() -> int:
    raw = os.getenv("OLLAMA_MAX_CONCURRENT_PER_HOST", "1")
    try:
        return int(raw)
    except ValueError:
        return 1


def _host_slots_enabled() -> bool:
    """When False (``OLLAMA_MAX_CONCURRENT_PER_HOST`` <= 0), slot limiting is disabled."""
    return _max_concurrent_per_host() > 0


def _host_slot_wait_seconds() -> float:
    raw = os.getenv("OLLAMA_HOST_SLOT_WAIT_SEC", "30")
    try:
        return float(raw)
    except ValueError:
        return 30.0


def _host_semaphore(host_key: str) -> threading.Semaphore:
    """Process-local limiter for one Ollama base URL (not shared across Gunicorn workers)."""
    key = host_key.rstrip("/")
    with _HOST_SLOTS_GUARD:
        if key not in _HOST_SLOTS:
            n = max(1, _max_concurrent_per_host())
            _HOST_SLOTS[key] = threading.Semaphore(n)
        return _HOST_SLOTS[key]


def _release_ollama_response_slot(response: Any) -> None:
    """Release a streaming inference slot attached by :meth:`OllamaClient._post_ollama`."""
    if response is None:
        return
    pair = getattr(response, "_ollama_slot_pair", None)
    if not isinstance(pair, tuple) or len(pair) != 2:
        return
    sem, owned = pair
    setattr(response, "_ollama_slot_pair", None)
    if owned and sem is not None:
        sem.release()


def coalesce_ollama_generate_response_text(data: Any) -> str:
    """Return assistant text from a single Ollama ``/api/generate`` JSON object (non-streaming).

    Reasoning/thinking models (e.g. Qwen3 family) sometimes leave ``response`` empty and
    emit content under ``thinking`` or ``think``. Prefer ``response`` when present.
    """
    if not isinstance(data, dict):
        return ""
    err = data.get("error")
    if err:
        logger.warning("Ollama generate JSON error field: %s", err)
    primary = data.get("response")
    if isinstance(primary, str) and primary.strip():
        return primary
    for key in ("thinking", "think"):
        alt = data.get(key)
        if alt is not None and str(alt).strip():
            logger.info(
                "Ollama `response` empty; coalescing from %r (%d chars)",
                key,
                len(str(alt)),
            )
            return str(alt)
    return ""


def ollama_tags_list_contains_model(available_names: Sequence[str], requested: str) -> bool:
    """Return True if Ollama ``/api/tags`` names include ``requested`` (exact or ``name:extra``)."""
    r = (requested or "").strip()
    if not r:
        return True
    names = [str(n).strip() for n in available_names if str(n).strip()]
    if r in names:
        return True
    for n in names:
        if n.startswith(r + ":") or n.startswith(r + "-"):
            return True
    return False


def load_model_config() -> Dict[str, Any]:
    """Load model configuration from JSON file.
    
    Returns:
        Dict containing model settings
    """
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'model_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
                logger.info(f"Loaded configuration for {len(config.get('models', {}))} models")
                return config
        else:
            logger.warning(f"Model config file not found at {config_path}")
            return {}
    except Exception as e:
        logger.error(f"Error loading model config: {e}")
        return {}


def _fit_summary_num_predict(
    *,
    model: str,
    effective_ctx: int,
    prompt_tokens_est: int,
    article_tokens_est: int,
    requested_num_predict: int,
) -> int:
    """Cap summary output tokens to reduce context overflow failures."""
    # Reserve a small margin for tokenizer variance and response framing overhead.
    available = effective_ctx - prompt_tokens_est - article_tokens_est - SUMMARY_CONTEXT_MARGIN
    if available < SUMMARY_MIN_PREDICT:
        logger.warning(
            "Very tight context budget for model=%s: ctx=%d, system≈%d, article≈%d. "
            "Forcing num_predict=%d.",
            model,
            effective_ctx,
            prompt_tokens_est,
            article_tokens_est,
            SUMMARY_MIN_PREDICT,
        )
        return SUMMARY_MIN_PREDICT

    fitted = min(requested_num_predict, available)
    if fitted < requested_num_predict:
        logger.info(
            "Adjusted summary num_predict for model=%s: %d -> %d (ctx fit)",
            model,
            requested_num_predict,
            fitted,
        )
    return max(SUMMARY_MIN_PREDICT, fitted)


# Optional semantic names for dual-Ollama layouts (see env.example). When unset, each maps to the
# legacy pair so existing deployments keep working:
#   OLLAMA_BASE_URL_AMD      → OLLAMA_BASE_URL
#   OLLAMA_BASE_URL_NVIDIA   → OLLAMA_BASE_URL_2
_OLLAMA_HOST_ENV_ALIASES: Dict[str, str] = {
    "OLLAMA_BASE_URL_AMD": "OLLAMA_BASE_URL",
    "OLLAMA_BASE_URL_NVIDIA": "OLLAMA_BASE_URL_2",
}


def _resolve_ollama_host_env(var_name: str) -> Optional[str]:
    """Resolve a host env var, including semantic aliases that fall back to the legacy URL pair."""
    key = str(var_name).strip()
    if not key:
        return None
    raw = os.getenv(key, "").strip().rstrip("/")
    if raw:
        return raw
    legacy = _OLLAMA_HOST_ENV_ALIASES.get(key)
    if legacy:
        raw = os.getenv(legacy, "").strip().rstrip("/")
        if raw:
            return raw
    return None


def _pop_env_url(settings: Dict[str, Any], env_attr: str, url_attr: str) -> None:
    """Resolve optional env indirection for URLs (mutates settings in place).

    If ``env_attr`` names an environment variable that is set and non-empty,
    its value becomes ``url_attr``. Keys ``*_env`` are removed after resolution.
    Semantic keys like ``OLLAMA_BASE_URL_AMD`` fall back to ``OLLAMA_BASE_URL`` when unset.
    """
    env_name = settings.pop(env_attr, None)
    if env_name and str(env_name).strip():
        v = _resolve_ollama_host_env(str(env_name).strip())
        if v:
            settings[url_attr] = v


class OllamaClient:
    """Client for interacting with Ollama API."""
    
    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None):
        """Initialize Ollama client.
        
        Args:
            base_url: Ollama API base URL (defaults to environment variable)
            timeout: Request timeout in seconds (defaults to environment variable)
        """
        candidate_url = base_url or OLLAMA_BASE_URL
        
        # Auto-detect correct URL if default is host.docker.internal but we're running on host
        # Similar to SearXNG client - try localhost if host.docker.internal doesn't resolve
        if "host.docker.internal" in candidate_url:
            try:
                import socket
                socket.gethostbyname("host.docker.internal")
            except (socket.gaierror, OSError):
                # Can't resolve host.docker.internal - we're probably running on host, not in Docker
                logger.info("Could not resolve host.docker.internal, falling back to localhost for Ollama")
                candidate_url = candidate_url.replace("host.docker.internal", "localhost")
        
        self.base_url = candidate_url
        self.timeout = timeout or OLLAMA_TIMEOUT
        self.enabled = OLLAMA_ENABLED
        
        logger.info(f"Ollama client initialized: base_url={self.base_url}, timeout={self.timeout}s, enabled={self.enabled}")
        
        # Create session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST", "GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Load model configuration
        self.model_config = load_model_config()

    def _load_model_config(self) -> Dict[str, Any]:
        """Deprecated: Use global load_model_config() instead."""
        return load_model_config()

    def get_model_settings(self, model_name: str) -> Dict[str, Any]:
        """Get settings for specific model.
        
        Checks database for admin overrides first, then falls back to JSON config.
        
        Args:
            model_name: Name of the model
            
        Returns:
            Dict with settings (num_ctx, temperature, num_predict, etc.)
        """
        models = self.model_config.get('models', {})
        default_config = self.model_config.get('default_config', {})
        
        # Start with JSON defaults (exact match or global defaults)
        if model_name in models:
            settings = models[model_name].copy()
        else:
            settings = default_config.copy()

        _pop_env_url(settings, "base_url_env", "base_url")
        _pop_env_url(settings, "fallback_base_url_env", "fallback_base_url")
        
        # Check database for admin overrides
        try:
            from settings import get_system_setting
            
            # Check for temperature override
            db_temp = get_system_setting(f"model_{model_name}_temperature", default=None)
            if db_temp is not None:
                settings['temperature'] = db_temp
            
            # Check for context window override
            db_ctx = get_system_setting(f"model_{model_name}_num_ctx", default=None)
            if db_ctx is not None:
                settings['num_ctx'] = db_ctx
            
            # Check for max tokens override
            db_predict = get_system_setting(f"model_{model_name}_num_predict", default=None)
            if db_predict is not None:
                settings['num_predict'] = db_predict

            db_base = get_system_setting(f"model_{model_name}_base_url", default=None)
            if db_base is not None and str(db_base).strip():
                settings["base_url"] = str(db_base).strip().rstrip("/")

            db_fb = get_system_setting(f"model_{model_name}_fallback_base_url", default=None)
            if db_fb is not None and str(db_fb).strip():
                settings["fallback_base_url"] = str(db_fb).strip().rstrip("/")

            db_think = get_system_setting(f"model_{model_name}_think", default=None)
            if db_think is not None:
                settings["think"] = db_think

            db_stream = get_system_setting(f"model_{model_name}_streaming_timeout", default=None)
            if db_stream is not None:
                try:
                    settings["streaming_timeout"] = int(db_stream)
                except (TypeError, ValueError):
                    pass
                
        except Exception as e:
            logger.debug(f"Could not load database overrides for {model_name}: {e}")
        
        return settings
        
    def get_model_description(self, model_name: str) -> str:
        """Get description for a model.
        
        Args:
            model_name: Name of the model
            
        Returns:
            Description string
        """
        settings = self.get_model_settings(model_name)
        return settings.get('desc', '')

    def _resolve_urls(self, model: str) -> Tuple[str, Optional[str]]:
        """Return ``(primary_base_url, fallback_base_url_or_none)`` for Ollama HTTP calls."""
        s = self.get_model_settings(model)
        raw_primary = s.get("base_url")
        primary = (str(raw_primary).strip() if raw_primary else "") or self.base_url
        primary = primary.rstrip("/")
        default_norm = self.base_url.rstrip("/")
        fb_raw = s.get("fallback_base_url")
        if fb_raw is not None and str(fb_raw).strip():
            fb = str(fb_raw).strip().rstrip("/")
            if fb != primary:
                return primary, fb
        if primary != default_norm:
            return primary, default_norm
        # When the model uses the default Ollama URL only, still try the optional second host
        # (same pattern as qwen3.6:27b in model_config). _post_ollama retries 404/5xx on fallback.
        env_secondary = os.getenv("OLLAMA_BASE_URL_2", "").strip().rstrip("/")
        if env_secondary and env_secondary != primary:
            return primary, env_secondary
        return primary, None

    def _apply_think_to_payload(self, payload: Dict[str, Any], model_settings: Dict[str, Any]) -> None:
        """Set top-level ``think`` when configured for this model."""
        if "think" in model_settings:
            val = model_settings["think"]
            if val is not None:
                payload["think"] = bool(val)

    def _post_ollama(
        self,
        model: str,
        path: str,
        payload: Dict[str, Any],
        *,
        stream: bool,
    ) -> requests.Response:
        """POST to Ollama; retry on fallback host after connect/timeout/5xx/404.

        When ``OLLAMA_MAX_CONCURRENT_PER_HOST`` > 0, limits in-flight requests per base URL
        inside this process. If a host is saturated longer than
        ``OLLAMA_HOST_SLOT_WAIT_SEC``, tries the next URL for this model; if all are busy,
        raises :class:`OllamaHostBusyError` so callers can try another model/host.

        Streaming responses transfer slot ownership to the returned ``Response``; the slot is
        released when stream helpers close the body (see ``_release_ollama_response_slot``).
        """
        primary, fallback = self._resolve_urls(model)
        candidates = [primary]
        if fallback and fallback.rstrip("/") != primary.rstrip("/"):
            candidates.append(fallback.rstrip("/"))
        last_exc: Optional[BaseException] = None
        n_hosts = len(candidates)
        slot_busy_hosts = 0
        for idx, base in enumerate(candidates):
            url = f"{base.rstrip('/')}{path}"
            sem: Optional[threading.Semaphore] = None
            acquired = False
            r: Optional[requests.Response] = None
            returning_ok = False
            try:
                if _host_slots_enabled():
                    sem = _host_semaphore(base)
                    wait = max(0.0, _host_slot_wait_seconds())
                    if not sem.acquire(timeout=wait):
                        logger.warning(
                            "[Ollama] Inference slot busy on %s (model=%s, waited %.1fs); "
                            "trying next host if any",
                            base,
                            model,
                            wait,
                        )
                        slot_busy_hosts += 1
                        continue
                    acquired = True
                if idx > 0:
                    logger.info("[Ollama] Retrying POST %s on fallback %s (model=%s)", path, base, model)
                r = self.session.post(url, json=payload, stream=stream, timeout=self.timeout)
                if stream and acquired and sem is not None:
                    setattr(r, "_ollama_slot_pair", (sem, True))
                    acquired = False
                r.raise_for_status()
                returning_ok = True
                return r
            except requests.exceptions.ConnectionError as e:
                last_exc = e
                logger.warning("[Ollama] POST %s failed on %s: %s", path, base, e)
            except requests.exceptions.Timeout as e:
                last_exc = e
                logger.warning("[Ollama] POST %s timed out on %s: %s", path, base, e)
            except requests.exceptions.HTTPError as e:
                resp = e.response
                status = resp.status_code if resp is not None else 0
                # 404 on "second GPU" host often means wrong service or stale proxy; try default Ollama.
                if status >= 500 or (status == 404 and idx < n_hosts - 1):
                    last_exc = e
                    logger.warning(
                        "[Ollama] POST %s HTTP %s on %s (model=%s)",
                        path,
                        status,
                        base,
                        model,
                    )
                else:
                    raise
            finally:
                if acquired and sem is not None:
                    sem.release()
                # Streaming slot was transferred to ``r`` (acquired cleared); if we are not
                # returning ``r`` to the caller, release here or slots leak on retryable HTTP.
                if not returning_ok and r is not None:
                    _release_ollama_response_slot(r)
                    try:
                        r.close()
                    except Exception:
                        pass
        if last_exc:
            raise last_exc
        if slot_busy_hosts >= n_hosts:
            raise OllamaHostBusyError(
                f"No free Ollama inference slot on any of {n_hosts} host(s) for model={model}; "
                "increase OLLAMA_MAX_CONCURRENT_PER_HOST, OLLAMA_HOST_SLOT_WAIT_SEC, or use fallback models."
            )
        raise requests.exceptions.RequestException("Ollama POST failed with no exception captured")

    def _stream_generate_response(
        self,
        response: requests.Response,
        *,
        idle_timeout_seconds: float,
        include_thinking: bool,
        request_start_time: float,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Generator[str, None, None]:
        """Stream ``/api/generate`` lines with idle-based timeout and optional thinking chunks."""
        last_chunk_at = time.monotonic()
        timeout_triggered = threading.Event()
        done_event = threading.Event()

        def watchdog() -> None:
            sleep_slice = min(5.0, max(1.0, idle_timeout_seconds / 10))
            while not done_event.is_set():
                time.sleep(sleep_slice)
                if done_event.is_set():
                    return
                if time.monotonic() - last_chunk_at > idle_timeout_seconds:
                    timeout_triggered.set()
                    logger.error(
                        "[ERROR] Ollama streaming idle timeout after %.1fs (no chunks)",
                        idle_timeout_seconds,
                    )
                    try:
                        response.close()
                    except Exception:
                        pass
                    done_event.set()
                    return

        wd = threading.Thread(target=watchdog, daemon=True)
        wd.start()
        tokens_received = 0
        estimated_total_tokens = 800
        thinking_parts: list[str] = []
        yielded_response_text = False
        try:
            for line in response.iter_lines():
                if timeout_triggered.is_set():
                    elapsed = time.time() - request_start_time
                    logger.error(f"[ERROR] Ollama streaming timed out after {elapsed:.2f}s")
                    yield (
                        f"\n\n[ERROR: Streaming timed out after {elapsed:.1f}s - "
                        "response may be incomplete]"
                    )
                    break
                if line:
                    last_chunk_at = time.monotonic()
                    try:
                        chunk_data = json.loads(line)
                        thinking = chunk_data.get("thinking") or chunk_data.get("think")
                        if thinking:
                            thinking_parts.append(str(thinking))
                            logger.info("[Ollama] thinking chunk (%d chars)", len(str(thinking)))
                            if include_thinking:
                                yield f"<think>{thinking}</think>"
                        if "response" in chunk_data:
                            chunk_text = chunk_data["response"] or ""
                            if chunk_text.strip():
                                yielded_response_text = True
                            yield chunk_text
                            tokens_received += len(chunk_text.split())
                            if progress_callback:
                                estimated_progress = min(
                                    95, int((tokens_received / estimated_total_tokens) * 100)
                                )
                                progress_callback(tokens_received, estimated_progress)
                        if chunk_data.get("done", False):
                            if (
                                not yielded_response_text
                                and not include_thinking
                                and thinking_parts
                            ):
                                merged = "".join(thinking_parts)
                                if merged.strip():
                                    logger.info(
                                        "Ollama stream: no `response` tokens; coalescing "
                                        "%d chars from thinking",
                                        len(merged),
                                    )
                                    yield merged
                            if progress_callback:
                                progress_callback(tokens_received, 100)
                            elapsed = time.time() - request_start_time
                            logger.info(f"[OK] Ollama streaming completed in {elapsed:.2f}s")
                            break
                    except json.JSONDecodeError:
                        continue
        finally:
            done_event.set()
            try:
                response.close()
            except Exception:
                pass
            _release_ollama_response_slot(response)

    def _stream_chat_response(
        self,
        response: requests.Response,
        *,
        idle_timeout_seconds: float,
        include_thinking: bool,
        request_start_time: float,
    ) -> Generator[str, None, None]:
        """Stream ``/api/chat`` lines with idle-based timeout and optional thinking content."""
        last_chunk_at = time.monotonic()
        timeout_triggered = threading.Event()
        done_event = threading.Event()

        def watchdog() -> None:
            sleep_slice = min(5.0, max(1.0, idle_timeout_seconds / 10))
            while not done_event.is_set():
                time.sleep(sleep_slice)
                if done_event.is_set():
                    return
                if time.monotonic() - last_chunk_at > idle_timeout_seconds:
                    timeout_triggered.set()
                    logger.error(
                        "[ERROR] Ollama chat streaming idle timeout after %.1fs (no chunks)",
                        idle_timeout_seconds,
                    )
                    try:
                        response.close()
                    except Exception:
                        pass
                    done_event.set()
                    return

        wd = threading.Thread(target=watchdog, daemon=True)
        wd.start()
        thinking_parts: list[str] = []
        yielded_content_text = False
        try:
            for line in response.iter_lines():
                if timeout_triggered.is_set():
                    elapsed = time.time() - request_start_time
                    yield f"\n\n[ERROR: Chat streaming timed out after {elapsed:.1f}s]"
                    break
                if line:
                    last_chunk_at = time.monotonic()
                    try:
                        chunk_data = json.loads(line)
                        msg = chunk_data.get("message") or {}
                        thinking = (
                            msg.get("thinking")
                            or msg.get("think")
                            or chunk_data.get("thinking")
                        )
                        if thinking:
                            thinking_parts.append(str(thinking))
                            logger.info("[Ollama] chat thinking chunk (%d chars)", len(str(thinking)))
                            if include_thinking:
                                yield f"<think>{thinking}</think>"
                        if "content" in msg and msg.get("content") is not None:
                            piece = str(msg["content"])
                            if piece.strip():
                                yielded_content_text = True
                            yield piece
                        if chunk_data.get("done", False):
                            if (
                                not yielded_content_text
                                and not include_thinking
                                and thinking_parts
                            ):
                                merged = "".join(thinking_parts)
                                if merged.strip():
                                    logger.info(
                                        "Ollama chat stream: no content; coalescing %d thinking chars",
                                        len(merged),
                                    )
                                    yield merged
                            elapsed = time.time() - request_start_time
                            logger.info(f"[OK] Ollama chat streaming completed in {elapsed:.2f}s")
                            break
                    except json.JSONDecodeError:
                        continue
        finally:
            done_event.set()
            try:
                response.close()
            except Exception:
                pass
            _release_ollama_response_slot(response)
    
    def check_health(self) -> bool:
        """Check if Ollama API is available.
        
        Returns:
            True if Ollama is reachable, False otherwise
        """
        if not self.enabled:
            return False
        
        try:
            response = self.session.get(
                f"{self.base_url}/api/tags",
                timeout=5
            )
            if response.status_code == 200:
                return True
            else:
                logger.warning(f"Ollama health check failed: HTTP {response.status_code}")
                return False
        except Exception as e:
            logger.warning(f"❌ Ollama health check failed: {e}")
            return False

    def check_health_for_model(self, model: Optional[str] = None) -> bool:
        """Probe ``/api/tags`` on the resolved host and verify ``model`` is listed (when given)."""
        if not self.enabled:
            return False
        if not model:
            return self.check_health()
        primary, _ = self._resolve_urls(model)
        try:
            response = self.session.get(f"{primary}/api/tags", timeout=5)
            if response.status_code != 200:
                logger.warning(
                    "Ollama health check failed for model=%s url=%s: HTTP %s",
                    model,
                    primary,
                    response.status_code,
                )
                return False
            data = response.json()
            if not isinstance(data, dict):
                logger.warning("Ollama /api/tags for model=%s url=%s: unexpected JSON", model, primary)
                return False
            names = [str(m.get("name", "")) for m in data.get("models", []) if m.get("name")]
            if not ollama_tags_list_contains_model(names, str(model)):
                logger.warning(
                    "Ollama at %s does not list model %s. Install with: ollama pull %s. "
                    "Sample of available: %s",
                    primary,
                    model,
                    model,
                    names[:12],
                )
                return False
            return True
        except Exception as e:
            logger.warning("Ollama health check failed for model=%s url=%s: %s", model, primary, e)
            return False
    
    def list_available_models(self) -> List[str]:
        """List all available models in Ollama (unfiltered).
        
        Returns:
            List of all model names from Ollama
        """
        if not self.enabled:
            logger.debug("Model listing skipped: Ollama disabled")
            return []
        
        try:
            logger.debug(f"Fetching available models from {self.base_url}...")
            response = self.session.get(
                f"{self.base_url}/api/tags",
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            models = [model.get("name", "") for model in data.get("models", [])]
            models = [m for m in models if m]  # Filter out empty strings
            logger.info(f"Found {len(models)} Ollama models: {', '.join(models) if models else 'none'}")
            return models
        except Exception as e:
            logger.error(f"❌ Error listing Ollama models: {e}")
            return []
    
    def get_filtered_models(self, include_hidden: bool = False) -> List[str]:
        """Get list of available models, filtered by JSON config.
        
        Filters out models marked as "hidden": true in model_config.json.
        Models not in the JSON config are included by default (backward compatibility).
        
        Args:
            include_hidden: If True, include models marked as hidden
            
        Returns:
            List of model names (filtered)
        """
        all_models = self.list_available_models()
        config_models = self.model_config.get('models', {})
        
        filtered = []
        for model in all_models:
            # If model not in config, include it (backward compatibility)
            if model not in config_models:
                filtered.append(model)
                continue
            
            # Model is in config - check if it's hidden
            model_config = config_models.get(model, {})
            is_hidden = model_config.get('hidden', False)
            
            # Include if not hidden, or if include_hidden=True
            if not is_hidden or include_hidden:
                filtered.append(model)
        
        logger.debug(f"Filtered {len(all_models)} models to {len(filtered)} visible models")
        return filtered
    
    def query_ollama(
        self,
        prompt: str,
        context: str = "",
        model: Optional[str] = None,
        stream: bool = True,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        num_ctx: Optional[int] = None,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
        streaming_timeout: int = 90,
        include_thinking: bool = False,
    ) -> Generator[str, None, None]:
        """Query Ollama API with a prompt and optional context.
        
        Args:
            prompt: User prompt/question
            context: Additional context data (formatted portfolio data, etc.)
            model: Model name to use
            stream: Whether to stream the response
            temperature: Model temperature (0.0-1.0). If None, uses model default.
            max_tokens: Maximum tokens in response (num_predict)
            num_ctx: Context window size. If None, uses model default.
            system_prompt: Optional system prompt to set model behavior
            json_mode: Whether to enforce JSON output format
            streaming_timeout: Max idle seconds between stream chunks (default: 90).
                Overridden by ``streaming_timeout`` in model_config / system_settings when set.
            include_thinking: When True, yield ``<think>...</think>`` for thinking chunks.
            
        Yields:
            Response chunks as strings (streaming) or full response (non-streaming)
        """
        if not model or not str(model).strip():
            try:
                from model_registry import get_primary_model

                model = get_primary_model()
            except ImportError:
                model = "glm-5.1"
        # Route GLM models to Z.AI transport (independent of Ollama availability).
        if model and str(model).startswith("glm-"):
            yield from self._query_glm(
                prompt=prompt,
                context=context,
                model=model,
                stream=stream,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                json_mode=json_mode,
            )
            return

        # Route web-based AI models to WebAI transport (independent of Ollama availability).
        try:
            from webai_wrapper import is_webai_model

            if model and is_webai_model(model):
                yield from self._query_webai(
                    prompt=prompt,
                    context=context,
                    model=model,
                    system_prompt=system_prompt,
                )
                return
        except ImportError:
            pass

        if not self.enabled:
            logger.warning("Ollama query rejected: AI assistant disabled")
            yield "AI assistant is currently disabled."
            return
        
        # Combine context and prompt
        full_prompt = prompt
        if context:
            full_prompt = f"{context}\n\nUser question: {prompt}"
        
        # Get model-specific defaults if values not provided
        model_settings = self.get_model_settings(model)
        
        # Use provided values, or model specific defaults, or global defaults
        effective_temp = temperature if temperature is not None else model_settings.get('temperature', 0.7)
        effective_ctx = num_ctx if num_ctx is not None else model_settings.get('num_ctx', 4096)
        effective_max_tokens = max_tokens if max_tokens is not None else model_settings.get('num_predict', 2048)
        cfg_idle = model_settings.get("streaming_timeout")
        effective_idle = float(cfg_idle) if cfg_idle is not None else float(streaming_timeout)
        
        # Prepare request payload
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": stream,
            "options": {
                "temperature": effective_temp,
                "num_predict": effective_max_tokens,
                "num_ctx": effective_ctx
            }
        }
        
        # Add system prompt if provided
        if system_prompt:
            payload["system"] = system_prompt
            
        # Add format if json_mode is enabled
        if json_mode:
            payload["format"] = "json"

        self._apply_think_to_payload(payload, model_settings)
        
        # Track request timing
        request_start_time = time.time()
        
        try:
            logger.info(
                f"[Ollama] query starting: model={model}, temp={effective_temp}, ctx={effective_ctx}, "
                f"max_tokens={effective_max_tokens}, stream={stream}, idle_timeout={effective_idle}s"
            )
            logger.debug(f"Prompt length: {len(full_prompt)} chars")
            
            response = self._post_ollama(model, "/api/generate", payload, stream=stream)
            
            connection_time = time.time() - request_start_time
            logger.debug(f"Ollama connection established in {connection_time:.2f}s, streaming...")
            
            if stream:
                yield from self._stream_generate_response(
                    response,
                    idle_timeout_seconds=effective_idle,
                    include_thinking=include_thinking,
                    request_start_time=request_start_time,
                )
            else:
                # Non-streaming response
                data = response.json()
                elapsed = time.time() - request_start_time
                logger.info(f"[OK] Ollama request completed in {elapsed:.2f}s")
                yield coalesce_ollama_generate_response_text(data)
                _release_ollama_response_slot(response)
                
        except OllamaHostBusyError:
            raise
        except requests.exceptions.Timeout:
            elapsed = time.time() - request_start_time
            logger.error(f"[ERROR] Ollama request timed out after {elapsed:.2f}s (timeout setting: {self.timeout}s)")
            yield "Request timed out. Please try again with a shorter prompt or context."
        except requests.exceptions.ConnectionError as e:
            elapsed = time.time() - request_start_time
            primary_url, _ = self._resolve_urls(model)
            logger.error(f"[ERROR] Cannot connect to Ollama API at {primary_url} after {elapsed:.2f}s: {e}")
            yield "Cannot connect to AI assistant. Please check if Ollama is running."
        except requests.exceptions.HTTPError as e:
            elapsed = time.time() - request_start_time
            # Provide more helpful error messages for common issues
            if e.response and e.response.status_code == 404:
                # 404 usually means model doesn't exist
                logger.error(f"[ERROR] Ollama API HTTP 404 after {elapsed:.2f}s: Model '{model}' not found. Available models: {', '.join(self.list_available_models()[:5])}")
                yield f"Model '{model}' not found. Please ensure the model is installed: ollama pull {model}"
            else:
                logger.error(f"[ERROR] Ollama API HTTP error after {elapsed:.2f}s: {e}")
                yield f"AI assistant error: {str(e)}"
        except Exception as e:
            elapsed = time.time() - request_start_time
            logger.error(f"[ERROR] Unexpected error querying Ollama after {elapsed:.2f}s: {e}", exc_info=True)
            yield f"An error occurred: {str(e)}"

    def _query_webai(
        self,
        *,
        prompt: str,
        context: str,
        model: str,
        system_prompt: Optional[str],
    ) -> Generator[str, None, None]:
        """Route completion requests to cookie-based WebAI service."""
        try:
            from webai_wrapper import PersistentConversationSession
        except ImportError as e:
            logger.error("WebAI wrapper unavailable: %s", e)
            yield "WebAI backend is not available."
            return

        full_prompt = prompt
        if context:
            full_prompt = f"{context}\n\nUser question: {prompt}"

        # WebAI service currently supports non-streaming sync in this project.
        try:
            session_id = f"chat_{int(time.time())}"
            session = PersistentConversationSession(
                session_id=session_id,
                model=model,
                system_prompt=system_prompt or "",
                auto_refresh=False,
            )
            response = session.send_sync(full_prompt) or ""
            if response:
                yield response
            else:
                yield "WebAI returned an empty response."
            try:
                session.reset_sync()
                session.close_sync()
            except Exception:
                pass
        except Exception as e:
            logger.error("WebAI query failed: %s", e, exc_info=True)
            yield f"WebAI error: {str(e)}"

    def _query_glm(
        self,
        *,
        prompt: str,
        context: str,
        model: str,
        stream: bool,
        temperature: Optional[float],
        max_tokens: Optional[int],
        system_prompt: Optional[str],
        json_mode: bool,
        _cheap_fallback_done: bool = False,
    ) -> Generator[str, None, None]:
        """Route completion requests to Z.AI chat/completions for glm-* models."""
        full_prompt = prompt
        if context:
            full_prompt = f"{context}\n\nUser question: {prompt}"

        model_settings = self.get_model_settings(model)
        effective_temp = temperature if temperature is not None else model_settings.get("temperature", 0.3)
        cfg_cap = model_settings.get("max_tokens") or model_settings.get("num_predict", 2048)
        try:
            cfg_cap_int = int(cfg_cap)
        except (TypeError, ValueError):
            cfg_cap_int = 2048
        effective_max_tokens = max_tokens if max_tokens is not None else cfg_cap_int
        if json_mode:
            effective_max_tokens = max(int(effective_max_tokens), 2048)

        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        elif json_mode:
            messages.append(
                {
                    "role": "system",
                    "content": "Return ONLY a valid raw JSON object. No markdown code fences.",
                }
            )
        messages.append({"role": "user", "content": full_prompt})

        glm_http_timeout = max(GLM_TIMEOUT, GLM_JSON_MODE_MIN_TIMEOUT) if json_mode else GLM_TIMEOUT

        yield from glm_chat_completion(
            messages,
            model=model,
            stream=stream,
            json_mode=json_mode,
            temperature=float(effective_temp),
            max_tokens=int(effective_max_tokens),
            timeout=float(glm_http_timeout),
            allow_cheap_fallback=True,
            _cheap_fallback_done=_cheap_fallback_done,
        )
    
    def generate_completion(
        self,
        prompt: str,
        model: Optional[str] = None,
        json_mode: bool = False,
        temperature: Optional[float] = None
    ) -> Optional[str]:
        """Generate a complete response (non-streaming).
        
        Args:
            prompt: User prompt
            model: Model name
            json_mode: Whether to enforce JSON output
            temperature: Model temperature
            
        Returns:
            Full response string or None if failed
        """
        if not model or not str(model).strip():
            try:
                from model_registry import get_primary_model

                model = get_primary_model()
            except ImportError:
                model = "glm-5.1"
        try:
            text, _used = collect_with_summary_model_chain(
                self,
                prompt=prompt,
                requested_model=model,
                stream=False,
                json_mode=json_mode,
                temperature=temperature,
            )
            return text
        except Exception as e:
            logger.error(f"Error generating completion: {e}")
            return None
    def analyze_crowd_sentiment(self, texts: List[str], ticker: str, model: Optional[str] = None) -> Dict[str, Any]:
        """Analyze crowd sentiment from Reddit posts/comments.
        
        Sends top posts/comments to Ollama for sentiment analysis.
        Returns label only (EUPHORIC, BULLISH, NEUTRAL, BEARISH, FEARFUL).
        Python code maps label to score - do NOT ask AI for numeric score.
        
        Args:
            texts: List of post/comment texts to analyze (top 5)
            ticker: Ticker symbol being analyzed (for context)
            model: Model name to use. If None, uses get_summarizing_model() from settings.
            
        Returns:
            Dictionary containing:
            - sentiment: One of "EUPHORIC", "BULLISH", "NEUTRAL", "BEARISH", "FEARFUL"
            - reasoning: Brief explanation of the sentiment classification
            
            Returns empty dict if generation fails or AI is disabled.
        """
        if not self.enabled:
            logger.warning("Ollama crowd sentiment analysis rejected: AI assistant disabled")
            return {}
        
        if not texts:
            logger.warning("No texts provided for crowd sentiment analysis")
            return {"sentiment": "NEUTRAL", "reasoning": "No posts to analyze"}
        
        # Get model from settings if not provided
        if model is None:
            try:
                from settings import get_summarizing_model
                model = get_summarizing_model()
            except Exception as e:
                logger.warning(f"Could not load summarizing model from settings: {e}, using fallback")
                model = "qwen3.6:27b"

        audit_start = time.time()
        result: Dict[str, Any] = {}
        audit_error: Optional[str] = None
        
        # Sanitize + delimit untrusted social posts before prompt interpolation.
        sanitized_blocks = []
        for idx, text in enumerate(texts[:5], 1):
            safe_text = sanitize_for_llm(text, max_chars=900)
            if contains_instruction_like_text(safe_text):
                logger.warning("Instruction-like text detected in %s social block for %s", idx, ticker)
            sanitized_blocks.append(
                prepare_untrusted_for_prompt(safe_text, source=f"social_post_{idx}")
            )

        combined_text = "\n\n---\n\n".join(sanitized_blocks)
        
        # System prompt - Robust crowd sentiment analysis
        system_prompt = f"""You are an expert financial sentiment analyst specializing in social media momentum. Analyze these posts about {ticker}.

TASK:
1. Read the posts and identify the prevailing emotion and conviction.
2. categorize the overall sentiment into exactly ONE of these labels:
   - EUPHORIC: Extreme irrational exuberance, "moon" talk, massive FOMO.
   - BULLISH: Confidence, buying discussion, positive catalysts.
   - NEUTRAL: Mixed opinions, questions, or balanced bull/bear debate.
   - BEARISH: Selling discussion, negative catalysts, doubt.
   - FEARFUL: Panic selling, despair, "it's over" talk.

OUTPUT FORMAT:
Return ONLY a raw JSON object with no markdown formatting or code blocks:
{{
  "sentiment": "LABEL",
  "reasoning": "One concise sentence explaining why (e.g., 'Users are excited about upcoming earnings' or 'Panic due to recent drop')."
}}"""
        
        try:
            from skill_loader import build_enhanced_prompt

            system_prompt = build_enhanced_prompt(
                system_prompt,
                combined_text,
                "crowd_sentiment",
            )
        except Exception as exc:
            logger.warning("Skill injection failed for crowd sentiment prompt (falling back to base): %s", exc)

        # User prompt with the actual posts
        user_prompt = f"Analyze the sentiment for {ticker} based on these posts:\n\n{combined_text}"
        
        import re

        dynamic_timeout = max(30, min(90, len(combined_text) // 100))
        model_used = model
        full_response = ""

        def _parse_crowd_json(body: str) -> Optional[Dict[str, Any]]:
            json_match = re.search(r'\{[^{}]*"sentiment"[^{}]*\}', body, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                json_str = body.strip()
            json_str = re.sub(r"```json\s*", "", json_str)
            json_str = re.sub(r"```\s*", "", json_str)
            json_str = json_str.strip()
            parsed = json.loads(json_str)
            sentiment = parsed.get("sentiment", "NEUTRAL").strip().upper()
            valid_sentiments = ["EUPHORIC", "BULLISH", "NEUTRAL", "BEARISH", "FEARFUL"]
            if sentiment not in valid_sentiments:
                logger.warning("Invalid sentiment label '%s', defaulting to NEUTRAL", sentiment)
                sentiment = "NEUTRAL"
            return {
                "sentiment": sentiment,
                "reasoning": parsed.get("reasoning", "Sentiment analysis completed"),
            }

        def _crowd_ok(body: str) -> bool:
            if _looks_like_query_ollama_user_facing_error(body):
                return False
            try:
                _parse_crowd_json(body)
                return True
            except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                return False

        try:
            full_response, model_used = collect_with_summary_model_chain(
                self,
                prompt=user_prompt,
                requested_model=model,
                stream=True,
                system_prompt=system_prompt,
                temperature=0.1,
                json_mode=True,
                streaming_timeout=dynamic_timeout,
                response_ok=_crowd_ok,
            )
            if not full_response:
                raise json.JSONDecodeError("empty response", "", 0)
            result = _parse_crowd_json(full_response)
            return result

        except json.JSONDecodeError as e:
            audit_error = str(e)
            logger.error("❌ Failed to parse JSON from Ollama response: %s", e)
            logger.debug("Response was: %s", (full_response or "")[:500])
            result = {"sentiment": "NEUTRAL", "reasoning": "Failed to parse AI response"}
            return result
        except Exception as e:
            audit_error = str(e)
            logger.error("❌ Error analyzing crowd sentiment: %s", e, exc_info=True)
            result = {"sentiment": "NEUTRAL", "reasoning": f"Error: {str(e)}"}
            return result
        finally:
            try:
                from ai_audit import _compute_input_hash, _detect_caller, log_inference

                log_inference(
                    function="analyze_crowd_sentiment",
                    model=model_used,
                    provider="ollama",
                    input_chars=len(combined_text),
                    input_hash=_compute_input_hash(combined_text),
                    output_summary=json.dumps(result, default=str) if result else "",
                    duration_ms=int((time.time() - audit_start) * 1000),
                    success=bool(result.get("sentiment")),
                    error=audit_error,
                    sentiment=result.get("sentiment"),
                    ticker=ticker,
                    caller=_detect_caller(),
                )
            except Exception:
                pass
    
    def generate_summary(
        self,
        text: str,
        model: Optional[str] = None,
        article_type: str = "",
        *,
        num_ctx_override: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate a comprehensive summary with Chain of Thought analysis, sentiment categorization, and relationship extraction.
        
        Uses a 3-step Chain of Thought process: Identify Claims, Fact Check, Conclusion.
        Also categorizes sentiment (VERY_BULLISH, BULLISH, NEUTRAL, BEARISH, VERY_BEARISH) and
        extracts corporate relationships (GraphRAG edges).
        
        Args:
            text: Text to summarize (will be truncated to ~6000 chars)
            model: Model name to use. If None, uses get_summarizing_model() from settings.
            
        Returns:
            Dictionary containing:
            - summary: Enhanced text summary (5-7+ bullet points)
            - claims: List of specific claims with numbers/dates extracted from article
            - fact_check: Simple fact-checking analysis (filters garbage/clickbait)
            - conclusion: Net impact on ticker(s) with specific implications
            - sentiment: One of "VERY_BULLISH", "BULLISH", "NEUTRAL", "BEARISH", "VERY_BEARISH"
            - sentiment_score: Numeric score for calculations (VERY_BULLISH=2.0, BULLISH=1.0, NEUTRAL=0.0, BEARISH=-1.0, VERY_BEARISH=-2.0)
            - logic_check: One of "DATA_BACKED", "HYPE_DETECTED", "NEUTRAL" (for relationship confidence scoring)
            - tickers: List of ticker symbols mentioned (e.g., ["HOOD", "NVDA"])
            - sectors: List of sectors mentioned (e.g., ["Financial Services", "Technology"])
            - key_themes: List of key themes/topics
            - companies: List of company names mentioned
            - relationships: List of relationship dicts with "source", "target", "type" keys (GraphRAG edges)
            
            Returns empty dict if generation fails or AI is disabled.
        """
        if not self.enabled:
            logger.warning("Ollama summary generation rejected: AI assistant disabled")
            return {}
        
        # Get model from settings if not provided
        if model is None:
            try:
                from settings import get_summarizing_model
                model = get_summarizing_model()
            except Exception as e:
                logger.warning(f"Could not load summarizing model from settings: {e}, using fallback")
                model = "qwen3.6:27b"

        # Web-based AI service: use cookie-based service, not Ollama
        try:
            from webai_wrapper import is_webai_model
            if is_webai_model(model):
                return _generate_summary_via_webai(text, model, article_type=article_type, stream=False)
        except ImportError:
            pass
        # GLM: use Z.AI, not Ollama (Ollama would 404 for glm-*)
        if model and str(model).startswith("glm-"):
            return _generate_summary_via_zhipu(text, model, article_type=article_type, stream=False)

        # Truncate text to ~6000 characters
        # TODO: PROMPT-INJECTION - Sanitize scraped article text before LLM ingestion.
        #   Article content from trafilatura/RSS is sent as the raw prompt with no
        #   delimiter-based sandboxing. Hidden text or invisible CSS content in articles
        #   could contain adversarial instructions. Mitigations to add:
        #   1. Strip residual HTML, zero-width chars, and control characters
        #   2. Use structural separation between system instructions and article content
        #   3. Validate that trafilatura output doesn't contain hidden/invisible text artifacts
        max_chars = 6000
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
            logger.debug(f"Truncated text to {max_chars} characters for summarization")

        system_prompt = get_summary_system_prompt(article_text=text, article_type=article_type)

        # Get model settings
        model_settings = self.get_model_settings(model)
        effective_temp = model_settings.get('temperature', 0.3)
        effective_ctx = model_settings.get('num_ctx', 4096)
        if num_ctx_override is not None:
            effective_ctx = int(num_ctx_override)
        requested_max_tokens = model_settings.get("num_predict", SUMMARY_DEFAULT_PREDICT)

        # Warn if skill-enhanced prompt + article + output may overflow context
        prompt_tokens_est = len(system_prompt) // 4
        article_tokens_est = len(text) // 4
        effective_max_tokens = _fit_summary_num_predict(
            model=model,
            effective_ctx=effective_ctx,
            prompt_tokens_est=prompt_tokens_est,
            article_tokens_est=article_tokens_est,
            requested_num_predict=requested_max_tokens,
        )
        total_est = prompt_tokens_est + article_tokens_est + effective_max_tokens
        if total_est > effective_ctx:
            logger.warning(
                "Context window likely exceeded for model=%s: "
                "system≈%d + article≈%d + output=%d = ~%d tokens vs ctx=%d. "
                "Consider increasing num_ctx or reducing skill budget.",
                model, prompt_tokens_est, article_tokens_est,
                effective_max_tokens, total_est, effective_ctx,
            )
        elif total_est > effective_ctx * 0.85:
            logger.info(
                "Context window >85%% full for model=%s: ~%d/%d tokens",
                model, total_est, effective_ctx,
            )

        # Prepare request payload
        payload = {
            "model": model,
            "prompt": text,
            "stream": False,
            "system": system_prompt,
            "options": {
                "temperature": effective_temp,
                "num_predict": effective_max_tokens,
                "num_ctx": effective_ctx
            }
        }
        self._apply_think_to_payload(payload, model_settings)
        
        try:
            start_time = time.time()
            logger.info(f"Generating enhanced summary with model {model}")
            response = self._post_ollama(model, "/api/generate", payload, stream=False)
            
            elapsed_time = time.time() - start_time
            logger.info(f"✅ Summary generated in {elapsed_time:.2f}s")
            
            data = response.json()
            raw_response = coalesce_ollama_generate_response_text(data).strip()

            if not raw_response:
                logger.warning("Empty response from Ollama (no response/thinking text)")
                return {}

            return parse_summary_response(raw_response)

        except requests.exceptions.Timeout:
            logger.error(f"❌ Ollama summary request timed out after {self.timeout}s")
            return {}
        except requests.exceptions.ConnectionError as e:
            primary_url, _ = self._resolve_urls(model)
            logger.error(f"[ERROR] Cannot connect to Ollama API at {primary_url}: {e}")
            return {}
        except Exception as e:
            logger.error(f"❌ Error generating summary: {e}", exc_info=True)
            return {}
    
    def generate_summary_streaming(
        self,
        text: str,
        model: Optional[str] = None,
        article_type: str = "",
        progress_callback=None,
        *,
        num_ctx_override: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate a comprehensive summary with streaming progress updates.

        Same as generate_summary but yields progress updates during generation.
        Use this for Server-Sent Events (SSE) to show real-time progress in the UI.

        Args:
            text: Text to summarize (will be truncated to ~6000 chars)
            model: Model name to use. If None, uses get_summarizing_model() from settings.
            progress_callback: Optional callback function(tokens_received, estimated_progress) called with progress updates

        Returns:
            Same dictionary as generate_summary
        """
        if model is None:
            try:
                from settings import get_summarizing_model
                model = get_summarizing_model()
            except Exception as e:
                logger.warning(f"Could not load summarizing model from settings: {e}, using fallback")
                model = "qwen3.6:27b"

        # Web-based AI service: use cookie-based service, not Ollama (note: doesn't support streaming)
        try:
            from webai_wrapper import is_webai_model
            if is_webai_model(model):
                return _generate_summary_via_webai(
                    text,
                    model,
                    article_type=article_type,
                    progress_callback=progress_callback,
                    stream=False,
                )
        except ImportError:
            pass
        # GLM: use Z.AI, not Ollama
        if model and str(model).startswith("glm-"):
            return _generate_summary_via_zhipu(
                text,
                model,
                article_type=article_type,
                progress_callback=progress_callback,
                stream=True,
            )

        if not self.enabled:
            logger.warning("Ollama summary generation rejected: AI assistant disabled")
            return {}

        # Truncate text to ~6000 characters
        max_chars = 6000
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
            logger.debug(f"Truncated text to {max_chars} characters for summarization")
        
        system_prompt = get_summary_system_prompt(article_text=text, article_type=article_type)

        # Get model settings
        model_settings = self.get_model_settings(model)
        effective_temp = model_settings.get("temperature", 0.3)
        effective_ctx = model_settings.get("num_ctx", 4096)
        if num_ctx_override is not None:
            effective_ctx = int(num_ctx_override)
        requested_max_tokens = model_settings.get("num_predict", SUMMARY_DEFAULT_PREDICT)

        # Warn if skill-enhanced prompt + article + output may overflow context
        prompt_tokens_est = len(system_prompt) // 4
        article_tokens_est = len(text) // 4
        effective_max_tokens = _fit_summary_num_predict(
            model=model,
            effective_ctx=effective_ctx,
            prompt_tokens_est=prompt_tokens_est,
            article_tokens_est=article_tokens_est,
            requested_num_predict=requested_max_tokens,
        )
        total_est = prompt_tokens_est + article_tokens_est + effective_max_tokens
        if total_est > effective_ctx:
            logger.warning(
                "Context window likely exceeded (streaming) for model=%s: "
                "system≈%d + article≈%d + output=%d = ~%d tokens vs ctx=%d. "
                "Consider increasing num_ctx or reducing skill budget.",
                model, prompt_tokens_est, article_tokens_est,
                effective_max_tokens, total_est, effective_ctx,
            )
        elif total_est > effective_ctx * 0.85:
            logger.info(
                "Context window >85%% full (streaming) for model=%s: ~%d/%d tokens",
                model, total_est, effective_ctx,
            )

        # Prepare streaming request payload
        cfg_idle = model_settings.get("streaming_timeout")
        effective_idle = float(cfg_idle) if cfg_idle is not None else 90.0

        payload = {
            "model": model,
            "prompt": text,
            "stream": True,  # Enable streaming!
            "system": system_prompt,
            "options": {
                "temperature": effective_temp,
                "num_predict": effective_max_tokens,
                "num_ctx": effective_ctx
            }
        }
        self._apply_think_to_payload(payload, model_settings)
        
        try:
            start_time = time.time()
            logger.info(f"Generating streaming summary with model {model}")
            
            response = self._post_ollama(model, "/api/generate", payload, stream=True)
            
            # Accumulate response while streaming (idle-based timeout inside helper)
            raw_response = ""
            tokens_received = 0

            def _accumulate_chunk(txt: str) -> None:
                nonlocal raw_response, tokens_received
                raw_response += txt
                tokens_received += len(txt.split())

            for piece in self._stream_generate_response(
                response,
                idle_timeout_seconds=effective_idle,
                include_thinking=False,
                request_start_time=start_time,
                progress_callback=progress_callback,
            ):
                _accumulate_chunk(piece)
            
            elapsed_time = time.time() - start_time
            logger.info(f"✅ Streaming summary generated in {elapsed_time:.2f}s ({tokens_received} tokens)")
            
            # Parse the complete response (same logic as generate_summary)
            if not raw_response:
                logger.warning("Empty response from Ollama")
                return {}
            
            return parse_summary_response(raw_response)

        except requests.exceptions.Timeout:
            logger.error(f"❌ Ollama streaming summary timed out after {self.timeout}s")
            return {}
        except requests.exceptions.ConnectionError as e:
            primary_url, _ = self._resolve_urls(model)
            logger.error(f"[ERROR] Cannot connect to Ollama API at {primary_url}: {e}")
            return {}
        except Exception as e:
            logger.error(f"❌ Error generating streaming summary: {e}", exc_info=True)
            return {}
    
    def generate_embedding(self, text: str, model: str = "nomic-embed-text") -> List[float]:
        """Generate embedding vector for text using Ollama embedding API.
        
        Args:
            text: Text to generate embedding for
            model: Embedding model name (defaults to nomic-embed-text)
            
        Returns:
            List of floats (768 dimensions for nomic-embed-text)
        """
        if not self.enabled:
            logger.warning("Ollama embedding generation rejected: AI assistant disabled")
            return []
        
        # Prepare request payload
        payload = {
            "model": model,
            "prompt": text
        }
        audit_start = time.time()
        embedding: List[float] = []
        audit_error: Optional[str] = None
        
        try:
            logger.debug(f"Generating embedding with model {model}")
            response = self._post_ollama(model, "/api/embeddings", payload, stream=False)
            
            data = response.json()
            embedding = data.get("embedding", [])
            
            if not embedding:
                logger.warning(f"No embedding returned from model {model}")
                return []
            
            logger.debug(f"Generated embedding: {len(embedding)} dimensions")
            return embedding
            
        except requests.exceptions.Timeout:
            audit_error = f"timeout after {self.timeout}s"
            logger.error(f"❌ Ollama embedding request timed out after {self.timeout}s")
            return []
        except requests.exceptions.ConnectionError as e:
            audit_error = str(e)
            primary_url, _ = self._resolve_urls(model)
            logger.error(f"[ERROR] Cannot connect to Ollama API at {primary_url}: {e}")
            return []
        except Exception as e:
            audit_error = str(e)
            logger.error(f"❌ Error generating embedding: {e}", exc_info=True)
            return []
        finally:
            try:
                from ai_audit import _compute_input_hash, _detect_caller, log_inference

                log_inference(
                    function="generate_embedding",
                    model=model,
                    provider="ollama",
                    input_chars=len(text),
                    input_hash=_compute_input_hash(text),
                    output_summary=f"embedding_dims={len(embedding)}" if embedding else "empty",
                    duration_ms=int((time.time() - audit_start) * 1000),
                    success=bool(embedding),
                    error=audit_error,
                    caller=_detect_caller(),
                )
            except Exception:
                pass
    
    def query_ollama_chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = True,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        num_ctx: Optional[int] = None,
        streaming_timeout: int = 90,
        include_thinking: bool = False,
    ) -> Generator[str, None, None]:
        """Query Ollama using chat API format.
        
        Args:
            messages: List of message dicts with "role" and "content" keys
            model: Model name to use
            stream: Whether to stream the response
            temperature: Model temperature (0.0-1.0). If None, uses model default.
            max_tokens: Maximum tokens in response
            num_ctx: Context window size. If None, uses model default.
            streaming_timeout: Max idle seconds between stream chunks (overridden by model config when set).
            include_thinking: Yield ``<think>...</think>`` when the server emits thinking.
            
        Yields:
            Response chunks as strings
        """
        if not self.enabled:
            yield "AI assistant is currently disabled."
            return
        if not model or not str(model).strip():
            try:
                from model_registry import get_primary_model

                model = get_primary_model()
            except ImportError:
                model = "glm-5.1"
        # Get model-specific defaults if values not provided
        model_settings = self.get_model_settings(model)
        
        # Use provided values, or model specific defaults, or global defaults
        effective_temp = temperature if temperature is not None else model_settings.get('temperature', 0.7)
        effective_ctx = num_ctx if num_ctx is not None else model_settings.get('num_ctx', 4096)
        effective_max_tokens = max_tokens if max_tokens is not None else model_settings.get('num_predict', 2048)
        cfg_idle = model_settings.get("streaming_timeout")
        effective_idle = float(cfg_idle) if cfg_idle is not None else float(streaming_timeout)
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": effective_temp,
                "num_predict": effective_max_tokens,
                "num_ctx": effective_ctx
            }
        }
        self._apply_think_to_payload(payload, model_settings)

        request_start_time = time.time()
        try:
            response = self._post_ollama(model, "/api/chat", payload, stream=stream)
            
            if stream:
                yield from self._stream_chat_response(
                    response,
                    idle_timeout_seconds=effective_idle,
                    include_thinking=include_thinking,
                    request_start_time=request_start_time,
                )
            else:
                data = response.json()
                msg = data.get("message") or {}
                thinking = msg.get("thinking") or msg.get("think")
                if thinking:
                    logger.info("[Ollama] chat thinking (%d chars)", len(str(thinking)))
                    if include_thinking:
                        yield f"<think>{thinking}</think>"
                content = msg.get("content")
                if content and str(content).strip():
                    yield str(content)
                elif (
                    thinking
                    and str(thinking).strip()
                    and not include_thinking
                ):
                    logger.info(
                        "Ollama chat non-stream: empty content; coalescing thinking (%d chars)",
                        len(str(thinking)),
                    )
                    yield str(thinking)
                _release_ollama_response_slot(response)

        except OllamaHostBusyError:
            raise
        except Exception as e:
            logger.error(f"Error in chat API: {e}")
            yield f"An error occurred: {str(e)}"


# Global client instance
_ollama_client: Optional[OllamaClient] = None


def get_ollama_client() -> Optional[OllamaClient]:
    """Get or create global Ollama client instance.
    
    Returns:
        OllamaClient instance or None if disabled
    """
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient()
    return _ollama_client if _ollama_client.enabled else None


def check_ollama_health() -> bool:
    """Check if Ollama is available.

    Returns:
        True if Ollama is reachable
    """
    client = get_ollama_client()
    return client.check_health() if client else False


def _generate_summary_via_webai(
    text: str,
    model: str,
    *,
    article_type: str = "",
    progress_callback=None,
    stream: bool = False
) -> Dict[str, Any]:
    """Run article summarization via web-based AI service (cookie-based). Used for WebAI models."""
    try:
        from webai_wrapper import PersistentConversationSession
        from summary_common import get_summary_system_prompt, parse_summary_response
    except ImportError:
        logger.warning("webai_wrapper or summary_common not available for web-based AI summary")
        return {}

    max_chars = 6000
    original_len = len(text)
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
        logger.debug(f"Truncated text from {original_len} to {max_chars} characters for web-based AI summarization")

    system_prompt = get_summary_system_prompt(article_text=text, article_type=article_type)
    total_chars = len(system_prompt) + len(text)
    logger.debug(f"Web-based AI prompt length: {total_chars} chars (system: {len(system_prompt)}, user: {len(text)})")

    # Note: Web-based AI service doesn't support streaming, so stream parameter is ignored
    if stream and progress_callback:
        progress_callback(0, 10)  # Indicate start

    timeout_sec = GLM_TIMEOUT
    start_time = time.time()
    logger.info(
        f"🤖 Web-based AI summary query starting: model={model}, "
        f"stream=False (not supported), timeout={timeout_sec}s"
    )

    try:
        # Create a temporary session for this summarization task
        # Use a unique session ID based on timestamp to avoid conversation history
        session_id = f"summary_{int(time.time())}"
        session = PersistentConversationSession(
            session_id=session_id,
            model=model,
            system_prompt=system_prompt,
            auto_refresh=False,
        )

        # Combine system prompt and article text (web-based service needs instructions in message)
        full_message = f"{system_prompt}\n\nArticle to analyze:\n\n{text}"

        if progress_callback:
            progress_callback(len(full_message), 30)  # Indicate sending

        conn_start = time.time()
        raw = session.send_sync(full_message)
        connection_time = time.time() - conn_start
        elapsed = time.time() - start_time

        # Clean up session
        try:
            session.reset_sync()
            session.close_sync()
        except Exception:
            pass  # Ignore cleanup errors

        logger.info(f"✅ Web-based AI summary completed in {elapsed:.2f}s (connection: {connection_time:.2f}s)")

        if progress_callback:
            progress_callback(len(raw), 100)

        if not raw or not raw.strip():
            logger.warning("Empty response from web-based AI service")
            return {}
        return parse_summary_response(raw.strip())

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            f"❌ Web-based AI summary request failed after {elapsed:.2f}s: {e}",
            exc_info=True,
        )
        return {}


def _generate_summary_via_zhipu(
    text: str,
    model: str,
    *,
    article_type: str = "",
    progress_callback=None,
    stream: bool = False
) -> Dict[str, Any]:
    """Run article summarization via Z.AI /chat/completions. Used when model.startswith('glm-')."""
    try:
        from glm_config import get_zhipu_api_key
        from summary_common import get_summary_system_prompt, parse_summary_response
    except ImportError:
        logger.warning("glm_config or summary_common not available for GLM summary")
        return {}

    key = get_zhipu_api_key()
    if not key or not key.strip():
        logger.warning("Z.AI API key not set - cannot generate summary with GLM model")
        return {}

    max_chars = 6000
    original_len = len(text)
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
        logger.debug(f"Truncated text from {original_len} to {max_chars} characters for Z.AI summarization")

    system_prompt = get_summary_system_prompt(article_text=text, article_type=article_type)
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text},
    ]
    total_chars = len(system_prompt) + len(text)
    logger.debug(f"Z.AI prompt length: {total_chars} chars (system: {len(system_prompt)}, user: {len(text)})")

    cfg_path = os.path.join(os.path.dirname(__file__), "model_config.json")
    me: Dict[str, Any] = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                mc = json.load(f)
            me = (mc.get("models") or {}).get(model, mc.get("default_config") or {})
        except Exception:
            pass
    max_tokens = int(me.get("max_tokens") or me.get("num_predict") or 1024)
    temperature = float(me.get("temperature", 0.3))

    timeout_sec = float(GLM_TIMEOUT)
    start_time = time.time()
    logger.info(
        "🤖 Z.AI summary query starting: model=%s, temp=%s, max_tokens=%s, stream=%s, timeout=%ss",
        model,
        temperature,
        max_tokens,
        stream,
        timeout_sec,
    )

    raw = ""
    tokens_received = 0
    try:
        for chunk in glm_chat_completion(
            messages,
            model=model,
            stream=stream,
            json_mode=False,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout_sec,
            allow_cheap_fallback=False,
        ):
            if chunk:
                raw += chunk
                if stream:
                    tokens_received += len(chunk.split())
                    if progress_callback:
                        progress_callback(len(raw), min(95, len(raw) // 10))
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "❌ Z.AI summary error after %.2fs: %s",
            elapsed,
            e,
            exc_info=True,
        )
        return {}

    elapsed = time.time() - start_time
    if stream:
        if progress_callback:
            progress_callback(len(raw), 100)
        logger.info(
            "✅ Z.AI streaming summary completed in %.2fs (%d tokens)",
            elapsed,
            tokens_received,
        )
    else:
        logger.info("✅ Z.AI summary request completed in %.2fs", elapsed)

    stripped = (raw or "").strip()
    if not stripped:
        logger.warning("Empty response from Z.AI")
        return {}
    if glm_raw_indicates_transport_failure(stripped):
        logger.warning("Z.AI summary transport failed (no parse): %s", stripped[:240])
        return {}
    return parse_summary_response(stripped)


def generate_summary(
    text: str, model: Optional[str] = None, article_type: str = ""
) -> Dict[str, Any]:
    """Module-level summary entry with provider/model fallback support."""
    model_chain = _get_summary_model_chain(model)
    if not model_chain:
        logger.error("No summary models available for generation")
        return {}

    for idx, candidate in enumerate(model_chain, start=1):
        logger.info(
            "Summary attempt %s/%s using model=%s",
            idx,
            len(model_chain),
            candidate,
        )
        try:
            result = _generate_summary_once(
                text=text,
                model=candidate,
                article_type=article_type,
                stream=False,
                progress_callback=None,
            )
        except OllamaHostBusyError:
            logger.warning(
                "Summary: all Ollama hosts busy for model=%s; trying next in chain",
                candidate,
            )
            continue
        if _has_summary_output(result):
            logger.info("Summary generated successfully with model=%s", candidate)
            return result
        logger.warning("Summary attempt failed/empty for model=%s", candidate)

    head = model_chain[0] if model_chain else None
    tried = {str(c).strip() for c in model_chain if c}
    try:
        from model_registry import get_cheap_model

        cheap = (get_cheap_model() or "").strip()
    except Exception:
        cheap = ""
    if (
        head
        and str(head).strip().startswith("glm-")
        and cheap
        and cheap not in tried
        and glm_should_try_cheap_fallback(
            model=str(head).strip(),
            cheap_fallback_done=False,
            http_status=None,
        )
    ):
        logger.info("Summary chain exhausted; trying cheap GLM model=%s", cheap)
        try:
            result = _generate_summary_once(
                text=text,
                model=cheap,
                article_type=article_type,
                stream=False,
                progress_callback=None,
            )
        except OllamaHostBusyError:
            result = {}
        if _has_summary_output(result):
            logger.info("Summary generated successfully with cheap model=%s", cheap)
            return result

    logger.error("All summary attempts failed across model chain: %s", model_chain)
    return {}


def generate_summary_streaming(
    text: str,
    model: Optional[str] = None,
    article_type: str = "",
    progress_callback=None
) -> Dict[str, Any]:
    """Module-level streaming summary entry with provider/model fallback support."""
    model_chain = _get_summary_model_chain(model)
    if not model_chain:
        logger.error("No summary models available for streaming generation")
        return {}

    for idx, candidate in enumerate(model_chain, start=1):
        logger.info(
            "Streaming summary attempt %s/%s using model=%s",
            idx,
            len(model_chain),
            candidate,
        )
        try:
            result = _generate_summary_once(
                text=text,
                model=candidate,
                article_type=article_type,
                stream=True,
                progress_callback=progress_callback,
            )
        except OllamaHostBusyError:
            logger.warning(
                "Streaming summary: all Ollama hosts busy for model=%s; trying next in chain",
                candidate,
            )
            continue
        if _has_summary_output(result):
            logger.info("Streaming summary generated successfully with model=%s", candidate)
            return result
        logger.warning("Streaming summary attempt failed/empty for model=%s", candidate)

    head = model_chain[0] if model_chain else None
    tried = {str(c).strip() for c in model_chain if c}
    try:
        from model_registry import get_cheap_model

        cheap = (get_cheap_model() or "").strip()
    except Exception:
        cheap = ""
    if (
        head
        and str(head).strip().startswith("glm-")
        and cheap
        and cheap not in tried
        and glm_should_try_cheap_fallback(
            model=str(head).strip(),
            cheap_fallback_done=False,
            http_status=None,
        )
    ):
        logger.info("Streaming summary chain exhausted; trying cheap GLM model=%s", cheap)
        try:
            result = _generate_summary_once(
                text=text,
                model=cheap,
                article_type=article_type,
                stream=True,
                progress_callback=progress_callback,
            )
        except OllamaHostBusyError:
            result = {}
        if _has_summary_output(result):
            logger.info("Streaming summary generated successfully with cheap model=%s", cheap)
            return result

    logger.error("All streaming summary attempts failed across model chain: %s", model_chain)
    return {}


def _has_summary_output(result: Any) -> bool:
    """True when a summary result is non-empty and usable."""
    if isinstance(result, str):
        return bool(result.strip())
    if isinstance(result, dict):
        summary = result.get("summary", "")
        return isinstance(summary, str) and bool(summary.strip())
    return False


def _get_summary_model_chain(requested_model: Optional[str]) -> List[str]:
    """Build ordered model chain: primary model followed by configured (DB/env) fallbacks only."""
    primary = requested_model
    fallback_models: List[str] = []
    try:
        from settings import get_summarizing_model, get_summarizing_fallback_models

        if not primary:
            primary = get_summarizing_model()
        fallback_models = get_summarizing_fallback_models()
    except Exception as e:
        logger.warning("Could not load summarization settings: %s", e)
        if not primary:
            primary = "qwen3.6:27b"
        fallback_models = []

    chain = [primary] + fallback_models
    ordered: List[str] = []
    seen: set[str] = set()
    for m in chain:
        if not m:
            continue
        s = str(m).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        ordered.append(s)

    # Drop glm-* fallbacks when Z.AI is flaky; keep primary model even if it is glm-*.
    if os.getenv("SUMMARY_SKIP_GLM_FALLBACK", "").strip().lower() in ("1", "true", "yes", "on"):
        if ordered:
            head, tail = ordered[0], ordered[1:]
            tail = [x for x in tail if not str(x).strip().startswith("glm-")]
            ordered = [head] + tail

    return ordered


def _looks_like_query_ollama_user_facing_error(text: str) -> bool:
    """True when :meth:`OllamaClient.query_ollama` likely yielded a failure message, not model output."""
    t = (text or "").strip()
    if not t:
        return True
    if t.startswith("{"):
        return False
    low = t.lower()
    markers = (
        "ai assistant is currently disabled",
        "not found. please ensure the model is installed",
        "request timed out. please try again",
        "cannot connect to ai assistant",
        "ai assistant error:",
        "an error occurred:",
    )
    return any(m in low for m in markers)


def collect_with_summary_model_chain(
    ollama: OllamaClient,
    *,
    prompt: str,
    context: str = "",
    requested_model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    json_mode: bool = False,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    num_ctx: Optional[int] = None,
    stream: bool = True,
    streaming_timeout: int = 90,
    include_thinking: bool = False,
    response_ok: Optional[Callable[[str], bool]] = None,
) -> Tuple[Optional[str], str]:
    """Run :meth:`OllamaClient.query_ollama` across the summarization model chain until success.

    Uses :func:`_get_summary_model_chain` (primary + configured fallbacks, including GLM when listed).
    On each candidate, tries the next model when the body is empty, matches
    :func:`_looks_like_query_ollama_user_facing_error`, or ``response_ok`` returns False.

    Returns:
        ``(full_text, model_used)`` on success, or ``(None, last_model_tried)`` if every candidate fails.
    """
    chain = _get_summary_model_chain(requested_model)
    if not chain:
        logger.error("collect_with_summary_model_chain: empty model chain")
        return None, ""

    def _default_ok(body: str) -> bool:
        if _looks_like_query_ollama_user_facing_error(body):
            return False
        return bool((body or "").strip())

    ok_fn = response_ok or _default_ok
    last_model = chain[-1]
    for idx, candidate in enumerate(chain, start=1):
        last_model = candidate
        full = ""
        try:
            for chunk in ollama.query_ollama(
                prompt=prompt,
                context=context,
                model=candidate,
                stream=stream,
                temperature=temperature,
                max_tokens=max_tokens,
                num_ctx=num_ctx,
                system_prompt=system_prompt,
                json_mode=json_mode,
                streaming_timeout=streaming_timeout,
                include_thinking=include_thinking,
            ):
                full += chunk
        except OllamaHostBusyError:
            logger.warning(
                "collect_with_summary_model_chain: hosts busy for model=%s (%s/%s); trying next",
                candidate,
                idx,
                len(chain),
            )
            continue
        except Exception as exc:
            logger.warning(
                "collect_with_summary_model_chain: error for model=%s (%s/%s): %s",
                candidate,
                idx,
                len(chain),
                exc,
            )
            continue

        if ok_fn(full):
            if idx > 1:
                logger.info(
                    "collect_with_summary_model_chain: success with model=%s (attempt %s/%s)",
                    candidate,
                    idx,
                    len(chain),
                )
            return full, candidate

        logger.warning(
            "collect_with_summary_model_chain: response not acceptable for model=%s (%s/%s)",
            candidate,
            idx,
            len(chain),
        )

    return None, last_model


def _generate_summary_once(
    text: str,
    model: str,
    *,
    article_type: str = "",
    stream: bool,
    progress_callback=None,
    num_ctx_override: Optional[int] = None,
) -> Dict[str, Any]:
    """Generate a summary once for the specified model/provider."""
    start_ms = time.time()
    result: Dict[str, Any] = {}
    error_msg: Optional[str] = None

    try:
        # Web-based AI service
        try:
            from webai_wrapper import is_webai_model

            if is_webai_model(model):
                result = _generate_summary_via_webai(
                    text,
                    model,
                    article_type=article_type,
                    progress_callback=progress_callback,
                    stream=False,
                )
                return result
        except ImportError:
            pass

        # GLM via Z.AI
        if model.startswith("glm-"):
            result = _generate_summary_via_zhipu(
                text,
                model,
                article_type=article_type,
                progress_callback=progress_callback,
                stream=stream,
            )
            return result

        # Ollama model
        client = get_ollama_client()
        if not client:
            logger.warning("Ollama client unavailable for model=%s", model)
            return {}
        if stream:
            result = client.generate_summary_streaming(
                text,
                model=model,
                article_type=article_type,
                progress_callback=progress_callback,
                num_ctx_override=num_ctx_override,
            )
            return result
        result = client.generate_summary(
            text,
            model=model,
            article_type=article_type,
            num_ctx_override=num_ctx_override,
        )
        return result
    except Exception as e:
        error_msg = str(e)
        raise
    finally:
        try:
            from ai_audit import (
                _compute_input_hash,
                _detect_caller,
                _detect_provider,
                get_audit_context,
                log_inference,
            )

            context = get_audit_context()
            log_inference(
                function="generate_summary",
                model=model,
                provider=_detect_provider(model),
                input_chars=len(text),
                input_hash=_compute_input_hash(text),
                output_summary=(result.get("summary", "") or "")
                if isinstance(result, dict)
                else "",
                duration_ms=int((time.time() - start_ms) * 1000),
                success=bool(result) and error_msg is None,
                error=error_msg,
                tickers_extracted=result.get("tickers") if isinstance(result, dict) else None,
                sentiment=result.get("sentiment") if isinstance(result, dict) else None,
                logic_check=result.get("logic_check") if isinstance(result, dict) else None,
                market_relevance=result.get("market_relevance") if isinstance(result, dict) else None,
                caller=_detect_caller(),
                article_type=article_type or None,
                article_url=context.get("article_url"),
                article_title=context.get("article_title"),
            )
        except Exception:
            pass


def list_available_models(include_hidden: bool = False) -> List[str]:
    """
    List all available AI models for selection.

    By default, excludes models marked as "hidden": true in model_config.json.
    Models not in the JSON config are included (backward compatibility).
    Also includes WebAI web-based model options.

    Args:
        include_hidden: If True, include models marked as hidden

    Returns:
        List of model names (filtered, includes WebAI variants)
    """
    models = []
    client = get_ollama_client()
    if client:
        models = client.get_filtered_models(include_hidden=include_hidden)
    
    # Add web-based AI model options
    try:
        from webai_wrapper import get_webai_models
        for webai_model in get_webai_models():
            if webai_model not in models:
                models.append(webai_model)
    except ImportError:
        pass

    # Add GLM models only when Zhipu API key is set (optional)
    try:
        from glm_config import get_zhipu_api_key, get_glm_models

        if get_zhipu_api_key():
            for m in get_glm_models():
                if m not in models:
                    models.append(m)
    except ImportError:
        pass

    return models
