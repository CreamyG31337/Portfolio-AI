-- Tier-1 cached AI summaries for dashboard / screen metric bundles (not trade advice).

CREATE TABLE IF NOT EXISTS ui_ai_summary (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    scope VARCHAR(80) NOT NULL,
    scope_key VARCHAR(256) NOT NULL,
    content_class VARCHAR(20) NOT NULL DEFAULT 'price_linked',
    summary_json JSONB NOT NULL DEFAULT '{}',
    inputs_digest VARCHAR(64) NOT NULL,
    model_used VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT ui_ai_summary_scope_key_unique UNIQUE (scope, scope_key),
    CONSTRAINT ui_ai_summary_content_class_chk CHECK (
        content_class IN ('price_linked', 'content_linked')
    )
);

CREATE INDEX IF NOT EXISTS idx_ui_ai_summary_scope_updated
    ON ui_ai_summary (scope, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ui_ai_summary_content_class
    ON ui_ai_summary (content_class, updated_at DESC);

COMMENT ON TABLE ui_ai_summary IS
    'Cached LLM summaries for UI scopes; skip regeneration when inputs_digest unchanged';
