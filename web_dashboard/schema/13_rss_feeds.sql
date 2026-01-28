-- =====================================================
-- RSS FEEDS TRACKING
-- =====================================================
-- Store RSS feed sources for the "Push" strategy
-- Enables automatic ingestion from trusted news sources
-- =====================================================

-- Create rss_feeds table
CREATE TABLE IF NOT EXISTS rss_feeds (
  id SERIAL PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  url TEXT NOT NULL UNIQUE,
  category VARCHAR(100),  -- e.g., 'finance', 'tech', 'general'
  enabled BOOLEAN DEFAULT true,
  last_fetched_at TIMESTAMP WITH TIME ZONE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Add comments for documentation
COMMENT ON TABLE rss_feeds IS 
  'RSS feed sources for automatic news ingestion (Push strategy)';

COMMENT ON COLUMN rss_feeds.name IS 
  'Human-readable name of the feed source';

COMMENT ON COLUMN rss_feeds.url IS 
  'RSS/Atom feed URL';

COMMENT ON COLUMN rss_feeds.category IS 
  'Category of content (finance, tech, general, etc.)';

COMMENT ON COLUMN rss_feeds.enabled IS 
  'Whether this feed is currently active for fetching';

COMMENT ON COLUMN rss_feeds.last_fetched_at IS 
  'Last successful fetch timestamp';

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_rss_feeds_enabled 
  ON rss_feeds(enabled) WHERE enabled = true;

CREATE INDEX IF NOT EXISTS idx_rss_feeds_last_fetched 
  ON rss_feeds(last_fetched_at DESC);

-- Insert initial high-quality feeds
INSERT INTO rss_feeds (name, url, category, enabled) VALUES
  ('StockTwits', 'https://www.stocktwits.com/sitemap/rss_feed.xml', 'finance', true),
  ('CNBC Finance', 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664', 'finance', true),
  ('Investing.com Breaking', 'https://ca.investing.com/rss/news_25.rss', 'finance', true),
  ('Fortune Finance', 'https://fortune.com/feed/finance', 'finance', true),
  ('Google News - AI Stocks', 'https://news.google.com/rss/search?q=artificial+intelligence+stocks+when:1d&hl=en-US&gl=US&ceid=US:en', 'tech', true),
  ('Hunterbrook', 'https://hntrbrk.com/feed/', 'finance', true)
ON CONFLICT (url) DO NOTHING;

-- =====================================================
-- VERIFICATION
-- =====================================================

DO $$
DECLARE
  feed_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO feed_count FROM rss_feeds;
    
    RAISE NOTICE '✅ RSS feeds table created!';
    RAISE NOTICE '   Table: rss_feeds';
    RAISE NOTICE '   Indexes: 2 created';
    RAISE NOTICE '   Initial feeds: %', feed_count;
    RAISE NOTICE '';
    RAISE NOTICE 'Feed sources configured:';
    RAISE NOTICE '  - StockTwits (ticker-specific)';
    RAISE NOTICE '  - CNBC Finance';
    RAISE NOTICE '  - Investing.com';
    RAISE NOTICE '  - Fortune Finance';
    RAISE NOTICE '  - Google News (AI Stocks)';
    RAISE NOTICE '  - Hunterbrook (investigative finance)';
END $$;
