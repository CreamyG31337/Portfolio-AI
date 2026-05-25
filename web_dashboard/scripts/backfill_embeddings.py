#!/usr/bin/env python3
"""
Backfill Embeddings for Research Articles
==========================================

Generates and saves embeddings for articles that don't have them yet.
Run this script after enabling RAG to populate embeddings for historical data.
"""

import sys
from pathlib import Path
import logging
import time
from typing import List, Dict, Any

# Add parent directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from research_repository import ResearchRepository
from ollama_client import get_ollama_client, check_ollama_health
from postgres_client import PostgresClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def backfill_embeddings(batch_size: int = 10, delay_between_batches: float = 2.0):
    """Generate embeddings for articles that don't have them.
    
    Args:
        batch_size: Number of articles to process before pausing
        delay_between_batches: Seconds to wait between batches
    """
    logger.info("Starting embedding backfill...")
    
    # Check Ollama availability
    if not check_ollama_health():
        logger.error("❌ Ollama is not available. Cannot generate embeddings.")
        return
    
    ollama_client = get_ollama_client()
    if not ollama_client:
        logger.error("❌ Failed to initialize Ollama client")
        return
    
    # Initialize repository
    try:
        repo = ResearchRepository()
    except Exception as e:
        logger.error(f"❌ Failed to initialize ResearchRepository: {e}")
        return
    
    # Get articles without embeddings
    query = """
        SELECT id, title, content
        FROM research_articles
        WHERE embedding IS NULL
        ORDER BY fetched_at DESC
    """
    
    try:
        articles = repo.client.execute_query(query)
        total_articles = len(articles)
        
        if total_articles == 0:
            logger.info("✅ All articles already have embeddings!")
            return
        
        logger.info(f"Found {total_articles} articles without embeddings")
        
        processed = 0
        successful = 0
        failed = 0
        
        for i, article in enumerate(articles):
            try:
                article_id = article['id']
                title = article.get('title', 'Untitled')
                content = article.get('content', '')
                
                if not content:
                    logger.warning(f"Skipping article {article_id}: no content")
                    failed += 1
                    continue
                
                # Generate embedding
                logger.info(f"[{i+1}/{total_articles}] Embedding: {title[:50]}...")
                embedding = ollama_client.generate_embedding(content)  # Truncate to avoid token limits
                
                if not embedding:
                    logger.warning(f"Failed to generate embedding for {article_id}")
                    failed += 1
                    continue
                
                # Save embedding to database
                embedding_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"
                update_query = "UPDATE research_articles SET embedding = %s::vector WHERE id = %s"
                repo.client.execute_update(update_query, (embedding_str, article_id))
                
                successful += 1
                processed += 1
                
                # Pause between batches to avoid overloading Ollama
                if processed % batch_size == 0:
                    logger.info(f"Processed {processed}/{total_articles} ({successful} successful, {failed} failed)")
                    logger.info(f"Pausing for {delay_between_batches}s...")
                    time.sleep(delay_between_batches)
                
            except Exception as e:
                logger.error(f"Error processing article {article.get('id')}: {e}")
                failed += 1
                continue
        
        logger.info(f"✅ Backfill complete: {successful} successful, {failed} failed out of {total_articles} total")
        
    except Exception as e:
        logger.error(f"❌ Error during backfill: {e}", exc_info=True)


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Research Articles Embedding Backfill")
    logger.info("=" * 60)
    
    # Process in batches of 10 with 2 second delays
    backfill_embeddings(batch_size=10, delay_between_batches=2.0)
    
    logger.info("=" * 60)
    logger.info("Backfill script complete")
    logger.info("=" * 60)
