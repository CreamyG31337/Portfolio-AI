-- Daily LLM-backed market backdrop from benchmark stats (not stock picks).

CREATE TABLE IF NOT EXISTS market_daily_brief (
    brief_date DATE NOT NULL PRIMARY KEY,
    headline VARCHAR(200),
    narrative TEXT,
    regime_json JSONB,
    inputs_digest JSONB,
    model_used VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_market_daily_brief_updated ON market_daily_brief (updated_at DESC);

COMMENT ON TABLE market_daily_brief IS 'Cached daily market regime summary from benchmark_data stats + LLM; not trade advice';
