-- Table: portfolio_positions
DROP TABLE IF EXISTS portfolio_positions CASCADE;

CREATE TABLE portfolio_positions (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    fund VARCHAR(50) NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    shares NUMERIC(15, 6) NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    cost_basis NUMERIC(10, 2) NOT NULL,
    pnl NUMERIC(10, 2) NOT NULL DEFAULT 0,
    total_value NUMERIC(10, 2),
    currency VARCHAR(10) NOT NULL DEFAULT 'USD'::character varying,
    date TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    base_currency VARCHAR(3),
    total_value_base NUMERIC(15, 2),
    cost_basis_base NUMERIC(15, 2),
    pnl_base NUMERIC(15, 2),
    exchange_rate NUMERIC(10, 6),
    date_only DATE
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE portfolio_positions ADD CONSTRAINT fk_portfolio_positions_fund FOREIGN KEY (fund) REFERENCES funds(name);
ALTER TABLE portfolio_positions ADD CONSTRAINT fk_portfolio_positions_ticker FOREIGN KEY (ticker) REFERENCES securities(ticker);

-- Indexes
CREATE INDEX idx_portfolio_positions_base_currency ON portfolio_positions (base_currency);
CREATE INDEX idx_portfolio_positions_date ON portfolio_positions (date);
CREATE INDEX idx_portfolio_positions_date_fund ON portfolio_positions (date, fund);
CREATE INDEX idx_portfolio_positions_fund ON portfolio_positions (fund);
CREATE INDEX idx_portfolio_positions_fund_date ON portfolio_positions (fund, date);
CREATE INDEX idx_portfolio_positions_fund_date_ticker ON portfolio_positions (fund, date, ticker);
CREATE INDEX idx_portfolio_positions_fund_ticker ON portfolio_positions (fund, ticker);
CREATE INDEX idx_portfolio_positions_fund_ticker_date ON portfolio_positions (fund, ticker, date);
CREATE INDEX idx_portfolio_positions_ticker ON portfolio_positions (ticker);
CREATE INDEX idx_portfolio_positions_ticker_fk ON portfolio_positions (ticker);
CREATE INDEX idx_portfolio_positions_ticker_fund_date ON portfolio_positions (ticker, fund, date);
CREATE UNIQUE INDEX idx_portfolio_positions_unique ON portfolio_positions (fund, ticker, date_only);
CREATE UNIQUE INDEX portfolio_positions_unique_fund_ticker_date ON portfolio_positions (fund, ticker, date_only);