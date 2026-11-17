-- Migration: add_get_portfolio_daily_totals
-- Purpose: SQL-side daily aggregation for the dashboard performance chart.
--          Avoids paginating every portfolio_positions row for long-history funds (TFSA).

\i ../functions/get_portfolio_daily_totals.sql
