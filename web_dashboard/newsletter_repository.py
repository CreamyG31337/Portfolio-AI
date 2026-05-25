#!/usr/bin/env python3
"""
Newsletter Repository
Handles CRUD operations for newsletters stored in PostgreSQL research database
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from postgres_client import PostgresClient

logger = logging.getLogger(__name__)


class NewsletterRepository:
    """Repository for newsletter email storage and retrieval"""
    
    def __init__(self, postgres_client: Optional[PostgresClient] = None):
        """Initialize newsletter repository
        
        Args:
            postgres_client: Optional PostgresClient instance. If not provided, creates a new one.
        """
        try:
            self.client = postgres_client or PostgresClient()
            logger.debug("NewsletterRepository initialized successfully")
        except Exception as e:
            logger.error(f"NewsletterRepository initialization failed: {e}")
            raise
    
    def save_newsletter(
        self,
        sender: str,
        recipient: str,
        subject: str,
        body_plain: Optional[str] = None,
        body_html: Optional[str] = None,
        sender_name: Optional[str] = None,
        tickers: Optional[List[str]] = None,
        summary: Optional[str] = None,
        article_url: Optional[str] = None,
        embedding: Optional[List[float]] = None,
        message_id: Optional[str] = None,
        received_at: Optional[datetime] = None
    ) -> Optional[str]:
        """Save a newsletter to the database
        
        Args:
            sender: Sender email address
            recipient: Recipient email address
            subject: Email subject
            body_plain: Plain text email body
            body_html: HTML email body
            sender_name: Sender display name
            tickers: List of ticker symbols mentioned
            summary: AI-generated summary
            embedding: Vector embedding (list of 768 floats)
            message_id: Mailgun message ID for deduplication
            received_at: When email was received
            
        Returns:
            Newsletter ID (UUID as string) if successful, None otherwise
        """
        if not sender or not recipient or not subject:
            logger.error("Sender, recipient, and subject are required")
            return None
        
        try:
            # Prepare timestamps
            received_at_str = None
            if received_at:
                if received_at.tzinfo is None:
                    received_at = received_at.replace(tzinfo=timezone.utc)
                received_at_str = received_at.isoformat()
            
            # Prepare embedding (convert list to PostgreSQL vector format)
            embedding_str = None
            if embedding:
                embedding_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"
            
            # Prepare tickers array
            tickers_array = tickers if tickers else None
            
            # Build query
            if embedding_str:
                query = """
                    INSERT INTO newsletters (
                        sender, sender_name, recipient, subject, body_plain, body_html,
                        tickers, summary, article_url, embedding, message_id, received_at, processed_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT (message_id) DO UPDATE SET
                        sender = EXCLUDED.sender,
                        sender_name = EXCLUDED.sender_name,
                        recipient = EXCLUDED.recipient,
                        subject = EXCLUDED.subject,
                        body_plain = EXCLUDED.body_plain,
                        body_html = EXCLUDED.body_html,
                        tickers = EXCLUDED.tickers,
                        summary = EXCLUDED.summary,
                        article_url = EXCLUDED.article_url,
                        embedding = EXCLUDED.embedding,
                        processed_at = CURRENT_TIMESTAMP
                    RETURNING id
                """
                params = (
                    sender,
                    sender_name,
                    recipient,
                    subject,
                    body_plain,
                    body_html,
                    tickers_array,
                    summary,
                    article_url,
                    embedding_str,
                    message_id,
                    received_at_str
                )
            else:
                query = """
                    INSERT INTO newsletters (
                        sender, sender_name, recipient, subject, body_plain, body_html,
                        tickers, summary, article_url, message_id, received_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (message_id) DO UPDATE SET
                        sender = EXCLUDED.sender,
                        sender_name = EXCLUDED.sender_name,
                        recipient = EXCLUDED.recipient,
                        subject = EXCLUDED.subject,
                        body_plain = EXCLUDED.body_plain,
                        body_html = EXCLUDED.body_html,
                        tickers = EXCLUDED.tickers,
                        summary = EXCLUDED.summary,
                        article_url = EXCLUDED.article_url
                    RETURNING id
                """
                params = (
                    sender,
                    sender_name,
                    recipient,
                    subject,
                    body_plain,
                    body_html,
                    tickers_array,
                    summary,
                    article_url,
                    message_id,
                    received_at_str
                )
            
            with self.client.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                result = cursor.fetchone()
                conn.commit()
                
                if result:
                    newsletter_id = str(result[0])
                    logger.info(f"✅ Saved newsletter: {subject[:50]}... (ID: {newsletter_id})")
                    return newsletter_id
                else:
                    logger.warning("Newsletter saved but no ID returned")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Error saving newsletter: {e}")
            return None
    
    def get_recent_newsletters(
        self,
        limit: int = 20,
        offset: int = 0,
        ticker: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get recent newsletters
        
        Args:
            limit: Maximum number of results
            offset: Number of results to skip
            ticker: Optional filter by ticker symbol
            
        Returns:
            List of newsletter dictionaries
        """
        try:
            query = """
                SELECT id, sender, sender_name, recipient, subject,
                       body_plain, body_html, tickers, summary, article_url,
                       received_at, processed_at, message_id,
                       (embedding IS NOT NULL) as has_embedding
                FROM newsletters
            """
            params = []
            
            if ticker:
                query += " WHERE %s = ANY(tickers)"
                params.append(ticker)
            
            query += " ORDER BY received_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            
            results = self.client.execute_query(query, tuple(params))
            
            # Ensure timestamps have timezone info
            for newsletter in results:
                if newsletter.get('received_at') and isinstance(newsletter['received_at'], datetime):
                    if newsletter['received_at'].tzinfo is None:
                        newsletter['received_at'] = newsletter['received_at'].replace(tzinfo=timezone.utc)
                if newsletter.get('processed_at') and isinstance(newsletter['processed_at'], datetime):
                    if newsletter['processed_at'].tzinfo is None:
                        newsletter['processed_at'] = newsletter['processed_at'].replace(tzinfo=timezone.utc)
            
            logger.debug(f"Retrieved {len(results)} recent newsletters")
            return results
            
        except Exception as e:
            logger.error(f"❌ Error getting recent newsletters: {e}")
            return []
    
    def get_newsletter_by_id(self, newsletter_id: str) -> Optional[Dict[str, Any]]:
        """Get a newsletter by ID
        
        Args:
            newsletter_id: UUID of the newsletter
            
        Returns:
            Newsletter dictionary or None if not found
        """
        try:
            query = """
                SELECT id, sender, sender_name, recipient, subject,
                       body_plain, body_html, tickers, summary, article_url,
                       received_at, processed_at, message_id,
                       (embedding IS NOT NULL) as has_embedding
                FROM newsletters
                WHERE id = %s
            """
            
            results = self.client.execute_query(query, (newsletter_id,))
            
            if results:
                newsletter = results[0]
                # Ensure timestamps have timezone info
                if newsletter.get('received_at') and isinstance(newsletter['received_at'], datetime):
                    if newsletter['received_at'].tzinfo is None:
                        newsletter['received_at'] = newsletter['received_at'].replace(tzinfo=timezone.utc)
                if newsletter.get('processed_at') and isinstance(newsletter['processed_at'], datetime):
                    if newsletter['processed_at'].tzinfo is None:
                        newsletter['processed_at'] = newsletter['processed_at'].replace(tzinfo=timezone.utc)
                return newsletter
            else:
                return None
                
        except Exception as e:
            logger.error(f"❌ Error getting newsletter {newsletter_id}: {e}")
            return None
    
    def search_newsletters(
        self,
        query_text: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Search newsletters using semantic similarity
        
        This requires the query_text to be embedded first using Ollama.
        
        Args:
            query_text: Search query (will be embedded before searching)
            limit: Maximum number of results
            
        Returns:
            List of newsletter dictionaries with similarity scores
        """
        try:
            # Generate embedding for query text
            from ollama_client import get_ollama_client
            
            ollama = get_ollama_client()
            if not ollama:
                logger.warning("Ollama client not available - cannot perform semantic search")
                return []
            
            query_embedding = ollama.generate_embedding(query_text)
            if not query_embedding:
                logger.warning("Failed to generate embedding for query")
                return []
            
            # Convert embedding to PostgreSQL vector format
            embedding_str = "[" + ",".join(str(float(x)) for x in query_embedding) + "]"
            
            # Search using cosine similarity
            # <=> is the cosine distance operator in pgvector (lower is more similar)
            query = """
                SELECT id, sender, sender_name, recipient, subject,
                       body_plain, body_html, tickers, summary, article_url,
                       received_at, processed_at, message_id,
                       (1 - (embedding <=> %s::vector)) as similarity_score
                FROM newsletters
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """
            
            results = self.client.execute_query(query, (embedding_str, embedding_str, limit))
            
            # Ensure timestamps have timezone info
            for newsletter in results:
                if newsletter.get('received_at') and isinstance(newsletter['received_at'], datetime):
                    if newsletter['received_at'].tzinfo is None:
                        newsletter['received_at'] = newsletter['received_at'].replace(tzinfo=timezone.utc)
                if newsletter.get('processed_at') and isinstance(newsletter['processed_at'], datetime):
                    if newsletter['processed_at'].tzinfo is None:
                        newsletter['processed_at'] = newsletter['processed_at'].replace(tzinfo=timezone.utc)
            
            logger.info(f"Found {len(results)} newsletters matching query: {query_text[:50]}...")
            return results
            
        except Exception as e:
            logger.error(f"❌ Error searching newsletters: {e}")
            return []
    
    def update_embedding(self, newsletter_id: str, embedding: List[float]) -> bool:
        """Update a newsletter's embedding after initial save
        
        Args:
            newsletter_id: UUID of the newsletter
            embedding: Vector embedding (list of 768 floats)
            
        Returns:
            True if updated, False otherwise
        """
        try:
            embedding_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"
            query = """
                UPDATE newsletters
                SET embedding = %s::vector, processed_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """
            rows_updated = self.client.execute_update(query, (embedding_str, newsletter_id))
            return rows_updated > 0
        except Exception as e:
            logger.error(f"❌ Error updating embedding for newsletter {newsletter_id}: {e}")
            return False
    
    def find_recent_duplicate_by_body(
        self,
        body_plain: Optional[str],
        days: int = 30,
    ) -> Optional[str]:
        """Return the id of an existing newsletter with the same normalized body, if any.

        Compares md5(lower(collapsed-whitespace(body_plain))) so manual re-forwards
        (which get fresh ``Message-ID`` headers from Gmail) still dedup. Window
        bounded by ``days`` to keep the scan small.
        """
        if not body_plain or not body_plain.strip():
            return None
        try:
            import hashlib
            import re

            normalized = re.sub(r"\s+", " ", body_plain).strip().lower()
            target_hash = hashlib.md5(normalized.encode("utf-8")).hexdigest()
            query = (
                "SELECT id FROM newsletters "
                "WHERE body_plain IS NOT NULL "
                "AND md5(lower(regexp_replace(body_plain, '\\s+', ' ', 'g'))) = %s "
                "AND received_at > NOW() - (%s::int * INTERVAL '1 day') "
                "ORDER BY received_at DESC "
                "LIMIT 1"
            )
            results = self.client.execute_query(query, (target_hash, int(days)))
            if results:
                return str(results[0]["id"])
            return None
        except Exception as e:
            logger.error(f"❌ Error checking newsletter duplicate: {e}")
            return None

    def delete_newsletter(self, newsletter_id: str) -> bool:
        """Delete a newsletter by ID
        
        Args:
            newsletter_id: UUID of the newsletter to delete
            
        Returns:
            True if deleted, False otherwise
        """
        try:
            query = "DELETE FROM newsletters WHERE id = %s"
            rows_deleted = self.client.execute_update(query, (newsletter_id,))
            
            if rows_deleted > 0:
                logger.info(f"✅ Deleted newsletter {newsletter_id}")
                return True
            else:
                logger.warning(f"⚠️ Newsletter {newsletter_id} not found for deletion")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error deleting newsletter {newsletter_id}: {e}")
            return False
    
    def get_newsletter_count(self, ticker: Optional[str] = None) -> int:
        """Get total count of newsletters
        
        Args:
            ticker: Optional filter by ticker symbol
            
        Returns:
            Total count of newsletters
        """
        try:
            if ticker:
                query = "SELECT COUNT(*) FROM newsletters WHERE %s = ANY(tickers)"
                params = (ticker,)
            else:
                query = "SELECT COUNT(*) FROM newsletters"
                params = ()
            
            results = self.client.execute_query(query, params)
            return results[0]['count'] if results else 0
            
        except Exception as e:
            logger.error(f"❌ Error getting newsletter count: {e}")
            return 0
