-- Add article_url column to newsletters table
-- Stores the URL extracted from email body pointing to the full article on the web
ALTER TABLE newsletters ADD COLUMN IF NOT EXISTS article_url TEXT;
COMMENT ON COLUMN newsletters.article_url IS 'URL to the original article on the web, extracted from email body links';
