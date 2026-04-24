-- =====================================================
-- PORTFOLIO DASHBOARD - MAIN SCHEMA
-- =====================================================
-- This is the core schema for the portfolio dashboard
-- Run this FIRST before any other schema files
-- =====================================================

-- Drop everything first (clean slate)
DROP VIEW IF EXISTS current_positions CASCADE;
DROP TABLE IF EXISTS portfolio_positions CASCADE;
DROP TABLE IF EXISTS trade_log CASCADE;
DROP TABLE IF EXISTS cash_balances CASCADE;
DROP TABLE IF EXISTS performance_metrics CASCADE;
DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE;
DROP FUNCTION IF EXISTS calculate_daily_performance(DATE, VARCHAR) CASCADE;

-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================================================
-- CORE PORTFOLIO TABLES
-- =====================================================

-- Portfolio positions table
CREATE TABLE portfolio_positions (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    fund VARCHAR(50) NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    company VARCHAR(255),  -- Company name (optional, for display)
    shares DECIMAL(15, 6) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    cost_basis DECIMAL(10, 2) NOT NULL,
    pnl DECIMAL(10, 2) NOT NULL DEFAULT 0,
    total_value DECIMAL(10, 2) GENERATED ALWAYS AS (shares * price) STORED,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    date TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    -- Additional fields to match Position model expectations
    unrealized_pnl DECIMAL(10, 2) DEFAULT 0,
    stop_loss DECIMAL(10, 2) DEFAULT NULL,
    current_price DECIMAL(10, 2) DEFAULT NULL,
    avg_price DECIMAL(10, 2) GENERATED ALWAYS AS (cost_basis / NULLIF(shares, 0)) STORED
);

-- Migration: Add missing columns to existing portfolio_positions table (if upgrading)
-- This should be run after creating the new table structure
ALTER TABLE portfolio_positions ADD COLUMN IF NOT EXISTS company VARCHAR(255);
ALTER TABLE portfolio_positions ADD COLUMN IF NOT EXISTS unrealized_pnl DECIMAL(10, 2) DEFAULT 0;
ALTER TABLE portfolio_positions ADD COLUMN IF NOT EXISTS stop_loss DECIMAL(10, 2) DEFAULT NULL;
ALTER TABLE portfolio_positions ADD COLUMN IF NOT EXISTS current_price DECIMAL(10, 2) DEFAULT NULL;
ALTER TABLE portfolio_positions ADD COLUMN IF NOT EXISTS avg_price DECIMAL(10, 2) GENERATED ALWAYS AS (cost_basis / NULLIF(shares, 0)) STORED;

-- Trade log table
CREATE TABLE trade_log (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    fund VARCHAR(50) NOT NULL,
    date TIMESTAMP WITH TIME ZONE NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    shares DECIMAL(15, 6) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    cost_basis DECIMAL(10, 2) NOT NULL,
    pnl DECIMAL(10, 2) NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    action VARCHAR(10) NOT NULL DEFAULT 'BUY',
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT trade_log_action_check CHECK (action IN ('BUY', 'SELL', 'DIVIDEND'))
);

-- Cash balances table
CREATE TABLE cash_balances (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    fund VARCHAR(50) NOT NULL,
    currency VARCHAR(10) NOT NULL,
    amount DECIMAL(10, 2) NOT NULL DEFAULT 0,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(fund, currency)
);

-- Performance metrics table for caching
CREATE TABLE performance_metrics (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    fund VARCHAR(50) NOT NULL,
    date DATE NOT NULL,
    total_value DECIMAL(10, 2) NOT NULL,
    cost_basis DECIMAL(10, 2) NOT NULL,
    unrealized_pnl DECIMAL(10, 2) NOT NULL,
    performance_pct DECIMAL(5, 2) NOT NULL,
    total_trades INTEGER NOT NULL DEFAULT 0,
    winning_trades INTEGER NOT NULL DEFAULT 0,
    losing_trades INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(fund, date)
);

-- =====================================================
-- INDEXES FOR PERFORMANCE
-- =====================================================

-- Portfolio positions indexes
CREATE INDEX idx_portfolio_positions_fund ON portfolio_positions(fund);
CREATE INDEX idx_portfolio_positions_ticker ON portfolio_positions(ticker);
CREATE INDEX idx_portfolio_positions_date ON portfolio_positions(date);
CREATE INDEX idx_portfolio_positions_fund_ticker ON portfolio_positions(fund, ticker);
CREATE INDEX idx_portfolio_positions_company ON portfolio_positions(company);

