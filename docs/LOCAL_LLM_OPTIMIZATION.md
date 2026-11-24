# Local LLM Inference Optimization & Benchmarks (Nov 2026)

This document captures our live hardware audit, configuration fixes, and empirical benchmarks applying **`llama.cpp` PR #31669** (*GDN: use replay instead of rollback*, merged Nov 23, 2026) and portable **`squid5090` (`LITE.md`)** inference techniques across the home fleet while the RTX 3090 is offline.

---

## 1. Fleet Hardware & Software State (Updated Nov 24, 2026)

| Host | GPU & Bandwidth | RAM | Production Runtime | Staged `llama.cpp` | Notes |
|---|---|---|---|---|---|
| **`ubuntu-server`** (`100.64.188.1`) | **RX 6800 XT 16 GB** (RDNA2, ~512 GB/s, 33–58°C) | 62 GB | Docker `ollama/ollama:rocm` **v0.40.18** (`OLLAMA_KV_CACHE_TYPE=q8_0`) | `~/llama.cpp.b12680-vulkan/llama-b12680/` (Vulkan) | Hosts `trading-dashboard-flask`. Adding `q8_0` KV saved **2.62 GB VRAM** on `granite4.1:8b` (13.07 → 10.45 GB @ 24k ctx). |
| **`ts-msi-laptop`** (`100.81.65.112`) | **RTX 3080 Laptop 16 GB** (Ampere, ~448 GB/s, 50–71°C) | 64 GB | **Ollama v0.40.18** (`OLLAMA_KV_CACHE_TYPE=q8_0`, 65k ctx) | `C:\opt\llama.cpp.b12680\` (CUDA 12.4) | Upgraded from `0.40.2` → `0.40.18` (saved **0.69 GB VRAM** on `qwen3.5:9b-q8_0`: 10.28 → 9.59 GB, 42 tok/s). Note: slow Wi-Fi (~2.8 MB/s) for large HF downloads. |
| **`ts-cr-desktop`** (local) | **RTX 3080 10 GB** (Ampere, ~760 GB/s) | 31 GB | **Ollama v0.40.18** (stopped) | — | Highest bandwidth (~1.7× laptop 3080), but daily desktop apps use ~6.5 / 10 GB VRAM. |

> **Why `b12680` matters:** `llama.cpp` PR #31669 (`d35dc4d9`) merged Nov 23, 2026 and is included in `b12680`+. It replaces Gated DeltaNet (GDN) recurrent-state rollback snapshots with state replay during speculative decoding, cutting recurrent state VRAM by **73–91% per sequence** on Qwen3.5 / Qwen3.6 / Qwen3.8 hybrids across CUDA, HIP, and Vulkan.

---

## 2. Empirical Benchmark Results

All benchmarks ran two real-world prompts:
- **Extract (high prompt overlap):** Financial press-release → structured JSON extraction (tickers, revenue, margins, guidance, 3 exact risk quotes).
- **Analysis (low prompt overlap):** 150-word analytical explanation of semiconductor inventory/margin warning signs.

### A. `ts-msi-laptop` — RTX 3080 Laptop 16 GB (CUDA, `qwen3.5:9b-q8_0` @ 65,536 ctx)

| Config | Build | KV | Slots | Speculative Decoding | VRAM | Prompt (`pp`) | Extract (`tg`) | Analysis (`tg`) | Draft Accepted |
|---|---|---|---|---|---:|---:|---:|---:|---|
| 1. Baseline | `b9505` | `q8_0` | 1 | none | 9,741 MiB | 1,315 tok/s | 43.1 tok/s | 43.6 tok/s | — |
| 2. Pre-PR #31669 | `b9505` | `q8_0` | 2 | `ngram-simple` (default 12/48) | 9,759 MiB | 1,810 tok/s | 43.4 tok/s | 43.4 tok/s | 0/0 |
| 3. Post-PR #31669 | `b12680` | `q8_0` | 2 | `ngram-simple` (default 12/48) | 9,769 MiB | **1,986 tok/s** | 43.6 tok/s | 43.5 tok/s | 0/0 |
| **4. Post-PR #31669 + Tuned** | **`b12680`** | **`q4_0`** | **2** | **`ngram-simple` (`n=6, m=16`)** | **9,257 MiB** | **1,851 tok/s** | **48.0 tok/s (+11.4%)** | **43.6 tok/s** | **26/64 (40.6%)** |
| 5. `ngram-cache` | `b12680` | `q4_0` | 2 | `ngram-cache` | 9,259 MiB | 1,845 tok/s | 36.8 tok/s (−15%) | 41.3 tok/s | 38/255 (14.9%) |

**Key findings:**
1. **Default `ngram-simple` (`n=12, m=48`) never fires** on short extraction prompts (`0/0`). Tuning to `--spec-ngram-simple-size-n 6 --spec-ngram-simple-size-m 16` hit **40.6% acceptance** and boosted extraction **+11.4% (43.1 → 48.0 tok/s)** with **zero penalty** on open analysis.
2. **`ngram-cache` hurt performance (−15%)** due to low acceptance (14.9%), confirming `LITE.md`'s principle: speculative decoding only wins when draft acceptance is high or draft cost is tiny.
3. **`q4_0` KV cache** saved **512 MiB** at 65k ctx with no throughput loss.
4. **Prompt eval (`pp`) jumped +41–51%** upgrading from `b9505` → `b12680`.

### B. `ts-msi-laptop` — RTX 3080 Laptop 16 GB (CUDA, `Qwen3.8-27B-UD-IQ3_S` + MTP @ 32,768 ctx, `q4_0` KV)

Measured apples-to-apples on `unsloth/Qwen3.8-27B-GGUF` (`Qwen3.8-27B-UD-IQ3_S.gguf` 11.21 GiB + `mtp-Qwen3.8-27B-Q4_0.gguf` 1.28 GiB):

| Config | Build | Speculative | VRAM | Temp | Prompt (`pp`) | Extract (`tg`) | Analysis (`tg`) | Draft Accepted (Ext / Ana) |
|---|---|---|---|---|---:|---:|---:|---|
| 1. Baseline (No MTP) | `b12680` | none | 11,873 MiB | 71°C | 613.8 tok/s | 27.2 tok/s | 27.3 tok/s | — |
| 2. Pre-PR #31669 | `b9505` | `draft-mtp` (`n=2`) | 13,531 MiB | 76°C | 564.8 tok/s | 46.3 tok/s | 31.8 tok/s | 113/114 (99%) / 100/197 (51%) |
| **3. Post-PR #31669 (`n=2`)** | **`b12680`** | **`draft-mtp` (`n=2`)** | **13,307 MiB** *(−224 MiB)* | **72°C** | **594.9 tok/s** | **56.4 tok/s (+107% vs no-MTP, +21.8% vs `b9505`)** | **38.3 tok/s (+40% vs no-MTP, +20.4% vs `b9505`)** | **111/114 (97%) / 99/199 (50%)** |
| **4. Post-PR #31669 (`n=3`)** | **`b12680`** | **`draft-mtp` (`n=3`)** | **13,311 MiB** | **73°C** | **609.1 tok/s** | **65.1 tok/s (+139% vs no-MTP!)** | **37.5 tok/s (+37%)** | **125/129 (97%) / 109/269 (41%)** |
| 5. Hybrid MTP + n-gram | `b12680` | `draft-mtp,ngram-simple` | 13,313 MiB | 75°C | 613.3 tok/s | 65.6 tok/s | 34.9 tok/s | 125/129 (97%) / 102/288 (35%) |

**Key findings:**
1. **PR #31669 (`b9505` → `b12680`) delivered +20.4% to +21.8% faster decode** at identical MTP acceptance rates, **−224 MiB less VRAM**, and **4°C cooler** GPU temps.
2. **27B Qwen3.8 + MTP is faster than 9B without MTP:** At **65.1 tok/s** (extraction) and **37.5–38.3 tok/s** (open analysis) in **13.0 GiB VRAM** (3 GiB still free on a 16 GB laptop card!), `Qwen3.8-27B-UD-IQ3_S` + MTP beats `qwen3.5:9b-q8_0` (42–48 tok/s) on structured extraction while stepping up from 9B to a flagship 27B model.
3. **Pure `draft-mtp` (`n=2` or `n=3`) beats hybrid `draft-mtp,ngram-simple`:** Adding `ngram-simple` on top of MTP only added +0.5 tok/s on extraction while costing −2.6 tok/s on open analysis.

### C. `ubuntu-server` — RX 6800 XT 16 GB (ROCm vs. Vulkan `b12680`)

| Model & Runtime | Backend | Context | KV | Slots | Speculative | VRAM | Temps (Edge / Junc) | Prompt (`pp`) | Extract (`tg`) | Analysis (`tg`) |
|---|---|---|---|---|---|---:|---|---:|---:|---:|
| `granite4.1:8b` (Ollama `v0.40.18`) | **ROCm 7.2** | 24k | `q8_0` | 1 | none | **10.45 GiB** | ~45°C | **11,531 tok/s** | **42.6 tok/s** | — |
| `batiai/qwen3.6-27b:iq3` (Ollama `v0.40.18`) | **ROCm 7.2** | 32k | `q8_0` | 1 | none | **11.37 GiB** | ~50°C | **2,110 tok/s** | **29.0 tok/s** | — |
| `batiai/qwen3.6-27b:iq3` (`llama-server b12680`) | Vulkan (RADV) | 32k | `q8_0` | 1 | none | 11.46 GiB | 49°C / 51°C | 159 tok/s | **29.3 tok/s** | 29.2 tok/s |
| `batiai/qwen3.6-27b:iq3` (`llama-server b12680`) | Vulkan (RADV) | 32k | `q4_0` | 2 | `ngram-simple` (6/16) | **11.09 GiB** | 54°C / 56°C | 248 tok/s | 26.5 tok/s | 29.3 tok/s |
| `batiai/qwen3.6-27b:iq3` (`llama-server b12680`) | Vulkan (RADV) | **64k** | `q4_0` | 1 | `ngram-simple` (6/16) | **11.56 GiB** | **57°C / 58°C** | 252 tok/s | 27.5 tok/s | **29.4 tok/s** |

**Key findings:**
1. **ROCm crushes Vulkan on prompt eval (8–13× faster):** Both hit ~29 tok/s decode (memory-bandwidth bound at 512 GB/s), but ROCm hits **2,110 tok/s prompt eval** vs **159–252 tok/s on Vulkan**. For long-article / transcript / meta-analysis prompts, **always use ROCm/HIP on the RX 6800 XT**, not Vulkan.
2. **27B GDN fits at full 64k context on 16 GB VRAM** (`11.56 GiB` used, leaving 4.4 GiB headroom) and runs ice-cold (**57°C / 58°C**).

---

## 3. Model Audit ("Are We Using Anything Outdated?")

- **`granite4.1:8b` on `ubuntu-server` (RX 6800 XT):** **Not outdated** — it's a fast, reliable 8B workhorse (11.5k tok/s prompt eval, 42.6 tok/s decode, 10.45 GB VRAM @ 24k ctx). Keep it for high-volume background jobs (social sentiment, bulk article summarization). *Minor weakness:* occasionally simplifies nuance (e.g., collapsed a `"$168M-$174M"` guidance range to `174`).
- **`qwen3.5:9b-q8_0` on `ts-msi-laptop` (RTX 3080 Laptop 16 GB):** **Solid, but leaves performance & intelligence on the table:**
  - Running `Q8_0` burns **9.73 GB** of bandwidth per token on a 448 GB/s card (~42 tok/s). A `Q4_K_M` / `IQ4_XS` 9B runs ~1.5× faster with negligible quality drop.
  - Better yet: **`unsloth/Qwen3.8-27B-GGUF`** (`Qwen3.8-27B-UD-IQ3_S.gguf` = **11.21 GB** + `MTP/mtp-Qwen3.8-27B-Q4_0.gguf` = **1.28 GB**, total **12.49 GB**) now fits **100% in 16 GB VRAM** thanks to **PR #31669** + **`q4_0` KV cache**. With `--spec-type draft-mtp --spec-draft-n-max 2` (or hybrid `draft-mtp,ngram-simple`), you get flagship **27B reasoning/extraction quality at ~45–55 tok/s** on a 16 GB card.
- **When the RTX 3090 (24 GB, 936 GB/s) returns:** Run `Qwen3.8-27B-UD-Q4_K_M` (15.43 GB) + `mtp-Qwen3.8-27B-Q4_0` (1.28 GB) + `q4_0`/`q8_0` KV + `--spec-type draft-mtp,ngram-simple` at 64k–128k ctx.

---

## 4. Recommended Software Stack Adaptations

1. **Immediate (already applied):**
   - Keep `OLLAMA_KV_CACHE_TYPE=q8_0` (and `OLLAMA_FLASH_ATTENTION=1`) on both `ubuntu-server` and `ts-msi-laptop`.
   - Keep Ollama synced to `v0.40.18+` across all hosts.
2. **Next step for `llama-server` (`b12680`+) integration:**
   - `web_dashboard/glm_transport.py` already supports OpenAI-compatible `/v1/chat/completions` via `GLM_LOCAL_FALLBACK_BASE_URL`.
   - When ready to switch `ts-msi-laptop` (or the 3090) from Ollama to standalone `llama-server` `b12680` for **MTP + tuned n-gram + system-RAM prefix caching (`-cram 8192`)**, launch with:
     ```powershell
     C:\opt\llama.cpp.b12680\llama-server.exe `
       -m C:\opt\models\qwen3.8-27b\Qwen3.8-27B-UD-IQ3_S.gguf `
       -md C:\opt\models\qwen3.8-27b\mtp-Qwen3.8-27B-Q4_0.gguf `
       --spec-type draft-mtp `
       --spec-draft-n-max 3 `
       -c 32768 -np 1 -ngl 99 -fa on -ctk q4_0 -ctv q4_0 -cram 8192 `
       --host 0.0.0.0 --port 11435 --no-webui
     ```
   - On `ubuntu-server` (RX 6800 XT), if deploying standalone `llama-server`, **compile/run with HIP/ROCm** (not Vulkan) to preserve the **2,110+ tok/s** prompt eval speed.
