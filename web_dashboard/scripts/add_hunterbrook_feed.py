#!/usr/bin/env python3
"""
Add financial research RSS feed to the database.

This script adds a financial research feed to the RSS feeds table
so that the rss_feed_ingest_job will automatically collect articles from it.
"""

import sys
import os
import base64
from pathlib import Path

# Add web_dashboard to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from postgres_client import PostgresClient
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_research_feed():
    """Add financial research RSS feed to the database."""
    client = PostgresClient()
    
    # URL obfuscation (same pattern as jobs_congress.py)
    _FEED_URL_ENCODED = "aHR0cHM6Ly9obnRyYnJrLmNvbS9mZWVkLw=="
    feed_url = base64.b64decode(_FEED_URL_ENCODED).decode('utf-8')
    
    sql = """
    INSERT INTO rss_feeds (name, url, category, enabled) 
    VALUES ('Hunterbrook', %s, 'finance', true)
    ON CONFLICT (url) DO UPDATE 
    SET name = EXCLUDED.name,
        category = EXCLUDED.category,
        enabled = EXCLUDED.enabled,
        updated_at = NOW();
    """
    
    try:
        client.execute_update(sql, (feed_url,))
        logger.info("✅ Successfully added financial research RSS feed to database")
        
        # Verify it was added
        result = client.execute_query(
            "SELECT id, name, url, category, enabled FROM rss_feeds WHERE url = %s",
            (feed_url,)
        )
        if result:
            feed = result[0]
            logger.info(f"   Feed ID: {feed['id']}")
            logger.info(f"   Name: {feed['name']}")
            logger.info(f"   URL: {feed['url']}")
            logger.info(f"   Category: {feed['category']}")
            logger.info(f"   Enabled: {feed['enabled']}")
        else:
            logger.warning("⚠️ Feed was added but could not be verified")
            
    except Exception as e:
        logger.error(f"❌ Error adding research feed: {e}")
        raise

if __name__ == "__main__":
    try:
        add_research_feed()
    except Exception as e:
        logger.error(f"Script failed: {e}")
        sys.exit(1)
