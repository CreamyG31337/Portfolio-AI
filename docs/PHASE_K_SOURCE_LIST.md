# Phase K — YouTube Source List (seed data + validation plan)

Companion to [`PHASE_K_SOURCES_UI_PLAN.md`](PHASE_K_SOURCES_UI_PLAN.md), which specs the
`/admin/sources` page and the `youtube_sources` schema. **That** doc says how to store
sources; **this** doc says which sources, and how we find out whether any of it is worth
running.

Seed payload in §6 is shaped for the `bulk-preview` / `bulk-commit` contract in
`PHASE_K_SOURCES_UI_PLAN.md` §5.2.

> **Read §20 before §10-§19.** Sections 10-19 record five research rounds that rejected ten
> sectors. Every one of those is a rejection against the **event-alpha** bar — "does a single
> video contain an unpriced, ticker-specific, falsifiable claim?" **§20 re-scopes them**: the
> corpus is retained for trend, context, sentiment and cross-source corroboration, which were
> never tested and which most of these failure modes do not touch. No channel list is
> discarded. The forward plan is
> [`PHASE_K_TREND_LAYER_PLAN.md`](PHASE_K_TREND_LAYER_PLAN.md).

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

---

## 15. Source selection driven by actual holdings (2026-07-29)

Every sector decision up to here was made against a *hypothetical* ticker universe. Reading
the real book changes two things, one of them a correction to a criterion this document has
been applying since §10.

Measured from `trading_data/funds/*/llm_portfolio_update.csv`, snapshot **2026-02-27**
(slightly stale, fine for sector weighting). Dollar-weighted across all three live funds:
Project Chimera $16.9k, TFSA $8.3k, RRSP Lance Webull $219.2k, **total $244.4k**.

| Theme | Share of book | Largest positions |
|---|---|---|
| Semis / compute | **19.9%** | MU 2.7, AMAT 2.4, NXTG.TO 1.6, TSM 1.6, RMBS 1.4, ASML 1.2 |
| Grid / power / electrical | **11.9%** | **VRT 3.5**, FTS.TO 1.7, KEY.TO 1.6, ENB.TO 1.6, GEV 1.5, ETN 1.2 |
| Gold / precious | **10.8%** | XGD.TO 2.7, GLCC.TO 2.6, AEM.TO 2.5, CGL.TO 2.0, GMIN.TO 1.0 |
| Defense / aero | **6.7%** | GE 1.5, LHX 1.4, ATRL.TO 1.4, ITA 1.3, GD 1.2 |
| Rail / freight / infra | 2.8% | SNA 1.0, FAST 0.7, RAIL 0.4, DRX.TO 0.4, CNR.TO 0.3 |
| Ag / heavy equipment | 2.8% | CMI 1.3, DE 1.1, TRMB 0.4 |
| Nuclear / uranium | 2.4% | HURA.TO 1.1, CCO.TO 0.4, GLO.TO 0.3, LEU, URNM, CEG, URNJ, OKLO |
| Diversified mining / materials | 2.2% | XMA.TO 1.2, STLD 1.0, TECK.B.TO 0.1 |
| Unclassified (broad ETFs, staples, healthcare, software) | 40.5% | — |

### The correction: 41% of the book is Canadian-listed

**41.0% CAD-listed (`.TO` / `.V`), 59.0% US-listed.** §10 and §12 both rejected sectors partly
on the grounds that the covered companies were "not US-listed". The operative universe is
**North American — US plus TSX and TSXV** — which is a materially larger tradeable set, and
it matters most for exactly the sectors the book is heaviest in: Canadian miners and
uranium names are tradeable, not excluded.

Worth being precise about what this does and does not overturn:

- **It does not revive space or displays.** SpaceX is still private; LG, Samsung and TCL are
  still Korean and Chinese listings. TSX access does not reach them. Those rejections stand.
- **It does revive mining.** [`PHASE_K_SOURCE_RESEARCH_PROMPT.md`](PHASE_K_SOURCE_RESEARCH_PROMPT.md)
  §2 listed mining with the hazard "junior-stock promotion is endemic; primary data is in
  filings, not video" — still true, but it was never evaluated, and TSXV juniors are the one
  universe where §3's unavailable **attention** mechanism is plausibly live.

### Weighting by fund, not just by dollars

Dollar weight alone is misleading here. RRSP is 90% of the money and is a broad,
ETF-heavy, largely passive book — low value per marginal signal. **Project Chimera is the
fund the bot actually trades**, and its concentration is completely different:

- Nuclear/uranium ≈ **19%** of Chimera (CCO.TO 6.4, GLO.TO 3.7, LEU 2.0, URNM 2.0, CEG 2.0,
  URNJ 1.5, OKLO 1.2)
- Mining/materials ≈ **31%** (XMA.TO 16.7, GMIN.TO 14.7)
- Plus RAIL 6.1, DRX.TO 5.6, CNR.TO 4.1 — small-cap industrials

So Chimera is roughly **half mining and nuclear**, and it holds genuine small caps
(GLO.TO, WEB.V, RAIL, DRX.TO, LTRX) rather than the mega-caps that killed the attention
thesis in §3. **Source selection should be weighted to Chimera's composition**, not to the
dollar-weighted aggregate.

### What the existing allowlist already covers, and what it misses

The 13 seeded tech channels map onto the single largest theme (semis, 19.9%) — that was a
good instinct, and §14's 27% yield was measured against the theme with the most exposure.
Automotive (§12, adopted, not yet seeded) maps onto **almost nothing in the book** — TSLA
0.7%, no F/GM/RIVN/LCID at all. It scored best on mechanism quality but has near-zero
portfolio relevance, which is a genuine argument for de-prioritising it below the themes
here.

Uncovered themes ranked by *Chimera-weighted* relevance:

1. **Uranium / nuclear fuel cycle** — highest conviction gap. Chimera ~19%, and both
   ends of the cycle are North-American listed (CCO.TO, DNN.TO, NXE.TO, GLO.TO, LEU, UEC,
   UUUU) plus SMR names (OKLO, SMR, CEG). Hazard: the corpus is heavily promotional and
   partly paid placement.
2. **Grid / power / datacenter electrical** — 11.9% of the book and **VRT is the single
   largest individual position (3.5%)**. Uniquely well-matched to captions: the AI-datacenter
   power-constraint story is discussed continuously and technically, and `ServeTheHome`
   (already seeded) partially covers it. Cleanest sector on the list — no promotion problem,
   no listing problem.
3. **Gold / precious metals** — 10.8%. Same promotional hazard as uranium, worse.
4. **Defense / aerospace primes** — 6.7%. Note §10 already rejected *space*; primes are a
   different corpus (GD, LHX, GE), but likely derived commentary. Low expectations.

### Recommended revision to the round-3 run order

Supersedes the solar → agriculture → trucking order in
[`PHASE_K_SOURCE_RESEARCH_PROMPT.md`](PHASE_K_SOURCE_RESEARCH_PROMPT.md) §4, which was
set before the book was read. Solar drops out entirely — there is **no ENPH, SEDG, FSLR, RUN
or NOVA position anywhere in the three funds**, so it was a well-reasoned recommendation
about a sector we have no exposure to.

1. **Grid / power / datacenter electrical** — best combination of exposure (11.9%, top
   position) and low corpus contamination.
2. **Uranium / nuclear** — highest Chimera weight; run it second because the promotion
   filter has to be built and validated first.
3. **Mining / precious metals** — same corpus as uranium, so run as a follow-on once the
   promotion tells are calibrated, not as a separate research round.

Agriculture and trucking stay on the list (DE, CMI, TRMB, RAIL, CNR.TO, SNA, FAST — 5.6%
combined) but below these.

---

## 16. Round-3 sector triage: two-model result (2026-07-29)

Both models were sent the §5 triage prompt from
[`PHASE_K_SOURCE_RESEARCH_PROMPT.md`](PHASE_K_SOURCE_RESEARCH_PROMPT.md). **That prompt
predates §15**, so neither model ever saw the portfolio and neither scored grid/power,
uranium, mining or defense. The headline rankings are therefore not usable as a run order —
but the diff is still valuable, and it killed three sectors for free.

### Ranking diff

| Sector | Model A rank | Model B rank | Agreement |
|---|---|---|---|
| RV / powersports / marine | 1 | 2 | **converge (top 2)** |
| Residential solar | 2 | 3 | **converge (top 3)** |
| Trucking / heavy diesel | 3 | 4 | converge |
| Power tools / outdoor | 5 | 5 | **converge — reject** |
| 3D printing | 7 | 7 | **converge — reject** |
| Restaurants | 8 | 8 | **converge — reject** |
| Agriculture | 4 | 6 | diverge |
| Firearms / ammunition | 6 | **1** | **maximal disagreement** |

### Three sectors double-rejected, with mechanisms — keep these

Independent double-nomination has outperformed either model's own ranking in every round, and
it applies to rejections as well as picks:

1. **Power tools.** Both name the same cause: Techtronic (Milwaukee, Ryobi) is HK-listed
   0669.HK and dominates the high-quality test corpus; Makita and Bosch are foreign or
   private; SWK is the only US play and we do not hold it. **Third occurrence of the
   space/displays failure mode.**
2. **3D printing.** Both name Bambu / Prusa / Creality (private or non-US) as owning the
   corpus, with DDD and SSYS "enterprise ghosts" on YouTube. Same failure mode again.
3. **Restaurants.** Both score primary-observation 1-2: food review is subjective, visual and
   concurrent with public release. No teardown analogue exists.

Solar also weakened on independent grounds: Model B notes Chinese portable-power brands
(EcoFlow, Jackery, Anker — private) and Tesla dominate DIY/teardown volume, diluting the US
mid-caps "exactly like displays"; Model A notes rate-driven macro swamps product alpha.
§15 had already dropped solar for zero exposure; this is convergent mechanistic support.

