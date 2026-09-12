-- Tickers the Grok Bot weekday sweep should not spend X credits on.
-- source='auto'   : filed by the ingest after a brief came back with zero posts.
-- source='manual' : curated (broad-market ETFs, sector duplicates).
-- Un-skipping is a row delete; nothing here is permanent by design.
CREATE TABLE IF NOT EXISTS grok_x_skips (
    ticker VARCHAR(20) NOT NULL,
    reason VARCHAR(200) NOT NULL,
    source VARCHAR(10) NOT NULL DEFAULT 'manual'
        CHECK (source IN ('auto', 'manual')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker)
);

CREATE INDEX IF NOT EXISTS idx_grok_x_skips_source
    ON grok_x_skips (source, created_at DESC);

COMMENT ON TABLE grok_x_skips IS
    'Tickers excluded from the Grok Bot queue. auto rows come from zero-post briefs; manual rows are curated. Delete a row to resume sweeping that ticker.';
