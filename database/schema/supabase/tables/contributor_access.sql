-- Table: contributor_access
DROP TABLE IF EXISTS contributor_access CASCADE;

CREATE TABLE contributor_access (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    contributor_id UUID,
    user_id UUID,
    access_level VARCHAR(50) DEFAULT 'viewer'::character varying,
    granted_by UUID,
    granted_at TIMESTAMP DEFAULT now(),
    expires_at TIMESTAMP,
    notes TEXT
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE contributor_access ADD CONSTRAINT contributor_access_contributor_id_fkey FOREIGN KEY (contributor_id) REFERENCES contributors(id);
ALTER TABLE contributor_access ADD CONSTRAINT contributor_access_granted_by_fkey FOREIGN KEY (granted_by) REFERENCES users(id);
ALTER TABLE contributor_access ADD CONSTRAINT contributor_access_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);

-- Indexes
CREATE UNIQUE INDEX contributor_access_contributor_id_user_id_key ON contributor_access (contributor_id, user_id);
CREATE INDEX idx_contributor_access_contributor ON contributor_access (contributor_id);
CREATE INDEX idx_contributor_access_user ON contributor_access (user_id);