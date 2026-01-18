#!/usr/bin/env python3
"""
GLM 4.7 (Zhipu / Z.AI) configuration and API key loading.

Uses the Z.AI OpenAI-compatible Coding API by default:
  https://api.z.ai/api/coding/paas/v4

Supports:
- ZHIPU_API_KEY or GLM_4_API_KEY environment variable
- File: web_dashboard/.secrets/zhipu_api_key (written from AI Settings UI)
- ZHIPU_BASE_URL to override (e.g. https://open.bigmodel.cn/api/paas/v4 for general)
"""

import json
import os
import time
from pathlib import Path
from typing import List, Optional

import requests

# Allowlist: only these are shown (4.7 = best quality, 4.5-air = fast/light)
GLM_ALLOWED: List[str] = ["glm-4.7", "glm-4.5-air"]
# Static list when API is unavailable
GLM_MODELS: List[str] = ["glm-4.7", "glm-4.5-air"]

# Z.AI OpenAI-compatible Coding API (GLM-4.7, Coding Plan)
# Override with ZHIPU_BASE_URL if using general endpoint (e.g. open.bigmodel.cn)
_DEFAULT_ZHIPU_BASE = "https://api.z.ai/api/coding/paas/v4"
ZHIPU_BASE_URL = os.getenv("ZHIPU_BASE_URL", _DEFAULT_ZHIPU_BASE).rstrip("/")
GLM_4_7_MODEL = "glm-4.7"

# Cache for models from GET /models (TTL 24h)
_CACHE_DIR = Path(__file__).resolve().parent / ".cache"
_CACHE_FILE = _CACHE_DIR / "glm_models.json"
_CACHE_TTL_SEC = 24 * 3600


def _get_secrets_path() -> Path:
    """Path to the zhipu_api_key file (web_dashboard/.secrets/zhipu_api_key)."""
    base = Path(__file__).resolve().parent
    return base / ".secrets" / "zhipu_api_key"


def get_zhipu_api_key() -> Optional[str]:
    """
    Get Zhipu/GLM-4 API key from environment or secrets file.

    Order: ZHIPU_API_KEY env -> GLM_4_API_KEY env -> .secrets/zhipu_api_key file.

    Returns:
        API key string if set, None otherwise.
    """
    key = os.getenv("ZHIPU_API_KEY") or os.getenv("GLM_4_API_KEY")
    if key and key.strip():
        return key.strip()

    path = _get_secrets_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                return content
        except OSError:
            pass
    return None


def fetch_zhipu_models() -> List[str]:
    """
    Fetch model ids from Z.AI GET /models or /v1/models; cache to .cache/glm_models.json.
    Returns cached list if fresh (< 24h), else fetches, updates cache, and returns.
    On failure: returns cached if valid, else GLM_MODELS.
    """
    key = get_zhipu_api_key()
    if not key or not key.strip():
        return list(GLM_MODELS)

    # Read cache
    now = time.time()
    if _CACHE_FILE.exists():
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            fetched = data.get("fetched_at", 0) or 0
            if isinstance(fetched, (int, float)) and (now - float(fetched)) < _CACHE_TTL_SEC:
                models = data.get("models") or []
                if isinstance(models, list) and models:
                    # Only return allowed models, in preferred order
                    out = [m for m in GLM_ALLOWED if m in models]
                    if out:
                        return out
        except (OSError, json.JSONDecodeError):
            pass

    # Fetch from API
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    base = ZHIPU_BASE_URL.rstrip("/")
    ids: List[str] = []
    for path in ("/models", "/v1/models"):
        try:
            r = requests.get(f"{base}{path}", headers=headers, timeout=10)
            if r.status_code == 200:
                d = r.json()
                if isinstance(d, dict) and "data" in d:
                    for o in d.get("data") or []:
                        if isinstance(o, dict):
                            mid = o.get("id") or o.get("model") or ""
                            if mid and isinstance(mid, str) and mid.strip().startswith("glm-"):
                                ids.append(mid.strip())
                if ids:
                    break
        except Exception:
            continue
    if not ids:
        ids = list(GLM_MODELS)

    # Restrict to allowlist, preferred order
    out = [m for m in GLM_ALLOWED if m in ids]
    if not out:
        out = list(GLM_MODELS)

    # Write cache
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"models": out, "fetched_at": now}, f, indent=0)
    except OSError:
        pass

    return out if out else list(GLM_MODELS)


def get_glm_models() -> List[str]:
    """Return GLM model list: from fetch cache/API when key is set, else static GLM_MODELS."""
    if get_zhipu_api_key():
        return fetch_zhipu_models()
    return list(GLM_MODELS)


def get_zhipu_api_key_source() -> Optional[str]:
    """
    Return where the key was loaded from: 'env' or 'file', or None if not set.
    """
    if os.getenv("ZHIPU_API_KEY") or os.getenv("GLM_4_API_KEY"):
        return "env"
    if _get_secrets_path().exists():
        return "file"
    return None


def save_zhipu_api_key(api_key: str) -> bool:
    """
    Save API key to .secrets/zhipu_api_key. Caller must ensure path is safe.

    Returns:
        True if saved successfully, False otherwise.
    """
    if not api_key or not api_key.strip():
        return False
    path = _get_secrets_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(api_key.strip())
        return True
    except OSError:
        return False