### The firearms contradiction — treat as unknown, not as Model B's pick

Rank 6 vs rank 1, and the caption-legibility scores are **2 vs 5** for the same corpus. Per
§8's blocklist finding, disagreement of this size is the signal: both are guessing.

Model A's case is the more checkable one and it is mechanistically right: the decisive data
points (chronograph velocities, shot groupings on paper) are **visual**, and the brands the
channels actually test are heavily private (Glock, Sig Sauer). RGR and SWBI are genuine
US-listed pure plays, but the corpus is not pointed at them. Model B asserts 85-95%
tradeable without naming which companies produce that figure.

Moot for now regardless — **zero firearms exposure.** Both models agree the demand signal
belongs to NICS, not YouTube.

### Convergent structured-dataset findings — the most durable output

Both rounds independently reached for datasets over video in the same places, continuing the
FAA/FCC (§10) and NHTSA (§12) pattern:

| Sector | Dataset | Cost |
|---|---|---|
| Firearms | **FBI NICS** background checks (both models) | free, monthly |
| Trucking | **DAT** load-board rates (both models); Cass Freight Index, ACT/FTR Class-8 net orders, FMCSA CSA, EPA engine certs | DAT / ACT / FTR are **paid subscriptions**; Cass is effectively free |
| Agriculture | USDA WASDE, NASS yields, crop progress, grain stocks | free |
| Restaurants | credit-card panels (YipitData, Earnest), Placer.ai foot traffic; municipal health-inspection scores | panels are **institutionally priced**; inspections free |
| Solar | EIA monthly generation, interconnection-queue reports, state PUC dockets | free |

Neither model flagged cost, and it matters: "skip YouTube, ingest DAT" is only actionable if
we buy DAT. The free-and-genuinely-good subset is **NICS, USDA, EIA, Cass, health
inspections**.

### One idea worth transplanting

Model A's proposed sector (HVAC/plumbing — LII, AAON, WTS, FIX) is zero-exposure and not
adoptable, but its *mechanism* is directly reusable: GoPro service-call channels where
technicians read out error codes, gauge pressures and part numbers. That is exactly the
primary-observation corpus §8.1 is looking for in grid/power, drawn from the same trades
population — and FIX and AAON are datacenter mechanical/cooling contractors, i.e. the VRT /
ETN theme observed from the install side. We do hold AOS (0.77%). **Fold this into the
grid/power round as a search hint, not a separate sector.**

Model B's proposed sector (powersports components) is not adoptable: zero exposure, and it
could not name a single ticker — "think the component suppliers... more specialized". An
unnamed universe has no verification path.

### Calibration notes for the next round

- **Model A answered "Leads" in 7 of 8 rows**; Model B was more discriminating (three
  "Concurrent"). Lead time is the column that should separate sectors, so a near-constant
  answer is agreement, not measurement. Our tech round *measured* a largely concurrent
  corpus (Anastasi was rejected for exactly this), so treat any unverified "Leads" as
  unknown.
- Both admitted their tradeable-share figures are estimates, not audits — §1's rules already
  say to treat these as leads, and they were honest about it. The escape hatches keep working.
- **Model B contributed a genuinely new pre-filter:** caption-legibility scores assume
  average auto-transcripts, so *channels with heavy on-screen charts or silent teardowns
  score lower in practice*. That is checkable per channel and belongs in the §9 discovery
  ranking.

### Action

Re-run triage on the §5 prompt **as patched by §15** — it now carries portfolio weights and
an explicit "I must already have exposure" constraint, plus the note that 41% of the book is
TSX/TSXV. The run order in §8.1-8.3 (grid/power → uranium → mining) stands unchanged, because
nothing in this round bears on those three sectors.

> **Superseded by §17.** The triage re-run was skipped as redundant — the portfolio had
> already selected the sector, and §8.1's core question subsumed the triage question. Went
> straight to the grid/power channel round.

---

## 17. Grid / power / datacenter electrical — REJECTED as a caption sector, ADOPTED as a
## dataset path (2026-07-29)

The §8.1 prompt was sent for the highest-exposure uncovered theme (11.9% of the book, VRT the
largest single position). One round trip, decisive answer, **zero caption fetches spent.**

**Verdict: do not add grid/power caption sources.** The response was a flat *"I will be
plain: it is wishful thinking"* — the same phrasing that correctly killed space attention
alpha in §10, which is mildly reassuring about calibration.

### The finding: a new failure mode — access-gated observation

This is **not** another instance of §10/§12's inverse-correlation pattern, and the difference
matters for the synthesis in §18. Here the companies are ideal: VRT, ETN, PWR, GEV, CEG,
FIX, MYRG are all US-listed, liquid, and the equipment *is* substantially their revenue. The
tradeability and materiality criteria both pass cleanly.

What fails is that **the observation is legally and physically inaccessible**:

1. **Security and NERC CIP.** You cannot bring a camera into a hyperscale datacenter or a
   500kV substation. For utility and contractor staff it is an NDA and corporate-comms
   violation, and substations sit under Critical Infrastructure Protection physical-security
   standards.
2. **Audience mismatch.** The residential HVAC tech works alone and owns his channel. The
   commissioning engineer spinning up 50 Vertiv CDU cooling loops is escorted, works under a
   tier-one GC, and is bound by corporate comms policy. **The person with the information is
   structurally the person who cannot publish it.**

So the residential/light-commercial trades corpus is real — and irrelevant to our tickers.
The utility-scale and hyperscale corpus we actually wanted does not exist in the wild. What
does exist is macro commentary, financial YouTubers reading Substacks, and vendor-approved
sanitized tours.

One caveat on the CIP claim: NERC CIP standards bind the *registered entity*, not a random
videographer, so "violation of federal CIP rules" is somewhat overstated as applied to a
filmer. The operational conclusion is unaffected — employees will not film regardless.

### Corroborated by the model's own output, which is why this is credible

The four channels it supplied argue against its own recommendation, and it did not hide that:

| Channel | Visual dependence | Lead time | Dated example |
|---|---|---|---|
| HVACR Videos | **HIGH** | UNVERIFIED | UNVERIFIED |
| Electrician U | MEDIUM | UNVERIFIED | UNVERIFIED |
| S​e​r​v​e​T​h​e​H​o​m​e | MEDIUM | **concurrent** | UNVERIFIED |
| Bobsdecline (lineman) | **HIGH** | UNVERIFIED | UNVERIFIED |

**Zero dated examples of the sector leading, on four attempts.** Under §7's criteria that is
a rejection on its own, independent of the structural argument. The `visual_dependence` field
added to the §6 schema this round did real work immediately — helmet-cam and gauge-pointing
content is exactly what a caption pipeline cannot use.

### Useful critique of a source we already run

It independently named **S​e​r​v​e​T​h​e​H​o​m​e** — already seeded — and flagged it as the
recommendation *most* exposed to the sanitization hazard: heavy vendor access, review
samples, sponsored datacenter tours, and `lead_time: concurrent`. Its tell is checkable from
caption text: *"vendor sent us this for review"*, *"we're here at the [Company] briefing
centre"*. Worth watching in Stage 0 — STH scored 40% yield in §14, and if those claims are
concurrent product-showcase facts rather than leading ones, that yield is overstated.

### The B-roll silence tell — implement this in K2, it generalises

The best mechanically-implementable heuristic produced by any research round:

> *"Let's take a look at how this liquid cooling loop works"*, followed by **1-3 minutes of
> silence in the captions** before the narrator returns — meaning OEM marketing animation or
> silent b-roll played.

This is a **caption-gap detector**: measure the distribution of timestamp gaps in a
transcript, and flag videos with long silent stretches. It is a direct proxy for
`visual_dependence`, computable with no LLM call, and it generalises to every sector — silent
teardowns and chart-heavy explainers fail a caption pipeline everywhere. Recommend
implementing alongside §8's derived-content score as a per-article metric.

Two further tells worth keeping, both caption-detectable:

- **TAM/CAGR tell** — `TAM`, `CAGR`, `hyperscaler`, *"according to a new report by Dell'Oro /
  Gartner"*. A technician fixing a chiller does not discuss total addressable market.
- **Marketing-adjective tell** — *cutting-edge*, *synergistic*, *next-generation*,
  *optimized*. A tradesman says *"this 400-amp Eaton breaker is backordered 12 weeks"*.

### What we gained: the best structured-data path found so far

The negative space answer is more valuable than the channel list, and cost flags were
supplied this round because §8.1 asked for them:

| Dataset | Cost | What it gives |
|---|---|---|
| **Interconnection queues** (PJM, ERCOT, CAISO, MISO) | **free** | Exact MW requests, developer names, status. What PWR / MYRG / PRIM will build in **18-24 months** — contractor backlog and equipment demand, explicitly listed |
| **EPA / state air-quality permits** | **free** (state-dependent) | Datacenter backup-generator permitting lands months before concrete is poured — reveals datacenter intent and scale ahead of press releases. Ties to CMI (held, 1.25%) and CAT |
| **FERC EQR / Form 1** | **free** | Utility transmission spend and vendor contracts |
| US customs / bill of lading (Panjiva, ImportGenius) | **paid** | Large transformers and HV switchgear entering the US |

The air-permit signal is the most genuinely novel item any round has produced: a
consumer-invisible, free, leading indicator of datacenter buildout intent. Interconnection
queues at 18-24 months lead time are the longest-dated signal in this document.

**This belongs in its own phase, not Phase K** — same conclusion as §10 reached for FAA/FCC
space data. Phase K is a captions pipeline; four rounds have now produced three separate
sectors whose real answer is structured data (space, auto recalls, grid/power) plus two more
where a dataset dominates (firearms → NICS, trucking → Cass/DAT). That recurrence is itself
the finding, and it is getting hard to ignore.

