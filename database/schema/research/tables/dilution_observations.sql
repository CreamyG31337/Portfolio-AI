-- Append-only log of detected share-count dilution events (ROADMAP G3).
-- A rising shares-outstanding count IS dilution; this records flagged growth
-- per (ticker, window) so the #1 micro-cap killer is visible on holdings the
-- US-only EDGAR filing watch (G2) cannot see (.TO names included). Only flagged
-- observations are persisted; clean readings are not stored.
CREATE TABLE IF NOT EXISTS dilution_observations (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    ticker VARCHAR(20) NOT NULL,
    as_of DATE NOT NULL,
    window_days INT NOT NULL,            -- 30 | 90
    shares_start NUMERIC(20, 2),
    shares_end NUMERIC(20, 2),
    pct_change NUMERIC(10, 2),           -- percent growth over the window
    flagged BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (ticker, as_of, window_days)
);

CREATE INDEX IF NOT EXISTS idx_dilution_obs_ticker_asof
    ON dilution_observations (ticker, as_of DESC);
CREATE INDEX IF NOT EXISTS idx_dilution_obs_asof ON dilution_observations (as_of DESC);

COMMENT ON TABLE dilution_observations IS
    'Flagged shares-outstanding growth events (free dilution detection via yfinance get_shares_full)';
COMMENT ON COLUMN dilution_observations.window_days IS
    'Lookback window the pct_change is measured over (30 or 90 days)';
