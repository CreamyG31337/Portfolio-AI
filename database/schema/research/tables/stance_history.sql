-- Append-only ledger of AI/mechanical stances per ticker (never overwrites).
CREATE TABLE IF NOT EXISTS stance_history (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    ticker VARCHAR(20) NOT NULL,
    fund_key TEXT NOT NULL DEFAULT '',
    source VARCHAR(40) NOT NULL,
    stance VARCHAR(40),
    confidence NUMERIC(5, 4),
    as_of TIMESTAMPTZ NOT NULL DEFAULT now(),
    price_at_stance NUMERIC(14, 4),
    drivers TEXT[],
    risks TEXT[],
    model_used VARCHAR(100),
    requested_by VARCHAR(100),
    source_ref_id UUID,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_stance_history_ticker_source_asof
    ON stance_history (ticker, source, fund_key, as_of DESC);
CREATE INDEX IF NOT EXISTS idx_stance_history_as_of ON stance_history (as_of DESC);

COMMENT ON TABLE stance_history IS
    'Append-only stance ledger; deduped on (ticker, source, fund_key) at insert time';
COMMENT ON COLUMN stance_history.fund_key IS
    'Fund scope for action_queue rows; empty string for fund-agnostic sources';
COMMENT ON COLUMN stance_history.metadata IS
    'Source-specific extras (e.g. ai_review verdict, sentiment, overall_signal)';
