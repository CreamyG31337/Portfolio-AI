---
name: MNST Split Recalc (Corrected)
overview: Fix MNST's unadjusted 2-for-1 split for RRSP Lance Webull and TFSA. The original plan's "rebuild from 2025-09-03" step would have destroyed ~11 months of history because of four separate defects in rebuild_from_date.py and because Yahoo has NOT back-adjusted MNST. This plan fixes the rebuild bugs first, validates them against throwaway TEST fund clones, and then applies a minimal 3-day repair to prod.
todos:
  - id: p0
    content: "Phase 0: Back up affected prod rows to disk; clone RRSP + TFSA into non-production TEST funds"
    status: completed
  - id: p1
    content: "Phase 1: Fix the 5 rebuild_from_date.py defects + add unit tests (no DB writes)"
    status: completed
  - id: p2
    content: "Phase 2: Validate fixed rebuild against TEST clones via no-op equivalence diff"
    status: completed
  - id: p2b
    content: "Phase 2.5: Fix rebuild write-path read amplification (~128 -> ~4 round trips/day); verify byte-identical output"
    status: completed
  - id: p3
    content: "Phase 3: Build debug/apply_stock_split.py + tests; exercise split->rebuild end-to-end on TEST funds only"
    status: completed
  - id: p4
    content: "Phase 4: Apply to prod - 4 trade_log rows + 2 mislabeled action rows + targeted 3-day position repair"
    status: completed
  - id: p5
    content: "Phase 5: Guardrails, docs, graphify update, and follow-up watch for Yahoo back-adjustment"
    status: completed
isProject: false
---

# MNST 2:1 Split Fix — Corrected Plan

> **This supersedes the previous version of this plan.** The diagnosis in the old
> plan was correct; the remediation was not. Read "Why the original plan was
> wrong" before doing anything. The previous version is recoverable from git.

## STOP — read this first

**Do not run `manual_rebuild.py` or `rebuild_fund_from_date` against any
production fund until Phase 4.** Running it today against `RRSP Lance Webull`
from `2025-09-03` would irreversibly delete 17,334 position rows and write back
roughly 5 days of wrong data.

**Do not edit the MNST trade through the admin UI.** `admin_routes.py` fires
`trigger_background_rebuild()` on trade edit, which passes `--job-id`, which hits
a `NameError` in `rebuild_from_date.py` — *after* the deletes have committed. It
also re-infers `action` from the reason prose and would undo the Phase 4 data
repair.

Every phase ends at a **REVIEW GATE**. Stop there and wait for sign-off.

---

## Verified facts (do not re-litigate these)

All of the following were confirmed against prod Supabase
(`injqbxdqyxfvannygadt`) and by running the repo's own fetcher on 2026-08-12.

### V1 — Yahoo has NOT back-adjusted MNST

This is the fact that invalidates the original plan. The repo's own
`MarketDataFetcher` returns, today:

| Date | Close returned |
|---|---|
| 2025-09-03 | 63.51 (unadjusted) |
| 2025-12-19 | 76.26 (unadjusted) |
| 2026-08-06 | 94.16 (unadjusted) |
| 2026-08-07 | 90.36 (unadjusted) |
| 2026-08-10 | **MISSING** |
| 2026-08-11 | **MISSING** (Yahoo row exists but is all-NaN, `Stock Splits = 2.0`) |
| 2026-08-12 | 45.68 (post-split) |

`yf.Ticker('MNST').splits` *does* record `2026-08-11 → 2.0`, but the historical
price series is still unadjusted. So doubling the share count and rebuilding
history today would pair **26 shares with unadjusted ~$63–97 prices** — double
the true market value for ~235 days. That is worse than the bug being fixed.

Reproduce with:
```powershell
.\venv\Scripts\python.exe -c "import yfinance as yf; print(yf.Ticker('MNST').splits.tail(3)); print(yf.Ticker('MNST').history(start='2026-08-05', end='2026-08-13')[['Close']])"
```

### V2 — `rebuild_fund_from_date` only writes snapshots on dates that have trades

`web_dashboard/utils/rebuild_from_date.py:212` keys `date_positions` on
`trade_df['Date'].dt.date.unique()`. Line 334 then does
`if trading_day not in date_positions: continue`. But line 129 deletes **every**
row from `start_date` forward.

| Fund | rows deleted | distinct trade dates since 2025-09-03 | days written back |
|---|---|---|---|
| RRSP Lance Webull | 17,334 | **5** | 5 |
| TFSA | 17,461 | 64 | 64 |

### V3 — Shallow-copy aliasing puts today's positions on every historical date

`rebuild_from_date.py:269` does `date_positions[trading_day] = dict(running_positions)`.
The per-ticker inner dicts are mutated in place, so every date aliases the same
objects and ends up holding the *final* share count and cost. Confirmed:

```
day1 snapshot -> {'shares': 13, 'cost': 815}   # should be 26 / 1630
day2 snapshot -> {'shares': 13, 'cost': 815}
same object? True
```

`debug/rebuild_portfolio_complete.py:674` has the identical defect.

### V4 — The dividend filter deletes ~$6.6k of real RRSP holdings

`rebuild_from_date.py:234` skips trades where `is_dividend_reason(reason)` when
the fund is `dividend_mode='cash'` — which `RRSP Lance Webull` is. That helper
matches `\b(drip|dividend)\b` **anywhere in the reason text**, including
investment theses. Compounding it, `trade_log.action` is itself mislabeled for
two of those rows (`infer_trade_action` made the same mistake at write time):

| Fund | Ticker | Trade | `action` | Current MV | Dropped by |
|---|---|---|---|---|---|
| RRSP | FTS.TO | 47 sh @ $70.00 | **`DIVIDEND`** (wrong) | $3,677.75 | reason regex + action |
| RRSP | KO | 24 sh @ $68.97 | **`DIVIDEND`** (wrong) | $2,079.84 | reason regex + action |
| RRSP | PEP | 6 sh @ $148.99 | `BUY` (correct) | $829.32 | reason regex |

`RRSP Lance Webull` has **zero** genuine dividend rows — all 2 of its
`action='DIVIDEND'` rows are mislabeled real buys. So the fix needs **both** a
code change (skip on `action`, not on reason prose) **and** a data repair of
those 2 rows. `Project Chimera` has 3 BUYs with the same prose problem but
correct `action` values, and is `reinvest` mode, so it is currently unaffected.

### V5 — The admin-UI rebuild path deletes and then crashes