### Second model: partial dissent that strengthens the rejection

Model B did **not** endorse A's structural-impossibility argument. Its read: *"a genuine but
sparse primary corpus"*, *"not entirely macro talking heads, but the information-dense primary
slice is thin"*, and — pushing back on the prompt's framing — *"if the 4-8 channel budget
cannot be filled with high-confidence primary sources after verification, filings + queue
data will outperform captions here. That is the practical read, not wishful thinking."*

That is a fair distinction, and it converts the question from *does the corpus exist* to
**can the 4-8 channel budget actually be filled**. Answer, taking both models' output
together: no.

**Eight channels proposed across both models. Seven fail mechanically:**

| Channel | Model | Disqualifier |
|---|---|---|
| Residual Electrical | B | `tickers_actually_discussed: []` — UK contractor, 10-20% tradeable |
| MEP Academy | B | `tickers: []`, visual MEDIUM-HIGH, educational content |
| Gaurav J | B | `tickers: []`, educator selling courses, manufacturer-interview access bias |
| HVACR Videos | A | visual dependence **HIGH** (gauges, part numbers pointed at, not read aloud) |
| Electrician U | A | NEC code theory, whiteboard-based |
| Bobsdecline | A | visual **HIGH** — helmet-cam, wind noise, brands not narrated |
| S​e​r​v​e​T​h​e​H​o​m​e | A | already seeded; flagged `concurrent` + vendor-sanitized |

**Three of Model B's four have literally empty `tickers_actually_discussed`.** The
tradeability scan fails at the source — these channels do not discuss our companies at all.
That field and `visual_dependence`, both added to the §6 schema this round, did the rejecting
without any probe work.

**And the decisive number: 8 channels, 8 × `dated_example: UNVERIFIED`.** Neither model could
produce a single instance of this sector leading, on eight attempts. §7's criteria reject on
that alone.

### The one survivor, and why it is a single source rather than a sector

**Gruber Power** (`@GruberPower`, ~229k) is the only candidate that clears the mechanical
filters: `PRIMARY`, `visual_dependence: LOW`, and it actually names Vertiv/Liebert and Eaton
equipment in service contexts — UPS modules, battery-string tests, LOTO procedures. Model A
missed it entirely, which is exactly why we run two models.

Three caveats, and the first is disqualifying at sector scale:

1. **It is a vendor.** Gruber Power is a critical-power service company selling and
   maintaining the equipment it discusses. Model B flags the promotional bias itself. This is
   the same conflict class that excluded **iFixit** in §5 — a company with direct financial
   interest in the problem it publicises.
2. `typical_nonstream_minutes: 5` — short service explainers, low absolute information volume.
3. `lead_time: UNKNOWN`, `dated_example: UNVERIFIED`, like everything else here.

**Recommendation:** probe Gruber Power as **one opportunistic source**, not as the beachhead
of a sector. ~10 caption fetches, well inside a day's budget, and it is the only falsifiable
residue of the whole round. If its captions genuinely carry backordered-lead-time claims on
named OEM equipment, that is a real find; the vendor conflict then needs weighing against it.

### The HVAC transplant idea is dead — tested and failed

§16 proposed folding Model A's HVAC-technician corpus into this round as a search hint. Both
models independently rejected it on the same grounds: the GoPro service-call corpus is real
and caption-rich for **residential and light-commercial** units, and **does not extend** to
industrial switchgear, transformers, UPS, or datacenter-scale mechanical at the same verbal
part-number density. Model B: *"Those jobs exist; they are simply not filmed and narrated at
scale on public English YouTube the way residential service calls are."*

Double-confirmed rejection of our own hypothesis, at the cost of one prompt. Worth recording
as a hit for the process, not against it.

### Dataset finding: double-nominated, so this is the durable output

Both models independently reached for the same free sources, which by §16's standard is the
strongest signal available:

- **ISO/RTO interconnection queues** (PJM, MISO, CAISO, ERCOT) — both models, free
- **FERC** eLibrary / Form 1 / EQR — both models, free
- Model B adds: **EIA Electric Power Monthly/Annual**, **DOE transformer reports**, utility
  **IRPs** and **state PUC dockets** — all free
- Model A adds: **EPA / state air-quality permits** for datacenter backup generators (free,
  and still the most novel single item any round has produced), plus customs bill-of-lading
  (paid)

Both state plainly that these beat captions *for the exact facts we wanted* — lead times and
shortages that later surface in VRT/ETN/PWR/GEV backlog.

### Blocklist tells also converged

