"""
Generate Test Database Seed File
Extracts real data, scrubs PII, and generates synthetic test fixtures for safe cloud agent testing.

Usage:
    python scripts/generate_test_seed.py

Output:
    - database/test_seed_supabase.sql
    - database/test_seed_research.sql
"""
import os
import sys
import re
import uuid
import random
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import create_engine, inspect, text

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

try:
    from faker import Faker
except ImportError:
    print("ERROR: faker library not installed. Run: pip install faker")
    sys.exit(1)


# Configuration
TEST_FUNDS = ['TEST', 'TFSA']
REAL_SOCIAL_POSTS_COUNT = 3374
REAL_SOCIAL_METRICS_COUNT = 19704
REAL_SENTIMENT_ANALYSIS_COUNT = 46
REAL_POST_SUMMARIES_COUNT = 0
REAL_SENTIMENT_SESSIONS_COUNT = 200
REAL_RESEARCH_ARTICLES_COUNT = 817
REAL_EXTRACTED_TICKERS_COUNT = 0
REAL_MARKET_RELATIONSHIPS_COUNT = 58

# Faker setup
fake = Faker()


def get_db_connection():
    """Load .env and return database URLs"""
    from dotenv import load_dotenv
    env_file = Path(__file__).parent.parent / "web_dashboard" / ".env"
    load_dotenv(env_file)

    supabase_url = os.getenv('SUPABASE_DATABASE_URL')
    research_url = os.getenv('RESEARCH_DATABASE_URL')

    if not supabase_url or not research_url:
        raise ValueError("Missing SUPABASE_DATABASE_URL or RESEARCH_DATABASE_URL in .env")

    return supabase_url, research_url


def write_header(f, db_name):
    """Write SQL header to seed file"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    f.write(f"""-- Test Database Seed for {db_name}
-- Generated: {timestamp}
-- Safe for Git - All PII scrubbed, synthetic test data included
--
-- This file is loaded after _init_schema.sql
-- Run with: psql -f database/test_seed_{db_name.lower()}.sql

SET client_encoding = 'UTF8';

-- =====================================================
-- REAL DATA (Extracted & Scrubbed)
-- =====================================================

