# AI Summaries — Research & Strategy Document

> **Purpose:** Think carefully about *what* to build before committing to an implementation.  
> The goal is not to display more text on screen. The goal is to help the user make better  
> trading decisions, or to enable the system to make better automated decisions.

---

## 1. The Core Question

The system already generates a significant amount of per-ticker AI analysis:
- `ticker_analysis` — LLM-generated stance, entry zone, target, stop loss, catalysts, risks
- `ticker_meta_analysis` — second-pass synthesis reconciling contradictions
- `signal_analysis` — technical ensemble (structure + timing + fear/risk + momentum + fundamentals)
- `social_sentiment_analysis` — AI-labeled sentiment from StockTwits/Reddit
- `congress_trades_analysis` — conflict score per congressional trade
- `action_queue_ai_review` — AI verdict on whether a signal is well-supported
- `market_daily_brief` — daily macro regime narrative

So the question is: **what does a layered summary system add that does not already exist?**

The honest answer is: the existing analyses are **per-source and per-ticker in isolation**. None of them answer the questions the user actually faces each day:

1. **"What changed since yesterday?"** — Not what the system thinks in aggregate, but specifically what new information arrived and what it means for my positions.
2. **"Given everything I know, what should I do today?"** — A cross-fund, cross-source, time-sensitive recommendation.
3. **"Why is this position underperforming, and is the thesis still intact?"** — Root-cause against original thesis, not just latest price.
4. **"Where is the risk concentrated right now?"** — Not per-ticker risk, but correlated risk across the portfolio.
5. **"What am I not seeing?"** — Tickers on the watchlist that are heating up, or sources that are flagging something the top-level action queue hasn't surfaced.

These are the questions worth designing for. An AI summary layer is only valuable if it helps answer one of them better than the user can today by manually reading the existing outputs.

---

## 2. Inventory of Available Data (What We Have)

### 2a. Portfolio-Level Data (Supabase)
| Data | Freshness | Notes |
|------|-----------|-------|
| Current positions (holdings, cost basis, market value) | ~15 min via `update_portfolio_prices` | Per-fund |
| Trade log | Real-time | Manual entry |
| Cash balances | Manual | Per-fund |
| Performance metrics (daily P&L, vs benchmark) | Daily | `performance_metrics` table |
| Allocation breakdown | Derived from positions | Sector, asset class |

### 2b. Per-Ticker Analysis (PostgreSQL Research DB)
| Data | Freshness | Notes |
|------|-----------|-------|
| Technical signals (structure, timing, fear/risk, momentum) | Every ~4h via `signal_scan` | `signal_analysis` table |
| Primary AI analysis (thesis, stance, levels) | Low frequency (hours/days) | `ticker_analysis`; expensive LLM job |
| Meta-analysis (synthesis, contradiction reconciliation) | After primary analysis | `ticker_meta_analysis` |
| Social sentiment AI | Every ~1h | `social_sentiment_analysis` |
| Congress trades + conflict scores | Every ~6h | `congress_trades_analysis` |
| Insider trades | Daily | Raw trades in DB |
| Research articles + sentiment | Every ~3–6h | `research_articles` |
| Fundamentals | Daily | `securities` + yfinance |
| Action queue AI review | Daily (nightly) | `action_queue_ai_review` |

### 2c. Macro/Market Data
| Data | Freshness | Notes |
|------|-----------|-------|
| Market daily brief (regime) | Daily | `market_daily_brief` |
| Benchmark performance (SPY, QQQ, RUT, VTI) | ~30 min | `benchmark_data` |
| Commodities (gold, silver, oil, nat gas, copper, uranium, lithium) | ~30 min | Same job |
| Market hours | Real-time | `MarketHours` |

### 2d. External Signals
| Data | Freshness | Notes |
|------|-----------|-------|
| Congress trades | ~6h | FMP API |
| ETF holdings changes | Periodic | `etf_holdings_log` |
| Social volume + sentiment | ~1h | StockTwits + Reddit |
| RSS / news articles | ~3h | SearXNG + RSS feeds |

---

## 3. Identified Gaps — What the System Cannot Currently Answer

