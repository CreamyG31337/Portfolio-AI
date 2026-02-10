-- Migration: Add LLM analysis fields to newsletters table
-- Date: 2026-02-10
-- Database: Research Postgres (NOT Supabase)
-- Description: Newsletters were only storing summary and tickers from LLM analysis.
--   This adds the same Chain-of-Thought fields that research_articles already has,
--   so newsletters display sentiment badges, claims, fact_check, conclusion, and
--   logic_check on the research dashboard.
-- Status: Applied to production on 2026-02-10

ALTER TABLE newsletters
    ADD COLUMN IF NOT EXISTS sentiment VARCHAR(20),
    ADD COLUMN IF NOT EXISTS sentiment_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS claims JSONB,
    ADD COLUMN IF NOT EXISTS fact_check TEXT,
    ADD COLUMN IF NOT EXISTS conclusion TEXT,
    ADD COLUMN IF NOT EXISTS logic_check VARCHAR(20);

-- Add comments for documentation
COMMENT ON COLUMN newsletters.sentiment IS 'Overall article sentiment: BULLISH, BEARISH, VERY_BULLISH, VERY_BEARISH, NEUTRAL';
COMMENT ON COLUMN newsletters.sentiment_score IS 'Numeric sentiment score from LLM analysis';
COMMENT ON COLUMN newsletters.claims IS 'JSONB array of key claims extracted by LLM';
COMMENT ON COLUMN newsletters.fact_check IS 'LLM fact-check assessment of the article claims';
COMMENT ON COLUMN newsletters.conclusion IS 'LLM-generated conclusion / investment takeaway';
COMMENT ON COLUMN newsletters.logic_check IS 'Logic consistency check: SOUND, MINOR_ISSUES, FLAWED';
