-- Table: user_newsletter_subscriptions
DROP TABLE IF EXISTS user_newsletter_subscriptions CASCADE;

CREATE TABLE user_newsletter_subscriptions (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    newsletter_type_id UUID NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    cadence TEXT NOT NULL DEFAULT 'weekly',
    subscribed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_sent_at TIMESTAMPTZ,
    PRIMARY KEY (id),
    CONSTRAINT user_newsletter_subscriptions_cadence_check CHECK (
        cadence = ANY (ARRAY['daily'::text, 'weekly'::text, 'biweekly'::text, 'monthly'::text])
    ),
    CONSTRAINT user_newsletter_subscriptions_newsletter_type_id_fkey
        FOREIGN KEY (newsletter_type_id) REFERENCES outbound_newsletter_types (id) ON DELETE CASCADE,
    CONSTRAINT user_newsletter_subscriptions_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES user_profiles (user_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX user_newsletter_subscriptions_user_type_key
    ON user_newsletter_subscriptions (user_id, newsletter_type_id);
CREATE INDEX user_newsletter_subscriptions_user_id_idx ON user_newsletter_subscriptions (user_id);
CREATE INDEX user_newsletter_subscriptions_active_due_idx
    ON user_newsletter_subscriptions (newsletter_type_id, is_active)
    WHERE is_active = true;

ALTER TABLE user_newsletter_subscriptions ENABLE ROW LEVEL SECURITY;
