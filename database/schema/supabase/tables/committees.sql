-- Table: committees
DROP TABLE IF EXISTS committees CASCADE;

CREATE TABLE committees (
    id INTEGER NOT NULL DEFAULT nextval('committees_id_seq'::regclass),
    name VARCHAR(255) NOT NULL,
    code VARCHAR(20),
    chamber VARCHAR(20) NOT NULL,
    target_sectors JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE UNIQUE INDEX committees_name_chamber_key ON committees (name, chamber);
CREATE INDEX idx_committees_chamber ON committees (chamber);
CREATE INDEX idx_committees_code ON committees (code);
CREATE INDEX idx_committees_name ON committees (name);
CREATE INDEX idx_committees_target_sectors ON committees (target_sectors);