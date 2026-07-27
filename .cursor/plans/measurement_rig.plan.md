---
name: Measurement rig repair
overview: The track record is unreadable and currently frozen. Three defects: (1) the outcome scoring queue is head-of-line blocked and has scored ~0 rows for days; (2) every stance is scored against ^RUT regardless of what the ticker is, so excess return measures benchmark mismatch rather than skill; (3) mean_excess pools bullish and bearish sign conventions and is meaningless. Fix those, record the benchmark immutably per outcome, then add baselines so a hit rate can be interpreted at all.
todos:
  - id: m1-unjam-scoring
    content: "Fix head-of-line block in select_unscored_stances: dead-letter unscoreable rows so the queue drains"
    status: completed
  - id: m2-per-stance-benchmark
    content: "Per-ticker benchmark (geography + cap band) stored on securities; record benchmark_symbol on every stance_outcomes row"
    status: completed
  - id: m3-sign-adjusted-excess
    content: "Sign-adjust excess return by stance direction so mean_excess is comparable across bullish/bearish sources"
    status: completed
  - id: m4-rescore-backfill
    content: "One-shot re-score of existing outcomes under correct benchmarks, gated by scoring_version"
    status: completed
  - id: m5-baselines
    content: "Null models: always-bullish and shuffled-stance baselines scored through the same path"
    status: pending
  - id: m6-fund-benchmark
    content: "Fund primary benchmark: weekly LLM proposal from holdings, effective-dated, for portfolio reporting only"
    status: pending
---

# Measurement rig repair — plan

**Created 2026-07-27** from a live read of prod via
[`verify_stance_pipeline.py`](../../web_dashboard/scripts/verify_stance_pipeline.py).

**Why this is now ahead of Ideas inbox work:** `/ideas` being full of junk costs the user
time. The measurement rig being wrong costs the user *the ability to tell whether any of
this works* — and it is currently producing confident-looking numbers that cannot support
the conclusions people will draw from them. See
[`ideas_inbox_quality.plan.md`](ideas_inbox_quality.plan.md) for the separate Ideas work;
these do not overlap and Ideas was never blocking measurement.

## Ground truth (prod, 2026-07-27)

```
stance_history      ticker_meta_analysis  3,274 rows / 112 tickers  (fund_key NULL)
                    ticker_analysis       1,676 rows / 112 tickers  (fund_key NULL)
                    action_queue_ai_review    61 rows /  25 tickers  (fund_key set)
                    thesis_ai_review / confluence / congress_herd: 11 rows total

stance_outcomes      7d: 1,884 scored — 879 hits / 1,005 misses = 46.7%
                    30d:   850 scored — 379 hits /   471 misses = 44.6%
                    90d: none (oldest stance is 2026-06-11, not yet matured)

nightly job         2026-07-27  scored=0  skipped=202
                    2026-07-26  scored=3  skipped=115
                    2026-07-25  scored=0  skipped=...
```

**98.6% of the ledger has `fund_key = NULL`** — the nightly 112-ticker universe is
fund-agnostic. This is the single most important constraint in this plan (see M2).

---

## Defect 1 — the scoring queue is jammed (live outage, fix first)

`scored=0 skipped=202` two nights running is not a slow trickle; **outcome scoring has
stopped**. The track record is frozen at stale numbers and will silently rot.

Mechanism, confirmed in
[`jobs_stance_outcomes.py`](../../web_dashboard/scheduler/jobs_stance_outcomes.py):

- [`select_unscored_stances`](../../web_dashboard/scheduler/jobs_stance_outcomes.py) selects
  `WHERE so.id IS NULL ORDER BY sh.as_of ASC LIMIT 200`.
- [`score_stance_row`](../../web_dashboard/scheduler/jobs_stance_outcomes.py) returns `None`
  when any of `baseline_price` / `end_price` / `bench_baseline` / `bench_end` is missing.
- The caller does `skipped += 1; continue` — **no row is written, nothing is marked.**

So a permanently unscoreable stance (delisted ticker, yfinance gap, bad symbol) sits at the
front of the `as_of ASC` window **forever**, and re-occupies one of the 200 slots every
night. Once ~200 such rows accumulate at the head, every newer stance is starved. That is
exactly the observed signature.

Note the existing comment at
[`jobs_stance_outcomes.py:252-254`](../../web_dashboard/scheduler/jobs_stance_outcomes.py)
already worries about "permanently skip older rows" for the price-window case — the same
class of bug, caught once and not generalized.

**Fix:** unscoreable rows must leave the queue.