-- Trade log indexes
CREATE INDEX idx_trade_log_fund ON trade_log(fund);
CREATE INDEX idx_trade_log_ticker ON trade_log(ticker);
CREATE INDEX idx_trade_log_date ON trade_log(date);

-- Cash balances indexes
CREATE INDEX idx_cash_balances_fund ON cash_balances(fund);

-- Performance metrics indexes
CREATE INDEX idx_performance_metrics_fund ON performance_metrics(fund);
CREATE INDEX idx_performance_metrics_date ON performance_metrics(date);

-- =====================================================
-- TRIGGERS AND FUNCTIONS
-- =====================================================

-- Updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create triggers for updated_at
CREATE TRIGGER update_portfolio_positions_updated_at
    BEFORE UPDATE ON portfolio_positions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_performance_metrics_updated_at
    BEFORE UPDATE ON performance_metrics
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =====================================================
-- VIEWS
-- =====================================================

-- Current positions view (shares > 0)
CREATE VIEW current_positions AS
SELECT
    fund,
    ticker,
    currency,
    MAX(company) as company,
    SUM(shares) as total_shares,
    AVG(price) as avg_price,
    SUM(cost_basis) as total_cost_basis,
    SUM(pnl) as total_pnl,
    SUM(total_value) as total_market_value,
    MAX(date) as last_updated
FROM portfolio_positions
WHERE shares > 0
GROUP BY fund, ticker, currency;

-- =====================================================
-- UTILITY FUNCTIONS
-- =====================================================

-- Function to calculate daily performance by fund
CREATE OR REPLACE FUNCTION calculate_daily_performance(target_date DATE, fund_name VARCHAR(50) DEFAULT NULL)
RETURNS TABLE (
    fund VARCHAR(50),
    total_value DECIMAL(10, 2),
    cost_basis DECIMAL(10, 2),
    unrealized_pnl DECIMAL(10, 2),
    performance_pct DECIMAL(5, 2)
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.fund,
        COALESCE(SUM(p.total_value), 0) as total_value,
        COALESCE(SUM(p.cost_basis), 0) as cost_basis,
        COALESCE(SUM(p.pnl), 0) as unrealized_pnl,
        CASE
            WHEN SUM(p.cost_basis) > 0 THEN (SUM(p.pnl) / SUM(p.cost_basis)) * 100
            ELSE 0
        END as performance_pct
    FROM portfolio_positions p
    WHERE p.date::date = target_date
      AND p.shares > 0
      AND (fund_name IS NULL OR p.fund = fund_name)
    GROUP BY p.fund;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- INITIAL DATA SETUP
-- =====================================================

-- Insert initial cash balances for common funds
INSERT INTO cash_balances (fund, currency, amount) VALUES
    ('Project Chimera', 'CAD', 0.00),
    ('Project Chimera', 'USD', 0.00),
    ('RRSP Lance Webull', 'CAD', 0.00),
    ('RRSP Lance Webull', 'USD', 0.00),
    ('TEST', 'CAD', 0.00),
    ('TEST', 'USD', 0.00),
    ('TFSA', 'CAD', 0.00),
    ('TFSA', 'USD', 0.00)
ON CONFLICT (fund, currency) DO NOTHING;

-- =====================================================
-- BASIC RLS (Will be enhanced by auth schema)
-- =====================================================

-- Enable Row Level Security (basic - will be enhanced by auth schema)
ALTER TABLE portfolio_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE trade_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE cash_balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE performance_metrics ENABLE ROW LEVEL SECURITY;

-- Basic RLS policies (allow all for now - will be restricted by auth schema)
CREATE POLICY "Allow all operations on portfolio_positions" ON portfolio_positions
    FOR ALL USING (true);

CREATE POLICY "Allow all operations on trade_log" ON trade_log
    FOR ALL USING (true);

CREATE POLICY "Allow all operations on cash_balances" ON cash_balances
    FOR ALL USING (true);

CREATE POLICY "Allow all operations on performance_metrics" ON performance_metrics
    FOR ALL USING (true);

-- =====================================================
-- SCHEMA COMPLETE
-- =====================================================

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Main schema created successfully!';
    RAISE NOTICE '📋 Next step: Run 02_auth_schema.sql';
    RAISE NOTICE '🔐 This will add user authentication and permissions';
END $$;
