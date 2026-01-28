-- Migration: Remove company_name column from insider_trades table
-- Date: 2026-01-27
-- Description: company_name should not be stored in insider_trades table.
--              Company names should be looked up from the securities table instead.

-- Drop the company_name column from insider_trades table
ALTER TABLE insider_trades DROP COLUMN IF EXISTS company_name;

-- Note: No data migration needed since company_name was always NULL or empty
--       and company names are now fetched from the securities table via ticker lookup