`rebuild_from_date.py:274` references `tickers_to_price` inside `if job_id:`;
the variable is defined at line 277. `NameError`, swallowed by the outer
handler — after Step 2's deletes commit. `background_rebuild.py:132` always
passes `--job-id`; `admin_routes.py:2560` fires it on trade edit. Regression
introduced in `fb37c509` (2026-03-31).

### V6 — A missing price silently deletes a position from the snapshot

`rebuild_from_date.py:347` skips any ticker with no exact price for the day, and
`save_portfolio_snapshot` replaces the entire day. Combined with V1, MNST would
vanish from the 08-10 and 08-11 snapshots under any rebuild, and fund totals for
those days would silently shrink.

### V7 — Schema facts relevant to the repair

- `funds.is_production` defaults to `false`, and every scheduler job filters on
  `is_production = true`. **A test fund created without that flag is
  automatically invisible to the daily price job, the backfill, and metrics.**
- `portfolio_positions.total_value` is `GENERATED ALWAYS AS (shares * price)` —
  never write it.
- `portfolio_positions.date_only` is set by trigger
  `trigger_set_portfolio_position_date_only` on INSERT/UPDATE — never write it.
- `portfolio_positions` has `UNIQUE (fund, ticker, date_only)`.
- `performance_metrics` has `UNIQUE (fund, date)`.
- `portfolio_positions`, `trade_log`, `performance_metrics` all have a FK on
  `fund` → the `funds` row must exist before cloning.
- `TradeMapper.db_to_model` honours a valid stored `action` and only falls back
  to reason inference when it is missing/invalid — so repairing the `action`
  column is effective.

### V8 — What is actually broken in prod is 3 days, not 11 months

Everything from 2025-09-03 → 2026-08-07 is already correct (26 sh, then 13 sh,
priced at then-current unadjusted closes). Only these rows are wrong:

| Fund | Date | Stored | Should be |
|---|---|---|---|
| RRSP | 2026-08-10 | 13 × $45.72 = $594.36 | 26 × $45.72 = $1,188.72 |
| RRSP | 2026-08-11 | 13 × $45.53 = $591.89 | 26 × $45.53 = $1,183.78 |
| RRSP | 2026-08-12 | 13 × $45.68 = $593.84 | 26 × $45.68 = $1,187.68 |
| TFSA | 2026-08-10 | 0.489269 × $45.72 | 0.978538 × $45.72 |
| TFSA | 2026-08-11 | 0.489269 × $45.53 | 0.978538 × $45.53 |
| TFSA | 2026-08-12 | 0.489269 × $45.68 | 0.978538 × $45.68 |

The stored prices on those days are **already split-adjusted** (that fetch came
from a fallback source, which is exactly what created the cliff). So the repair
needs no price fetch at all — only the share count is wrong.

---

### V16 — V4's scope was too narrow: TFSA had the same 2 mislabeled rows

Found at Gate 5. V4 named only RRSP's FTS.TO/KO rows. TFSA carries the identical
pair, same thesis prose, same `infer_trade_action` misfire at write time:

| Fund | Ticker | Date | Shares | Cost | `action` |
|---|---|---|---|---|---|
| TFSA | FTS.TO | 2025-08-25 | 1.768895 | 123.82 | `DIVIDEND` |
| TFSA | KO | 2025-09-03 | 0.903266 | 62.30 | `DIVIDEND` |

Why it was missed: the Gate 0 query counted TFSA's DIVIDEND rows as "127 of 127
containing a dividend word." `DRIP` matches that word pattern too, so the two
thesis rows were indistinguishable inside the count. The lesson is to enumerate
non-`DRIP` DIVIDEND rows explicitly:

```sql
select fund, ticker, date::date, action, shares, left(reason,55)
from trade_log where action='DIVIDEND' and reason !~* '^\s*drip\s*$';
```

**Impact: none today** — TFSA is `dividend_mode='reinvest'`, so the cash-dividend
skip never fires and the rows already behave as buys (Gate 4 reconciliation was
clean). Purely latent: switching TFSA to `cash` would make a rebuild drop ~$215.

Repaired at Gate 5 alongside the RRSP pair. After the `is_dividend_reason` fix,
newly written trades will not reproduce this.

### V15 — Live and recalculated `performance_metrics` disagree (pre-existing)

Found at Gate 4. Days written by the live daily job do **not** equal the sum of
that day's stored `portfolio_positions.total_value_base`; days written by
`populate_performance_metrics_job` match it exactly.

| Date | Σ positions (base) | metric | diff |
|---|---|---|---|
| 2026-08-06 (live) | 310,207.83 | 309,976.23 | −231.60 |
| 2026-08-07 (live) | 312,467.16 | 313,393.34 | +926.18 |
| 2026-08-10/11/12 (recalc) | — | — | **0.00** |

The sign varies, so it is not a constant cash component — most likely the live
job computes at 21:00 UTC from prices captured at that moment while the stored
snapshot is written at 16:00 ET and may be rewritten later.

Implications:

- **Old and new metric values are not comparable.** The apparent 08-07 → 08-10
  drop of −1,880 is mostly methodology; like-for-like it is −954.24 (−0.31%),
  and MNST's +$828 CAD is inside that.
- Days 2026-08-10..08-12 are now internally consistent while their neighbours are
  not, leaving a small discontinuity in the series at the 08-07/08-10 boundary
  that is **not** a market move.
- A future full-series metrics recalc would shift every historical day by a few
  hundred CAD. Expect it; it is not damage.

Pre-existing, out of scope, do not chase. Recorded so it is not misread later.

### V14 — MNST's 2026-08-10 close exists ONLY in prod `portfolio_positions`

Demonstrated at Gate 3, not merely argued. Yahoo has no 2026-08-10 bar for MNST.
The prod row holds `price = 45.72` — captured live by the daily job, already
split-adjusted, and unavailable from any feed today.

The Phase 2 rebuild **destroyed that value on the clone**, replacing it with an
F5 carry-forward of the 08-07 close (90.36). After the clone's split adjustment,
08-10 became 26 × 90.36 = $2,349.36 instead of the correct 26 × 45.72 = $1,188.72.

Consequences:

- **Gate 3 rehearsed 4 of the 6 target rows faithfully** (08-11 and 08-12 for both
  funds match what prod will produce exactly). The two 08-10 rows were *not*
  rehearsed, because the clone no longer holds prod's 08-10 price. Phase 4's
  08-10 outcome rests on arithmetic, not on the rehearsal: prod 13 × 45.72
  doubles to 26 × 45.72 = $1,188.72, pnl +$373.62.
