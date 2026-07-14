#!/usr/bin/env python3
"""Smoke-test: run advisory llm_reply eval on one thesis (not the due queue)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_WEB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_WEB))

from env_loader import load_project_dotenv

load_project_dotenv()


def main() -> int:
    import os

    os.chdir(_WEB)
    ticker = (sys.argv[1] if len(sys.argv) > 1 else "COST").upper().strip()

    from ai_prompts import INSIGHTS_THESIS_EVALUATION_PROMPT
    from ollama_client import OllamaClient, collect_with_summary_model_chain, get_ollama_client
    from postgres_client import PostgresClient
    from settings import get_summarizing_model
    from ticker_analysis_service import extract_json
    from user_insights_service import add_llm_reply, get_thesis_detail, list_theses
    from scheduler.jobs_insights_thesis_evaluation import _research_excerpt, _thesis_context

    pg = PostgresClient()
    rows = list_theses(pg, ticker=ticker, include_archived=False, limit=5)
    if not rows:
        print(f"no active thesis for {ticker}")
        return 1
    thesis_id = str(rows[0]["id"])
    detail = get_thesis_detail(pg, thesis_id)
    prior_disp = detail.get("disposition")
    prior_reviewed = detail.get("last_reviewed_at")
    print(f"thesis={thesis_id} ticker={ticker} disp={prior_disp}")

    research, _refs = _research_excerpt(pg, ticker)
    prompt = INSIGHTS_THESIS_EVALUATION_PROMPT.format(
        thesis_json=_thesis_context(detail),
        research_excerpt=research,
    )
    ollama = get_ollama_client() or OllamaClient()
    full, model_used = collect_with_summary_model_chain(
        ollama,
        prompt=prompt,
        requested_model=get_summarizing_model(),
        stream=True,
        system_prompt="Return ONLY valid JSON. Advisory review — not trade advice.",
        json_mode=True,
        temperature=0.15,
        response_ok=lambda s: extract_json(s) is not None,
        function_name="insights_thesis_evaluation_smoke",
    )
    parsed = extract_json(full or "") or {}
    print("parsed=", json.dumps(parsed, indent=2)[:800])
    body = str(parsed.get("one_liner") or f"Advisory: {parsed.get('verdict')}")
    result = add_llm_reply(
        pg,
        thesis_id=thesis_id,
        body=body,
        metadata={
            "verdict": parsed.get("verdict"),
            "one_liner": parsed.get("one_liner"),
            "suggested_disposition": parsed.get("suggested_disposition"),
            "suggested_intent": parsed.get("suggested_intent"),
            "advisory_only": True,
            "smoke_test": True,
        },
        author_id="insights_thesis_evaluation",
        model_used=model_used,
    )
    after = get_thesis_detail(pg, thesis_id)
    print(f"entry_id={result.get('entry_id')}")
    print(f"disposition unchanged={after.get('disposition') == prior_disp} ({after.get('disposition')})")
    print(
        f"last_reviewed unchanged={after.get('last_reviewed_at') == prior_reviewed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
