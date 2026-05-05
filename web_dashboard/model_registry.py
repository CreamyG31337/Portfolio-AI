#!/usr/bin/env python3
"""
Central defaults for GLM / Z.AI model roles (primary, cheap classifier, embeddings).

Production code should read model IDs via the getters here instead of scattering literals.
Bench/eval-only constants are included for scripts under tests/benchmarks and verification/.
"""

from __future__ import annotations

import os
from typing import List

# Same default coding endpoint as glm_config (avoid importing glm_config at module load).
_DEFAULT_ZHIPU_BASE = "https://api.z.ai/api/coding/paas/v4"

PRIMARY_MODEL_DEFAULT = "glm-5.1"
CHEAP_MODEL_DEFAULT = "glm-5-turbo"
EMBED_MODEL_DEFAULT = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest")

# Benchmark / probe lists (not used for automatic production fallback chains).
BENCH_JUDGE_MODEL = os.getenv("AI_BENCH_JUDGE_MODEL", PRIMARY_MODEL_DEFAULT).strip() or PRIMARY_MODEL_DEFAULT
BENCH_DEFAULT_CANDIDATES = os.getenv(
    "OLLAMA_QUALITY_MODELS",
    "granite3.3:8b,qwen3.6:27b,"
    + PRIMARY_MODEL_DEFAULT
    + ","
    + CHEAP_MODEL_DEFAULT
    + ",glm-4.5-air",
).strip()
PROBE_DEFAULT_MODELS: List[str] = [
    PRIMARY_MODEL_DEFAULT,
    CHEAP_MODEL_DEFAULT,
    "glm-5",
    "glm-4.7",
    "glm-4.6",
    "glm-4.5",
    "glm-4.5-air",
]


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
