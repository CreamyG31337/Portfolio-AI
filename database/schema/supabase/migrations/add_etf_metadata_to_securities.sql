-- Migration: Add ETF metadata column to securities table
-- Adds fund_description for storing ETF fund information (objective, strategy, themes)
-- This helps the AI better understand ETF investment strategies when analyzing holdings changes

ALTER TABLE securities 
ADD COLUMN IF NOT EXISTS fund_description TEXT;

-- Comments
COMMENT ON COLUMN securities.fund_description IS 'ETF fund description (objective, strategy, themes, sectors - can include line breaks)';

-- Index for querying ETFs with metadata
CREATE INDEX IF NOT EXISTS idx_securities_etf_metadata ON securities (ticker) 
WHERE fund_description IS NOT NULL;
