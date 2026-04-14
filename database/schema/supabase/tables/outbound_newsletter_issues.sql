-- Table: outbound_newsletter_issues (one row per send wave)
DROP TABLE IF EXISTS outbound_newsletter_issues CASCADE;

CREATE TABLE outbound_newsletter_issues (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    newsletter_type_id UUID NOT NULL,
    triggered_by TEXT NOT NULL DEFAULT 'scheduler',
    status TEXT NOT NULL DEFAULT 'draft',
    sent_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT outbound_newsletter_issues_newsletter_type_id_fkey
        FOREIGN KEY (newsletter_type_id) REFERENCES outbound_newsletter_types (id) ON DELETE CASCADE,
    CONSTRAINT outbound_newsletter_issues_status_check CHECK (
        status = ANY (ARRAY['draft'::text, 'sending'::text, 'completed'::text, 'failed'::text])
    )
);

CREATE INDEX outbound_newsletter_issues_type_sent_idx ON outbound_newsletter_issues (newsletter_type_id, sent_at DESC);
CREATE INDEX outbound_newsletter_issues_expires_idx ON outbound_newsletter_issues (expires_at);

ALTER TABLE outbound_newsletter_issues ENABLE ROW LEVEL SECURITY;