These are the gaps that a summary/synthesis layer could fill. Ranked by potential trading value.

### Gap A: "What changed since my last session?"
**Problem:** The user opens the dashboard and sees a bunch of signals, but has no quick way to understand what is *new* vs. what was already there. Did a new thesis break? Did congress conflict scores spike overnight? Did social sentiment flip on a holding?

**What exists:** Nothing. Individual data is there but there is no "delta since last viewed / since N hours ago" layer.

**Value:** High. This is the first thing a real trader wants. Reduces time to awareness.

### Gap B: Portfolio-Level Risk Concentration
**Problem:** The system knows individual fear/risk signals per ticker. It does not synthesize whether the portfolio is heavily exposed to a correlated risk (e.g., three positions all flagged as high-volatility + bearish social sentiment + bearish sector regime). The user cannot see this without manually reading every signal.

**What exists:** Per-ticker fear/risk, individual allocation percentages. Not combined.

**Value:** High. This is directly risk management — prevents holding correlated exposures that look diversified on the surface.

### Gap C: Thesis Integrity Check per Holding
**Problem:** When a position is added, there is presumably a thesis (captured in `fund_thesis_data`). As time passes, new information arrives (negative research articles, congressional sells, technical breakdown). Currently there is no mechanism to automatically check "does current evidence still support the original thesis?"

**What exists:** `ticker_meta_analysis` partially does this, but it is not explicitly framed against the original thesis and is not triggered on a per-position basis with attention to entry price and current P&L.

**Value:** Very high. The most common mistake in active investing is holding a loser because the original thesis was never formally re-evaluated. This feature could literally prevent losing money.

### Gap D: Cross-Source Consensus Score per Ticker
**Problem:** A ticker might have: bullish technical signal, bearish social sentiment, neutral congress activity, mixed research articles. Currently the user has to mentally aggregate these. There is no single "cross-source consensus" score that weights these inputs.

**What exists:** `signal_analysis.overall_signal` combines only *technical* signals. `action_queue_ai_review` does a verdict but it is daily, nightly, and per-action-queue item only (not all holdings).

**Value:** High. The multi-source consensus is the whole premise of the system — that no single signal is reliable, but agreement across uncorrelated sources is informative. This is not exposed cleanly.

### Gap E: Watchlist Heat Map (What Am I Missing?)
**Problem:** The user's attention goes to holdings by default. But a watchlist ticker could be screaming buy across three sources (technical breakout + high positive social sentiment + congress buying) and the user might not notice because it never bubbled to the top of the action queue.

**What exists:** `action_queue` surfaces some of this, but the ranking is driven by technical confidence primarily.

**Value:** Medium-High. This is the opportunity discovery side — useful for micro-cap alpha, which is the core purpose of the system.

### Gap F: Fund-Level Narrative ("State of the Fund")
**Problem:** There is no LLM-generated high-level summary of what is happening in a given fund: its overall performance vs. benchmark, the theme of its current holdings, whether it is running hot or cold vs. its strategy.

**What exists:** Performance metrics table, daily brief (macro, not fund-specific). No fund narrative.

**Value:** Medium. Useful for periodic review, investor digest, and decision context — but less time-sensitive than Gaps A–E.

---

## 4. Proposed Summary Types (Ordered by Value)

### Type 1: Daily Delta Brief (per fund)
**What it answers:** Gap A — "What changed?"

**Inputs:**
- Holdings where `signal_analysis.analysis_date` is within last 24h AND signal changed
- `social_sentiment_analysis` where sentiment_label changed since yesterday
- New `research_articles` for portfolio tickers (last 24h) with non-neutral sentiment
- New congress trades for portfolio tickers (last 24h) with conflict_score > 0.5
- `market_daily_brief` comparison to previous day's regime
- Any ticker that crossed a technical signal threshold today

**LLM task:** "Given today's new signals and data for fund X, write a concise daily briefing. What changed materially? What needs attention? What can wait?"

**Output:** Short narrative (3–5 sentences) + a ranked list of "today's flags" (ticker, reason, urgency)

**Cadence:** Once per trading day, post-market. Or morning pre-market using previous close data.

