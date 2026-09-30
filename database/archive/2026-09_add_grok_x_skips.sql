-- Migration: Grok Bot sweep skip list
-- Date: 2026-09-12
-- Database: Research Postgres (NOT Supabase)

CREATE TABLE IF NOT EXISTS grok_x_skips (
    ticker VARCHAR(20) NOT NULL,
    reason VARCHAR(200) NOT NULL,
    source VARCHAR(10) NOT NULL DEFAULT 'manual'
        CHECK (source IN ('auto', 'manual')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker)
);

CREATE INDEX IF NOT EXISTS idx_grok_x_skips_source
    ON grok_x_skips (source, created_at DESC);

COMMENT ON TABLE grok_x_skips IS
    'Tickers excluded from the Grok Bot queue. auto rows come from zero-post briefs; manual rows are curated. Delete a row to resume sweeping that ticker.';

-- Seed: broad-market index funds (no company for X to discuss) and sector
-- duplicates, keeping one fund per sector for a sector read.
INSERT INTO grok_x_skips (ticker, reason, source) VALUES
    ('XEQT.TO', 'broad-market index ETF', 'manual'),
    ('XIC.TO',  'broad-market index ETF', 'manual'),
    ('VFV.TO',  'broad-market index ETF', 'manual'),
    ('VOO',     'broad-market index ETF', 'manual'),
    ('VTI',     'broad-market index ETF', 'manual'),
    ('VEE.TO',  'broad-market index ETF', 'manual'),
    ('ZEA.TO',  'broad-market index ETF', 'manual'),
    ('ZCH.TO',  'broad-market index ETF', 'manual'),
    ('XHC.TO',  'broad-market index ETF', 'manual'),
    ('FTXL',    'sector duplicate; SMH kept for semis', 'manual'),
    ('BUG',     'sector duplicate; CIBR kept for cyber', 'manual'),
    ('XHAK.TO', 'sector duplicate; CIBR kept for cyber', 'manual'),
    ('ROBO',    'sector duplicate; SMH kept for semis/robotics', 'manual'),
    ('NXTG.TO', 'sector duplicate; SMH kept for semis/5G', 'manual'),
    ('FXD',     'sector duplicate; First Trust sector sleeve', 'manual'),
    ('FXG',     'sector duplicate; First Trust sector sleeve', 'manual'),
    ('FXL',     'sector duplicate; First Trust sector sleeve', 'manual'),
    ('XMA.TO',  'sector duplicate; materials sleeve', 'manual'),
    ('GLCC.TO', 'sector duplicate; XGD.TO kept for gold', 'manual'),
    ('CGL.TO',  'sector duplicate; XGD.TO kept for gold', 'manual'),
    ('GLO.TO',  'sector duplicate; XGD.TO kept for gold', 'manual'),
    ('HURA.TO', 'sector duplicate; URNM kept for uranium', 'manual'),
    ('URNJ',    'sector duplicate; URNM kept for uranium', 'manual')
ON CONFLICT (ticker) DO NOTHING;
