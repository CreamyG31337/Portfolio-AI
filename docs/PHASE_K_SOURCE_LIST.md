# Phase K — YouTube Source List (seed data + validation plan)

Companion to [`PHASE_K_SOURCES_UI_PLAN.md`](PHASE_K_SOURCES_UI_PLAN.md), which specs the
`/admin/sources` page and the `youtube_sources` schema. **That** doc says how to store
sources; **this** doc says which sources, and how we find out whether any of it is worth
running.

Seed payload in §6 is shaped for the `bulk-preview` / `bulk-commit` contract in
`PHASE_K_SOURCES_UI_PLAN.md` §5.2.

---

## 1. Provenance and verification status

Two research passes (Grok and Gemini) produced ranked channel lists. Every factual claim
in them that could be checked mechanically **was** checked, on **2026-07-28**, using
`listing client` 2026.07.04 against public channel metadata (read-only).

The probe scripts are throwaway and were not committed; they did three things:
resolve each handle to a `channel_id`, read the `/videos` and `/streams` tabs for duration
distribution, and read one recent video per channel for its subtitle tracks.

**The verification changed the list materially.** Three handles were wrong, the
live-stream figures in both reports were wrong, and several caption-status claims were
wrong. Details in §2. The lesson worth carrying: treat LLM-supplied handles, cadence,
and caption status as unverified leads, never as seed data.

### What is still unverified

- **Cadence.** `extract_flat` does not return upload timestamps, so uploads/week was not
  measured. Both reports' cadence numbers are retained nowhere in this doc — the field is
  left empty in the seed payload rather than filled with a guess.
- **Ticker associations.** The `expected_tickers` values are model assertions. They are
  seeded as a starting hint only, and §7 Stage 0 replaces them with measured values.
- **Track records.** Grok marked nearly all of its own as `UNVERIFIED`. Gemini supplied
  five dated, falsifiable claims — better, but at least one is inflated (crediting High
  Yield with predicting Intel Foundry's structural separation, which Intel itself
  announced in Feb 2024). These are **not** used to set `confidence_weight`; see §8.

---

## 2. Corrections to the research output

| Claim | Source | Reality (measured 2026-07-28) |
|---|---|---|
| H​i​g​h​ ​Y​i​e​l​d is `@​H​i​g​h​Y​i​e​l​d​Y​T` | Gemini | **404.** Correct handle is `@​H​i​g​h​Y​i​e​l​d` (`UCmMwHbw2j8LfvTKVh3O7Vdw`). Grok had this right. |
| G​e​e​k​e​r​w​a​n EN is `@geekerwan_eng` | Gemini | **404.** Two real channels exist — see below. |
| der8auer is German-only, poor fit | Grok | **Half right.** `@​d​e​r​8​a​u​e​r` is indeed German. But an English channel exists: **`@​d​e​r​8​a​u​e​r​-​e​n`** (`UCGsaijjOJshS2_ZmMNZgS-g`, 264k). Grok's exclusion was right about the handle it checked, wrong as a conclusion. |
| B​u​i​l​d​z​o​i​d live share: 0%, "records live-to-tape" | Gemini | **Wrong.** `/streams` tab has 30+ entries, median **191 min**. |
| B​u​i​l​d​z​o​i​d live share: high | Grok | **Right**, and the operationally important call. |
| HWU live share ~0%, "podcasts on a secondary channel" | Gemini | **Wrong.** 16 streams on the main channel, median 164 min. |
| HWU captions "manual and auto" | Gemini | **Wrong.** Auto-only, no manual English track. |
| ASUS trades as `ASY` | Gemini | **Not a real ticker.** ASUSTeK is 2357.TW; ADR is ASUUY. Gigabyte TPE:2376 is real but Taiwan-listed. Neither is realistically tradeable here — dropped. |

### The two G​e​e​k​e​r​w​a​n channels

| Handle | Channel ID | Subs | Last upload | Captions |
|---|---|---|---|---|
| `@G​e​e​k​e​r​w​a​n` | `UCNi3K9HUzuTmILZH0iGupkw` | 283k | **2025-05-07** — stale | manual `en` |
| `@​g​e​e​k​e​r​w​a​n​1​0​2​4` (极客湾G​e​e​k​e​r​w​a​n) | `UCeUJO1H3TEXu2syfAAPjYKQ` | 624k | 2026-07-25 — active | manual `en-US`, **no auto** |

Gemini's cited A17 Pro track record sits on the *stale* channel. The active one is
`@​g​e​e​k​e​r​w​a​n​1​0​2​4`, and it is the one to ingest.

---

## 3. Which alpha mechanism this corpus actually supports

Two mechanisms get bundled together under "analyse YouTube captions", and they are not
the same thing:

