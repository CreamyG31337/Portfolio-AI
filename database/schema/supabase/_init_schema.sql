-- Master Init Schema
-- Generated: 2026-01-15 02:59:22

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- SEQUENCES
\i sequences/benchmark_data_id_seq.sql
\i sequences/committee_assignments_id_seq.sql
\i sequences/committees_id_seq.sql
\i sequences/congress_trades_id_seq.sql
\i sequences/congress_trades_staging_id_seq.sql
\i sequences/funds_id_seq.sql
\i sequences/job_executions_id_seq.sql
\i sequences/job_retry_queue_id_seq.sql
\i sequences/politicians_id_seq.sql
\i sequences/rss_feeds_id_seq.sql

-- TABLES
\i tables/apscheduler_jobs.sql
\i tables/benchmark_data.sql
\i tables/cash_balances.sql
\i tables/committee_assignments.sql
\i tables/committees.sql
\i tables/congress_trades.sql
\i tables/congress_trades_staging.sql
\i tables/contributor_access.sql
\i tables/contributors.sql
\i tables/dividend_log.sql
\i tables/etf_holdings_log.sql
\i tables/exchange_rates.sql
\i tables/fund_contributions.sql
\i tables/fund_thesis.sql
\i tables/fund_thesis_pillars.sql
\i tables/funds.sql
\i tables/job_executions.sql
\i tables/job_retry_queue.sql
\i tables/performance_metrics.sql
\i tables/politicians.sql
\i tables/portfolio_positions.sql
\i tables/research_domain_health.sql
\i tables/rss_feeds.sql
\i tables/securities.sql
\i tables/system_settings.sql
\i tables/trade_log.sql
\i tables/user_funds.sql
\i tables/user_profiles.sql
\i tables/watched_tickers.sql

-- FUNCTIONS
\i functions/assign_fund_to_user.sql
\i functions/backfill_preconverted_values.sql
\i functions/calculate_daily_performance.sql
\i functions/can_modify_data.sql
\i functions/create_user_profile.sql
\i functions/delete_user_safe.sql
\i functions/get_exchange_rate_for_date.sql
\i functions/get_fund_thesis.sql
\i functions/get_latest_exchange_rate.sql
\i functions/get_user_accessible_funds.sql
\i functions/get_user_funds.sql
\i functions/get_user_preference.sql
\i functions/get_user_preferences.sql
\i functions/grant_admin_role.sql
\i functions/grant_contributor_access.sql
\i functions/is_admin.sql
\i functions/list_unregistered_contributors.sql
\i functions/list_users_with_funds.sql
\i functions/normalize_email.sql
\i functions/remove_fund_from_user.sql
\i functions/revoke_admin_role.sql
\i functions/revoke_contributor_access.sql
\i functions/set_portfolio_position_date_only.sql
\i functions/set_user_preference.sql
\i functions/update_updated_at_column.sql
\i functions/user_has_contributor_access.sql
\i functions/user_has_fund_access.sql
\i functions/get_etf_holding_trades.sql

-- VIEWS
\i views/congress_trades_enriched.sql
\i views/contributor_ownership.sql
\i views/daily_portfolio_snapshots.sql
\i views/fund_contributor_summary.sql
\i views/fund_thesis_with_pillars.sql
\i views/latest_positions.sql

-- TRIGGERS
\i triggers/trigger_set_portfolio_position_date_only.sql
\i triggers/update_dividend_log_updated_at.sql
\i triggers/update_fund_contributions_updated_at.sql
\i triggers/update_performance_metrics_updated_at.sql
\i triggers/update_portfolio_positions_updated_at.sql

