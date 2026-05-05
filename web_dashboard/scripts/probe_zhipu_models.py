#!/usr/bin/env python3
"""Probe Z.AI / Zhipu for listed models and smoke-test chat completions.

Uses the same key resolution as the app (env + web_dashboard/.env via glm_config).
Does not print secrets. Use this to see whether glm-4.5 / 4.6 / 4.7 / 5.1 work on your plan.

Usage (from repo root):

  .\\venv\\Scripts\\activate
  python web_dashboard/scripts/probe_zhipu_models.py

Optional:

  set PROBE_GLM_MODELS=glm-4.5,glm-4.7
  python web_dashboard/scripts/probe_zhipu_models.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

# Allow imports from web_dashboard package
_WEB = Path(__file__).resolve().parent.parent
if str(_WEB) not in sys.path:
    sys.path.insert(0, str(_WEB))

from glm_config import ZHIPU_BASE_URL, get_zhipu_api_key  # noqa: E402
from model_registry import PROBE_DEFAULT_MODELS  # noqa: E402

GENERAL_ZAI = "https://api.z.ai/api/paas/v4"

# Models we care about for benchmarks + judge (official ids per Z.AI docs).
DEFAULT_PROBE_MODELS = PROBE_DEFAULT_MODELS


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


def _post_smoke(base: str, model: str, headers: dict[str, str]) -> tuple[int, str]:
    url = f"{base.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 16,
        "temperature": 0,
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=90)
    except requests.RequestException as e:
        return -1, str(e)
    if r.status_code != 200:
        return r.status_code, (r.text or "")[:220].replace("\n", " ")
    try:
        data = r.json()
        msg = ((data.get("choices") or [{}])[0].get("message") or {})
        content = str(msg.get("content") or "").strip()
        reasoning = str(msg.get("reasoning_content") or msg.get("reasoning") or "").strip()
    except (json.JSONDecodeError, IndexError, TypeError):
        return 200, "(json parse error)"
    if content:
        return 200, content[:120]
    if reasoning:
        return 200, f"(reasoning) {reasoning[:100]}…"
    return 200, "(200 OK but empty content; still usable)"


def main() -> int:
    key = get_zhipu_api_key()
    if not key:
        print("No API key: set ZHIPU_API_KEY / GLM_4_API_KEY or web_dashboard/.secrets/zhipu_api_key")
        return 1

    raw = os.getenv("PROBE_GLM_MODELS", "").strip()
    if raw:
        test_models = [m.strip() for m in raw.split(",") if m.strip()]
    else:
        test_models = list(DEFAULT_PROBE_MODELS)

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
    print("Probe models:", ", ".join(test_models))
    print()

    print("--- GET model list (glm-* ids returned by API) ---")
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
            preview = ", ".join(ids) if ids else "(none)"
            print(f"  {url}")
            print(f"      glm-* ({len(ids)}): {preview}")

    print()
    print("--- POST smoke test (minimal chat; tries configured base, then general paas if needed) ---")
    for model in test_models:
        tried: list[str] = []
        for base in bases:
            code, detail = _post_smoke(base, model, headers)
            tried.append(f"{base.split('//')[-1]}: HTTP {code}" if code >= 0 else f"{base.split('//')[-1]}: {detail}")
            if code == 200:
                print(f"  OK  {model}")
                print(f"       via {base}")
                print(f"       preview: {detail!r}")
                break
        else:
            print(f"  FAIL {model}")
            for t in tried:
                print(f"       {t}")
            if code >= 0 and code != 200:
                print(f"       last body: {detail[:200]!r}")

    print()
    print(
        "Notes: Coding-plan keys often use api.z.ai/api/coding/paas/v4; some model ids only appear on "
        "the general paas base. If a model fails with 404/403, it may not be enabled for your account."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
