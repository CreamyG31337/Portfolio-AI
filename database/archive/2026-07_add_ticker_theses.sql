-- Migration: Insights thesis threads (ticker_theses + thesis_entries + thesis_evidence)
-- Date: 2026-07-09
-- Database: Research Postgres (NOT Supabase)

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

CREATE TABLE IF NOT EXISTS thesis_entries (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    thesis_id UUID NOT NULL REFERENCES ticker_theses(id) ON DELETE CASCADE,
    entry_kind VARCHAR(30) NOT NULL
        CHECK (entry_kind IN ('opening', 'comment', 'review', 'llm_reply')),
    author_kind VARCHAR(20) NOT NULL
        CHECK (author_kind IN ('user', 'llm', 'system')),
    author_id VARCHAR(100),
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(1024),
    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_thesis_entries_thread
    ON thesis_entries (thesis_id, created_at);

CREATE TABLE IF NOT EXISTS thesis_evidence (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    thesis_id UUID NOT NULL REFERENCES ticker_theses(id) ON DELETE CASCADE,
    entry_id UUID REFERENCES thesis_entries(id) ON DELETE SET NULL,
    evidence_kind VARCHAR(40) NOT NULL
        CHECK (evidence_kind IN (
            'user_url', 'research_article', 'ticker_analysis',
            'ticker_meta_analysis', 'confluence_event', 'stance_history'
        )),
    ref_id UUID,
    url TEXT,
    title TEXT,
    snippet TEXT,
    relation VARCHAR(20) NOT NULL DEFAULT 'context'
        CHECK (relation IN ('supports', 'contradicts', 'context')),
    created_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_thesis_evidence_thesis
    ON thesis_evidence (thesis_id);
CREATE INDEX IF NOT EXISTS idx_thesis_evidence_article
    ON thesis_evidence (ref_id) WHERE evidence_kind = 'research_article';