-- POLICIES
\i policies/benchmark_data_Allow authenticated users to read benchmark data.sql
\i policies/benchmark_data_Allow public read access to benchmark data.sql
\i policies/benchmark_data_Allow service role to insert benchmark data.sql
\i policies/benchmark_data_Allow service role to manage benchmark data.sql
\i policies/benchmark_data_Allow service role to update benchmark data.sql
\i policies/cash_balances_Admins can view all cash balances.sql
\i policies/cash_balances_Service role full access to cash_balances.sql
\i policies/cash_balances_Users can view cash balances for their funds.sql
\i policies/committee_assignments_Allow authenticated users to read committee_assignments.sql
\i policies/committee_assignments_Service role can manage committee_assignments.sql
\i policies/committees_Allow authenticated users to read committees.sql
\i policies/committees_Service role can manage committees.sql
\i policies/congress_trades_Allow authenticated users to read congress_trades.sql
\i policies/congress_trades_Service role can manage congress_trades.sql
\i policies/congress_trades_staging_Service role can manage congress_trades_staging.sql
\i policies/contributor_access_Admins can manage all contributor access.sql
\i policies/contributor_access_Admins can view all contributor access.sql
\i policies/contributor_access_Owners can grant access to their contributors.sql
\i policies/contributor_access_Users can view their own contributor access.sql
\i policies/contributors_Admins can manage all contributors.sql
\i policies/contributors_Users can view accessible contributors.sql
\i policies/dividend_log_Allow all operations on dividend_log.sql
\i policies/etf_holdings_log_Allow authenticated read access.sql
\i policies/etf_holdings_log_Allow service role full access.sql
\i policies/exchange_rates_Allow authenticated users to manage exchange_rates.sql
\i policies/exchange_rates_Allow public read access to exchange_rates.sql
\i policies/exchange_rates_Allow service role full access to exchange_rates.sql
\i policies/fund_contributions_Admins can manage all contributions.sql
\i policies/fund_contributions_Allow service role operations.sql
\i policies/fund_contributions_Users can insert contributions for accessible contributors.sql
\i policies/fund_contributions_Users can update contributions for accessible contributors.sql
\i policies/fund_contributions_Users can view contributions for accessible contributors.sql
\i policies/fund_contributions_Users can view contributions for their funds.sql
\i policies/fund_thesis_Allow all operations on fund_thesis.sql
\i policies/fund_thesis_pillars_Allow all operations on fund_thesis_pillars.sql
\i policies/funds_Service role can manage funds.sql
\i policies/funds_Users can view assigned funds.sql
\i policies/job_executions_Allow authenticated users to read job executions.sql
\i policies/job_executions_Allow service role to write job executions.sql
\i policies/performance_metrics_Admins can view all performance metrics.sql
\i policies/performance_metrics_Service role full access to performance_metrics.sql
\i policies/performance_metrics_Users can view performance metrics for their funds.sql
\i policies/politicians_Allow authenticated users to read politicians.sql
\i policies/politicians_Service role can manage politicians.sql
\i policies/portfolio_positions_Admins can view all portfolio positions.sql
\i policies/portfolio_positions_Service role full access to portfolio_positions.sql
\i policies/portfolio_positions_Users can view portfolio positions for their funds.sql
\i policies/research_domain_health_Anyone can view domain health stats.sql
\i policies/research_domain_health_Service role can modify domain health.sql
\i policies/rss_feeds_Service role can manage rss_feeds.sql
\i policies/securities_Allow read access to securities.sql
\i policies/securities_Service role can manage securities.sql
\i policies/system_settings_Anyone can view system settings.sql
\i policies/system_settings_Only admins can modify system settings.sql
\i policies/trade_log_Admins can view all trades.sql
\i policies/trade_log_Service role full access to trade_log.sql
\i policies/trade_log_Users can view trades for their funds.sql
\i policies/user_funds_Users can delete their own fund assignments.sql
\i policies/user_funds_Users can insert their own fund assignments.sql
\i policies/user_funds_Users can update their own fund assignments.sql
\i policies/user_funds_Users can view their own fund assignments.sql
\i policies/user_profiles_Service role full access to user_profiles.sql
\i policies/user_profiles_Users can insert their own profile.sql
\i policies/user_profiles_Users can update their own profile.sql
\i policies/user_profiles_Users can view own profile.sql
\i policies/watched_tickers_Allow authenticated users to read watched_tickers.sql
\i policies/watched_tickers_Service role can manage watched_tickers.sql