- **Phase 5's deferred full rebuild will do the same thing to prod.** When Yahoo
  back-adjusts and the full rebuild runs, it will overwrite prod's 45.72 with a
  carry-forward. Before that rebuild: capture the 08-10 row, and re-apply it
  afterwards. Add this to the Phase 5 checklist — it is easy to forget and
  impossible to undo.
- This is the concrete form of V10's point: `portfolio_positions` is
  `trade_log × an external mutable feed`, and the feed has permanently dropped a
  bar we captured.

### V13 — Rebuild output has an irreducible noise floor; byte-identity is not a valid criterion

Phase 2.5 measured this. The rebuild re-fetches Yahoo on every run, so two runs of
**identical code** cannot be byte-identical on price-derived columns. Diff of the
Gate 2 vs Phase 2.5 RRSP clone (17,484 joined rows), independently reproduced:

| Column group | Diffs | Meaning |
|---|---|---|
| `shares`, `cost_basis`, `currency`, `date`, `base_currency`, `exchange_rate`, `cost_basis_base` | **0** | Everything the caching could touch — provably inert |
| `price`, `total_value` | 3 | ±$0.01 Yahoo reprints (stored price is cent-rounded) |
| `pnl`, `total_value_base`, `pnl_base` | 59 / 81 / 72 | Computed from the *unrounded* close, so they move when the cent-rounded price does not |

Noise floor, by date: **only the current date exceeds $0.01** (max $0.40, its bar
is still live). Every historical date maxes at **exactly $0.01** — scattered,
uncorrelated single-cent rounding flips on 1–3 tickers.

`exchange_rate` = 0 and `cost_basis_base` = 0 across all rows is the decisive
proof the FX memoization is inert: one wrong cached rate would diverge for every
USD position on that date. A cache defect produces *correlated* error; this is
uncorrelated.

**Correct acceptance criterion for any rebuild-vs-rebuild diff** (supersedes the
"byte-identical" wording in Phase 2.5):

1. Zero diffs on `shares`, `cost_basis`, `currency`, `date`, `base_currency`,
   `exchange_rate`, `cost_basis_base` — non-negotiable.
2. Price-derived diffs ≤ $0.01 on any date before today; larger deltas allowed
   only on the current date, and only if that date's bar was live between runs.
3. Anything outside that envelope is a real regression and must be explained.

### V12 — Gate 2 outcome: 39 diffs, all baseline defects, rebuild correct in every case

The §2.3 diff was not zero. All 39 rows were individually attributed; in every
case the rebuild matches `trade_log` and the stored baseline does not.

- **37 TFSA rows** — DRIP trades (20:00 UTC) missing from the baseline from their
  own trade date until 2026-06-30, when a daily run self-corrected. 9 tickers
  dated 06-25 × 3 days + 4 dated 06-26 × 2 days + ZEA.TO on 06-29 = 36, plus MU.
  Cause: the only `backfill_portfolio_prices_range` run in `job_executions`
  **failed on 2026-06-27**, between 06-26 and 06-29.
- **MU 2026-07-20** — baseline − rebuild = 0.000111, exactly the MU DRIP, which
  is dated 2026-07-21. Baseline applied it a day early.
- **NXTG.TO 2026-06-29, both funds** — baseline had 71/72 tickers vs 72/73 on
  adjacent days, NXTG.TO absent. Textbook V6: old code dropped an unpriced ticker
  and replaced the whole day. F5 carry-forward repaired it.

**Gate 2 = PASS.** The criterion is "zero *unexplained* mismatches, and zero cases
where the rebuild is wrong" — met. Do not read this as licence to wave through
future diffs: the standard is per-row attribution with `trade_log` as arbiter,
not a tolerance band.

Corollary: Gate 0's reconciliation (zero mismatches vs `trade_log`) was correct
but only sampled the **latest** date, where the baseline had already
self-corrected. It did not and could not detect the June staleness.

Follow-up for Phase 2.5: successful **carry-forwards are invisible** in the
dry-run summary — `missing_price_days` is only populated when carry-forward also
fails. MNST 2026-08-10 was silently priced at the 08-07 close (90.36), carried
across a 2:1 split, with no warning line. Track and report carry-forward usage
separately.

### V11 — Trade application must use `<= trading_day`, not date equality

Found at Gate 1. The rebuild applied trades by date equality against the trading
calendar, so trades dated on a non-trading day were dropped entirely. TFSA has 5
such rows — Sunday-dated DRIP reinvestments (AEM.TO, AOS, CHD, EXPD, KO,
0.0012–0.0066 sh each).

The stored baseline **does** include them: `backfill_portfolio_prices_range`
filters `trades_up_to_date = [t for t in trades if t['_parsed_date'] <= target_date]`.
Verified — `stored_shares` equals the full `trade_log` sum including Sunday rows
for all five tickers.

Resolution: the rebuild's day loop uses an advancing cursor applying all
not-yet-applied trades with `date <= trading_day`, matching the reference
implementation. This subsumes the pre-window FIFO seed into the same mechanism.

**Phase 2's zero-share-mismatch criterion stays binary.** Tolerating "small"
fractional diffs would make every future mismatch a judgement call and destroy
the gate's value.

### V10 — The stored data is NOT corrupt; the rebuild bugs have never run here

Full reconciliation at Gate 0: derive each ticker's share count from `trade_log`
alone and compare to the latest `portfolio_positions` row, for all three
production funds. **Zero mismatches across ~190 ticker-positions.** No per-day
ticker-count cliffs in 247 days × 3 funds. MNST's history shows correct
*time-varying* share counts (26 until 2025-12-19, then 13) — if V3's aliasing had
ever been applied to this range, every day would read 13.

Consequences for this plan:

- The displayed values have been correct except MNST from 2026-08-10 — **0.19% of
  NAV** in both funds. This is a small, recent, contained error.
- **MNST reconciles perfectly between `trade_log` and `portfolio_positions`
  (both say 13 shares).** The system is internally consistent and wrong relative
  to reality, because the *trade log itself* is missing the split. A rebuild
  would faithfully reproduce 13 shares forever. This is why the 4-row
  `trade_log` update in Phase 4.2 is the actual fix and the position repair in
  4.4 is only a cache refresh.
