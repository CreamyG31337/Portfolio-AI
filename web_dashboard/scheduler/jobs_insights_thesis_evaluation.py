"""Insights thesis evaluation — advisory llm_reply for due/stale theses.

Distinct from fund-level thesis_update_job (Supabase fund_thesis).
Does not write stance_history or auto-flip disposition/intent.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from scheduler.scheduler_core import log_job_execution

logger = logging.getLogger(__name__)

JOB_ID = "insights_thesis_evaluation"
MAX_PER_RUN = 8


def _research_excerpt(postgres: Any, ticker: str) -> tuple[str, dict[str, Any]]:
    """Build a compact read-only research excerpt; return (text, meta_ids)."""
    refs: dict[str, Any] = {}
    parts: list[str] = []
    try:
        ta_rows = postgres.execute_query(
            """
            SELECT id, summary, updated_at FROM ticker_analysis
            WHERE ticker = %s AND analysis_type = 'standard'
            ORDER BY updated_at DESC NULLS LAST
            LIMIT 1
            """,
            (ticker,),
        )
        if ta_rows:
            refs["ticker_analysis_id"] = str(ta_rows[0].get("id") or "")
            summary = str(ta_rows[0].get("summary") or "")[:500]
            parts.append(f"Latest ticker_analysis summary: {summary or '(empty)'}")
    except Exception as exc:
        logger.debug("thesis eval: ticker_analysis fetch failed for %s: %s", ticker, exc)

    try:
        meta_rows = postgres.execute_query(
            """
            SELECT id, narrative, unified_conviction, confidence_adjusted, updated_at
            FROM ticker_meta_analysis
            WHERE ticker = %s
            LIMIT 1
            """,
            (ticker,),
        )
        if meta_rows:
            refs["ticker_meta_analysis_id"] = str(meta_rows[0].get("id") or "")
            narrative = str(meta_rows[0].get("narrative") or "")[:600]
            stance = meta_rows[0].get("unified_conviction")
            conf = meta_rows[0].get("confidence_adjusted")
            parts.append(
                f"Meta stance={stance} confidence={conf}\nMeta narrative: {narrative or '(empty)'}"
            )
    except Exception as exc:
        logger.debug("thesis eval: meta fetch failed for %s: %s", ticker, exc)

    return ("\n".join(parts) if parts else "(no saved research)"), refs


def _thesis_context(detail: dict[str, Any]) -> str:
    entries = detail.get("entries") or []
    recent = entries[-4:] if len(entries) > 4 else entries
    entry_bits = []
    for e in recent:
        entry_bits.append(
            f"- [{e.get('entry_kind')}] {str(e.get('body') or '')[:400]}"
        )
    return json.dumps(
        {
            "ticker": detail.get("ticker"),
            "title": detail.get("title"),
            "disposition": detail.get("disposition"),
            "intent": detail.get("intent"),
            "is_weak": detail.get("is_weak"),
            "review_status": detail.get("review_status"),
            "recent_entries": entry_bits,
        },
        default=str,
    )


def insights_thesis_evaluation_job() -> None:
    """Evaluate due/stale human theses; post advisory llm_reply entries only."""
    job_id = JOB_ID
    start = time.time()
    target_date = datetime.now(UTC).date()

    try:
        from utils.job_tracking import get_running_ai_job, mark_job_started

        running = get_running_ai_job(exclude_job_name=job_id)
        if running:
            logger.info("AI lock active (%s). Skipping %s.", running, job_id)
            return
        mark_job_started(job_id, target_date)
    except Exception as exc:
        logger.warning("AI lock / start tracking failed: %s", exc)

    processed = 0
    errors = 0
    try:
        from ai_prompts import INSIGHTS_THESIS_EVALUATION_PROMPT
        from ollama_client import OllamaClient, collect_with_summary_model_chain, get_ollama_client
        from postgres_client import PostgresClient
        from settings import get_summarizing_model
        from ticker_analysis_service import extract_json
        from user_insights_service import (
            add_evidence,
            add_llm_reply,
            get_thesis_detail,
            list_theses_due,
        )

        ollama = get_ollama_client()
        if not ollama:
            ollama = OllamaClient()
        postgres = PostgresClient()
        model = get_summarizing_model()

        candidates = list_theses_due(postgres, limit=MAX_PER_RUN * 2)
        # Prefer weak + stale; list_theses_due already sorts that way.
        batch = candidates[:MAX_PER_RUN]

        for row in batch:
            thesis_id = str(row.get("id") or "")
            ticker = str(row.get("ticker") or "")
            if not thesis_id or not ticker:
                continue
            try:
                detail = get_thesis_detail(postgres, thesis_id)
                detail["is_weak"] = row.get("is_weak")
                detail["review_status"] = row.get("review_status")
                prior_disp = detail.get("disposition")
                prior_intent = detail.get("intent")
                prior_reviewed = detail.get("last_reviewed_at")

                research, refs = _research_excerpt(postgres, ticker)
                prompt = INSIGHTS_THESIS_EVALUATION_PROMPT.format(
                    thesis_json=_thesis_context(detail),
                    research_excerpt=research,
                )
                full, model_used = collect_with_summary_model_chain(
                    ollama,
                    prompt=prompt,
                    requested_model=model,
                    stream=True,
                    system_prompt=(
                        "Return ONLY valid JSON. Advisory review of a human thesis — "
                        "do not invent trades."
                    ),
                    json_mode=True,
                    temperature=0.15,
                    response_ok=lambda s: extract_json(s) is not None,
                    function_name=job_id,
                    audit_extra={"tickers_extracted": [ticker]},
                )
                if not full:
                    errors += 1
                    continue
                parsed = extract_json(full)
                if not parsed:
                    errors += 1
                    continue

                verdict = str(parsed.get("verdict") or "INSUFFICIENT_DATA")[:40]
                one_liner = str(parsed.get("one_liner") or "")[:500]
                suggested_disp = parsed.get("suggested_disposition")
                suggested_intent = parsed.get("suggested_intent")
                evidence_notes = parsed.get("evidence_notes") or ""

                body = one_liner or f"Advisory verdict: {verdict}"
                if evidence_notes:
                    body = f"{body}\n\nNotes: {str(evidence_notes)[:800]}"

                meta = {
                    "verdict": verdict,
                    "one_liner": one_liner,
                    "suggested_disposition": suggested_disp,
                    "suggested_intent": suggested_intent,
                    "advisory_only": True,
                    "prior_disposition": prior_disp,
                    "prior_intent": prior_intent,
                }
                result = add_llm_reply(
                    postgres,
                    thesis_id=thesis_id,
                    body=body,
                    metadata=meta,
                    author_id=job_id,
                    model_used=model_used,
                )

                # Link known meta/analysis evidence when IDs present (best-effort).
                entry_id = result.get("entry_id")
                meta_id = refs.get("ticker_meta_analysis_id")
                if meta_id and entry_id:
                    try:
                        add_evidence(
                            postgres,
                            thesis_id=thesis_id,
                            evidence_kind="ticker_meta_analysis",
                            created_by=job_id,
                            entry_id=str(entry_id),
                            ref_id=meta_id,
                            title=f"Meta at eval ({ticker})",
                            snippet=str(parsed.get("one_liner") or "")[:300],
                            relation="context"
                            if verdict in ("HOLDS", "INSUFFICIENT_DATA")
                            else "contradicts",
                        )
                    except Exception as ev_exc:
                        logger.debug("thesis eval evidence link skipped: %s", ev_exc)

                # Invariant: disposition / last_reviewed_at unchanged.
                after = get_thesis_detail(postgres, thesis_id)
                if after.get("disposition") != prior_disp or after.get("intent") != prior_intent:
                    logger.error(
                        "insights_thesis_evaluation: disposition/intent mutated for %s — unexpected",
                        thesis_id,
                    )
                    errors += 1
                    continue
                if after.get("last_reviewed_at") != prior_reviewed:
                    logger.error(
                        "insights_thesis_evaluation: last_reviewed_at bumped for %s — unexpected",
                        thesis_id,
                    )
                    errors += 1
                    continue

                processed += 1
            except Exception as item_exc:
                errors += 1
                logger.warning(
                    "insights_thesis_evaluation failed for %s/%s: %s",
                    ticker,
                    thesis_id,
                    item_exc,
                    exc_info=True,
                )

        duration_ms = int((time.time() - start) * 1000)
        msg = f"replies={processed} errors={errors} candidates={len(batch)}"
        log_job_execution(job_id, True, msg, duration_ms)
        try:
            from utils.job_tracking import mark_job_completed

            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=msg)
        except Exception:
            pass
        logger.info("insights_thesis_evaluation_job: %s", msg)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(job_id, False, err, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(job_id, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("insights_thesis_evaluation_job failed: %s", exc, exc_info=True)
