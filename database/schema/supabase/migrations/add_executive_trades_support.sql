-- Executive branch trades: chamber expansion, asset descriptions, ticker cache.

-- 1. Allow Executive chamber on politicians (no CHECK in prod schema; safe no-op if absent)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'politicians_chamber_check'
    ) THEN
        ALTER TABLE politicians DROP CONSTRAINT politicians_chamber_check;
        ALTER TABLE politicians
            ADD CONSTRAINT politicians_chamber_check
            CHECK (chamber IN ('House', 'Senate', 'Executive'));
    END IF;
END $$;

-- 2. Allow Executive chamber on congress_trades
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'congress_trades_chamber_check'
    ) THEN
        ALTER TABLE congress_trades DROP CONSTRAINT congress_trades_chamber_check;
        ALTER TABLE congress_trades
            ADD CONSTRAINT congress_trades_chamber_check
            CHECK (chamber IN ('House', 'Senate', 'Executive'));
    END IF;
END $$;

-- 3. Preserve original OGE asset text on trade rows
ALTER TABLE congress_trades
    ADD COLUMN IF NOT EXISTS asset_description TEXT;

COMMENT ON COLUMN congress_trades.asset_description IS
    'Original OGE 278-T asset description (executive branch filings)';

-- 4. Persistent company-name -> ticker cache for OGE descriptions
CREATE TABLE IF NOT EXISTS og_asset_ticker_map (
    canonical_description TEXT PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('suffix', 'open_cabinet', 'securities', 'yfinance', 'manual')),
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    asset_type VARCHAR(20) NOT NULL DEFAULT 'Stock',
    resolved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_og_asset_ticker_map_ticker
    ON og_asset_ticker_map (ticker);

COMMENT ON TABLE og_asset_ticker_map IS
    'Cache mapping canonical OGE asset descriptions to validated equity tickers';

-- 5. Seed Donald J. Trump as executive-branch politician
INSERT INTO politicians (name, bioguide_id, party, state, chamber)
VALUES ('Donald J. Trump', 'EXEC-POTUS-47', 'Republican', 'US', 'Executive')
ON CONFLICT (bioguide_id) DO UPDATE
SET
    name = EXCLUDED.name,
    party = EXCLUDED.party,
    state = EXCLUDED.state,
    chamber = EXCLUDED.chamber,
    updated_at = now();
