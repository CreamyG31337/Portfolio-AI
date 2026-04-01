#!/usr/bin/env python3
"""Probe Z.AI / Zhipu endpoints for available models and glm-5 eligibility.

Uses the same key resolution as the app (env + web_dashboard/.env via glm_config).
Does not print secrets. Safe to run locally; ignore in production pipelines.

Usage (from repo root):
  python web_dashboard/scripts/probe_zhipu_models.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

# Allow imports from web_dashboard package
_WEB = Path(__file__).resolve().parent.parent
if str(_WEB) not in sys.path:
    sys.path.insert(0, str(_WEB))

from glm_config import ZHIPU_BASE_URL, get_zhipu_api_key  # noqa: E402

GENERAL_ZAI = "https://api.z.ai/api/paas/v4"


def _glm_ids_from_models_payload(data: object) -> list[str]:
    out: list[str] = []
    if not isinstance(data, dict):
        return out
    for o in data.get("data") or []:
        if not isinstance(o, dict):
            continue
        mid = o.get("id") or o.get("model") or ""
        if isinstance(mid, str) and mid.strip().startswith("glm-"):
            out.append(mid.strip())
    return sorted(set(out))


def main() -> int:
    key = get_zhipu_api_key()
    if not key:
        print("No API key: set ZHIPU_API_KEY / GLM_4_API_KEY or .secrets/zhipu_api_key")
        return 1

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    configured = ZHIPU_BASE_URL.rstrip("/")
    bases = [configured]
    if GENERAL_ZAI.rstrip("/") not in bases:
        bases.append(GENERAL_ZAI.rstrip("/"))

    print("Configured ZHIPU_BASE_URL:", configured)
    print("--- GET model list (OpenAI-style paths) ---")
    for base in bases:
        for path in ("/models", "/v1/models"):
            url = f"{base}{path}"
            try:
                r = requests.get(url, headers=headers, timeout=20)
            except requests.RequestException as e:
                print(f"  {url} -> ERROR {e}")
                continue
            if r.status_code != 200:
                print(f"  {url} -> HTTP {r.status_code}")
                continue
            try:
                ids = _glm_ids_from_models_payload(r.json())
            except json.JSONDecodeError:
                print(f"  {url} -> 200 but non-JSON body")
                continue
            print(f"  {url} -> glm-* ids ({len(ids)}): {', '.join(ids) if ids else '(none in response)'}")

    print("--- POST smoke test (minimal chat) ---")
    # glm-5-flash is not a valid id on this API (1211); glm-5-turbo / glm-5.1 may vary by plan.
    test_models = ["glm-5", "glm-5-turbo", "glm-5.1", "glm-4.7", "glm-4.5-air"]
    for base in bases:
        url = f"{base.rstrip('/')}/chat/completions"
        for model in test_models:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                "max_tokens": 16,
                "temperature": 0,
            }
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=60)
            except requests.RequestException as e:
                print(f"  {model} @ {base} -> ERROR {e}")
                continue
            if r.status_code == 200:
                try:
                    content = (
                        ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                    ).strip()
                except json.JSONDecodeError:
                    content = "(non-JSON)"
                print(f"  {model} @ {base} -> OK preview: {content[:80]!r}")
            else:
                err = r.text[:200].replace("\n", " ")
                print(f"  {model} @ {base} -> HTTP {r.status_code} {err}")

    print("\nNote: GLM-5 is documented on the general paas base; Coding plan base may differ.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
