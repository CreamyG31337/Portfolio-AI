-- Migration 004: Add Fundamentals Columns to Securities Table
-- ============================================================
-- This migration adds columns to store fundamental data (P/E, Dividend Yield, 52W High/Low)
-- directly in the securities table to reduce dependency on external API calls.

-- Add fundamentals columns to securities table
ALTER TABLE securities
ADD COLUMN IF NOT EXISTS trailing_pe NUMERIC,
ADD COLUMN IF NOT EXISTS dividend_yield NUMERIC,
ADD COLUMN IF NOT EXISTS fifty_two_week_high NUMERIC,
ADD COLUMN IF NOT EXISTS fifty_two_week_low NUMERIC;

-- Add index on last_updated for efficient staleness checks
CREATE INDEX IF NOT EXISTS idx_securities_last_updated ON securities(last_updated);

-- Verify columns were added
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'securities' 
AND column_name IN ('trailing_pe', 'dividend_yield', 'fifty_two_week_high', 'fifty_two_week_low', 'last_updated')
ORDER BY column_name;
