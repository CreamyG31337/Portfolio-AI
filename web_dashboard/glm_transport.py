#!/usr/bin/env python3
"""
Shared Z.AI / GLM HTTP transport (OpenAI-compatible chat/completions).

All production glm-* HTTP paths should use this module so multi-base failover,
retryable HTTP statuses (including 500), and optional cheap-model fallback stay
consistent. Does not route WebAI or Ollama.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Generator, List, Optional

import requests

from env_loader import load_project_dotenv

load_project_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_GLM_TIMEOUT = int(os.getenv("GLM_TIMEOUT", "180"))
_DEFAULT_GLM_JSON_MIN = int(os.getenv("GLM_JSON_MODE_MIN_TIMEOUT", "360"))


def _effective_timeout(*, json_mode: bool, timeout: Optional[float]) -> float:
    if timeout is not None:
        return float(timeout)
    base = float(_DEFAULT_GLM_TIMEOUT)
    jmin = float(_DEFAULT_GLM_JSON_MIN)
    return max(base, jmin) if json_mode else base


def glm_raw_indicates_transport_failure(raw: str) -> bool:
    """True when ``raw`` is a known GLM transport error (not model summary JSON/text)."""
    s = (raw or "").strip()
    if not s:
        return False
    if s.startswith("GLM API error:"):
        return True
    if s.startswith("GLM error:"):
        return True
    return s in (
        "GLM backend is not available.",
        "GLM API key is not configured.",
        "GLM returned an empty response.",
        "GLM request timed out. Please try again.",
        "Cannot connect to GLM API.",
        "GLM error: all configured Z.AI base URLs failed.",
    )


def glm_should_try_cheap_fallback(
    *,
    model: str,
    cheap_fallback_done: bool,
    http_status: Optional[int] = None,
) -> bool:
    """After primary glm-* fails, optionally retry once with ``get_cheap_model()`` (same API key)."""
    if cheap_fallback_done:
        return False
    flag = os.getenv("GLM_FALLBACK_TO_CHEAP_MODEL", "true").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if http_status in (401, 403):
        return False
    try:
        from model_registry import get_cheap_model

        cheap = (get_cheap_model() or "").strip()
    except Exception:
        return False
    cur = (model or "").strip()
    if not cheap.startswith("glm-") or cheap == cur:
        return False
    return True


def _yield_cheap_fallback(
    messages: List[Dict[str, Any]],
    *,
    model: str,
    stream: bool,
    json_mode: bool,
    temperature: float,
    max_tokens: int,
    timeout: Optional[float],
    allow_cheap_fallback: bool,
) -> Generator[str, None, None]:
    from model_registry import get_cheap_model

    cheap = (get_cheap_model() or "").strip()
    logger.warning("GLM failed for model=%s; retrying once with cheap model=%s", model, cheap)
    yield from glm_chat_completion(
        messages,
        model=cheap,
        stream=stream,
        json_mode=json_mode,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        allow_cheap_fallback=allow_cheap_fallback,
        _cheap_fallback_done=True,
    )


def glm_chat_completion(
    messages: List[Dict[str, Any]],
    *,
    model: str,
    stream: bool = False,
    json_mode: bool = False,
    temperature: float,
    max_tokens: int,
    timeout: Optional[float] = None,
    allow_cheap_fallback: bool = True,
    _cheap_fallback_done: bool = False,
) -> Generator[str, None, None]:
    """POST /chat/completions to Z.AI; yield content chunks (stream or single non-stream body)."""
    try:
        from glm_config import get_zhipu_api_key
        from model_registry import get_glm_base_urls, zai_http_status_retryable
    except ImportError as e:
        logger.error("GLM config unavailable: %s", e)
        yield "GLM backend is not available."
        return

    key = get_zhipu_api_key()
    if not key:
        logger.error("GLM API key not configured")
        yield "GLM API key is not configured."
        return

    eff_max = int(max_tokens)
    if json_mode:
        eff_max = max(eff_max, 2048)

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "max_tokens": eff_max,
        "temperature": float(temperature),
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    glm_http_timeout = _effective_timeout(json_mode=json_mode, timeout=timeout)

    bases = get_glm_base_urls()
    for bi, z_base in enumerate(bases):
        url = f"{z_base.rstrip('/')}/chat/completions"
        request_start = time.time()
        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                stream=stream,
                timeout=glm_http_timeout,
            )
            sc = int(response.status_code)
            if zai_http_status_retryable(sc) and bi < len(bases) - 1:
                logger.info(
                    "GLM host %s returned HTTP %s; retrying next base URL (%s/%s)",
                    z_base,
                    sc,
                    bi + 2,
                    len(bases),
                )
                continue
            response.raise_for_status()

            if stream:
                for line in response.iter_lines(decode_unicode=True):
                    if not line or not line.strip():
                        continue
                    s = line.strip()
                    if not s.startswith("data: "):
                        continue
                    data = s[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        for choice in (obj.get("choices") or [])[:1]:
                            delta = choice.get("delta") or {}
                            part = delta.get("content") or ""
                            if part:
                                yield part
                            if choice.get("finish_reason") == "stop":
                                return
                    except json.JSONDecodeError:
                        continue
                return
            data = response.json()
            msg = ((data.get("choices") or [{}])[0].get("message") or {})
            content = str(msg.get("content") or "").strip()
            if content:
                yield content
                return
            reasoning = str(
                msg.get("reasoning_content") or msg.get("reasoning") or ""
            ).strip()
            if reasoning:
                logger.info(
                    "GLM non-stream: empty message.content; yielding reasoning_content (%d chars)",
                    len(reasoning),
                )
                yield reasoning
                return
            if allow_cheap_fallback and glm_should_try_cheap_fallback(
                model=model,
                cheap_fallback_done=_cheap_fallback_done,
                http_status=None,
            ):
                yield from _yield_cheap_fallback(
                    messages,
                    model=model,
                    stream=stream,
                    json_mode=json_mode,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    allow_cheap_fallback=allow_cheap_fallback,
                )
                return
            yield "GLM returned an empty response."
            return
        except requests.exceptions.Timeout:
            elapsed = time.time() - request_start
            if bi < len(bases) - 1:
                logger.info(
                    "GLM request timed out after %.2fs on %s; trying next base (%s/%s)",
                    elapsed,
                    z_base,
                    bi + 2,
                    len(bases),
                )
                continue
            logger.error("GLM request timed out after %.2fs", elapsed)
            if allow_cheap_fallback and glm_should_try_cheap_fallback(
                model=model,
                cheap_fallback_done=_cheap_fallback_done,
                http_status=None,
            ):
                yield from _yield_cheap_fallback(
                    messages,
                    model=model,
                    stream=stream,
                    json_mode=json_mode,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    allow_cheap_fallback=allow_cheap_fallback,
                )
                return
            yield "GLM request timed out. Please try again."
            return
        except requests.exceptions.ConnectionError as e:
            elapsed = time.time() - request_start
            if bi < len(bases) - 1:
                logger.info(
                    "GLM connection error after %.2fs on %s (%s); trying next base (%s/%s)",
                    elapsed,
                    z_base,
                    e,
                    bi + 2,
                    len(bases),
                )
                continue
            logger.error("GLM connection error after %.2fs: %s", elapsed, e)
            if allow_cheap_fallback and glm_should_try_cheap_fallback(
                model=model,
                cheap_fallback_done=_cheap_fallback_done,
                http_status=None,
            ):
                yield from _yield_cheap_fallback(
                    messages,
                    model=model,
                    stream=stream,
                    json_mode=json_mode,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    allow_cheap_fallback=allow_cheap_fallback,
                )
                return
            yield "Cannot connect to GLM API."
            return
        except requests.exceptions.HTTPError as e:
            elapsed = time.time() - request_start
            resp_sc = int(e.response.status_code) if getattr(e, "response", None) is not None else 0
            if resp_sc and zai_http_status_retryable(resp_sc) and bi < len(bases) - 1:
                logger.info(
                    "GLM HTTP %s after %.2fs on %s; trying next base (%s/%s)",
                    resp_sc,
                    elapsed,
                    z_base,
                    bi + 2,
                    len(bases),
                )
                continue
            logger.error("GLM HTTP error after %.2fs: %s", elapsed, e)
            if allow_cheap_fallback and glm_should_try_cheap_fallback(
                model=model,
                cheap_fallback_done=_cheap_fallback_done,
                http_status=resp_sc or None,
            ):
                yield from _yield_cheap_fallback(
                    messages,
                    model=model,
                    stream=stream,
                    json_mode=json_mode,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    allow_cheap_fallback=allow_cheap_fallback,
                )
                return
            yield f"GLM API error: {str(e)}"
            return
        except Exception as e:
            elapsed = time.time() - request_start
            logger.error("Unexpected GLM query error after %.2fs: %s", elapsed, e, exc_info=True)
            if allow_cheap_fallback and glm_should_try_cheap_fallback(
                model=model,
                cheap_fallback_done=_cheap_fallback_done,
                http_status=None,
            ):
                yield from _yield_cheap_fallback(
                    messages,
                    model=model,
                    stream=stream,
                    json_mode=json_mode,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    allow_cheap_fallback=allow_cheap_fallback,
                )
                return
            yield f"GLM error: {str(e)}"
            return

    if allow_cheap_fallback and glm_should_try_cheap_fallback(
        model=model,
        cheap_fallback_done=_cheap_fallback_done,
        http_status=None,
    ):
        yield from _yield_cheap_fallback(
            messages,
            model=model,
            stream=stream,
            json_mode=json_mode,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            allow_cheap_fallback=allow_cheap_fallback,
        )
        return
    yield "GLM error: all configured Z.AI base URLs failed."


def glm_chat_completion_text(
    messages: List[Dict[str, Any]],
    *,
    model: str,
    stream: bool = False,
    json_mode: bool = False,
    temperature: float,
    max_tokens: int,
    timeout: Optional[float] = None,
    allow_cheap_fallback: bool = True,
) -> str:
    """Non-streaming convenience: full response body as a single string."""
    return "".join(
        glm_chat_completion(
            messages,
            model=model,
            stream=stream,
            json_mode=json_mode,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            allow_cheap_fallback=allow_cheap_fallback,
        )
    )
