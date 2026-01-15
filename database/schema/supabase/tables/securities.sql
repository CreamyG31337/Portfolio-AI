-- Table: securities
DROP TABLE IF EXISTS securities CASCADE;

CREATE TABLE securities (
    ticker VARCHAR(20) NOT NULL,
    company_name TEXT,
    sector TEXT,
    industry TEXT,
    country VARCHAR(50),
    market_cap TEXT,
    currency VARCHAR(3),
    last_updated TIMESTAMP DEFAULT now(),
    created_at TIMESTAMP DEFAULT now(),
    trailing_pe NUMERIC,
    dividend_yield NUMERIC,
    fifty_two_week_high NUMERIC,
    fifty_two_week_low NUMERIC
,
    PRIMARY KEY (ticker)
);

-- Indexes
CREATE INDEX idx_securities_currency ON securities (currency);
CREATE INDEX idx_securities_industry ON securities (industry);
CREATE INDEX idx_securities_last_updated ON securities (last_updated);
CREATE INDEX idx_securities_sector ON securities (sector);