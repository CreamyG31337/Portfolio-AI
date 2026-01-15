-- Table: fund_thesis_pillars
DROP TABLE IF EXISTS fund_thesis_pillars CASCADE;

CREATE TABLE fund_thesis_pillars (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    thesis_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL,
    allocation VARCHAR(20) NOT NULL,
    thesis TEXT NOT NULL,
    pillar_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE fund_thesis_pillars ADD CONSTRAINT fund_thesis_pillars_thesis_id_fkey FOREIGN KEY (thesis_id) REFERENCES fund_thesis(id);

-- Indexes
CREATE INDEX idx_fund_thesis_pillars_thesis_id ON fund_thesis_pillars (thesis_id);