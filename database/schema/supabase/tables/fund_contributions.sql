-- Table: fund_contributions
DROP TABLE IF EXISTS fund_contributions CASCADE;

CREATE TABLE fund_contributions (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    fund VARCHAR(50) NOT NULL,
    contributor VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    amount NUMERIC(10, 2) NOT NULL,
    contribution_type VARCHAR(20) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    fund_id INTEGER NOT NULL,
    contributor_id UUID
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE fund_contributions ADD CONSTRAINT fk_fund_contributions_fund FOREIGN KEY (fund) REFERENCES funds(name);
ALTER TABLE fund_contributions ADD CONSTRAINT fund_contributions_fund_id_fkey FOREIGN KEY (fund_id) REFERENCES funds(id);

-- Indexes
CREATE INDEX idx_fund_contributions_contributor ON fund_contributions (contributor);
CREATE INDEX idx_fund_contributions_fund ON fund_contributions (fund);
CREATE INDEX idx_fund_contributions_fund_contributor ON fund_contributions (fund, contributor);
CREATE INDEX idx_fund_contributions_fund_id ON fund_contributions (fund_id);
CREATE INDEX idx_fund_contributions_timestamp ON fund_contributions (timestamp);