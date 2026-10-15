-- Stop retrying failed fundamentals fetches every night.
-- Tickers yfinance cannot serve (404 "Quote not found", non-equity ETF
-- holdings, quotes with no fundamental data) were re-fetched on every run,
-- wasting ~1s of the per-run yfinance budget each.  This table records them
-- with an exponential retry_after (7 days * 2**(failure_count - 1), capped
-- at 90 days, computed by the scheduler).  Delete a row to force a retry.

CREATE TABLE IF NOT EXISTS public.fundamentals_fetch_skips (
    ticker VARCHAR(20) NOT NULL,
    reason VARCHAR(40) NOT NULL,
    failure_count INTEGER NOT NULL DEFAULT 1,
    first_failed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_failed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    retry_after TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (ticker)
);

CREATE INDEX IF NOT EXISTS idx_fundamentals_fetch_skips_retry_after
    ON public.fundamentals_fetch_skips (retry_after);

ALTER TABLE public.fundamentals_fetch_skips ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.fundamentals_fetch_skips IS
    'Tickers whose fundamentals fetch reliably fails; the refresh job skips them '
    'while retry_after is in the future. Delete a row to force a retry.';
