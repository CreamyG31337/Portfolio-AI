-- Measurement rig repair M1: unjam stance_outcomes scoring.
--
-- Problem: score_stance_row() returns None when prices are unavailable, and the
-- caller just increments a counter. Nothing is recorded, so select_unscored_stances
-- (ORDER BY as_of ASC LIMIT 200) re-fetches the same unscoreable rows every night.
-- Permanently-unscoreable stances (bad symbol, delisting) occupy the head of the
-- queue forever and starve everything newer. Observed: scored=0 skipped=202.
--
-- Fix: record every failed attempt with a reason so (a) rows can be dead-lettered
-- out of the queue after N tries, and (b) "yfinance is rate-limiting" is
-- distinguishable from "this symbol does not exist" in the job summary.
--
-- Additive only. Safe to re-run.

CREATE TABLE IF NOT EXISTS stance_outcome_attempts (
    stance_id UUID NOT NULL,
    horizon_days SMALLINT NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    last_reason TEXT,
    last_attempt_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (stance_id, horizon_days)
);

CREATE INDEX IF NOT EXISTS idx_stance_outcome_attempts_reason
    ON stance_outcome_attempts (last_reason, attempts DESC);

COMMENT ON TABLE stance_outcome_attempts IS
  'Failed stance_outcomes scoring attempts. Rows here are excluded from the scoring queue once attempts >= threshold (dead-letter), preventing head-of-line blocking.';
COMMENT ON COLUMN stance_outcome_attempts.last_reason IS
  'Why scoring failed: no_ticker_price | no_benchmark_price | not_matured | bad_as_of | zero_baseline. Used to tell transient fetch failures from permanently bad symbols.';

-- Resolved price-provider symbol (yfinance) when it differs from the stored ticker.
-- e.g. TECK.B -> TECK-B.TO. Cached after the first successful candidate resolves so
-- the fallback ladder runs once per symbol, not once per run.
ALTER TABLE securities ADD COLUMN IF NOT EXISTS price_symbol TEXT;
ALTER TABLE securities ADD COLUMN IF NOT EXISTS price_symbol_set_at TIMESTAMPTZ;

COMMENT ON COLUMN securities.price_symbol IS
  'Symbol to use with the price provider when it differs from ticker (class shares, TSX suffixes). NULL means use ticker as-is.';