- Add `attempts INT DEFAULT 0`, `last_attempt_at TIMESTAMPTZ`, `skip_reason TEXT` to
  `stance_outcomes` **or** a small `stance_outcome_attempts` sidecar (prefer the sidecar —
  `stance_outcomes` should stay "rows that scored").
- Record an attempt on every `None` return, with the specific reason
  (`no_ticker_price` / `no_benchmark_price` / `not_matured` / `bad_symbol`).
- Exclude rows with `attempts >= 5` from `select_unscored_stances`; surface them as a
  dead-letter count in the job summary.
- **Distinguish `not_matured` from genuinely unscoreable** — a not-yet-matured row must not
  burn attempts. (`select_unscored_stances` already filters `as_of <= cutoff` per horizon,
  so this should be rare; if it is not rare, that is its own bug and the reason counts will
  show it.)
- Log the distinct tickers in the dead-letter set. For a micro-cap book these are likely
  delistings, and **that is information, not noise** — see ROADMAP follow-up on scoring
  delistings as realized losses rather than dropping them (dropping biases hit rate upward).

**Acceptance:** one nightly run reports `scored > 0` and a dead-letter count; the next run's
candidate set is different from the previous run's.

### ✅ M1 SHIPPED 2026-07-27 — result

Migration applied; job run manually against prod:

```
before:  scored=0    skipped=202   errors=0     (three consecutive nights)
after:   scored=247  skipped=0     errors=0
         stance_outcomes 7d 1,884 -> 2,036   30d 850 -> 945
         resolved TECK.B -> TECK-B.TO  (cached in securities.price_symbol)
         dead-letter rows written: 0
```

**Honest correction to the diagnosis above.** I had hypothesised that provider rate-limiting
across ~65 sequential fetches was contributing to the mass skip. That looks wrong: once
`TECK.B` resolved via the symbol ladder, *everything else scored on the first attempt*, and
no row needed dead-lettering. The evidence is consistent with head-of-line blocking alone
being the cause — though I cannot fully rule out a transient provider failure during the
stalled nights, because the old code had no per-reason accounting to distinguish them.

That gap is precisely what shipped: if this stalls again, the summary line names the reason
instead of printing an undiagnosable `skipped=N`. The dead-letter net is untested in prod
(nothing failed) but is covered by unit tests.

⚠️ **The 247 new rows were scored against `^RUT`**, like everything before them — M2a/M2b
still have to re-score the whole table. This unjammed the pipe; it did not make the numbers
correct.

## Defect 2 — every stance is scored against ^RUT

[`jobs_stance_outcomes.py:102-107`](../../web_dashboard/scheduler/jobs_stance_outcomes.py)
fetches a single module-level `BENCHMARK_TICKER` for everything. The latest stances are
AAPL, CRM, CEG, NOW, CTRN — megacaps benchmarked against the Russell 2000. `excess_return`
is therefore dominated by the large-cap/small-cap spread, not by whether the call was right.
This alone can explain a sub-50% hit rate, and it means **the current numbers cannot answer
the question either way.**

### The wrinkle: a *fund* benchmark cannot fix this

The user's proposal — LLM sets a primary benchmark from holdings weekly — is right for
portfolio reporting, but it cannot score the ledger: **4,950 of 5,022 stance rows have
`fund_key = NULL`**, because `ticker_meta_analysis` / `ticker_analysis` run over a
112-ticker research universe, not a fund. A fund-level benchmark would apply to the 61
`action_queue_ai_review` rows and nothing else.

So this splits into two layers, and only the first fixes the track record:

### M2a — Ticker-level benchmark (this is the actual fix)

Assignment is mechanical; an LLM adds nothing here and would add nondeterminism to a number
that must be stable.

**Decided 2026-07-27 from the actual universe** (user asked me to pick; probe run against
prod). The stance universe is *not* micro-cap: MSFT, AVGO, QCOM, MRK, COST, AMAT, SPGI, GD,
NUE, DG… plus US sector ETFs (VOO, ROBO, BUG, CIBR, FTXL, URNJ, FXD) plus Canadian listings
(CLS.TO, AEM.TO, FTS.TO, KEY.TO, DOL.TO, GMIN.TO, GLO.TO, HURA.TO, TECK.B). Benchmarking
that book against `^RUT` is the mismatch.

Constraint that decides the symbols: `benchmark_data` **already caches `^GSPC`, `^RUT`,
`QQQ`, `VTI` with 350 rows each through today**. Picking those avoids standing up a new
price backfill; `^GSPC` ≈ `SPY` for this purpose.

