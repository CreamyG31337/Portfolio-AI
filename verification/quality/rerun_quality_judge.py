"""Re-run only the GLM-5.1 judge on a saved quality bench summaries file.

The pytest bench (``OLLAMA_QUALITY_BENCH=1``) writes ``quality_<ts>_summaries.json`` next to the CSV.
This script does **not** call Ollama again; it only re-invokes the judge using stored ``summary`` dicts.

Usage::

    cd project_root
    .\\venv\\Scripts\\activate
    python verification/quality/rerun_quality_judge.py verification/quality/quality_20260503T120000Z_summaries.json

"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
WEB = ROOT / "web_dashboard"
BENCH = ROOT / "tests" / "benchmarks" / "llm_quality_bench.py"
SAMPLES = Path(__file__).resolve().parent / "quality_samples.json"

sys.path.insert(0, str(WEB))
sys.path.insert(0, str(ROOT))


def _load_bench_module():
    spec = importlib.util.spec_from_file_location("llm_quality_bench", BENCH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {BENCH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        print(
            "Usage: python verification/quality/rerun_quality_judge.py "
            "verification/quality/quality_<timestamp>_summaries.json",
            file=sys.stderr,
        )
        raise SystemExit(2)
    path = Path(argv[1]).resolve()
    if not path.is_file():
        raise SystemExit(f"Not a file: {path}")

    name = path.name
    if not name.startswith("quality_") or "_summaries.json" not in name:
        raise SystemExit(f"Expected quality_<ts>_summaries.json, got: {name}")
    ts_in = name[len("quality_") : name.index("_summaries")]
    out_ts = f"{ts_in}_judged_rerun"

    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise SystemExit("No items in summaries JSON")

    samples_raw = json.loads(SAMPLES.read_text(encoding="utf-8"))
    samples_list = samples_raw.get("samples") or []
    by_id = {str(s.get("id")): s for s in samples_list if isinstance(s, dict)}

    llmqb = _load_bench_module()
    _run_judge = llmqb._run_judge
    _write_outputs = llmqb._write_outputs

    from datetime import UTC, datetime

    from ollama_client import OllamaClient

    client = OllamaClient()
    ts_iso = datetime.now(UTC).isoformat()
    rows: list[dict] = []

    for it in items:
        if not isinstance(it, dict):
            continue
        sid = str(it.get("sample_id", ""))
        sample = by_id.get(sid)
        if not sample:
            print(f"[warn] unknown sample_id {sid}, skipping", file=sys.stderr)
            continue
        title = (sample.get("title") or "").strip()
        content = (sample.get("content") or "").strip()
        gold = sample.get("gold_tickers") or []
        if isinstance(gold, str):
            gold = [gold]
        summary = it.get("summary")
        if not isinstance(summary, dict):
            continue

        judge_row: dict = {
            "factuality": "",
            "relevance": "",
            "ticker_correctness": "",
            "clarity": "",
            "hallucination_flag": "",
            "notes": "",
            "judge_skipped": "1",
        }
        jr = _run_judge(
            client,
            title=title,
            content=content,
            gold_tickers=[str(x) for x in gold],
            summary_dict=summary,
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

        rows.append(
            {
                "run_id": str(it.get("run_id", "")) + "_judge_rerun",
                "timestamp": ts_iso,
                "sample_id": sid,
                "model": str(it.get("model", "")),
                "parse_ok": int(it.get("parse_ok") or 0),
                "lexical_claims_support": it.get("lexical_claims_support", ""),
                "duration_ms": it.get("duration_ms", ""),
                "error_type": it.get("error_type", ""),
                **judge_row,
            }
        )

    csv_path, md_path = _write_outputs(rows, ts=out_ts)
    print(f"Wrote {csv_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main(sys.argv)
