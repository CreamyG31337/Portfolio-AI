import sys
import os
from pathlib import Path

# Add web_dashboard to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from postgres_client import PostgresClient
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def restore_table():
    client = PostgresClient()
    
    sql = """
    CREATE TABLE IF NOT EXISTS rss_feeds (
      id SERIAL PRIMARY KEY,
      name VARCHAR(200) NOT NULL,
      url TEXT NOT NULL UNIQUE,
      category VARCHAR(100),
      enabled BOOLEAN DEFAULT true,
      last_fetched_at TIMESTAMP WITH TIME ZONE,
      created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
      updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_rss_feeds_enabled 
      ON rss_feeds(enabled) WHERE enabled = true;

    CREATE INDEX IF NOT EXISTS idx_rss_feeds_last_fetched 
      ON rss_feeds(last_fetched_at DESC);

    INSERT INTO rss_feeds (name, url, category, enabled) VALUES
      ('StockTwits', 'https://www.stocktwits.com/sitemap/rss_feed.xml', 'finance', true),
      ('CNBC Finance', 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664', 'finance', true),
      ('Investing.com Breaking', 'https://ca.investing.com/rss/news_25.rss', 'finance', true),
      ('Fortune Finance', 'https://fortune.com/feed/finance', 'finance', true),
      ('Google News - AI Stocks', 'https://news.google.com/rss/search?q=artificial+intelligence+stocks+when:1d&hl=en-US&gl=US&ceid=US:en', 'tech', true),
      ('Hunterbrook', 'https://hntrbrk.com/feed/', 'finance', true)
    ON CONFLICT (url) DO NOTHING;
    """
    
    try:
        # Split statements if execute_update doesn't handle multiple
        # But psycopg2 usually handles multiple if valid. 
        # Safest is to execute the whole block.
        client.execute_update(sql)
        print("✅ RSS Table Restored Successfully")
        
        # Verify
        res = client.execute_query("SELECT count(*) FROM rss_feeds")
        print(f"Current feed count: {res[0]['count']}")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    restore_table()
