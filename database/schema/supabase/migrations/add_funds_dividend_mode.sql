-- Add explicit per-fund dividend handling mode.
-- Backfill with current behavior:
--   rrsp => cash
--   all other fund types => reinvest

ALTER TABLE funds
ADD COLUMN IF NOT EXISTS dividend_mode VARCHAR(20);

UPDATE funds
SET dividend_mode = CASE
    WHEN LOWER(COALESCE(fund_type, '')) = 'rrsp' THEN 'cash'
    ELSE 'reinvest'
END
WHERE dividend_mode IS NULL OR BTRIM(dividend_mode) = '';

UPDATE funds
SET dividend_mode = CASE
    WHEN LOWER(dividend_mode) = 'cash' THEN 'cash'
    ELSE 'reinvest'
END;

ALTER TABLE funds
ALTER COLUMN dividend_mode SET DEFAULT 'reinvest';

ALTER TABLE funds
ALTER COLUMN dividend_mode SET NOT NULL;

ALTER TABLE funds
DROP CONSTRAINT IF EXISTS funds_dividend_mode_check;

ALTER TABLE funds
ADD CONSTRAINT funds_dividend_mode_check
CHECK (dividend_mode IN ('reinvest', 'cash'));
