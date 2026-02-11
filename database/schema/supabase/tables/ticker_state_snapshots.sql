-- Table: ticker_state_snapshots
DROP TABLE IF EXISTS ticker_state_snapshots CASCADE;

CREATE TABLE ticker_state_snapshots (
    ticker TEXT NOT NULL,
    snapshot_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    state JSONB NOT NULL,
    summary TEXT,

    PRIMARY KEY (ticker, snapshot_date)
);

-- Indexes
CREATE INDEX idx_ticker_state_snapshots_ticker_date ON ticker_state_snapshots (ticker, snapshot_date DESC);
CREATE INDEX idx_ticker_state_snapshots_date ON ticker_state_snapshots (snapshot_date);

COMMENT ON TABLE ticker_state_snapshots IS 'Cross-source ticker state snapshots for LLM analysis. Retention: 90 days.';
