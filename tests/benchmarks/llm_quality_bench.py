"""
Opt-in LLM quality benchmark: curated articles + LLM-as-judge (GLM).

Run::

    set OLLAMA_QUALITY_BENCH=1
    python -m pytest tests/benchmarks/llm_quality_bench.py -m bench -v

Requires:
- Live Ollama for candidate models (same as llm_bench).
- ZHIPU_API_KEY (or equivalent) for GLM judge (default ``glm-5.1``); skipped with a warning row if unavailable.
- Default summarizer models include Ollama + ``glm-5.1``, ``glm-5-turbo``, ``glm-4.5-air`` (override with ``OLLAMA_QUALITY_MODELS``).
- To verify which glm-* ids work on your plan: ``python web_dashboard/scripts/probe_zhipu_models.py``.
- Set ``OLLAMA_QUALITY_SKIP_JUDGE=1`` to never call the GLM judge (parse_ok / lexical / timing only).
- Judge transient Z.AI failures retry same judge model (``QUALITY_JUDGE_MAX_ATTEMPTS``, default 3).

Artifacts: verification/quality/quality_<ts>.csv, .md, and quality_<ts>_summaries.json (gitignored).
The JSON file is used to re-run only the GLM judge: ``python verification/quality/rerun_quality_judge.py <path>``.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WEB_DASHBOARD = PROJECT_ROOT / "web_dashboard"
if str(WEB_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from model_registry import BENCH_JUDGE_MODEL, zai_error_text_probably_transient  # noqa: E402
from ollama_client import OllamaClient, _generate_summary_once  # noqa: E402
from social_service import _extract_json_object  # noqa: E402

QUALITY_ENV = "OLLAMA_QUALITY_BENCH"
SAMPLES_PATH = PROJECT_ROOT / "verification" / "quality" / "quality_samples.json"
OUTPUT_DIR = PROJECT_ROOT / "verification" / "quality"


def _quality_enabled() -> bool:
    return os.getenv(QUALITY_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _skip_glm_judge() -> bool:
    """When true, do not call GLM-5.1 judge (no Z.AI usage for scoring)."""
    return os.getenv("OLLAMA_QUALITY_SKIP_JUDGE", "").strip().lower() in ("1", "true", "yes", "on")


def _load_samples() -> list[dict[str, Any]]:
    if not SAMPLES_PATH.is_file():
        raise FileNotFoundError(f"Missing curated samples: {SAMPLES_PATH}")
    data = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    samples = data.get("samples") or []
    if not isinstance(samples, list) or not samples:
        raise ValueError("quality_samples.json must contain a non-empty 'samples' array")
    return [s for s in samples if isinstance(s, dict)]


def _lexical_claims_support(result: dict[str, Any], article_lower: str) -> str:
    """Fraction of summary ``claims`` list items whose text appears in article (rough check)."""
    claims = result.get("claims")
    if not isinstance(claims, list) or not claims:
        return ""
    usable = 0
    hits = 0
    for c in claims:
        s = str(c).strip().lower()
        if len(s) < 16:
            continue
        usable += 1
        if s in article_lower:
            hits += 1
    if not usable:
        return ""
    return str(round(hits / usable, 3))


def _parse_judge_json(raw: str) -> dict[str, Any]:
    """Parse judge output; tolerate markdown fences and leading prose (same as social_service)."""
    out = _extract_json_object(raw or "")
    return out if isinstance(out, dict) else {}


def _run_judge(
    client: OllamaClient,
    *,
    title: str,
    content: str,
    gold_tickers: list[str],
    summary_dict: dict[str, Any],
) -> dict[str, Any]:
    try:
        from glm_config import get_zhipu_api_key
    except ImportError:
        return {"judge_error": "glm_config_unavailable"}
    if not get_zhipu_api_key():
        return {"judge_error": "no_zhipu_api_key"}

    summary_blob = json.dumps(
        {
            "summary": summary_dict.get("summary"),
            "tickers": summary_dict.get("tickers"),
            "claims": summary_dict.get("claims"),
            "fact_check": summary_dict.get("fact_check"),
            "conclusion": summary_dict.get("conclusion"),
            "sentiment": summary_dict.get("sentiment"),
            "market_relevance": summary_dict.get("market_relevance"),
        },
        default=str,
    )[:14000]

    prompt = f"""You are an impartial evaluator. Score the AI article summary JSON against the source article only.

Article title: {title}
Article text:
{content[:12000]}

