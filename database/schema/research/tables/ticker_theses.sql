-- Human-authored thesis threads per ticker (Insights feature).
CREATE TABLE IF NOT EXISTS ticker_theses (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    ticker VARCHAR(20) NOT NULL,
    title TEXT NOT NULL,
    disposition VARCHAR(20) NOT NULL
        CHECK (disposition IN ('bullish', 'bearish', 'neutral')),
    intent VARCHAR(20) NOT NULL
        CHECK (intent IN ('seek_entry', 'seek_exit', 'monitor')),
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived', 'superseded')),
    created_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_reviewed_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,
    archived_by VARCHAR(100),
    embedding vector(1024),
    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_theses_ticker_active
    ON ticker_theses (ticker) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_theses_disposition
    ON ticker_theses (disposition) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_theses_intent
    ON ticker_theses (intent) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_theses_updated
    ON ticker_theses (updated_at DESC);

COMMENT ON TABLE ticker_theses IS
    'Org-wide human thesis threads; multiple active theses per ticker allowed';
