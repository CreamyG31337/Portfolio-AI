-- Tier-2 per-fund digest synthesizing tier-1 summaries + market brief (not trade advice).

CREATE TABLE IF NOT EXISTS ui_ai_rollup_fund (
    fund VARCHAR(200) NOT NULL PRIMARY KEY,
    headline VARCHAR(300),
    narrative TEXT,
    sources_used JSONB,
    inputs_digest VARCHAR(64) NOT NULL,
    model_used VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ui_ai_rollup_fund_updated ON ui_ai_rollup_fund (updated_at DESC);

COMMENT ON TABLE ui_ai_rollup_fund IS
    'Cross-screen AI digest per fund; refreshed when market open (scheduler) or inputs change';