Gold tickers (reference list from benchmark; may be incomplete): {json.dumps(gold_tickers)}

Model summary JSON (subset of fields):
{summary_blob}

Return ONLY a JSON object with these exact keys (integers where noted):
{{
  "factuality": <1-5 integer, claims supported by article>,
  "relevance": <1-5 integer, market-relevant focus>,
  "ticker_correctness": <1-5 integer, tickers vs article + gold list>,
  "clarity": <1-5 integer, readable useful prose in summary field>,
  "hallucination_flag": <0 or 1 integer, 1 if clear invented facts not in article>,
  "notes": "<=300 chars string>"
}}
No markdown fences."""

    max_attempts = max(1, int(os.getenv("QUALITY_JUDGE_MAX_ATTEMPTS", "3")))
    raw = ""
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            gen = client.query_ollama(
                prompt=prompt,
                model=BENCH_JUDGE_MODEL,
                stream=False,
                json_mode=True,
                temperature=0.1,
                max_tokens=None,
            )
            raw = "".join(gen)
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                time.sleep(2.0**attempt)
                continue
            return {"judge_error": type(exc).__name__, "judge_raw": ""}

        parsed = _parse_judge_json(raw)
        if parsed:
            return parsed

        if zai_error_text_probably_transient(raw) and attempt < max_attempts - 1:
            time.sleep(2.0**attempt)
            continue

        return {"judge_error": "parse_failed", "judge_raw": raw[:2000]}

    if last_exc is not None:
        return {"judge_error": type(last_exc).__name__, "judge_raw": ""}
    return {"judge_error": "parse_failed", "judge_raw": raw[:500]}


def _write_summary_artifacts(ts: str, artifacts: list[dict[str, Any]]) -> Path | None:
    """Persist parseable summaries so the GLM judge can be re-run without re-summarizing."""
    if not artifacts:
        return None
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"quality_{ts}_summaries.json"
    payload = {"schema_version": 1, "run_ts": ts, "items": artifacts}
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _write_outputs(
    rows: list[dict[str, Any]],
    *,
    ts: str | None = None,
) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = ts or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    csv_path = OUTPUT_DIR / f"quality_{ts}.csv"
    md_path = OUTPUT_DIR / f"quality_{ts}.md"
    if not rows:
        csv_path.write_text(
            "run_id,sample_id,model,parse_ok,lexical_claims_support,judge_skipped,"
            "factuality,relevance,ticker_correctness,clarity,hallucination_flag,notes,duration_ms\n",
            encoding="utf-8",
        )
        md_path.write_text("# LLM quality bench (empty)\n", encoding="utf-8")
        return csv_path, md_path

    fieldnames = list(rows[0].keys())
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        buckets[str(r.get("model", ""))].append(r)

    lines = [
        f"# LLM quality benchmark `{ts}`",
        "",
        "_Judge is not ground truth; scores are relative signal._",
        "",
        "**Legend:** **F** factuality, **R** relevance, **T** ticker correctness, **C** clarity, **H** hallucination flag (0/1); "
        "**mean lexical claims** = mean fraction of long `claims[]` strings that appear as substrings of the article (case-insensitive); "
        "**mean ms** = average summarizer latency.",
        "",
        "| model | n | parse_ok % | mean lexical claims | mean factuality | mean relevance | "
        "mean ticker_corr | mean clarity | hallucination_rate % | mean ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, rs in sorted(buckets.items()):
        if not model:
            continue
        n = len(rs)
        ok_pct = round(100.0 * sum(1 for x in rs if int(x.get("parse_ok") or 0)) / n, 1) if n else 0.0

        def _mean(key: str) -> str:
            vals = []
            for x in rs:
                v = x.get(key)
                if v in ("", None):
                    continue
                try:
                    vals.append(float(v))
                except (TypeError, ValueError):
                    continue
            if not vals:
                return "n/a"
            return str(round(sum(vals) / len(vals), 2))

        hall = [
            float(x["hallucination_flag"])
            for x in rs
            if str(x.get("hallucination_flag", "")).strip() in ("0", "1", "0.0", "1.0")
        ]
        hall_pct = round(100.0 * sum(hall) / len(hall), 1) if hall else "n/a"

        durs = [float(x["duration_ms"]) for x in rs if x.get("duration_ms")]
        mean_ms = round(sum(durs) / len(durs), 0) if durs else 0.0

        lines.append(
            f"| {model} | {n} | {ok_pct} | {_mean('lexical_claims_support')} | "
            f"{_mean('factuality')} | {_mean('relevance')} | {_mean('ticker_correctness')} | "
            f"{_mean('clarity')} | {hall_pct} | {mean_ms} |"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, md_path


@pytest.mark.bench
def test_bench_llm_quality_judge() -> None:
    if not _quality_enabled():
        pytest.skip(f"Set {QUALITY_ENV}=1 to run quality benchmarks")

    samples = _load_samples()
    client = OllamaClient()
    if not client.enabled:
        pytest.skip("OLLAMA_ENABLED is false")

    models_env = os.getenv(
        "OLLAMA_QUALITY_MODELS",
        "qwen3.8:27b-mtp-q4_K_M,granite4.1:8b,glm-5.1,glm-5-turbo,glm-4.5-air",
    )
    models = [m.strip() for m in models_env.split(",") if m.strip()]
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    ts_iso = datetime.now(UTC).isoformat()
    ts_slug = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    rows: list[dict[str, Any]] = []
    summary_artifacts: list[dict[str, Any]] = []

    for model in models:
        if model.startswith("glm-"):
            try:
                from glm_config import get_zhipu_api_key

                if not get_zhipu_api_key():
                    continue
            except ImportError:
                continue
        elif not client.check_health_for_model(model):
            continue
        for sample in samples:
            sid = str(sample.get("id", ""))
            title = (sample.get("title") or "").strip()
            content = (sample.get("content") or "").strip()
            article_type = (sample.get("article_type") or "Market News").strip()
            gold = sample.get("gold_tickers") or []
            if isinstance(gold, str):
                gold = [gold]
            text = f"Title: {title}\n\n{content}" if title else content
            article_lower = (title + "\n" + content).lower()

            t0 = time.perf_counter()
            err = ""
            result: dict[str, Any] = {}
            try:
                out = _generate_summary_once(
                    text=text,
                    model=model,
                    article_type=article_type,
                    stream=False,
                    progress_callback=None,
                )
                if isinstance(out, dict):
                    result = out
            except Exception as e:
                err = type(e).__name__
            duration_ms = round((time.perf_counter() - t0) * 1000, 1)

            parse_ok = 1 if (isinstance(result, dict) and str(result.get("summary", "")).strip()) else 0
            lex = _lexical_claims_support(result, article_lower)
            if parse_ok and isinstance(result, dict):
                summary_artifacts.append(
                    {
                        "run_id": run_id,
                        "sample_id": sid,
                        "model": model,
                        "parse_ok": parse_ok,
                        "lexical_claims_support": lex,
                        "duration_ms": duration_ms,
                        "error_type": err,
                        "summary": result,
                    }
                )

            judge_row: dict[str, Any] = {
                "factuality": "",
                "relevance": "",
                "ticker_correctness": "",
                "clarity": "",
                "hallucination_flag": "",
                "notes": "",
                "judge_skipped": "1",
            }
            if parse_ok and result and not _skip_glm_judge():
                jr = _run_judge(
                    client,
                    title=title,
                    content=content,
                    gold_tickers=[str(x) for x in gold],
                    summary_dict=result,
                )
                if jr.get("judge_error"):
                    judge_row["judge_skipped"] = "1"
                    judge_row["notes"] = str(jr.get("judge_error", ""))[:300]
                else:
                    judge_row["judge_skipped"] = "0"
                    for k in (
                        "factuality",
                        "relevance",
                        "ticker_correctness",
                        "clarity",
                        "hallucination_flag",
                        "notes",
                    ):
                        if k in jr:
                            judge_row[k] = jr[k]
            elif parse_ok and result and _skip_glm_judge():
                judge_row["judge_skipped"] = "1"
                judge_row["notes"] = "OLLAMA_QUALITY_SKIP_JUDGE"

            rows.append(
                {
                    "run_id": run_id,
                    "timestamp": ts_iso,
                    "sample_id": sid,
                    "model": model,
                    "parse_ok": parse_ok,
                    "lexical_claims_support": lex,
                    "duration_ms": duration_ms,
                    "error_type": err,
                    **judge_row,
                }
            )

    csv_path, md_path = _write_outputs(rows, ts=ts_slug)
    art_path = _write_summary_artifacts(ts_slug, summary_artifacts)
    print(f"[llm_quality_bench] wrote {csv_path} and {md_path}")
    if art_path:
        print(f"[llm_quality_bench] wrote {art_path} (re-run judge: python verification/quality/rerun_quality_judge.py {art_path})")
    assert csv_path.is_file() and md_path.is_file()
