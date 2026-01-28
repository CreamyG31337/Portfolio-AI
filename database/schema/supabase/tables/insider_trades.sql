-- Table: insider_trades
DROP TABLE IF EXISTS insider_trades CASCADE;

CREATE TABLE insider_trades (
    id INTEGER NOT NULL DEFAULT nextval('insider_trades_id_seq'::regclass),
    ticker VARCHAR(20) NOT NULL,
    insider_name VARCHAR(255) NOT NULL,
    insider_title VARCHAR(255),
    transaction_date DATE NOT NULL,
    disclosure_date TIMESTAMP NOT NULL,
    type VARCHAR(20) NOT NULL,
    shares BIGINT,
    price_per_share NUMERIC(10, 2),
    value NUMERIC(15, 2),
    shares_held_after BIGINT,
    percent_change NUMERIC(10, 4),
    notes TEXT,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE UNIQUE INDEX insider_trades_unique_key ON insider_trades (ticker, insider_name, transaction_date, type, shares, price_per_share);
CREATE INDEX idx_insider_ticker ON insider_trades (ticker);
CREATE INDEX idx_insider_name ON insider_trades (insider_name);
CREATE INDEX idx_insider_transaction_date ON insider_trades (transaction_date);
CREATE INDEX idx_insider_disclosure_date ON insider_trades (disclosure_date);
CREATE INDEX idx_insider_type ON insider_trades (type);
CREATE INDEX idx_insider_value ON insider_trades (value);
