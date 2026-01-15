-- Table: securities
DROP TABLE IF EXISTS securities CASCADE;

CREATE TABLE securities (
    ticker VARCHAR(20) NOT NULL,
    name TEXT,
    sector TEXT,
    industry TEXT,
    asset_class VARCHAR(50),
    exchange VARCHAR(50),
    currency VARCHAR(10) DEFAULT 'USD'::character varying,
    description TEXT,
    last_updated TIMESTAMP DEFAULT now(),
    first_detected_by VARCHAR(50)
,
    PRIMARY KEY (ticker)
);

-- Indexes
CREATE INDEX idx_securities_industry ON securities (industry);
CREATE INDEX idx_securities_sector ON securities (sector);