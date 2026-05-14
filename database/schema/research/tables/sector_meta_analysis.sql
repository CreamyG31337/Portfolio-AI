-- Table: sector_meta_analysis
-- Phase 3b: sector-level synthesis over ETF group AI articles (research DB).
-- One row per (sector, run_date); UPSERT nightly when META_ANALYSIS_PHASE3_SECTOR is on.

CREATE TABLE IF NOT EXISTS sector_meta_analysis (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    sector VARCHAR(120) NOT NULL,
    run_date DATE NOT NULL,
    sector_stance VARCHAR(40) NOT NULL,
    momentum_state VARCHAR(40) NOT NULL,
    news_pressure VARCHAR(40) NOT NULL,
    rotation_rank INTEGER NOT NULL DEFAULT 0,
    confidence NUMERIC(5, 4) NOT NULL,
    key_drivers JSONB NOT NULL DEFAULT '[]'::jsonb,
    risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    as_of TIMESTAMPTZ NOT NULL,
    full_result JSONB,
    model_used VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT sector_meta_analysis_sector_run_date_key UNIQUE (sector, run_date)
);

CREATE INDEX IF NOT EXISTS idx_sector_meta_analysis_sector ON sector_meta_analysis (sector);
CREATE INDEX IF NOT EXISTS idx_sector_meta_analysis_run_date ON sector_meta_analysis (run_date DESC);
CREATE INDEX IF NOT EXISTS idx_sector_meta_analysis_updated ON sector_meta_analysis (updated_at DESC);

COMMENT ON TABLE sector_meta_analysis IS
  'LLM sector rotation synthesis from ETF Analysis articles; JSON contract in docs/meta_analysis_roadmap.md Phase 3';
