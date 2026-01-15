-- Table: politicians
DROP TABLE IF EXISTS politicians CASCADE;

CREATE TABLE politicians (
    id INTEGER NOT NULL DEFAULT nextval('politicians_id_seq'::regclass),
    name VARCHAR(255) NOT NULL,
    bioguide_id VARCHAR(20) NOT NULL,
    party VARCHAR(50),
    state VARCHAR(2) NOT NULL,
    chamber VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE INDEX idx_politicians_bioguide_id ON politicians (bioguide_id);
CREATE INDEX idx_politicians_chamber ON politicians (chamber);
CREATE INDEX idx_politicians_name ON politicians (name);
CREATE INDEX idx_politicians_state ON politicians (state);
CREATE UNIQUE INDEX politicians_bioguide_id_key ON politicians (bioguide_id);