**Stale risk:** Low — if nothing changed, the inputs_digest will match and we skip the LLM call.

---

### Type 2: Thesis Integrity Digest (per holding)
**What it answers:** Gap C — "Is the thesis still intact?"

**Inputs:**
- Original thesis text from `fund_thesis_data`
- Entry price, current price, current P&L
- Latest `ticker_meta_analysis` (unified_conviction, what_changed_vs_last_run)
- Latest `signal_analysis.overall_signal` + confidence
- Recent `research_articles` sentiment trend (last 30 days)
- Recent congress + insider trades (last 30 days)
- Social sentiment trend

**LLM task:** "The original thesis was [X]. Current evidence is [Y]. Is this thesis still intact? Rate: Intact / Weakening / Broken. Explain why in 2–3 sentences."

**Output:** Per-holding card: thesis status label + brief explanation + key evidence for/against.

**Cadence:** Triggered when: (a) a holding's overall_signal changes, (b) new negative-sentiment research articles arrive, (c) congress conflict score exceeds threshold, or (d) weekly unconditionally.

**Stale risk:** Medium — want to avoid calling this "Intact" when it's based on 2-week-old data. Must show last-evaluated timestamp prominently.

---

### Type 3: Cross-Source Consensus Score (per ticker)
**What it answers:** Gap D — aggregated signal across all uncorrelated sources

**Inputs:**
- Technical: `signal_analysis.overall_signal` + confidence
- Social: `social_sentiment_analysis.sentiment_score` + confidence
- Research: aggregate of `research_articles.sentiment_score` for ticker (last 30 days, weighted by recency)
- Congress: avg `conflict_score` + trade direction (buy vs sell) for ticker (last 60 days)
- Meta-analysis: `ticker_meta_analysis.unified_conviction`

**Design note:** This may not need LLM — it could be a deterministic weighted score. The LLM adds value only if the sources *disagree* and need narrative reconciliation ("technical says buy but every research article is negative — here's why that matters").

**Output:** A score (-1 to +1) + signal label + optional LLM narrative for high-disagreement cases.

**Cadence:** Recompute when any input source updates. No LLM unless disagreement threshold is crossed.

---

### Type 4: Portfolio Risk Concentration Summary (per fund)
**What it answers:** Gap B — correlated risk exposure

**Inputs:**
- All holdings with their `signal_analysis.fear_level` and `fear_risk_signal`
- Allocation weights
- Sector tags per holding
- Macro regime from `market_daily_brief` (bull/bear/correction)

**LLM task:** "Given these holdings and their risk signals, describe the concentrated risk exposures. What correlated scenarios could cause simultaneous drawdowns?"

**Output:** Paragraph identifying top 2–3 risk clusters + what would have to happen to trigger them.

**Cadence:** Daily, or when 2+ holdings get high fear signals simultaneously.

---

### Type 5: Watchlist Opportunity Brief
**What it answers:** Gap E — surface overlooked opportunities

**Inputs:**
- All watchlist tickers with `signal_analysis` updated in last 24h
- Social sentiment changes (large moves in bull_bear_ratio)
- Recent research articles sentiment
- Congress buys on watchlist tickers (last 14 days)

**LLM task:** "Which non-held watchlist tickers are showing the strongest multi-source positive signals? Rank and explain top 3."

**Cadence:** Daily or on-demand.

---

### Type 6: Fund Narrative Summary
**What it answers:** Gap F — big picture state of the fund

**Inputs:**
- Performance vs benchmark (MTD, QTD, YTD from `performance_metrics`)
- Allocation breakdown
- Largest contributors / detractors
- Overall regime (`market_daily_brief`)
- Number of holdings with intact vs. weakening thesis (from Type 2 if available)

**Cadence:** Weekly. Low urgency, useful for digest email and periodic review.

---

## 5. How Summaries Enable Automated Decisions

If the system only uses summaries to display text on a dashboard, it has limited value. The higher-value use case is: **summaries become structured inputs into the action queue and recommendation engine**.