- The architecture (positions derived from `trade_log`) is sound. It is
  temporarily untrustworthy for two reasons only: the derivation also depends on
  an external mutable price feed that has changed its answer for MNST (V1), and
  the rebuild path is lossy (V2/V3/V4). Phase 1 fixes the second; Phase 5's
  deferred follow-up handles the first. After that, rebuild-from-trade-log is
  the correct and preferred repair tool again.

### V9 — Pre-existing conditions found at Gate 0 (do not "fix" in this project)

- **TFSA `performance_metrics` has an ~8-month hole**: 0–1 rows/month from
  2025-10 through 2026-05, vs ~20/month for RRSP over the same span (77 rows
  total vs 246). Pre-dates this work and is unrelated to the split. The days
  Phase 4.5 touches (2026-08-10, 08-11) *are* present for both funds, so the
  targeted recalc is unaffected. **Do not widen the Phase 4.5 date range to
  chase this** — that is exactly the kind of scope creep that turns a 6-row
  repair into a full rebuild.
- **Full-fund position counts** (use these in gate reports, not V2's numbers):
  RRSP Lance Webull 17,483 rows / 247 days / 79 tickers; TFSA 17,610 / 247 / 77.
  V2's 17,334 and 17,461 were measured at `date_only >= '2025-09-03'`.
- **The Phase 0 backup covers `>= 2025-09-01` only**, leaving 121 position rows
  per fund and the 2025-08-25→08-31 metrics outside the rollback path. Adequate
  for Phase 4 (which touches 2026-08-10+ only). Widen the filter on the Phase 4.1
  re-export if any earlier-dated write is ever contemplated.

## Why the original plan was wrong, in one line

It assumed Yahoo had back-adjusted the price history (V1 — it has not), and it
routed the fix through a rebuild function with four independent
history-destroying defects (V2–V6).

## What the original plan got right — keep this

The `trade_log` transform is correct and is retained unchanged:

- `shares *= ratio`
- `price /= ratio`
- `cost_basis` unchanged

Verified invariant: the SELL row's `cost_basis` is proceeds (13 × 76.66 =
996.58), so `shares × price` is preserved by the transform for both BUY and SELL
rows. Realized P&L stays $181.48 (RRSP) / $6.83 (TFSA).

---

## Ground rules for every phase

1. **No writes to `Project Chimera`, `RRSP Lance Webull`, or `TFSA` before
   Phase 4.** All experimentation happens on the TEST clones.
2. Every destructive step is preceded by a `--dry-run` whose output is pasted
   into the review gate.
3. Service-role Supabase client only, same pattern as the existing rebuild
   scripts. Never hand-edit `portfolio_positions` outside the SQL in this plan.
4. Do not touch the local CSVs — they are stale backups, not source of truth.
5. Windows/PowerShell: use `.\venv\Scripts\python.exe` from the repo root (or
   the `web_dashboard` venv per AGENTS.md) — do not assume a POSIX shell.
6. If any acceptance check in a phase fails, **stop at that phase's gate**.
   Do not "fix forward" into the next phase.

---

## Phase 0 — Safety net and TEST clones

Nothing here modifies production data.

### 0.1 Export the blast radius to disk

Write `debug/export_fund_snapshot.py` (or a one-off script) that dumps, to
timestamped JSON under `debug/backups/`:

- `trade_log` for `RRSP Lance Webull` and `TFSA` (89 + 208 rows)
- `portfolio_positions` for both funds where `date_only >= '2025-09-01'`
  (17,334 + 17,461 rows)
- `performance_metrics` for both funds where `date >= '2025-09-01'`

Paginate at 1000 rows — PostgREST truncates silently otherwise (see the recent
`fetch_all_rows` work in `scheduler/jobs_portfolio.py`). Assert the row counts
above before declaring success.

Also check whether Supabase PITR is enabled for this project. If it is not, this
JSON export is the *only* rollback path, so verify the files are non-empty and
re-readable before proceeding.

### 0.2 Create the TEST funds

Two clones, because they exercise different code paths:

- `TEST MNST RRSP` ← `RRSP Lance Webull` (cash dividend mode, whole shares,
  only 5 trade dates, mislabeled `action` rows — the hard case)
- `TEST MNST TFSA` ← `TFSA` (reinvest mode, fractional shares, 127 real
  `DIVIDEND` rows)

```sql
-- Fund rows. is_production is omitted so it defaults to false, which keeps
-- every scheduler job away from these funds (see V7).
insert into funds (name, description, currency, fund_type, base_currency, dividend_mode)
select 'TEST MNST RRSP', 'Throwaway clone for MNST split work', currency, fund_type, base_currency, dividend_mode
from funds where name = 'RRSP Lance Webull';

insert into funds (name, description, currency, fund_type, base_currency, dividend_mode)
select 'TEST MNST TFSA', 'Throwaway clone for MNST split work', currency, fund_type, base_currency, dividend_mode
from funds where name = 'TFSA';

-- Trades.
insert into trade_log (fund, ticker, date, shares, price, cost_basis, pnl, currency, reason, action)
select 'TEST MNST RRSP', ticker, date, shares, price, cost_basis, pnl, currency, reason, action
from trade_log where fund = 'RRSP Lance Webull';

insert into trade_log (fund, ticker, date, shares, price, cost_basis, pnl, currency, reason, action)
select 'TEST MNST TFSA', ticker, date, shares, price, cost_basis, pnl, currency, reason, action
from trade_log where fund = 'TFSA';

-- Positions. Never write id, date_only (trigger) or total_value (generated).
insert into portfolio_positions
  (fund, ticker, shares, price, cost_basis, pnl, currency, date,
   base_currency, total_value_base, cost_basis_base, pnl_base, exchange_rate)
select 'TEST MNST RRSP', ticker, shares, price, cost_basis, pnl, currency, date,
       base_currency, total_value_base, cost_basis_base, pnl_base, exchange_rate
from portfolio_positions where fund = 'RRSP Lance Webull';

insert into portfolio_positions
  (fund, ticker, shares, price, cost_basis, pnl, currency, date,
   base_currency, total_value_base, cost_basis_base, pnl_base, exchange_rate)
select 'TEST MNST TFSA', ticker, shares, price, cost_basis, pnl, currency, date,
       base_currency, total_value_base, cost_basis_base, pnl_base, exchange_rate
from portfolio_positions where fund = 'TFSA';
```

### 0.3 Freeze a baseline for the Phase 2 diff

Snapshot the cloned positions into a comparison table so Phase 2 can diff
against the pre-rebuild state without a second network round trip:

