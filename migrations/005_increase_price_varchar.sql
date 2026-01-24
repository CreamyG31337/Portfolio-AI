-- Migration: Increase target_price and stop_loss VARCHAR limits
-- Database: Research (portfolio_research)
-- Issue: LLM sometimes returns longer values like "$142.50 - $150.00 (12% upside)"
-- Date: 2025-01-24

-- Increase VARCHAR(20) to VARCHAR(50) to accommodate longer price descriptions
ALTER TABLE ticker_analysis ALTER COLUMN target_price TYPE VARCHAR(50);
ALTER TABLE ticker_analysis ALTER COLUMN stop_loss TYPE VARCHAR(50);
