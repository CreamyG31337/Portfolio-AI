-- Table: trade_log
DROP TABLE IF EXISTS trade_log CASCADE;

CREATE TABLE trade_log (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    fund VARCHAR(50) NOT NULL,
    date TIMESTAMP NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    shares NUMERIC(15, 6) NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    cost_basis NUMERIC(10, 2) NOT NULL,
    pnl NUMERIC(10, 2) NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD'::character varying,
    created_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE trade_log ADD CONSTRAINT fk_trade_log_fund FOREIGN KEY (fund) REFERENCES funds(name);
ALTER TABLE trade_log ADD CONSTRAINT fk_trade_log_ticker FOREIGN KEY (ticker) REFERENCES securities(ticker);

-- Indexes
CREATE INDEX idx_trade_log_date ON trade_log (date);
CREATE INDEX idx_trade_log_fund ON trade_log (fund);
CREATE INDEX idx_trade_log_ticker ON trade_log (ticker);
CREATE INDEX idx_trade_log_ticker_fk ON trade_log (ticker);