-- Table: corporate_actions
-- Ledger of stock splits applied to trade_log / portfolio_positions by
-- web_dashboard/split_guard.py (via the apply_stock_split() function) or by hand.
-- The unique key is what stops a split being applied twice.
-- Created by database/migrations/2026-11_add_corporate_actions.sql.
DROP TABLE IF EXISTS corporate_actions CASCADE;

CREATE TABLE corporate_actions (
    id BIGSERIAL PRIMARY KEY,
    fund VARCHAR(100) NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    action_type VARCHAR(20) NOT NULL DEFAULT 'split' CHECK (action_type IN ('split')),
    ex_date DATE NOT NULL,
    ratio NUMERIC(12,6) NOT NULL CHECK (ratio > 0),
    status VARCHAR(20) NOT NULL CHECK (status IN ('applied', 'unconfirmed')),
    cliff_date DATE,
    trades_adjusted INTEGER,
    positions_adjusted INTEGER,
    source VARCHAR(40) NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fund, ticker, action_type, ex_date)
);

ALTER TABLE corporate_actions ENABLE ROW LEVEL SECURITY;