A's **TAM/CAGR tell** and B's *"AI data centers will need X GW / the grid can't keep up"*
tell are the same tell: macro narration with no SKU, part number, observed lead time, error
code, or schedule slip. Both independently name the news-aggregation tell (*"according to
reports"*, *"analysts say transformer lead times are now 3 years"*) and the AI-voice/scripted
cadence tell (*"in this video we will explore"*, smooth low-hesitation stat delivery). B adds
**manufacturer promo without field friction** — product-feature lists with zero mention of
installation problems, commissioning delays, or parts availability.

Convergent tells across two models, in a domain where §8 found blocklists had *zero* overlap.
These are worth implementing.

### Self-verification: run, and the absence is confirmed (2026-07-30)

`scripts/yt_discover_channels.py` now exists and was pointed at this exact question.
**6 observation-targeted queries × 20 results = 120 listings, zero caption fetches, ~2
minutes.**

| Measure | Result |
|---|---|
| Distinct channels across 120 videos | **102** |
| Max distinct-query recurrence | **2** (one channel) |
| Channels recurring across ≥3 queries | **0** |
| Channels whose titles name a tradeable target | **2 — `Eaton` and `Switch On to Eaton`**, both the manufacturer's own channels |

**No concentration whatsoever** — 0.85 channels per video means the search surface is a flat
long tail with no repeat authorities, which is the opposite of what a real source corpus looks
like. For contrast, the double-nomination principle that drove every research round assumes
good sources *recur*; here nothing does.

The only tradeable-name coverage comes from **the issuer's own marketing channels**, which are
disclosure-preempted (§19) and derived by construction. The rest of the head is vendor
channels (Schneider Electric, OMICRONenergy, DCX Liquid Cooling, NM Cabling, Equinix) and
`The Engineering Mindset` — which Model A specifically named as *"excellent visually, useless
for NLP"*. `Electrician U` appears, matching Model A's list, so the tool reproduces the
research findings rather than contradicting them.

**§17's absence claim is confirmed by measurement, not assertion**, at a cost of zero caption
fetches. Both models' conclusion stands, and the two research rounds that produced it could
have been replaced by two minutes of listing.

> **Measurement caveat worth carrying.** The first run reported `0%` tradeable share for
> *every* channel, which was a bug in the tool, not a finding: it matched ticker symbols only,
> while §3's original scan counted **company mentions**. Titles say "Eaton", not "ETN". The
> script now takes company/brand aliases (`ETN:Eaton`), and the corrected figures are above.
> Any future tradeable-share scan must match names, or it will manufacture absence results.

### The original plan for cheap self-verification

The claim is an assertion of *absence*, which is the hardest kind to trust, and it is
consequential. It can be checked for free — **listing is not rate-limited (§13)** — using the
§9 discovery pipeline: run observation-targeted queries (`transformer lead times 2026`,
`switchgear shortage datacenter`, `liquid cooling retrofit colocation`,
`interconnection queue delay`), aggregate to channels, and title-scan. If the results are all
macro commentary and vendor tours, the absence is confirmed at a cost of zero caption
fetches. Prefer this over a second research round: it is cheaper and it produces measured
rather than asserted evidence.

---

## 18. Cross-round synthesis: what actually predicts a sector's fate

Four research rounds, ~10 sectors assessed, **2 adopted**. The per-sector reasoning is above;
this is the part that transfers.

### Scoreboard

| Sector | Verdict | Killed by |
|---|---|---|
| Tech / semis | **adopted** — 27% Stage 0 yield | — |
| Automotive | **adopted** (§12), seeding pending | — |
| Space / aerospace | rejected | untradeable subject (SpaceX private) |
| Consumer electronics / displays | rejected | untradeable subject (KR/CN listings) |
| Power tools | rejected | untradeable subject (TTI HK-listed) |
| 3D printing | rejected | untradeable subject (Bambu/Prusa/Creality) |
| Restaurants | rejected | no primary corpus; subjective and visual |
| Grid / power | rejected as captions, **adopted as dataset** | access-gated observation |
| Residential solar | dropped | zero portfolio exposure |
| Firearms | moot | zero exposure; visual data; NICS dominates |
| Uranium / mining | **pending** | — |

### The five failure modes, in order of how often they have fired

1. **Untradeable subject (4×).** The best primary observation points at a private or
   foreign-listed company. Detected free by title-scanning for tradeable share — the single
   highest-value filter we have. Reject under ~50%.
2. **Dataset dominance (5×).** A free public dataset is more complete, more timely and
   cheaper than the video corpus: FAA/FCC/SAM.gov (space), NHTSA (recalls), NICS (firearms),
   Cass/DAT (freight), interconnection queues + EPA air permits (grid). **This has now fired
   more often than anything else.** Ask the negative-space question early — it has been the
   highest-yield question in the prompt every single round.
3. **Access-gated observation (1×, new in §17).** Tradeability and materiality both pass, but
   the people who can see the facts are contractually or legally barred from publishing — or
   simply do not film. Watch for this wherever the subject is industrial-scale, secure, or
   enterprise; it is the failure mode that does *not* show up in a tradeability scan, so it
   needs asking about directly. Note the two models disagreed on *why* (A: structurally
   impossible; B: exists but sparse) while agreeing the budget cannot be filled — the
   operational test is **"can I name 4-8 qualifying channels?"**, not "does any exist?"
4. **Visual dependence (2×).** Chronograph readings, shot groupings, gauges, helmet-cam.
   Now partly mechanised: the `visual_dependence` field plus §17's caption-gap detector.
5. **Materiality dilution (1×).** Real defect, immaterial issuer line — §11's melting
   Nvidia connector.
6. **Disclosure-law preemption (1×, new in §19, and the most general of the six).** Where the
   *issuer* is the source of the fact, securities law requires the filing to precede the
   spoken word — NI 43-101 and NI 51-102 in Canada, Reg FD in the US. Captions cannot lead in
   principle. This kills interview- and IR-format sources across **every** regulated sector at
   once, and it is why `TEARDOWN` and `LEAK` sources have worked for us while `EARNINGS_IR`
   and interview-`ANALYSIS` have not. **Ask of any candidate source: is the fact observed
   independently, or supplied by the issuer?** If the latter, the filing beats it by law.

Plus one process failure, which was ours rather than a model's: **recommending sectors with
zero portfolio exposure** (solar, RV, HVAC). Fixed in §15 by putting real weights in the
prompt. Cost: two research rounds spent ranking sectors we hold nothing in.

### What consistently worked

- **Independent double-nomination**, for picks *and* rejections. More reliable than either
  model's self-ranking in every round without exception (§16 killed three sectors this way).
- **Explicit escape hatches** (`HANDLE UNSURE`, `UNKNOWN`, `UNVERIFIED`). §10 noted these
  improved calibration; §17 is the strongest case — the model's honest `UNVERIFIED` fields
  are what made its rejection believable.
- **Demanding a dated, falsifiable example per channel.** Zero-for-four on that field
  rejected grid/power independently of any argument.
- **Asking the make-or-break question directly** in the prompt, and inviting a flat no. Both
  flat "wishful thinking" answers (space attention, grid corpus) were correct.
- **Asking for the negative space.** Failure mode 2 above; it has out-produced the channel
  lists.

### What consistently did not work

- **Model rankings and self-scored tables.** Near-constant columns (§16: "Leads" in 7 of 8
  rows), estimated percentages presented as measurements, and maximal disagreement on
  firearms (rank 1 vs 6, caption-legibility 5 vs 2) on identical evidence.
- **Blocklists of named channels.** Zero overlap between models (§8). The *tells* generalise;
  the names do not. §17's three tells are worth more than every blocklist combined.
- **Handles.** ~4 of 30 wrong across rounds, including a 290-sub impostor. Never seed
  unverified.

### Prediction to test on uranium / mining *(resolved — see §19)*

Given failure mode 2's frequency, the base rate now favours **SEDAR+ technical reports and
drill-result filings over captions** for mining — as already written down in prompt §8.3
before the research runs. If the next round comes back enthusiastic about mining channels,
that is *weak* evidence, because promotional channels are built to read as authoritative.
Uranium is the more interesting of the two, because it is the only remaining sector where
ATTENTION alpha is plausibly live (TSXV juniors, retail bases) — and that mechanism has been
unavailable everywhere else we have looked.

> **Resolved in §19. Prediction confirmed by both models independently:** SEDAR+ / NI 43-101
> dominate the resource signal and are free; UxC / TradeTech are paid. Recording that it was
> written down *before* the round, since a prediction made after the fact is worth nothing.

---

## 19. Uranium / nuclear — REJECTED as an INFORMATION sector. Attention alpha is real and
## is the promotion machine (2026-07-30)

Both models answered the §8.2 prompt. This is the cleanest result of the project, and it
generalises further than the sector.

### The budget test, and the number that decides it

| | Model A | Model B |
|---|---|---|
| Channels named | 4 | 6 |
| Clearing the INFORMATION filter | **0** | claims 4-6 "usable" |
| `promotion_risk` LOW | **0** | **0** |
| `dated_example` verified | **0 / 4** | **0 / 6** |
| Any channel claimed to *lead* on fact | no ("lagging" ×4) | no ("concurrent \| lagging"; best case "interpretation of known data") |

**Ten distinct channels across two models. Zero rated `promotion_risk: LOW`. Zero dated
examples, on ten attempts.** Combined with grid/power's 8, that is **18 consecutive channel
assessments with no verifiable instance of leading.**

Model A answered the budget test bluntly: *"Zero channels clear your INFORMATION filter…
If your pipeline requires a channel to beat a press release to be valuable, you should
abandon YouTube for this sector entirely."* Model B said the budget was met at 4-6 usable
channels — but its own best case for the strongest candidate is *"concurrent to days on
interpretation of known data; UNKNOWN on pure firsts."* Interpretation of public data is
`ANALYSIS` of already-priced information; §3 defines that as not alpha. **The two models
disagree on the verdict and agree on every underlying fact.**

Double-nominated channels: Crux Investor (both, promotion HIGH both), Uranium Insider (both),
Mining Stock Education (both). Model A supplies the detail that decides Uranium Insider,
which B missed: its paid newsletter *"subscribers receive actionable stock picks days before
they are discussed on YouTube."* The video is structurally the exit, not the entry.

### The structural finding: disclosure-law preemption — a new failure mode, and the most general one yet

Model A: *"Because of NI 43-101 (Canada) and Reg FD (US), material drill intercepts and
resource estimates must hit the tape before a CEO can legally discuss them on a podcast…
Any channel breaking a drill result first is a CEO committing a securities violation."*

Model B confirms it from the other side: it cannot verify a dated first because it *"cannot
mechanically confirm a channel published a material non-public fact before any press or
filing"* — and it routes the hard resource signal to NI 43-101 technical reports.

This is not access-gating (§17) and not untradeability. **The information is legally required
to be public before it can be spoken.** Where an issuer is the source, the filing *always*
precedes the video, by law. Captions cannot lead, in principle, not merely in practice.

### Why this explains the entire project's results

The preemption applies to **issuer-sourced** content, not to independent observation. That
single distinction retrodicts every result in this document:

| `alpha_mechanism` | Source of the fact | Preempted? | Our result |
|---|---|---|---|
| `TEARDOWN` | Independent measurement of a product | **No** — nobody has a disclosure duty over a reviewer's bench | tech + auto **adopted** |
| `LEAK` | Supply-chain source, unofficial | **No** — the whole point is that it evades disclosure | M​L​I​D, 40% yield |
| `ANALYSIS` | Interpretation of public data | Partly — the input is already priced | low yields (§14: 10-11%) |
| `EARNINGS_IR` | The issuer itself | **Yes, totally** | — |

**Concrete implication for a source we already run:** `P​a​l​a​n​t​i​r​ ​I​R` is seeded as
`EARNINGS_IR` (tier 2, disabled by default). An earnings call is Reg FD-compliant public
disclosure at the moment it is spoken, and machine transcripts are available faster
elsewhere. **It can never lead, by construction.** It may still be useful as structured claim
extraction, but it should not be weighted as a source of unpriced information, and enabling
it should be a deliberate decision rather than a default.

This also retrospectively explains §14's yield table better than the "tech density" heuristic
did: the low-yield channels were the interpretive ones, the high-yield ones were the
observational ones.

### Attention alpha: the first YES in the project — and it is the promotion machine

Both models say live, and both immediately qualify it identically.

Model A: *"It is live, but it is entirely the promotion machine working as designed…
engineered liquidity… it exists primarily so that insiders, warrant holders, or the
channel's paid newsletter subscribers (who were given the ticker a week in advance) have a
retail bid to sell into… If you hold the position for a week, you will become the exit
liquidity for the bought-deal equity raise that almost always immediately follows."*

Model B: *"live in the narrow sense… usually the promotion machine working as designed rather
than independent information alpha… often reverses once the promotional wave ends… Flat
dismissal would be wrong; calling it clean alpha would also be wrong."*

So §3's founding question finally gets a YES — in the one sector where the mechanism is
inseparable from paid promotion. Both describe the same trade: buy the video drop, exit
within hours, before the financing.

**Recommendation: do not build that.** Two reasons, and the second is sufficient on its own:

1. It is buying into a paid promotion in order to sell to the retail flow the promotion
   creates. That is being part of the machine, not trading around it.
2. **Our infrastructure would systematically capture the wrong half.** The edge is
   hours-scale; `jobs_stance_outcomes.py` and the Stage 3 machinery measure at week scale,
   and the bought deal lands inside that window. We would reliably eat the reversal and miss
   the spike. This is not a squeamishness argument — the plumbing cannot hold the trade.

**The defensible use is the inverse, and it is genuinely valuable:** we hold GLO.TO, and both
models name it as a promotion target. A detector that flags *"a paid-IR wave is running on a
name we own"* is a **risk and exit signal**, not an entry signal. Same model, same tells,
opposite direction, no ethical problem, and it fits the horizon our machinery actually
measures.

### The promotion tells — double-nominated, and the most implementable artifact of the project

§8 found two models' *blocklists* had zero overlap. Their *tells* here converge strongly,
which is exactly the pattern that made us prefer tells over names:

| Tell | A | B | Implementation |
|---|---|---|---|
| **Missing friction words** | ✔ | ✔ | **Zero-count check** on `burn rate`, `dilution`, `warrant overhang`, `bought deal`, `G&A`, `cost overrun`, `inferred only`, `AISC`. Cheap, no LLM call. |
| **Bad-news reframing** | ✔ ("does this give a better buying opportunity?") | ✔ ("additional de-risking time") | Regex/LLM on delay-adjacent spans |
| **Story-prompt phrasing** | ✔ ("walk us through the story") | ✔ ("tell us about the opportunity") | Direct phrase match |
| **Macro buffer** | ✔ (first 30-50% on macro before naming the asset) | — | Transcript-position measure: index of first asset mention |
| **No adversarial follow-up** | — | ✔ (host never presses on dodged numbers) | LLM scoring |
| **Absolutist upside language** | — | ✔ (`game-changer`, `multi-bagger`) vs probability-weighted | Lexicon |
| **Disclosure placement** | — | ✔ (paid: rapid legal paragraph at the very end) | Position of `paid for by` / `business relationship` |

**The missing-friction-word zero-count is the single best filter any round has produced.** It
is nearly free, needs no model, and generalises to every interview-format source in any
sector. Recommend implementing it in K2 alongside §8's derived-content score and §17's
caption-gap detector.

### Datasets — both models, all free unless noted

- **SEDAR+** (Canada) and **EDGAR** (US) — NI 43-101 technical reports, material change
  reports, resource/reserve tables. Both models. Free.
- **NRC** and **CNSC** dockets — permitting and SMR licensing timelines, lead YouTube by
  weeks. Both models. Free.
- **EIA Uranium Marketing Annual** — utility contracting volumes, inventories, realised
  prices. Model B. Free.
- **Euratom Supply Agency** indices — EU equivalent. Model B. Free.
- **IMF Primary Commodity Prices via FRED** — monthly spot history, free CSV. Model B.
- **UxC** and **TradeTech** — the actual spot/term benchmarks. **Paid, institutionally
  priced.** Both models. Model A adds the operational point that YouTubers subscribe to these
  and read the numbers out days later, so the video is a lagged copy of a paid feed.

---

## 20. Scope correction: what these rejections do and do not mean (2026-07-30)

**Everything above was measured against one bar: does a channel produce a ticker-specific,
falsifiable, material claim that is not yet priced?** That is the *event-driven information
alpha* bar from §7 Stage 0. It is the right bar for that mechanism and the rejections stand
against it.

**It is the wrong bar for the corpus as a whole, and reading §10-§19 as "YouTube is a dead
end" would be a misreading of our own evidence.** This section fixes the framing before it
calcifies. Nothing in §1-§19 is retracted; the *conclusions* are re-scoped.

### Two distinct uses, one corpus

| | **Use 1 — event alpha** | **Use 2 — trend, context, sentiment** |
|---|---|---|
| Unit | a single video | a rolling window of many videos |
| Question | "is this fact unpriced?" | "what is changing, and how fast?" |
| Needs a source to be | **first** | **consistent and dated** |
| Killed by disclosure preemption (§19)? | **yes** | **no** — aggregate interpretation is not a disclosure |
| Killed by promotion (§19)? | yes | **no** — promotion volume is itself a measurable series |
| Killed by "concurrent, not leading"? | yes | **no** — concurrent is fine for tracking a trend |
| Status | tested across 10 sectors, 2 adopted | **never tested** |

Every rejection in §10-§19 is a **Use 1** rejection. Use 2 has not been evaluated once, and
most of the failure modes that killed Use 1 do not apply to it:

- **Grid/power (§17)** — no channel leads on transformer lead times. But a rising *count* of
  contractors mentioning backorders across many videos over months is exactly the kind of
  slow-moving read that shows up in VRT/ETN backlog later. The individual video is not the
  signal; the derivative is.
- **Uranium (§19)** — no channel can legally break a drill result. But shifting sentiment
  across the analyst-and-interview corpus tracks how consensus *forms*, and §19 already
  identified promotion-wave detection on names we hold (GLO.TO) as a genuine exit signal.
  That is a Use 2 product built entirely out of a Use 1 rejection.
- **Stage 0's 27% yield (§14)** — the other **73% of videos were discarded**. They were
  discarded for lacking a falsifiable ticker claim, not for lacking information. That is
  three-quarters of an already-paid-for corpus sitting unused.

### What is retained, explicitly

**No research is discarded and no channel list is deleted.** Specifically retained as a
candidate pool for Use 2:

- All 13 seeded tech sources, plus the 6 verified automotive channels (§12).
- The grid/power candidates (§17): Gruber Power, HVACR Videos, Electrician U, Bobsdecline,
  Residual Electrical, MEP Academy, Gaurav J — rejected as leading indicators, still valid as
  a field-conditions corpus.
- The uranium/mining candidates (§19): Crux Investor, Palisades Gold Radio, Uranium Insider,
  Mining Stock Education, Triangle Investor, Resource Talks, The Next Big Rush — **useless as
  truth, valuable as a promotion-and-sentiment instrument.** A paid-IR channel is a perfectly
  reliable sensor for *"paid IR is running"*.
- Every measured artefact: handles, channel IDs, duration distributions, caption status,
  tradeable-share scans.

The five sector rejections that fail on **tradeability** (space, displays, power tools, 3D
printing) stay rejected for both uses — a corpus about companies we cannot trade has no Use 2
value either. **Access-gating and disclosure-preemption rejections do not transfer to Use 2.**

### The honest risk, stated up front

Use 2 is where a system can generate unlimited plausible-looking output that predicts
nothing. "Sentiment is improving" is unfalsifiable in a way "MU will beat on DRAM pricing" is
not. The discipline that made §10-§19 useful — demand a falsifiable claim, measure before
believing, prefer measurement to model opinion — has to carry into the trend layer or it
becomes an expensive vibes generator.

**Therefore: every Use 2 component gets a measurable success criterion defined *before* it is
built.** Those criteria are in [`PHASE_K_TREND_LAYER_PLAN.md`](PHASE_K_TREND_LAYER_PLAN.md).

### The two principles that carry forward

1. **No single source is reliable; agreement across independent sources is measurable.**
   Double-nomination outperformed every individual model ranking in all five research rounds
   (§16, §17, §19). We used it as a *research method*. It should become the **product's core
   algorithm** — the unit of output being a claim corroborated across N independent sources
   with an explicit divergence score, not a claim from one video.
2. **Allowlist polling answers the wrong question.** It asks *"what did my sources say
   today?"*. The powerful capability we actually have is transcript retrieval for **any**
   video, which answers *"what does YouTube know about MU and DRAM pricing?"* — on demand,
   when a question is being asked. That is a far better fit for research support, and it fits
   the ~90 fetches/day budget precisely because it is episodic rather than continuous.

---

## 21. K7 validation: the friction-word filter is FALSIFIED (2026-07-30)

`PHASE_K_TREND_LAYER_PLAN.md` §1 set the gate before building: *"K7 filters ship only if the
friction-word score separates known-promotional from known-primary channels with clear margin.
Killed if no separation — the tells were model opinion, not signal."*

**It failed, and it failed backwards.** Recording this in full, because it is the first time
measurement has overturned a double-nominated finding.

### The measurement

`web_dashboard/yt_content_filters.py` scored **109 known-primary transcripts** (the Stage 0
cache, mapped to their seeded channels via listing) against **12 mining-interview transcripts**
freshly fetched from Resource Talks, Crux Investor and Mining Stock Education — the exact
channels §19 named as the paid-IR corpus.

| Group | n | median words | friction/1k | **`zero_friction`** | disclosure hits |
|---|---|---|---|---|---|
| Tech primary (all 12 seeded channels) | 109 | 4,167 | **0.00** | **95%** | 0 |
| Resource Talks *(openly discloses paid production)* | 4 | 17,706 | **0.35** | **0%** | **2.0** |
| Mining Stock Education | 4 | 6,590 | 0.16 | 25% | 0 |
| Crux Investor | 4 | 4,060 | 0.00 | 75% | 0 |

§19's claim was that paid-IR interviews score **zero** on friction words while substantive
ones score above zero. Measured, the ordering is **inverted**: the interviews carry *more*
friction vocabulary (median 0.20/1k, max 1.46) than the primary corpus (median 0.00, max
0.47), and **95% of known-primary videos trip `zero_friction` against 33% of the interviews.**
The single most promotional channel in the sample — the one that openly discloses paid
content creation — has the **highest** friction score of any group, which contradicts even
the narrow within-domain version of the claim.

### Why it fails, which is the transferable part

**Friction words are corporate-finance vocabulary, so they track subject matter, not
integrity.** A GPU teardown never says "dilution" or "bought deal" because it is not about
corporate finance. A mining interview always does, paid or not, because that *is* the subject.
The filter was measuring topic and being read as measuring honesty.

This is exactly the §8 sanity check we specced and never ran — *"If Gamers Nexus scores as
derived, the heuristic is wrong"* — arriving two documents later in a different costume.
Gamers Nexus scores 100% `zero_friction`. Under the original interpretation it would have been
flagged as promotional.

### What survives

- **`disclosure_hits` — the only promotional signal that validated.** Resource Talks median 2,
  primary corpus 0. It detects *disclosed* payment, so by construction it finds honest
  promoters and misses covert ones. Useful as a K11 input, not as a completeness guarantee.
- **`friction_rate`, renamed in effect to `finance_topic_rate`** — retained as an honest topic
  feature. "Does this transcript discuss the issuer's balance sheet at all?" is a genuinely
  useful routing question and a K9 trend input.
- **`attribution_rate`** (§8 derived-content) — not yet validated either way; no labelled
  derived-vs-primary pairs exist. Untested, not endorsed.

### What is inert and should not be trusted

`story_prompt_hits` fired **zero times across all 121 transcripts** — the phrasing both models
quoted (*"walk us through the story"*, *"tell us about the opportunity"*) simply does not
occur at measurable rates. `hype_rate` and `macro_rate` are 0.00 median in both groups. The
composite `promotion_score` was removed rather than shipped, because it summed three inert
signals and subtracted an inverted one.

### The methodological finding — this is the important one

**Double-nomination is evidence, not proof.** It has been our most reliable instrument across
five research rounds and it is still the right way to rank leads. But two independent models
converged on a specific, confidently-stated, mechanically-testable claim, and the first
measurement falsified it in the opposite direction.

Both models were reasoning plausibly about a corpus neither had measured. The convergence
reflected shared priors about how promotion *sounds*, not shared observation. Treat future
double-nominated *tells* as hypotheses with a validation gate attached — which is what the
plan's kill criteria are for, and why writing them down before building was worth the effort.

**Cost of finding this out: 12 caption fetches and about an hour.** Cost of not finding out:
a promotion filter, wired into K11, that flags Gamers Nexus and clears paid IR.

### Caveats, stated plainly

n=12 on the interview side, 4 per channel, newest-first — small, and not a random sample.
The direction is unambiguous and the mechanism explains it, but the precise rates are not
reliable. What is *not* tested: paid versus unpaid interviews **within** mining, which is the
narrowest form of §19's claim; we have no labelled pairs. The Resource Talks result is
evidence against it, not a disproof of it.

---

## 22. View counts: the attention thesis rests on the wrong number (2026-07-30)

Flat listings carry `view_count` for free, and **no research round ever measured it.** Every
model reported *subscriber* counts, and §19's attention-alpha verdict was argued explicitly
from them: *"when a junior miner pays for an IR package and a video drops on a channel with
80K+ subscribers, retail volume measurably spikes."*

Measured across 30 recent videos per channel, listing only, zero caption fetches:

### Seeded tech corpus

| Channel | median views | p90 | max |
|---|---|---|---|
| G​a​m​e​r​s​ ​N​e​x​u​s | **241,000** | 615,000 | 1,200,000 |
| S​e​r​v​e​T​h​e​H​o​m​e | 177,500 | 318,000 | 479,000 |
| A​s​i​a​n​o​m​e​t​r​y | 158,500 | 286,000 | 485,000 |
| H​i​g​h​ ​Y​i​e​l​d | 154,500 | 387,000 | 1,600,000 |
| H​a​r​d​w​a​r​e​ ​U​n​b​o​x​e​d | 115,500 | 270,000 | 569,000 |
| G​e​e​k​e​r​w​a​n | 114,000 | 269,000 | 623,000 |
| d​e​r​8​a​u​e​r​ ​E​N | 56,000 | 130,000 | 486,000 |
| M​o​o​r​e​'​s​ ​L​a​w​ ​I​s​ ​D​e​a​d | 53,500 | 82,000 | 149,000 |
| L​e​v​e​l​1​T​e​c​h​s | 29,500 | 99,000 | 149,000 |
| T​h​e​ ​S​i​g​n​a​l​ ​P​a​t​h | 16,000 | 28,000 | 70,000 |
| A​c​t​u​a​l​l​y​ ​H​a​r​d​c​o​r​e​ ​O​v​e​r​c​l​o​c​k​i​n​g | 7,800 | 15,000 | 47,000 |
| T​e​c​h​T​e​c​h​P​o​t​a​t​o | 5,500 | 27,000 | 142,000 |
| **P​a​l​a​n​t​i​r​ ​I​R** | **1,200** | 6,900 | 24,000 |

### Mining / uranium interview corpus

| Channel | subs *(as reported by research)* | **median views** | view/sub | max |
|---|---|---|---|---|
| Resource Talks | 119k | **2,350** | **2.0%** | 4,900 |
| Crux Investor | 88k | **3,600** | **4.1%** | 10,000 |
| Mining Stock Education | 50k | 7,600 | 15% | 252,000 |
| Palisades Gold Radio | 115k | 13,000 | 11% | 107,000 |
| Uranium Insider | 22k | 12,500 | 57% | 28,000 |

**Median-of-channel-medians: tech 56,000 vs mining 7,600 — roughly 7×.**

### The finding: subscriber counts overstate reach by 10-50× in exactly the corpus the attention claim depends on

Crux Investor has 88k subscribers and a **median of 3,600 views**. Resource Talks — the
channel that openly discloses paid production, and the most promotional in the sample — has
119k subscribers and a **median of 2,350 views, a 2% view/sub ratio.** By engagement it is
close to a dead channel propped up by an accumulated subscriber number.

So §19's attention argument was reasoning from "80K+ subscribers" when the actual per-video
audience on those channels is **2,000-13,000 people** — before discounting for viewers who
are not traders, are not in the name, and cannot trade a TSXV junior. The claim is not
refuted, but its stated basis is off by an order of magnitude *in the direction that makes it
look strongest*, and the two channels with the largest subscriber counts have the **worst**
view ratios.

### This is the inverse-correlation pattern again, in a third form

Attention alpha needs **reach × small float**. Measured, those two are anti-correlated:

- G​a​m​e​r​s​ ​N​e​x​u​s has 241k median views and, per §3, talks about mega-caps a video cannot move.
- The mining channels cover genuinely small TSXV floats and reach 2-13k viewers.

§10 found quality inversely correlated with tradeability; §17 found the same for access; this
is the third instance. **The thing that makes a corpus valuable keeps being anti-correlated
with the thing that makes it tradeable.** That is now a strong enough regularity to treat as a
prior when evaluating any future source.

### Immediate consequences

1. **`P​a​l​a​n​t​i​r​ ​I​R` now has two independent disqualifications** — disclosure-preempted by
   construction (§19) *and* a median audience of 1,200. It is seeded tier 2 / disabled;
   it should stay that way, and this is the second reason to say so.
2. **The event study must use views as the independent variable, not run on medians.** If the
   attention mechanism is real, effect size scales with viewers. The right sample is the
   **high-view tail** — Mining Stock Education's 252k and Palisades' 107k outliers — not the
   2,350-view median, which is almost certainly too small to move anything. Testing the median
   would produce a null result that proves nothing.
3. **`view_count` is now carried on `VideoListing`** and is a structural reject in
   `scripts/yt_discover_channels.py` (`--min-views`, default 2,000): no audience means
   attention is impossible by construction, and information alpha rarely justifies a fetch
   either.
4. Low views do **not** disqualify a source for Use 2 (§20). T​e​c​h​T​e​c​h​P​o​t​a​t​o at 5,500 median
   views still scored 30% Stage 0 yield. Reach matters for *attention*; it is close to
   irrelevant for *information* and *trend* work.

---

## 23. Promotion event study: high-view tail not in the curated junior set (2026-07-30)

`PHASE_K_TREND_LAYER_PLAN.md` §7 asked whether a promotional mining/uranium video produces a
measurable 24–48h abnormal price/volume move that then reverses. Script:
`web_dashboard/scripts/yt_promotion_event_study.py`. Zero caption fetches, zero LLM, zero DB
writes. Methodology mirrors `insider_event_study.py` (entry = first close strictly after
publish date; dedupe to ticker×day; high−low spread; day-bucketed null; Canadian listings
via `resolve_benchmark`).

### Publish dates

Confirmed before the run: flat listing returns `upload_date=None` / `timestamp=None`;
non-flat metadata (`fetch_video_metadata`, no captions) returns both. All 16 title-matched
candidates resolved a date; **0 blocked**. Metadata remains available at this volume on a
residential IP.

### Attrition (the result that matters more than the headline)

| Stage | n |
|---|---|
| Videos listed (5 channels × 100) | **500** |
| Title matched exactly one curated ticker | **16** |
| Title matched multiple curated tickers | 1 |
| Title matched none | 483 |
| Demoted to multi after description re-match | −7 |
| Dates resolved (**16 of 16 attempted, 0 blocked**) | 9 |
| After (ticker, day) dedupe | 9 |
| Usable price history | **8** |

*(Row order corrected 2026-07-30: date resolution lost nothing — all 16 attempts
succeeded. The 16 → 9 drop is entirely the description re-match demotion.)*

Effective sample: **n=8 — directional only.** View buckets after dedupe: low=7, mid=2,
**high (≥50k)=0**.

### What the high-view tail actually is

§22 named Mining Stock Education's 252k and Palisades' 107k outliers as the sample the claim
needs. Those videos exist in the listing — they are about names **outside** the curated
uranium/gold junior list (e.g. copper developers). On the curated set that §19's claim is
about (DNN / NXE / GLO / CCO-type names), **no priced event cleared 50k views.** Max in the
priced sample: 24,421 (OR.TO on Mining Stock Education).

So the study cannot falsify or confirm the attention mechanism *as stated*. Running on
low/mid views would be exactly the null §22 warned against. Reported below for completeness,
not as a verdict on the claim.

### Low/mid numbers (not a test of the claim)

Pre-event drift (t−5→t−1 excess): n=8, mean **−0.52%**, median +0.91% — names are not
systematically running into the video in this tiny sample.

| Horizon | low n=6 mean | mid n=2 mean |
|---|---|---|
| t+1 | +0.41% | +0.57% |
| t+2 | +0.69% | +1.02% |
| t+5 | +1.40% | +0.75% |
| t+21 | +1.53% (n=5) | −10.66% |

Abnormal volume (entry / 20-session median): low 1.16×, mid 0.61× — no retail volume spike
on these events either. No high/low co-occurrence by day, so the null model has nothing to
relabel.

### What survives

- **Publish-date path is usable** for event studies without caption quota spend.
- **Company-name matching is mandatory** — 16/500 single-ticker title hits on aliases; symbol-
  only matching would have been near zero (§17).
- **Description re-match is strict**: 7/16 title singles demoted when the description named a
  second curated company. Correct for attribution purity; costly for sample size.
- **The §19 claim remains UNVERIFIED**, not falsified. The blocker is sample construction:
  the high-view tail of the promotion channels is not concentrated on the curated junior set
  the claim names. Closing it needs either a wider (still pre-registered) ticker universe that
  includes whatever the outliers actually name, or a different channel set — not threshold
  tuning on this run.

### Follow-up: the 483 unmatched titles were inspected, and they change this diagnosis

*(Added 2026-07-30 after §23's first draft. The remedy proposed immediately above — widen the
ticker universe — was checked and **would not work**. Recording why, because the reason is a
finding.)*

The obvious worry about a 16/500 match rate is a repeat of the §17 matcher bug. It is not:
the matcher is fine and the 42-company universe is reasonable. Sorting all 483 unmatched
titles by view count and reading the top 26:

| Content type | count (top 26 by views) |
|---|---|
| **Macro / pundit commentary** — Rick Rule, Martin Armstrong, Douglas Macgregor, Bill Holter, Luke Gromen, Michael Oliver, Lyn Alden, Doomberg, Grant Williams, Art Berman | **23** |
| Single-company promotion | **3** — Midnight Sun (252k, 107k), First Phosphate (104k) |

The titles are things like *"Bill Holter: Massive Inflation Ahead"*, *"Douglas Macgregor: Why
The Iran War Will Restart, Oil to Skyrocket"*, *"Luke Gromen: The Mother of All Supply
Disruptions"*. Gold, silver, oil, the dollar, war — **no tradeable single issuer at all.**

Median views, unmatched: **top 50 = 40,000; bottom 50 = 1,600.** Against a priced
single-company sample whose maximum was **24,421**.

**So the structure is: high views = macro punditry with no company attached; company-specific
promotion = low views.** Widening the ticker list to include Midnight Sun and First Phosphate
would add roughly three events and would not create a high-view single-company sample,
because these channels barely produce one.

### What that means for the attention claim

§19's mechanism requires a **high-reach, single-company** video. Measured across 500 videos
from the five channels both models named, that combination is close to absent: the content
that reaches 40k-250k viewers is a named pundit talking about the gold price, and the content
naming a specific junior reaches 2-13k (§22).

That is stronger than "untested". **The precondition for the mechanism is largely missing from
the corpus the claim was made about.** It remains formally unfalsified — we have not measured
a high-view single-company event because there are almost none to measure — but the reason we
cannot test it is itself evidence against it.

**Fourth instance of the inverse-correlation pattern** (§10 quality vs tradeability, §17
quality vs access, §22 reach vs float): here it is **reach vs company-specificity**. Whatever
attracts a large audience keeps being the thing that detaches the content from a tradeable
security.

### Revised recommendation

Do **not** widen the ticker universe and re-run; the sample it would build does not exist.
If the attention mechanism is to be tested at all, it needs a channel set selected *because*
it publishes high-view single-company content — which the §9 discovery script can now look for
directly, ranking on `median_views` with a single-company title filter, at zero fetch cost.
Absent that, treat attention alpha as unavailable across every sector examined and close the
question.

> **Retracted the same day — see §24.** "The sample does not exist" was too strong, and
> measuring one more channel produced a direct counterexample. The corrected statement is
> that the sample does not exist *inside a ticker universe built from established names*,
> which is a different and much more fixable problem.

---

## 24. The universe was selecting against the phenomenon (2026-07-30)

Prompted by a user-supplied channel — **The Deep Dive** (`@TheDeepDiveCa`), a Canadian
small-cap outlet not surfaced by any research round. Listing only, 100 videos, zero fetches.

| Measure | The Deep Dive | The five §19 channels |
|---|---|---|
| Median views | 1,850 | 2,350-13,000 |
| **Max views** | **252,000** | 4,900-252,000 |
| Median duration | 730s (12 min) | 25-60 min |
| Shorts (<120s) | **0%** | — |
| **Single-company title match** (42-name universe) | **19/100 = 19%** | **16/500 = 3.2%** |

Six times the company-specificity of the previously tested set, no Shorts, and a 12-minute
median that is the cleanest ingest profile of any mining channel measured.

### The counterexample

§23 concluded that high-view single-company content is close to absent. The Deep Dive's two
highest-view videos are:

- **252,000** — *"The Fundamental Building Block for the Next Decade of Energy | DD-On-The-G…"*
- **204,000** — *"This LFP Supply Chain Story Just Got G7 Backing | John Passalacqua — First
  Phosphate"*

That second one is a **named CEO interview about a single company at 204k views**, which is
precisely the combination §23 said the corpus did not contain. And First Phosphate appeared
independently in the §23 unmatched list at 104k on a *different* channel. So high-reach
single-company promotional content exists, is repeatable, and clusters on the same names.

### Why we missed it — the methodological error

The 42-company universe in `yt_promotion_event_study.py` was built from **established
producers and our own holdings**: Cameco, Agnico, Barrick, Kinross, Franco-Nevada, Newmont.

Those companies do not buy investor-relations campaigns. **Paid promotion concentrates on
pre-revenue story juniors** — critical minerals, LFP battery supply chain, phosphate, "G7
backing" — which is exactly the population the universe excluded.

**We built the sample frame out of the companies least likely to exhibit the behaviour we
were trying to measure, then concluded the behaviour was absent.** That is a textbook
sample-frame error and it invalidates §23's negative conclusion (though not its attrition
numbers or its low/mid results, which stand as reported).

