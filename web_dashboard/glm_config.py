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

import os
from pathlib import Path
from typing import Optional

# Z.AI OpenAI-compatible Coding API (GLM-4.7, Coding Plan)
# Override with ZHIPU_BASE_URL if using general endpoint (e.g. open.bigmodel.cn)
_DEFAULT_ZHIPU_BASE = "https://api.z.ai/api/coding/paas/v4"
ZHIPU_BASE_URL = os.getenv("ZHIPU_BASE_URL", _DEFAULT_ZHIPU_BASE).rstrip("/")
GLM_4_7_MODEL = "glm-4.7"


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