### 5a. Thesis-Broken Auto-Flag
If Type 2 returns `status: "Broken"` with high confidence, automatically elevate to action queue as `REVIEW_THESIS` with urgency tag. The user should be forced to decide: sell, hold with updated thesis, or acknowledge.

### 5b. Cross-Source STRONG_BUY Upgrade
If Type 3 consensus score exceeds a threshold AND all 4 sources agree (technical BUY + positive social + positive research + congress buying), auto-upgrade the action queue entry from `WATCH` to `STRONG_BUY`.

### 5c. Risk Cluster Alert
If Type 4 identifies that 3+ holdings with >15% weight each are simultaneously in `HIGH` fear, trigger a `RISK_CLUSTER_WARNING` action queue item suggesting reducing one of the correlated positions.

### 5d. Opportunity Elevation
If Type 5 identifies a watchlist ticker scoring high on multi-source consensus, auto-create a `RESEARCH_OPPORTUNITY` action queue item so the user doesn't have to actively monitor the watchlist.

---

## 6. What NOT to Build (Anti-Patterns)

- **Per-screen "what does this chart mean" text:** Low value. The user can read a chart. LLM narrative about numbers already visible on screen adds clutter without insight.
- **Summaries that re-narrate what the UI already shows:** A summary that says "your portfolio is up 3% this month" when the chart is right there is noise.
- **Summaries with no defined staleness policy:** If a "thesis intact" summary is 3 weeks old, it could be actively misleading. Every summary type must have an expiry and a clear "as of" timestamp.
- **Summaries that run on a fixed clock regardless of input changes:** LLM calls are not free (time + local compute). The inputs_digest skip-if-unchanged pattern is mandatory.
- **Global portfolio summary (single, across all funds):** Per-fund is correct. Different funds may have different strategies; a global rollup would mix signals meaninglessly.

---

## 7. Thesis System — What Actually Exists

Reviewed `thesis_update_job.py` (runs weekly, Sunday evenings, uses GLM glm-4.7).

### What the thesis is

The thesis is **per-fund, not per-holding**. It is stored across two Supabase tables:

- `fund_thesis`: `id, fund, title, overview, updated_at`
- `fund_thesis_pillars`: `thesis_id, name, allocation, thesis, pillar_order`

A thesis has 2–4 "pillars" — thematic groupings of the fund's holdings (e.g. "Emerging Tech Growth", "Defensive Dividend Core") with an approximate allocation percentage and a philosophical narrative for each. The system prompt explicitly forbids per-ticker stop-losses or entry rules; the thesis is intentionally high-level and descriptive.

**What it captures:** Why these holdings make sense together. What market conditions favor each pillar. General guidance on when to add/reduce that pillar.

**What it does NOT capture:**
- Why any specific ticker was bought
- At what price or under what conditions the original buy decision was made
- Per-holding entry thesis or invalidation conditions
- Any time-stamped "state at time of purchase" record

### Implication for Type 2 (Thesis Integrity Check)

The original framing of Type 2 — "does current evidence still support the *original buy thesis* for this holding?" — **cannot be built from the current thesis structure**. There is no per-holding buy thesis to check against.

What Type 2 can realistically do instead:

**Pillar Health Check (per fund, weekly):** Given the current AI signals for holdings within each pillar, is the pillar thesis still holding? If the "Emerging Tech Growth" pillar holds 5 tickers and 4 of them have bearish `ticker_meta_analysis.unified_conviction` + high fear signals, the LLM can flag this pillar as "under stress" even if the overall thesis hasn't been regenerated yet.

This is weaker than a per-holding buy thesis check, but it's what the data supports. It has value as an **early warning signal that the thesis needs to be regenerated** before the weekly job fires.

### Gap this reveals

The absence of a per-holding thesis is itself a significant gap. The system has no memory of *why* a position was entered. This means:

- There is no automated way to flag "this position is down 25% and the original reason no longer applies"
- The user has to carry this context mentally
- The weekly thesis regeneration **overwrites** the previous thesis, so there is no historical record of what the thesis was when positions were opened

