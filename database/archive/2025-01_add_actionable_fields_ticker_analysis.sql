-- Migration: Add actionable trading fields to ticker_analysis table
-- Date: 2025-01
-- Description: Adds stance, timeframe, entry/exit levels, catalysts, risks, and invalidation fields

-- Add new columns for actionable trading analysis
ALTER TABLE ticker_analysis
    ADD COLUMN IF NOT EXISTS stance VARCHAR(10) CHECK (stance IN ('BUY', 'SELL', 'HOLD', 'AVOID')),
    ADD COLUMN IF NOT EXISTS timeframe VARCHAR(20) CHECK (timeframe IN ('day_trade', 'swing', 'position')),
    ADD COLUMN IF NOT EXISTS entry_zone VARCHAR(50),
    ADD COLUMN IF NOT EXISTS target_price VARCHAR(20),
    ADD COLUMN IF NOT EXISTS stop_loss VARCHAR(20),
    ADD COLUMN IF NOT EXISTS key_levels JSONB,
    ADD COLUMN IF NOT EXISTS catalysts TEXT[],
    ADD COLUMN IF NOT EXISTS risks TEXT[],
    ADD COLUMN IF NOT EXISTS invalidation TEXT;

-- Add comments for documentation
COMMENT ON COLUMN ticker_analysis.stance IS 'Trading stance: BUY, SELL, HOLD, or AVOID';
COMMENT ON COLUMN ticker_analysis.timeframe IS 'Recommended trading timeframe: day_trade, swing, or position';
COMMENT ON COLUMN ticker_analysis.entry_zone IS 'Suggested entry price range (e.g., "$45-47")';
COMMENT ON COLUMN ticker_analysis.target_price IS 'Price target for the trade';
COMMENT ON COLUMN ticker_analysis.stop_loss IS 'Stop loss level';
COMMENT ON COLUMN ticker_analysis.key_levels IS 'JSON with support and resistance levels';
COMMENT ON COLUMN ticker_analysis.catalysts IS 'Array of potential catalysts for price movement';
COMMENT ON COLUMN ticker_analysis.risks IS 'Array of identified risks';
COMMENT ON COLUMN ticker_analysis.invalidation IS 'What would invalidate the trading thesis';

-- Create index on stance for filtering
CREATE INDEX IF NOT EXISTS idx_ticker_analysis_stance ON ticker_analysis (stance) WHERE stance IS NOT NULL;