| Condition | Benchmark | Why |
|---|---|---|
| Canadian listing (`.TO` / `.V` suffix, or `currency = 'CAD'`) | `^GSPTSE` | only symbol needing a cache backfill |
| US, cap < $2B | `^RUT` | already cached; genuinely small-cap |
| US, everything else (incl. unknown cap) | `^GSPC` | already cached; matches the large-cap-heavy reality |

- Detect Canadian listings from the **ticker suffix**, not `securities`: 51 of the stance
  tickers (2,244 stances — the largest single bucket) have **no `securities` row at all**,
  so exchange/currency is NULL for them. Suffix is the reliable signal; `securities` is the
  enrichment, not the source of truth.
- `market_cap` still needs adding to `securities` (monthly yfinance refresh) for the
  `< $2B` split. Until it is populated, unknown cap → `^GSPC`, flagged
  `benchmark_fallback = true` so the fallback share is visible.

#### Broad-index ETF exclusion — **DECIDED 2026-07-27 (user approved)**

"BULLISH on VOO" scored against `^GSPC` has an excess return of ~0 **by construction**. It is
not a prediction; it is the benchmark wearing a hat. But it lands in the hit rate as a coin
flip, so every such stance drags the aggregate toward 50% and mutes whatever real signal
exists in the rest of the book.

**Rule:** exclude a stance from **hit-rate and mean-excess aggregates** when its ticker
tracks substantially the same index as the benchmark it would be scored against. Keep the
row in `stance_history` and keep scoring it into `stance_outcomes` — this is an *aggregation*
filter, not a ledger filter, so nothing is lost and the decision is reversible.

Implemented as a named constant in `track_record_service.py` (auditable, one place to edit):

```python
# ETFs that track ~the same index as their assigned benchmark. Scoring these is
# tautological (excess ~ 0), so they are excluded from aggregates -- not from the ledger.
BROAD_INDEX_ETFS = frozenset({
    "VOO", "VTI", "SPY", "IVV", "SPLG", "ITOT",     # US broad market -> ^GSPC
    "IWM", "VTWO",                                   # US small cap    -> ^RUT
    "XIC.TO", "XIU.TO", "ZCN.TO", "VCN.TO",          # Canada broad    -> ^GSPTSE
})
```

**Deliberately NOT excluded** — these are genuine directional calls with real tracking error
against a broad benchmark, and removing them would throw away signal:
`QQQ` (Nasdaq-100 is a real tilt vs the S&P 500), and every sector/thematic fund in the
universe — `ROBO`, `BUG`, `CIBR`, `FTXL`, `URNJ`, `FXD`, `LIT`, `URA`, `HURA.TO`.