### The fix, and the trap in the fix

Build the ticker universe **from the corpus**, not from the portfolio: extract company names
from high-view titles, resolve to tickers, then run the event study on those.

The trap is obvious and must be designed around: choosing the universe by looking at which
videos got views is **selecting on the outcome**, and would manufacture a positive result as
convincingly as §7's lookahead-bias warning. The clean construction is a **split sample** —
define the universe from titles in period A, test events in period B only, and pre-register
the list before looking at any prices. That keeps the discovery honest and is cheap, because
listing costs nothing.

### Also worth noting

- First Phosphate is **CSE-listed (PHOS.CN)**. Verify broker access before building on it —
  CSE is not TSX/TSXV and may not be tradeable in these accounts. If it is not, the finding
  survives as a mechanism but not as a trade.
- The Deep Dive's in-universe matches (First Majestic `AG`, Agnico `AEM.TO` — **held**,
  Seabridge `SA`) top out at 19,000 views, versus 204-252k for the out-of-universe story
  juniors. The reach/company-specificity relationship from §23 holds *within* the channel;
  it just does not mean what §23 said it meant.
- Caption ingestability is **unverified** — the fetch was blocked, the day's quota having
  been spent on §21 and §23. Retry via proxy before adding it as a source.

### Standing lesson

Two conclusions in this document have now been overturned by one additional measurement each
(§21's filter, §23's sample). Both times the error was the same shape: a plausible negative
accepted before checking whether the *instrument* could have detected a positive. The §8
sanity check — "if G​a​m​e​r​s​ ​N​e​x​u​s scores as derived, the heuristic is wrong" — generalises to
**always confirm the measurement can see the thing before reporting that the thing is
absent.**

