"""
Opt-in LLM benchmark harness (Phase 3).

Run::

    set OLLAMA_BENCH=1
    python -m pytest tests/benchmarks/llm_bench.py -m bench -v

Requires:

- Live Ollama (``OLLAMA_ENABLED`` not false) and models available on resolved hosts.
  For ``qwen3.6:27b-heretic``, set ``OLLAMA_BASE_URL_2`` to the Ollama base URL of the host that has that model installed;
  ``OLLAMA_BASE_URL`` may point at a different machine.
- ``RESEARCH_DATABASE_URL`` for article-summary rows (skipped if unset).

Artifacts are written under ``verification/benchmarks/`` (CSV + Markdown summary).

Optional context sweep (same article sample, one model)::

    set OLLAMA_BENCH_NUM_CTX_SWEEP=8192,16384,32768
    set OLLAMA_BENCH_CTX_MODEL=qwen3.6:27b-heretic

Requires ``RESEARCH_DATABASE_URL`` and a healthy Ollama for ``OLLAMA_BENCH_CTX_MODEL``.
"""

from __future__ import annotations

import csv
import os
import sys
import time
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WEB_DASHBOARD = PROJECT_ROOT / "web_dashboard"
if str(WEB_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ollama_client import OllamaClient, _generate_summary_once  # noqa: E402
from social_service import _extract_json_object  # noqa: E402

BENCH_ENV = "OLLAMA_BENCH"
OUTPUT_DIR = PROJECT_ROOT / "verification" / "benchmarks"

SUMMARY_SCHEMA_KEYS = [
    "summary",
    "claims",
    "fact_check",
    "conclusion",
    "sentiment",
    "tickers",
    "key_themes",
    "companies",
    "relationships",
    "market_relevance",
]


def _bench_enabled() -> bool:
    return os.getenv(BENCH_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _summary_completeness(result: dict[str, Any]) -> tuple[int, int]:
    present = 0
    for k in SUMMARY_SCHEMA_KEYS:
        v = result.get(k)
        if v is None:
            continue
        if isinstance(v, str) and v.strip():
            present += 1
        elif isinstance(v, list | dict) and len(v) > 0:
            present += 1
    total = len(SUMMARY_SCHEMA_KEYS)
    return present, total


def _ticker_recall_pct(predicted: list[str], gold: list[str]) -> float | None:
    if not gold:
        return None
    pred = {str(t).strip().upper() for t in predicted if t}
    g = {str(t).strip().upper() for t in gold if t}
    if not g:
        return None
    inter = pred & g
    return round(100.0 * len(inter) / len(g), 2)


def _fetch_article_samples(limit: int) -> list[dict[str, Any]]:
    from postgres_client import PostgresClient

    client = PostgresClient()
    q = """
    SELECT id::text AS id, title, article_type, content, tickers
    FROM research_articles
    WHERE content IS NOT NULL
      AND LENGTH(TRIM(content)) > 400
    ORDER BY fetched_at DESC
    LIMIT %s
    """
    rows = client.execute_query(q, (limit,))
    return list(rows or [])


def _write_outputs(rows: list[dict[str, Any]]) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    csv_path = OUTPUT_DIR / f"llm_bench_{ts}.csv"
    md_path = OUTPUT_DIR / f"llm_bench_{ts}.md"
    if not rows:
        csv_path.write_text(
            "run_id,timestamp,model,schema,num_ctx,sample_id,parse_ok,keys_present_pct,ticker_recall_pct,duration_ms,error_type\n",
            encoding="utf-8",
        )
        md_path.write_text("# LLM bench (empty)\n", encoding="utf-8")
        return csv_path, md_path

    fieldnames = list(rows[0].keys())
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # Aggregate by model + schema
    from collections import defaultdict

    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        nc = r.get("num_ctx")
        nc_key = str(nc) if nc not in ("", None) else "—"
        buckets[(r["model"], r["schema"], nc_key)].append(r)

    lines = [
        f"# LLM benchmark `{ts}`",
        "",
        "| model | schema | num_ctx | n | parse_ok % | mean keys % | mean recall % | mean ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for (model, schema, nc_key), rs in sorted(buckets.items()):
        n = len(rs)
        ok_pct = round(100.0 * sum(1 for x in rs if int(x.get("parse_ok") or 0)) / n, 1)
        keys_vals = [float(x["keys_present_pct"]) for x in rs if x.get("keys_present_pct") not in ("", None)]
        mean_keys = round(sum(keys_vals) / len(keys_vals), 1) if keys_vals else 0.0
        rec_vals = [float(x["ticker_recall_pct"]) for x in rs if x.get("ticker_recall_pct") not in ("", None)]
        mean_rec = round(sum(rec_vals) / len(rec_vals), 1) if rec_vals else None
        durs = [float(x["duration_ms"]) for x in rs if x.get("duration_ms")]
        mean_ms = round(sum(durs) / len(durs), 0) if durs else 0.0
        rec_s = str(mean_rec) if mean_rec is not None else "n/a"
        lines.append(
            f"| {model} | {schema} | {nc_key} | {n} | {ok_pct} | {mean_keys} | {rec_s} | {mean_ms} |"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, md_path


@pytest.mark.bench
def test_bench_article_summary_and_crowd_json() -> None:
    """End-to-end bench: article summaries from research DB + fixed crowd-style JSON completion."""
    if not _bench_enabled():
        pytest.skip(f"Set {BENCH_ENV}=1 to run LLM benchmarks")

    client = OllamaClient()
    if not client.enabled:
        pytest.skip("OLLAMA_ENABLED is false")

    models_env = os.getenv("OLLAMA_BENCH_MODELS", "granite3.3:8b,qwen3.6:27b-heretic")
    models = [m.strip() for m in models_env.split(",") if m.strip()]
    limit = max(1, min(50, int(os.getenv("OLLAMA_BENCH_LIMIT", "5"))))
    ctx_sweep: list[int] = []
    for part in os.getenv("OLLAMA_BENCH_NUM_CTX_SWEEP", "").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            ctx_sweep.append(int(p))
        except ValueError:
            pass
    ctx_model = os.getenv("OLLAMA_BENCH_CTX_MODEL", "").strip()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")

    rows: list[dict[str, Any]] = []
    ts_iso = datetime.now(UTC).isoformat()

    # --- Article summary track (optional DB) ---
    samples: list[dict[str, Any]] = []
    if os.getenv("RESEARCH_DATABASE_URL"):
        try:
            samples = _fetch_article_samples(limit)
        except Exception as exc:
            print(f"[llm_bench] Article samples unavailable (continuing with JSON-only): {exc}")

    for model in models:
        if not client.check_health_for_model(model):
            continue
        for sample in samples:
            title = (sample.get("title") or "").strip()
            content = (sample.get("content") or "")[:6000]
            article_type = (sample.get("article_type") or "").strip()
            text = f"Title: {title}\n\n{content}" if title else content
            gold = sample.get("tickers") or []
            if isinstance(gold, str):
                gold = [gold]
            err = ""
            t0 = time.perf_counter()
            try:
                result = _generate_summary_once(
                    text=text,
                    model=model,
                    article_type=article_type,
                    stream=False,
                    progress_callback=None,
                )
            except Exception as e:
                result = {}
                err = type(e).__name__
            duration_ms = round((time.perf_counter() - t0) * 1000, 1)
            if not isinstance(result, dict):
                result = {}
            parse_ok = bool(result.get("summary", "").strip())
            present, total = _summary_completeness(result)
            keys_pct = round(100.0 * present / total, 2) if total else 0.0
            pred_tickers = [str(t) for t in (result.get("tickers") or [])]
            rec = _ticker_recall_pct(pred_tickers, list(gold))
            rows.append(
                {
                    "run_id": run_id,
                    "timestamp": ts_iso,
                    "model": model,
                    "schema": "article_summary",
                    "num_ctx": "",
                    "sample_id": sample.get("id", ""),
                    "parse_ok": 1 if parse_ok else 0,
                    "keys_present_pct": keys_pct,
                    "ticker_recall_pct": rec if rec is not None else "",
                    "duration_ms": duration_ms,
                    "error_type": err,
                }
            )

    # --- num_ctx sweep removed ---
    # Previously this benchmark accepted --ctx-sweep to vary num_ctx per request
    # via a num_ctx_override hook on _generate_summary_once. That hook has been
    # removed because changing num_ctx between requests forces Ollama to evict
    # and reload the model weights, which (a) wrecks latency comparisons since
    # most of the wall-clock is reload time rather than inference, and (b) is
    # never what production code wants. To benchmark a specific num_ctx, edit
    # model_config.json (or system_settings) for the target model and re-run.
    _ = ctx_sweep, ctx_model  # kept in signature for CLI compatibility

    # --- Crowd-style JSON track (no DB) ---
    crowd_prompt = """You are a financial sentiment analyst. Given the posts below, return ONLY valid JSON:
{"sentiment": "BULLISH", "reasoning": "one short sentence"}
Use sentiment one of: EUPHORIC, BULLISH, NEUTRAL, BEARISH, FEARFUL.

Posts:
- User1: Loading up on shares before earnings.
- User2: Looks strong, holding.
"""
    for model in models:
        if not client.check_health_for_model(model):
            continue
        err = ""
        t0 = time.perf_counter()
        try:
            raw = client.generate_completion(
                prompt=crowd_prompt,
                model=model,
                json_mode=True,
            )
        except Exception as e:
            raw = None
            err = type(e).__name__
        duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        parsed = _extract_json_object(raw or "")
        parse_ok = bool(parsed and parsed.get("sentiment"))
        rows.append(
            {
                "run_id": run_id,
                "timestamp": ts_iso,
                "model": model,
                "schema": "crowd_sentiment_json",
                "num_ctx": "",
                "sample_id": "synthetic_1",
                "parse_ok": 1 if parse_ok else 0,
                "keys_present_pct": 100.0 if parse_ok else 0.0,
                "ticker_recall_pct": "",
                "duration_ms": duration_ms,
                "error_type": err,
            }
        )

    if not rows:
        pytest.skip(
            "No models passed health check or no samples "
            "(set RESEARCH_DATABASE_URL for articles; ctx sweep needs samples too)"
        )

    csv_path, md_path = _write_outputs(rows)
    # Surface paths in pytest summary
    print(f"\n[llm_bench] Wrote {csv_path}\n[llm_bench] Wrote {md_path}")

    assert len(rows) > 0