```sql
create table if not exists tmp_mnst_baseline as
select fund, ticker, date_only, shares, cost_basis, price
from portfolio_positions
where fund in ('TEST MNST RRSP', 'TEST MNST TFSA');
```

### Acceptance criteria

- `debug/backups/` holds JSON for both funds with the exact row counts above.
- `select fund, count(*) from portfolio_positions where fund like 'TEST MNST%' group by fund`
  returns 17,334 and 17,461 (matching the sources for `date_only >= '2025-09-01'`
  plus any earlier rows — assert equality against the source fund, not a literal).
- `select name, is_production from funds where name like 'TEST MNST%'` returns
  `false` for both.
- Production `portfolio_positions` and `trade_log` row counts are **unchanged**.

### REVIEW GATE 0
Report: backup file paths and sizes, clone row counts vs source, PITR status.

---

## Phase 1 — Fix `rebuild_from_date.py` (code + unit tests, no DB writes)

All five defects, plus a dry-run mode. No database is touched in this phase —
the tests must run against fixtures/mocks.

### F1 — `NameError` on the `job_id` path (V5)
`web_dashboard/utils/rebuild_from_date.py:271-284`. Move the
`_update_job_status(... 'Step 4 of 6' ...)` call to *after* `tickers_to_price`
is populated, or compute the set first. This is a two-line fix.

### F2 — Write a snapshot for every trading day, not just trade dates (V2)
Replace the `all_dates = trade_df['Date'].dt.date.unique()` loop with a loop
over `trading_days_to_rebuild`, computing positions as-of each day. The correct
pattern already exists in this repo — mirror
`scheduler/jobs_portfolio.py:1530-1572` (`backfill_portfolio_prices_range`),
which filters `trades_up_to_date = [t for t in trades if t['_parsed_date'] <= target_date]`
and builds a fresh `running_positions` per day.

Note the O(days × trades) cost of that approach is irrelevant here (241 days ×
≤208 trades), and correctness beats cleverness. If you prefer to keep the
single-pass running accumulator, you must carry it forward across non-trade days
*and* deep-copy per day (F3).

