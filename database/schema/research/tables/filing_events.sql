-- Append-only log of US SEC (EDGAR) filing-risk events (ROADMAP G2).
-- The FORWARD/structural signal the shares-outstanding dilution watch (G3) can't
-- show: a shelf S-3 means dilution is *coming*; plus late filings (distress),
-- delisting notices, and activist/accumulation 13D/13G stakes. US-only by nature
-- (EDGAR has no Canadian filings). Sourced from data.sec.gov submissions; one
-- row per filing, deduped on accession_no. Distinct from G3's dilution_observations
-- (realized share-count growth) — complementary, clearly labeled.
CREATE TABLE IF NOT EXISTS filing_events (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    ticker VARCHAR(20) NOT NULL,
    cik VARCHAR(20),
    form_type VARCHAR(40) NOT NULL,
    category VARCHAR(20) NOT NULL,    -- 'dilution' | 'distress' | 'delisting' | 'activist'
    direction VARCHAR(10) NOT NULL,   -- 'risk' | 'positive' | 'neutral'
    filed_at DATE,
    accession_no VARCHAR(30) NOT NULL,
    title TEXT,
    url TEXT,
    raw JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (accession_no)
);

CREATE INDEX IF NOT EXISTS idx_filing_events_ticker_filed
    ON filing_events (ticker, filed_at DESC);
CREATE INDEX IF NOT EXISTS idx_filing_events_filed ON filing_events (filed_at DESC);

COMMENT ON TABLE filing_events IS
    'US EDGAR filing-risk events (shelf/dilution intent, distress, delisting, activist); deduped on accession_no';
COMMENT ON COLUMN filing_events.category IS
    'dilution (S-1/S-3/424B5/S-8/EFFECT) | distress (NT 10-Q/K, 8-K Item 3.01) | delisting (Form 25/25-NSE) | activist (SC/SCHEDULE 13D/13G)';
COMMENT ON COLUMN filing_events.direction IS
    'risk (dilution/distress/delisting) | positive (13D/13G accumulation) | neutral (routine, e.g. S-8)';
