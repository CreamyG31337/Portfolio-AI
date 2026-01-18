#!/usr/bin/env python3
"""
Test GLM 4.7 (Zhipu / Z.AI) API from the dev machine.

No Flask, no browser. Verifies:
- Key resolution (ZHIPU_API_KEY, GLM_4_API_KEY, or .secrets file)
- Optional GET /models and /v1/models (logs if supported)
- POST /chat/completions with glm-4.7

Usage:
    python debug/test_glm_api.py

Requires ZHIPU_API_KEY in project root .env, web_dashboard/.env, or
web_dashboard/.secrets/zhipu_api_key.
"""

import sys
from pathlib import Path

# Project root and .env loading
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv(project_root / ".env", override=True)
load_dotenv(project_root / "web_dashboard" / ".env", override=True)

# Now import glm_config (needs env/secrets from above)
from web_dashboard.glm_config import (
    get_zhipu_api_key,
    ZHIPU_BASE_URL,
    GLM_4_7_MODEL,
    get_glm_models,
)

import requests


def main() -> int:
    print("=" * 60)
    print("GLM 4.7 (Zhipu / Z.AI) API test")
    print("=" * 60)

    key = get_zhipu_api_key()
    if not key or not key.strip():
        print("ZHIPU_API_KEY or GLM_4_API_KEY (or web_dashboard/.secrets/zhipu_api_key) must be set.")
        print("Add to project root .env, web_dashboard/.env, or save via AI Settings.")
        return 1

    print(f"Key: {key[:12]}...{key[-4:]}")
    print(f"Base: {ZHIPU_BASE_URL}")
    print(f"Model: {GLM_4_7_MODEL}")
    print(f"Models (from API cache or static): {get_glm_models()}")
    print()

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    # Optional: try GET /models and /v1/models
    for path in ("/models", "/v1/models"):
        url = f"{ZHIPU_BASE_URL.rstrip('/')}{path}"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                ids = []
                if isinstance(data, dict) and "data" in data:
                    ids = [o.get("id", "") for o in (data["data"] or []) if isinstance(o, dict)]
                elif isinstance(data, dict) and "model" in data:
                    ids = [data.get("model", "")]
                print(f"GET {path} OK. Summary: {ids[:5] if ids else 'unknown shape'}")
                break
        except Exception as e:
            print(f"GET {path} error: {e}")
    else:
        print("GET /models and /v1/models not supported or error; using static list.")

    # POST /chat/completions
    chat_url = f"{ZHIPU_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": GLM_4_7_MODEL,
        "messages": [{"role": "user", "content": "Say OK in one word."}],
        "max_tokens": 10,
        "stream": False,
    }
    try:
        r = requests.post(chat_url, json=payload, headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
            print(f"Chat OK. Reply: {repr((content or '').strip())[:80]}")
        else:
            err = r.text
            try:
                err = r.json().get("error", {}).get("message", err)
            except Exception:
                pass
            print(f"Chat error ({r.status_code}): {str(err)[:200]}")
            return 1
    except Exception as e:
        print(f"Chat request failed: {e}")
        return 1

    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
