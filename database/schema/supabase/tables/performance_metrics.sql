-- Table: performance_metrics
DROP TABLE IF EXISTS performance_metrics CASCADE;

CREATE TABLE performance_metrics (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    fund VARCHAR(50) NOT NULL,
    date DATE NOT NULL,
    total_value NUMERIC(10, 2) NOT NULL,
    cost_basis NUMERIC(10, 2) NOT NULL,
    unrealized_pnl NUMERIC(10, 2) NOT NULL,
    performance_pct NUMERIC(5, 2) NOT NULL,
    total_trades INTEGER NOT NULL DEFAULT 0,
    winning_trades INTEGER NOT NULL DEFAULT 0,
    losing_trades INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE performance_metrics ADD CONSTRAINT fk_performance_metrics_fund FOREIGN KEY (fund) REFERENCES funds(name);

-- Indexes
CREATE INDEX idx_performance_metrics_date ON performance_metrics (date);
CREATE INDEX idx_performance_metrics_fund ON performance_metrics (fund);
CREATE UNIQUE INDEX performance_metrics_fund_date_key ON performance_metrics (fund, date);