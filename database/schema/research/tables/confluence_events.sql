-- Append-only log of cross-signal confluence events (ROADMAP G4).
-- Records when multiple independent signal families align on a ticker within
-- a short window. Bullish score >= 3 also writes a scoreable stance_history row.
CREATE TABLE IF NOT EXISTS confluence_events (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    ticker VARCHAR(20) NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    direction VARCHAR(10) NOT NULL,   -- 'bullish' | 'risk'
    score INT NOT NULL,
    families JSONB NOT NULL,          -- sorted list of family keys
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_confluence_ticker_asof
    ON confluence_events (ticker, as_of DESC);
CREATE INDEX IF NOT EXISTS idx_confluence_asof ON confluence_events (as_of DESC);

COMMENT ON TABLE confluence_events IS
    'Cross-signal confluence scores when multiple families align on a ticker (G4)';
COMMENT ON COLUMN confluence_events.families IS
    'Sorted JSON array of distinct family keys that fired for this event';
COMMENT ON COLUMN confluence_events.direction IS
    'bullish or risk — tallied separately per ticker';
