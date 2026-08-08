"""Ollama context-window helpers: sticky num_ctx, unload, telemetry, budget scaffold.

Shared-GPU note (ts-desktop RTX 3090): Goose and this app share one Ollama host.
Context is fixed at model *load* (``llama-server -c N``), not per request. The first
client to load a model name pins the runner until unload / ``keep_alive`` expiry.
Sending ``num_ctx: 20000`` from this app used to leave a warm 20k runner that starved
Goose of a ~32k window. Prefer sticky 32768 for ``qwen3.6:27b-heretic``.

``/api/show`` and ``/api/ps`` ``context_length`` can disagree with the live slot;
prefer ``prompt_eval_count`` on completed responses as a soft ceiling for that turn.
Truncation is silent and from the front (system/tool preamble dies first).
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence

logger = logging.getLogger(__name__)

# Default for the desktop 3090 heretic Modelfile / Goose alignment.
HERETIC_PREFERRED_NUM_CTX = 32768
DEFAULT_OUTPUT_RESERVE_TOKENS = 4096

_STICKY_NUM_CTX: Dict[str, int] = {}
_STICKY_LOCK = threading.Lock()


def _env_int(name: str) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return None
    try:
        value = int(str(raw).strip())
    except ValueError:
        logger.warning("Ignoring invalid %s=%r (expected int)", name, raw)
        return None
    return value if value > 0 else None


def configured_num_ctx_from_env(model_name: str) -> Optional[int]:
    """Optional env overrides for num_ctx (after model_config, before sticky).

    Resolution:
      1. ``OLLAMA_NUM_CTX_<SANITIZED_MODEL>`` (``:``/``/`` → ``_``)
      2. ``OLLAMA_NUM_CTX`` (global — use carefully; hits every Ollama model)
    """
    sanitized = (
        str(model_name or "")
        .strip()
        .replace(":", "_")
        .replace("/", "_")
        .replace(".", "_")
        .replace("-", "_")
    )
    if sanitized:
        per_model = _env_int(f"OLLAMA_NUM_CTX_{sanitized}")
        if per_model is not None:
            return per_model
    return _env_int("OLLAMA_NUM_CTX")


def resolve_sticky_num_ctx(model_name: str, configured: int) -> int:
    """Return process-sticky num_ctx for ``model_name`` (first request wins).

    Later config drift is ignored so we do not churn Ollama reloads mid-process.
    Call :func:`clear_sticky_num_ctx` (after unload) to intentionally change.
    """
    key = (model_name or "").strip() or "_default"
    configured_i = int(configured)
    with _STICKY_LOCK:
        sticky = _STICKY_NUM_CTX.get(key)
        if sticky is None:
            _STICKY_NUM_CTX[key] = configured_i
            logger.info(
                "[Ollama ctx] sticky num_ctx set model=%s num_ctx=%d",
                key,
                configured_i,
            )
            return configured_i
        if sticky != configured_i:
            logger.warning(
                "[Ollama ctx] sticky num_ctx retained model=%s sticky=%d configured=%d "
                "(unload + clear_sticky_num_ctx to change)",
                key,
                sticky,
                configured_i,
            )
        return sticky


def get_sticky_num_ctx(model_name: str) -> Optional[int]:
    key = (model_name or "").strip() or "_default"
    with _STICKY_LOCK:
        return _STICKY_NUM_CTX.get(key)


def clear_sticky_num_ctx(model_name: Optional[str] = None) -> None:
    """Clear sticky ctx for one model, or all models when ``model_name`` is None."""
    with _STICKY_LOCK:
        if model_name is None:
            _STICKY_NUM_CTX.clear()
            logger.info("[Ollama ctx] cleared all sticky num_ctx entries")
            return
        key = model_name.strip() or "_default"
        removed = _STICKY_NUM_CTX.pop(key, None)
        if removed is not None:
            logger.info(
                "[Ollama ctx] cleared sticky num_ctx model=%s (was %d)",
                key,
                removed,
            )


def compute_prompt_token_budget(
    num_ctx: int,
    *,
    reserved_for_output: int = DEFAULT_OUTPUT_RESERVE_TOKENS,
    measured_ceiling: Optional[int] = None,
) -> int:
    """Tokens available for prompt/history after reserving generation room.

    ``measured_ceiling`` should be a hard observed limit (e.g. prior
    ``prompt_eval_count``) when API-reported context looks wrong.
    """
    ceiling = int(num_ctx)
    if measured_ceiling is not None and int(measured_ceiling) > 0:
        ceiling = min(ceiling, int(measured_ceiling))
    reserve = max(0, int(reserved_for_output))
    return max(0, ceiling - reserve)


def estimate_messages_tokens(messages: Sequence[Mapping[str, Any]]) -> int:
    """Rough token estimate (chars/4) for chat-style messages."""
    total_chars = 0
    for msg in messages:
        content = msg.get("content")
        if content is not None:
            total_chars += len(str(content))
        for key in ("thinking", "think"):
            extra = msg.get(key)
            if extra:
                total_chars += len(str(extra))
    return max(1, total_chars // 4) if total_chars else 0


def compact_messages_to_budget(
    messages: Sequence[Mapping[str, Any]],
    budget_tokens: int,
    *,
    keep_system: bool = True,
) -> List[Dict[str, Any]]:
    """Drop/summarize oldest turns until under ``budget_tokens``.

    Scaffold: currently drops oldest non-system messages (no LLM summarize yet).
    TODO: call existing summarizer path for middle turns instead of hard-drop when
    over budget by a large margin; never assume Goose-style compaction exists here.
    """
    msgs: List[Dict[str, Any]] = [dict(m) for m in messages]
    if budget_tokens <= 0 or estimate_messages_tokens(msgs) <= budget_tokens:
        return msgs

    system: List[Dict[str, Any]] = []
    rest: List[Dict[str, Any]] = []
    for m in msgs:
        if keep_system and str(m.get("role") or "").lower() == "system":
            system.append(m)
        else:
            rest.append(m)

    while rest and estimate_messages_tokens(system + rest) > budget_tokens:
        dropped = rest.pop(0)
        logger.info(
            "[Ollama ctx] compaction dropped oldest turn role=%s chars=%d",
            dropped.get("role"),
            len(str(dropped.get("content") or "")),
        )

    if estimate_messages_tokens(system + rest) > budget_tokens and system:
        # Still over: truncate system content as last resort (front-truncation
        # matches Ollama's silent front-clip hazard — keep the tail).
        sys0 = dict(system[0])
        content = str(sys0.get("content") or "")
        # chars ≈ tokens * 4; keep tail
        keep_chars = max(256, budget_tokens * 4 // 2)
        if len(content) > keep_chars:
            sys0["content"] = (
                "[...system truncated for context budget...]\n" + content[-keep_chars:]
            )
            system[0] = sys0
            logger.warning(
                "[Ollama ctx] compaction truncated system prompt to ~%d chars",
                keep_chars,
            )

    return system + rest


def log_ollama_ctx_telemetry(
    *,
    model: str,
    requested_num_ctx: int,
    response_data: Optional[Mapping[str, Any]] = None,
    ps_context_length: Optional[int] = None,
) -> None:
    """Log requested num_ctx vs response ``prompt_eval_count`` (and optional /api/ps).

    Do not treat ``ps_context_length`` as ground truth alone — it often echoes the
    configured/requested size, not a clamped live slot.
    """
    prompt_eval: Optional[int] = None
    eval_count: Optional[int] = None
    if isinstance(response_data, Mapping):
        pe = response_data.get("prompt_eval_count")
        ec = response_data.get("eval_count")
        try:
            prompt_eval = int(pe) if pe is not None else None
        except (TypeError, ValueError):
            prompt_eval = None
        try:
            eval_count = int(ec) if ec is not None else None
        except (TypeError, ValueError):
            eval_count = None

    logger.info(
        "[Ollama ctx] telemetry model=%s requested_num_ctx=%d prompt_eval_count=%s "
        "eval_count=%s ps_context_length=%s",
        model,
        requested_num_ctx,
        prompt_eval if prompt_eval is not None else "n/a",
        eval_count if eval_count is not None else "n/a",
        ps_context_length if ps_context_length is not None else "n/a",
    )

    if prompt_eval is not None and requested_num_ctx > 0:
        # Far below requested → likely clamped/inherited smaller runner.
        if prompt_eval < int(requested_num_ctx * 0.5):
            logger.warning(
                "[Ollama ctx] prompt_eval_count=%d is far below requested_num_ctx=%d "
                "for model=%s — live runner may be smaller than configured "
                "(unload with keep_alive=0 then reload at sticky ctx)",
                prompt_eval,
                requested_num_ctx,
                model,
            )


def apply_num_ctx_to_options(
    options: MutableMapping[str, Any],
    model_name: str,
    configured_num_ctx: int,
) -> int:
    """Set sticky ``num_ctx`` on an Ollama ``options`` dict; return effective value."""
    effective = resolve_sticky_num_ctx(model_name, configured_num_ctx)
    options["num_ctx"] = effective
    return effective
