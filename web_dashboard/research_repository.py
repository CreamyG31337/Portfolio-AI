#!/usr/bin/env python3
"""
Research Articles Repository
Handles CRUD operations for research articles stored in local Postgres
"""

import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from postgres_client import PostgresClient

logger = logging.getLogger(__name__)


class ResearchRepository:
    """Repository for research articles stored in local Postgres"""
    
    def __init__(self, postgres_client: Optional[PostgresClient] = None):
        """Initialize research repository
        
        Args:
            postgres_client: Optional PostgresClient instance. If not provided, creates a new one.
        """
        try:
            self.client = postgres_client or PostgresClient()
            # Check which ticker column exists (for backward compatibility)
            self._has_tickers_column = self._check_tickers_column_exists()
            logger.debug(f"ResearchRepository initialized successfully (tickers column: {self._has_tickers_column})")
        except Exception as e:
            logger.error(f"ResearchRepository initialization failed: {e}")
            raise
    
    def _check_tickers_column_exists(self) -> bool:
        """Check if the tickers array column exists in the database.
        
        Returns:
            True if tickers column exists, False if only ticker column exists
        """
        try:
            query = """
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'research_articles' 
                  AND column_name = 'tickers'
            """
            result = self.client.execute_query(query)
            return len(result) > 0
        except Exception:
            # If we can't check, assume old schema (ticker column only)
            return False
    
    def _normalize_ticker_data(self, article: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize ticker data to always use 'tickers' key (array format).
        
        Handles backward compatibility with old 'ticker' column.
        
        Args:
            article: Article dictionary from database
            
        Returns:
            Article dictionary with normalized 'tickers' field
        """
        # If we have tickers array, use it
        if 'tickers' in article and article['tickers'] is not None:
            # Already in array format
            return article
        
        # Fallback to old ticker column
        if 'ticker' in article and article['ticker'] is not None:
            # Convert single ticker to array
            article['tickers'] = [article['ticker']]
            # Remove old ticker key to avoid confusion
            if 'ticker' in article:
                del article['ticker']
        else:
            # No ticker data
            article['tickers'] = None
        
        return article
    
    def save_article(
        self,
        tickers: Optional[List[str]] = None,
        sector: Optional[str] = None,
        article_type: str = "ticker_news",
        title: str = "",
        url: str = "",
        summary: Optional[str] = None,
        content: Optional[str] = None,
        source: Optional[str] = None,
        published_at: Optional[datetime] = None,
        relevance_score: Optional[float] = None,
        embedding: Optional[List[float]] = None,
        fund: Optional[str] = None,
        claims: Optional[List[str]] = None,
        fact_check: Optional[str] = None,
        conclusion: Optional[str] = None,
        sentiment: Optional[str] = None,
        sentiment_score: Optional[float] = None,
        logic_check: Optional[str] = None
    ) -> Optional[str]:
        """Save a research article to the database
        
        Args:
            tickers: List of stock ticker symbols (e.g., ["NVDA", "AMD"])
            sector: Sector name (e.g., "Technology")
            article_type: Type of article ('ticker_news', 'market_news', 'earnings', 'uploaded_report')
            title: Article title (required)
            url: Article URL (required, must be unique)
            summary: AI-generated summary
            content: Full article content
            source: Source name (e.g., "Yahoo Finance")
            published_at: When the article was published
            relevance_score: Relevance score (0.00 to 1.00)
            embedding: Vector embedding (list of 768 floats)
            fund: Fund name for fund-specific materials (e.g., uploaded research reports).
                  Should be NULL for general market news/articles that apply to all funds.
                  Purpose: Tag fund-specific research reports prepared for a specific fund.
            claims: List of specific claims extracted from article (Chain of Thought Step 1)
            fact_check: Simple fact-checking analysis (Chain of Thought Step 2)
            conclusion: Net impact on ticker(s) (Chain of Thought Step 3)
            sentiment: Sentiment category (VERY_BULLISH, BULLISH, NEUTRAL, BEARISH, VERY_BEARISH)
            sentiment_score: Numeric sentiment score for calculations (VERY_BULLISH=2.0, BULLISH=1.0, NEUTRAL=0.0, BEARISH=-1.0, VERY_BEARISH=-2.0)
            logic_check: Categorical classification (DATA_BACKED, HYPE_DETECTED, NEUTRAL) for relationship confidence scoring
            
        Returns:
            Article ID (UUID as string) if successful, None otherwise
        """
        if not title or not url:
            logger.error("Title and URL are required")
            return None
        
        try:
            # Prepare published_at timestamp
            published_at_str = None
            if published_at:
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=timezone.utc)
                published_at_str = published_at.isoformat()
            
            # Prepare embedding (convert list to PostgreSQL vector format)
            embedding_str = None
            if embedding:
                # PostgreSQL vector format: '[0.1,0.2,0.3]'
                embedding_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"
            
            # Prepare tickers array (convert None/empty to None for database)
            tickers_array = tickers if tickers else None
            
            # Prepare claims as JSONB (convert list to JSON string)
            claims_json = json.dumps(claims) if claims else None
            
            # Build query dynamically based on whether embedding is provided
            if embedding_str:
                query = """
                    INSERT INTO research_articles (
                        tickers, sector, article_type, title, url, summary, content,
                        source, published_at, relevance_score, embedding, fund,
                        claims, fact_check, conclusion, sentiment, sentiment_score, logic_check
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s,
                        %s::jsonb, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (url) DO UPDATE SET
                        tickers = EXCLUDED.tickers,
                        sector = EXCLUDED.sector,
                        article_type = EXCLUDED.article_type,
                        title = EXCLUDED.title,
                        summary = EXCLUDED.summary,
                        content = EXCLUDED.content,
                        source = EXCLUDED.source,
                        published_at = EXCLUDED.published_at,
                        relevance_score = EXCLUDED.relevance_score,
                        embedding = EXCLUDED.embedding,
                        fund = EXCLUDED.fund,
                        claims = EXCLUDED.claims,
                        fact_check = EXCLUDED.fact_check,
                        conclusion = EXCLUDED.conclusion,
                        sentiment = EXCLUDED.sentiment,
                        sentiment_score = EXCLUDED.sentiment_score,
                        logic_check = EXCLUDED.logic_check,
                        fetched_at = CURRENT_TIMESTAMP
                    RETURNING id
                """
                params = (
                    tickers_array,
                    sector,
                    article_type,
                    title,
                    url,
                    summary,
                    content,
                    source,
                    published_at_str,
                    relevance_score,
                    embedding_str,
                    fund,
                    claims_json,
                    fact_check,
                    conclusion,
                    sentiment,
                    sentiment_score,
                    logic_check
                )
            else:
                query = """
                    INSERT INTO research_articles (
                        tickers, sector, article_type, title, url, summary, content,
                        source, published_at, relevance_score, fund,
                        claims, fact_check, conclusion, sentiment, sentiment_score, logic_check
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (url) DO UPDATE SET
                        tickers = EXCLUDED.tickers,
                        sector = EXCLUDED.sector,
                        article_type = EXCLUDED.article_type,
                        title = EXCLUDED.title,
                        summary = EXCLUDED.summary,
                        content = EXCLUDED.content,
                        source = EXCLUDED.source,
                        published_at = EXCLUDED.published_at,
                        relevance_score = EXCLUDED.relevance_score,
                        fund = EXCLUDED.fund,
                        claims = EXCLUDED.claims,
                        fact_check = EXCLUDED.fact_check,
                        conclusion = EXCLUDED.conclusion,
                        sentiment = EXCLUDED.sentiment,
                        sentiment_score = EXCLUDED.sentiment_score,
                        logic_check = EXCLUDED.logic_check,
                        fetched_at = CURRENT_TIMESTAMP
                    RETURNING id
                """
                params = (
                    tickers_array,
                    sector,
                    article_type,
                    title,
                    url,
                    summary,
                    content,
                    source,
                    published_at_str,
                    relevance_score,
                    fund,
                    claims_json,
                    fact_check,
                    conclusion,
                    sentiment,
                    sentiment_score,
                    logic_check
                )
            
            with self.client.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                result = cursor.fetchone()
                conn.commit()
                
                if result:
                    article_id = str(result[0])
                    logger.info(f"✅ Saved article: {title[:50]}... (ID: {article_id})")
                    return article_id
                else:
                    # Article may already exist (ON CONFLICT DO NOTHING)
                    # Try to get existing article ID
                    logger.debug(f"Article may already exist, fetching ID for URL: {url}")
                    existing = self.client.execute_query(
                        "SELECT id FROM research_articles WHERE url = %s",
                        (url,)
                    )
                    if existing:
                        article_id = str(existing[0]['id'])
                        logger.info(f"✅ Article already exists: {title[:50]}... (ID: {article_id})")
                        return article_id
                    else:
                        logger.warning("Article saved but no ID returned and not found by URL")
                        return None
                    
        except Exception as e:
            logger.error(f"❌ Error saving article: {e}")
            return None
    
    def save_relationship(
        self,
        source_ticker: str,
        target_ticker: str,
        relationship_type: str,
        initial_confidence: float,
        source_article_id: Optional[str] = None
    ) -> Optional[int]:
        """Save a market relationship to the database.
        
        Uses ON CONFLICT to increment confidence on duplicate relationships.
        If relationship already exists, confidence is incremented by 0.1 (capped at 1.0).
        
        Args:
            source_ticker: Source company ticker (e.g., "TSM")
            target_ticker: Target company ticker (e.g., "AAPL")
            relationship_type: Type of relationship (e.g., "SUPPLIER", "COMPETITOR")
            initial_confidence: Initial confidence score (0.0 to 1.0)
            source_article_id: UUID of the article that discovered this relationship (optional)
            
        Returns:
            Relationship ID if successful, None otherwise
        """
        if not source_ticker or not target_ticker or not relationship_type:
            logger.error("Source ticker, target ticker, and relationship type are required")
            return None
        
        try:
            query = """
                INSERT INTO market_relationships (
                    source_ticker, target_ticker, relationship_type,
                    confidence_score, source_article_id
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (source_ticker, target_ticker, relationship_type)
                DO UPDATE SET
                    confidence_score = LEAST(market_relationships.confidence_score + 0.1, 1.0),
                    detected_at = NOW()
                RETURNING id
            """
            params = (
                source_ticker.upper().strip(),
                target_ticker.upper().strip(),
                relationship_type.upper().strip(),
                initial_confidence,
                source_article_id
            )
            
            with self.client.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                result = cursor.fetchone()
                conn.commit()
                
                if result:
                    relationship_id = result[0]
                    logger.debug(f"✅ Saved relationship: {source_ticker} -> {relationship_type} -> {target_ticker} (ID: {relationship_id}, confidence: {initial_confidence})")
                    return relationship_id
                else:
                    logger.warning("Relationship saved but no ID returned")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Error saving relationship: {e}")
            return None
    
    def get_articles_by_ticker(
        self,
        ticker: str,
        limit: int = 20,
        offset: int = 0,
        article_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get articles for a specific ticker.
        
        For ETFs, also includes sector-level articles (where ticker IS NULL but sector matches).
        
        Args:
            ticker: Stock ticker symbol
            limit: Maximum number of results
            offset: Number of results to skip
            article_type: Optional filter by article type
            
        Returns:
            List of article dictionaries
        """
        try:
            # Check if this is an ETF and get its sector
            etf_sector = None
            try:
                # Check if ticker or company name contains "ETF"
                sector_query = """
                    SELECT sector, company_name
                    FROM securities
                    WHERE ticker = %s
                """
                sector_result = self.client.execute_query(sector_query, (ticker,))
                
                if sector_result:
                    sec = sector_result[0]
                    company_name = sec.get('company_name', '') or ''
                    # Check if it's an ETF
                    is_etf = (
                        'etf' in ticker.lower() or 
                        (company_name and 'etf' in company_name.lower())
                    )
                    if is_etf:
                        etf_sector = sec.get('sector')
                        if etf_sector:
                            logger.debug(f"Ticker {ticker} is an ETF with sector: {etf_sector}")
            except Exception as e:
                logger.debug(f"Could not check ETF status for {ticker}: {e}")
            
            # Build query: include ticker-specific articles, and for ETFs also include sector articles
            # Handle both old (ticker) and new (tickers array) schema
            if self._has_tickers_column:
                # New schema: use array lookup
                if etf_sector:
                    query = """
                        SELECT id, tickers, sector, article_type, title, url, summary, content,
                               source, published_at, fetched_at, relevance_score, fund,
                               claims, fact_check, conclusion, sentiment, sentiment_score,
                               archive_url, archive_submitted_at, archive_checked_at,
                               (embedding IS NOT NULL) as has_embedding
                        FROM research_articles
                        WHERE (%s = ANY(tickers) OR (tickers IS NULL AND sector = %s))
                    """
                    params = [ticker, etf_sector]
                else:
                    query = """
                        SELECT id, tickers, sector, article_type, title, url, summary, content,
                               source, published_at, fetched_at, relevance_score, fund,
                               archive_url, archive_submitted_at, archive_checked_at,
                               (embedding IS NOT NULL) as has_embedding
                        FROM research_articles
                        WHERE %s = ANY(tickers)
                    """
                    params = [ticker]
            else:
                # Old schema: use single ticker column
                if etf_sector:
                    query = """
                        SELECT id, ticker, sector, article_type, title, url, summary, content,
                               source, published_at, fetched_at, relevance_score, fund,
                               claims, fact_check, conclusion, sentiment, sentiment_score,
                               archive_url, archive_submitted_at, archive_checked_at,
                               (embedding IS NOT NULL) as has_embedding
                        FROM research_articles
                        WHERE (ticker = %s OR (ticker IS NULL AND sector = %s))
                    """
                    params = [ticker, etf_sector]
                else:
                    query = """
                        SELECT id, ticker, sector, article_type, title, url, summary, content,
                               source, published_at, fetched_at, relevance_score, fund,
                               archive_url, archive_submitted_at, archive_checked_at,
                               (embedding IS NOT NULL) as has_embedding
                        FROM research_articles
                        WHERE ticker = %s
                    """
                    params = [ticker]
            
            if article_type:
                query += " AND article_type = %s"
                params.append(article_type)
            
            query += " ORDER BY fetched_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            
            results = self.client.execute_query(query, tuple(params))
            
            # Note: RealDictCursor already returns TIMESTAMP columns as datetime objects
            # Normalize ticker data to always use 'tickers' array format
            normalized_results = []
            for article in results:
                article = self._normalize_ticker_data(article)
                if article.get('published_at') and isinstance(article['published_at'], datetime):
                    if article['published_at'].tzinfo is None:
                        article['published_at'] = article['published_at'].replace(tzinfo=timezone.utc)
                if article.get('fetched_at') and isinstance(article['fetched_at'], datetime):
                    if article['fetched_at'].tzinfo is None:
                        article['fetched_at'] = article['fetched_at'].replace(tzinfo=timezone.utc)
                normalized_results.append(article)
            
            logger.debug(f"Retrieved {len(normalized_results)} articles for ticker {ticker}" + 
                        (f" (including {etf_sector} sector articles)" if etf_sector else ""))
            return normalized_results
            
        except Exception as e:
            logger.error(f"❌ Error getting articles by ticker: {e}")
            return []
    
    def get_recent_articles(
        self,
        limit: int = 20,
        days: int = 7,
        article_type: Optional[str] = None,
        ticker: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get recent articles
        
        Args:
            limit: Maximum number of results
            days: Number of days to look back
            article_type: Optional filter by article type
            ticker: Optional filter by ticker
            
        Returns:
            List of article dictionaries
        """
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            
            # Select appropriate ticker column based on schema version
            ticker_column = "tickers" if self._has_tickers_column else "ticker"
            query = f"""
                SELECT id, {ticker_column}, sector, article_type, title, url, summary, content,
                       source, published_at, fetched_at, relevance_score, fund,
                       archive_url, archive_submitted_at, archive_checked_at,
                       (embedding IS NOT NULL) as has_embedding
                FROM research_articles
                WHERE fetched_at >= %s
            """
            params = [cutoff_date.isoformat()]
            
            if article_type:
                query += " AND article_type = %s"
                params.append(article_type)
            
            if ticker:
                # Check if this is an ETF and get its sector
                etf_sector = None
                try:
                    sector_query = "SELECT sector, company_name FROM securities WHERE ticker = %s"
                    sector_result = self.client.execute_query(sector_query, (ticker,))
                    
                    if sector_result:
                        sec = sector_result[0]
                        company_name = sec.get('company_name', '') or ''
                        is_etf = ('etf' in ticker.lower() or (company_name and 'etf' in company_name.lower()))
                        if is_etf:
                            etf_sector = sec.get('sector')
                            logger.debug(f"Ticker {ticker} is an ETF with sector: {etf_sector}")
                except Exception as e:
                    logger.debug(f"Could not check ETF status for {ticker}: {e}")
                
                # Include sector articles for ETFs
                if etf_sector:
                    query += " AND (%s = ANY(tickers) OR (tickers IS NULL AND sector = %s))"
                    params.extend([ticker, etf_sector])
                else:
                    query += " AND %s = ANY(tickers)"
                    params.append(ticker)
            
            query += " ORDER BY fetched_at DESC LIMIT %s"
            params.append(limit)
            
            results = self.client.execute_query(query, tuple(params))
            
            # Note: RealDictCursor already returns TIMESTAMP columns as datetime objects
            for article in results:
                if article.get('published_at') and isinstance(article['published_at'], datetime):
                    if article['published_at'].tzinfo is None:
                        article['published_at'] = article['published_at'].replace(tzinfo=timezone.utc)
                if article.get('fetched_at') and isinstance(article['fetched_at'], datetime):
                    if article['fetched_at'].tzinfo is None:
                        article['fetched_at'] = article['fetched_at'].replace(tzinfo=timezone.utc)
            
            logger.debug(f"Retrieved {len(results)} recent articles")
            return results
            
        except Exception as e:
            logger.error(f"❌ Error getting recent articles: {e}")
            return []
    
    def delete_old_articles(self, days_to_keep: int = 30) -> int:
        """Delete articles older than specified days
        
        Args:
            days_to_keep: Number of days of articles to keep
            
        Returns:
            Number of articles deleted
        """
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
            
            query = "DELETE FROM research_articles WHERE fetched_at < %s"
            params = (cutoff_date.isoformat(),)
            
            rows_deleted = self.client.execute_update(query, params)
            logger.info(f"✅ Deleted {rows_deleted} old articles (older than {days_to_keep} days)")
            return rows_deleted
            
        except Exception as e:
            logger.error(f"❌ Error deleting old articles: {e}")
            return 0
    
    def delete_article(self, article_id: str) -> bool:
        """Delete a single article by ID
        
        Args:
            article_id: UUID of the article to delete
            
        Returns:
            True if deleted, False otherwise
        """
        try:
            query = "DELETE FROM research_articles WHERE id = %s"
            rows_deleted = self.client.execute_update(query, (article_id,))
            
            if rows_deleted > 0:
                logger.info(f"✅ Deleted article {article_id}")
                return True
            else:
                logger.warning(f"⚠️ Article {article_id} not found for deletion")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error deleting article {article_id}: {e}")
            return False
    
    def update_article_analysis(
        self,
        article_id: str,
        summary: Optional[str] = None,
        tickers: Optional[List[str]] = None,
        sector: Optional[str] = None,
        embedding: Optional[List[float]] = None,
        relevance_score: Optional[float] = None,
        claims: Optional[List[str]] = None,
        fact_check: Optional[str] = None,
        conclusion: Optional[str] = None,
        sentiment: Optional[str] = None,
        sentiment_score: Optional[float] = None,
        logic_check: Optional[str] = None
    ) -> bool:
        """Update AI-generated fields of an article (summary, tickers, sector, embedding, relevance_score, Chain of Thought fields).
        
        Preserves original fields: title, url, content, source, published_at, fetched_at, article_type.
        
        Args:
            article_id: UUID of the article to update
            summary: New AI-generated summary
            tickers: List of extracted tickers (can be None to clear)
            sector: Extracted sector (can be None to clear)
            embedding: New vector embedding (list of 768 floats)
            relevance_score: Recalculated relevance score (0.0 to 1.0)
            claims: List of specific claims extracted (Chain of Thought Step 1)
            fact_check: Simple fact-checking analysis (Chain of Thought Step 2)
            conclusion: Net impact on ticker(s) (Chain of Thought Step 3)
            sentiment: Sentiment category (VERY_BULLISH, BULLISH, NEUTRAL, BEARISH, VERY_BEARISH)
            sentiment_score: Numeric sentiment score for calculations
            
        Returns:
            True if updated successfully, False otherwise
        """
        try:
            # Build UPDATE query dynamically based on what's provided
            updates = []
            params = []
            
            if summary is not None:
                updates.append("summary = %s")
                params.append(summary)
            
            if tickers is not None:
                # Convert None/empty list to None for database
                tickers_array = tickers if tickers else None
                updates.append("tickers = %s")
                params.append(tickers_array)
            elif tickers is None and any(x is not None for x in [summary, sector, embedding, relevance_score]):
                # Allow explicitly clearing tickers by passing None
                # Only add if we're actually updating something
                updates.append("tickers = %s")
                params.append(None)
            
            if sector is not None:
                updates.append("sector = %s")
                params.append(sector)
            elif sector is None and any(x is not None for x in [summary, tickers, embedding, relevance_score]):
                # Allow explicitly clearing sector
                updates.append("sector = %s")
                params.append(None)
            
            if embedding is not None:
                # Convert embedding list to PostgreSQL vector format
                embedding_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"
                updates.append("embedding = %s::vector")
                params.append(embedding_str)
            
            if relevance_score is not None:
                updates.append("relevance_score = %s")
                params.append(float(relevance_score))
            
            # Chain of Thought fields
            if claims is not None:
                claims_json = json.dumps(claims) if claims else None
                updates.append("claims = %s::jsonb")
                params.append(claims_json)
            
            if fact_check is not None:
                updates.append("fact_check = %s")
                params.append(fact_check)
            
            if conclusion is not None:
                updates.append("conclusion = %s")
                params.append(conclusion)
            
            if sentiment is not None:
                updates.append("sentiment = %s")
                params.append(sentiment)
            
            if sentiment_score is not None:
                updates.append("sentiment_score = %s")
                params.append(float(sentiment_score))
            
            if logic_check is not None:
                updates.append("logic_check = %s")
                params.append(logic_check)
            
            if not updates:
                logger.warning(f"No fields to update for article {article_id}")
                return False
            
            # Add article_id to params
            params.append(article_id)
            
            query = f"UPDATE research_articles SET {', '.join(updates)} WHERE id = %s"
            
            rows_updated = self.client.execute_update(query, tuple(params))
            
            if rows_updated > 0:
                logger.info(f"✅ Updated article {article_id} analysis")
                return True
            else:
                logger.warning(f"⚠️ Article {article_id} not found for update")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error updating article {article_id} analysis: {e}")
            return False
    
    def mark_archive_submitted(self, article_id: str, original_url: str) -> bool:
        """Mark an article as submitted to archive service.
        
        Args:
            article_id: UUID of the article
            original_url: Original article URL that was submitted
            
        Returns:
            True if successful, False otherwise
        """
        try:
            query = """
                UPDATE research_articles
                SET archive_submitted_at = %s
                WHERE id = %s
            """
            rows_updated = self.client.execute_update(
                query,
                (datetime.now(timezone.utc), article_id)
            )
            if rows_updated > 0:
                logger.debug(f"Marked article {article_id} as archive submitted")
                return True
            else:
                logger.warning(f"Article {article_id} not found for archive submission marking")
                return False
        except Exception as e:
            logger.error(f"Error marking archive submitted for {article_id}: {e}")
            return False
    
    def get_pending_archive_articles(self, min_wait_minutes: int = 5) -> List[Dict[str, Any]]:
        """Get articles that were submitted for archiving but not yet checked.
        
        Only returns articles that were submitted at least min_wait_minutes ago
        (to give archive service time to process).
        
        Args:
            min_wait_minutes: Minimum minutes to wait after submission before checking
            
        Returns:
            List of article dictionaries with id, url, archive_submitted_at
        """
        try:
            query = """
                SELECT id, url, archive_submitted_at, archive_checked_at
                FROM research_articles
                WHERE archive_submitted_at IS NOT NULL
                  AND archive_url IS NULL
                  AND archive_submitted_at <= %s
                ORDER BY archive_submitted_at ASC
                LIMIT 100
            """
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=min_wait_minutes)
            results = self.client.execute_query(query, (cutoff_time,))
            return results
        except Exception as e:
            logger.error(f"Error getting pending archive articles: {e}")
            return []
    
    def mark_archive_checked(self, article_id: str, archive_url: Optional[str] = None, success: bool = False) -> bool:
        """Mark an article as checked for archiving.
        
        Args:
            article_id: UUID of the article
            archive_url: Archived URL if found, None otherwise
            success: True if archived version was found
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if success and archive_url:
                query = """
                    UPDATE research_articles
                    SET archive_checked_at = %s,
                        archive_url = %s
                    WHERE id = %s
                """
                rows_updated = self.client.execute_update(
                    query,
                    (datetime.now(timezone.utc), archive_url, article_id)
                )
            else:
                query = """
                    UPDATE research_articles
                    SET archive_checked_at = %s
                    WHERE id = %s
                """
                rows_updated = self.client.execute_update(
                    query,
                    (datetime.now(timezone.utc), article_id)
                )
            if rows_updated > 0:
                logger.debug(f"Marked article {article_id} as archive checked (success: {success})")
                return True
            else:
                logger.warning(f"Article {article_id} not found for archive check marking")
                return False
        except Exception as e:
            logger.error(f"Error marking archive checked for {article_id}: {e}")
            return False
    
    def update_article_fund(self, article_id: str, fund: Optional[str] = None) -> bool:
        """Update the fund assignment for an article.
        
        Args:
            article_id: UUID of the article to update
            fund: Fund name (None to clear fund assignment)
            
        Returns:
            True if updated successfully, False otherwise
        """
        try:
            query = "UPDATE research_articles SET fund = %s WHERE id = %s"
            params = (fund, article_id)
            
            rows_updated = self.client.execute_update(query, params)
            
            if rows_updated > 0:
                logger.info(f"✅ Updated fund for article {article_id} to {fund}")
                return True
            else:
                logger.warning(f"⚠️ Article {article_id} not found for fund update")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error updating article fund: {e}")
            return False
    
    def search_similar_articles(
        self,
        query_embedding: List[float],
        limit: int = 5,
        min_similarity: float = 0.5,
        ticker: Optional[str] = None,
        article_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search for articles similar to the query embedding using vector similarity.
        
        Args:
            query_embedding: Vector embedding of the search query (768 dimensions)
            limit: Maximum number of results to return
            min_similarity: Minimum cosine similarity score (0.0 to 1.0)
            ticker: Optional filter by ticker
            article_type: Optional filter by article type
            
        Returns:
            List of article dictionaries with similarity scores
        """
        try:
            # Convert embedding list to PostgreSQL vector format
            embedding_str = "[" + ",".join(str(float(x)) for x in query_embedding) + "]"
            
            # Build query with vector similarity search
            # <=> is cosine distance operator in pgvector
            # Similarity = 1 - distance
            # Select appropriate ticker column based on schema version
            ticker_column = "tickers" if self._has_tickers_column else "ticker"
            query = f"""
                SELECT 
                    id, {ticker_column}, sector, article_type, title, url, summary, content,
                    source, published_at, fetched_at, relevance_score,
                    1 - (embedding <=> %s::vector) as similarity,
                    (embedding IS NOT NULL) as has_embedding
                FROM research_articles
                WHERE embedding IS NOT NULL
                  AND 1 - (embedding <=> %s::vector) >= %s
            """
            params = [embedding_str, embedding_str, min_similarity]
            
            # Add optional filters
            if ticker:
                # Check if this is an ETF and get its sector
                etf_sector = None
                try:
                    sector_query = "SELECT sector, company_name FROM securities WHERE ticker = %s"
                    sector_result = self.client.execute_query(sector_query, (ticker,))
                    
                    if sector_result:
                        sec = sector_result[0]
                        company_name = sec.get('company_name', '') or ''
                        is_etf = ('etf' in ticker.lower() or (company_name and 'etf' in company_name.lower()))
                        if is_etf:
                            etf_sector = sec.get('sector')
                            logger.debug(f"Ticker {ticker} is an ETF with sector: {etf_sector}")
                except Exception as e:
                    logger.debug(f"Could not check ETF status for {ticker}: {e}")
                
                # Include sector articles for ETFs
                if self._has_tickers_column:
                    # New schema: use array lookup
                    if etf_sector:
                        query += " AND (%s = ANY(tickers) OR (tickers IS NULL AND sector = %s))"
                        params.extend([ticker, etf_sector])
                    else:
                        query += " AND %s = ANY(tickers)"
                        params.append(ticker)
                else:
                    # Old schema: use single ticker column
                    if etf_sector:
                        query += " AND (ticker = %s OR (ticker IS NULL AND sector = %s))"
                        params.extend([ticker, etf_sector])
                    else:
                        query += " AND ticker = %s"
                        params.append(ticker)
            
            if article_type:
                query += " AND article_type = %s"
                params.append(article_type)
            
            # Order by similarity and limit
            query += " ORDER BY similarity DESC LIMIT %s"
            params.append(limit)
            
            results = self.client.execute_query(query, tuple(params))
            
            # Process datetime fields and normalize ticker data
            normalized_results = []
            for article in results:
                article = self._normalize_ticker_data(article)
                if article.get('published_at') and isinstance(article['published_at'], datetime):
                    if article['published_at'].tzinfo is None:
                        article['published_at'] = article['published_at'].replace(tzinfo=timezone.utc)
                if article.get('fetched_at') and isinstance(article['fetched_at'], datetime):
                    if article['fetched_at'].tzinfo is None:
                        article['fetched_at'] = article['fetched_at'].replace(tzinfo=timezone.utc)
                normalized_results.append(article)
            
            logger.info(f"✅ Found {len(normalized_results)} similar articles (min_similarity={min_similarity})")
            return normalized_results
            
        except Exception as e:
            logger.error(f"❌ Error searching similar articles: {e}")
            return []
    
    def search_articles(
        self,
        query_text: str,
        ticker: Optional[str] = None,
        limit: int = 10,
        min_relevance: float = 0.0
    ) -> List[Dict[str, Any]]:
        """Search articles by text (basic text search, vector search coming later)
        
        Args:
            query_text: Search query
            ticker: Optional filter by ticker
            limit: Maximum number of results
            min_relevance: Minimum relevance score
            
        Returns:
            List of article dictionaries
        """
        try:
            # Select appropriate ticker column based on schema version
            ticker_column = "tickers" if self._has_tickers_column else "ticker"
            search_query = f"""
                SELECT id, {ticker_column}, sector, article_type, title, url, summary, content,
                       source, published_at, fetched_at, relevance_score, fund,
                       (embedding IS NOT NULL) as has_embedding
                FROM research_articles
                WHERE (title ILIKE %s OR summary ILIKE %s OR content ILIKE %s)
                  AND relevance_score >= %s
            """
            params = [f"%{query_text}%", f"%{query_text}%", f"%{query_text}%", min_relevance]
            
            if ticker:
                if self._has_tickers_column:
                    search_query += " AND %s = ANY(tickers)"
                else:
                    search_query += " AND ticker = %s"
                params.append(ticker)
            
            search_query += " ORDER BY relevance_score DESC, fetched_at DESC LIMIT %s"
            params.append(limit)
            
            results = self.client.execute_query(search_query, tuple(params))
            
            # Note: RealDictCursor already returns TIMESTAMP columns as datetime objects
            for article in results:
                if article.get('published_at') and isinstance(article['published_at'], datetime):
                    if article['published_at'].tzinfo is None:
                        article['published_at'] = article['published_at'].replace(tzinfo=timezone.utc)
                if article.get('fetched_at') and isinstance(article['fetched_at'], datetime):
                    if article['fetched_at'].tzinfo is None:
                        article['fetched_at'] = article['fetched_at'].replace(tzinfo=timezone.utc)
            
            logger.debug(f"Found {len(results)} articles matching '{query_text}'")
            return results
            
        except Exception as e:
            logger.error(f"❌ Error searching articles: {e}")
            return []
    
    def article_exists(self, url: str) -> bool:
        """Check if an article with the given URL already exists
        
        Args:
            url: Article URL
            
        Returns:
            True if article exists, False otherwise
        """
        try:
            query = "SELECT id FROM research_articles WHERE url = %s LIMIT 1"
            results = self.client.execute_query(query, (url,))
            return len(results) > 0
        except Exception as e:
            logger.error(f"❌ Error checking if article exists: {e}")
            return False
    
    def get_article_statistics(self, days: int = 30) -> Dict[str, Any]:
        """Get statistics about articles
        
        Args:
            days: Number of days to look back for statistics
            
        Returns:
            Dictionary with statistics:
            - total_count: Total number of articles
            - by_type: Count by article_type
            - by_source: Count by source
            - by_day: Count by day (last N days)
        """
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            
            stats = {}
            
            # Total count
            total_result = self.client.execute_query("SELECT COUNT(*) as count FROM research_articles")
            stats['total_count'] = total_result[0]['count'] if total_result else 0
            
            # Count by type
            type_result = self.client.execute_query("""
                SELECT article_type, COUNT(*) as count
                FROM research_articles
                GROUP BY article_type
                ORDER BY count DESC
            """)
            stats['by_type'] = {row['article_type']: row['count'] for row in type_result} if type_result else {}
            
            # Count by source
            source_result = self.client.execute_query("""
                SELECT source, COUNT(*) as count
                FROM research_articles
                WHERE source IS NOT NULL
                GROUP BY source
                ORDER BY count DESC
            """)
            stats['by_source'] = {row['source']: row['count'] for row in source_result} if source_result else {}
            
            # Count by day (last N days)
            day_result = self.client.execute_query("""
                SELECT DATE(fetched_at) as day, COUNT(*) as count
                FROM research_articles
                WHERE fetched_at >= %s
                GROUP BY DATE(fetched_at)
                ORDER BY day DESC
            """, (cutoff_date.isoformat(),))
            stats['by_day'] = {str(row['day']): row['count'] for row in day_result} if day_result else {}
            
            return stats
            
        except Exception as e:
            logger.error(f"❌ Error getting article statistics: {e}")
            return {
                'total_count': 0,
                'by_type': {},
                'by_source': {},
                'by_day': {}
            }
    
    def get_unique_sources(self) -> List[str]:
        """Get list of all unique sources
        
        Returns:
            List of unique source names, sorted alphabetically
        """
        try:
            result = self.client.execute_query("""
                SELECT DISTINCT source
                FROM research_articles
                WHERE source IS NOT NULL
                ORDER BY source
            """)
            return [row['source'] for row in result] if result else []
        except Exception as e:
            logger.error(f"❌ Error getting unique sources: {e}")
            return []
    
    def get_unique_tickers(self) -> List[str]:
        """Get list of all unique tickers from articles
        
        Returns:
            List of unique ticker symbols, sorted alphabetically
        """
        try:
            # Use UNNEST to extract tickers from the array column
            # Use 't' as alias to avoid conflict with 'ticker' column (if it exists)
            result = self.client.execute_query("""
                SELECT DISTINCT t AS ticker
                FROM research_articles, UNNEST(tickers) AS t
                WHERE tickers IS NOT NULL
                ORDER BY t
            """)
            return [row['ticker'] for row in result] if result else []
        except Exception as e:
            logger.error(f"❌ Error getting unique tickers: {e}")
            return []
    
    def get_articles_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        article_type: Optional[str] = None,
        source: Optional[str] = None,
        search_text: Optional[str] = None,
        embedding_filter: Optional[bool] = None,
        tickers_filter: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get articles within a date range with optional filters
        
        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            article_type: Optional filter by article type
            source: Optional filter by source
            search_text: Optional text search in title, summary, content
            embedding_filter: Optional filter by embedding status (True=has embedding, False=no embedding, None=all)
            tickers_filter: Optional list of tickers to filter by (articles must have at least one matching ticker)
            limit: Maximum number of results
            offset: Number of results to skip
            
        Returns:
            List of article dictionaries
        """
        try:
            # Ensure timezone-aware datetimes
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            
            # Select appropriate ticker column based on schema version
            ticker_column = "tickers" if self._has_tickers_column else "ticker"
            query = f"""
                SELECT id, {ticker_column}, sector, article_type, title, url, summary, content,
                       source, published_at, fetched_at, relevance_score, fund,
                       claims, fact_check, conclusion, sentiment, sentiment_score,
                       archive_url, archive_submitted_at, archive_checked_at,
                       (embedding IS NOT NULL) as has_embedding
                FROM research_articles
                WHERE fetched_at >= %s AND fetched_at <= %s
            """
            # Convert to ISO format strings for PostgreSQL
            params = [start_date.isoformat(), end_date.isoformat()]
            
            if article_type:
                query += " AND article_type = %s"
                params.append(article_type)
            
            if source:
                query += " AND source = %s"
                params.append(source)
            
            if search_text:
                query += " AND (title ILIKE %s OR summary ILIKE %s OR content ILIKE %s)"
                search_pattern = f"%{search_text}%"
                params.extend([search_pattern, search_pattern, search_pattern])
            
            if embedding_filter is not None:
                if embedding_filter:
                    query += " AND embedding IS NOT NULL"
                else:
                    query += " AND embedding IS NULL"
            
            # Filter by tickers if provided (for owned tickers filter)
            if tickers_filter and self._has_tickers_column:
                # Use PostgreSQL array overlap operator to find articles with any matching ticker
                query += " AND tickers && %s::text[]"
                params.append(list(tickers_filter))
            
            query += " ORDER BY fetched_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            
            results = self.client.execute_query(query, tuple(params))
            
            # Note: RealDictCursor already returns TIMESTAMP columns as datetime objects
            # so no conversion is needed. Just ensure timezone awareness if needed.
            # Normalize ticker data to always use 'tickers' array format
            normalized_results = []
            for article in results:
                article = self._normalize_ticker_data(article)
                if article.get('published_at') and isinstance(article['published_at'], datetime):
                    if article['published_at'].tzinfo is None:
                        article['published_at'] = article['published_at'].replace(tzinfo=timezone.utc)
                if article.get('fetched_at') and isinstance(article['fetched_at'], datetime):
                    if article['fetched_at'].tzinfo is None:
                        article['fetched_at'] = article['fetched_at'].replace(tzinfo=timezone.utc)
                normalized_results.append(article)
            
            logger.debug(f"Retrieved {len(normalized_results)} articles for date range")
            return normalized_results
            
        except Exception as e:
            logger.error(f"❌ Error getting articles by date range: {e}")
            return []
    
    def get_all_articles(
        self,
        article_type: Optional[str] = None,
        source: Optional[str] = None,
        search_text: Optional[str] = None,
        embedding_filter: Optional[bool] = None,
        tickers_filter: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get all articles without date filtering
        
        Args:
            article_type: Optional filter by article type
            source: Optional filter by source
            search_text: Optional text search in title, summary, content
            embedding_filter: Optional filter by embedding status (True=has embedding, False=no embedding, None=all)
            tickers_filter: Optional list of tickers to filter by (articles must have at least one matching ticker)
            limit: Maximum number of results
            offset: Number of results to skip
            
        Returns:
            List of article dictionaries
        """
        try:
            # Select appropriate ticker column based on schema version
            ticker_column = "tickers" if self._has_tickers_column else "ticker"
            query = f"""
                SELECT id, {ticker_column}, sector, article_type, title, url, summary, content,
                       source, published_at, fetched_at, relevance_score, fund,
                       archive_url, archive_submitted_at, archive_checked_at,
                       (embedding IS NOT NULL) as has_embedding
                FROM research_articles
                WHERE 1=1
            """
            params = []
            
            if article_type:
                query += " AND article_type = %s"
                params.append(article_type)
            
            if source:
                query += " AND source = %s"
                params.append(source)
            
            if search_text:
                query += " AND (title ILIKE %s OR summary ILIKE %s OR content ILIKE %s)"
                search_pattern = f"%{search_text}%"
                params.extend([search_pattern, search_pattern, search_pattern])
            
            if embedding_filter is not None:
                if embedding_filter:
                    query += " AND embedding IS NOT NULL"
                else:
                    query += " AND embedding IS NULL"
            
            # Filter by tickers if provided (for owned tickers filter)
            if tickers_filter and self._has_tickers_column:
                # Use PostgreSQL array overlap operator to find articles with any matching ticker
                query += " AND tickers && %s::text[]"
                params.append(list(tickers_filter))
            
            query += " ORDER BY fetched_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            
            results = self.client.execute_query(query, tuple(params))
            
            # Note: RealDictCursor already returns TIMESTAMP columns as datetime objects
            # so no conversion is needed. Just ensure timezone awareness if needed.
            # Normalize ticker data to always use 'tickers' array format (same as get_articles_by_date_range)
            normalized_results = []
            for article in results:
                article = self._normalize_ticker_data(article)
                if article.get('published_at') and isinstance(article['published_at'], datetime):
                    if article['published_at'].tzinfo is None:
                        article['published_at'] = article['published_at'].replace(tzinfo=timezone.utc)
                if article.get('fetched_at') and isinstance(article['fetched_at'], datetime):
                    if article['fetched_at'].tzinfo is None:
                        article['fetched_at'] = article['fetched_at'].replace(tzinfo=timezone.utc)
                normalized_results.append(article)
            
            logger.debug(f"Retrieved {len(normalized_results)} articles (all time)")
            return normalized_results
            
        except Exception as e:
            logger.error(f"❌ Error getting all articles: {e}")
            return []
    
    def get_article_count(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        article_type: Optional[str] = None,
        source: Optional[str] = None,
        search_text: Optional[str] = None,
        embedding_filter: Optional[bool] = None,
        tickers_filter: Optional[List[str]] = None
    ) -> int:
        """Get total count of articles matching the given filters
        
        Args:
            start_date: Optional start date (inclusive)
            end_date: Optional end date (inclusive)
            article_type: Optional filter by article type
            source: Optional filter by source
            search_text: Optional text search in title, summary, content
            embedding_filter: Optional filter by embedding status (True=has embedding, False=no embedding, None=all)
            tickers_filter: Optional list of tickers to filter by (articles must have at least one matching ticker)
            
        Returns:
            Total count of matching articles
        """
        try:
            query = "SELECT COUNT(*) as count FROM research_articles WHERE 1=1"
            params = []
            
            # Date range filter
            if start_date and end_date:
                # Ensure timezone-aware datetimes
                if start_date.tzinfo is None:
                    start_date = start_date.replace(tzinfo=timezone.utc)
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=timezone.utc)
                
                query += " AND fetched_at >= %s AND fetched_at <= %s"
                params.extend([start_date.isoformat(), end_date.isoformat()])
            
            # Article type filter
            if article_type:
                query += " AND article_type = %s"
                params.append(article_type)
            
            # Source filter
            if source:
                query += " AND source = %s"
                params.append(source)
            
            # Search text filter
            if search_text:
                query += " AND (title ILIKE %s OR summary ILIKE %s OR content ILIKE %s)"
                search_pattern = f"%{search_text}%"
                params.extend([search_pattern, search_pattern, search_pattern])
            
            # Embedding filter
            if embedding_filter is not None:
                if embedding_filter:
                    query += " AND embedding IS NOT NULL"
                else:
                    query += " AND embedding IS NULL"
            
            # Tickers filter
            if tickers_filter and self._has_tickers_column:
                query += " AND tickers && %s::text[]"
                params.append(list(tickers_filter))
            
            results = self.client.execute_query(query, tuple(params))
            count = results[0]['count'] if results else 0
            
            logger.debug(f"Article count: {count}")
            return count
            
        except Exception as e:
            logger.error(f"❌ Error getting article count: {e}")
            return 0
    
    def search_ticker_analyses(self, query_embedding: List[float], limit: int = 10) -> List[Dict[str, Any]]:
        """Search ticker analyses by semantic similarity.
        
        Args:
            query_embedding: Query vector embedding (list of 768 floats)
            limit: Maximum number of results
            
        Returns:
            List of ticker analysis dictionaries with similarity scores
        """
        try:
            if not query_embedding or len(query_embedding) != 768:
                logger.warning("Invalid embedding dimensions for ticker analysis search")
                return []
            
            # Convert to PostgreSQL vector format
            embedding_str = "[" + ",".join(str(float(x)) for x in query_embedding) + "]"
            
            query = """
                SELECT 
                    ticker, analysis_type, analysis_date, data_start_date, data_end_date,
                    sentiment, sentiment_score, confidence_score, themes, summary,
                    analysis_text, reasoning,
                    etf_changes_count, congress_trades_count, research_articles_count,
                    created_at, updated_at, model_used,
                    1 - (embedding <=> %s::vector) as similarity
                FROM ticker_analysis
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """
            
            results = self.client.execute_query(query, (embedding_str, embedding_str, limit))
            
            # Process datetime fields
            for result in results:
                if result.get('analysis_date'):
                    result['analysis_date'] = self._parse_datetime(result['analysis_date'])
                if result.get('data_start_date'):
                    result['data_start_date'] = self._parse_datetime(result['data_start_date'])
                if result.get('data_end_date'):
                    result['data_end_date'] = self._parse_datetime(result['data_end_date'])
                if result.get('created_at'):
                    result['created_at'] = self._parse_datetime(result['created_at'])
                if result.get('updated_at'):
                    result['updated_at'] = self._parse_datetime(result['updated_at'])
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Error searching ticker analyses: {e}")
            return []
    
    def get_latest_ticker_analysis(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get most recent analysis for a ticker.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Latest ticker analysis dictionary or None
        """
        try:
            query = """
                SELECT * FROM ticker_analysis
                WHERE ticker = %s
                ORDER BY analysis_date DESC, updated_at DESC
                LIMIT 1
            """
            
            results = self.client.execute_query(query, (ticker.upper(),))
            
            if results:
                result = results[0]
                # Process datetime fields
                if result.get('analysis_date'):
                    result['analysis_date'] = self._parse_datetime(result['analysis_date'])
                if result.get('data_start_date'):
                    result['data_start_date'] = self._parse_datetime(result['data_start_date'])
                if result.get('data_end_date'):
                    result['data_end_date'] = self._parse_datetime(result['data_end_date'])
                if result.get('created_at'):
                    result['created_at'] = self._parse_datetime(result['created_at'])
                if result.get('updated_at'):
                    result['updated_at'] = self._parse_datetime(result['updated_at'])
                return result
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Error getting latest ticker analysis for {ticker}: {e}")
            return None
    
    def _parse_datetime(self, dt_value: Any) -> Optional[datetime]:
        """Parse datetime value from database result."""
        if not dt_value:
            return None
        if isinstance(dt_value, datetime):
            return dt_value
        if isinstance(dt_value, str):
            try:
                return datetime.fromisoformat(dt_value.replace('Z', '+00:00'))
            except:
                return None
        return None
