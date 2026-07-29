-- Table: ai_assistant_chats
-- One active AI Assistant transcript per (user_id, fund).
DROP TABLE IF EXISTS ai_assistant_chats CASCADE;

CREATE TABLE ai_assistant_chats (
    user_id UUID NOT NULL,
    fund TEXT NOT NULL,
    messages JSONB NOT NULL DEFAULT '[]'::jsonb,
    model TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, fund),
    CONSTRAINT ai_assistant_chats_messages_is_array
        CHECK (jsonb_typeof(messages) = 'array'),
    CONSTRAINT ai_assistant_chats_fund_nonempty
        CHECK (length(trim(fund)) > 0),
    CONSTRAINT ai_assistant_chats_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES user_profiles (user_id) ON DELETE CASCADE
);

CREATE INDEX idx_ai_assistant_chats_updated
    ON ai_assistant_chats (updated_at DESC);

ALTER TABLE ai_assistant_chats ENABLE ROW LEVEL SECURITY;
