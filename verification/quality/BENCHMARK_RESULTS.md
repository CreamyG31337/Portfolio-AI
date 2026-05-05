# LLM quality benchmark (subset run)

_Generated: 2026-05-04 23:17 UTC (subset script: `verification/quality/run_subset_benchmark.py`)_

**Samples:** first 3 of `quality_samples.json` | **Models:** `glm-5.1, glm-5-turbo`

## How to read this report

**Who scores what:** Summaries come from the listed Ollama/Z.AI models. **Judge** is always **glm-5.1** (Z.AI), using a fixed rubric. Scores are **relative QA signal**, not ground truth.

### Judge columns (abbreviated **F R T C H**)

| Abbr | Name | What it measures | Scale |
|---|---|---|---|
| **F** | Factuality | Claims in the summary JSON supported by the source article | 1–5 (higher better) |
| **R** | Relevance | Market-relevant focus vs noise | 1–5 |
| **T** | Ticker correctness | Tickers vs article text and the benchmark **gold** ticker list | 1–5 |
| **C** | Clarity | Readable, useful prose in the `summary` field | 1–5 |
| **H** | Hallucination flag | Clear invented facts **not** in the article | **0** = none, **1** = suspected |

### Other columns

- **mean lexical** (summary-by-model table): Average of **lex** over rows for that model.
- **halluc %** (summary-by-model table): Percentage of scored rows where **H** (hallucination flag) is **1**.
- **lex** (per row): Of `claims[]` items longer than 15 characters, the **fraction** whose text appears as a substring of the article (case-insensitive). Empty string if there are no qualifying claims. This is a **cheap lexical anchor check**, not semantic entailment.
- **parse**: `1` if the summarizer returned a non-empty `summary` field.
- **ms**: Wall time for the **summarizer** call only (judge time is separate).
- **err**: Exception type if summarization threw; blank if OK.

---

## Summary by model

| model | n | parse_ok % | mean lexical | mean factuality | mean relevance | mean ticker | mean clarity | halluc % | mean ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| glm-5-turbo | 3 | 100.0 | 0.28 | 4.0 | 5.0 | 1.0 | 5.0 | 0.0 | 39482.0 |
| glm-5.1 | 3 | 100.0 | 0.37 | 5.0 | 5.0 | 2.0 | 5.0 | 0.0 | 26530.0 |

## Per-row scores

Judge commentary is **not** in this table (see **Full judge notes** below) so columns stay readable.

| model | sample | parse | lex | F | R | T | C | H | ms | err |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| glm-5.1 | synth-01-earnings | 1 | 0.571 | 5 | 5 | 2 | 5 | 0 | 28886.9 | - |
| glm-5.1 | synth-02-macro | 1 | 0.2 | 5 | 5 | 2 | 5 | 0 | 20792.0 | - |
| glm-5.1 | synth-03-mna | 1 | 0.333 | 5 | 5 | 2 | 5 | 0 | 29911.9 | - |
| glm-5-turbo | synth-01-earnings | 1 | 0.4 |  |  |  |  |  | 49388.4 | - |
| glm-5-turbo | synth-02-macro | 1 | 0.25 |  |  |  |  |  | 20764.9 | - |
| glm-5-turbo | synth-03-mna | 1 | 0.2 | 4 | 5 | 1 | 5 | 0 | 48292.4 | - |

## Full judge notes

_One bullet per row. Text is the GLM-5.1 `notes` field (the judge prompt asks for a short string; multi-line output is flattened to one paragraph). If summarization failed, the summarizer error type is shown._

1. **glm-5.1** · `synth-01-earnings` — Summary accurately captures all article details with clear structure. Ticker field empty despite gold tickers NVDA/AMD being relevant competitors mentioned in text. All claims verified against source.

2. **glm-5.1** · `synth-02-macro` — Summary is highly accurate with all claims directly supported by the article. Well-structured bullet points. However, tickers array is empty while gold list includes TLT - a significant omission given the Treasury yield focus of the article.

3. **glm-5.1** · `synth-03-mna` — All claims accurately sourced from article. Empty ticker list misses gold tickers RF/PBCT though article doesn't explicitly mention them. Summary and conclusion are well-structured and informative.

4. **glm-5-turbo** · `synth-01-earnings` — parse_failed

5. **glm-5-turbo** · `synth-02-macro` — parse_failed

6. **glm-5-turbo** · `synth-03-mna` — Summary accurately captures article details. Missing gold tickers RF and PBCT - returned empty array. Final bullet about execution risk is analytical inference not explicitly stated in source. Claims section is accurate.


## Full corpus + pytest bench

For all samples and default model list, run:

```powershell
$env:OLLAMA_QUALITY_BENCH='1'
python -m pytest tests/benchmarks/llm_quality_bench.py -m bench -v
```

Artifacts: `verification/quality/quality_<timestamp>.md` (gitignored).

**Note:** `tests/benchmarks/llm_quality_bench.py` had a typo fix (`dict[str, list[dict[str, Any]]]`); re-run pytest bench after pull.