### Caveats

n=8, no high-view events, seven description demotions, one unpriceable. Mid bucket is n=2.
Do not read the low/mid table as evidence for or against attention alpha.

---

## 25. Complete-exchange universe re-run (2026-07-30)

§24's sample-frame error is fixed by matching titles against **every equity issuer on
TSX, TSXV, and CSE**, not a hand-curated 42. The list is downloaded from public exchange
directories, cached at `web_dashboard/data/canadian_issuers/issuers.json` with
`retrieved_at=2026-07-30` (3,198 equities after dropping ETFs/warrants/preferreds), and
committed so the run is reproducible. Script:
`web_dashboard/scripts/yt_promotion_event_study.py` (default `--universe both`) plus
`canadian_issuer_universe.py`.

Channels: the five §19 promotion channels **plus The Deep Dive**
(`UC04_rUstP7vyLANZ0rJYz_A`). Zero caption fetches. Guardrails unchanged: entry = first
close strictly after publish date; dedupe `(ticker, day)`; high−low spread; day-bucketed
null; `resolve_benchmark()`; pre-event drift t−5→t−1; view buckets from §22.

Matching rules required one adaptation that is *not* sample selection: bare ticker
symbols are matched only as `$CASHTAG`, and single-token sector peels like
"Discovery Mining"→"Discovery" are dropped. Without that, English-word CSE/TSXV tickers
(`MINE`, `PLAN`, `NEWS`, `LONG`, `RISE`) and peeled generics demote almost every
description re-match and false-positive macro titles. Company-name aliases remain the
primary key (§17).

