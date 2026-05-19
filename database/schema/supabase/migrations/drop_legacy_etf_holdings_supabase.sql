-- Drop legacy Supabase ETF holdings objects (data lives in Research Postgres).
-- Prerequisites:
--   1. Research etf_holdings_log is source of truth (Watchtower writes there).
--   2. App code no longer queries Supabase etf_holdings_log / etf_holdings_changes.
--   3. Optional: pg_dump or migrate_etf_holdings.py audit for archive.
--
-- Safe drop order (views/functions before table):

DROP VIEW IF EXISTS public.etf_holdings_changes CASCADE;

DROP FUNCTION IF EXISTS public.get_etf_holding_trades_batch(text[], date, date, integer);
DROP FUNCTION IF EXISTS public.get_etf_holding_trades(text, date, date, text);

DROP TABLE IF EXISTS public.etf_holdings_log CASCADE;
