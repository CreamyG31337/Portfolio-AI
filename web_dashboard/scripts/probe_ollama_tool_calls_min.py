#!/usr/bin/env python3
"""Minimal Ollama tool-call probe (unbuffered)."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "web_dashboard"))
sys.path.insert(0, str(REPO))
os.environ.setdefault("DISABLE_SCHEDULER", "true")

from env_loader import load_project_dotenv

load_project_dotenv()

import requests

BASE = (os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
MODELS = ["granite4.1:8b", "qwen3:14b", "mistral-small:22b", "llama3.1:8b", "glm4:latest"]
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_track_record",
            "description": "Learn-layer scorecard: hit rate by source. Call this to answer which sources were right.",
            "parameters": {
                "type": "object",
                "properties": {
                    "horizon_days": {"type": "integer", "enum": [7, 30, 90]},
                },
            },
        },
    }
]
Q = (
    "Which stance sources have been right over the last 30 days? "
    "You MUST call get_track_record. Do not answer in plain text first."
)


def main() -> None:
    print(f"base={BASE}", flush=True)
    tags = requests.get(f"{BASE}/api/tags", timeout=15).json()
    installed = {m.get("name") for m in tags.get("models") or []}
    print(f"installed={len(installed)}", flush=True)

    results = []
    for model in MODELS:
        if model not in installed:
            print(f"SKIP {model}", flush=True)
            continue
        print(f"PROBE {model} ...", flush=True)
        t0 = time.time()
        try:
            r = requests.post(
                f"{BASE}/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a trading assistant with tools. Always call tools when asked for track record.",
                        },
                        {"role": "user", "content": Q},
                    ],
                    "tools": TOOLS,
                    "options": {"temperature": 0.1, "num_predict": 256},
                },
                timeout=180,
            )
            elapsed = round(time.time() - t0, 1)
            if r.status_code >= 400:
                print(f"  FAIL http {r.status_code}: {r.text[:240]}", flush=True)
                results.append({"model": model, "ok": False, "verdict": f"http_{r.status_code}"})
                continue
            msg = (r.json().get("message") or {})
            calls = msg.get("tool_calls") or []
            names = [((c.get("function") or {}).get("name") or "") for c in calls]
            content = (msg.get("content") or "")[:160]
            ok = "get_track_record" in names
            print(
                f"  {'PASS' if ok else 'FAIL'} tools={names} ({elapsed}s) content={content!r}",
                flush=True,
            )
            results.append(
                {
                    "model": model,
                    "ok": ok,
                    "verdict": "pass" if ok else "no_tool_call",
                    "tools": names,
                    "elapsed_s": elapsed,
                    "content": content,
                }
            )
        except Exception as exc:
            print(f"  FAIL exception: {exc}", flush=True)
            results.append({"model": model, "ok": False, "verdict": "exception", "error": str(exc)})

    out = REPO / "verification" / "ollama_tool_call_probe.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    passed = [r["model"] for r in results if r.get("ok")]
    print(f"\nPASS: {passed}", flush=True)
    print(f"FAIL: {[(r['model'], r['verdict']) for r in results if not r.get('ok')]}", flush=True)
    print(f"Wrote {out}", flush=True)


if __name__ == "__main__":
    main()
