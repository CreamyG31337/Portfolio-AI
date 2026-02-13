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
    fifty_two_week_low NUMERIC,
    description TEXT,
    forward_pe NUMERIC,
    price_to_book NUMERIC,
    price_to_sales NUMERIC,
    peg_ratio NUMERIC,
    return_on_equity NUMERIC,
    net_margin NUMERIC,
    operating_margin NUMERIC,
    gross_margin NUMERIC,
    revenue_growth NUMERIC,
    earnings_growth NUMERIC,
    current_ratio NUMERIC,
    debt_to_equity NUMERIC,
    free_cash_flow NUMERIC,
    short_ratio NUMERIC,
    short_percent_of_float NUMERIC,
    ebitda NUMERIC,
    trailing_eps NUMERIC,
    forward_eps NUMERIC,
    use_alt_logo BOOLEAN DEFAULT false,
    website TEXT
,
    PRIMARY KEY (ticker)
);

-- Indexes
CREATE INDEX idx_securities_currency ON securities (currency);
CREATE INDEX idx_securities_industry ON securities (industry);
CREATE INDEX idx_securities_last_updated ON securities (last_updated);
CREATE INDEX idx_securities_sector ON securities (sector);