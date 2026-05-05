"""Quick subset quality run for local comparison (not pytest).

Writes ``BENCHMARK_RESULTS.md`` in this directory. Usage::

    cd project_root
    .\\venv\\Scripts\\activate
    python verification/quality/run_subset_benchmark.py

Optional env:
    QUALITY_SUBSET_MODELS      comma models (default: model_registry.BENCH_DEFAULT_CANDIDATES / OLLAMA_QUALITY_MODELS)
    QUALITY_SUBSET_N           max samples (default: 3)
    OLLAMA_QUALITY_SKIP_JUDGE   1 = do not call GLM-5.1 judge (faster; no Z.AI)
    QUALITY_JUDGE_MAX_ATTEMPTS  max GLM judge calls per row when Z.AI returns transient errors (default: 3)

Each run overwrites ``verification/quality/run_subset_benchmark.log`` (timestamped lines; file +
stderr). Use the log to see where a run stalled (model/sample phase, summarize vs judge).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
WEB = ROOT / "web_dashboard"
sys.path.insert(0, str(WEB))
sys.path.insert(0, str(ROOT))

from model_registry import (  # noqa: E402
    BENCH_DEFAULT_CANDIDATES,
    BENCH_JUDGE_MODEL,
    zai_error_text_probably_transient,
)
from ollama_client import (  # noqa: E402
    GLM_JSON_MODE_MIN_TIMEOUT,
    GLM_TIMEOUT,
    OllamaClient,
    _generate_summary_once,
)
from social_service import _extract_json_object  # noqa: E402

SAMPLES_PATH = Path(__file__).resolve().parent / "quality_samples.json"
OUT_MD = Path(__file__).resolve().parent / "BENCHMARK_RESULTS.md"
LOG_PATH = Path(__file__).resolve().parent / "run_subset_benchmark.log"


def _markdown_legend_lines() -> list[str]:
    """Human-readable definitions for aggregate and per-row tables."""
    return [
        "## How to read this report",
        "",
        f"**Who scores what:** Summaries come from the listed Ollama/Z.AI models. **Judge** is always **{BENCH_JUDGE_MODEL}** (Z.AI), "
        "using a fixed rubric. Scores are **relative QA signal**, not ground truth.",
        "",
        "### Judge columns (abbreviated **F R T C H**)",
        "",
        "| Abbr | Name | What it measures | Scale |",
        "|---|---|---|---|",
        "| **F** | Factuality | Claims in the summary JSON supported by the source article | 1–5 (higher better) |",
        "| **R** | Relevance | Market-relevant focus vs noise | 1–5 |",
        "| **T** | Ticker correctness | Tickers vs article text and the benchmark **gold** ticker list | 1–5 |",
        "| **C** | Clarity | Readable, useful prose in the `summary` field | 1–5 |",
        "| **H** | Hallucination flag | Clear invented facts **not** in the article | **0** = none, **1** = suspected |",
        "",
        "### Other columns",
        "",
        (
            "- **mean lexical** (summary-by-model table): Average of **lex** over rows for that model.\n"
            "- **halluc %** (summary-by-model table): Percentage of scored rows where **H** (hallucination flag) is **1**."
        ),
        "- **lex** (per row): Of `claims[]` items longer than 15 characters, the **fraction** whose text appears "
        "as a substring of the article (case-insensitive). Empty string if there are no qualifying claims. "
        "This is a **cheap lexical anchor check**, not semantic entailment.",
        "- **parse**: `1` if the summarizer returned a non-empty `summary` field.",
        "- **ms**: Wall time for the **summarizer** call only (judge time is separate).",
        "- **err**: Exception type if summarization threw; blank if OK.",
        "",
        "---",
        "",
    ]


def _notes_plain_text(notes: str) -> str:
    """Single line safe for markdown bullets; keeps full length."""
    return (notes or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _configure_logging() -> logging.Logger:
    log = logging.getLogger("run_subset_benchmark")
    log.handlers.clear()
    log.setLevel(logging.DEBUG)
    log.propagate = False
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    fh = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


def _lexical_claims_support(result: dict, article_lower: str) -> str:
    claims = result.get("claims")
    if not isinstance(claims, list) or not claims:
        return ""
    usable = hits = 0
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


def _parse_judge_json(raw: str) -> dict:
    out = _extract_json_object(raw or "")
    return out if isinstance(out, dict) else {}


def _skip_glm_judge() -> bool:
    return os.getenv("OLLAMA_QUALITY_SKIP_JUDGE", "").strip().lower() in ("1", "true", "yes", "on")


def _run_judge(
    client: OllamaClient,
    *,
    title: str,
    content: str,
    gold: list[str],
    summary_dict: dict,
    log: logging.Logger,
) -> dict:
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

Gold tickers (reference list from benchmark; may be incomplete): {json.dumps(gold)}

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
            t_j = time.perf_counter()
            gen = client.query_ollama(
                prompt=prompt,
                model=BENCH_JUDGE_MODEL,
                stream=False,
                json_mode=True,
                temperature=0.1,
                max_tokens=None,
            )
            raw = "".join(gen)
            log.debug(
                "judge %s finished in %.0f ms; raw_len=%d prefix=%r",
                BENCH_JUDGE_MODEL,
                (time.perf_counter() - t_j) * 1000,
                len(raw),
                (raw[:240] + ("…" if len(raw) > 240 else "")).replace("\n", "\\n"),
            )
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                delay = 2.0**attempt
                log.warning(
                    "judge %s attempt %s/%s raised %s; retry in %.1fs",
                    BENCH_JUDGE_MODEL,
                    attempt + 1,
                    max_attempts,
                    type(exc).__name__,
                    delay,
                )
                time.sleep(delay)
                continue
            log.exception("judge %s request failed: %s", BENCH_JUDGE_MODEL, exc)
            return {"judge_error": type(exc).__name__}

        parsed = _parse_judge_json(raw)
        if parsed:
            return parsed

        transient = zai_error_text_probably_transient(raw)
        if transient and attempt < max_attempts - 1:
            delay = 2.0**attempt
            log.warning(
                "judge parse_failed (transient?) attempt %s/%s raw_prefix=%r; retry in %.1fs",
                attempt + 1,
                max_attempts,
                (raw[:120] + ("…" if len(raw) > 120 else "")).replace("\n", "\\n"),
                delay,
            )
            time.sleep(delay)
            continue

        log.warning(
            "judge parse_failed raw_len=%d prefix=%r",
            len(raw),
            (raw[:400] + ("…" if len(raw) > 400 else "")).replace("\n", "\\n"),
        )
        return {"judge_error": "parse_failed", "judge_raw": raw[:500]}

    if last_exc is not None:
        return {"judge_error": type(last_exc).__name__}
    return {"judge_error": "parse_failed", "judge_raw": raw[:500]}


def main() -> None:
    wall0 = time.perf_counter()
    log = _configure_logging()
    log.info("log file: %s", LOG_PATH.resolve())

    n_samples = int(os.getenv("QUALITY_SUBSET_N", "3"))
    models_raw = os.getenv(
        "QUALITY_SUBSET_MODELS",
        BENCH_DEFAULT_CANDIDATES,
    )
    models = [m.strip() for m in models_raw.split(",") if m.strip()]

    samples = json.loads(SAMPLES_PATH.read_text(encoding="utf-8")).get("samples") or []
    samples = [s for s in samples if isinstance(s, dict)][:n_samples]

    client = OllamaClient()
    _glm_json_eff = max(GLM_TIMEOUT, GLM_JSON_MODE_MIN_TIMEOUT)
    log.info(
        "config: QUALITY_SUBSET_N=%s (%d samples) models=%s OLLAMA_ENABLED=%s "
        "GLM_TIMEOUT=%s GLM_JSON_MODE_MIN_TIMEOUT=%s (json_mode glm uses max => %ss) skip_judge=%s",
        os.getenv("QUALITY_SUBSET_N", "3"),
        len(samples),
        models,
        getattr(client, "enabled", None),
        GLM_TIMEOUT,
        GLM_JSON_MODE_MIN_TIMEOUT,
        _glm_json_eff,
        _skip_glm_judge(),
    )
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    rows: list[dict] = []

    for model in models:
        log.info("--- model %s ---", model)
        if model.startswith("glm-"):
            try:
                from glm_config import get_zhipu_api_key

                if not get_zhipu_api_key():
                    log.warning("skip model %s: no ZHIPU key", model)
                    rows.append({"model": model, "sample_id": "_skipped_", "note": "no ZHIPU key"})
                    continue
            except ImportError:
                log.warning("skip model %s: glm_config missing", model)
                rows.append({"model": model, "sample_id": "_skipped_", "note": "glm_config missing"})
                continue
        elif client.enabled and not client.check_health_for_model(model):
            log.warning("skip model %s: Ollama health check failed (model not on resolved host?)", model)
            rows.append({"model": model, "sample_id": "_skipped_", "note": "Ollama model not available"})
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

            log.info("summarize start model=%s sample=%s", model, sid)
            t0 = time.perf_counter()
            err = ""
            result: dict = {}
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
                log.exception("summarize exception model=%s sample=%s", model, sid)
            duration_ms = round((time.perf_counter() - t0) * 1000, 1)
            log.info(
                "summarize done model=%s sample=%s ms=%s parse_ok=%s err=%s",
                model,
                sid,
                duration_ms,
                bool(isinstance(result, dict) and str(result.get("summary", "")).strip()),
                err or "-",
            )

            parse_ok = bool(isinstance(result, dict) and str(result.get("summary", "")).strip())
            lex = _lexical_claims_support(result, article_lower)

            jr = {
                "factuality": "",
                "relevance": "",
                "ticker_correctness": "",
                "clarity": "",
                "hallucination_flag": "",
                "judge_skipped": "1",
            }
            if parse_ok and result and not _skip_glm_judge():
                log.info("judge start model=%s sample=%s (%s)", model, sid, BENCH_JUDGE_MODEL)
                judged = _run_judge(
                    client,
                    title=title,
                    content=content,
                    gold=[str(x) for x in gold],
                    summary_dict=result,
                    log=log,
                )
                if judged.get("judge_error"):
                    jr["notes"] = str(judged.get("judge_error", ""))[:200]
                    log.warning(
                        "judge error model=%s sample=%s code=%s",
                        model,
                        sid,
                        judged.get("judge_error"),
                    )
                else:
                    jr["judge_skipped"] = "0"
                    for k in (
                        "factuality",
                        "relevance",
                        "ticker_correctness",
                        "clarity",
                        "hallucination_flag",
                        "notes",
                    ):
                        if k in judged:
                            jr[k] = judged[k]
                    log.info(
                        "judge ok model=%s sample=%s F=%s R=%s",
                        model,
                        sid,
                        jr.get("factuality"),
                        jr.get("relevance"),
                    )
            elif parse_ok and result and _skip_glm_judge():
                jr["notes"] = "OLLAMA_QUALITY_SKIP_JUDGE"

            rows.append(
                {
                    "model": model,
                    "sample_id": sid,
                    "parse_ok": int(parse_ok),
                    "lexical_claims_support": lex,
                    "duration_ms": duration_ms,
                    "error_type": err,
                    **jr,
                }
            )

    # Aggregate by model
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("sample_id") not in ("_skipped_",) and r.get("model"):
            buckets[str(r["model"])].append(r)

    lines = [
        "# LLM quality benchmark (subset run)",
        "",
        f"_Generated: {ts} (subset script: `verification/quality/run_subset_benchmark.py`)_",
        "",
        f"**Samples:** first {len(samples)} of `quality_samples.json` | **Models:** `{', '.join(models)}`",
        "",
    ]
    lines.extend(_markdown_legend_lines())

    lines += [
        "## Summary by model",
        "",
        "| model | n | parse_ok % | mean lexical | mean factuality | mean relevance | mean ticker | mean clarity | halluc % | mean ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def mean_key(rs: list[dict], key: str) -> str:
        vals = []
        for x in rs:
            v = x.get(key)
            if v in ("", None):
                continue
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
        return str(round(sum(vals) / len(vals), 2)) if vals else "n/a"

    for model, rs in sorted(buckets.items()):
        if not rs:
            continue
        n = len(rs)
        ok_pct = round(100.0 * sum(1 for x in rs if int(x.get("parse_ok") or 0)) / n, 1)
        hall = [
            float(x["hallucination_flag"])
            for x in rs
            if str(x.get("hallucination_flag", "")).strip() in ("0", "1", "0.0", "1.0")
        ]
        hall_pct = round(100.0 * sum(hall) / len(hall), 1) if hall else "n/a"
        durs = [float(x["duration_ms"]) for x in rs if x.get("duration_ms")]
        mean_ms = round(sum(durs) / len(durs), 0) if durs else 0.0
        lines.append(
            f"| {model} | {n} | {ok_pct} | {mean_key(rs, 'lexical_claims_support')} | "
            f"{mean_key(rs, 'factuality')} | {mean_key(rs, 'relevance')} | {mean_key(rs, 'ticker_correctness')} | "
            f"{mean_key(rs, 'clarity')} | {hall_pct} | {mean_ms} |"
        )

    lines += [
        "",
        "## Per-row scores",
        "",
        "Judge commentary is **not** in this table (see **Full judge notes** below) so columns stay readable.",
        "",
        "| model | sample | parse | lex | F | R | T | C | H | ms | err |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in rows:
        if r.get("sample_id") == "_skipped_":
            lines.append(
                f"| {r.get('model')} | (skipped) | — | — | — | — | — | — | — | — | "
                f"{str(r.get('note', '') or '').replace('|', '/')[:120]} |"
            )
            continue
        lines.append(
            f"| {r.get('model')} | {r.get('sample_id')} | {r.get('parse_ok')} | {r.get('lexical_claims_support','')} | "
            f"{r.get('factuality','')} | {r.get('relevance','')} | {r.get('ticker_correctness','')} | {r.get('clarity','')} | "
            f"{r.get('hallucination_flag','')} | {r.get('duration_ms','')} | {r.get('error_type','') or '-'} |"
        )

    lines += [
        "",
        "## Full judge notes",
        "",
        "_One bullet per row. Text is the GLM-5.1 `notes` field (the judge prompt asks for a short string; "
        "multi-line output is flattened to one paragraph). If summarization failed, the summarizer error type is shown._",
        "",
    ]
    n_note = 0
    for r in rows:
        if r.get("sample_id") == "_skipped_":
            continue
        n_note += 1
        note = _notes_plain_text(str(r.get("notes") or ""))
        err = str(r.get("error_type") or "").strip()
        head = f"**{r.get('model')}** · `{r.get('sample_id')}`"
        parts: list[str] = []
        if err:
            parts.append(f"Summarizer error: `{err}`.")
        if note:
            parts.append(" ".join(note.splitlines()))
        elif not err:
            parts.append("_No judge notes text for this row._")
        lines.append(f"{n_note}. {head} — {' '.join(parts)}")
        lines.append("")
    if n_note == 0:
        lines.append("_No data rows in this run._")
        lines.append("")

    lines += [
        "",
        "## Full corpus + pytest bench",
        "",
        "For all samples and default model list, run:",
        "",
        "```powershell",
        "$env:OLLAMA_QUALITY_BENCH='1'",
        "python -m pytest tests/benchmarks/llm_quality_bench.py -m bench -v",
        "```",
        "",
        "Artifacts: `verification/quality/quality_<timestamp>.md` (gitignored).",
        "",
        "**Note:** `tests/benchmarks/llm_quality_bench.py` had a typo fix (`dict[str, list[dict[str, Any]]]`); re-run pytest bench after pull.",
    ]

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elapsed = time.perf_counter() - wall0
    log.info("finished in %.1f s - wrote %s (rows=%d)", elapsed, OUT_MD.resolve(), len(rows))
    print(f"Wrote {OUT_MD}")
    print(f"Log: {LOG_PATH.resolve()}")


if __name__ == "__main__":
    main()
