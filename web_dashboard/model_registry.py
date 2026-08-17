#!/usr/bin/env python3
"""
Central defaults for GLM / Z.AI model roles (primary, cheap classifier, embeddings).

Production code should read model IDs via the getters here instead of scattering literals.
Bench/eval-only constants are included for scripts under tests/benchmarks and verification/.
"""

from __future__ import annotations

import os
from typing import List, Optional

# Same default coding endpoint as glm_config (avoid importing glm_config at module load).
_DEFAULT_ZHIPU_BASE = "https://api.z.ai/api/coding/paas/v4"

PRIMARY_MODEL_DEFAULT = "glm-5.2"
CHEAP_MODEL_DEFAULT = "glm-5-turbo"

# GLM ids exposed in UI pickers (Z.AI Coding Plan).
SUPPORTED_GLM_MODELS: List[str] = [
    "glm-5.2",
    "glm-5.1",
    "glm-5-turbo",
    "glm-4.5-air",
]

# Stock Qwen3.8 27B (vision+tools+thinking+MTP). No heretic tag in this app.
OLLAMA_QWEN38_STOCK = "qwen3.8:27b-mtp-q4_K_M"

# Retired GLM ids + deleted Qwen3.6 / unused heretic tags mapped on read.
DEPRECATED_MODEL_MAP: dict[str, str] = {
    "glm-4.7": PRIMARY_MODEL_DEFAULT,
    "glm-4.6": PRIMARY_MODEL_DEFAULT,
    "glm-4.5": PRIMARY_MODEL_DEFAULT,
    "glm-5": PRIMARY_MODEL_DEFAULT,
    "qwen3.6:27b-heretic": OLLAMA_QWEN38_STOCK,
    "qwen3.6:27b-heretic-agentic": OLLAMA_QWEN38_STOCK,
    "qwen3.8:27b-heretic": OLLAMA_QWEN38_STOCK,
}
# Local Ollama roles (summarization primary + queue worker defaults).
OLLAMA_SUMMARIZING_DEFAULT = OLLAMA_QWEN38_STOCK
OLLAMA_QUEUE_PRIMARY_DEFAULT = "granite4.1:8b"
OLLAMA_QUEUE_SECONDARY_DEFAULT = OLLAMA_QWEN38_STOCK
EMBED_MODEL_DEFAULT = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")
EMBED_DIM_DEFAULT = int(os.getenv("AI_EMBED_DIM", "1024"))
EMBED_MAX_CHARS_DEFAULT = int(os.getenv("AI_EMBED_MAX_CHARS", "24000"))

# Benchmark / probe lists (not used for automatic production fallback chains).
BENCH_JUDGE_MODEL = os.getenv("AI_BENCH_JUDGE_MODEL", PRIMARY_MODEL_DEFAULT).strip() or PRIMARY_MODEL_DEFAULT
BENCH_DEFAULT_CANDIDATES = os.getenv(
    "OLLAMA_QUALITY_MODELS",
    f"{OLLAMA_QUEUE_PRIMARY_DEFAULT},{OLLAMA_SUMMARIZING_DEFAULT},"
    + PRIMARY_MODEL_DEFAULT
    + ","
    + CHEAP_MODEL_DEFAULT
    + ",glm-4.5-air",
).strip()
PROBE_DEFAULT_MODELS: List[str] = [
    PRIMARY_MODEL_DEFAULT,
    "glm-5.1",
    CHEAP_MODEL_DEFAULT,
    "glm-5",
    "glm-4.7",
    "glm-4.6",
    "glm-4.5",
    "glm-4.5-air",
]


def remap_deprecated_model(model_id: Optional[str]) -> str:
    """Map deleted/retired model tags to their replacements (identity if unknown)."""
    candidate = (model_id or "").strip()
    if not candidate:
        return ""
    return DEPRECATED_MODEL_MAP.get(candidate, candidate)


def resolve_ai_model_preference(
    stored: Optional[str],
    available_ids: Optional[List[str]] = None,
) -> str:
    """Normalize a stored model id: apply deprecation map, then clamp to available list."""
    candidate = (stored or "").strip()
    if not candidate:
        candidate = get_primary_model()

    candidate = remap_deprecated_model(candidate)

    if available_ids is not None:
        available = [m for m in available_ids if m]
        if available and candidate not in available:
            primary = get_primary_model()
            if primary in available:
                return primary
            return available[0]

    return candidate


