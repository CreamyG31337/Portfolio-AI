#!/usr/bin/env python3
"""Probe which AI Assistant picker models actually invoke tools.

For each candidate model:
  - GLM: one-shot tool-required question via glm_chat_completion_message + TOOL_SCHEMAS
  - Non-GLM: report as tools_unsupported (chat handler only enables tools for backend==glm)

Usage (repo root):
  .\\venv\\Scripts\\python.exe web_dashboard\\scripts\\probe_assistant_tool_models.py
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

PROBE_QUESTION = (
    "Which of our stance sources have been right over the last 30 days? "
    "You must call get_track_record. Do not answer without the tool."
)
EXPECTED_TOOL = "get_track_record"


def _candidates() -> list[dict[str, str]]:
    """Mirror the AI Assistant picker: Ollama + WebAI + GLM allowlist."""
    from ollama_client import list_available_models

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for mid in list_available_models() or []:
        mid_s = str(mid or "").strip()
        if not mid_s or mid_s in seen:
            continue
        seen.add(mid_s)
        if mid_s.startswith("glm-"):
            mtype = "glm"
        else:
            try:
                from webai_wrapper import is_webai_model

                mtype = "webai" if is_webai_model(mid_s) else "ollama"
            except Exception:
                mtype = "ollama"
        out.append({"id": mid_s, "type": mtype})
    return out


def _probe_glm(model: str) -> dict[str, Any]:
    from ai_assistant_tools import TOOL_SCHEMAS
    from ai_prompts import get_system_prompt
    from glm_transport import glm_chat_completion_message

    system = get_system_prompt(model, allow_search=True, enable_tools=True)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": PROBE_QUESTION},
    ]
    t0 = time.time()
    result = glm_chat_completion_message(
        messages,
        model=model,
        temperature=0.1,
        max_tokens=512,
        tools=TOOL_SCHEMAS,
        tool_choice="auto",
        timeout=90.0,
        allow_cheap_fallback=False,
    )
    elapsed = round(time.time() - t0, 1)
    names: list[str] = []
    for tc in result.tool_calls or []:
        fn = tc.get("function") or {}
        names.append(str(fn.get("name") or ""))
    ok = EXPECTED_TOOL in names and not result.error
    return {
        "model": model,
        "type": "glm",
        "ok": ok,
        "tools_called": names,
        "error": result.error,
        "content_preview": (result.content or "")[:180],
        "elapsed_s": elapsed,
        "verdict": "pass" if ok else "fail_no_tool_call",
    }


def main() -> int:
    rows = _candidates()
    print(f"Picker candidates: {len(rows)}")
    results: list[dict[str, Any]] = []
    for row in rows:
        mid = str(row.get("id") or "")
        mtype = str(row.get("type") or "")
        print(f"\n=== {mid} ({mtype}) ===")
        if mtype != "glm" and not mid.startswith("glm-"):
            out = {
                "model": mid,
                "type": mtype or "unknown",
                "ok": False,
                "tools_called": [],
                "error": None,
                "content_preview": "",
                "elapsed_s": 0,
                "verdict": "fail_tools_not_wired",
                "note": "ChatHandler only enables tools when backend == 'glm' (wishlist A1).",
            }
            print(f"  SKIP/FAIL: {out['verdict']} — {out['note']}")
            results.append(out)
            continue
        try:
            out = _probe_glm(mid)
        except Exception as exc:
            out = {
                "model": mid,
                "type": "glm",
                "ok": False,
                "tools_called": [],
                "error": str(exc),
                "content_preview": "",
                "elapsed_s": 0,
                "verdict": "fail_exception",
            }
        print(
            f"  verdict={out['verdict']} tools={out.get('tools_called')} "
            f"err={out.get('error')} ({out.get('elapsed_s')}s)"
        )
        results.append(out)

    passed = [r["model"] for r in results if r.get("ok")]
    failed = [r for r in results if not r.get("ok")]
    print("\n========== SUMMARY ==========")
    print(f"PASS ({len(passed)}): {passed}")
    print(f"FAIL ({len(failed)}):")
    for r in failed:
        print(f"  - {r['model']}: {r['verdict']}")

    out_path = REPO_ROOT / "verification" / "ai_assistant_tool_model_probe.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
