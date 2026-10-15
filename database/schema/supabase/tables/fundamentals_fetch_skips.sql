-- Table: fundamentals_fetch_skips
-- Tickers the fundamentals refresh job should stop re-fetching every night
-- (no yfinance info / not an equity / no fundamental data).  Delete a row to
-- force a retry on the next run.
DROP TABLE IF EXISTS fundamentals_fetch_skips CASCADE;

CREATE TABLE fundamentals_fetch_skips (
    ticker VARCHAR(20) NOT NULL,
    reason VARCHAR(40) NOT NULL,
    failure_count INTEGER NOT NULL DEFAULT 1,
    first_failed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_failed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    retry_after TIMESTAMPTZ NOT NULL,
,
    PRIMARY KEY (ticker)
);

ALTER TABLE fundamentals_fetch_skips ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE fundamentals_fetch_skips IS
    'Tickers whose fundamentals fetch reliably fails; the refresh job skips them '
    'while retry_after is in the future. Delete a row to force a retry.';

-- Indexes
CREATE INDEX idx_fundamentals_fetch_skips_retry_after
    ON fundamentals_fetch_skips (retry_after);