def get_primary_model() -> str:
    """Preferred GLM id for most production workloads (chat, jobs using flagship)."""
    env = os.getenv("AI_PRIMARY_MODEL", "").strip()
    if env:
        return env
    try:
        from settings import get_system_setting

        v = get_system_setting("ai_primary_model", default=None)
        if v and str(v).strip():
            return str(v).strip()
    except Exception:
        pass
    return PRIMARY_MODEL_DEFAULT


def get_cheap_model() -> str:
    """High-volume / classification-style GLM (e.g. article relevance)."""
    env = os.getenv("AI_CHEAP_MODEL", "").strip()
    if env:
        return env
    try:
        from settings import get_system_setting

        v = get_system_setting("ai_cheap_model", default=None)
        if v and str(v).strip():
            return str(v).strip()
    except Exception:
        pass
    return CHEAP_MODEL_DEFAULT


def get_ollama_queue_primary_model() -> str:
    """Ollama model pinned to AI queue ``ollama_primary`` workers."""
    env = os.getenv("AI_QUEUE_MODEL_OLLAMA_PRIMARY", "").strip()
    return remap_deprecated_model(env) or OLLAMA_QUEUE_PRIMARY_DEFAULT


def get_ollama_queue_secondary_model() -> str:
    """Ollama model pinned to AI queue ``ollama_secondary`` workers."""
    env = os.getenv("AI_QUEUE_MODEL_OLLAMA_SECONDARY", "").strip()
    return remap_deprecated_model(env) or OLLAMA_QUEUE_SECONDARY_DEFAULT


def get_builtin_summarizing_fallback_models() -> List[str]:
    """Built-in summarization fallback tail when DB/env fallbacks are unset."""
    return [
        OLLAMA_QUEUE_PRIMARY_DEFAULT,
        OLLAMA_QUEUE_SECONDARY_DEFAULT,
        get_primary_model(),
    ]


def get_embed_model() -> str:
    """Dedicated embedding model (separate from chat GLM)."""
    env = os.getenv("AI_EMBED_MODEL", "").strip()
    if env:
        return env
    try:
        from settings import get_system_setting

        v = get_system_setting("ai_embed_model", default=None)
        if v and str(v).strip():
            return str(v).strip()
    except Exception:
        pass
    return EMBED_MODEL_DEFAULT


def get_embed_dim() -> int:
    """Expected vector width for the configured embedding model."""
    env = os.getenv("AI_EMBED_DIM", "").strip()
    if env:
        return int(env)
    try:
        from settings import get_system_setting

        v = get_system_setting("ai_embed_dim", default=None)
        if v and str(v).strip():
            return int(str(v).strip())
    except Exception:
        pass
    return EMBED_DIM_DEFAULT


def get_embed_max_chars() -> int:
    """Maximum input characters sent to the embedding model."""
    env = os.getenv("AI_EMBED_MAX_CHARS", "").strip()
    if env:
        return int(env)
    try:
        from settings import get_system_setting

        v = get_system_setting("ai_embed_max_chars", default=None)
        if v and str(v).strip():
            return int(str(v).strip())
    except Exception:
        pass
    return EMBED_MAX_CHARS_DEFAULT


def get_glm_base_urls() -> List[str]:
    """
    Ordered Z.AI / OpenAI-compatible base URLs for chat/completions.

    Primary: ZHIPU_BASE_URL or coding API default. Additional hosts from
    ZHIPU_BASE_URL_FALLBACKS (comma-separated), deduplicated.
    """
    primary = os.getenv("ZHIPU_BASE_URL", _DEFAULT_ZHIPU_BASE).strip().rstrip("/")
    out: List[str] = []
    if primary:
        out.append(primary)
    raw = os.getenv("ZHIPU_BASE_URL_FALLBACKS", "").strip()
    if raw:
        for part in raw.split(","):
            p = part.strip().rstrip("/")
            if p and p not in out:
                out.append(p)
    if not out:
        out.append(_DEFAULT_ZHIPU_BASE.rstrip("/"))
    return out


def zai_http_status_retryable(status_code: int) -> bool:
    """HTTP statuses where we try the next Z.AI base URL with the same model."""
    # 500 included: Z.AI frequently returns transient internal errors.
    return status_code in (429, 500, 502, 503, 504)


def zai_error_text_probably_transient(text: str) -> bool:
    """True when a glm failure body suggests retry (same judge model), not bad JSON from the model."""
    t = (text or "").lower()
    needles = (
        "glm api error",
        "500 server error",
        "502 server error",
        "503 server error",
        "504",
        "429",
        "timed out",
        "timeout",
        "cannot connect to glm",
        "connection error",
        "internal server error",
    )
    return any(n in t for n in needles)
