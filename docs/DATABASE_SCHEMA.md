# Supabase Database Schema Documentation

## Overview
The "Portfolio-AI" database schema is defined using raw SQL files located in `web_dashboard/schema/`. This folder is the **single source of truth** for the database structure.

**Optimization Status:** Views pre-calculate `market_value` and P&L for performance.
**Migration Tool:** `migrate.py` applies these schema files to your Supabase instance.

## 🗂️ Schema Index

### 1. Core Portfolio & Trading
*   **[01_main_schema.sql](../web_dashboard/schema/01_main_schema.sql)**: Core tables (`portfolio_positions`, `trade_log`)
*   **[08_optimized_views_with_historical_pnl.sql](../web_dashboard/schema/08_optimized_views_with_historical_pnl.sql)**: Performance calculation views
*   **[05_fund_contributions_schema.sql](../web_dashboard/schema/05_fund_contributions_schema.sql)**: Fund capital tracking

### 2. Authentication & Users
*   **[02_auth_schema.sql](../web_dashboard/schema/02_auth_schema.sql)**: User profiles, RLS policies, and triggers
*   **[06_user_preferences.sql](../web_dashboard/schema/06_user_preferences.sql)**: User-specific settings (themes, default funds)
*   **[37_admin_role_management.sql](../web_dashboard/schema/37_admin_role_management.sql)**: Admin permissions system

### 3. AI Research System
*   **[10_research_articles.sql](../web_dashboard/schema/10_research_articles.sql)**: Article storage and vector embeddings
*   **[13_rss_feeds.sql](../web_dashboard/schema/13_rss_feeds.sql)**: RSS feed configurations
*   **[18_social_metrics.sql](../web_dashboard/schema/18_social_metrics.sql)**: Social sentiment tracking

### 4. Congress Trading
*   **[20_congress_trades.sql](../web_dashboard/schema/20_congress_trades.sql)**: Core tracking for politician trades
*   **[21_committees.sql](../web_dashboard/schema/21_committees.sql)**: Committee assignments and metadata
*   **[26_create_congress_trades_enriched_view.sql](../web_dashboard/schema/26_create_congress_trades_enriched_view.sql)**: Analytics views

### 5. System & data
*   **[09_exchange_rates_schema.sql](../web_dashboard/schema/09_exchange_rates_schema.sql)**: Historical USD/CAD rates
*   **[12_job_executions_tracking.sql](../web_dashboard/schema/12_job_executions_tracking.sql)**: Background job logs
*   **[30_job_retry_queue.sql](../web_dashboard/schema/30_job_retry_queue.sql)**: Resilience queue for failed jobs

> **Note:** Always check the `web_dashboard/schema/` directory for the most up-to-date definitions.