- **Attention alpha** — the video *is* the catalyst. Requires low float and a retail
  audience. This was the founding thesis ("G​a​m​e​r​s​ ​N​e​x​u​s has enough subscribers to move a
  stock price").
- **Information alpha** — the video contains a material fact that is not yet priced. The
  video does **not** need to move the stock; it needs to *predict* the move.

### The measurement

Recent video titles from all 12 allowlist channels were scanned for company names
(2026-07-28, 60 titles each, 720 total, 313 company mentions). Titles understate coverage,
so these are lower bounds — but the distribution is unambiguous:

| Cap bucket | Mentions | Share |
|---|---|---|
| Large + mega (NVDA, AMD, INTC, AAPL, QCOM, MU, TSM, ASML, AVGO) | 302 | **96.5%** |
| Mid (SMCI) | 3 | 1.0% |
| Small (CRSR) | 3 | 1.0% |
| Recent IPO (CBRS) | 1 | 0.3% |
| Private (Tenstorrent, Ampere, SiFive…) | 4 | 1.3% |

**Attention alpha is not available from this corpus, and no amount of source curation
fixes it.** These channels talk about NVDA and AMD, which a video cannot move. They almost
never discuss companies small enough for attention to matter, and the ones they do
(Corsair, Supermicro) appear ~3 times in 60 videos — too thin to build on.

Chasing attention alpha would mean abandoning this corpus for micro-cap coverage, which is
dominated by paid stock promotion. That is a worse problem than the one it solves.

### Conclusion: build for information alpha, on liquid names

This is not a downgrade. For information alpha, large caps are **better**: tight spreads,
tradeable at size, no promotion industry, and a supply chain the allowlist channels track
closely. The bar is different, not higher-risk — the extracted claim must be genuinely
non-consensus and material, which is exactly what §7 Stage 0 measures.

Real examples pulled from the scanned titles, all information-alpha shaped:

- *"The DRAM Crisis: 600% Price Increases by Micron, SK Hynix & Samsung"* (G​a​m​e​r​s​ ​N​e​x​u​s) —
  hardware channels track DRAM/NAND retail pricing continuously because it sets RAM prices.
  Memory pricing is the dominant driver of MU earnings. This is a consumer-observable
  leading indicator of an income statement.
- *"The Billion Dollar Decoy GPU Smuggling Scheme | Supermicro"* (G​a​m​e​r​s​ ​N​e​x​u​s) — SMCI,
  export-control exposure.
- *"The $1 Trillion+ Bet Against ASML: Substrate"* (T​e​c​h​T​e​c​h​P​o​t​a​t​o) — competitive threat to
  a core holding.

The DRAM/pricing category is the most promising single thread here and is worth treating as
a first-class extraction target in K2, not as an afterthought.

### On the micro-cap orientation elsewhere in the repo

`web_dashboard/skills/microcap_red_flags.md` and cap-aware benchmarking in
[`benchmarks.py:76-96`](../web_dashboard/benchmarks.py#L76-L96) still apply to other
signals. Phase K simply is not a micro-cap source, and should not be bent into one.
Micro-cap attention signal, if wanted later, belongs with
[`jobs_reddit_discovery.py`](../web_dashboard/scheduler/jobs_reddit_discovery.py).

**Spam risk is near zero by construction**: `youtube_sources` is an allowlist, not an open
crawl. Low-quality content can only enter if someone adds it deliberately, and the §8
derived-content filter is a second line of defence.

---

## 4. The stream problem (biggest operational finding)

Every high-value channel publishes long-form live content that the `/videos` tab hides:

| Channel | Streams found | Median stream length |
|---|---|---|
| A​c​t​u​a​l​l​y​ ​H​a​r​d​c​o​r​e​ ​O​v​e​r​c​l​o​c​k​i​n​g | 30+ | **191 min** |
| G​a​m​e​r​s​ ​N​e​x​u​s | 30+ | **188 min** |
| T​e​c​h​T​e​c​h​P​o​t​a​t​o | 30+ | 166 min |
| H​a​r​d​w​a​r​e​ ​U​n​b​o​x​e​d | 16 | 164 min |
| L​e​v​e​l​1​T​e​c​h​s | 30+ | 132 min |
| M​o​o​r​e​'​s​ ​L​a​w​ ​I​s​ ​D​e​a​d | 30+ | 103 min |

M​o​o​r​e​'​s​ ​L​a​w​ ​I​s​ ​D​e​a​d is the extreme case: even its `/videos` tab has a **median of 94
minutes**, with 50% of uploads over an hour.

A 3-hour stream is roughly 27,000 words of caption text — order 36k tokens — at very low
signal density (rambling, tangents, audience Q&A). Ingesting streams indiscriminately is
the single fastest way to make Phase K cost more than it returns.

**Guardrails this implies for the K3 ingest job:**

1. Pull from the `/videos` tab, **not** the channel root — the root mixes in streams.
2. Enforce a `max_duration_s` per source (suggest 3600 default), stored on
   `youtube_sources` so M​L​I​D can be given a higher ceiling deliberately rather than by
   accident.
3. Enforce a `min_duration_s` (suggest 120) to drop Shorts, which carry no analysis.
4. Treat streams as a **separately enabled** ingest, off by default. B​u​i​l​d​z​o​i​d's streams
   genuinely contain signal Grok was right to flag — but that is a deliberate,
   cost-accepted decision, not a default.

---

## 5. Verified seed allowlist

Tier 1 = named independently by both research passes, or already chosen by us. Tier 2 =
single-source but performs genuine primary measurement. All handles and channel IDs below
are **measured**, not reported.

| # | Channel | Handle | Channel ID | Subs | Median len | Mechanism | Tier |
|---|---|---|---|---|---|---|---|
| 1 | G​a​m​e​r​s​ ​N​e​x​u​s | `@​G​a​m​e​r​s​N​e​x​u​s` | `UChIs72whgZI9w6d6FhwGGHA` | 2.63M | 28.5m | TEARDOWN + MARKET_MOVER | 1 |
| 2 | M​o​o​r​e​'​s​ ​L​a​w​ ​I​s​ ​D​e​a​d | `@​M​o​o​r​e​s​L​a​w​I​s​D​e​a​d` | `UCRPdsCVuH53rcbTcEkuY4uQ` | 237k | 93.8m ⚠ | LEAK | 1 |
| 3 | H​a​r​d​w​a​r​e​ ​U​n​b​o​x​e​d | `@​H​a​r​d​w​a​r​e​u​n​b​o​x​e​d` | `UCI8iQa1hv7oV_Z8D35vVuSg` | 1.17M | 25.5m | TEARDOWN | 1 |
| 4 | A​c​t​u​a​l​l​y​ ​H​a​r​d​c​o​r​e​ ​O​v​e​r​c​l​o​c​k​i​n​g | `@​A​c​t​u​a​l​l​y​H​a​r​d​c​o​r​e​O​v​e​r​c​l​o​c​k​i​n​g` | `UCrwObTfqv8u1KO7Fgk-FXHQ` | 196k | 27.0m | TEARDOWN | 1 |
| 5 | H​i​g​h​ ​Y​i​e​l​d | `@​H​i​g​h​Y​i​e​l​d` | `UCmMwHbw2j8LfvTKVh3O7Vdw` | 121k | 17.7m | ANALYSIS | 1 |
| 6 | G​e​e​k​e​r​w​a​n | `@​g​e​e​k​e​r​w​a​n​1​0​2​4` | `UCeUJO1H3TEXu2syfAAPjYKQ` | 624k | 25.7m | TEARDOWN | 2 |
| 7 | A​s​i​a​n​o​m​e​t​r​y | `@A​s​i​a​n​o​m​e​t​r​y` | `UC1LpsuAUaKoMzzJSEt5WImw` | 951k | 26.4m | ANALYSIS | 2 |
| 8 | T​e​c​h​T​e​c​h​P​o​t​a​t​o | `@T​e​c​h​T​e​c​h​P​o​t​a​t​o` | `UC1r0DG-KEPyqOeW6o79PByw` | 145k | 30.7m | ANALYSIS | 2 |
| 9 | S​e​r​v​e​T​h​e​H​o​m​e | `@​S​e​r​v​e​T​h​e​H​o​m​e​V​i​d​e​o` | `UCv6J_jJa8GJqFwQNgNrMuww` | 1.04M | 19.0m | TEARDOWN | 2 |
| 10 | L​e​v​e​l​1​T​e​c​h​s | `@L​e​v​e​l​1​T​e​c​h​s` | `UC4w1YQAJMWOz4qtxinq55LQ` | 533k | 20.9m | TEARDOWN | 2 |
| 11 | T​h​e​ ​S​i​g​n​a​l​ ​P​a​t​h | `@​T​h​e​S​i​g​n​a​l​P​a​t​h` | `UCKxRARSpahF1Mt-2vbPug-g` | 142k | 32.1m | TEARDOWN | 2 |
| 12 | d​e​r​8​a​u​e​r​ ​E​N | `@​d​e​r​8​a​u​e​r​-​e​n` | `UCGsaijjOJshS2_ZmMNZgS-g` | 264k | 15.9m | TEARDOWN | 2 |
| 13 | P​a​l​a​n​t​i​r​ ​I​R | `@​P​a​l​a​n​t​i​r​T​e​c​h` | `UCwed6_f0WcDIioXvMQfcP2Q` | 157k | 12.1m | EARNINGS_IR | 2 |

⚠ M​L​I​D needs an explicit `max_duration_s` override or half its catalogue is rejected.

### Caption tracks (measured)

Auto-only English, no manual track: G​a​m​e​r​s​ ​N​e​x​u​s, M​L​I​D, H​a​r​d​w​a​r​e​ ​U​n​b​o​x​e​d, B​u​i​l​d​z​o​i​d,
T​h​e​ ​S​i​g​n​a​l​ ​P​a​t​h, S​e​r​v​e​T​h​e​H​o​m​e, L​e​v​e​l​1​T​e​c​h​s, T​e​c​h​T​e​c​h​P​o​t​a​t​o, d​e​r​8​a​u​e​r​ ​E​N.
Manual `en`: H​i​g​h​ ​Y​i​e​l​d, A​s​i​a​n​o​m​e​t​r​y.
Manual `en-US` **and no auto-English at all**: `@​g​e​e​k​e​r​w​a​n​1​0​2​4`.

> **`en-US` risk: tested, not a problem.** `yt_captions.py` requests `["en"]`, and
> `@​g​e​e​k​e​r​w​a​n​1​0​2​4` publishes `en-US` with no auto-English track — a plausible
> silent-empty-source failure. Fetched live on 2026-07-28: it returns
> `language='en-US'`, `caption_kind='manual'`, 36,450 chars. The library prefix-matches.
> No change needed.

### End-to-end verification (2026-07-28)

`fetch_caption_text` was run against the newest video on 9 of the 13 sources — **9/9
succeeded**, all via the caption provider with no listing-client fallback, ~1.2s each.

| Channel | Lang | Kind | Chars |
|---|---|---|---|
| G​a​m​e​r​s​ ​N​e​x​u​s | en | auto | 31,444 |
| M​o​o​r​e​'​s​ ​L​a​w​ ​I​s​ ​D​e​a​d | en | auto | **101,573** |
| H​a​r​d​w​a​r​e​ ​U​n​b​o​x​e​d | en | auto | 36,881 |
| B​u​i​l​d​z​o​i​d | en | auto | 18,383 |
| H​i​g​h​ ​Y​i​e​l​d | en | manual | 5,515 |
| G​e​e​k​e​r​w​a​n | en-US | manual | 36,450 |
| A​s​i​a​n​o​m​e​t​r​y | en | manual | 16,741 |
| T​e​c​h​T​e​c​h​P​o​t​a​t​o | en | auto | 20,804 |
| d​e​r​8​a​u​e​r​ ​E​N | en | auto | 20,013 |

K1 is confirmed working against production sources, not just mocks.

**Cost calibration:** one M​L​I​D video is ~101k chars ≈ **25k tokens**, roughly 5× the median
of the rest. §4's duration caps are not theoretical — M​L​I​D alone can dominate the Phase K
token budget. Typical non-M​L​I​D video is 20-37k chars ≈ 5-9k tokens.

**Thesis check.** The nine videos pulled at random (newest per channel) included: *"GPU
Prices To Rise By Another 40%?!?!?!"* (HWU), *"Intel Nova Lake Delay Leak"* (M​L​I​D), *"True
3D DRAM"* (A​s​i​a​n​o​m​e​t​r​y), and *"The BIOS Company Is Getting Acquired"* (T​e​c​h​T​e​c​h​P​o​t​a​t​o —
AMI, an M&A event). Four of nine carried a pricing, delay, or corporate-action claim on a
single unfiltered sample. That is a genuinely encouraging prior for §7 Stage 0 — and it
independently reinforces §3's finding that component pricing is the strongest thread.

### Deliberately excluded

| Channel | Why |
|---|---|
| Anastasi In Tech | Grok concedes it is *"concurrent or after primary announcements"* — downstream by definition, which is negative alpha under our own criterion. |
| Jeff Geerling | Good channel, weak ticker linkage (mostly Pi/homelab). |
| iFixit | Sells repair parts — a real financial incentive to amplify repairability controversy. Repairability also rarely maps to a trade. |
| MKBHD, LTT | Attention-only, on mega-caps. No working mechanism (§3). |
| `@G​e​e​k​e​r​w​a​n` | Stale since 2025-05. Superseded by `@​g​e​e​k​e​r​w​a​n​1​0​2​4`. |
| `@​d​e​r​8​a​u​e​r` | German-language. Use `@​d​e​r​8​a​u​e​r​-​e​n`. |

---

## 6. Bulk-import payload

Matches `PHASE_K_SOURCES_UI_PLAN.md` §5.2. `channel_id` is pre-resolved, so
`bulk-preview` should report zero `warnings` about unresolved channels and dedupe cleanly
on re-paste. `cadence` is intentionally absent — unmeasured (§1).

```json
[
  {"label": "G​a​m​e​r​s​ ​N​e​x​u​s",                   "handle": "@​G​a​m​e​r​s​N​e​x​u​s",                  "channel_id": "UChIs72whgZI9w6d6FhwGGHA", "kind": "channel", "alpha_mechanism": "TEARDOWN",  "expected_tickers": ["NVDA","AMD","INTC"],        "max_duration_s": 3600, "enabled": true},
  {"label": "M​o​o​r​e​'​s​ ​L​a​w​ ​I​s​ ​D​e​a​d",            "handle": "@​M​o​o​r​e​s​L​a​w​I​s​D​e​a​d",              "channel_id": "UCRPdsCVuH53rcbTcEkuY4uQ", "kind": "channel", "alpha_mechanism": "LEAK",      "expected_tickers": ["NVDA","AMD","INTC"],        "max_duration_s": 9000, "enabled": true, "notes": "median 94min; long-form podcast format"},
  {"label": "H​a​r​d​w​a​r​e​ ​U​n​b​o​x​e​d",               "handle": "@​H​a​r​d​w​a​r​e​u​n​b​o​x​e​d",              "channel_id": "UCI8iQa1hv7oV_Z8D35vVuSg", "kind": "channel", "alpha_mechanism": "TEARDOWN",  "expected_tickers": ["NVDA","AMD","INTC"],        "max_duration_s": 3600, "enabled": true},
  {"label": "A​c​t​u​a​l​l​y​ ​H​a​r​d​c​o​r​e​ ​O​v​e​r​c​l​o​c​k​i​n​g", "handle": "@​A​c​t​u​a​l​l​y​H​a​r​d​c​o​r​e​O​v​e​r​c​l​o​c​k​i​n​g", "channel_id": "UCrwObTfqv8u1KO7Fgk-FXHQ", "kind": "channel", "alpha_mechanism": "TEARDOWN",  "expected_tickers": ["NVDA","AMD","INTC"],        "max_duration_s": 3600, "enabled": true, "notes": "streams median 191min - keep streams disabled"},
  {"label": "H​i​g​h​ ​Y​i​e​l​d",                     "handle": "@​H​i​g​h​Y​i​e​l​d",                    "channel_id": "UCmMwHbw2j8LfvTKVh3O7Vdw", "kind": "channel", "alpha_mechanism": "ANALYSIS",  "expected_tickers": ["ASML","TSM","INTC","AMAT"], "max_duration_s": 3600, "enabled": true},
  {"label": "G​e​e​k​e​r​w​a​n",                      "handle": "@​g​e​e​k​e​r​w​a​n​1​0​2​4",                "channel_id": "UCeUJO1H3TEXu2syfAAPjYKQ", "kind": "channel", "alpha_mechanism": "TEARDOWN",  "expected_tickers": ["AAPL","QCOM","NVDA"],       "max_duration_s": 3600, "enabled": true, "notes": "manual en-US only, NO auto-en"},
  {"label": "A​s​i​a​n​o​m​e​t​r​y",                    "handle": "@A​s​i​a​n​o​m​e​t​r​y",                  "channel_id": "UC1LpsuAUaKoMzzJSEt5WImw", "kind": "channel", "alpha_mechanism": "ANALYSIS",  "expected_tickers": ["TSM","ASML","INTC"],        "max_duration_s": 3600, "enabled": true},
  {"label": "T​e​c​h​T​e​c​h​P​o​t​a​t​o",                 "handle": "@T​e​c​h​T​e​c​h​P​o​t​a​t​o",               "channel_id": "UC1r0DG-KEPyqOeW6o79PByw", "kind": "channel", "alpha_mechanism": "ANALYSIS",  "expected_tickers": ["INTC","AMD","NVDA"],        "max_duration_s": 3600, "enabled": true},
  {"label": "S​e​r​v​e​T​h​e​H​o​m​e",                   "handle": "@​S​e​r​v​e​T​h​e​H​o​m​e​V​i​d​e​o",            "channel_id": "UCv6J_jJa8GJqFwQNgNrMuww", "kind": "channel", "alpha_mechanism": "TEARDOWN",  "expected_tickers": ["SMCI","NVDA","AMD","ARM"],  "max_duration_s": 3600, "enabled": true},
  {"label": "L​e​v​e​l​1​T​e​c​h​s",                    "handle": "@L​e​v​e​l​1​T​e​c​h​s",                  "channel_id": "UC4w1YQAJMWOz4qtxinq55LQ", "kind": "channel", "alpha_mechanism": "TEARDOWN",  "expected_tickers": ["AMD","INTC","NVDA"],        "max_duration_s": 3600, "enabled": true},
  {"label": "T​h​e​ ​S​i​g​n​a​l​ ​P​a​t​h",                "handle": "@​T​h​e​S​i​g​n​a​l​P​a​t​h",                "channel_id": "UCKxRARSpahF1Mt-2vbPug-g", "kind": "channel", "alpha_mechanism": "TEARDOWN",  "expected_tickers": ["ADI","TXN","QCOM"],         "max_duration_s": 5400, "enabled": true, "notes": "low cadence, high per-item value"},
  {"label": "d​e​r​8​a​u​e​r​ ​E​N",                    "handle": "@​d​e​r​8​a​u​e​r​-​e​n",                  "channel_id": "UCGsaijjOJshS2_ZmMNZgS-g", "kind": "channel", "alpha_mechanism": "TEARDOWN",  "expected_tickers": ["NVDA","AMD","INTC"],        "max_duration_s": 3600, "enabled": true},
  {"label": "P​a​l​a​n​t​i​r​ ​I​R",                    "handle": "@​P​a​l​a​n​t​i​r​T​e​c​h",                 "channel_id": "UCwed6_f0WcDIioXvMQfcP2Q", "kind": "channel", "alpha_mechanism": "EARNINGS_IR","expected_tickers": ["PLTR"],                     "max_duration_s": 9000, "enabled": true, "notes": "only major issuer posting full earnings calls to YouTube"}
]
```

`alpha_mechanism` values used are exactly the vocabulary already defined in
`PHASE_K_SOURCES_UI_PLAN.md` §4.1: `TEARDOWN`, `LEAK`, `ANALYSIS`, `MARKET_MOVER`,
`EARNINGS_IR`. No schema change needed.

---

## 7. Does this have any value? A staged test

Ordered by information gained per hour spent. Stop early if a stage fails.

### Stage 0 — extraction yield (no price data, no market exposure)

For each of the 13 sources, pull the last ~50 videos, fetch captions, run extraction, and
measure **the fraction of videos producing a ticker-specific, falsifiable, material
claim.**

This needs no price history and risks no money. If a channel yields under ~10%, it costs
more than it returns *regardless of how accurate the other 10% is* — so this kills weak
sources for free. It also produces the measured `expected_tickers` that replace §5's
guesses, and exercises the whole K1→K2 path, so none of it is throwaway work.

Deliverable: a per-source yield table. Expected outcome — teardown channels beat analysis
channels, and M​L​I​D has high yield per video but high token cost per video.

### Stage 1 — event study on the five dated claims

Gemini supplied five dated, falsifiable events (HWU/Nvidia FE sample ban Dec 2020;
G​e​e​k​e​r​w​a​n A17 Pro Sept 2023; B​u​i​l​d​z​o​i​d 7800X3D burnout Apr 2023; iFixit iPhone 13 Face ID
Nov 2021; H​i​g​h​ ​Y​i​e​l​d Intel 18A Feb 2024). Measure abnormal return on the affected ticker
in the days after each.

[`scripts/insider_event_study.py`](../web_dashboard/scripts/insider_event_study.py) and
[`benchmarks.py`](../web_dashboard/benchmarks.py) already do cap-aware abnormal-return
measurement, so this is mostly wiring, not building.

n=5 proves nothing statistically — but it gives the **magnitude**, which is the decisive
number. If the most notorious tech-YouTube events in five years moved their tickers by
approximately nothing, the mega-cap information-alpha thesis is dead and §3's attention
mechanism becomes the only live option. **Highest information per hour in this document.**

### Stage 2 — retrospective backtest

Captions are retroactively available and the listing client exposes upload dates, so a year of history
can be replayed without waiting.

> **The trap: lookahead bias.** The LLM already knows how 2024–2025 resolved. A naive
> replay will produce spectacular, meaningless results, and will do so *convincingly*.
> Mitigate by restricting to videos published after the model's training cutoff, and/or
> stripping dates and identifying context from the prompt. Treat any backtest Sharpe
> produced without one of those controls as evidence of nothing.

### Stage 3 — forward paper trading

The only clean evidence. Slowest. Route through the existing stance-outcome machinery
([`jobs_stance_outcomes.py`](../web_dashboard/scheduler/jobs_stance_outcomes.py)) so
results are measured the same way as every other signal in the system.

---

## 8. Weighting, blocklists, and filters

**`confidence_weight` starts uniform.** No research pass produced defensible per-source
credibility — Grok declined to, and Gemini's dated claims are too few and partly inflated.
Seeding the rankings above into weights would encode two models' opinions as if they were
measurements. Weights get set from Stage 0 yield and Stage 1/3 outcomes.

**Static blocklists are near-worthless here.** The two research passes produced blocklists
with **zero overlap** (Grok: AdoredTV, GamerMeld, Unbox Therapy, TTS scrape channels.
Gemini: TechLinked, YongYea, ReviewTechUSA, wccftechTV, ColdFusion). That disagreement is
itself the finding: these are cheap opinion, not knowledge.

**The derived-content filter is worth more than both blocklists.** Gemini's generalization
is implementable and channel-agnostic — score each transcript on:

- attribution phrases: *"according to an article by"*, *"if we look at this tweet"*,
  *"a report from"*, *"sources say"*
- ratio of technical terms (`die size`, `cache`, `VRM`, `yield`, `node`, `TDP`) to opinion
  words (`crazy`, `insane`, `destroy`, `finished`)

A channel that reads other people's reporting is a lagging indicator no matter how large
it is. This filter catches that at the *content* level, including for channels nobody
thought to blocklist — and it generalizes to sources added later. Recommend implementing
it in K2 as a per-article score, not as a source-level flag.

Since it is measurable, note that it also gives a cheap sanity check on the whole
list: run it across Stage 0's corpus and confirm the Tier 1 channels really do score as
primary sources. If G​a​m​e​r​s​ ​N​e​x​u​s scores as derived, the heuristic is wrong — and that is
worth knowing before it gates anything.

---

## 9. Open questions

1. ~~Which mechanism is Phase K testing?~~ **Resolved 2026-07-28 by measurement** — 96.5%
   of company mentions across the allowlist are large/mega-cap, so attention alpha is not
   available from this corpus at any source-curation effort. Phase K is an
   **information-alpha** system on liquid names. See §3. The remaining question is narrower
   and empirical: *does extraction yield (Stage 0) clear the bar to be worth running?*
2. **Search-kind sources.** Both passes supplied query templates. The listing client's
   curated search mode handles them, but search results are far noisier than channel feeds.
   Recommend search be used for **discovering candidate channels for human review**, not
   for direct ingestion into `research_articles`.
3. **Streams.** Enable per-source later, with cost measured, once Stage 0 shows whether
   B​u​i​l​d​z​o​i​d's VOD yield alone justifies the channel.
4. `confidence_weight` representation — numeric or bucketed words in the LLM prompt.
   Deferred to K4, unchanged from `PHASE_K_SOURCES_UI_PLAN.md` §10.

---

## 10. Sector expansion: space/aerospace — evaluated and rejected (2026-07-28)

Both Gemini and Grok were given the §1 prompt from
[`PHASE_K_SOURCE_RESEARCH_PROMPT.md`](PHASE_K_SOURCE_RESEARCH_PROMPT.md) and asked for
space channels. All handles resolved, and all were then title-scanned for tradeable
tickers exactly as in §3.

**Verdict: do not add space sources.** Not because the channels are low quality — several
are outstanding — but because of a structural mismatch that curation cannot fix.

### The finding: observation quality and tradeability are inversely correlated

| Channel | Subs | VOD median | Streams | Stream median | **Tradeable share of company mentions** |
|---|---|---|---|---|---|
| NASASpaceflight | 1.51M | 17.8m | 30+ | **212m** | **2%** |
| Everyday Astronaut | 1.98M | 22.9m | 30+ | 138m | **3%** |
| Scott Manley | 1.87M | 21.1m | 30+ | 105m | **3%** |
| CSI Starbase | 118k | 43.1m | 1 | 120m | **0%** |
| Nanalyze | 94.6k | 13.8m | 3 | 62m | 0%* |
| Dave G Investing | 23k | 19.6m | 30+ | 67m | **81%** |

\* Nanalyze registered only 2 company mentions in 60 titles — it is a general investing
channel, not a space channel. Title-scanning understates in-video coverage, so treat all
figures as lower bounds; the distribution is nonetheless unambiguous.

The four channels both models ranked highest are overwhelmingly about **SpaceX** — 45 of
NASASpaceflight's 60 recent titles, 43 of CSI Starbase's. SpaceX is private. The world's
best primary space observation is pointed at a company that cannot be traded.

The single channel with high tradeable coverage (Dave G Investing, RKLB in 40 of 60 titles)
is a retail portfolio channel that Grok itself classes as *"derived + personal… conflict by
design"* and that Gemini's blocklist criteria would reject outright. It is precisely the
category §8's derived-content filter exists to exclude.

So the sector fails on both mechanisms at once:

- **Information alpha** — excellent primary observation, aimed at an untradeable target.
  The residual "SpaceX execution affects RKLB competitively" chain is a second-order
  inference an LLM will happily assert with unearned confidence. Low reliability.
- **Attention alpha** — both models were asked directly and neither endorsed it. Gemini:
  *"I will be plain: it is wishful thinking… space stocks trade almost entirely on
  institutional milestone de-risking."* Grok: *"partially live… but weaker and more
  catalyst-dependent… secondary to INFORMATION signals."*

Compare tech, where coverage was mega-cap but at least **tradeable**. Space is a harder
corpus, not an easier one, and the hoped-for small-cap advantage does not survive contact
with the data.

### Stream load is also worse

NASASpaceflight's streams run a **212-minute median** — the heaviest of any channel
evaluated in either sector. Launch coverage is inherently live and multi-hour, so §4's
duration caps would be doing continuous heavy lifting for comparatively little return.

### What is worth keeping

Both models independently identified the same **non-YouTube** sources as superior for
space, which is the most valuable output of the exercise:

- **FAA TFRs** — reveal that a launch is genuinely scheduled, regardless of company PR
- **USCG Notices to Mariners** — booster landing zones, recovery ship movement
- **FCC OET experimental licenses** — testing timelines months in advance
- **SAM.gov** — DoD/NASA contract awards
- **space-track / nextspaceflight** — manifests and orbital parameters

Independent double-nomination, and all structured, parseable, and genuinely leading. If
space exposure is wanted later, **this is the ingestion path — not captions.** It belongs
in its own phase, not Phase K.

### Process note

The §1 prompt's honesty instructions worked. Gemini's `UNVERIFIED` on CSI Starbase and its
flat rejection of the attention premise both proved correct; Grok's `UNKNOWN` on live
splits was more accurate than Gemini's confident *"Scott Manley: almost exclusively VOD"*
(30 streams, 105-minute median). Explicit escape hatches produced better calibration than
the first round. Keep them.

---

## 11. Defect / recall as an extraction category (adopted, with a materiality caveat)

Hypothesis raised 2026-07-28: *a bad product or a recall moves the stock even on a mega
cap, and these channels are the primary discoverers of those events.* Measured against
1,200 recent titles (12 channels × 100).

**The mechanism is real and is hereby a first-class extraction category alongside
pricing.** It had been folded into general "information alpha", which undersold it — a
defect is the highest-severity, longest-running event type in this corpus, and hardware
YouTube genuinely breaks these stories rather than repeating them.

### Frequency

3.5% of titles (42/1200) contain defect/failure/legal language, but that number is
inflated by metaphor and non-product usage — *"AI Companies Are Setting Money on Fire"*,
*"The EU Chips Act is a Failure"*, *"YouTube Loses Lawsuit"*. Hand-filtering to genuine
product-liability events affecting a specific issuer leaves roughly **1% of videos, or
about one event per month across the whole corpus.**

Genuine examples in the sample:

- *"MSI's Insane 2500W RTX 5090 and Solution to Melting Power Cables"* (HWU) — the 12VHPWR
  connector failure, an issue that ran for months
- *"After Recall Rumors: ASUS Secretly Changed RTX 5090 Matrix Liquid Metal"* (der8auer)
- *"It's An Active Choice to Lie This Much | Micron's 'Commitment' to Gamers"* (GN) — **MU**
- *"HW News — DRAM Antitrust Lawsuit"* (GN) — MU / SK Hynix / Samsung
- *"AMD Gaslights Security Researcher, Changes Rules Retroactively"* (GN)
- *"Nvidia RMA Surge"* (M​L​I​D)

Low frequency is acceptable for an event-driven overlay — but it does mean defect signal
cannot carry Phase K alone. Pricing (§3) remains the high-frequency thread.

### The materiality caveat — this is the real limit

**A defect's stock impact scales with the affected product's share of revenue, not with
how bad the defect is.** This cuts directly against the mega-cap corpus:

- Samsung's Note 7 recall was material because flagship phones were a huge revenue line.
- NVDA's melting 12VHPWR connectors, by contrast, affect a halo product in a company whose
  earnings are driven by datacenter. Severe, viral, extensively covered — and close to
  immaterial to the P&L.
- Intel's Raptor Lake degradation (2024) is the strongest real precedent, because CPUs
  *are* Intel's consumer revenue. Even there, INTC's 2024 decline is badly confounded by
  foundry losses, so attribution is genuinely hard.

So the tradeable subset is narrower than the mechanism suggests: **defects in products that
constitute a large share of the issuer's revenue.** Micron/DRAM and Intel/CPUs qualify.
An Nvidia connector does not. This is a good Stage 1 test — it is falsifiable on history.

### On consumer electronics specifically (Sony, Samsung, LG)

The corpus does **not** support this, which was the specific hope. Consumer-brand mentions
across 1,200 titles:

| Brand | Mentions | Tradeable here? |
|---|---|---|
| MSI | 26 | 2377.TW — no |
| ASUS | 23 | 2357.TW — no |
| Apple | 22 | yes (AAPL) |
| Valve | 16 | private |
| Gigabyte | 14 | 2376.TW — no |
| **Sony** | **12** | yes (SONY) |
| **Samsung** | **4** | 005930.KS — no |
| **LG** | **0** | — |

The three most-covered consumer brands are all Taiwan-listed board partners, not the
Japanese/Korean majors. Sony appears 12 times in 1,200 titles and Samsung 4 (mostly as a
memory vendor, not a consumer one). **These are PC-component channels; they do not review
TVs, phones or appliances.** Getting Sony/Samsung consumer coverage would mean adding a
different corpus (MKBHD-tier reviewers) — already excluded in §5 as attention-only with
low teardown rigor, and §3 showed attention alpha is unavailable regardless.

### Cars

Entirely absent from this corpus — zero automotive coverage. Would require a separate
sector addition (Munro Live et al.). Not evaluated. Note that the authoritative recall data
for autos is **NHTSA filings**, which is structured and public — the same pattern found for
space in §10, where the regulatory source beats the video source.

### Implementation

1. Add `DEFECT_RECALL` as an extraction category in K2, distinct from pricing.
2. Have the extractor capture **the affected product line and an estimate of its revenue
   share**, not just the defect. Without that the materiality filter cannot be applied and
   every melting cable looks like a Note 7.
3. Micron is emerging as the single richest tradeable name in this corpus — it carries both
   the pricing thread (§3) and conduct/legal coverage. Worth watching as the Stage 0
   bellwether.

---

## 12. Sector expansion: automotive (ADOPT) and consumer electronics (reject)

Evaluated 2026-07-28 against the same bar as tech (§3) and space (§10): handle resolves,
primary measurement rather than news-rehash, and — the criterion that killed space — the
companies discussed must be **tradeable**.

### Automotive: the best-scoring sector tested so far

| Channel | Handle | Channel ID | Subs | VOD med | Streams | **Tradeable** | Top names |
|---|---|---|---|---|---|---|---|
| Munro Live | `@M​u​n​r​o​L​i​v​e` | `UCj--iMtToRO_cGG_fpmP5XQ` | 508k | 21.4m | 11@79m | **100%** | GM 10, RIVN 5, LCID 2 |
| Weber Auto | `@W​e​b​e​r​A​u​t​o` | `UCtr07mdKhsUwVJjL8Kw_q5A` | 476k | 33.9m | **0** | **100%** | TM 12, TSLA 11, GM 7, F 6 |
| Car Care Nut | `@TheCarCareNut` | `UCEKt2bUDBoRUw3wpPpDOUaA` | 1.79M | 32.1m | 30@77m | **100%** | TM 40 |
| Out of Spec | `@OutofSpecReviews` | `UCVRZKu68-4tQIk7_3CJ_wKA` | 321k | 40.9m | 3@60m | 88% | TSLA 15, RIVN 8 |
| TFLcar | `@tflcar` | `UC6S0jAvcapqJ48ZzLfva12g` | 1.58M | 15.6m | 2@43m | 75% | TM 14, STLA 12, GM 3 |
| Engineering Explained | `@EngineeringExplained` | `UClqhvGmHcvWL9w3R48t9QXQ` | 4.22M | 16.9m | **0** | 70% | TSLA 7, LCID 4, F 3 |

Captions verified end-to-end on all six — **6/6 succeeded**, English auto-captions,
13-38k chars. Sample titles confirm the content type: *"Five Generations of the Toyota
Prius High-Voltage Battery"* (Weber), *"Rivian R2 First Tow! Maxing Out Payload"*
(Out of Spec).

**Why automotive beats every sector tested, including tech:**

Autos are almost entirely US-listed and liquid — TSLA, F, GM, RIVN, LCID, STLA, plus TM
and HMC as ADRs. There is no Taiwan/Korea listing problem (§11) and no private-company
problem (§10). Tradeable share runs 70-100% versus space's 0-3%.

More importantly, this is **the first sector where the measurement maps directly onto the
valuation driver.** Munro Live does teardown *cost* analysis — bill-of-materials,
manufacturing cost, margin per vehicle. RIVN and LCID are mid-caps whose entire equity
thesis *is* gross margin per vehicle and the path to positive unit economics. A credible
independent BOM estimate is not adjacent to the thesis; it is the thesis. That is a
materially better fit than anything in tech, where §11's materiality caveat applies
(a defect in a mega-cap's minor product line is noise).

Secondary but genuinely novel: **Car Care Nut is a Toyota master technician**, so his
content is effectively field-failure data — which model years and components fail in
service. No equivalent primary source exists in any other sector reviewed. Weakness: 40/40
mentions are Toyota, a mega-cap ADR where materiality is low. Ingest for the mechanism, not
for near-term tradeability.

**Recommended tier 1:** Munro Live, Weber Auto, Out of Spec.
**Tier 2:** Engineering Explained, TFLcar, Car Care Nut.
Weber Auto and Engineering Explained have **zero streams** — the cleanest ingest targets
found in any sector. Car Care Nut (30 streams @ 77m) and savagegeese (18 @ 134m) need
`max_duration_s` caps.

Not adopted: savagegeese (67% tradeable, heavy EU-marque coverage, stream-heavy).

### Consumer electronics / displays: reject, same failure mode as space

| Channel | Tradeable | Why |
|---|---|---|
| HDTVTest | **26%** | Genuine display lab work — but LG 11, Samsung 10, TCL 5 are Korean/Chinese listings. Only Sony (9) is easily tradeable. |
| Dave2D | 62% | Apple/Samsung review content, attention-style, not primary measurement. |
| JerryRigEverything | 73% | Real durability testing, 10M subs — but AAPL 10 / Samsung 4. A bend test is immaterial to a $4T issuer (§11). |

HDTVTest is the sector's best primary measurer and scores worst on tradeability, because
the TV industry is Korean and Chinese. **This is the space failure mode exactly: quality of
measurement is inversely correlated with tradeability.** The user's Sony/Samsung intuition
was directionally right about where the *product* signal is — it just does not reach a US
brokerage.

Deferred, not rejected: **RTINGS** (`UCAi6GKtTPoYxUheIbVhnwqw`) does rigorous lab testing
and was not scanned (the `@rtings` handle 404s; real channel is "RTINGS Home Theater").
Same listing problem is likely.

### Another handle failure

`@iFixit` resolves to a **290-subscriber impostor** with 14 videos, not the real iFixit
(`UCHbx9IUW7eCeJsC4sBCTNBA`). Fourth wrong handle across three research rounds. §3 of the
research-prompt doc's verification checklist is not optional — and note this one would have
silently ingested a near-empty channel rather than erroring.

---

## 13. BLOCKER — YouTube IP-rate-limits bulk caption fetching (2026-07-28)

The first full Stage 0 run (15 sources × 10 videos) **failed as a measurement** and
instead surfaced the most consequential constraint in Phase K.

### What happened

Of 150 attempted videos, **137 returned `blocked`** and 1 `no_captions`. The only 12
successes were cache hits from earlier single-video probes — essentially **every live
fetch failed**. Elapsed 895s, so the batch was issuing roughly 10 fetches/minute.

The K1 module is not at fault. It worked perfectly at low volume (§5: 9/9 end-to-end,
~1.2s each) and correctly classified the failures with the `blocked` reason. This is
YouTube throttling the IP.

### Diagnosis

Probing the individual paths after the run:

| Path | Result |
|---|---|
| Caption provider track *list* | **works** — metadata listing is not blocked |
| Caption provider caption *fetch* | **blocked**, still failing 6 videos later at 6s spacing |
| Listing client metadata / subtitle *listing* | **works** |
| Listing client subtitle *download* | **HTTP 429 Too Many Requests** |

Two findings that matter for design:

1. **Listing is cheap, fetching is rate-limited.** Enumerating a channel and reading which
   caption tracks exist stayed available throughout. Only the caption body fetch is
   throttled. Discovery and health-checking can therefore run at volume; ingestion cannot.
2. **The listing-client fallback provides no redundancy against this.** Both paths egress from the
   same IP and both are 429'd together. The dual-path design in `yt_captions.py`
   protects against per-video quirks (disabled captions, age gates), **not** against rate
   limiting. This was an unstated assumption and it is now falsified.

The block is transient but long-lived — listing recovered within minutes while fetching was
still blocked more than 20 minutes after the batch ended.

### Consequences for K3

The nightly ingest job as specced cannot fetch tens of videos in a burst. Options, roughly
in order of cost:

- **Throttle hard and spread over time.** Implemented in the harness: `--delay` (default
  20s), exponential backoff, and abort after 5 consecutive blocks so a run degrades instead
  of deepening the block. A sustainable steady-state rate is **not yet known** — it must be
  measured from an unblocked IP, and 6s spacing was still failing *while already blocked*,
  so that datapoint proves nothing about the ceiling.
- **Cache aggressively and never re-fetch.** Already implemented (`.stage0_cache/`,
  gitignored). Captions are immutable, so a fetched transcript should be permanent —
  `research_articles` storage makes re-fetching unnecessary forever.
- **Proxy rotation.** Caption provider + listing client honor `YOUTUBE_PROXY_URL`; this is
  the practical answer when a single egress IP hits its daily fetch ceiling. Costs money /
  ops; adds a secret.
- **Accept a low ceiling.** With ~15 sources at a few videos each per day, a slow trickle
  may be entirely sufficient — Phase K does not need real-time ingestion, and §11 showed the
  interesting events are roughly monthly.

**Recommendation:** treat sustainable-rate discovery as a K3 prerequisite, not a detail.
The right next experiment is a low-volume soak test from an unblocked IP — one fetch every
30-60s for an hour — to find where the ceiling actually is before choosing to pay for
proxies.

### Status of the Stage 0 result

**Void.** The yield figures from this run (tech 44%, auto 67%) are computed over 9 and 3
videos respectively, all cache hits, all newest-per-channel — biased and far too small.
They are recorded here only to prevent them being mistaken for findings later. The 12
usable extractions did produce plausible claims (RIVN 5, AMD 4, SONY 3, NVDA 2, MU 1;
categories SUPPLY_CHAIN 4, PRODUCT_LAUNCH 4, PRICING 2), and the extractor correctly
returned zero claims for a teardown of a *private* Chinese robotics company — encouraging
for the prompt, but not a yield measurement.

Stage 0 must be re-run once the rate question is settled.

---

## 14. Stage 0 first real result + the quota finding (2026-07-28)

Re-run through the Gluetun proxy (`YOUTUBE_PROXY_URL`), `--delay 8`. Completed 11 of 15
sources — **108 videos with captions, 1 `no_captions`** — then hit the block again and
aborted cleanly. The 3 automotive sources and der8auer never ran.

### It is a per-IP quota, not a rate limit

This is the important operational correction to §13.

| | Direct (residential) | Proxy (NL datacenter) |
|---|---|---|
| Spacing | ~6s (≈10/min) | **8s (≈7.5/min)** |
| Live fetches before block | ~12 | **~90** |

Slowing down by 25% bought ~7× the volume, which is not what a rate limit looks like.
Roughly **90-110 caption fetches per IP** trips a multi-hour block regardless of pacing.
Treat it as a **daily quota per egress IP**, not something politeness alone solves.

Consequences for K3:

- Budget **~90 fetches/IP/day** and design the job to stop at its budget rather than
  discover the ceiling. `max_videos_per_poll` on `youtube_sources` is the right lever.
- 15 sources × 3-5 videos/day ≈ 45-75 fetches — **comfortably inside one IP's budget.**
  Phase K does not need more egress capacity in steady state; it needed it for backfill.
- Backfill is the expensive phase. Spread it over days, or rotate Gluetun's exit country
  between runs (a config change, not new infrastructure).
- **Never re-fetch.** Captions are immutable; `research_articles` should be the permanent
  store, exactly as the on-disk cache is for Stage 0.

### The yield result

First measurement worth quoting. Definition: a video counts if it produced ≥1 claim naming
a publicly traded ticker at non-LOW materiality.

| Source | Yield | Claims | Median kchars | Tech density |
|---|---|---|---|---|
| G​e​e​k​e​r​w​a​n | **44%** | 7 | 24.2 | 1.2 |
| M​o​o​r​e​'​s​ ​L​a​w​ ​I​s​ ​D​e​a​d | 40% | 10 | 101.6 | 0.1 |
| S​e​r​v​e​T​h​e​H​o​m​e | 40% | 7 | 24.8 | 0.7 |
| L​e​v​e​l​1​T​e​c​h​s | 40% | 7 | 21.0 | 0.6 |
| H​a​r​d​w​a​r​e​ ​U​n​b​o​x​e​d | 30% | 7 | 24.2 | 1.0 |
| T​e​c​h​T​e​c​h​P​o​t​a​t​o | 30% | 7 | 21.1 | 0.6 |
| G​a​m​e​r​s​ ​N​e​x​u​s | 20% | 8 | 30.9 | 0.6 |
| H​i​g​h​ ​Y​i​e​l​d | 20% | 5 | 16.7 | 3.8 |
| A​s​i​a​n​o​m​e​t​r​y | 10% | 2 | 21.7 | 1.8 |
| B​u​i​l​d​z​o​i​d | 10% | 1 | 25.6 | 2.6 |
| T​h​e​ ​S​i​g​n​a​l​ ​P​a​t​h | 11% | 1 | 27.7 | 4.2 |

**Tech overall: 27% (29/108 videos).** Comfortably above the ~10% viability floor set in §7,
so the corpus is not obviously worthless — the mechanism has something in it.

Tickers: AMD 20, INTC 10, NVDA 7, MU 6, AAPL 5, then a long tail.
Categories: COMPETITIVE 20, PRODUCT_LAUNCH 18, SUPPLY_CHAIN 10, DEMAND 9, MA_LEGAL 2,
**PRICING 1**.

### Three things this result does not say

1. **No auto comparison.** The run aborted before the automotive sources. The tech-vs-auto
   question from §12 is still open and is the single most useful follow-up.
2. **PRICING got 1 hit.** §3 called component pricing the most promising thread; this run
   contradicts that, and the disagreement matters. Most likely the extraction prompt buckets
   pricing claims as COMPETITIVE or SUPPLY_CHAIN rather than pricing genuinely being absent —
   the §5 sample had *"GPU Prices To Rise By Another 40%"* sitting right there. Needs a
   prompt fix and a re-run before §3's conclusion is either trusted or withdrawn.
3. **Yield ≠ alpha.** This counts claims the model judged material. Whether they *predict
   returns* is Stage 1/2 and is untouched. A 27% yield of worthless claims is still worthless.

### Signal-quality note

The two highest tech-density channels — T​h​e​ ​S​i​g​n​a​l​ ​P​a​t​h (4.2) and B​u​i​l​d​z​o​i​d (2.6) — have the
*lowest* yields (11%, 10%). Deep technical content is not the same as tradeable content, and
the density heuristic should not be used as a quality proxy for source selection. Note also
that the low-yield channels are largely the ones covering *untradeable* subjects
(oscilloscopes, VRM design), which is §10's inverse-correlation pattern showing up inside a
single sector.

### Harness fix

The abort discarded the in-flight source's partial results. `BlockedError` now carries them
and the report includes them, so an aborted run reports everything it actually did.
