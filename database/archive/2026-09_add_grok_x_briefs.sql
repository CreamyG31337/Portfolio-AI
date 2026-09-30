-- Migration: Grok Bot X-listening briefs
-- Date: 2026-09-09
-- Database: Research Postgres (NOT Supabase)

CREATE TABLE IF NOT EXISTS grok_x_briefs (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    fund VARCHAR(50) NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    sweep_date DATE NOT NULL,
    body TEXT NOT NULL,
    themes TEXT[] NOT NULL DEFAULT '{}',
    posts JSONB NOT NULL DEFAULT '[]'::jsonb,
    notable BOOLEAN NOT NULL DEFAULT false,
    cited_urls TEXT[] NOT NULL DEFAULT '{}',
    status VARCHAR(20) NOT NULL DEFAULT 'ingested'
        CHECK (status IN ('ingested', 'evaluated', 'ignored')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT grok_x_briefs_fund_ticker_day UNIQUE (fund, ticker, sweep_date)
);

CREATE INDEX IF NOT EXISTS idx_grok_x_briefs_fund_date
    ON grok_x_briefs (fund, sweep_date DESC);
CREATE INDEX IF NOT EXISTS idx_grok_x_briefs_ticker
    ON grok_x_briefs (ticker, sweep_date DESC);
CREATE INDEX IF NOT EXISTS idx_grok_x_briefs_status
    ON grok_x_briefs (status, created_at DESC);

COMMENT ON TABLE grok_x_briefs IS
    'Grok Bot weekday X sweep briefs; later LLM jobs consume status=ingested. Not a human Insights review.';
