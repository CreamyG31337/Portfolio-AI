#!/usr/bin/env python3
"""Quality smoke-test for AI Assistant pulse + GLM tools (no browser).

Uses Supabase service-role (bypasses RLS) + Research DB + GLM.
Prints tool traces and final answers for manual review.

Usage (from repo root):
  .\\venv\\Scripts\\python.exe web_dashboard\\scripts\\quality_test_ai_assistant_chat.py
  .\\venv\\Scripts\\python.exe web_dashboard\\scripts\\quality_test_ai_assistant_chat.py --fund \"Project Chimera\" --limit 6
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB = REPO_ROOT / "web_dashboard"
sys.path.insert(0, str(WEB))
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("DISABLE_SCHEDULER", "true")

# Windows consoles default to cp1252; pulse tables (em-dashes) and model
# answers (emoji) must not crash the run. Force UTF-8 on the text streams.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from env_loader import load_project_dotenv  # noqa: E402

load_project_dotenv()

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("quality_ai_chat")
logger.setLevel(logging.INFO)


QUESTIONS: list[dict[str, str]] = [
    {
        "family": "discovery_timing",
        "q": "What stock has a good entry point right now? Cite entry zones if you have them.",
    },
    {
        "family": "market",
        "q": "What's the market doing today? Summarize regime and headline.",
    },
    {
        "family": "sector",
        "q": "How is Health Care rotating right now based on our sector meta?",
    },
    {
        "family": "sector_discovery",
        "q": "Best setups in Energy right now from our candidates?",
    },
    {
        "family": "specific_ticker",
        "q": "Using tools, is TSM a buy right now? Cite stance, entry zone, target, and stop if available.",
    },
    {
        "family": "news",
        "q": "Any recent news on TSM? Use search tools; do not invent headlines.",
    },
    {
        "family": "overview",
        "q": "What should I focus on today across market, signals, and candidates?",
    },
    {
        "family": "holdings_risk",
        "q": "Any of my holdings look risky right now (RISK/SELL)?",
    },
]


def _sb():
    from supabase_client import SupabaseClient

    return SupabaseClient(use_service_role=True)


def _service_patches(sb: Any):
    return (
        patch("flask_data_utils.get_supabase_client_flask", return_value=sb),
        patch("ai_assistant_tools._supabase", return_value=sb),
        patch(
            "ai_assistant_clients.get_assistant_research_supabase",
            return_value=sb,
        ),
        patch("action_queue_service.get_ticker_logo_urls", return_value={}),
    )


def _resolve_fund(explicit: str | None) -> str:
    if explicit:
        return explicit
    try:
        client = _sb()
        rows = client.supabase.table("funds").select("name").limit(30).execute()
        names = [str(r.get("name") or "") for r in (rows.data or []) if r.get("name")]
        for preferred in ("Project Chimera", "TFSA", "TEST"):
            if preferred not in names:
                continue
            wl = (
                client.supabase.table("watched_tickers_v2")
                .select("ticker")
                .eq("is_active", True)
                .eq("fund", preferred)
                .limit(1)
                .execute()
            )
            if wl.data:
                return preferred
        return names[0] if names else "TEST"
    except Exception as exc:
        logger.warning("fund lookup failed: %s", exc)
        return "TEST"


def _probe_tools(fund: str, sb: Any) -> None:
    from ai_assistant_tools import AssistantToolContext, execute_tool

    ctx = AssistantToolContext(user_id="quality-script", fund=fund)
    probes = [
        ("list_entry_candidates", {"limit": 5}),
        ("list_entry_candidates", {"limit": 5, "sector": "Energy"}),
        ("get_market_brief", {}),
        ("get_sector_rotation", {"sector": "Health Care"}),
        ("get_ticker_setup", {"ticker": "TSM"}),
        ("get_signals_overview", {}),
    ]
    print("\n========== TOOL PROBES ==========")
    with _service_patches(sb)[0], _service_patches(sb)[1], _service_patches(sb)[2]:
        for name, args in probes:
            t0 = time.time()
            raw = execute_tool(name, args, ctx)
            elapsed = time.time() - t0
            data = json.loads(raw)
            preview = json.dumps(data, default=str)[:500]
            print(f"\n--- {name}({args}) [{elapsed:.1f}s] ok={data.get('ok')} ---")
            print(preview + ("..." if len(json.dumps(data, default=str)) > 500 else ""))


def _run_chat_questions(
    fund: str, pulse_text: str, limit: int, sb: Any
) -> list[dict[str, Any]]:
    from ai_assistant_tools import TOOL_SCHEMAS, AssistantToolContext, execute_tool
    from ai_prompts import get_system_prompt
    from glm_config import get_zhipu_api_key
    from glm_transport import glm_chat_completion_message
    from model_registry import get_primary_model

    if not get_zhipu_api_key():
        raise RuntimeError("ZHIPU_API_KEY not configured")

    model = get_primary_model()
    ctx = AssistantToolContext(user_id="quality-script", fund=fund)
    system = get_system_prompt(model, allow_search=True, enable_tools=True)
    results: list[dict[str, Any]] = []

    print(f"\n========== GLM CHAT ({model}) ==========")

    for item in QUESTIONS[:limit]:
        query = item["q"]
        family = item["family"]
        full_prompt = f"{pulse_text}\n\n{query}" if pulse_text else query
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": full_prompt},
        ]
        tool_trace: list[str] = []
        final = ""
        t0 = time.time()
        print(f"\n##### [{family}] {query}")

        with _service_patches(sb)[0], _service_patches(sb)[1], _service_patches(sb)[2]:
            for round_i in range(4):
                result = glm_chat_completion_message(
                    messages,
                    model=model,
                    temperature=0.1,
                    max_tokens=2048,
                    tools=TOOL_SCHEMAS if round_i < 3 else None,
                    tool_choice="auto" if round_i < 3 else None,
                    timeout=120.0,
                    allow_cheap_fallback=True,
                )
                if result.error and not result.content and not result.has_tool_calls:
                    final = f"ERROR: {result.error}"
                    break
                if result.has_tool_calls and round_i < 3:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": result.content or None,
                            "tool_calls": result.tool_calls,
                        }
                    )
                    for tc in result.tool_calls:
                        fn = tc.get("function") or {}
                        name = str(fn.get("name") or "")
                        args_raw = fn.get("arguments") or "{}"
                        tool_trace.append(f"{name}({args_raw})")
                        print(f"  tool -> {name}({args_raw})")
                        tool_json = execute_tool(name, args_raw, ctx)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.get("id") or f"call_{name}",
                                "content": tool_json,
                            }
                        )
                    continue
                final = result.content or ""
                break

        elapsed = time.time() - t0
        print(f"  ({elapsed:.1f}s) tools={tool_trace or ['(none)']}")
        print("--- answer ---")
        print(final[:2500] + ("..." if len(final) > 2500 else ""))
        results.append(
            {
                "family": family,
                "query": query,
                "tools": tool_trace,
                "answer": final,
                "elapsed_s": round(elapsed, 1),
            }
        )

    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fund", default=None)
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--skip-chat", action="store_true")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "verification" / "ai_assistant_quality_latest.json"),
    )
    args = parser.parse_args()

    sb = _sb()
    fund = _resolve_fund(args.fund)
    print(f"Using fund: {fund}")

    from ai_intelligence_pulse import build_intelligence_pulse, format_intelligence_pulse

    with _service_patches(sb)[0], _service_patches(sb)[1], _service_patches(sb)[2]:
        structured = build_intelligence_pulse(fund, candidate_limit=8)
        pulse_text = format_intelligence_pulse(structured)

    print("\n========== TODAY PULSE ==========")
    print(pulse_text)
    print(
        f"\n[pulse meta] candidates={structured.get('candidate_count')} "
        f"market_ok={bool(structured.get('market'))}"
    )

    _probe_tools(fund, sb)

    chat_results: list[dict[str, Any]] = []
    if not args.skip_chat:
        chat_results = _run_chat_questions(fund, pulse_text, args.limit, sb)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fund": fund,
        "pulse_candidate_count": structured.get("candidate_count"),
        "market": structured.get("market"),
        "candidates": structured.get("candidates"),
        "chat": chat_results,
    }
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
