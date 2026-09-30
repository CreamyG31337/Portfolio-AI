-- Measurement rig M2a: per-ticker benchmarks.
--
-- Problem: every stance was scored against a single hardcoded ^RUT, but the stance
-- universe is large-cap US (MSFT, AVGO, QCOM, MRK, COST...), US sector ETFs, and
-- Canadian TSX listings. excess_return was therefore dominated by the large/small
-- cap and US/Canada spreads rather than by whether the call was right.
--
-- Fix: resolve a benchmark per ticker (geography from the symbol suffix, size from
-- market cap) and RECORD IT on every scored row. Recording is the important half:
-- an unrecorded benchmark that changes silently rewrites the track record, which is
-- exactly the failure the append-only stance_history design exists to prevent.
--
-- Additive only. Safe to re-run.

-- Market cap is the only benchmark input that needs a network fetch, so it is the
-- only one cached here. benchmark_symbol itself is DERIVED at scoring time from
-- (ticker suffix, price_symbol, market_cap, currency) so it can never go stale
-- against the rule that produced it.
ALTER TABLE securities ADD COLUMN IF NOT EXISTS market_cap NUMERIC;
ALTER TABLE securities ADD COLUMN IF NOT EXISTS market_cap_set_at TIMESTAMPTZ;

-- Manual escape hatch: pin a benchmark for a ticker the rules get wrong.
-- NULL (the normal case) means "use the derived benchmark".
ALTER TABLE securities ADD COLUMN IF NOT EXISTS benchmark_override TEXT;

COMMENT ON COLUMN securities.market_cap IS
  'Market cap in USD, refreshed periodically from the price provider. Drives the small/large benchmark split (< $2B -> ^RUT).';
COMMENT ON COLUMN securities.benchmark_override IS
  'Manual benchmark pin. NULL means derive from ticker suffix + market_cap.';

-- What each outcome was actually measured against, and under which scoring rules.
-- scoring_version 1 = legacy (everything vs ^RUT); 2 = per-ticker benchmarks.
ALTER TABLE stance_outcomes ADD COLUMN IF NOT EXISTS benchmark_symbol TEXT;
ALTER TABLE stance_outcomes ADD COLUMN IF NOT EXISTS scoring_version SMALLINT DEFAULT 1;

COMMENT ON COLUMN stance_outcomes.benchmark_symbol IS
  'Benchmark this row was scored against. Immutable once written; a benchmark change bumps scoring_version instead of rewriting history.';
COMMENT ON COLUMN stance_outcomes.scoring_version IS
  '1 = legacy single ^RUT benchmark; 2 = per-ticker benchmark (^GSPC / ^RUT / ^GSPTSE). Track-record aggregates should filter to one version.';

CREATE INDEX IF NOT EXISTS idx_stance_outcomes_scoring_version
    ON stance_outcomes (scoring_version, horizon_days);
