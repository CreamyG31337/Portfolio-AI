-- Migration: YouTube industry-thesis ideas + per-source title filter
-- Date: 2026-11-12
-- Database: Research Postgres (NOT Supabase)
--
-- Sources with alpha_mechanism = 'INDUSTRY' (general-interest explainer channels:
-- Business Insider, Maxinomics) get a second GLM pass after the normal summary.
-- That pass turns the video's industry dynamics into candidate companies. The
-- candidates are low-trust ideas, so they live here, NOT in
-- research_articles.tickers: most come from the model's own knowledge rather
-- than the transcript, and tagging them on the article would corrupt per-source
-- ROI attribution (see yt_articles.summarize_transcript).

CREATE TABLE IF NOT EXISTS yt_industry_ideas (
    id                  BIGSERIAL PRIMARY KEY,
    article_id          UUID         NOT NULL,
    video_id            VARCHAR(16),
    source              VARCHAR(100),
    thesis_index        SMALLINT     NOT NULL,
    dynamic             TEXT         NOT NULL,
    quote               TEXT,
    -- True when the quote was found in the stored transcript (normalized match).
    quote_verified      BOOLEAN      NOT NULL DEFAULT false,
    direction           VARCHAR(10),
    beneficiary_profile TEXT,
    loser_profile       TEXT,
    company_name        TEXT         NOT NULL,
    ticker              VARCHAR(20),
    -- True when ticker_validator confirmed the ticker exists and matches company_name.
    ticker_verified     BOOLEAN      NOT NULL DEFAULT false,
    side                VARCHAR(5)   CHECK (side IN ('long', 'short')),
    approx_cap          VARCHAR(10),
    -- 'transcript' = the video names the company; 'model_knowledge' = GLM added it.
    origin              VARCHAR(20)  CHECK (origin IN ('transcript', 'model_knowledge')),
    confidence          NUMERIC(3,2),
    why                 TEXT,
    model               VARCHAR(60),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_yt_industry_ideas_article
    ON yt_industry_ideas (article_id);
CREATE INDEX IF NOT EXISTS idx_yt_industry_ideas_ticker
    ON yt_industry_ideas (ticker, created_at DESC) WHERE ticker IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_yt_industry_ideas_created
    ON yt_industry_ideas (created_at DESC);

COMMENT ON TABLE yt_industry_ideas IS
    'Advisory company candidates from the INDUSTRY-source thesis pass on YouTube transcripts. Only rows that passed the code-side filters (verified quote, confidence floor, verified ticker) are stored.';

-- Skip videos by title before fetching captions (e.g. Business Insider lifestyle
-- series such as "The Pay Check" and "Boot Camp"). Case-insensitive regex.
ALTER TABLE youtube_sources ADD COLUMN IF NOT EXISTS title_exclude_regex TEXT;
