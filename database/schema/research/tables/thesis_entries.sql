-- Conversation log for a thesis thread (users, reviews; llm_reply in v2).
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

COMMENT ON TABLE thesis_entries IS
    'Flat chronological posts on a thesis; review entries may snapshot disposition/intent changes';
