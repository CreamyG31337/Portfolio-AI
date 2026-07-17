-- Migration: add trade-level quality quarantine columns to congress_trades
-- Applied via Supabase MCP as add_congress_trades_quality_status (2026-07-17)

ALTER TABLE congress_trades
  ADD COLUMN IF NOT EXISTS quality_status TEXT NOT NULL DEFAULT 'ok',
  ADD COLUMN IF NOT EXISTS quality_reason TEXT,
  ADD COLUMN IF NOT EXISTS suggested_ticker TEXT,
  ADD COLUMN IF NOT EXISTS replacement_trade_id INTEGER REFERENCES congress_trades(id);

ALTER TABLE congress_trades
  DROP CONSTRAINT IF EXISTS congress_trades_quality_status_check;

ALTER TABLE congress_trades
  ADD CONSTRAINT congress_trades_quality_status_check
  CHECK (quality_status IN ('ok', 'garbage', 'corrected'));

CREATE INDEX IF NOT EXISTS idx_congress_trades_quality_status
  ON congress_trades (quality_status);

CREATE OR REPLACE FUNCTION congress_trades_preserve_quality()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF OLD.quality_status IN ('garbage', 'corrected') THEN
    IF COALESCE(current_setting('app.force_quality_update', true), '') IS DISTINCT FROM 'true' THEN
      NEW.quality_status := OLD.quality_status;
      NEW.quality_reason := OLD.quality_reason;
      NEW.suggested_ticker := OLD.suggested_ticker;
      -- Allow first-time link to corrected sibling; then lock it
      IF OLD.replacement_trade_id IS NOT NULL THEN
        NEW.replacement_trade_id := OLD.replacement_trade_id;
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_congress_trades_preserve_quality ON congress_trades;
CREATE TRIGGER trg_congress_trades_preserve_quality
  BEFORE UPDATE ON congress_trades
  FOR EACH ROW
  EXECUTE FUNCTION congress_trades_preserve_quality();
