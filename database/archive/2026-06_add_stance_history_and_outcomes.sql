-- Migration: Add stance_history ledger and stance_outcomes scoring table
-- Date: 2026-06-10
-- Database: Research Postgres (NOT Supabase)
-- Description: Append-only stance ledger (Pillar 1) plus outcome scoring table.
-- Status: Pending apply to production

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

CREATE TABLE IF NOT EXISTS stance_outcomes (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    stance_id UUID NOT NULL REFERENCES stance_history (id) ON DELETE CASCADE,
    horizon_days SMALLINT NOT NULL,
    baseline_price NUMERIC(14, 4),
    end_price NUMERIC(14, 4),
    ticker_return NUMERIC(10, 6),
    benchmark_return NUMERIC(10, 6),
    excess_return NUMERIC(10, 6),
    scored_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT stance_outcomes_unique UNIQUE (stance_id, horizon_days)
);

CREATE INDEX IF NOT EXISTS idx_stance_outcomes_stance ON stance_outcomes (stance_id);

CREATE TABLE IF NOT EXISTS idea_triage (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    article_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL,
    decided_at TIMESTAMPTZ DEFAULT now(),
    decided_by VARCHAR(100),
    notes TEXT,
    snooze_until TIMESTAMPTZ,
    PRIMARY KEY (id),
    CONSTRAINT idea_triage_article_unique UNIQUE (article_id)
);

CREATE INDEX IF NOT EXISTS idx_idea_triage_status ON idea_triage (status, decided_at DESC);
