-- Triage decisions for alpha/opportunity research articles (Ideas inbox).
CREATE TABLE IF NOT EXISTS idea_triage (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    article_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL,
    decided_at TIMESTAMPTZ DEFAULT now(),
    decided_by VARCHAR(100),
    notes TEXT,
    snooze_until TIMESTAMPTZ,
    PRIMARY KEY (id),
    CONSTRAINT idea_triage_article_unique UNIQUE (article_id)
);

CREATE INDEX IF NOT EXISTS idx_idea_triage_status ON idea_triage (status, decided_at DESC);

COMMENT ON TABLE idea_triage IS 'Accept/dismiss/snooze decisions for Ideas inbox (Pillar 2.2)';
