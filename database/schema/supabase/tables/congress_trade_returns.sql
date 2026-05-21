CREATE TABLE congress_trade_returns (
    trade_id        INTEGER PRIMARY KEY REFERENCES congress_trades(id) ON DELETE CASCADE,
    entry_price_adj NUMERIC(12, 4),
    current_price   NUMERIC(12, 4),
    pct_change      NUMERIC(8, 2),
    midpoint_est    NUMERIC(12, 2),
    last_updated    TIMESTAMP DEFAULT now(),
    price_source    VARCHAR(20) DEFAULT 'yfinance'
);

ALTER TABLE congress_trade_returns ENABLE ROW LEVEL SECURITY;

CREATE INDEX idx_ctr_last_updated ON congress_trade_returns(last_updated);
CREATE INDEX idx_ctr_pct_change ON congress_trade_returns(pct_change);
