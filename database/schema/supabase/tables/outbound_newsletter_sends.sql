-- Table: outbound_newsletter_sends (per recipient per issue)
DROP TABLE IF EXISTS outbound_newsletter_sends CASCADE;

CREATE TABLE outbound_newsletter_sends (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    issue_id UUID NOT NULL,
    user_id UUID NOT NULL,
    email TEXT NOT NULL,
    mailgun_message_id TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT outbound_newsletter_sends_issue_id_fkey
        FOREIGN KEY (issue_id) REFERENCES outbound_newsletter_issues (id) ON DELETE CASCADE,
    CONSTRAINT outbound_newsletter_sends_status_check CHECK (
        status = ANY (ARRAY['queued'::text, 'sent'::text, 'failed'::text])
    )
);

CREATE INDEX outbound_newsletter_sends_issue_id_idx ON outbound_newsletter_sends (issue_id);
CREATE INDEX outbound_newsletter_sends_user_id_idx ON outbound_newsletter_sends (user_id);

ALTER TABLE outbound_newsletter_sends ENABLE ROW LEVEL SECURITY;
