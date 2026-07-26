#!/usr/bin/env python3
"""Live probe: can local Ollama models emit OpenAI-style tool calls?

Hits Ollama /api/chat with tools= (our Assistant schemas) — independent of
whether ChatHandler wires tools today.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB = REPO_ROOT / "web_dashboard"
sys.path.insert(0, str(WEB))
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("DISABLE_SCHEDULER", "true")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from env_loader import load_project_dotenv  # noqa: E402

load_project_dotenv()

# Prefer chat-sized models; skip embeddings / tiny tags.
CANDIDATES = [
    "granite4.1:8b",
    "qwen3:14b",
    "mistral-small:22b",
    "llama3.1:8b",
    "gemma3:12b",
    "gpt-oss:20b",
    "qwen2.5-coder:14b",
    "glm4:latest",
]

PROBE_Q = (
    "Which of our stance sources have been right over the last 30 days? "
    "You must call the get_track_record tool. Do not answer without calling a tool."
)


def _ollama_base() -> str:
    return (os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")


def _installed() -> set[str]:
    import requests

    r = requests.get(f"{_ollama_base()}/api/tags", timeout=10)
    r.raise_for_status()
    return {str(m.get("name") or "") for m in (r.json().get("models") or []) if m.get("name")}


def _tool_schemas() -> list[dict[str, Any]]:
    from ai_assistant_tools import TOOL_SCHEMAS

    # Ollama accepts OpenAI-style function tools; keep the catalog lean for the probe.
    keep = {
        "get_track_record",
        "get_theses_attention",
        "get_confluence",
        "get_holdings_snapshot",
        "get_earnings_calendar",
    }
    out = []
    for t in TOOL_SCHEMAS:
        fn = (t.get("function") or {})
        if fn.get("name") in keep:
            out.append(t)
    return out


def _probe(model: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
    import requests

    from ai_prompts import get_system_prompt

    # Use the tools-enabled system prompt text so the model sees the catalog.
    system = get_system_prompt("glm-5.2", allow_search=True, enable_tools=True)
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": PROBE_Q},
        ],
        "tools": tools,
        "options": {"temperature": 0.1, "num_predict": 512},
    }
    t0 = time.time()
    try:
        r = requests.post(f"{_ollama_base()}/api/chat", json=payload, timeout=180)
        elapsed = round(time.time() - t0, 1)
        if r.status_code >= 400:
            return {
                "model": model,
                "ok": False,
                "verdict": "http_error",
                "status": r.status_code,
                "body": r.text[:400],
                "elapsed_s": elapsed,
            }
        data = r.json()
        msg = data.get("message") or {}
        tool_calls = msg.get("tool_calls") or []
        names: list[str] = []
        for tc in tool_calls:
            fn = tc.get("function") or {}
            names.append(str(fn.get("name") or ""))
        content = str(msg.get("content") or "")
        ok = "get_track_record" in names
        return {
            "model": model,
            "ok": ok,
            "verdict": "pass" if ok else "no_tool_call",
            "tools_called": names,
            "content_preview": content[:200],
            "elapsed_s": elapsed,
        }
    except Exception as exc:
        return {
            "model": model,
            "ok": False,
            "verdict": "exception",
            "error": str(exc),
            "elapsed_s": round(time.time() - t0, 1),
        }


def main() -> int:
    installed = _installed()
    print(f"Ollama at {_ollama_base()} — {len(installed)} models installed")
    tools = _tool_schemas()
    print(f"Sending {len(tools)} tools; question requires get_track_record\n")

    results: list[dict[str, Any]] = []
    for mid in CANDIDATES:
        # Allow tag-less match (granite4.1:8b vs granite4.1:8b)
        if mid not in installed and not any(m.startswith(mid.split(":")[0]) for m in installed):
            print(f"=== {mid} === SKIP (not installed)")
            continue
        # Prefer exact installed name if a variant exists
        model = mid if mid in installed else next(
            (m for m in installed if m.startswith(mid.split(":")[0])), mid
        )
        print(f"=== {model} ===")
        out = _probe(model, tools)
        print(
            f"  verdict={out['verdict']} tools={out.get('tools_called')} "
            f"({out.get('elapsed_s')}s)"
        )
        if out.get("content_preview"):
            print(f"  content: {out['content_preview']!r}")
        if out.get("body"):
            print(f"  body: {out['body']!r}")
        if out.get("error"):
            print(f"  error: {out['error']}")
        results.append(out)

    passed = [r["model"] for r in results if r.get("ok")]
    failed = [r for r in results if not r.get("ok")]
    print("\n========== SUMMARY ==========")
    print(f"PASS ({len(passed)}): {passed}")
    print(f"FAIL ({len(failed)}):")
    for r in failed:
        print(f"  - {r['model']}: {r['verdict']}")

    out_path = REPO_ROOT / "verification" / "ollama_tool_call_probe.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
