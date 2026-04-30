-- Table: ticker_meta_analysis
-- Second-order synthesis: reconciles stored AI/analysis artifacts for one ticker.
-- One row per ticker (upsert on refresh).

CREATE TABLE IF NOT EXISTS ticker_meta_analysis (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    ticker VARCHAR(10) NOT NULL,
    source_analysis_id UUID REFERENCES ticker_analysis (id) ON DELETE SET NULL,
    source_analysis_snapshot_at TIMESTAMPTZ,
    unified_conviction VARCHAR(40),
    confidence_adjusted NUMERIC(4, 3),
    contradictions JSONB,
    what_changed_vs_last_run TEXT,
    action_items TEXT[],
    narrative TEXT,
    full_result JSONB,
    model_used VARCHAR(100),
    requested_by VARCHAR(100),
    artifact_bundle_digest VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT ticker_meta_analysis_ticker_key UNIQUE (ticker)
);

CREATE INDEX IF NOT EXISTS idx_ticker_meta_analysis_ticker ON ticker_meta_analysis (ticker);
CREATE INDEX IF NOT EXISTS idx_ticker_meta_analysis_updated ON ticker_meta_analysis (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_ticker_meta_source ON ticker_meta_analysis (source_analysis_id);

COMMENT ON TABLE ticker_meta_analysis IS
  'LLM synthesis over prior analyses (ticker_analysis, social AI, congress, articles)—not raw market tables';
