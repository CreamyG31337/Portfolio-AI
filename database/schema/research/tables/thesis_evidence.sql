-- Evidence links backing a thesis (URLs, research_articles, automated artifacts).
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

COMMENT ON TABLE thesis_evidence IS
    'Many evidence rows per thesis; optional link to the entry that added them';
