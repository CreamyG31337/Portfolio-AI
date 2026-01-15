-- Table: dividend_log
DROP TABLE IF EXISTS dividend_log CASCADE;

CREATE TABLE dividend_log (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    fund VARCHAR(50) NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    ex_date DATE NOT NULL,
    pay_date DATE NOT NULL,
    gross_amount NUMERIC(15, 6) NOT NULL,
    withholding_tax NUMERIC(15, 6) NOT NULL DEFAULT 0,
    net_amount NUMERIC(15, 6) NOT NULL,
    reinvested_shares NUMERIC(15, 6) NOT NULL,
    drip_price NUMERIC(10, 2) NOT NULL,
    is_verified BOOLEAN DEFAULT false,
    trade_log_id UUID,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD'::character varying,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE dividend_log ADD CONSTRAINT dividend_log_fund_fkey FOREIGN KEY (fund) REFERENCES funds(name);
ALTER TABLE dividend_log ADD CONSTRAINT dividend_log_trade_log_id_fkey FOREIGN KEY (trade_log_id) REFERENCES trade_log(id);
ALTER TABLE dividend_log ADD CONSTRAINT fk_dividend_log_ticker FOREIGN KEY (ticker) REFERENCES securities(ticker);

-- Indexes
CREATE UNIQUE INDEX dividend_log_fund_ticker_ex_date_key ON dividend_log (fund, ticker, ex_date);
CREATE INDEX idx_dividend_log_ex_date ON dividend_log (ex_date);
CREATE INDEX idx_dividend_log_fund ON dividend_log (fund);
CREATE INDEX idx_dividend_log_pay_date ON dividend_log (pay_date);
CREATE INDEX idx_dividend_log_ticker ON dividend_log (ticker);
CREATE INDEX idx_dividend_log_ticker_fk ON dividend_log (ticker);
CREATE INDEX idx_dividend_log_trade_log_id ON dividend_log (trade_log_id);