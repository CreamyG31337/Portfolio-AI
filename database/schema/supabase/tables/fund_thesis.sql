-- Table: fund_thesis
DROP TABLE IF EXISTS fund_thesis CASCADE;

CREATE TABLE fund_thesis (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    fund VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,
    overview TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE fund_thesis ADD CONSTRAINT fk_fund_thesis_fund FOREIGN KEY (fund) REFERENCES funds(name);

-- Indexes
CREATE UNIQUE INDEX fund_thesis_fund_key ON fund_thesis (fund);
CREATE INDEX idx_fund_thesis_fund ON fund_thesis (fund);