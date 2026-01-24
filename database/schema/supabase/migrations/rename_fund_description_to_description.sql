-- Migration: Rename fund_description column to description
-- The column is now used for both ETF fund descriptions and company business descriptions
-- so "fund_description" is no longer an accurate name

ALTER TABLE securities 
RENAME COLUMN fund_description TO description;

-- Update comment to reflect dual usage
COMMENT ON COLUMN securities.description IS 'Description: ETF fund description (objective, strategy, themes, sectors) or company description for stocks (business description from yfinance - can include line breaks)';

-- Rename index
DROP INDEX IF EXISTS idx_securities_fund_description;
DROP INDEX IF EXISTS idx_securities_etf_metadata;

CREATE INDEX IF NOT EXISTS idx_securities_description ON securities (ticker) 
WHERE description IS NOT NULL;
