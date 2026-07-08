-- Table: og_asset_ticker_map
DROP TABLE IF EXISTS og_asset_ticker_map CASCADE;

CREATE TABLE og_asset_ticker_map (
    canonical_description TEXT NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('suffix', 'open_cabinet', 'securities', 'yfinance', 'manual')),
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    asset_type VARCHAR(20) NOT NULL DEFAULT 'Stock',
    resolved_at TIMESTAMPTZ NOT NULL DEFAULT now()
,
    PRIMARY KEY (canonical_description)
);

-- Indexes
CREATE INDEX idx_og_asset_ticker_map_ticker ON og_asset_ticker_map (ticker);