### Attrition — curated-42 vs complete-exchange (same 600 videos)

| Stage | curated-42 | complete-exchange | Δ |
|---|---:|---:|---:|
| Videos listed (6 × 100) | 600 | 600 | — |
| Title matched exactly one | **35** | **223** | **+188** |
| Title matched multiple | 1 | 8 | +7 |
| Title matched none | 564 | 369 | −195 |
| Demoted to multi after description re-match | 25 | 85 | +60 |
| Dates resolved | 10 | **138** | **+128** |
| After (ticker, day) dedupe | 10 | **138** | +128 |
| Usable price history | — | **138** | — |

View buckets after dedupe (exchange): low=122, mid=11, **high (≥50k)=5**.

The sample-frame cost of the curated list was roughly **an order of magnitude** of dated
single-company events (10 → 138), and it had been zeroing the high-view bucket that §22
said the claim needs.

### Tradeability (reported before prices)

| | TSX | TSXV | CSE |
|---|---:|---:|---:|
| All matched events | 37 | 81 | 20 (14.5%) |
| High-view (≥50k) | 0 | 2 | **3 (60%)** |

**Majority of the high-view promotion sample is CSE-listed** (First Phosphate `PHOS.CN`
×3 in the high bucket). If CSE is not accessible in these accounts, this is a §10-style
"signal may exist, untradeable" finding on the exact events the attention claim needs —
stated here, not discovered at the broker later.

Checked against the actual book (§15 snapshot): held listings are **28 `.TO`, 70 US, and
exactly one `.V` (WEB.V) — zero `.CN`.** That is not proof CSE is inaccessible; it may
simply never have been wanted. But no CSE name has ever been held, so **broker access is
unverified for the exchange carrying 60% of the high-view sample.** Worth a two-minute
check in the broker before any further work is spent on this branch.

