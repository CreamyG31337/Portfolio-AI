-- Table: watched_tickers_v2
DROP TABLE IF EXISTS watched_tickers_v2 CASCADE;

CREATE TABLE watched_tickers_v2 (
    fund VARCHAR(50) NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    priority_tier VARCHAR(10) DEFAULT 'B'::character varying,
    is_active BOOLEAN DEFAULT true,
    source VARCHAR(50),
    created_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (fund, ticker)
);

-- Foreign Keys
ALTER TABLE watched_tickers_v2 ADD CONSTRAINT fk_watched_tickers_v2_fund FOREIGN KEY (fund) REFERENCES funds(name);
ALTER TABLE watched_tickers_v2 ADD CONSTRAINT fk_watched_tickers_v2_ticker FOREIGN KEY (ticker) REFERENCES securities(ticker);

-- Indexes
CREATE INDEX idx_watched_tickers_v2_fund_active ON watched_tickers_v2 (fund, is_active);
CREATE INDEX idx_watched_tickers_v2_ticker ON watched_tickers_v2 (ticker);
CREATE INDEX idx_watched_tickers_v2_priority ON watched_tickers_v2 (priority_tier);

-- source values include: ideas_inbox (Ideas Accept), watchlist_ui, bulk_paste, manual, …
-- WARNING: app upserts currently overwrite source on conflict — preserve ideas_inbox
-- when adding merge/patch logic so discovery adds stay auditable for expiry.
COMMENT ON COLUMN watched_tickers_v2.source IS
  'Provenance (e.g. ideas_inbox). Do not casually overwrite; needed for expiry/audit.';