**The field already exists.** `trade_log.reason TEXT NOT NULL` is in the schema and surfaces in the trade entry UI. For recent and future trades this is the right place to capture rationale. The gap is purely historical: 80–90% of current holdings were entered as initial positions from research done before the system was fully operational, so `reason` is likely generic for most of them ("Initial position" or similar).

**Backfill opportunity — and the source data likely already exists in the DB.**

The Gemini research documents from last summer were manually uploaded through the web dashboard and stored in `research_articles` with `article_type = 'uploaded_report'`. These records include:
- `tickers[]` array containing the relevant ticker(s)
- `content` = full extracted PDF text
- `summary`, `conclusion`, `sentiment`, `sentiment_score` from the AI pass
- `fund` = fund association if set at upload time

There is already a diagnostic script `check_uploaded_reports.py` that lists all uploaded reports with their tickers, content length, and summary previews.

**What's actually in the DB (verified 2026-04-17):**

Running `diagnose_reports.py` revealed the uploaded docs are stored as `article_type = 'Research Report'` (not `'uploaded_report'` — that type has 0 rows). There are **6 research reports** with full content:

| Title | Folder | Tickers | Content |
|-------|--------|---------|---------|
| Stock Analysis of Undervalued Companies | _MARKET | KO, FTS, MSFT, NUE, GD, FAST, AMD, ABNB, TXN, KEY, TSCO, DOL | 98K chars |
| Dividend Stock Analysis Alternatives | _MARKET | FTS, CNR.TO, HD, MRK, UNP, NUE, FAST, ENB.TO, RY.TO, AVGO, BCE.TO | 114K chars |
| AI Investment Frontier | _MARKET | NVDA, MSFT, GOOGL | 67K chars |
| Portfolio Analysis and Trading Suggestions | _CHIMERA | *(None extracted)* | 58K chars |
| Project Chimera Inaugural Thesis | _CHIMERA | *(None extracted)* | 58K chars |
| Researching Gain Therapeutics | GANX | GANX | 44K chars |

All research report trades have `reason = 'Imported from Webull (Row N) BUY'` — this is the universal backfill target pattern. There are **73 unique tickers** across RRSP and TFSA funds needing backfill.

**Coverage assessment:**
- **17 tickers have direct research report coverage:** ABNB, AMD, AVGO, DOL.TO, ENB.TO, FAST, FTS.TO, GD, HD, KEY.TO, KO, MSFT, NUE, NVDA, RY.TO, TSCO, TXN — these should get high-quality rationales from the actual Gemini research
- **56 tickers have no research report:** Includes ETFs (VOO, VTI, XIC.TO, XEQT.TO, VFV.TO, BUG, CIBR, ITA, ROBO, etc.) and individual stocks with no uploaded doc (AMZN, TSLA, META, ASML, TSM, COST, JNJ, etc.)

**Backfill strategy (3 tiers):**

**Tier 1 — Research report available (17 tickers):** Pull `conclusion` + relevant section of `content` from the matching research report. LLM prompt: *"Based on this research, write 1–2 sentences explaining why [ticker] was a buy candidate in September 2025."* High confidence.

**Tier 2 — Individual stock, no research report (~36 tickers):** Fall back to `ticker_analysis.summary` + `ticker_analysis.stance` from the research DB. This reflects current analysis, not the original buy thesis, so the generated rationale should be prefixed with a note. Lower confidence.

**Tier 3 — ETFs and index funds (~20 tickers):** No LLM needed. Generate a standard rationale from the ETF name and category (e.g. VOO → "Broad US market exposure via S&P 500 index fund, held for passive diversification."). Deterministic, no API call.

**Update approach:** Write directly to `trade_log.reason`. The original "Imported from Webull (Row N) BUY" text is recoverable from trade dates if ever needed. Suggest dry-run mode first (print proposed changes without committing) for human review before the live update.

---

## 8. Model Strategy

### Current state
- **Local Ollama:** `granite3.3:8b`, `granite3.1:8b` — used for ticker analysis, congress scoring, social sentiment, signal explanation
- **GLM (glm-4.7 via Z.AI API):** Used for thesis generation; runs weekly, concurrently with Ollama jobs since it's a separate API. Noted as slow.
- **AI lock:** Ollama jobs share a global lock to avoid resource contention

