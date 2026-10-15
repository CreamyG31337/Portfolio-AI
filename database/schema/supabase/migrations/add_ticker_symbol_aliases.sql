-- Map holdings-file ticker spellings to the Yahoo symbol yfinance serves.
-- ETF holdings files spell share classes in ways yfinance won't serve
-- (BRKB, BF/B) while the real Yahoo symbols are BRK-B / BF-B.  The right
-- symbol can't be derived by rule alone (FOXA is a real ticker and must
-- stay), so the fundamentals refresh job records the alias whenever its
-- share-class fallback fetch succeeds, and the ticker details ETF holdings
-- panel reads this table to link each holding to a loadable /ticker page.
-- No policies: only the service role (server-side jobs and routes) reads
-- or writes it.

CREATE TABLE IF NOT EXISTS public.ticker_symbol_aliases (
    ticker VARCHAR(20) PRIMARY KEY,
    yahoo_symbol VARCHAR(20) NOT NULL,
    source VARCHAR(20) NOT NULL DEFAULT 'refresh_job',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.ticker_symbol_aliases ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.ticker_symbol_aliases IS
    'Holdings-file ticker spellings mapped to the Yahoo symbol yfinance serves '
    '(BRKB -> BRK-B, BF/B -> BF-B); written by the fundamentals refresh job '
    'when its alias fetch succeeds, read by the ETF holdings panel to build '
    'holding links.';