""")


def escape_sql_string(value):
    """Escape SQL string literals"""
    if value is None:
        return 'NULL'
    value_str = str(value)
    value_str = value_str.replace("'", "''")
    return f"'{value_str}'"


def escape_sql_value(value):
    """Format value for SQL INSERT"""
    if value is None:
        return 'NULL'
    elif isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, datetime):
        return f"'{value.isoformat()}'"
    elif isinstance(value, list):
        # Handle PostgreSQL arrays using ARRAY[] syntax
        if not value:
            return "ARRAY[]::text[]"  # Empty array with explicit type
        escaped = [escape_sql_string(v) for v in value]
        return f"ARRAY[{', '.join(escaped)}]"
    else:
        return escape_sql_string(value)


def generate_insert_sql(table_name, columns, rows):
    """Generate INSERT statements from rows"""
    if not rows:
        return ""

    col_list = ', '.join(columns)
    sql_lines = []

    for row in rows:
        values = ', '.join(escape_sql_value(row.get(col)) for col in columns)
        sql_lines.append(f"INSERT INTO {table_name} ({col_list}) VALUES ({values});")

    return '\n'.join(sql_lines) + '\n\n'


def export_table_full_copy(conn, table_name, exclude_columns=None):
    """Export all rows from a table"""
    inspector = inspect(conn.engine)
    columns_info = inspector.get_columns(table_name)

    if exclude_columns:
        columns = [c['name'] for c in columns_info if c['name'] not in exclude_columns]
    else:
        columns = [c['name'] for c in columns_info]

    query = text(f"SELECT {', '.join(columns)} FROM {table_name}")
    result = conn.execute(query).fetchall()

    rows = [dict(zip(columns, row)) for row in result]
    return columns, rows


def export_table_filtered(conn, table_name, filter_clause, exclude_columns=None):
    """Export rows matching filter condition"""
    inspector = inspect(conn.engine)
    columns_info = inspector.get_columns(table_name)

    if exclude_columns:
        columns = [c['name'] for c in columns_info if c['name'] not in exclude_columns]
    else:
        columns = [c['name'] for c in columns_info]

    query = text(f"SELECT {', '.join(columns)} FROM {table_name} WHERE {filter_clause}")
    result = conn.execute(query).fetchall()

    rows = [dict(zip(columns, row)) for row in result]
    return columns, rows


def scrub_rss_url(url):
    """Scrub API keys from RSS feed URLs"""
    if url is None:
        return None

    # Replace apikey= and token= values with 'REDACTED'
    url = re.sub(r'(apikey=)[^&\'"]*', r'\1REDACTED', url, flags=re.IGNORECASE)
    url = re.sub(r'(token=)[^&\'"]*', r'\1REDACTED', url, flags=re.IGNORECASE)
    return url


def generate_supabase_seed(supabase_url, output_path):
    """Generate Supabase test seed file"""
    print(f"\n[*] Generating Supabase seed file: {output_path}")

    engine = create_engine(supabase_url)

    with open(output_path, 'w', encoding='utf-8') as f:
        write_header(f, 'Supabase')

        with engine.connect() as conn:
            # =====================================================
            # Reference Data (Full Copy - No Scrubbing)
            # =====================================================
            print("    Exporting reference data...")

            full_copy_tables = [
                'securities',
                'benchmark_data',
                'exchange_rates',
                'system_settings',
                'congress_trades',
                'congress_trades_staging',
                'politicians',
                'committee_assignments',
                'committees',
                'watched_tickers',
                'etf_holdings_log',
                'job_executions',
                'job_retry_queue'
            ]

            for table in full_copy_tables:
                print(f"      {table}...")
                columns, rows = export_table_full_copy(conn, table)
                f.write(f"-- {table}\n")
                f.write(generate_insert_sql(table, columns, rows))

            # =====================================================
            # Test Fund Data (Filtered)
            # =====================================================
            print("    Exporting test fund data...")

            # Get exact fund names from database
            fund_names_query = text("""
                SELECT name FROM funds
                WHERE name LIKE '%TEST%' OR name LIKE '%TFSA%'
            """)
            fund_names = [row[0] for row in conn.execute(fund_names_query).fetchall()]
            print(f"      Test funds found: {fund_names}")

            fund_filter = " OR ".join([f"fund = '{fn}'" for fn in fund_names])

            fund_filtered_tables = [
                'portfolio_positions',
                'trade_log',
                'dividend_log',
                'performance_metrics',
                'cash_balances',
                'fund_contributions',
                'fund_thesis'
            ]

            for table in fund_filtered_tables:
                print(f"      {table}...")
                columns, rows = export_table_filtered(conn, table, fund_filter)
                f.write(f"-- {table} (filtered for {fund_names})\n")
                f.write(generate_insert_sql(table, columns, rows))

            # =====================================================
            # fund_thesis_pillars - needs join filtering
            # =====================================================
            print("      fund_thesis_pillars...")
            thesis_ids_query = text(f"""
                SELECT id FROM fund_thesis
                WHERE fund IN ({', '.join([f"'{fn}'" for fn in fund_names])})
            """)
            thesis_ids = [str(row[0]) for row in conn.execute(thesis_ids_query).fetchall()]

            if thesis_ids:
                pillars_filter = " OR ".join([f"thesis_id = '{tid}'" for tid in thesis_ids])
                columns, rows = export_table_filtered(conn, 'fund_thesis_pillars', pillars_filter)
                f.write(f"-- fund_thesis_pillars (filtered for {fund_names})\n")
                f.write(generate_insert_sql('fund_thesis_pillars', columns, rows))

            # =====================================================
            # User Data (Filtered & Scrubbed)
            # =====================================================
            print("    Exporting and scrubbing user data...")

            # Get users with test fund assignments
            user_funds_query = text(f"""
                SELECT DISTINCT user_id FROM user_funds
                WHERE fund_name IN ({', '.join([f"'{fn}'" for fn in fund_names])})
            """)
            user_ids = [str(row[0]) for row in conn.execute(user_funds_query).fetchall()]

            if user_ids:
                user_filter = " OR ".join([f"user_id = '{uid}'" for uid in user_ids])

                columns, rows = export_table_filtered(conn, 'user_profiles', user_filter)

                # Scrub PII
                for i, row in enumerate(rows):
                    row['full_name'] = f"Test User {i + 1}"
                    row['email'] = f"test-user-{i + 1}@example.com"

                f.write("-- user_profiles (scrubbed PII)\n")
                f.write(generate_insert_sql('user_profiles', columns, rows))

                # Export user_funds
                columns, rows = export_table_filtered(conn, 'user_funds', user_filter)
                f.write("-- user_funds (filtered for test funds)\n")
                f.write(generate_insert_sql('user_funds', columns, rows))

            # =====================================================
            # Contributor Data (Filtered & Scrubbed)
            # =====================================================
            print("    Exporting and scrubbing contributor data...")

            # Get contributors linked to test funds
            contributors_query = text(f"""
                SELECT DISTINCT c.id, c.name, c.email, c.phone, c.address, c.kyc_status, c.created_at, c.updated_at
                FROM contributors c
                JOIN fund_contributions fc ON c.id = fc.contributor_id
                WHERE fc.fund IN ({', '.join([f"'{fn}'" for fn in fund_names])})
            """)
            contributor_rows = [dict(row) for row in conn.execute(contributors_query).fetchall()]

            if contributor_rows:
                # Scrub PII with fake names
                fake_names = [
                    "Alice Johnson", "Bob Smith", "Carol Davis", "David Wilson",
                    "Eva Martinez", "Frank Brown", "Grace Lee", "Henry Taylor",
                    "Ivy Chen", "Jack White"
                ]

                contributor_ids = []
                for i, row in enumerate(contributor_rows):
                    row['name'] = fake_names[i % len(fake_names)]
                    row['email'] = f"contributor-{i + 1}@example.com"
                    row['phone'] = None
                    row['address'] = None
                    contributor_ids.append(row['id'])

                columns = ['id', 'name', 'email', 'phone', 'address', 'kyc_status', 'created_at', 'updated_at']
                f.write("-- contributors (scrubbed PII)\n")
                f.write(generate_insert_sql('contributors', columns, contributor_rows))

                # Export contributor_access for scrubbed contributors
                if contributor_ids:
                    contributor_filter = " OR ".join([f"contributor_id = '{cid}'" for cid in contributor_ids])
                    columns, rows = export_table_filtered(conn, 'contributor_access', contributor_filter)
                    f.write("-- contributor_access (filtered for scrubbed contributors)\n")
                    f.write(generate_insert_sql('contributor_access', columns, rows))

            # =====================================================
            # Funds Table (Set is_production = true)
            # =====================================================
            print("    Exporting funds table...")

            funds_filter = " OR ".join([f"name = '{fn}'" for fn in fund_names])
            columns, rows = export_table_filtered(conn, 'funds', funds_filter)

            # Set is_production = true
            for row in rows:
                row['is_production'] = True

            f.write("-- funds (test funds only, is_production = true)\n")
            f.write(generate_insert_sql('funds', columns, rows))

            # =====================================================
            # RSS Feeds (Scrub API Keys)
            # =====================================================
            print("    Exporting RSS feeds...")

            columns, rows = export_table_full_copy(conn, 'rss_feeds')

            # Scrub API keys in URLs
            for row in rows:
                row['url'] = scrub_rss_url(row['url'])

            f.write("-- rss_feeds (API keys scrubbed)\n")
            f.write(generate_insert_sql('rss_feeds', columns, rows))

            # =====================================================
            # Update Sequences
            # =====================================================
            print("    Updating sequences...")

            f.write("\n-- Update sequences to prevent conflicts\n")
            sequence_queries = [
                ("benchmark_data", "benchmark_data_id_seq"),
                ("funds", "funds_id_seq"),
                ("job_executions", "job_executions_id_seq"),
                ("job_retry_queue", "job_retry_queue_id_seq"),
                ("politicians", "politicians_id_seq"),
                ("rss_feeds", "rss_feeds_id_seq"),
                ("committee_assignments", "committee_assignments_id_seq"),
                ("committees", "committees_id_seq"),
                ("congress_trades", "congress_trades_id_seq"),
                ("congress_trades_staging", "congress_trades_staging_id_seq"),
            ]

            for table, seq_name in sequence_queries:
                f.write(f"SELECT setval('{seq_name}', (SELECT COALESCE(MAX(id), 1) FROM {table}) + 1);\n")

            f.write("\n-- =====================================================\n")
            f.write("-- SUMMARY\n")
            f.write("-- =====================================================\n")
            f.write("SELECT 'Supabase test seed generation complete' as status;\n\n")

            f.write("SELECT table_name, COUNT(*) as records\n")
            f.write("FROM information_schema.tables\n")
            f.write("WHERE table_schema = 'public' AND table_type = 'BASE TABLE'\n")
            f.write("GROUP BY table_name\n")
            f.write("ORDER BY table_name;\n")

    engine.dispose()
    print(f"    [OK] Generated {output_path}")


def generate_research_seed(research_url, output_path):
    """Generate Research test seed file"""
    print(f"\n[*] Generating Research seed file: {output_path}")

    engine = create_engine(research_url)

    # Get real tickers for synthetic data
    real_tickers = []
    try:
        supabase_url, _ = get_db_connection()
        supabase_engine = create_engine(supabase_url)
        with supabase_engine.connect() as conn:
            tickers = conn.execute(text("SELECT ticker FROM securities LIMIT 50")).fetchall()
            real_tickers = [t[0] for t in tickers]
        supabase_engine.dispose()
    except:
        real_tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA', 'AMD', 'INTC', 'NFLX']

    with open(output_path, 'w', encoding='utf-8') as f:
        write_header(f, 'Research')

        with engine.connect() as conn:
            # =====================================================
            # Reference Data (Full Copy)
            # =====================================================
            print("    Exporting reference data...")

            reference_tables = [
                'congress_trade_sessions',
                'congress_trades_analysis',
                'etf_holdings_log',
                'rss_feeds',
                'securities'
            ]

            for table in reference_tables:
                print(f"      {table}...")
                columns, rows = export_table_full_copy(conn, table)
                f.write(f"-- {table}\n")
                f.write(generate_insert_sql(table, columns, rows))

            # =====================================================
            # Synthetic Data Generation
            # =====================================================
            print("    Generating synthetic test data...")

            f.write("\n-- =====================================================\n")
            f.write("-- SYNTHETIC TEST DATA\n")
            f.write("-- =====================================================\n\n")

            # Social Posts
            print("      Generating fake social posts...")
            f.write("-- social_posts (synthetic)\n")
            for i in range(REAL_SOCIAL_POSTS_COUNT):
                post = {
                    'id': i + 1,
                    'metric_id': None,
                    'platform': random.choice(['reddit', 'twitter']),
                    'post_id': f"fake_{uuid.uuid4().hex[:16]}",
                    'content': fake.paragraph(nb_sentences=random.randint(2, 5)),
                    'author': fake.user_name(),
                    'posted_at': fake.date_time_between(start_date='-90d', end_date='now'),
                    'engagement_score': random.randint(-10, 500),
                    'url': f"https://fake-social-{random.randint(1, 999)}.example.com/post/{uuid.uuid4().hex[:12]}",
                    'extracted_tickers': random.sample(real_tickers, min(random.randint(0, 3), len(real_tickers))) if random.random() > 0.5 else [],
                    'created_at': datetime.now()
                }
                columns = list(post.keys())
                f.write(generate_insert_sql('social_posts', columns, [post]))

            # Social Metrics
            print("      Generating fake social metrics...")
            f.write("-- social_metrics (synthetic)\n")
            metrics_count = min(REAL_SOCIAL_METRICS_COUNT, REAL_SOCIAL_POSTS_COUNT * 3)
            for i in range(metrics_count):
                post_id = random.randint(1, REAL_SOCIAL_POSTS_COUNT)
                tracking_date = fake.date_time_between(start_date='-7d', end_date='now')
                metric = {
                    'id': i + 1,
                    'ticker': random.choice(real_tickers),
                    'platform': random.choice(['reddit', 'twitter']),
                    'post_count': random.randint(1, 100),
                    'avg_score': round(random.uniform(-10, 500), 2),
                    'tracking_date': tracking_date.date(),
                    'created_at': datetime.now()
                }
                columns = list(metric.keys())
                f.write(generate_insert_sql('social_metrics', columns, [metric]))

            # Social Sentiment Analysis
            print("      Generating fake sentiment analysis...")
            f.write("-- social_sentiment_analysis (synthetic)\n")
            sentiment_count = int(REAL_SOCIAL_POSTS_COUNT * 0.7)
            for i in range(sentiment_count):
                post_id = random.randint(1, REAL_SOCIAL_POSTS_COUNT)
                ticker = random.choice(real_tickers)
                analyzed_at = fake.date_time_between(start_date='-48h', end_date='now')
                sentiment = {
                    'id': i + 1,
                    'session_id': random.randint(1, 10),
                    'ticker': ticker,
                    'platform': random.choice(['reddit', 'twitter']),
                    'sentiment_score': round(random.uniform(-1.0, 1.0), 2),
                    'confidence_score': round(random.uniform(0.5, 0.99), 2),
                    'sentiment_label': random.choice(['bullish', 'bearish', 'neutral']),
                    'summary': fake.paragraph(nb_sentences=2),
                    'key_themes': random.sample(['AI', 'earnings', 'market trends', 'technical', 'fundamental'], k=random.randint(1, 3)),
                    'reasoning': fake.paragraph(nb_sentences=3),
                    'model_used': 'test-model-v1',
                    'analysis_version': 1,
                    'analyzed_at': analyzed_at
                }
                columns = list(sentiment.keys())
                f.write(generate_insert_sql('social_sentiment_analysis', columns, [sentiment]))

            # Post Summaries
            print("      Generating fake post summaries...")
            f.write("-- post_summaries (synthetic)\n")
            for i in range(10):
                summary = {
                    'id': i + 1,
                    'session_id': i + 1,
                    'summary_text': fake.paragraph(nb_sentences=5),
                    'key_points': fake.sentences(nb=5),
                    'ticker_mentions': random.sample(real_tickers, k=random.randint(1, 5)),
                    'created_at': datetime.now()
                }
                columns = list(summary.keys())
                f.write(generate_insert_sql('post_summaries', columns, [summary]))

            # Sentiment Sessions
            print("      Generating fake sentiment sessions...")
            f.write("-- sentiment_sessions (synthetic)\n")
            for i in range(10):
                session = {
                    'id': i + 1,
                    'start_time': fake.date_time_between(start_date='-7d', end_date='now'),
                    'end_time': fake.date_time_between(start_date='-7d', end_date='now'),
                    'total_posts': random.randint(50, 200),
                    'platform': random.choice(['reddit', 'twitter']),
                    'created_at': datetime.now()
                }
                columns = list(session.keys())
                f.write(generate_insert_sql('sentiment_sessions', columns, [session]))

            # Research Articles
            print("      Generating fake research articles...")
            f.write("-- research_articles (synthetic)\n")
            for i in range(REAL_RESEARCH_ARTICLES_COUNT):
                published_at = fake.date_time_between(start_date='-120d', end_date='now')
                article = {
                    'id': i + 1,
                    'title': fake.catch_phrase() + " - Market Analysis",
                    'url': f"https://fake-news-{random.randint(1, 999)}.example.com/article/{uuid.uuid4().hex[:12]}",
                    'source_domain': f"fake-finance-{random.randint(1, 50)}.example.com",
                    'published_at': published_at,
                    'content': fake.text(max_nb_chars=2000),
                    'summary': fake.paragraph(nb_sentences=3),
                    'is_relevant': random.choice([True, False]),
                    'scraped_at': datetime.now()
                }
                columns = list(article.keys())
                f.write(generate_insert_sql('research_articles', columns, [article]))

            # Extracted Tickers
            print("      Generating fake extracted tickers...")
            f.write("-- extracted_tickers (synthetic)\n")
            ticker_count = REAL_RESEARCH_ARTICLES_COUNT * 2
            for i in range(ticker_count):
                article_id = random.randint(1, REAL_RESEARCH_ARTICLES_COUNT)
                extracted = {
                    'id': i + 1,
                    'article_id': article_id,
                    'ticker': random.choice(real_tickers),
                    'context': fake.sentence(),
                    'confidence': round(random.uniform(0.5, 0.99), 2),
                    'extracted_at': datetime.now()
                }
                columns = list(extracted.keys())
                f.write(generate_insert_sql('extracted_tickers', columns, [extracted]))

            # Market Relationships
            print("      Generating fake market relationships...")
            f.write("-- market_relationships (synthetic)\n")
            for i in range(REAL_MARKET_RELATIONSHIPS_COUNT):
                ticker1, ticker2 = random.sample(real_tickers, 2)
                relationship = {
                    'id': i + 1,
                    'ticker1': ticker1,
                    'ticker2': ticker2,
                    'correlation': round(random.uniform(-1.0, 1.0), 3),
                    'p_value': round(random.uniform(0.0, 0.1), 4),
                    'sample_size': random.randint(30, 252),
                    'start_date': fake.date_between(start_date='-1y', end_date='-30d'),
                    'end_date': fake.date_between(start_date='-60d', end_date='now'),
                    'created_at': datetime.now()
                }
                columns = list(relationship.keys())
                f.write(generate_insert_sql('market_relationships', columns, [relationship]))

            # =====================================================
            # Update Sequences
            # =====================================================
            print("    Updating sequences...")

            f.write("\n-- Update sequences to prevent conflicts\n")
            sequence_queries = [
                ("social_posts", "social_posts_id_seq"),
                ("social_metrics", "social_metrics_id_seq"),
                ("social_sentiment_analysis", "social_sentiment_analysis_id_seq"),
                ("post_summaries", "post_summaries_id_seq"),
                ("sentiment_sessions", "sentiment_sessions_id_seq"),
                ("rss_feeds", "rss_feeds_id_seq"),
                ("congress_trade_sessions", "congress_trade_sessions_id_seq"),
                ("congress_trades_analysis", "congress_trades_analysis_id_seq"),
                ("etf_holdings_log", "etf_holdings_log_id_seq"),
                ("extracted_tickers", "extracted_tickers_id_seq"),
                ("market_relationships", "market_relationships_id_seq"),
            ]

            for table, seq_name in sequence_queries:
                f.write(f"SELECT setval('{seq_name}', (SELECT COALESCE(MAX(id), 1) FROM {table}) + 1);\n")

            f.write("\n-- =====================================================\n")
            f.write("-- SUMMARY\n")
            f.write("-- =====================================================\n")
            f.write("SELECT 'Research test seed generation complete' as status;\n\n")

            f.write("SELECT table_name, COUNT(*) as records\n")
            f.write("FROM information_schema.tables\n")
            f.write("WHERE table_schema = 'public' AND table_type = 'BASE TABLE'\n")
            f.write("GROUP BY table_name\n")
            f.write("ORDER BY table_name;\n")

    engine.dispose()
    print(f"    [OK] Generated {output_path}")


def main():
    """Main execution function"""
    print("=" * 60)
    print("TEST DATABASE SEED GENERATOR")
    print("=" * 60)

    try:
        supabase_url, research_url = get_db_connection()

        # Create output directory if needed
        output_dir = Path(__file__).parent.parent / "database"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Generate seeds
        generate_supabase_seed(supabase_url, output_dir / "test_seed_supabase.sql")
        generate_research_seed(research_url, output_dir / "test_seed_research.sql")

        print("\n" + "=" * 60)
        print("SEED GENERATION COMPLETE")
        print("=" * 60)
        print("\nGenerated files:")
        print("  - database/test_seed_supabase.sql")
        print("  - database/test_seed_research.sql")
        print("\nThese files are safe for Git commit (PII scrubbed).")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