### Why model quality matters here

The summary types in this doc have different reasoning demands:

| Summary Type | Reasoning Required | Min Viable Model |
|---|---|---|
| Type 3 — Cross-source consensus score | Mostly deterministic; narrative only on disagreement | 8B fine |
| Type 1 — Daily delta brief | Pattern-match on structured inputs; write a short paragraph | 8B adequate |
| Type 6 — Fund narrative | Summarize performance data | 8B fine |
| Type 4 — Risk concentration | Identify correlated exposures across holdings | 14B+ preferred |
| Type 2 (revised) — Pillar health check | Evaluate whether multi-source evidence invalidates a philosophical thesis | 14B+ strongly preferred |
| Type 5 — Watchlist opportunity brief | Rank and reason across multiple tickers | 14B+ preferred |

The jump in quality that matters most is for **thesis-level reasoning** — evaluating nuanced, multi-source evidence against a philosophical investment thesis. 8B models tend to produce shallow reasoning here: "stock is down therefore pillar is stressed" rather than "the macro thesis driving this pillar has changed."

### 16GB VRAM targets (roughly 2x current models, properly quantized)

Good candidates to try on a 16GB card:
- **Qwen2.5-14B-Instruct Q6_K** (~12GB) — strong instruction following and multi-step reasoning; recommended first try
- **Phi-4-14B Q6_K** (~12GB) — Microsoft's reasoning-focused 14B; punches above weight on analytical tasks
- **Mistral-Small-3.1-22B Q4_K_M** (~13GB) — larger model at lower quantization; good for narrative generation
- **Gemma 3 27B Q4_K_M** (~15–16GB) — tight fit; may work depending on card and context length needed

Quantization note: Q4_K_M at 22B is generally better for reasoning than Q8 at 8B. The extra parameters matter more than the precision for these tasks.

### Strategy recommendation

- Keep 8B models for high-frequency, structured jobs (signal explanation, congress scoring, social sentiment) where speed matters and the task is pattern-matching.
- Move thesis-level reasoning (Types 2, 4, 5) to a larger local model once benchmarked — this avoids GLM latency and cost for batch jobs.
- GLM remains useful for tasks that run infrequently and benefit from a large context window or better instruction following than current local models.

---

## 9. Open Questions (Decide Before Building Anything)

1. **Per-holding trade rationale** — Is there any appetite to add a free-text rationale field to trade entry? Even optional, this would be the single biggest unlock for the most valuable version of Type 2. Low implementation cost, high long-term value.

2. **Is the action queue user-editable or fully automated?** Before wiring summary outputs into the action queue (Section 5), need to confirm the queue is designed to accept programmatic entries with metadata.

3. **What is the user's actual workflow?** Does the user check the dashboard daily? Before market open, after close, or intraday? This determines which summary types are most time-sensitive and which cadence to target.

4. **Larger model benchmark** — Before building Types 2/4/5, run a quick qualitative test: give Qwen2.5-14B or Phi-4-14B one real fund's pillar thesis + a set of mixed signals and see if the reasoning quality is noticeably better than granite3.3:8b.

---

## 10. Recommended Next Steps

1. **Backfill `trade_log.reason` for initial holdings** — The field exists and is populated for recent trades. For the 80–90% of initial positions with generic reasons, run a one-time LLM backfill using `research_articles` and `ticker_analysis` records from around each trade date. Flag AI-generated rationales (e.g. `reason_generated BOOLEAN`) to distinguish from human-written ones.
2. **Prototype Type 3 (Cross-Source Consensus) as a deterministic score first** — No LLM needed for the score itself. Fast to build, validates multi-source aggregation, and the output feeds into Types 1 and 2 anyway.
3. **Build Type 1 (Daily Delta Brief)** — High value, relatively simple inputs. Defines the inputs_digest pattern for all subsequent types.
4. **Test a 14B model locally** — Benchmark Qwen2.5-14B or Phi-4-14B before committing Types 2/4/5 to any model.
5. **Revisit `screen_ai_summaries_rollout.plan.md`** after Types 1–3 are validated conceptually, using this document as the revised scope.
