-- Table: etf_holdings_log
DROP TABLE IF EXISTS etf_holdings_log CASCADE;

CREATE TABLE etf_holdings_log (
    date DATE NOT NULL,
    etf_ticker VARCHAR(10) NOT NULL,
    holding_ticker VARCHAR(50) NOT NULL,
    holding_name TEXT,
    shares_held NUMERIC,
    weight_percent NUMERIC,
    market_value NUMERIC,
    created_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (date, etf_ticker, holding_ticker)
);

-- Indexes
CREATE INDEX idx_etf_holdings_date ON etf_holdings_log (date);
CREATE INDEX idx_etf_holdings_etf ON etf_holdings_log (etf_ticker, date);
CREATE INDEX idx_etf_holdings_ticker ON etf_holdings_log (holding_ticker);