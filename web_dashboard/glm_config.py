#!/usr/bin/env python3
"""
GLM / Zhipu / Z.AI configuration and API key loading (GLM-5.x, 4.7, 4.5, etc.).

Uses the Z.AI OpenAI-compatible Coding API by default:
  https://api.z.ai/api/coding/paas/v4

Supports:
- ZHIPU_API_KEY or GLM_4_API_KEY environment variable
- File: web_dashboard/.secrets/zhipu_api_key (written from AI Settings UI)
- ZHIPU_BASE_URL to override (e.g. https://open.bigmodel.cn/api/paas/v4 for general)
"""

import json
import os
import stat
import time
from pathlib import Path
from typing import List, Optional

import requests

from env_loader import load_project_dotenv

load_project_dotenv()

# Allowlist: order = rough preference for UI; only ids also returned by GET /models are shown.
# GLM-5.x / 4.6 availability depends on Z.AI plan; keys that recently lacked 5.x may need cache refresh.
GLM_ALLOWED: List[str] = [
    "glm-5.2",
    "glm-5.1",
    "glm-5-turbo",
    "glm-5",
    "glm-4.7",
    "glm-4.6",
    "glm-4.5",
    "glm-4.5-air",
]
# Static list when API is unavailable
GLM_MODELS: List[str] = ["glm-5.2", "glm-5.1", "glm-5-turbo", "glm-4.5-air"]

# Z.AI OpenAI-compatible Coding API (GLM-4.7, Coding Plan)
# Override with ZHIPU_BASE_URL if using general endpoint (e.g. open.bigmodel.cn)
_DEFAULT_ZHIPU_BASE = "https://api.z.ai/api/coding/paas/v4"
ZHIPU_BASE_URL = os.getenv("ZHIPU_BASE_URL", _DEFAULT_ZHIPU_BASE).rstrip("/")
# Legacy export name (admin smoke + scripts); static default — prefer model_registry.get_primary_model().
from model_registry import PRIMARY_MODEL_DEFAULT as GLM_4_7_MODEL  # noqa: E402

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


def _read_glm_models_cache() -> List[str]:
    """Return allowlisted GLM ids from cache if fresh, else []."""
    now = time.time()
    if not _CACHE_FILE.exists():
        return []
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        fetched = data.get("fetched_at", 0) or 0
        if not isinstance(fetched, (int, float)) or (now - float(fetched)) >= _CACHE_TTL_SEC:
            return []
        models = data.get("models") or []
        if not isinstance(models, list) or not models:
            return []
        out = [m for m in GLM_ALLOWED if m in models]
        return out if out else []
    except (OSError, json.JSONDecodeError):
        return []


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
    cached = _read_glm_models_cache()
    if cached:
        return cached

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
            json.dump({"models": out, "fetched_at": time.time()}, f, indent=0)
    except OSError:
        pass

    return out if out else list(GLM_MODELS)


def get_glm_models(*, refresh: bool = True) -> List[str]:
    """Return GLM model list: from fetch cache/API when key is set, else static GLM_MODELS.

    When ``refresh=False`` (model picker / UI), use cache or static list only — no live
    Z.AI round-trip so ticker-details and AI Assistant load quickly even if Z.AI is slow.
    """
    if not get_zhipu_api_key():
        return list(GLM_MODELS)
    if not refresh:
        cached = _read_glm_models_cache()
        return cached if cached else list(GLM_MODELS)
    return fetch_zhipu_models()


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
    Sets file permissions to 600 (read/write by owner only).

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
        # Secure the file: read/write by owner only (Unix). On Windows this is
        # best-effort; ignore errors so we never crash (e.g. network drives).
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return True
    except OSError:
        return False
