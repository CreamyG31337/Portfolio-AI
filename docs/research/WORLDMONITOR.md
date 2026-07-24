# WorldMonitor research notes

**Upstream:** [koala73/worldmonitor](https://github.com/koala73/worldmonitor)  
**Local clone (gitignored):** `.research_worldmonitor/`  
**Reviewed:** 2026-07-20; pipeline audit follow-up: 2026-07-20  
**License:** platform **AGPL-3.0**; official SDKs/CLI **MIT**

This note captures what WorldMonitor is, what each major subsystem does, and what (if anything) is worth borrowing for the LLM Micro-Cap trading bot. It is our analysis — not a fork plan.

---

## One-line verdict

Impressive global-intel dashboard with a finance variant. For us: **borrow ideas/techniques (clean-room reimplemented) + optionally call their MIT SDK/MCP for macro context**. Do **not** merge their AGPL TypeScript into our app. Most equity/intel surface we already have; the real gaps are **FRED/macro series**, an optional **equity Fear & Greed** feed, and — the standout find after auditing our actual pipeline — a **near-duplicate news/story-dedup algorithm** (`shared/story-identity.js`) that is materially better engineered than anything we have and maps onto a real, confirmed gap in our news collection code (see below).

---

## What it is

Real-time situational-awareness SPA that fuses geopolitics, military/AIS, climate, news, and markets onto a dual map (deck.gl + globe.gl). Six hostname variants from one codebase (`world`, `tech`, `finance`, `commodity`, `happy`, `energy`). Also ships:

- Vercel Edge Functions + Railway seed loops + Upstash Redis
- Proto/RPC contracts (sebuf) → OpenAPI + MCP
- Desktop app (Tauri 2)
- Local-first AI (Ollama → OpenRouter → Groq → browser Transformers.js)
- npm CLI + Python/Go/Ruby SDKs

**Clone size:** ~4.4k files. Heavy TypeScript frontend; market/news logic lives under `server/worldmonitor/<domain>/v1/`.

---

## Architecture (how data moves)

```
Browser / Desktop panels
        │  GET /api/{domain}/v1/...
        ▼
Vercel Edge gateways (proto RPCs)
        │  mostly Redis cache reads
        ▼
Upstash Redis  ◄── Railway seed scripts (Yahoo, Finnhub, FRED, RSS, …)
        │
   65+ upstream providers
```

Important split:

| Path | Role |
|------|------|
| **Seed scripts** (`scripts/seed-*.mjs`, AIS relay) | Expensive upstream fetches, composite scores |
| **RPC handlers** (`server/worldmonitor/*/v1/`) | Thin cached readers (+ a few live compute paths) |
| **Browser workers** (`src/workers/`) | Jaccard clustering, correlation, ONNX ML |
| **Premium stock analysis** | Exception: live Yahoo + news search + LLM in `analyze-stock.ts` |

Bootstrap hydrates the SPA in fast/slow Redis key tiers so first paint does not hammer origin.

---

## Domain map (what stuff does)

Server domains under `.research_worldmonitor/server/worldmonitor/`:

| Domain | What it does | Micro-cap relevance |
|--------|--------------|---------------------|
| **market** | Quotes, sectors, crypto, commodities, ETF flows, F&G, COT, earnings, insider Form 4, **premium analyze-stock** | High (selective) |
| **economic** | FRED, macro radar, stress index, BIS/ECB/EIA, calendars | **High — our gap** |
| **news** | 500+ RSS feeds by variant, classify, digest, summarize | Medium (we already RSS+Ollama) |
| **intelligence** | CII risk scores, strategic risk | Low (geo Tier-1 countries) |
| **prediction** | Polymarket-style contracts | Low–medium (event hedges) |
| **conflict / military / maritime / aviation / cyber / …** | OSINT map layers | Low for US micro-caps |
| **trade / supply-chain / sanctions** | Tariffs, chokepoints, sanctions | Occasional ticker context |
| **forecast / scenario / leads** | LLM deduction & forecasts | Idea patterns only |

### Market RPCs (finance variant)

Handler: `server/worldmonitor/market/v1/handler.ts`  
Catalog: `docs/finance-data.mdx`

| Capability | Source pattern | Notes |
|------------|----------------|-------|
| Equity/index quotes | Finnhub + Yahoo (seeded) | Watchlist-style |
| Sector summary | Finnhub sector ETFs | Heatmap |
| Crypto / DeFi / AI tokens | CoinGecko | Skip for us |
| Commodity quotes | Yahoo | Optional macro |
| BTC ETF flows | Yahoo heuristic (`vol × price × dir × 0.1`) | Not official creations |
| Fear & Greed | Redis from `seed-fear-greed.mjs` | Equity-macro blend (see below) |
| COT positioning | Seeded | Futures positioning |
| Earnings calendar | Seeded | Nice-to-have |
| Insider transactions | Finnhub Form 4 | **P/S-only conviction filter** |
| `analyze-stock` | Live Yahoo + news APIs + LLM | PRO; ~59KB technical+AI pipeline |

### Premium `analyze-stock` (what the big file does)

Path: `server/worldmonitor/market/v1/analyze-stock.ts`

1. Yahoo daily candles → technicals (SMA 5/10/20/60, MACD, RSI 6/12/24, volume patterns, S/R)
2. Composite `signalScore` 0–100 → Strong buy … Strong sell
3. Optional headlines via Tavily → Brave → SerpAPI → Google News RSS
4. LLM overlay (`callLlm`) or deterministic fallback
5. Yahoo `quoteSummary` for analyst targets
6. Persist snapshot with engine version `v2` (replayable history / backtest of *prior signals*)

Useful **idea**: versioned analysis ledger + backtest of stored signals. Not a drop-in for micro-caps (Yahoo/Finnhub thin on tiny names; AGPL code).

### Macro Market Radar (7 signals)

Computed in `scripts/seed-economy.mjs` → Redis → `economic/v1/get-macro-signals.ts`.  
Verdict: ≥57% of known signals bullish → **BUY**, else **CASH**.

| Signal | Bullish when |
|--------|--------------|
| Liquidity (JPY/USD 30d ROC) | ROC ≥ −2% |
| Flow structure (BTC 5d vs QQQ 5d) | \|gap\| ≤ 5% |
| Macro regime (QQQ 20d vs XLP 20d) | QQQ > XLP (risk-on) |
| Technical trend (BTC vs SMA50+VWAP) | Above both |
| Hash rate (mempool) | 30d change > 3% |
| Price momentum (Mayer = BTC/SMA200) | > 1.0 |
| Fear & Greed | > 50 |

**Skew:** crypto + mega-cap risk-on. Poor primary signal for US micro-caps. Docs still mention a “Mining Cost > $60K” signal; seed code uses Mayer Multiple instead.

### Fear & Greed 2.0 (equity-macro)

`scripts/seed-fear-greed.mjs` — multi-component blend (CNN FG, AAII, VIX term, put/call, SPX MAs, sector RSI, M2/WALCL/SOFR, credit OAS, Fed/curve/UNRATE, gold/TLT/DXY). Closer to what we’d want than the crypto radar.

### Economic stress composite

Six FRED-ish components in `seed-economy.mjs` (weights): T10Y2Y 0.20, T10Y3M 0.15, VIX 0.20, STLFSI4 0.20, GSCPI 0.15, ICSA 0.10. Labels Low → Critical. **This is the closest match to a real gap in our stack.**

Confirmed after checking: no FRED/macro-stress signal exists anywhere in our repo today — `market_daily_brief.regime_json` (normalized in [`market_regime_normalization.py`](../../web_dashboard/market_regime_normalization.py)) gets `risk_regime`/`volatility_state`/`breadth_proxy` purely from LLM narrative judgment, with nothing quantitative backing it. Also: `pandas-datareader` is **already in `requirements.txt`, unused** — it can pull FRED series (e.g. `DataReader('T10Y2Y', 'fred')`) via the free CSV endpoint with no API key, so this composite is cheaper to stand up than "go get a FRED SDK" implies. Slots into the existing `regime_json` contract without new schema.

### Insider Form 4 filter (borrow the idea)

`server/worldmonitor/market/v1/get-insider-transactions.ts`:

- Count **only** open-market `P` / `S` toward buy/sell dollar totals
- Still list `M, A, D, F` (exercise/grant/tax) but **value = 0**
- ~6 month window; top 20; cache 24h

We already scrape/show insider trades (`jobs_insiders.py`). Applying this conviction filter would clean noise without needing WorldMonitor.

**Correction after checking our code (2026-07-20):** this is a bigger lift for us than it sounds. WorldMonitor's filter works because they parse **raw SEC Form 4 XML**, which carries the real transaction code (`P`, `S`, `A`, `M`, `G`, `D`, `F`). Our [`jobs_insiders.py`](../../web_dashboard/scheduler/jobs_insiders.py) scrapes a third-party site (quiverquant) whose page has **already collapsed everything into `"Purchase"`/`"Sale"`/`"Unknown"` text** before it reaches us (see the `transactionCode` handling around line 411) — the raw code is gone, so there's nothing left to filter on. A P/S-only conviction filter can't be bolted onto the current scrape.

The real prerequisite already half-exists: [`sec_form4_poc.py`](../../web_dashboard/scheduler/sec_form4_poc.py) is a working proof-of-concept that pulls raw Form 4 XML straight from SEC EDGAR and does retain the true transaction code. Finishing that pipeline (replacing or supplementing the quiverquant scrape) is the actual unlock — the P/S filter becomes a one-line addition once that lands, not a standalone task.

### News + AI briefing

| Piece | Location | Behavior |
|-------|----------|----------|
| Feed lists | `news/v1/_feeds.ts` | Variant-specific (finance → CNBC, Yahoo Finance, Seeking Alpha, …) |
| Digest | `list-feed-digest.ts` | RSS fetch, keyword classify, story identity |
| Clustering | `src/services/analysis-core.ts` | Token Jaccard; threshold **0.5** (brief dedup **0.55**) |
| Summarize | `news/v1/summarize-article.ts` + `server/_shared/llm.ts` | Provider chain: **ollama → openrouter → groq → generic** |
| Cache key | `src/utils/summary-cache-key.ts` | `summary:v8:{mode}:{variant}:{lang}:{hash}…` |

Docs sometimes say Jaccard >0.6 and Groq-before-OpenRouter — **code thresholds/order above are authoritative**.

The finance-variant feed catalog itself (`_feeds.ts` `finance` block: markets, forex, bonds, commodities, crypto, centralbanks, economic, ipo, derivatives, fintech, `fin-regulation`, institutional, analysis, gccNews) is broad but **mega-cap/macro-flavored, not micro-cap** — CNBC, Yahoo Finance, Seeking Alpha, Fed press releases, SEC press releases, plus dozens of Google-News-proxy queries for crypto/PE/hedge-fund/GCC coverage. None of it targets small caps specifically, same conclusion the original review reached. The URLs themselves are not IP and are fine to borrow piecemeal if feed breadth turns out to be thin on our side (see below).

#### Story dedup / corroboration (`shared/story-identity.js`) — the standout piece, and a confirmed real gap for us

This is the one module in the whole clone that reads as genuinely mature, incident-hardened engineering rather than a feature list — worth reimplementing the *technique* directly (pure algorithm, dependency-free, no AGPL handler logic, no data). It answers "are these two headlines the same story?" with:

1. **Dual-view feature-hashed lexical vectors** — word tokens (weight 2.0) + word bigrams (1.5, order-sensitive) + char 4-grams (1.0, morphology fuzz) + char bigrams for non-ASCII tokens, hashed (FNV-1a) into 512 dims, L2-normalized. Two views: uniform weights, and entity-boosted (capitalized tokens ×3, numeric tokens ×2) — a pair only counts as the same story when **both views agree** (similarity = min of the two cosines). This is what separates "Turkey hikes rates to 50%" from "Argentina hikes rates to 50%," which flat bag-of-words would conflate.
2. **Containment rescue**: if one title's tokens are ≥90% contained in the other's (≥4 tokens on the smaller side), force-match — catches severely truncated wire copies that cosine alone would miss.
3. **Clustering via inverted-index candidate generation + union-find** (connected components, not greedy first-seed) — deterministic regardless of feed arrival order, bounded cost via a max-bucket cutoff for hot tokens.
4. **Corroboration count** — number of *distinct sources* reporting the same clustered story. Tuned threshold **0.615**, validated against a labeled positive/negative pair test set.

**Why this matters for us specifically:** I checked our actual pipeline against this and our dedup is exact-match only, in two places:
- [`web_dashboard/scheduler/rss_feed_workers.py:58`](../../web_dashboard/scheduler/rss_feed_workers.py) — `article_exists(url)`, literal URL match
- [`web_dashboard/scheduler/jobs_common.py:58`](../../web_dashboard/scheduler/jobs_common.py) — `claim_recent_summary_input()`, SHA-256 of the *exact* article text, 6h TTL

Neither catches "same story, different wording, different URL" — and our architecture makes that collision routine: `market_research_job` runs rotating SearXNG keyword searches ([`jobs_research.py:166`](../../web_dashboard/scheduler/jobs_research.py)) on an **hourly rotation**, independently of `rss_feed_ingest_job` pulling configured feeds. When both surface the same catalyst (e.g. a microcap earnings beat picked up by a Google News hit *and* an RSS feed), we pay for two full `trafilatura` extractions and two full Ollama summarizations, and end up with near-duplicate rows in `research_articles` that downstream meta-analysis treats as independent evidence — silently inflating apparent conviction on a ticker without any of the layers knowing it's the same story twice.

**Proposed fix (not yet built):** port the vectorize → cosine → cluster technique into a small Python module (~150 lines, no new dependency — just hashing + arrays, same as the JS original). Before extraction/summarization, check a new article's title against a rolling window (last ~48–96h) of recently-processed story vectors, scoped by ticker or general-market bucket. On a match: skip re-extraction/re-summarization but increment a `corroboration_count` on the existing article instead of inserting a near-dupe. Then feed `corroboration_count` into [`calculate_relevance_score`](../../web_dashboard/scheduler/jobs_common.py) (currently just `tickers` + `owned_tickers`, line 15) as a conviction multiplier — **3 independent outlets covering the same small-cap catalyst is a stronger tell than 1**, and today we have no way to express that distinction at all. This isn't just cleanup — corroboration count would be a genuinely new signal, not present anywhere in our stack today.

Their `_classifier.ts` (threat-level keyword classifier: nuclear strike / coup / invasion / etc.) is pure geo-military and has zero relevance here — skip it entirely, don't be tempted by proximity to the dedup module.

**Feed breadth — confirmed (2026-07-20):** the real seed (`database/test_seed_research.sql`, matches the test fixture) has exactly **6 feeds**: StockTwits, CNBC Finance, Investing.com Breaking, Fortune Finance, one Google News AI-stocks query, Hunterbrook. Adding a feed is trivial — one `INSERT` into `rss_feeds` (see `web_dashboard/scripts/add_research_feed.py` for the pattern), no code changes, since `rss_feed_ingest_job` reads every enabled row dynamically.

Diffed against WorldMonitor's finance catalog (`_feeds.ts`) — **and cross-checked against what's already flowing in opportunistically via SearXNG** (`docs/source_roi_report_results.json` scores domains by contribution, so it doubles as a "what are we already getting" check):

**Already covered, no action needed:** `finance.yahoo.com` is our **top-scored source-ROI domain** (299.67 in one bucket) and `seekingalpha.com` also scores (49.2) — both arrive via SearXNG search results even without a dedicated RSS subscription. Adding them as standalone feeds would mostly just increase how often the *same* domains show up, which raises the near-duplicate rate rather than adding new signal — a good argument for landing the story-dedup work (above) before adding feed volume from sources we already partially have.

**Confirmed genuinely missing** (no RSS feed, no domain-health entry, no source-ROI score — nothing):
- **SEC press releases** — `https://www.sec.gov/news/pressreleases.rss` (regulatory/enforcement radar — halts, fraud charges, rule changes can directly hit a held microcap)
- **Federal Reserve press releases** — `https://www.federalreserve.gov/feeds/press_all.xml` (macro regime signal, pairs with the FRED stress-composite work above)

*Google News proxy queries (same `gn()` pattern our `jobs_research.py` rotating queries already use) — checked against the existing 10-query rotation, no overlap:*
- **Financial Regulation** — `(SEC OR CFTC OR FINRA OR FCA) regulation OR enforcement`
- **IPO News** — `(IPO OR "initial public offering" OR "stock market debut")` — new listings are new microcaps
- **Economic Data** — `(CPI OR inflation OR GDP OR "economic data" OR "jobs report")` — cheap headline-level macro pulse between FRED pulls

*Skip:* everything else in their finance catalog is mega-cap/macro noise for a microcap fund — forex, bonds, derivatives/options, institutional (hedge fund/PE/sovereign wealth), fintech, GCC regional, and the entire crypto block (17 feeds). MarketWatch / Reuters Business also skipped — likely overlaps with what SearXNG's rotation already surfaces. Same conclusion the original review reached.

### Correlation / geo convergence

| System | Idea | For us |
|--------|------|--------|
| Geo convergence (`src/services/geo-convergence.ts`) | 1° cells; ≥3 of protest/flight/vessel/quake in 24h | Geo OSINT — skip |
| Cross-stream correlation (`analysis-core` + worker) | `silent_divergence`, `explained_market_move`, prediction-leads-news, etc.; confidence ≥0.6 | **Conceptual peer** to meta analysis “multiple independent streams” |

### MCP + SDK

- MCP: `https://worldmonitor.app/mcp` — `tools/list` public; `tools/call` needs Pro OAuth or `X-WorldMonitor-Key`
- Pro OAuth: ~**50 quota calls / UTC day** (tight for agent loops)
- Equity-useful tools: `get_market_data`, `get_economic_data`, `get_news_intelligence`, `get_world_brief`, `get_prediction_markets`, country risk/brief, energy/tariffs
- **Not** first-class MCP: `analyze-stock`, insider Form 4 (premium REST)
- Python: `pip install worldmonitor-sdk` (**MIT**, stdlib-only) — preferred integration path

---

## Overlap with our bot

| WorldMonitor thing | Our equivalent | Gap? |
|--------------------|----------------|------|
| News aggregation + AI briefs | RSS / SearXNG → `research_articles`; `market_daily_brief` | No — optional feed URLs only |
| Market regime | `market_daily_brief` + `market_regime_normalization.py` (benchmarks) | Partial — no FRED |
| Fear & Greed index | Ticker technical `FearRiskSignal` only | **Yes** (index-level) |
| FRED / stress / curve | — | **Yes** |
| Congress / politician trades | Mature congress + executive stack | No |
| Insider trades | `insider_trades` + Yahoo SEDI | Filter quality only |
| ETF flow / holdings | ETF watchtower → group AI → sector meta | No (different product) |
| Layered synthesis | Meta analysis (market → sector → ticker) | No — ours is the north star |
| Social / retail sentiment | StockTwits/Reddit + Ollama Granite | Different surface |
| Ollama-first LLM | Ubiquitous | Shared pattern |
| Geo / military / AIS map | — | Out of scope |

**Highest-ROI borrows** (reordered 2026-07-20 after auditing our actual pipeline)

1. **News story-dedup + corroboration count** — port `shared/story-identity.js`'s technique (hashed feature vectors, dual-view cosine, union-find clustering) into Python. Confirmed real gap: our dedup is exact-match only (URL / exact text hash), so same-story-different-wording articles from SearXNG and RSS both get fully re-extracted and re-summarized, and pollute `research_articles` as fake-independent evidence. Corroboration count is also a genuinely new signal to feed `calculate_relevance_score` — not just cleanup. See detailed writeup above under "News + AI briefing."
2. Optional **FRED stress / equity F&G** collector → enrich `market_daily_brief.regime_json`. `pandas-datareader` is already installed and unused, so the FRED half is cheaper than it first looked.
3. Finish **`sec_form4_poc.py`** (raw SEC Form 4 XML ingestion) — prerequisite for a real P/S Form 4 conviction filter; our current insider scrape has already lost the raw transaction code, so the filter can't be bolted onto it as-is.
4. Optional **`worldmonitor-sdk`** for macro/news context only (cache aggressively; respect MCP quota) — lowest priority; #1 and #2 get the same value in-house with no external dependency or quota limit.

### What our own stack already does well (confirmed 2026-07-20)

Auditing WorldMonitor surfaced a few things we already have that either match or exceed their equivalent — worth naming so we don't accidentally "borrow" something we've already solved:

- **Signal replay / backtest ledger** — WorldMonitor's `analyze-stock.ts` persists a versioned snapshot for later backtesting (flagged in the original review as a "useful idea"). We already have this and it's more developed: [`track_record_service.py`](../../web_dashboard/track_record_service.py) computes hit-rate, excess-return, and **confidence-band calibration** from `stance_outcomes` (ROADMAP §2.4 / Phase H1 source-ROI) — i.e. we don't just replay past calls, we're already working toward *down-weighting noisy sources* based on their track record, which is further than WorldMonitor's version goes.
- **Layered market → sector → ticker synthesis** — `meta_analysis_service.py` + `sector_meta_analysis_service.py` + `ticker_meta_analysis` is explicitly the "north star" per `docs/meta_analysis_roadmap.md`, and it's shipped (Phases 1–3). WorldMonitor's cross-stream correlation (`silent_divergence`, `explained_market_move` in `analysis-core.ts`) is a conceptual cousin but stays at "flag an interesting pattern" — ours is built to produce an actual stance with drivers/contradictions/freshness a human can act on.
- **Congress + executive trades stack** — mature and specific to US political trading disclosures; WorldMonitor has no equivalent at all (it's out of scope for their product).
- **Insider trades with a Canadian leg** — `insider_trades` (SEC Form 4 via scrape) *and* `yahoo_sedi_insider_service.py` (Canadian SEDI filings). WorldMonitor is US-only.
- **Ticker-level fear/risk composite** — [`fear_risk_signal.py`](../../web_dashboard/signals/fear_risk_signal.py) already fuses volatility spike, drawdown, volume anomaly, and price-action risk into one 0–100 score with actionable recommendations (SAFE/CAUTION/RISKY/AVOID). What we're missing is the *index-level* (market-wide) equivalent WorldMonitor has via Fear & Greed 2.0 — see the FRED/F&G borrow above — not the per-ticker mechanic itself.
- **ETF holdings → group AI → sector meta pipeline** (ETF Watchtower) — a genuinely different product from WorldMonitor's ETF flow tracking, tailored to inferring sector rotation from what funds are actually buying/selling rather than price-based flow proxies.

**Do not**

- Fork the SPA or copy AGPL handlers into the repo  
- Use BTC Market Radar as a micro-cap BUY/CASH gate  
- Stand up a second meta-analysis stack

---

## License / legal

| Layer | License | Safe use |
|-------|---------|----------|
| Clone under `.research_worldmonitor/` | AGPL-3.0 | Read / learn locally; keep gitignored |
| Porting their TS engines into our product | AGPL | Would infect network service — avoid |
| `worldmonitor-sdk` / CLI | MIT | OK to depend on |
| Algorithms / thresholds as ideas | — | Reimplement clean-room |

---

## Graphify: should we index it as a different project?

**Yes — as a separate graphify project if we keep digging into their code. No — do not merge it into the trading-bot graph.**

| Option | Recommendation |
|--------|----------------|
| Merge WM into `LLM-Micro-Cap-trading-bot` graph | **No.** ~4k unrelated TS files would drown communities, pollute `query_graph`, and mix AGPL reference code with our product graph. |
| Separate graphify project (e.g. `%USERPROFILE%\graphify\worldmonitor\`) | **Yes, optional.** Use when you need `query` / `path` / MCP over *their* tree. Point a second Cursor MCP entry at that `graph.json`. |
| Docs-only (this file) | **Enough for decisions.** Most “what should we borrow?” answers live here; graphify helps file-level navigation, not product strategy. |
| Graphify the clone *inside* `.research_worldmonitor/graphify-out` | Fine for local browse; do **not** point the trading-bot MCP at it. |

Suggested workflow if we go deeper later:

```powershell
# From outside OneDrive / fixed install path (same pattern as trading-bot)
cd $env:USERPROFILE\graphify
# graphify the clone (AST-only), write graph.json under worldmonitor\
graphify ".research path or copy" --no-viz
# Add a second MCP server in mcp.json pointing at that graph.json
```

Do **not** run `graphify update .` from the trading-bot root expecting it to absorb `.research_worldmonitor` — that folder is intentionally ignored for git and should stay out of our product graph.

---

## Local paths

| Item | Path |
|------|------|
| Clone | `.research_worldmonitor/` (gitignored via `.research_*/`) |
| Their architecture docs | `.research_worldmonitor/ARCHITECTURE.md`, `docs/*.mdx` |
| Market handlers | `.research_worldmonitor/server/worldmonitor/market/v1/` |
| Economic seeds | `.research_worldmonitor/scripts/seed-economy.mjs`, `seed-fear-greed.mjs` |
| This note | `docs/research/WORLDMONITOR.md` |

---

## Suggested next experiments

1. **Build the story-dedup module** (see "News + AI briefing" above) and wire it into both `market_research_job` and `rss_feed_ingest_job`; backfill-check how many existing `research_articles` rows would have clustered, as a sanity check on how big the problem actually is
2. Spike a FRED stress row (`pandas-datareader`, no new dependency) into `market_daily_brief` inputs — compare narrative quality for one week
3. Check the real `rss_feeds` table row count/breadth in prod (the 4-feed count found is from a test fixture, not confirmed live state)
4. Scope finishing `sec_form4_poc.py` → raw Form 4 ingestion; only then prototype the P/S conviction filter on a TEST fund insider sample
5. `npx worldmonitor tools` — list MCP tools; try `get_economic_data` / `get_market_data` without burning a full Pro day, lowest priority
6. Only then consider a second graphify MCP for WorldMonitor if file-level exploration is still needed