Surface the excluded count on the track-record screen (e.g. "12 broad-index ETF stances
excluded") so the filter is visible rather than silently shrinking *n*.

- Scoring resolves: `securities.benchmark_symbol` → fund default (M6) → `SPY`.
- **Record `benchmark_symbol` on every `stance_outcomes` row.** It does not exist today, so
  no scored row records what it was measured against. Without this, a benchmark that ever
  changes silently rewrites history — the exact failure the append-only `stance_history`
  design was built to prevent ("the overwrite offender").
- Benchmark price fetching becomes per-symbol; cache per run like `ticker_cache` already
  does. Handful of symbols, negligible cost.

### M2b — Re-score existing outcomes (one shot, versioned)

Existing 1,884 + 850 rows were scored against the wrong benchmark and are not comparable to
anything produced after M2a.

- Add `scoring_version INT` to `stance_outcomes`.
- One-shot script `web_dashboard/scripts/rescore_stance_outcomes.py`, `--dry-run` default,
  reporting how many rows change hit/miss.
- ⚠️ The insert is `ON CONFLICT (stance_id, horizon_days) DO NOTHING`
  ([`jobs_stance_outcomes.py:301`](../../web_dashboard/scheduler/jobs_stance_outcomes.py)),
  so a naive re-run silently no-ops. The backfill must explicitly `DO UPDATE` (or
  delete-then-rescore) and stamp the new `scoring_version`.
- **Re-score exactly once, deliberately.** After this, benchmark assignment for a scored row
  is immutable. Any future benchmark change bumps `scoring_version` and applies to new rows
  only; the track-record screen filters to a single version.

### ✅ M2a + M2b SHIPPED 2026-07-27 — result

```
113 tickers resolved:   ^GSPC=76   ^GSPTSE=32   ^RUT=5
2,981 outcome rows re-scored to scoring_version=2, zero NULL benchmark_symbol
       ^GSPC=2,072      ^GSPTSE=719      ^RUT=190

verdict churn:  miss->hit 166 | hit->miss 165 | unchanged 2,650 | unscoreable 0
```

#### ⚠️ The benchmark mismatch did NOT explain the sub-50% hit rate

**166 up against 165 down is a wash.** This retracts the claim made earlier in this plan
("This alone can explain a sub-50% hit rate"). Hit/miss is a *sign test* on excess return —
changing the benchmark shifts magnitude but rarely pushes a row across zero, and when it
does it goes both ways in equal measure. Post-rescore 7d:

```
ticker_meta_analysis    46.0%   mean_excess -0.22   (1,304 scored)
ticker_analysis         49.9%   mean_excess -0.37   (  657 scored)
action_queue_ai_review  72.0%   mean_excess +2.97   (   25 scored)
```

The ~46% is **real**, not a benchmarking artifact. What the fix bought is a *trustworthy*
number and a meaningful `mean_excess`, not a better one.

**This promotes M5 (baselines) to the critical path.** It is now the only remaining thing
that can say whether 46% is bad — if always-bullish on this universe also scores ~46%, the
conclusion is "no edge either way", which is very different from "the model is wrong".

#### Design notes worth keeping

- `benchmark_symbol` is **derived at scoring time**, not stored on `securities`, so it cannot
  go stale against the rule that produced it. Only `market_cap` (the input needing a network
  fetch) is cached, plus a `benchmark_override` manual escape hatch.
- Canadian detection reads **`price_symbol` before `ticker`**: `TECK.B` looks US-shaped but
  resolves to `TECK-B.TO` via the M1 alias ladder. `securities.currency` is checked last
  because 51 tickers have no securities row.
- Unknown / NaN / zero market cap is treated as **unknown** (broad index, `fallback` flagged),
  never as "tiny" — otherwise one bad data point silently moves a megacap onto ^RUT.
- Benchmark fetching is **self-populating**: `^GSPTSE` was absent from `benchmark_data`, so a
  cache miss falls through to the provider and writes back. No backfill job; future
  benchmarks work the same way.
- `SCORING_VERSION` lives in `benchmarks.py` (not the scheduler) so the scoring job and
  `track_record_service` cannot drift on which scheme they mean.
- `build_track_record_summary` now **filters to one `scoring_version`**. Mixing schemes
  averages numbers measured against different yardsticks — the original bug, reintroduced.

## Defect 3 — `mean_excess` mixes sign conventions

[`track_record_service.py:39-42`](../../web_dashboard/track_record_service.py): bullish hit is
`excess > 0`, bearish hit is `excess < 0`. So a *correct* bearish call contributes a
*negative* number to `mean_excess`. Pooling them is meaningless.

This is visible in the live data: `action_queue_ai_review` shows **68.0% hit rate with
−4.24 mean excess** — a source that is right about direction most of the time while its
own quality metric reports it as the worst performer.

**Fix:** compute `directional_excess = excess_return * (+1 if bullish else −1)` and
aggregate *that*. Report it as "mean return in the direction of the call." Keep raw
`excess_return` stored as-is; this is a presentation-layer fix in `track_record_service.py`
plus the retro digest. Add a unit test with one bullish hit and one bearish hit asserting
both contribute positively.

### ✅ M3 SHIPPED 2026-07-27 — result

Confirmed on prod data, exactly the predicted sign flip:

```
action_queue_ai_review   before: hit_rate=68.0%  mean_excess=-4.24
                          after: hit_rate=68.0%  mean_excess=+4.24
ticker_meta_analysis     -0.60 -> -0.33
ticker_analysis          -0.38 -> -0.13
```

The SELL/RISK-heavy source was being reported as the **worst** performer in the book while
actually being the best. The two large sources moved toward zero for the same reason (their
correct bearish calls had been subtracting).

Shipped alongside:
- `_BULLISH_STANCES` / `_BEARISH_STANCES` extracted as shared constants so `_hit_from_row`
  and `_directional_excess` can never disagree about what a directional call is.
- **Best/worst calls sorting was wrong too** — it ranked by raw excess, so a correct bearish
  call sorted as the worst call in the book. Now sorts directionally.
- Broad-index ETF exclusion (below), user-approved.
- `excess_metric: "directional"` in the API payload, since `ai_assistant_tools` passes this
  dict to an LLM verbatim and needed the semantics stated inline.
- Meta-bundle label renamed `mean_excess` → `mean_directional_excess` in
  `stance_history.py` for the same reason.
- UI labels/tooltips in `track_record.ts` updated; excluded-ETF count surfaced.

⚠️ Still scored against `^RUT` — M2a/M2b outstanding. `ticker_meta_analysis` at 45.9% and
`ticker_analysis` at 48.1% remain uninterpretable until the benchmark is right **and** M5
baselines exist.

## Defect 4 — no baseline, so no hit rate is interpretable

46.7% means nothing without knowing what no-skill scores. The median individual stock
underperforms an index routinely, so a mostly-bullish book can print sub-50% while having
ordinary luck.

Score two null models through the **same** path (same tickers, same dates, same horizons,
same benchmark resolution):

- **Always-bullish:** every stance forced to BULLISH.
- **Shuffled:** stance labels permuted across rows within the same date bucket (preserves
  the market-move correlation structure; that matters, see below).

Store in a `stance_baselines` table or as reserved `source` values — prefer a separate table
so baselines can never leak into real source-ROI aggregates. Surface on the track-record
screen next to the real number. **The headline metric becomes `hit_rate − baseline_hit_rate`,
not `hit_rate`.**

### Sample size honesty (put this on the screen, not just in this doc)

3,274 meta stances over 112 tickers in 46 days is ~29 stances per ticker — one every 1.6
days. These are not independent predictions; they are a near-continuous opinion stream on
the same names, and they are correlated *across* tickers (a market drop makes every bullish
stance miss at once). **Effective sample size is in the low hundreds, not 1,884.**

Minimum: show `n` next to every rate, and suppress rates where `scored < 30`. The live data
already has `thesis_ai_review: 50.0% (1/2 scored)` and `confluence: 33.3% (1/3 scored)`
displayed as if they were comparable to a 1,227-row source.

## M6 — Fund primary benchmark (the user's ask, correctly scoped)

Useful, and worth building — for **fund-level performance reporting**, not stance scoring.

- Table `fund_benchmarks(fund_key, benchmark_symbol, rationale, effective_from,
  effective_to, set_by)`. Effective-dated, append-only.
- Weekly job: read current holdings, compute the mechanical default (weighted cap band +
  geography, same rules as M2a), then ask the LLM to propose an override with a one-line
  rationale — its real value is judgment on concentrated or thematic books, not on the
  arithmetic.
- Store the proposal; **do not retroactively re-cut history.** Fund performance charts
  splice the benchmark series across effective-date boundaries.
- Consumed by: fund performance reporting, and as the fallback in M2a's resolution chain for
  fund-scoped stances (`action_queue_ai_review`, `fund_key` set).

---

## Non-goals

- Insider buy/sell event study, news-sentiment event study → ROADMAP (see follow-ups)
- Confidence intervals / clustered standard errors → ROADMAP
- Scoring delistings as realized losses → ROADMAP (needs a judgment call on magnitude)
- Retiring or retuning any source based on current numbers — **not until M1–M5 land**
- Any change to Ideas inbox (separate plan)
- Acting automatically on track-record output; this stays a reporting loop

## Success criteria

- Nightly job reports `scored > 0` with a bounded dead-letter set; no repeat of
  `scored=0 skipped=202`.
- Every `stance_outcomes` row records `benchmark_symbol` and `scoring_version`.
- Megacap stances are scored against a large-cap benchmark; Canadian listings against a
  Canadian one. Spot-check 10.
- `action_queue_ai_review` no longer shows a high hit rate alongside a negative quality
  metric.
- Track-record screen shows, for each source: `n`, hit rate, baseline hit rate, and the
  difference — with rates suppressed below n=30.
- Someone can look at the screen and state, with a straight face, whether the LLM stances
  beat always-bullish.

## Implementation order

1. **M1** unjam scoring. It is a live outage and everything downstream needs a draining
   queue. Ship alone, verify one nightly run.
2. **M2a** ticker benchmark map + `benchmark_symbol` on outcomes.
3. **M3** sign-adjusted excess (independent of M2; can go in parallel).
4. **M2b** one-shot re-score, `--dry-run` first, report hit/miss churn.
5. **M5** baselines.
6. **M6** fund benchmark (independent; can slip without blocking anything above).

## Open question for the user

M2a's cap bands (`$10B` / `$2B`) and benchmark picks (`SPY` / `IJH` / `IWM` / `XIC.TO`) are
my defaults, not yours. If the book has a house convention, say so before M2a — changing it
afterward means another re-score.
