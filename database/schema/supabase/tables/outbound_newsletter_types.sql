-- Table: outbound_newsletter_types
-- Catalog of outbound email products (portfolio digest, future types).
DROP TABLE IF EXISTS outbound_newsletter_types CASCADE;

CREATE TABLE outbound_newsletter_types (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    slug TEXT NOT NULL,
    display_name TEXT NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    default_cadence TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE UNIQUE INDEX outbound_newsletter_types_slug_key ON outbound_newsletter_types (slug);
CREATE INDEX outbound_newsletter_types_is_active_idx ON outbound_newsletter_types (is_active);

ALTER TABLE outbound_newsletter_types ENABLE ROW LEVEL SECURITY;

-- Seed default portfolio digest type (stable id for app references / tests)
INSERT INTO outbound_newsletter_types (id, slug, display_name, description, is_active, config, default_cadence)
VALUES (
    'd1111111-1111-4111-8111-111111111111'::uuid,
    'portfolio_digest',
    'Portfolio digest',
    'Personalized portfolio KPIs, movers, and market brief',
    true,
    '{"ttl_days": 7, "builder": "portfolio_v1", "mailgun_tag": "portfolio_digest"}'::jsonb,
    'weekly'
);
