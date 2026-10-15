-- Grok Bot weekday thesis evidence sweep: one web-research review per thesis per day.
-- The Bot reads filings, press releases and news for a thesis and files sources as
-- thesis_evidence (evidence_kind='grok_review', ref_id = this row). It is advisory input
-- for the thesis evaluation job; it never bumps ticker_theses.last_reviewed_at.
CREATE TABLE IF NOT EXISTS grok_thesis_reviews (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    thesis_id UUID NOT NULL REFERENCES ticker_theses(id) ON DELETE CASCADE,
    ticker VARCHAR(20) NOT NULL,
    review_date DATE NOT NULL,
    verdict VARCHAR(20) NOT NULL
        CHECK (verdict IN ('supports', 'contradicts', 'mixed', 'no_change')),
    summary TEXT NOT NULL,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'ingested'
        CHECK (status IN ('ingested', 'evaluated')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (thesis_id, review_date)
);

CREATE INDEX IF NOT EXISTS idx_grok_thesis_reviews_thesis
    ON grok_thesis_reviews (thesis_id, review_date DESC);
CREATE INDEX IF NOT EXISTS idx_grok_thesis_reviews_date
    ON grok_thesis_reviews (review_date DESC);

COMMENT ON TABLE grok_thesis_reviews IS
    'Grok Bot web-research reviews of Insights theses (advisory). Sources are mirrored into thesis_evidence as grok_review rows.';
