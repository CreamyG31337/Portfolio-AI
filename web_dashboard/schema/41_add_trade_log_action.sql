-- Restore trade_log.action as explicit BUY | SELL | DIVIDEND.
-- Column is nullable until backfill; then run NOT NULL + default (see footer).

ALTER TABLE trade_log
  ADD COLUMN IF NOT EXISTS action TEXT;

ALTER TABLE trade_log DROP CONSTRAINT IF EXISTS trade_log_action_check;
ALTER TABLE trade_log
  ADD CONSTRAINT trade_log_action_check
  CHECK (action IS NULL OR action IN ('BUY', 'SELL', 'DIVIDEND'));

COMMENT ON COLUMN trade_log.action IS 'Trade side: BUY, SELL, or DIVIDEND (e.g. DRIP). Prefer this over parsing reason.';

-- After backfilling NULLs (see web_dashboard/scripts/backfill_trade_log_action.py --apply):
--   ALTER TABLE trade_log ALTER COLUMN action SET DEFAULT 'BUY';
--   ALTER TABLE trade_log ALTER COLUMN action SET NOT NULL;
