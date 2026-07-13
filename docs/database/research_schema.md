# Research Database Database Schema

**Generated:** 2026-07-13 14:12:47

**Total Tables:** 30

---

## Table of Contents

- [action_queue_ai_review](#action-queue-ai-review)
- [confluence_events](#confluence-events)
- [congress_trade_sessions](#congress-trade-sessions)
- [congress_trades_analysis](#congress-trades-analysis)
- [dilution_observations](#dilution-observations)
- [etf_holdings_log](#etf-holdings-log)
- [extracted_tickers](#extracted-tickers)
- [filing_events](#filing-events)
- [idea_triage](#idea-triage)
- [market_daily_brief](#market-daily-brief)
- [market_relationships](#market-relationships)
- [newsletters](#newsletters)
- [post_summaries](#post-summaries)
- [research_articles](#research-articles)
- [rss_feeds](#rss-feeds)
- [sector_meta_analysis](#sector-meta-analysis)
- [securities](#securities)
- [sentiment_sessions](#sentiment-sessions)
- [social_metrics](#social-metrics)
- [social_posts](#social-posts)
- [social_sentiment_analysis](#social-sentiment-analysis)
- [stance_history](#stance-history)
- [stance_outcomes](#stance-outcomes)
- [thesis_entries](#thesis-entries)
- [thesis_evidence](#thesis-evidence)
- [ticker_analysis](#ticker-analysis)
- [ticker_meta_analysis](#ticker-meta-analysis)
- [ticker_theses](#ticker-theses)
- [ui_ai_rollup_fund](#ui-ai-rollup-fund)
- [ui_ai_summary](#ui-ai-summary)

---

## action_queue_ai_review

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `fund_key` | TEXT | ✗ | ''::text |
| `ticker` | VARCHAR(20) | ✗ | - |
| `signal_analysis_date` | DATE | ✓ | - |
| `verdict` | VARCHAR(30) | ✗ | - |
| `one_liner` | TEXT | ✓ | - |
| `model_used` | VARCHAR(100) | ✓ | - |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `action_queue_ai_review_unique_key` | `fund_key`, `ticker`, `signal_analysis_date` | ✓ |
| `idx_action_queue_ai_review_ticker` | `ticker` | ✗ |
| `idx_action_queue_ai_review_updated` | `updated_at` | ✗ |

---

## confluence_events

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `ticker` | VARCHAR(20) | ✗ | - |
| `as_of` | TIMESTAMP | ✗ | - |
| `direction` | VARCHAR(10) | ✗ | - |
| `score` | INTEGER | ✗ | - |
| `families` | JSONB | ✗ | - |
| `details` | JSONB | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_confluence_asof` | `as_of` | ✗ |
| `idx_confluence_ticker_asof` | `ticker`, `as_of` | ✗ |

---

## congress_trade_sessions

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('congress_trade_sessions_id_seq'::regclass) |
| `politician_id` | INTEGER | ✓ | - |
| `politician_name` | VARCHAR(255) | ✗ | - |
| `start_date` | DATE | ✗ | - |
| `end_date` | DATE | ✗ | - |
| `trade_count` | INTEGER | ✓ | 0 |
| `total_value_estimate` | VARCHAR(100) | ✓ | - |
| `conflict_score` | NUMERIC(3, 2) | ✓ | - |
| `confidence_score` | NUMERIC(3, 2) | ✓ | - |
| `ai_summary` | TEXT | ✓ | - |
| `last_analyzed_at` | TIMESTAMP | ✓ | - |
| `needs_reanalysis` | BOOLEAN | ✓ | true |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |
| `model_used` | VARCHAR(100) | ✓ | - |
| `analysis_version` | INTEGER | ✓ | 1 |
| `risk_pattern` | VARCHAR(20) | ✓ | - |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_congress_trade_sessions_dates` | `start_date`, `end_date` | ✗ |
| `idx_congress_trade_sessions_needs_reanalysis` | `needs_reanalysis` | ✗ |
| `idx_congress_trade_sessions_politician` | `politician_name` | ✗ |
| `idx_congress_trade_sessions_risk_pattern` | `risk_pattern` | ✗ |
| `idx_congress_trade_sessions_score` | `conflict_score` | ✗ |
| `unique_politician_date_range` | `politician_name`, `start_date`, `end_date` | ✓ |

---

## congress_trades_analysis

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('congress_trades_analysis_id_seq'::regclass) |
| `trade_id` | INTEGER | ✗ | - |
| `conflict_score` | NUMERIC(3, 2) | ✓ | - |
| `reasoning` | TEXT | ✓ | - |
| `model_used` | VARCHAR(100) | ✗ | 'granite3.3:8b'::character varying |
| `analyzed_at` | TIMESTAMP | ✓ | now() |
| `analysis_version` | INTEGER | ✓ | 1 |
| `confidence_score` | NUMERIC(3, 2) | ✓ | - |
| `session_id` | INTEGER | ✓ | - |
| `risk_pattern` | VARCHAR(20) | ✓ | - |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `session_id` | `congress_trade_sessions`.`id` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `congress_trades_analysis_unique_trade_model_version` | `trade_id`, `model_used`, `analysis_version` | ✓ |
| `idx_congress_trades_analysis_analyzed_at` | `analyzed_at` | ✗ |
| `idx_congress_trades_analysis_confidence` | `confidence_score` | ✗ |
| `idx_congress_trades_analysis_risk_pattern` | `risk_pattern` | ✗ |
| `idx_congress_trades_analysis_score` | `conflict_score` | ✗ |
| `idx_congress_trades_analysis_session` | `session_id` | ✗ |
| `idx_congress_trades_analysis_trade_id` | `trade_id` | ✗ |

---

## dilution_observations

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `ticker` | VARCHAR(20) | ✗ | - |
| `as_of` | DATE | ✗ | - |
| `window_days` | INTEGER | ✗ | - |
| `shares_start` | NUMERIC(20, 2) | ✓ | - |
| `shares_end` | NUMERIC(20, 2) | ✓ | - |
| `pct_change` | NUMERIC(10, 2) | ✓ | - |
| `flagged` | BOOLEAN | ✗ | true |
| `created_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `dilution_observations_ticker_as_of_window_days_key` | `ticker`, `as_of`, `window_days` | ✓ |
| `idx_dilution_obs_asof` | `as_of` | ✗ |
| `idx_dilution_obs_ticker_asof` | `ticker`, `as_of` | ✗ |

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
| `idx_ehl_holding_date` | `holding_ticker`, `date` | ✗ |
| `idx_etf_holdings_date` | `date` | ✗ |
| `idx_etf_holdings_etf` | `etf_ticker`, `date` | ✗ |
| `idx_etf_holdings_ticker` | `holding_ticker` | ✗ |

---

## extracted_tickers

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('extracted_tickers_id_seq'::regclass) |
| `analysis_id` | INTEGER | ✓ | - |
| `ticker` | VARCHAR(20) | ✗ | - |
| `confidence` | NUMERIC(3, 2) | ✓ | - |
| `context` | TEXT | ✓ | - |
| `is_primary` | BOOLEAN | ✓ | false |
| `company_name` | VARCHAR(200) | ✓ | - |
| `sector` | VARCHAR(100) | ✓ | - |
| `extracted_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `analysis_id` | `social_sentiment_analysis`.`id` | NO ACTION | NO ACTION |

---

## filing_events

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `ticker` | VARCHAR(20) | ✗ | - |
| `cik` | VARCHAR(20) | ✓ | - |
| `form_type` | VARCHAR(40) | ✗ | - |
| `category` | VARCHAR(20) | ✗ | - |
| `direction` | VARCHAR(10) | ✗ | - |
| `filed_at` | DATE | ✓ | - |
| `accession_no` | VARCHAR(30) | ✗ | - |
| `title` | TEXT | ✓ | - |
| `url` | TEXT | ✓ | - |
| `raw` | JSONB | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `filing_events_accession_no_key` | `accession_no` | ✓ |
| `idx_filing_events_filed` | `filed_at` | ✗ |
| `idx_filing_events_ticker_filed` | `ticker`, `filed_at` | ✗ |

---

## idea_triage

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `article_id` | UUID | ✗ | - |
| `status` | VARCHAR(20) | ✗ | - |
| `decided_at` | TIMESTAMP | ✓ | now() |
| `decided_by` | VARCHAR(100) | ✓ | - |
| `notes` | TEXT | ✓ | - |
| `snooze_until` | TIMESTAMP | ✓ | - |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idea_triage_article_unique` | `article_id` | ✓ |
| `idx_idea_triage_status` | `status`, `decided_at` | ✗ |

---

## market_daily_brief

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `brief_date` | DATE | ✗ | - |
| `headline` | VARCHAR(200) | ✓ | - |
| `narrative` | TEXT | ✓ | - |
| `regime_json` | JSONB | ✓ | - |
| `inputs_digest` | JSONB | ✓ | - |
| `model_used` | VARCHAR(100) | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `brief_date`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_market_daily_brief_updated` | `updated_at` | ✗ |

---

## market_relationships

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('market_relationships_id_seq'::regclass) |
| `source_ticker` | VARCHAR(20) | ✗ | - |
| `target_ticker` | VARCHAR(20) | ✗ | - |
| `relationship_type` | VARCHAR(50) | ✗ | - |
| `confidence_score` | DOUBLE PRECISION | ✓ | 0.0 |
| `detected_at` | TIMESTAMP | ✓ | now() |
| `source_article_id` | UUID | ✓ | - |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `source_article_id` | `research_articles`.`id` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_relationships_article` | `source_article_id` | ✗ |
| `idx_relationships_confidence` | `confidence_score` | ✗ |
| `idx_relationships_source` | `source_ticker` | ✗ |
| `idx_relationships_source_confidence` | `source_ticker`, `confidence_score` | ✗ |
| `idx_relationships_target` | `target_ticker` | ✗ |
| `idx_relationships_type` | `relationship_type` | ✗ |
| `unique_relationship` | `source_ticker`, `target_ticker`, `relationship_type` | ✓ |

---

## newsletters

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `sender` | VARCHAR(500) | ✗ | - |
| `sender_name` | VARCHAR(500) | ✓ | - |
| `recipient` | VARCHAR(500) | ✗ | - |
| `subject` | TEXT | ✗ | - |
| `body_plain` | TEXT | ✓ | - |
| `body_html` | TEXT | ✓ | - |
| `tickers` | ARRAY | ✓ | - |
| `summary` | TEXT | ✓ | - |
| `embedding` | NULL | ✓ | - |
| `received_at` | TIMESTAMP | ✓ | CURRENT_TIMESTAMP |
| `processed_at` | TIMESTAMP | ✓ | - |
| `message_id` | VARCHAR(500) | ✓ | - |
| `article_url` | TEXT | ✓ | - |
| `ticker_sentiment` | JSONB | ✓ | - |
| `sentiment` | VARCHAR(20) | ✓ | - |
| `sentiment_score` | DOUBLE PRECISION | ✓ | - |
| `claims` | JSONB | ✓ | - |
| `fact_check` | TEXT | ✓ | - |
| `conclusion` | TEXT | ✓ | - |
| `logic_check` | VARCHAR(20) | ✓ | - |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_newsletters_embedding` | `embedding` | ✗ |
| `idx_newsletters_received_at` | `received_at` | ✗ |
| `idx_newsletters_sender` | `sender` | ✗ |
| `idx_newsletters_tickers` | `tickers` | ✗ |
| `newsletters_message_id_unique` | `message_id` | ✓ |

---

## post_summaries

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('post_summaries_id_seq'::regclass) |
| `post_id` | INTEGER | ✗ | - |
| `summary` | TEXT | ✗ | - |
| `key_points` | ARRAY | ✓ | - |
| `sentiment_impact` | NUMERIC(3, 2) | ✓ | - |
| `summarized_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

---

## research_articles

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `ticker` | VARCHAR(20) | ✓ | - |
| `sector` | VARCHAR(100) | ✓ | - |
| `article_type` | VARCHAR(50) | ✓ | - |
| `title` | TEXT | ✗ | - |
| `url` | TEXT | ✓ | - |
| `summary` | TEXT | ✓ | - |
| `content` | TEXT | ✓ | - |
| `source` | VARCHAR(100) | ✓ | - |
| `published_at` | TIMESTAMP | ✓ | - |
| `fetched_at` | TIMESTAMP | ✓ | now() |
| `relevance_score` | NUMERIC(3, 2) | ✓ | - |
| `embedding` | NULL | ✓ | - |
| `tickers` | ARRAY | ✓ | - |
| `fund` | VARCHAR(100) | ✓ | - |
| `claims` | JSONB | ✓ | - |
| `fact_check` | TEXT | ✓ | - |
| `conclusion` | TEXT | ✓ | - |
| `sentiment` | VARCHAR(20) | ✓ | - |
| `sentiment_score` | DOUBLE PRECISION | ✓ | - |
| `logic_check` | VARCHAR(20) | ✓ | - |
| `archive_submitted_at` | TIMESTAMP | ✓ | - |
| `archive_checked_at` | TIMESTAMP | ✓ | - |
| `archive_url` | TEXT | ✓ | - |
| `ticker_sentiment` | JSONB | ✓ | - |
| `ticker_validated_at` | TIMESTAMP | ✓ | - |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_research_articles_archive_submitted` | `archive_submitted_at` | ✗ |
| `idx_research_articles_archive_url` | `archive_url` | ✗ |
| `idx_research_articles_embedding` | `embedding` | ✗ |
| `idx_research_articles_unvalidated` | `fetched_at` | ✗ |
| `idx_research_claims` | `claims` | ✗ |
| `idx_research_fetched` | `fetched_at` | ✗ |
| `idx_research_fund` | `fund` | ✗ |
| `idx_research_logic_check` | `logic_check` | ✗ |
| `idx_research_sentiment` | `sentiment` | ✗ |
| `idx_research_sentiment_score` | `sentiment_score` | ✗ |
| `idx_research_ticker` | `ticker` | ✗ |
| `idx_research_tickers_gin` | `tickers` | ✗ |
| `idx_research_type` | `article_type` | ✗ |
| `research_articles_url_key` | `url` | ✓ |

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

## sector_meta_analysis

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `sector` | VARCHAR(120) | ✗ | - |
| `run_date` | DATE | ✗ | - |
| `sector_stance` | VARCHAR(40) | ✗ | - |
| `momentum_state` | VARCHAR(40) | ✗ | - |
| `news_pressure` | VARCHAR(40) | ✗ | - |
| `rotation_rank` | INTEGER | ✗ | 0 |
| `confidence` | NUMERIC(5, 4) | ✗ | - |
| `key_drivers` | JSONB | ✗ | '[]'::jsonb |
| `risk_flags` | JSONB | ✗ | '[]'::jsonb |
| `as_of` | TIMESTAMP | ✗ | - |
| `full_result` | JSONB | ✓ | - |
| `model_used` | VARCHAR(100) | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_sector_meta_analysis_run_date` | `run_date` | ✗ |
| `idx_sector_meta_analysis_sector` | `sector` | ✗ |
| `idx_sector_meta_analysis_updated` | `updated_at` | ✗ |
| `sector_meta_analysis_sector_run_date_key` | `sector`, `run_date` | ✓ |

---

## securities

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `ticker` | VARCHAR(20) | ✗ | - |
| `name` | TEXT | ✓ | - |
| `sector` | TEXT | ✓ | - |
| `industry` | TEXT | ✓ | - |
| `asset_class` | VARCHAR(50) | ✓ | - |
| `exchange` | VARCHAR(50) | ✓ | - |
| `currency` | VARCHAR(10) | ✓ | 'USD'::character varying |
| `description` | TEXT | ✓ | - |
| `last_updated` | TIMESTAMP | ✓ | now() |
| `first_detected_by` | VARCHAR(50) | ✓ | - |

### Primary Key

- `ticker`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_securities_industry` | `industry` | ✗ |
| `idx_securities_name` | `None` | ✗ |
| `idx_securities_sector` | `sector` | ✗ |

---

## sentiment_sessions

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('sentiment_sessions_id_seq'::regclass) |
| `ticker` | VARCHAR(20) | ✗ | - |
| `platform` | VARCHAR(20) | ✗ | - |
| `session_start` | TIMESTAMP | ✗ | - |
| `session_end` | TIMESTAMP | ✗ | - |
| `post_count` | INTEGER | ✓ | 0 |
| `total_engagement` | INTEGER | ✓ | 0 |
| `needs_ai_analysis` | BOOLEAN | ✓ | true |
| `created_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

---

## social_metrics

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('social_metrics_id_seq'::regclass) |
| `ticker` | VARCHAR(20) | ✗ | - |
| `platform` | VARCHAR(20) | ✗ | - |
| `volume` | INTEGER | ✓ | 0 |
| `bull_bear_ratio` | DOUBLE PRECISION | ✓ | 0.0 |
| `sentiment_label` | VARCHAR(20) | ✓ | - |
| `sentiment_score` | DOUBLE PRECISION | ✓ | - |
| `raw_data` | JSONB | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `basic_sentiment_score` | NUMERIC(3, 2) | ✓ | - |
| `has_ai_analysis` | BOOLEAN | ✓ | false |
| `analysis_session_id` | INTEGER | ✓ | - |
| `raw_posts` | ARRAY | ✓ | - |
| `post_count` | INTEGER | ✓ | 0 |
| `engagement_score` | DOUBLE PRECISION | ✓ | 0.0 |
| `data_quality_score` | DOUBLE PRECISION | ✓ | 0.0 |
| `collection_metadata` | JSONB | ✓ | - |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_social_created_at` | `created_at` | ✗ |
| `idx_social_platform` | `platform` | ✗ |
| `idx_social_ticker_platform` | `ticker`, `platform` | ✗ |
| `idx_social_ticker_time` | `ticker`, `created_at` | ✗ |

---

## social_posts

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('social_posts_id_seq'::regclass) |
| `metric_id` | INTEGER | ✓ | - |
| `platform` | VARCHAR(20) | ✗ | - |
| `post_id` | VARCHAR(100) | ✓ | - |
| `content` | TEXT | ✗ | - |
| `author` | VARCHAR(100) | ✓ | - |
| `posted_at` | TIMESTAMP | ✓ | - |
| `engagement_score` | INTEGER | ✓ | 0 |
| `url` | TEXT | ✓ | - |
| `extracted_tickers` | ARRAY | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `metric_id` | `social_metrics`.`id` | NO ACTION | NO ACTION |

---

## social_sentiment_analysis

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | INTEGER | ✗ | nextval('social_sentiment_analysis_id_seq'::regclass) |
| `session_id` | INTEGER | ✗ | - |
| `ticker` | VARCHAR(20) | ✗ | - |
| `platform` | VARCHAR(20) | ✗ | - |
| `sentiment_score` | NUMERIC(3, 2) | ✓ | - |
| `confidence_score` | NUMERIC(3, 2) | ✓ | - |
| `sentiment_label` | VARCHAR(20) | ✓ | - |
| `summary` | TEXT | ✓ | - |
| `key_themes` | ARRAY | ✓ | - |
| `reasoning` | TEXT | ✓ | - |
| `model_used` | VARCHAR(100) | ✓ | 'granite3.1:8b'::character varying |
| `analysis_version` | INTEGER | ✓ | 1 |
| `analyzed_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

---

## stance_history

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `ticker` | VARCHAR(20) | ✗ | - |
| `fund_key` | TEXT | ✗ | ''::text |
| `source` | VARCHAR(40) | ✗ | - |
| `stance` | VARCHAR(40) | ✓ | - |
| `confidence` | NUMERIC(5, 4) | ✓ | - |
| `as_of` | TIMESTAMP | ✗ | now() |
| `price_at_stance` | NUMERIC(14, 4) | ✓ | - |
| `drivers` | ARRAY | ✓ | - |
| `risks` | ARRAY | ✓ | - |
| `model_used` | VARCHAR(100) | ✓ | - |
| `requested_by` | VARCHAR(100) | ✓ | - |
| `source_ref_id` | UUID | ✓ | - |
| `metadata` | JSONB | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_stance_history_as_of` | `as_of` | ✗ |
| `idx_stance_history_ticker_source_asof` | `ticker`, `source`, `fund_key`, `as_of` | ✗ |

---

## stance_outcomes

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `stance_id` | UUID | ✗ | - |
| `horizon_days` | SMALLINT | ✗ | - |
| `baseline_price` | NUMERIC(14, 4) | ✓ | - |
| `end_price` | NUMERIC(14, 4) | ✓ | - |
| `ticker_return` | NUMERIC(10, 6) | ✓ | - |
| `benchmark_return` | NUMERIC(10, 6) | ✓ | - |
| `excess_return` | NUMERIC(10, 6) | ✓ | - |
| `scored_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `stance_id` | `stance_history`.`id` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_stance_outcomes_stance` | `stance_id` | ✗ |
| `stance_outcomes_unique` | `stance_id`, `horizon_days` | ✓ |

---

## thesis_entries

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `thesis_id` | UUID | ✗ | - |
| `entry_kind` | VARCHAR(30) | ✗ | - |
| `author_kind` | VARCHAR(20) | ✗ | - |
| `author_id` | VARCHAR(100) | ✓ | - |
| `body` | TEXT | ✗ | - |
| `created_at` | TIMESTAMP | ✗ | now() |
| `metadata` | JSONB | ✗ | '{}'::jsonb |
| `embedding` | NULL | ✓ | - |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `thesis_id` | `ticker_theses`.`id` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_thesis_entries_thread` | `thesis_id`, `created_at` | ✗ |

---

## thesis_evidence

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `thesis_id` | UUID | ✗ | - |
| `entry_id` | UUID | ✓ | - |
| `evidence_kind` | VARCHAR(40) | ✗ | - |
| `ref_id` | UUID | ✓ | - |
| `url` | TEXT | ✓ | - |
| `title` | TEXT | ✓ | - |
| `snippet` | TEXT | ✓ | - |
| `relation` | VARCHAR(20) | ✗ | 'context'::character varying |
| `created_by` | VARCHAR(100) | ✗ | - |
| `created_at` | TIMESTAMP | ✗ | now() |

### Primary Key

- `id`

### Foreign Keys

| Column | References | On Delete | On Update |
|--------|------------|-----------|------------|
| `entry_id` | `thesis_entries`.`id` | NO ACTION | NO ACTION |
| `thesis_id` | `ticker_theses`.`id` | NO ACTION | NO ACTION |

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_thesis_evidence_article` | `ref_id` | ✗ |
| `idx_thesis_evidence_thesis` | `thesis_id` | ✗ |

---

## ticker_analysis

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `ticker` | VARCHAR(10) | ✗ | - |
| `analysis_type` | VARCHAR(20) | ✗ | 'standard'::character varying |
| `analysis_date` | DATE | ✗ | - |
| `data_start_date` | DATE | ✗ | - |
| `data_end_date` | DATE | ✗ | - |
| `sentiment` | VARCHAR(40) | ✓ | - |
| `sentiment_score` | NUMERIC(5, 4) | ✓ | - |
| `confidence_score` | NUMERIC(5, 4) | ✓ | - |
| `themes` | ARRAY | ✓ | - |
| `summary` | TEXT | ✓ | - |
| `analysis_text` | TEXT | ✓ | - |
| `reasoning` | TEXT | ✓ | - |
| `input_context` | TEXT | ✓ | - |
| `etf_changes_count` | INTEGER | ✓ | 0 |
| `congress_trades_count` | INTEGER | ✓ | 0 |
| `research_articles_count` | INTEGER | ✓ | 0 |
| `embedding` | NULL | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |
| `model_used` | VARCHAR(50) | ✓ | 'granite3.3:8b'::character varying |
| `analysis_version` | INTEGER | ✓ | 1 |
| `requested_by` | VARCHAR(100) | ✓ | - |
| `stance` | VARCHAR(20) | ✓ | - |
| `timeframe` | VARCHAR(60) | ✓ | - |
| `entry_zone` | VARCHAR(100) | ✓ | - |
| `target_price` | VARCHAR(60) | ✓ | - |
| `stop_loss` | VARCHAR(60) | ✓ | - |
| `key_levels` | JSONB | ✓ | - |
| `catalysts` | ARRAY | ✓ | - |
| `risks` | ARRAY | ✓ | - |
| `invalidation` | TEXT | ✓ | - |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_ticker_analysis_date` | `analysis_date` | ✗ |
| `idx_ticker_analysis_embedding` | `embedding` | ✗ |
| `idx_ticker_analysis_stance` | `stance` | ✗ |
| `idx_ticker_analysis_ticker` | `ticker` | ✗ |
| `idx_ticker_analysis_updated` | `updated_at` | ✗ |
| `unique_ticker_analysis` | `ticker`, `analysis_type`, `analysis_date` | ✓ |

---

## ticker_meta_analysis

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `ticker` | VARCHAR(10) | ✗ | - |
| `source_analysis_id` | UUID | ✓ | - |
| `source_analysis_snapshot_at` | TIMESTAMP | ✓ | - |
| `unified_conviction` | VARCHAR(40) | ✓ | - |
| `confidence_adjusted` | NUMERIC(4, 3) | ✓ | - |
| `contradictions` | JSONB | ✓ | - |
| `what_changed_vs_last_run` | TEXT | ✓ | - |
| `action_items` | ARRAY | ✓ | - |
| `narrative` | TEXT | ✓ | - |
| `full_result` | JSONB | ✓ | - |
| `model_used` | VARCHAR(100) | ✓ | - |
| `requested_by` | VARCHAR(100) | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |
| `artifact_bundle_digest` | VARCHAR(64) | ✓ | - |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_ticker_meta_analysis_ticker` | `ticker` | ✗ |
| `idx_ticker_meta_analysis_updated` | `updated_at` | ✗ |
| `idx_ticker_meta_source` | `source_analysis_id` | ✗ |
| `ticker_meta_analysis_ticker_key` | `ticker` | ✓ |

---

## ticker_theses

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `ticker` | VARCHAR(20) | ✗ | - |
| `title` | TEXT | ✗ | - |
| `disposition` | VARCHAR(20) | ✗ | - |
| `intent` | VARCHAR(20) | ✗ | - |
| `status` | VARCHAR(20) | ✗ | 'active'::character varying |
| `created_by` | VARCHAR(100) | ✗ | - |
| `created_at` | TIMESTAMP | ✗ | now() |
| `updated_at` | TIMESTAMP | ✗ | now() |
| `last_reviewed_at` | TIMESTAMP | ✓ | - |
| `archived_at` | TIMESTAMP | ✓ | - |
| `archived_by` | VARCHAR(100) | ✓ | - |
| `embedding` | NULL | ✓ | - |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_theses_disposition` | `disposition` | ✗ |
| `idx_theses_intent` | `intent` | ✗ |
| `idx_theses_ticker_active` | `ticker` | ✗ |
| `idx_theses_updated` | `updated_at` | ✗ |

---

## ui_ai_rollup_fund

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `fund` | VARCHAR(200) | ✗ | - |
| `headline` | VARCHAR(300) | ✓ | - |
| `narrative` | TEXT | ✓ | - |
| `sources_used` | JSONB | ✓ | - |
| `inputs_digest` | VARCHAR(64) | ✗ | - |
| `model_used` | VARCHAR(100) | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `fund`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_ui_ai_rollup_fund_updated` | `updated_at` | ✗ |

---

## ui_ai_summary

### Columns

| Column | Type | Nullable | Default |
|--------|------|----------|----------|
| `id` | UUID | ✗ | gen_random_uuid() |
| `scope` | VARCHAR(80) | ✗ | - |
| `scope_key` | VARCHAR(256) | ✗ | - |
| `content_class` | VARCHAR(20) | ✗ | 'price_linked'::character varying |
| `summary_json` | JSONB | ✗ | '{}'::jsonb |
| `inputs_digest` | VARCHAR(64) | ✗ | - |
| `model_used` | VARCHAR(100) | ✓ | - |
| `created_at` | TIMESTAMP | ✓ | now() |
| `updated_at` | TIMESTAMP | ✓ | now() |

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_ui_ai_summary_content_class` | `content_class`, `updated_at` | ✗ |
| `idx_ui_ai_summary_scope_updated` | `scope`, `updated_at` | ✗ |
| `ui_ai_summary_scope_key_unique` | `scope`, `scope_key` | ✓ |

---

