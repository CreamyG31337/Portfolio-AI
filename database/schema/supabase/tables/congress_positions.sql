CREATE TABLE IF NOT EXISTS congress_positions (
    id              SERIAL PRIMARY KEY,
    politician_id   INTEGER NOT NULL REFERENCES politicians(id) ON DELETE CASCADE,
    ticker          VARCHAR(20) NOT NULL,
    status          VARCHAR(10) NOT NULL DEFAULT 'closed',
    buy_count       INTEGER NOT NULL DEFAULT 0,
    sell_count      INTEGER NOT NULL DEFAULT 0,
    first_buy_date  DATE,
    last_sell_date  DATE,
    avg_buy_price   NUMERIC(12, 4),
    avg_sell_price  NUMERIC(12, 4),
    pct_return      NUMERIC(10, 2),
    est_invested    NUMERIC(14, 2),
    est_pnl         NUMERIC(14, 2),
    days_held       INTEGER,
    spy_pct_change  NUMERIC(10, 2),
    last_computed   TIMESTAMP DEFAULT now(),
    UNIQUE(politician_id, ticker)
);

ALTER TABLE congress_positions ENABLE ROW LEVEL SECURITY;

CREATE INDEX idx_cp_politician ON congress_positions(politician_id);
CREATE INDEX idx_cp_status ON congress_positions(status);
CREATE INDEX idx_cp_pct_return ON congress_positions(pct_return);
CREATE INDEX idx_cp_est_pnl ON congress_positions(est_pnl);
CREATE INDEX idx_cp_first_buy ON congress_positions(first_buy_date);

COMMENT ON TABLE congress_positions IS 'Aggregated closed positions: one row per (politician, ticker) pair where buys were followed by sells. Computed daily from congress_trades.';
COMMENT ON COLUMN congress_positions.status IS 'Position status: closed (has sells after buys). Future: open (buys only, no sells yet).';
COMMENT ON COLUMN congress_positions.est_invested IS 'Sum of midpoint estimates of purchase amount ranges (approximate dollar invested).';
COMMENT ON COLUMN congress_positions.est_pnl IS 'Estimated profit/loss = est_invested * pct_return / 100.';
COMMENT ON COLUMN congress_positions.spy_pct_change IS 'SPY return over the same holding period (first_buy_date to last_sell_date) for reference.';