### High-view numbers (the only cut that tests the claim)

Pre-event drift overall: n=137, mean **−1.11%**, median −1.23% — names are not
systematically running into the video.

| Horizon | low n≈122 mean | mid n=11 mean | **high n=5 mean** | high−low spread |
|---|---:|---:|---:|---:|
| t+1 | −0.38% | −1.30% | **+1.83%** | +2.21% |
| t+2 | +0.11% | −1.29% | +0.07% | −0.03% |
| t+5 | +0.91% | −4.38% | −0.62% | −1.53% |
| t+21 | −4.46% | +1.80% | **−6.81%** (n=4) | −2.35% |

Abnormal volume (entry / 20-session median): low 1.87×, mid 2.08×, high 1.52× — no
retail volume spike on the high-view tail relative to low.

High-view inventory (all priced):

| Date | Ticker | Views | Channel | t+1 excess |
|---|---|---:|---|---:|
| 2026-05-16 | MMA.V | 252,939 | Mining Stock Education | −2.22% |
| 2026-06-24 | PHOS.CN | 204,391 | The Deep Dive | −3.31% |
| 2026-07-10 | MMA.V | 108,154 | Mining Stock Education | −0.19% |
| 2026-06-19 | PHOS.CN | 104,863 | Mining Stock Education | −2.90% |
| 2026-05-01 | PHOS.CN | 62,670 | The Deep Dive | **+17.77%** |

### Dose-response: the test §22 specified, and it fails

§22 set the design principle before any of this ran: *"if the attention mechanism is real,
effect size scales with viewers."* That is the check the high-view inventory is for, and it
is more informative at n=5 than the mean, because it uses the ordering rather than the level.

Sorting the five events by views and reading t+1:

| Views | Ticker | t+1 |
|---:|---|---:|
| 252,939 | MMA.V | −2.22% |
| 204,391 | PHOS.CN | −3.31% |
| 108,154 | MMA.V | −0.19% |
| 104,863 | PHOS.CN | −2.90% |
| **62,670** | PHOS.CN | **+17.77%** |

**The single positive event is the lowest-view event.** And *within* each ticker — which
controls for the security entirely — the relationship is monotonic and **inverted**:

- `PHOS.CN`: 62.7k → **+17.8%**, 104.9k → −2.9%, 204.4k → −3.3%
- `MMA.V`: 108.2k → −0.2%, 252.9k → −2.2%

More viewers, worse return, in both names, with no exceptions. That is the opposite of the
claimed mechanism, and it is not a level comparison that a benchmark choice or an outlier can
explain away.

n=5 proves nothing on its own. But it means the +17.77% print cannot be attributed to the
video without also explaining why the same ticker's two *larger* audiences produced negative
returns. The parsimonious reading is that +17.77% is ordinary micro-cap volatility on a CSE
name, and that it is carrying the entire positive mean.

**This moves the verdict from "inconclusive" toward "no support found"** — still not a clean
null, because n=5 cannot deliver one, but the one piece of evidence that looked supportive
does not survive the dose-response check that was specified in advance.

### What survives

- **The sample frame was the bug.** Complete-exchange matching recovers the high-view
  single-company events §23/§24 said were missing (Midnight Sun, First Phosphate), and
  The Deep Dive supplies two of the five high-view rows.
- **High-view n=5 is directional only.** Mean t+1 of +1.83% is **outlier-driven**:
  median t+1 is **−2.22%**, and four of five high-view events are flat-to-negative at
  t+1. The fading into t+21 (−6.81%) looks like reverse in the mean curve but is not a
  confirmatory spike-then-reverse result at this n. **INCONCLUSIVE / directional — not
  a confirmed attention-alpha edge, not a clean null either.**
- **CSE concentration on the high-view tail** is a first-order tradeability result
  independent of the return numbers.
- Low/mid rows (n=133) remain **untestable for attention alpha** per §22 — reported only
  as context. Do not read the low bucket as a null on the claim.
- Issuer cache + parser/matcher tests live under
  `tests/test_canadian_issuer_universe.py`. Refresh:
  `python web_dashboard/scripts/canadian_issuer_universe.py --refresh`.

### Caveats

Description demotion still costs 85/223 exchange title singles (channel footers name
many issuers). Matching deliberately ignores bare English-word tickers; a title that
only says `PHOS` without "First Phosphate" or `$PHOS` will miss — acceptable given §17
(names dominate titles). Dual-listed US symbols in the old curated list (e.g. `DNN`) are
not in the Canadian directory; Canadian aliases (e.g. Denison as `DML.TO` if present)
cover name hits. No threshold or channel tuning after seeing prices.

## 26. The corpus covers 8% of the book. Search reaches the rest — but not by view count
## (2026-08-02)

The ingest pipeline went live (13 sources, cursors sealed, ~17 fetches/day). Before
spending 30 days accumulating toward the K5 source-ROI read, we measured what that read
would actually be computed over. It would have come back "no value," and the reason would
have been the sample frame, not YouTube.

### 26.1 The measurement

Production holdings: **100 positions** across TFSA / RRSP Lance Webull / Project Chimera.
Enabled-source `expected_tickers`, unioned: **15 symbols**.

| Set | Overlap with holdings |
|---|---|
| Tickers appearing in the 9-row corpus | 7 / 15 (`AMD CEG META MSFT MU NVDA QCOM`) |
| Seed tickers across all 13 enabled sources | 8 / 15 (`AEM.TO AMAT AMD ASML NVDA QCOM TSM TXN`) |
| **Holdings with any possible coverage** | **8 / 100 = 8%** |

Every enabled source but one is a semiconductor or PC-hardware channel. The book is
uranium and nuclear (`CCO.TO HURA.TO GLO.TO URNJ URNM LEU OKLO`), gold and base metals
(`AEM.TO GMIN.TO XGD.TO TECK.B GLCC.TO`), Canadian rails, pipelines and utilities
(`CNR.TO ENB.TO TRP.TO FTS.TO KEY.TO RY.TO`), grid and power equipment (`GEV VRT ETN`),
and broad ETFs. **92% of it has no path to coverage from the current allowlist.**

This is §24's sample-frame error a second time, in the opposite direction. There we built
a *ticker universe* that excluded the phenomenon; here we built a *source list* that
excludes the portfolio. Both times the pipeline was sound and the frame was wrong. The
generalization worth keeping: **whenever a result is about to be computed, check what it
is computed over before trusting the answer, not after.**

Note also that `CEG` and `TLN` — power names, the sector §17 rejected as a caption sector
— entered the corpus organically through *"How AI Datacenters Eat the World"* on a tech
channel. Coverage is topic-shaped, not sector-list-shaped. Channel curation is a blunt
instrument for aiming at a book.

### 26.2 Search reaches the whole book (10 / 10 probes)

`list_search_videos` is listing, not caption fetch, so this cost zero quota (§14). Ten
uncovered holdings, queried by *company name* rather than symbol (§17: titles say
"Cameco", not `CCO.TO`):

Every probe returned hits — including `GMIN.TO` (G Mining Ventures), a name no channel in
the allowlist would ever mention. The push model cannot reach these; the pull model can.

### 26.3 But ranking by views selects for noise — the inverse correlation, 5th firing

Sorting each probe's hits by view count returns almost pure junk:

| Query | Top result by views | Views | Relevant? |
|---|---|---|---|
| Shopify | "I Tried AI Dropshipping For 7 Days" | 17,670,827 | no |
| Cameco uranium | "How It's Made — Uranium Part 1" | 5,251,091 | no |
| Oklo nuclear | "Earth's Two-Billion-Year-Old Nuclear Reactor" | 3,050,035 | no |
| Eaton electrical | "Current Transformers (CT) \| Eaton PSEC" | 619,443 | no (vendor training) |
| Vertiv | "VERTICAL \| LEV vs NRG — VCT Americas" | 111,027 | no (**esports name collision**) |

The genuinely relevant hits are the *low*-view ones — Centrus CEO interview (4,604), the
Teck / Anglo $70B tie-up (4,733), Enbridge CEO on tariffs (6,716), G Mining `TSX:GMIN`
(8,349). The gap is two to three orders of magnitude.

So the inverse-correlation regularity fires a **fifth** time (after §10 quality vs
tradeability, §17 quality vs access, §22 reach vs float, §23/§24 reach vs
company-specificity): **relevance vs views, on search**. High view counts on a
company-name query mean the query matched something *other* than the company — a
tutorial, a documentary, a training video, or an unrelated brand.

This has a direct consequence for code already written: the `no_audience(median=N views)`
structural reject in `scripts/yt_discover_channels.py` is correct for finding *channels*
with retail reach (the ATTENTION mechanism, §19/§22) and **actively harmful** for finding
*videos about a holding* (the INFORMATION mechanism). The two uses of the corpus (§20)
need opposite view-count filters. Do not share one ranker between them.

### 26.4 What this implies

Adding mining/uranium *channels* is the wrong repair: §17 and §19 already rejected those
sectors on access and disclosure-preemption grounds, and §26.1 shows channel curation
aims poorly at a 100-position book regardless. The repair is **K8 pull retrieval**
(PHASE_K_TREND_LAYER_PLAN.md §3): query per holding on a cadence, filter by
ticker/company confirmation in the transcript, and rank by relevance with views used —
if at all — only as a tiebreaker *within* already-confirmed hits.

Kill criterion, pre-registered: if per-holding search cannot produce ≥1 confirmed
company-specific video per month for at least 30 of the 100 positions, the pull model is
no better aimed than the push model and Phase K reverts to a pure trend/sentiment layer
(§20) with no per-security ambition.
