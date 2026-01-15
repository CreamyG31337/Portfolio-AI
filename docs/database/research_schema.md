# Research Database Database Schema

**Generated:** 2026-01-15 02:41:49

**Total Tables:** 13

---

## Table of Contents

- [congress_trade_sessions](#congress-trade-sessions)
- [congress_trades_analysis](#congress-trades-analysis)
- [etf_holdings_log](#etf-holdings-log)
- [extracted_tickers](#extracted-tickers)
- [market_relationships](#market-relationships)
- [post_summaries](#post-summaries)
- [research_articles](#research-articles)
- [rss_feeds](#rss-feeds)
- [securities](#securities)
- [sentiment_sessions](#sentiment-sessions)
- [social_metrics](#social-metrics)
- [social_posts](#social-posts)
- [social_sentiment_analysis](#social-sentiment-analysis)

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

### Primary Key

- `id`

### Indexes

| Name | Columns | Unique |
|------|---------|--------|
| `idx_research_articles_archive_submitted` | `archive_submitted_at` | ✗ |
| `idx_research_articles_archive_url` | `archive_url` | ✗ |
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