### F3 — Deep-copy the per-day position snapshot (V3)
`rebuild_from_date.py:269`. `dict(running_positions)` is a shallow copy. Either
rebuild a fresh dict per day (F2's approach makes this automatic) or use an
explicit per-ticker copy. Do the same in
`debug/rebuild_portfolio_complete.py:674`.

### F4 — Skip dividends by `action`, not by reason prose (V4)
`rebuild_from_date.py:229-235`. Replace the `is_dividend_reason(reason)` check
with `action == 'DIVIDEND'` (the `Trade` model already carries a trustworthy
`action` — `field_mapper.py:263-267` honours the stored column). Leave
`is_dividend_reason` in place for other callers; just stop using it for the
skip decision here.

The two mislabeled prod rows are repaired in Phase 4, not here. But **repair
them on the TEST clones now** so Phase 2's diff is meaningful:

```sql
update trade_log set action = 'BUY'
where fund = 'TEST MNST RRSP' and ticker in ('FTS.TO', 'KO') and action = 'DIVIDEND';
```

### F5 — Never silently drop a held ticker from a snapshot (V6)
`rebuild_from_date.py:344-348`. Carry the last known price forward, as
`jobs_portfolio.py:1594-1604` does. If a held ticker still has no price on a
given day, **skip writing that entire day** (and log loudly) rather than writing
a snapshot with a hole in it — a partial snapshot understates fund totals and is
worse than a missing day.

### F6 — Add `--dry-run` (new, and the most important guardrail)
`rebuild_fund_from_date(..., dry_run: bool = False)`. When set: do everything
except the deletes and the writes, and print a summary:

```
Fund: TEST MNST RRSP   Range: 2025-09-03 .. 2026-08-12
Would DELETE  17,334 position rows /   241 metric rows
Would WRITE   17,334 position rows /   240 metric rows
Days covered: 241 of 241 trading days   (0 days would be lost)
Tickers with missing prices: MNST (2 days: 2026-08-10, 2026-08-11)
```

Add a hard safety check that runs in **both** modes: if the rebuild would write
fewer days than it deletes, abort with a non-zero exit and an explicit message,
unless `--allow-day-loss` is passed. This single check would have caught V2.

Wire `--dry-run` through `manual_rebuild.py` and **make dry-run the default**
there; require an explicit `--apply` to write.

### Tests — `tests/test_rebuild_from_date.py` (new)

One test per defect, each of which must fail against the current code:

1. **Sparse trade dates** — fund with trades on 2 days inside a 10-trading-day
   range produces **10** snapshots, not 2. (F2)
2. **Historical share counts** — buy 26 on day 1, sell 13 on day 5; assert day 3
   shows 26 shares and day 7 shows 13. (F3)
3. **Dividend-word thesis** — a cash-dividend fund with a BUY whose reason is
   `"...decades of dividend growth..."` and `action='BUY'` keeps the position.
   (F4)
4. **Mislabeled action still skipped** — same row with `action='DIVIDEND'` *is*
   skipped, proving the skip now keys on `action` and documenting why the Phase 4
   data repair is required.
5. **`job_id` path executes** — call with `job_id='123'` and a patched
   `_update_job_status`; assert no `NameError` and that Step 4's status message
   is emitted. (F1)
6. **Missing price** — a held ticker with no price on day 3 carries the day-2
   price forward; a ticker with no price at all causes the day to be skipped
   entirely rather than written short. (F5)
7. **Day-loss guard** — a scenario that would lose days aborts without deleting.
   (F6)

Mock Supabase and `MarketDataFetcher`; no network, no DB. Follow the existing
fixture style in `tests/test_jobs_dividends_dividend_mode.py`.

### Acceptance criteria

- All 7 new tests pass; each was demonstrated failing before the corresponding fix.
- `python run_tests.py` (or the project's usual runner) is green — no regressions.
- Zero production rows written. Confirm with a `select count(*)` before/after.

### REVIEW GATE 1
Report: the diff, test names + pass/fail output, and the before-fix failure
output for each of the 7 tests.

---

## Phase 2 — Validate the fixed rebuild on the TEST clones

The goal is an **equivalence test**: rebuilding a fund whose trades have *not*
been modified should reproduce the data that the daily job already produced.

### 2.1 Dry-run first

```powershell
.\venv\Scripts\python.exe web_dashboard\manual_rebuild.py "TEST MNST RRSP" "2025-09-03" --dry-run
.\venv\Scripts\python.exe web_dashboard\manual_rebuild.py "TEST MNST TFSA" "2025-09-03" --dry-run
```

Expected: "would write 241 of 241 trading days", 0 days lost, MNST flagged as
missing prices on 2026-08-10 and 2026-08-11.

### 2.2 Apply to the TEST funds only

```powershell
.\venv\Scripts\python.exe web_dashboard\manual_rebuild.py "TEST MNST RRSP" "2025-09-03" --apply
.\venv\Scripts\python.exe web_dashboard\manual_rebuild.py "TEST MNST TFSA" "2025-09-03" --apply
```

### 2.3 Diff against the frozen baseline

```sql
-- Shares and cost_basis must match EXACTLY. Prices may differ (Yahoo close vs
-- the price captured live by the daily job), so they are reported, not asserted.
select b.fund, b.ticker, b.date_only,
       b.shares as old_shares, p.shares as new_shares,
       b.cost_basis as old_cost, p.cost_basis as new_cost
from tmp_mnst_baseline b
full outer join portfolio_positions p
  on p.fund = b.fund and p.ticker = b.ticker and p.date_only = b.date_only
where b.shares is distinct from p.shares
   or b.cost_basis is distinct from p.cost_basis
order by b.fund, b.date_only, b.ticker;
```

### Acceptance criteria

- **Day coverage:** `count(distinct date_only)` per TEST fund is unchanged (241).
- **Ticker coverage:** per-day ticker counts unchanged (72 for the RRSP clone on
  recent days), except where F5 legitimately skips a day — which must be zero here.
- **Shares:** the diff query returns **zero** share mismatches. Any mismatch is a
  stop-the-line failure.
- **Cost basis:** zero mismatches.
- **FTS.TO, KO, PEP** are present in the rebuilt `TEST MNST RRSP` on 2026-08-12
  with 47 / 24 / 6 shares. (This is the V4 regression check against real data.)
- **MNST** is present on 2026-08-10 and 2026-08-11 via carry-forward, not missing.
- Price differences are expected and should be *reported* with their magnitude;
  anything beyond normal close-vs-intraday drift needs explaining before Phase 3.
- Production funds untouched.

### REVIEW GATE 2
Report: dry-run output, the full diff query result, per-day coverage counts, and
the FTS.TO/KO/PEP presence check.

---

## Phase 2.5 — Rebuild write-path performance

Observed at Gate 2: the RRSP clone apply ran at **~45s per trading day** (~3h for
241 days). The cause is read amplification in `save_portfolio_snapshot`, not the
writes — positions are already sent as one batched `upsert`.

**Do not start this phase until both clones have finished and Gate 2 is signed
off.** Changing the code between the RRSP and TFSA runs would validate the two
clones against different logic and void the gate.

### Measured baseline (RRSP, 72 held tickers: 52 USD / 20 CAD)

| Source | Calls/day | Note |
|---|---|---|
| `get_exchange_rate_for_date_from_db` | **52** | `supabase_repository.py:410` — one per USD position, all with the same `snapshot.timestamp` and the same USD→CAD pair |
| `ensure_ticker_in_securities` | **72** | `supabase_repository.py:449` — one `securities` select per ticker, same ~79 tickers every day |
| `funds` base_currency lookup | 1 | Re-read on every snapshot |
| dup-detection `get_portfolio_data` | 1 | Returns 0 rows during a rebuild (Step 5 already deleted the range) |
| delete + batched upsert | 2 | Already efficient — leave alone |
| **Total** | **~128** | ~124 redundant; at ~350ms each ≈ 45s |

### Two facts that de-risk the fix

- **`exchange_rates` holds exactly one row per day** (482 rows / 482 distinct
  days, USD→CAD only). So memoizing on `(date, from_currency, to_currency)` is
  *provably equivalent* to the current "most recent on or before this timestamp"
  lookup. This is not an approximation.
- **All 75 currently-held tickers have complete `securities` metadata**, so
  `ensure_ticker_in_securities` returns early at `supabase_repository.py:147`
  after one select — the `yf.Ticker().info` branch is not being hit today. But it
  is a latent cliff: one new or stale-metadata ticker would add a *network* call
  per ticker **per day of the rebuild**. Caching removes that hazard as well as
  the current cost.

### Fixes

1. **Memoize the exchange rate** by `(date, from, to)`. The reference
   implementation already exists — `get_cached_exchange_rate` /
   `exchange_rate_cache` at `scheduler/jobs_portfolio.py:1495-1520`. 52 → 1/day.
2. **Instance-level verified-ticker set** on `SupabaseRepository` for
   `ensure_ticker_in_securities`; populate only on a successful verify/insert so
   a failure is retried rather than cached. 72 → ~0 after day one.
3. **Hoist the `funds` base_currency read** out of the per-snapshot path. 241 → 1.

Leave the dup-detection `get_portfolio_data` call alone — it is 1 query/day and
removing it touches the market-close protection logic for no meaningful gain.

Expected: ~128 → ~4 round trips/day, i.e. ~45s → 1–2s per day (~3h → <10 min).

### Verification — byte-identical output

Caching changes are exactly the kind of "obviously safe" edit that earns its own
verification, and here one is free:

1. Keep the Gate 2 rebuilt positions for one clone (snapshot them to a table,
   e.g. `tmp_gate2_rrsp`, before re-running).
2. Re-run the same rebuild on the same clone with the perf changes applied.
3. Diff **every** column, not just shares/cost. The result must be identical —
   any difference at all means the caching changed behaviour and must be
   explained before proceeding.

### Acceptance criteria

- Per-day wall time drops to ≤5s for the RRSP clone.
- Re-run output is byte-identical to the Gate 2 result on all columns.
- The full Phase 1 test suite still passes unchanged.
- No production fund touched.

### REVIEW GATE 2.5
Report: before/after per-day timing, the byte-identical diff result, and the test
suite run.

### Why this is not on the MNST critical path

Phase 4 is six `UPDATE` statements and no rebuild, so the MNST fix does not need
this. It matters for **Phase 5's deferred full rebuild** once Yahoo
back-adjusts: two production funds × 241 days at 45s/day is ~6 hours of live
writes against prod, versus a few minutes once fixed. Do this before that runs.

---

## Phase 3 — `debug/apply_stock_split.py` + end-to-end on TEST funds

### 3.1 The script

```text
python debug/apply_stock_split.py --fund "TEST MNST RRSP" --ticker MNST --ratio 2 --dry-run
python debug/apply_stock_split.py --fund "TEST MNST RRSP" --ticker MNST --ratio 2 --apply
```

Behaviour:

- Service-role Supabase client only.
- Pure, unit-testable helper: `adjust_trade_for_split(shares, price, ratio) -> (shares, price)`.
  `cost_basis` is deliberately *not* an input — it is invariant.
- Prints a before/after table for every matched `trade_log` row plus the implied
  open position.
- `--apply` updates `trade_log` rows only. **It never rebuilds** — that stays an
  explicit, separate step.
- Refuses when: `ratio < 1`; zero rows matched; or the target fund has
  `is_production = true` and `--i-know-this-is-prod` was not passed.
- Uses `Decimal`, not float, for the arithmetic.
- Emits the exact follow-up repair command to run next.

### 3.2 Tests — `tests/test_apply_stock_split.py`

- `adjust_trade_for_split(26, 62.70, 2) == (52, 31.35)`; `shares * price` invariant.
- Fractional case: `adjust_trade_for_split(0.978538, 62.70, 2)` — assert
  `shares * price` is preserved to the cent, and that the doubled share count
  round-trips (this is the TFSA case, and float drift here would be silent).
- `ratio < 1` raises.
- Reverse-split guard and zero-row guard.

### 3.3 End-to-end rehearsal on the TEST funds

1. `--dry-run` both TEST funds; confirm 2 rows each match the table in V8.
2. `--apply` both.
3. Verify `trade_log`: RRSP clone shows BUY 52 @ $31.35 (cost 1630.20) and
   SELL 26 @ $38.33 (cost_basis 996.58, pnl 181.48); TFSA clone shows
   BUY 1.957076 @ $31.35 and SELL 0.978538 @ $38.33.
4. Apply the Phase 4 repair SQL (below) to the TEST funds and verify the
   expected values.
5. **Also rehearse the thing we are choosing not to do**, so the decision is
   evidence-backed: run `manual_rebuild.py "TEST MNST RRSP" "2025-09-03" --dry-run`
   *after* the split is applied and confirm it reports the ~2× overstatement
   across pre-split days. Paste that output into the gate. Do not `--apply` it.

### Acceptance criteria

- All split-helper tests pass.
- TEST fund `trade_log` matches the expected values above exactly.
- The post-repair TEST positions match the V8 "should be" column.
- The step-5 dry-run demonstrates the overstatement, confirming V1.
- Production funds untouched.

### REVIEW GATE 3
Report: dry-run and apply output, resulting trade rows, repair verification, and
the step-5 dry-run showing why the full rebuild is deferred.

---

## Phase 4 — Apply to production

Only after gates 0–3 are signed off. Total prod writes: **6 `trade_log` rows and
6 `portfolio_positions` rows.** No rebuild.

### 4.1 Re-run the Phase 0 backup

Data has moved since Phase 0 (the daily job runs). Re-export before writing.

### 4.2 Split-adjust the trade log (4 rows)

```powershell
.\venv\Scripts\python.exe debug\apply_stock_split.py --fund "RRSP Lance Webull" --ticker MNST --ratio 2 --dry-run
.\venv\Scripts\python.exe debug\apply_stock_split.py --fund "TFSA" --ticker MNST --ratio 2 --dry-run
# review output, then:
.\venv\Scripts\python.exe debug\apply_stock_split.py --fund "RRSP Lance Webull" --ticker MNST --ratio 2 --apply --i-know-this-is-prod
.\venv\Scripts\python.exe debug\apply_stock_split.py --fund "TFSA" --ticker MNST --ratio 2 --apply --i-know-this-is-prod
```

### 4.3 Repair the 2 mislabeled `action` rows (V4)

Required so that any *future* rebuild does not delete FTS.TO and KO.

```sql
-- Verify first (expect exactly 2 rows: FTS.TO 47 sh, KO 24 sh)
select ticker, date::date, shares, price, action
from trade_log where fund = 'RRSP Lance Webull' and action = 'DIVIDEND';

update trade_log set action = 'BUY'
where fund = 'RRSP Lance Webull' and ticker in ('FTS.TO', 'KO') and action = 'DIVIDEND';
```

### 4.4 Repair the 3 affected days (6 rows)

No price fetch needed — the stored prices on these days are already
split-adjusted (V8). All right-hand references to `shares` see the pre-update
value, so this single statement is self-consistent.

```sql
-- Before
select fund, date_only, shares, price, total_value, pnl, total_value_base, pnl_base
from portfolio_positions
where ticker = 'MNST' and fund in ('RRSP Lance Webull', 'TFSA') and date_only >= '2026-08-10'
order by fund, date_only;

-- Run per fund. The `shares = <pre-split>` predicate makes this EXACTLY-ONCE:
-- `shares * 2` is not idempotent, and the scheduler is live — once 4.2 lands,
-- the daily job derives 26 shares from the corrected trade_log by itself. Any
-- row it has already fixed must not be doubled again (that yields 52).
update portfolio_positions
set shares           = shares * 2,
    pnl              = round(shares * 2 * price - cost_basis, 2),
    total_value_base = round(shares * 2 * price * exchange_rate, 2),
    pnl_base         = round((shares * 2 * price - cost_basis) * exchange_rate, 2)
where ticker = 'MNST'
  and fund = 'RRSP Lance Webull'
  and date_only >= '2026-08-10'
  and shares = 13;

update portfolio_positions
set shares           = shares * 2,
    pnl              = round(shares * 2 * price - cost_basis, 2),
    total_value_base = round(shares * 2 * price * exchange_rate, 2),
    pnl_base         = round((shares * 2 * price - cost_basis) * exchange_rate, 2)
where ticker = 'MNST'
  and fund = 'TFSA'
  and date_only >= '2026-08-10'
  and shares = 0.489269;
```

**Post-repair sanity check — no row may hold a double-doubled count:**

```sql
select fund, date_only, shares from portfolio_positions
where ticker = 'MNST' and fund in ('RRSP Lance Webull','TFSA')
  and (shares = 52 or shares = 1.957076);   -- must return zero rows
```

`cost_basis`, `cost_basis_base` and `price` are unchanged. `total_value`
recomputes itself (generated column). `date_only` is preserved by the trigger.

**Expected result — verify relationally, not against hardcoded dollars.** Stored
prices drift (2026-08-12 read 45.68 when this plan was written and 45.98 at
Gate 3), and the daily job adds a new row every trading day. The repair does not
touch `price`, so the arithmetic holds at whatever price is stored. Assert:

1. `shares` exactly doubled on every affected row — 13 → 26 (RRSP),
   0.489269 → 0.978538 (TFSA). No other ticker's shares changed.
2. `cost_basis` unchanged: 815.10 (RRSP) / 30.68 (TFSA). Same for
   `cost_basis_base`.
3. `total_value = shares × price` (generated column recomputes itself).
4. `pnl = total_value − cost_basis`, and `pnl > 0` — roughly **+45–47%** of cost
   on every affected day.
5. `total_value_base = total_value × exchange_rate` and
   `pnl_base = pnl × exchange_rate`, using each row's own stored rate.
6. Row count updated == number of MNST rows with `date_only >= '2026-08-10'` at
   the moment of the run — enumerate them in the "before" SELECT and confirm the
   UPDATE touched exactly that many.

Reference values at Gate 3 prices, for sanity only:

| Fund | Date | price | shares | total_value | pnl |
|---|---|---|---|---|---|
| RRSP | 2026-08-10 | 45.72 | 26 | 1188.72 | +373.62 |
| RRSP | 2026-08-11 | 45.53 | 26 | 1183.78 | +368.68 |
| RRSP | 2026-08-12 | 45.98 | 26 | 1195.48 | +380.38 |
| TFSA | 2026-08-10 | 45.72 | 0.978538 | 44.74 | +14.06 |
| TFSA | 2026-08-11 | 45.53 | 0.978538 | 44.55 | +13.87 |
| TFSA | 2026-08-12 | 45.98 | 0.978538 | 44.99 | +14.31 |

The 08-11 and 08-12 rows were rehearsed exactly on the clones. The 08-10 rows
were **not** — see V14 — so check those two against the arithmetic above with
extra care.

### 4.5 Recalculate `performance_metrics` for those days only

```powershell
.\venv\Scripts\python.exe -c "from web_dashboard.scheduler.jobs_metrics import populate_performance_metrics_job; from datetime import date; populate_performance_metrics_job(from_date=date(2026,8,10), to_date=date(2026,8,12), fund_filter='RRSP Lance Webull', skip_existing=False)"
```
Repeat for `TFSA`. Do **not** widen the date range.

### Acceptance criteria

- MNST positions: 26 sh / 0.978538 sh, cost unchanged at $815.10 / $30.68,
  unrealized P&L ≈ **+46%**, not −27%.
- No ~50% MV cliff between 2026-08-07 and 2026-08-10 in either fund's series.
- `select count(*) from portfolio_positions where fund = 'RRSP Lance Webull'` is
  **unchanged** from the pre-Phase-4 count. Same for TFSA. (If this changed, a
  rebuild ran — stop and restore.)
- FTS.TO / KO / PEP still present with 47 / 24 / 6 shares.
- Realized P&L still $181.48 / $6.83.
- Dashboard holdings and fund totals spot-check clean for both funds.

### REVIEW GATE 4
Report: before/after SQL output for all 6 rows, row-count invariants, metrics
recalc output, and a dashboard screenshot or holdings dump.

---

## Phase 5 — Guardrails, docs, cleanup

1. **`debug/README.md`** — replace the "no corporate-action tooling" note
   (L105–122) with `apply_stock_split.py` usage, and state plainly that a split
   adjustment must be paired with a *targeted* position repair, **not** a full
   historical rebuild, until the data provider has back-adjusted its series.
2. **Record the corporate action.** Even a simple `docs/corporate_actions.md`
   row (ticker, ratio, ex-date, funds affected, date applied, method) is enough.
   Without it, the next person to run a full rebuild will silently reintroduce
   the 2× overstatement, because `trade_log` is now split-adjusted while the
   pre-2026-08-11 price history is not.
3. **Fix `infer_trade_action` prose matching** (root cause of V4) or, at minimum,
   file it with a repro: a BUY thesis containing "dividend growth" is classified
   `DIVIDEND`. Note that `admin_routes.py:2498` and `:2662` re-infer `action`
   from the reason on every trade edit, so editing FTS.TO or KO in the admin UI
   will re-corrupt the rows repaired in 4.3.
4. **Drop the TEST funds and scratch table** once gate 4 is signed off:
   ```sql
   delete from portfolio_positions where fund like 'TEST MNST%';
   delete from performance_metrics  where fund like 'TEST MNST%';
   delete from trade_log            where fund like 'TEST MNST%';
   delete from funds                where name like 'TEST MNST%';
   drop table if exists tmp_mnst_baseline;
   ```
   Order matters — the FKs on `fund` require children first.
5. **`graphify update .`** after the code changes land.

### Deferred follow-up — re-check Yahoo

Yahoo currently has the split half-applied: the event is recorded, the history is
not adjusted, and 2026-08-10/11 are missing. Re-run the V1 reproduce command in
a week or two. **Once the history is back-adjusted and the gaps are filled**, a
full rebuild from 2025-09-03 becomes both safe (post-Phase-1 fixes) and correct
— and at that point it is worth doing, because it will make the whole series
internally consistent with the split-adjusted `trade_log`. Until then, the
current mixed state is the intended, documented outcome.

---

## Out of scope

- Auto-detecting future splits; Wealthsimple sync.
- Editing the local CSV backups.
- `Project Chimera` (no MNST). Its 3 dividend-prose BUYs are correctly labelled
  and it is `reinvest` mode, so it is unaffected — note it, do not change it.
- A full corporate-actions table/DB.
- Rewriting `backfill_portfolio_prices_range`, though it is the better-written of
  the two rebuild paths and is the reference implementation for F2/F3/F5.

## Risk register

| Risk | Mitigation |
|---|---|
| Accidental full rebuild on prod | Dry-run default in `manual_rebuild.py`; day-loss guard (F6); Phase 0 backup |
| Admin UI trade edit triggers the broken rebuild | F1 fixes the crash; do not edit MNST in the UI before Phase 4 |
| Admin UI edit re-corrupts `action` | Documented in Phase 5.3; avoid editing FTS.TO / KO |
| Yahoo back-adjusts mid-project, changing expected values | Re-run the V1 check at the start of each phase; values in V8 assume unadjusted history |
| Float drift on the fractional TFSA position | `Decimal` throughout; explicit test in 3.2 |
| PITR unavailable | Phase 0 JSON export is the rollback path; verify it is readable |
