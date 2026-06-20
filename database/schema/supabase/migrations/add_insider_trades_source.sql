-- G7: provenance for US QuiverQuant scrape vs yfinance SEDI (.TO/.V)
ALTER TABLE insider_trades
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'sec_form4';

COMMENT ON COLUMN insider_trades.source IS
  'Provenance: sec_form4 (US QuiverQuant scrape) | yahoo_sedi (yfinance .TO/.V)';
