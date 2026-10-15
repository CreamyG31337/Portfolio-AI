-- Table: ticker_symbol_aliases
-- Maps holdings-file ticker spellings to the Yahoo symbol yfinance serves
-- (BRKB -> BRK-B, BF/B -> BF-B).  Rows are written by the fundamentals
-- refresh job when its share-class alias fetch succeeds, and read by the
-- ticker details ETF holdings panel to link each holding to a loadable
-- /ticker page.  No policies: only the service role (server-side jobs and
-- routes) reads or writes it.
DROP TABLE IF EXISTS ticker_symbol_aliases CASCADE;

CREATE TABLE ticker_symbol_aliases (
    ticker VARCHAR(20) PRIMARY KEY,
    yahoo_symbol VARCHAR(20) NOT NULL,
    source VARCHAR(20) NOT NULL DEFAULT 'refresh_job',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE ticker_symbol_aliases ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE ticker_symbol_aliases IS
    'Holdings-file ticker spellings mapped to the Yahoo symbol yfinance serves '
    '(BRKB -> BRK-B, BF/B -> BF-B); written by the fundamentals refresh job '
    'when its alias fetch succeeds, read by the ETF holdings panel to build '
    'holding links.';
