# Supabase Production Database Schema

**Generated:** 2026-01-15 02:40:52

**Total Tables:** 29

---

## Table of Contents

- [apscheduler_jobs](#apscheduler-jobs)
- [benchmark_data](#benchmark-data)
- [cash_balances](#cash-balances)
- [committee_assignments](#committee-assignments)
- [committees](#committees)
- [congress_trades](#congress-trades)
- [congress_trades_staging](#congress-trades-staging)
- [contributor_access](#contributor-access)
- [contributors](#contributors)
- [dividend_log](#dividend-log)
- [etf_holdings_log](#etf-holdings-log)
- [exchange_rates](#exchange-rates)
- [fund_contributions](#fund-contributions)
- [fund_thesis](#fund-thesis)
- [fund_thesis_pillars](#fund-thesis-pillars)
- [funds](#funds)
- [job_executions](#job-executions)
- [job_retry_queue](#job-retry-queue)
- [performance_metrics](#performance-metrics)
- [politicians](#politicians)
- [portfolio_positions](#portfolio-positions)
- [research_domain_health](#research-domain-health)
- [rss_feeds](#rss-feeds)
- [securities](#securities)
- [system_settings](#system-settings)
- [trade_log](#trade-log)
- [user_funds](#user-funds)
- [user_profiles](#user-profiles)
- [watched_tickers](#watched-tickers)

---

## apscheduler_jobs

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | VARCHAR(191) | ✗ | - |
| `next_run_time` | DOUBLE PRECISION | ✓ | - |
| `job_state` | BYTEA | ✗ | - |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `ix_apscheduler_jobs_next_run_time` | `next_run_time` | ✗ |

---

## benchmark_data

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | BIGINT | ✗ | nextval('benchmark_data_id_seq'::regclass) |
| `ticker` | TEXT | ✗ | - |
| `date` | DATE | ✗ | - |
| `open` | NUMERIC(12, 4) | ✓ | - |
| `high` | NUMERIC(12, 4) | ✓ | - |
| `low` | NUMERIC(12, 4) | ✓ | - |
| `close` | NUMERIC(12, 4) | ✗ | - |
| `volume` | BIGINT | ✓ | - |
| `adjusted_close` | NUMERIC(12, 4) | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `benchmark_data_ticker_date_key` | `ticker`, `date` | ✓ |
| `idx_benchmark_ticker_date` | `ticker`, `date` | ✗ |

---

## cash_balances

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | uuid_generate_v4() |
| `fund` | VARCHAR(50) | ✗ | - |
| `currency` | VARCHAR(10) | ✗ | - |
| `amount` | NUMERIC(10, 2) | ✗ | 0 |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `cash_balances_fund_currency_key` | `fund`, `currency` | ✓ |
| `idx_cash_balances_fund` | `fund` | ✗ |

---

## committee_assignments

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('committee_assignments_id_seq'::regclass) |
| `politician_id` | INTEGER | ✗ | - |
| `committee_id` | INTEGER | ✗ | - |
| `rank` | INTEGER | ✓ | - |
| `title` | VARCHAR(100) | ✓ | - |
| `party` | VARCHAR(50) | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `committee_id` | `committees`.`id` | NO ACTION | NO ACTION |
| `politician_id` | `politicians`.`id` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `committee_assignments_politician_id_committee_id_key` | `politician_id`, `committee_id` | ✓ |
| `idx_committee_assignments_committee` | `committee_id` | ✗ |
| `idx_committee_assignments_politician` | `politician_id` | ✗ |
| `idx_committee_assignments_politician_committee` | `politician_id`, `committee_id` | ✗ |

---

## committees

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('committees_id_seq'::regclass) |
| `name` | VARCHAR(255) | ✗ | - |
| `code` | VARCHAR(20) | ✓ | - |
| `chamber` | VARCHAR(20) | ✗ | - |
| `target_sectors` | JSONB | ✓ | '[]'::jsonb |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `committees_name_chamber_key` | `name`, `chamber` | ✓ |
| `idx_committees_chamber` | `chamber` | ✗ |
| `idx_committees_code` | `code` | ✗ |
| `idx_committees_name` | `name` | ✗ |
| `idx_committees_target_sectors` | `target_sectors` | ✗ |

---

## congress_trades

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('congress_trades_id_seq'::regclass) |
| `ticker` | VARCHAR(20) | ✗ | - |
| `chamber` | VARCHAR(20) | ✗ | - |
| `transaction_date` | DATE | ✗ | - |
| `disclosure_date` | DATE | ✗ | - |
| `type` | VARCHAR(20) | ✗ | - |
| `amount` | VARCHAR(100) | ✓ | - |
| `asset_type` | VARCHAR(50) | ✓ | - |
| `conflict_score` | DOUBLE PRECISION | ✓ | - |
| `notes` | TEXT | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `price` | NUMERIC(10, 2) | ✓ | NULL::numeric |
| `party` | VARCHAR(50) | ✓ | - |
| `state` | VARCHAR(2) | ✓ | - |
| `owner` | VARCHAR(100) | ✗ | 'Unknown'::character varying |
| `politician_id` | INTEGER | ✓ | - |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `politician_id` | `politicians`.`id` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `congress_trades_politician_ticker_date_amount_type_owner_key` | `politician_id`, `ticker`, `transaction_date`, `amount`, `type`, `owner` | ✓ |
| `idx_congress_chamber` | `chamber` | ✗ |
| `idx_congress_conflict_score` | `conflict_score` | ✗ |
| `idx_congress_disclosure_date` | `disclosure_date` | ✗ |
| `idx_congress_owner` | `owner` | ✗ |
| `idx_congress_party` | `party` | ✗ |
| `idx_congress_state` | `state` | ✗ |
| `idx_congress_ticker` | `ticker` | ✗ |
| `idx_congress_trades_politician_id` | `politician_id` | ✗ |
| `idx_congress_transaction_date` | `transaction_date` | ✗ |

---

## congress_trades_staging

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('congress_trades_staging_id_seq'::regclass) |
| `ticker` | VARCHAR(20) | ✗ | - |
| `politician` | VARCHAR(200) | ✗ | - |
| `chamber` | VARCHAR(20) | ✗ | - |
| `transaction_date` | DATE | ✗ | - |
| `disclosure_date` | DATE | ✗ | - |
| `type` | VARCHAR(20) | ✗ | - |
| `amount` | VARCHAR(100) | ✓ | - |
| `price` | NUMERIC(10, 2) | ✓ | NULL::numeric |
| `asset_type` | VARCHAR(50) | ✓ | - |
| `party` | VARCHAR(50) | ✓ | - |
| `state` | VARCHAR(2) | ✓ | - |
| `owner` | VARCHAR(100) | ✓ | - |
| `conflict_score` | DOUBLE PRECISION | ✓ | - |
| `notes` | TEXT | ✓ | - |
| `import_batch_id` | UUID | ✓ | gen_random_uuid() |
| `import_timestamp` | TIMESTAMP | ✓ | now() |
| `validation_status` | VARCHAR(20) | ✓ | 'pending'::character varying |
| `validation_notes` | TEXT | ✓ | - |
| `promoted_to_production` | BOOLEAN | ✓ | false |
| `promoted_at` | TIMESTAMP | ✓ | - |
| `source_url` | TEXT | ✓ | - |
| `raw_data` | JSONB | ✓ | - |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_staging_batch` | `import_batch_id` | ✗ |
| `idx_staging_date` | `transaction_date` | ✗ |
| `idx_staging_politician` | `politician` | ✗ |
| `idx_staging_promoted` | `promoted_to_production` | ✗ |
| `idx_staging_status` | `validation_status` | ✗ |
| `idx_staging_ticker` | `ticker` | ✗ |

---

## contributor_access

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | uuid_generate_v4() |
| `contributor_id` | UUID | ✓ | - |
| `user_id` | UUID | ✓ | - |
| `access_level` | VARCHAR(50) | ✓ | 'viewer'::character varying |
| `granted_by` | UUID | ✓ | - |
| `granted_at` | TIMESTAMP | ✓ | now() |
| `expires_at` | TIMESTAMP | ✓ | - |
| `notes` | TEXT | ✓ | - |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `contributor_id` | `contributors`.`id` | NO ACTION | NO ACTION |
| `granted_by` | `users`.`id` | NO ACTION | NO ACTION |
| `user_id` | `users`.`id` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `contributor_access_contributor_id_user_id_key` | `contributor_id`, `user_id` | ✓ |
| `idx_contributor_access_contributor` | `contributor_id` | ✗ |
| `idx_contributor_access_user` | `user_id` | ✗ |

---

## contributors

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | uuid_generate_v4() |
| `name` | VARCHAR(255) | ✗ | - |
| `email` | VARCHAR(255) | ✓ | - |
| `phone` | VARCHAR(50) | ✓ | - |
| `address` | TEXT | ✓ | - |
| `kyc_status` | VARCHAR(50) | ✓ | 'pending'::character varying |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `contributors_email_key` | `email` | ✓ |
| `idx_contributors_email` | `email` | ✗ |
| `idx_contributors_name` | `name` | ✗ |

---

## dividend_log

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | uuid_generate_v4() |
| `fund` | VARCHAR(50) | ✗ | - |
| `ticker` | VARCHAR(20) | ✗ | - |
| `ex_date` | DATE | ✗ | - |
| `pay_date` | DATE | ✗ | - |
| `gross_amount` | NUMERIC(15, 6) | ✗ | - |
| `withholding_tax` | NUMERIC(15, 6) | ✗ | 0 |
| `net_amount` | NUMERIC(15, 6) | ✗ | - |
| `reinvested_shares` | NUMERIC(15, 6) | ✗ | - |
| `drip_price` | NUMERIC(10, 2) | ✗ | - |
| `is_verified` | BOOLEAN | ✓ | false |
| `trade_log_id` | UUID | ✓ | - |
| `currency` | VARCHAR(10) | ✗ | 'USD'::character varying |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `fund` | `funds`.`name` | NO ACTION | NO ACTION |
| `trade_log_id` | `trade_log`.`id` | NO ACTION | NO ACTION |
| `ticker` | `securities`.`ticker` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `dividend_log_fund_ticker_ex_date_key` | `fund`, `ticker`, `ex_date` | ✓ |
| `idx_dividend_log_ex_date` | `ex_date` | ✗ |
| `idx_dividend_log_fund` | `fund` | ✗ |
| `idx_dividend_log_pay_date` | `pay_date` | ✗ |
| `idx_dividend_log_ticker` | `ticker` | ✗ |
| `idx_dividend_log_ticker_fk` | `ticker` | ✗ |
| `idx_dividend_log_trade_log_id` | `trade_log_id` | ✗ |

---

## etf_holdings_log

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `date` | DATE | ✗ | - |
| `etf_ticker` | VARCHAR(10) | ✗ | - |
| `holding_ticker` | VARCHAR(50) | ✗ | - |
| `holding_name` | TEXT | ✓ | - |
| `shares_held` | NUMERIC | ✓ | - |
| `weight_percent` | NUMERIC | ✓ | - |
| `market_value` | NUMERIC | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `date`, `etf_ticker`, `holding_ticker`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_etf_holdings_date` | `date` | ✗ |
| `idx_etf_holdings_etf` | `etf_ticker`, `date` | ✗ |
| `idx_etf_holdings_ticker` | `holding_ticker` | ✗ |

---

## exchange_rates

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | uuid_generate_v4() |
| `from_currency` | VARCHAR(3) | ✗ | - |
| `to_currency` | VARCHAR(3) | ✗ | - |
| `rate` | NUMERIC(10, 6) | ✗ | - |
| `timestamp` | TIMESTAMP | ✗ | - |
| `created_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `exchange_rates_from_currency_to_currency_timestamp_key` | `from_currency`, `to_currency`, `timestamp` | ✓ |
| `idx_exchange_rates_currencies` | `from_currency`, `to_currency` | ✗ |
| `idx_exchange_rates_currencies_timestamp` | `from_currency`, `to_currency`, `timestamp` | ✗ |
| `idx_exchange_rates_timestamp` | `timestamp` | ✗ |

---

## fund_contributions

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | uuid_generate_v4() |
| `fund` | VARCHAR(50) | ✗ | - |
| `contributor` | VARCHAR(255) | ✗ | - |
| `email` | VARCHAR(255) | ✓ | - |
| `amount` | NUMERIC(10, 2) | ✗ | - |
| `contribution_type` | VARCHAR(20) | ✗ | - |
| `timestamp` | TIMESTAMP | ✗ | - |
| `notes` | TEXT | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |
| `fund_id` | INTEGER | ✗ | - |
| `contributor_id` | UUID | ✓ | - |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `fund` | `funds`.`name` | NO ACTION | NO ACTION |
| `fund_id` | `funds`.`id` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_fund_contributions_contributor` | `contributor` | ✗ |
| `idx_fund_contributions_fund` | `fund` | ✗ |
| `idx_fund_contributions_fund_contributor` | `fund`, `contributor` | ✗ |
| `idx_fund_contributions_fund_id` | `fund_id` | ✗ |
| `idx_fund_contributions_timestamp` | `timestamp` | ✗ |

---

## fund_thesis

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | uuid_generate_v4() |
| `fund` | VARCHAR(50) | ✗ | - |
| `title` | VARCHAR(255) | ✗ | - |
| `overview` | TEXT | ✗ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `fund` | `funds`.`name` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `fund_thesis_fund_key` | `fund` | ✓ |
| `idx_fund_thesis_fund` | `fund` | ✗ |

---

## fund_thesis_pillars

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | uuid_generate_v4() |
| `thesis_id` | UUID | ✗ | - |
| `name` | VARCHAR(255) | ✗ | - |
| `allocation` | VARCHAR(20) | ✗ | - |
| `thesis` | TEXT | ✗ | - |
| `pillar_order` | INTEGER | ✗ | 0 |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `thesis_id` | `fund_thesis`.`id` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_fund_thesis_pillars_thesis_id` | `thesis_id` | ✗ |

---

## funds

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('funds_id_seq'::regclass) |
| `name` | VARCHAR(100) | ✗ | - |
| `description` | TEXT | ✓ | - |
| `currency` | VARCHAR(10) | ✗ | 'CAD'::character varying |
| `fund_type` | VARCHAR(50) | ✗ | 'investment'::character varying |
| `created_at` | TIMESTAMP | ✓ | now() |
| `base_currency` | VARCHAR(3) | ✓ | 'CAD'::character varying |
| `is_production` | BOOLEAN | ✓ | false |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `funds_name_key` | `name` | ✓ |
| `idx_funds_base_currency` | `base_currency` | ✗ |
| `idx_funds_is_production` | `is_production` | ✗ |

---

## job_executions

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('job_executions_id_seq'::regclass) |
| `job_name` | VARCHAR(100) | ✗ | - |
| `target_date` | DATE | ✗ | - |
| `fund_name` | VARCHAR(200) | ✓ | - |
| `status` | VARCHAR(20) | ✗ | - |
| `started_at` | TIMESTAMP | ✓ | now() |
| `completed_at` | TIMESTAMP | ✓ | - |
| `funds_processed` | ARRAY | ✓ | - |
| `error_message` | TEXT | ✓ | - |
| `duration_ms` | INTEGER | ✓ | - |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_job_executions_date` | `target_date` | ✗ |
| `idx_job_executions_running` | `status` | ✗ |
| `idx_job_executions_status` | `job_name`, `target_date`, `status` | ✗ |
| `unique_job_execution` | `job_name`, `target_date`, `fund_name` | ✓ |

---

## job_retry_queue

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('job_retry_queue_id_seq'::regclass) |
| `job_name` | VARCHAR(100) | ✗ | - |
| `target_date` | DATE | ✓ | - |
| `entity_id` | VARCHAR(200) | ✓ | - |
| `entity_type` | VARCHAR(50) | ✓ | 'fund'::character varying |
| `failure_reason` | VARCHAR(50) | ✗ | - |
| `error_message` | TEXT | ✓ | - |
| `failed_at` | TIMESTAMP | ✓ | now() |
| `retry_count` | INTEGER | ✓ | 0 |
| `last_retry_at` | TIMESTAMP | ✓ | - |
| `status` | VARCHAR(20) | ✗ | 'pending'::character varying |
| `context` | JSONB | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `resolved_at` | TIMESTAMP | ✓ | - |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_retry_queue_created` | `created_at` | ✗ |
| `idx_retry_queue_job_entity` | `job_name`, `entity_type`, `status` | ✗ |
| `idx_retry_queue_pending` | `target_date` | ✗ |
| `idx_retry_queue_status` | `status`, `target_date` | ✗ |
| `unique_retry_entry` | `job_name`, `target_date`, `entity_id`, `entity_type` | ✓ |

---

## performance_metrics

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | uuid_generate_v4() |
| `fund` | VARCHAR(50) | ✗ | - |
| `date` | DATE | ✗ | - |
| `total_value` | NUMERIC(10, 2) | ✗ | - |
| `cost_basis` | NUMERIC(10, 2) | ✗ | - |
| `unrealized_pnl` | NUMERIC(10, 2) | ✗ | - |
| `performance_pct` | NUMERIC(5, 2) | ✗ | - |
| `total_trades` | INTEGER | ✗ | 0 |
| `winning_trades` | INTEGER | ✗ | 0 |
| `losing_trades` | INTEGER | ✗ | 0 |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `fund` | `funds`.`name` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_performance_metrics_date` | `date` | ✗ |
| `idx_performance_metrics_fund` | `fund` | ✗ |
| `performance_metrics_fund_date_key` | `fund`, `date` | ✓ |

---

## politicians

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('politicians_id_seq'::regclass) |
| `name` | VARCHAR(255) | ✗ | - |
| `bioguide_id` | VARCHAR(20) | ✗ | - |
| `party` | VARCHAR(50) | ✓ | - |
| `state` | VARCHAR(2) | ✗ | - |
| `chamber` | VARCHAR(20) | ✗ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_politicians_bioguide_id` | `bioguide_id` | ✗ |
| `idx_politicians_chamber` | `chamber` | ✗ |
| `idx_politicians_name` | `name` | ✗ |
| `idx_politicians_state` | `state` | ✗ |
| `politicians_bioguide_id_key` | `bioguide_id` | ✓ |

---

## portfolio_positions

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | uuid_generate_v4() |
| `fund` | VARCHAR(50) | ✗ | - |
| `ticker` | VARCHAR(20) | ✗ | - |
| `shares` | NUMERIC(15, 6) | ✗ | - |
| `price` | NUMERIC(10, 2) | ✗ | - |
| `cost_basis` | NUMERIC(10, 2) | ✗ | - |
| `pnl` | NUMERIC(10, 2) | ✗ | 0 |
| `total_value` | NUMERIC(10, 2) | ✓ | - |
| `currency` | VARCHAR(10) | ✗ | 'USD'::character varying |
| `date` | TIMESTAMP | ✗ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |
| `base_currency` | VARCHAR(3) | ✓ | - |
| `total_value_base` | NUMERIC(15, 2) | ✓ | - |
| `cost_basis_base` | NUMERIC(15, 2) | ✓ | - |
| `pnl_base` | NUMERIC(15, 2) | ✓ | - |
| `exchange_rate` | NUMERIC(10, 6) | ✓ | - |
| `date_only` | DATE | ✓ | - |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `fund` | `funds`.`name` | NO ACTION | NO ACTION |
| `ticker` | `securities`.`ticker` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_portfolio_positions_base_currency` | `base_currency` | ✗ |
| `idx_portfolio_positions_date` | `date` | ✗ |
| `idx_portfolio_positions_date_fund` | `date`, `fund` | ✗ |
| `idx_portfolio_positions_fund` | `fund` | ✗ |
| `idx_portfolio_positions_fund_date` | `fund`, `date` | ✗ |
| `idx_portfolio_positions_fund_date_ticker` | `fund`, `date`, `ticker` | ✗ |
| `idx_portfolio_positions_fund_ticker` | `fund`, `ticker` | ✗ |
| `idx_portfolio_positions_fund_ticker_date` | `fund`, `ticker`, `date` | ✗ |
| `idx_portfolio_positions_ticker` | `ticker` | ✗ |
| `idx_portfolio_positions_ticker_fk` | `ticker` | ✗ |
| `idx_portfolio_positions_ticker_fund_date` | `ticker`, `fund`, `date` | ✗ |
| `idx_portfolio_positions_unique` | `fund`, `ticker`, `date_only` | ✓ |
| `portfolio_positions_unique_fund_ticker_date` | `fund`, `ticker`, `date_only` | ✓ |

---

## research_domain_health

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `domain` | TEXT | ✗ | - |
| `total_attempts` | INTEGER | ✓ | 0 |
| `total_successes` | INTEGER | ✓ | 0 |
| `total_failures` | INTEGER | ✓ | 0 |
| `consecutive_failures` | INTEGER | ✓ | 0 |
| `last_failure_reason` | TEXT | ✓ | - |
| `last_attempt_at` | TIMESTAMP | ✓ | - |
| `last_success_at` | TIMESTAMP | ✓ | - |
| `auto_blacklisted` | BOOLEAN | ✓ | false |
| `auto_blacklisted_at` | TIMESTAMP | ✓ | - |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `domain`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_domain_health_blacklisted` | `auto_blacklisted`, `domain` | ✗ |
| `idx_domain_health_consecutive` | `consecutive_failures`, `domain` | ✗ |

---

## rss_feeds

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('rss_feeds_id_seq'::regclass) |
| `name` | VARCHAR(200) | ✗ | - |
| `url` | TEXT | ✗ | - |
| `category` | VARCHAR(100) | ✓ | - |
| `enabled` | BOOLEAN | ✓ | true |
| `last_fetched_at` | TIMESTAMP | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_rss_feeds_enabled` | `enabled` | ✗ |
| `idx_rss_feeds_last_fetched` | `last_fetched_at` | ✗ |
| `rss_feeds_url_key` | `url` | ✓ |

---

## securities

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `ticker` | VARCHAR(20) | ✗ | - |
| `company_name` | TEXT | ✓ | - |
| `sector` | TEXT | ✓ | - |
| `industry` | TEXT | ✓ | - |
| `country` | VARCHAR(50) | ✓ | - |
| `market_cap` | TEXT | ✓ | - |
| `currency` | VARCHAR(3) | ✓ | - |
| `last_updated` | TIMESTAMP | ✓ | now() |
| `created_at` | TIMESTAMP | ✓ | now() |
| `trailing_pe` | NUMERIC | ✓ | - |
| `dividend_yield` | NUMERIC | ✓ | - |
| `fifty_two_week_high` | NUMERIC | ✓ | - |
| `fifty_two_week_low` | NUMERIC | ✓ | - |

### Primary Key

- `ticker`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_securities_currency` | `currency` | ✗ |
| `idx_securities_industry` | `industry` | ✗ |
| `idx_securities_last_updated` | `last_updated` | ✗ |
| `idx_securities_sector` | `sector` | ✗ |

---

## system_settings

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `key` | TEXT | ✗ | - |
| `value` | JSONB | ✗ | - |
| `description` | TEXT | ✓ | - |
| `updated_at` | TIMESTAMP | ✓ | now() |
| `updated_by` | UUID | ✓ | - |

### Primary Key

- `key`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `updated_by` | `users`.`id` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_system_settings_updated_at` | `updated_at` | ✗ |

---

## trade_log

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | uuid_generate_v4() |
| `fund` | VARCHAR(50) | ✗ | - |
| `date` | TIMESTAMP | ✗ | - |
| `ticker` | VARCHAR(20) | ✗ | - |
| `shares` | NUMERIC(15, 6) | ✗ | - |
| `price` | NUMERIC(10, 2) | ✗ | - |
| `cost_basis` | NUMERIC(10, 2) | ✗ | - |
| `pnl` | NUMERIC(10, 2) | ✗ | 0 |
| `reason` | TEXT | ✗ | - |
| `currency` | VARCHAR(10) | ✗ | 'USD'::character varying |
| `created_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `fund` | `funds`.`name` | NO ACTION | NO ACTION |
| `ticker` | `securities`.`ticker` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_trade_log_date` | `date` | ✗ |
| `idx_trade_log_fund` | `fund` | ✗ |
| `idx_trade_log_ticker` | `ticker` | ✗ |
| `idx_trade_log_ticker_fk` | `ticker` | ✗ |

---

## user_funds

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | uuid_generate_v4() |
| `user_id` | UUID | ✓ | - |
| `fund_name` | VARCHAR(50) | ✗ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `fund_id` | INTEGER | ✓ | - |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `fund_id` | `funds`.`id` | NO ACTION | NO ACTION |
| `user_id` | `users`.`id` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_user_funds_fund_id` | `fund_id` | ✗ |
| `idx_user_funds_fund_name` | `fund_name` | ✗ |
| `idx_user_funds_user_id` | `user_id` | ✗ |
| `user_funds_user_id_fund_name_key` | `user_id`, `fund_name` | ✓ |

---

## user_profiles

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | uuid_generate_v4() |
| `user_id` | UUID | ✓ | - |
| `email` | VARCHAR(255) | ✗ | - |
| `full_name` | VARCHAR(255) | ✓ | - |
| `role` | VARCHAR(50) | ✓ | 'user'::character varying |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |
| `preferences` | JSONB | ✓ | '{}'::jsonb |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `user_id` | `users`.`id` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_user_profiles_preferences` | `preferences` | ✗ |
| `idx_user_profiles_user_id` | `user_id` | ✗ |
| `user_profiles_user_id_key` | `user_id` | ✓ |

---

## watched_tickers

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `ticker` | VARCHAR(20) | ✗ | - |
| `priority_tier` | VARCHAR(10) | ✓ | 'B'::character varying |
| `is_active` | BOOLEAN | ✓ | true |
| `source` | VARCHAR(50) | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `ticker`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_watched_tickers_active` | `is_active` | ✗ |
| `idx_watched_tickers_priority` | `priority_tier` | ✗ |

---

