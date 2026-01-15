-- Table: funds
DROP TABLE IF EXISTS funds CASCADE;

CREATE TABLE funds (
    id INTEGER NOT NULL DEFAULT nextval('funds_id_seq'::regclass),
    name VARCHAR(100) NOT NULL,
    description TEXT,
    currency VARCHAR(10) NOT NULL DEFAULT 'CAD'::character varying,
    fund_type VARCHAR(50) NOT NULL DEFAULT 'investment'::character varying,
    created_at TIMESTAMP DEFAULT now(),
    base_currency VARCHAR(3) DEFAULT 'CAD'::character varying,
    is_production BOOLEAN DEFAULT false
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE UNIQUE INDEX funds_name_key ON funds (name);
CREATE INDEX idx_funds_base_currency ON funds (base_currency);
CREATE INDEX idx_funds_is_production ON funds (is_production);