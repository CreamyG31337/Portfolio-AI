-- =====================================================
-- ADD TICKER FOREIGN KEYS
-- =====================================================
-- Purpose: Add foreign key constraints from ticker columns
--          in dividend_log, trade_log, and portfolio_positions
--          to securities.ticker to enforce referential integrity
-- =====================================================

-- Step 1: Add foreign keys with NOT VALID (allows existing invalid data)
-- This allows us to add the constraint even if some tickers are missing
-- We'll validate after backfilling missing tickers

-- Foreign key for dividend_log
ALTER TABLE dividend_log 
  ADD CONSTRAINT fk_dividend_log_ticker 
  FOREIGN KEY (ticker) REFERENCES securities(ticker) 
  NOT VALID;

-- Foreign key for trade_log
ALTER TABLE trade_log 
  ADD CONSTRAINT fk_trade_log_ticker 
  FOREIGN KEY (ticker) REFERENCES securities(ticker) 
  NOT VALID;

-- Foreign key for portfolio_positions
ALTER TABLE portfolio_positions 
  ADD CONSTRAINT fk_portfolio_positions_ticker 
  FOREIGN KEY (ticker) REFERENCES securities(ticker) 
  NOT VALID;

-- Step 2: Add indexes for better join performance (if not already exist)
-- Note: These may already exist, but adding IF NOT EXISTS is safe

CREATE INDEX IF NOT EXISTS idx_dividend_log_ticker_fk ON dividend_log(ticker);
CREATE INDEX IF NOT EXISTS idx_trade_log_ticker_fk ON trade_log(ticker);
CREATE INDEX IF NOT EXISTS idx_portfolio_positions_ticker_fk ON portfolio_positions(ticker);

-- Step 3: Validate constraints (run this AFTER backfilling missing tickers)
-- Uncomment these lines after running backfill_securities_tickers.py:
/*
ALTER TABLE dividend_log 
  VALIDATE CONSTRAINT fk_dividend_log_ticker;

ALTER TABLE trade_log 
  VALIDATE CONSTRAINT fk_trade_log_ticker;

ALTER TABLE portfolio_positions 
  VALIDATE CONSTRAINT fk_portfolio_positions_ticker;
*/

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Foreign key constraints added (NOT VALID)';
    RAISE NOTICE '📝 Next steps:';
    RAISE NOTICE '   1. Run: python web_dashboard/scripts/backfill_securities_tickers.py --execute';
    RAISE NOTICE '   2. Uncomment VALIDATE CONSTRAINT statements above and run again';
END $$;
