-- Table: cash_balances
DROP TABLE IF EXISTS cash_balances CASCADE;

CREATE TABLE cash_balances (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    fund VARCHAR(50) NOT NULL,
    currency VARCHAR(10) NOT NULL,
    amount NUMERIC(10, 2) NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE UNIQUE INDEX cash_balances_fund_currency_key ON cash_balances (fund, currency);
CREATE INDEX idx_cash_balances_fund ON cash_balances (fund);