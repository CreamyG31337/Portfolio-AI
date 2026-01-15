-- Table: committee_assignments
DROP TABLE IF EXISTS committee_assignments CASCADE;

CREATE TABLE committee_assignments (
    id INTEGER NOT NULL DEFAULT nextval('committee_assignments_id_seq'::regclass),
    politician_id INTEGER NOT NULL,
    committee_id INTEGER NOT NULL,
    rank INTEGER,
    title VARCHAR(100),
    party VARCHAR(50),
    created_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE committee_assignments ADD CONSTRAINT committee_assignments_committee_id_fkey FOREIGN KEY (committee_id) REFERENCES committees(id);
ALTER TABLE committee_assignments ADD CONSTRAINT committee_assignments_politician_id_fkey FOREIGN KEY (politician_id) REFERENCES politicians(id);

-- Indexes
CREATE UNIQUE INDEX committee_assignments_politician_id_committee_id_key ON committee_assignments (politician_id, committee_id);
CREATE INDEX idx_committee_assignments_committee ON committee_assignments (committee_id);
CREATE INDEX idx_committee_assignments_politician ON committee_assignments (politician_id);
CREATE INDEX idx_committee_assignments_politician_committee ON committee_assignments (politician_id, committee_id);