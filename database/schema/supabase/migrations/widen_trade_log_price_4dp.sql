-- Allow 4-decimal trade prices (sub-dollar micro-caps quote to 0.0001).
-- trade_log.price was NUMERIC(10, 2), so even a 3-decimal price entered on the
-- trade entry form was silently rounded to 2 decimals on insert. Widening keeps
-- every existing value and the same 8 integer digits. No views depend on it.
-- Applied to production 2026-10-15.
-- portfolio_positions.price is still NUMERIC(10, 2); widening it means dropping
-- and recreating latest_positions and daily_portfolio_snapshots.

ALTER TABLE public.trade_log ALTER COLUMN price TYPE NUMERIC(12, 4);
