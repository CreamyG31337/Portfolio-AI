#!/usr/bin/env python3
"""
Ticker Analysis Service
=======================

Analyzes individual tickers with 3 months of multi-source data:
- ETF changes (all ETFs that held this ticker)
- Congress trades
- Signals (technical analysis)
- Fundamentals
- Research articles
- Social sentiment

Formats data like AI context builder and sends to LLM for analysis.
"""

import json
import re
import logging
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timedelta, timezone
import pandas as pd

from supabase_client import SupabaseClient
from postgres_client import PostgresClient
from ollama_client import OllamaClient
from ai_skip_list_manager import AISkipListManager
from ai_context_builder import (
    format_fundamentals_table,
    format_trades
)
from settings import get_summarizing_model

logger = logging.getLogger(__name__)

# Helper to extract JSON from text
def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract first JSON block found in text using regex."""
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except:
            pass
    return None

class TickerAnalysisService:
    """Analyze a ticker with 3 months of multi-source data."""
    
    LOOKBACK_DAYS = 90
    MAX_ETF_CHANGES = 50
    MAX_CONGRESS_TRADES = 30
    MAX_RESEARCH_ARTICLES = 10
    SKIP_IF_ANALYZED_WITHIN_HOURS = 24
    
    def __init__(self, ollama: OllamaClient, supabase: SupabaseClient, postgres: PostgresClient, skip_list: AISkipListManager):
        """Initialize ticker analysis service.
        
        Args:
            ollama: Ollama client for LLM analysis
            supabase: Supabase client for querying data
            postgres: Postgres client for Research DB queries
            skip_list: Skip list manager
        """
        self.ollama = ollama
        self.supabase = supabase
        self.postgres = postgres
        self.skip_list = skip_list
    
    def _recently_analyzed(self, ticker: str) -> bool:
        """Check if ticker was analyzed within SKIP_IF_ANALYZED_WITHIN_HOURS.
        
        Args:
            ticker: Ticker symbol to check
            
        Returns:
            True if recently analyzed, False otherwise
        """
        try:
            result = self.postgres.execute_query("""
                SELECT 1 FROM ticker_analysis 
                WHERE ticker = %s 
                AND updated_at > NOW() - INTERVAL '%s hours'
                LIMIT 1
            """, (ticker.upper(), self.SKIP_IF_ANALYZED_WITHIN_HOURS))
            return len(result) > 0
        except Exception as e:
            logger.warning(f"Error checking recent analysis for {ticker}: {e}")
            return False
    
    def _get_fundamentals(self, ticker: str) -> Optional[Dict]:
        """Get fundamentals from securities table.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Fundamentals dict or None
        """
        try:
            result = self.supabase.supabase.table('securities') \
                .select('*') \
                .eq('ticker', ticker.upper()) \
                .execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning(f"Error fetching fundamentals for {ticker}: {e}")
            return None
    
    def _get_etf_changes(self, ticker: str, start_date: datetime) -> List[Dict]:
        """Get ETF changes for this ticker (all ETFs that held it).
        
        Args:
            ticker: Ticker symbol
            start_date: Start of lookback period
            
        Returns:
            List of ETF change dictionaries
        """
        try:
            start_str = start_date.strftime('%Y-%m-%d')
            result = self.supabase.supabase.from_('etf_holdings_changes') \
                .select('*') \
                .eq('holding_ticker', ticker.upper()) \
                .gte('date', start_str) \
                .order('date', desc=True) \
                .limit(self.MAX_ETF_CHANGES) \
                .execute()
            return result.data or []
        except Exception as e:
            logger.warning(f"Error fetching ETF changes for {ticker}: {e}")
            return []
    
    def _get_congress_trades(self, ticker: str, start_date: datetime) -> List[Dict]:
        """Get congress trades for this ticker.
        
        Args:
            ticker: Ticker symbol
            start_date: Start of lookback period
            
        Returns:
            List of congress trade dictionaries
        """
        try:
            start_str = start_date.strftime('%Y-%m-%d')
            result = self.supabase.supabase.table('congress_trades_enriched') \
                .select('*') \
                .eq('ticker', ticker.upper()) \
                .gte('transaction_date', start_str) \
                .order('transaction_date', desc=True) \
                .limit(self.MAX_CONGRESS_TRADES) \
                .execute()
            return result.data or []
        except Exception as e:
            logger.warning(f"Error fetching congress trades for {ticker}: {e}")
            return []
    
    def _get_latest_signals(self, ticker: str) -> Optional[Dict]:
        """Get latest signals for this ticker.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Signals dict or None
        """
        try:
            # Get latest signal from signal_analysis table
            result = self.supabase.supabase.table('signal_analysis') \
                .select('*') \
                .eq('ticker', ticker.upper()) \
                .order('analysis_date', desc=True) \
                .limit(1) \
                .execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning(f"Error fetching signals for {ticker}: {e}")
            return None
    
    def _get_research_articles(self, ticker: str, start_date: datetime) -> List[Dict]:
        """Get research articles for this ticker.
        
        Args:
            ticker: Ticker symbol
            start_date: Start of lookback period
            
        Returns:
            List of article dictionaries
        """
        try:
            start_str = start_date.isoformat()
            result = self.postgres.execute_query("""
                SELECT id, title, url, summary, source, published_at, fetched_at,
                       relevance_score, sentiment, sentiment_score, article_type
                FROM research_articles
                WHERE tickers @> ARRAY[%s]::text[]
                   OR ticker = %s
                AND fetched_at >= %s
                ORDER BY fetched_at DESC
                LIMIT %s
            """, (ticker.upper(), ticker.upper(), start_str, self.MAX_RESEARCH_ARTICLES))
            return result or []
        except Exception as e:
            logger.warning(f"Error fetching research articles for {ticker}: {e}")
            return []
    
    def _get_social_sentiment(self, ticker: str, start_date: datetime) -> Dict:
        """Get social sentiment for this ticker.
        
        Args:
            ticker: Ticker symbol
            start_date: Start of lookback period
            
        Returns:
            Dict with latest_metrics and alerts
        """
        try:
            start_str = start_date.isoformat()
            # Latest metrics per platform
            latest = self.postgres.execute_query("""
                SELECT DISTINCT ON (platform)
                    ticker, platform, volume, sentiment_label, sentiment_score,
                    bull_bear_ratio, created_at
                FROM social_metrics
                WHERE ticker = %s
                ORDER BY platform, created_at DESC
                LIMIT 10
            """, (ticker.upper(),))
            
            # Extreme alerts (last 24 hours)
            alerts = self.postgres.execute_query("""
                SELECT DISTINCT ON (platform, sentiment_label)
                    ticker, platform, sentiment_label, sentiment_score, created_at
                FROM social_metrics
                WHERE ticker = %s
                  AND sentiment_label IN ('EUPHORIC', 'FEARFUL', 'BULLISH')
                  AND created_at > NOW() - INTERVAL '24 hours'
                ORDER BY platform, sentiment_label, created_at DESC
                LIMIT 10
            """, (ticker.upper(),))
            
            return {
                'latest_metrics': latest or [],
                'alerts': alerts or []
            }
        except Exception as e:
            logger.warning(f"Error fetching social sentiment for {ticker}: {e}")
            return {'latest_metrics': [], 'alerts': []}
    
    def gather_ticker_data(self, ticker: str) -> Dict:
        """Gather 3 months of data from all sources.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Dict with all data sources
        """
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=self.LOOKBACK_DAYS)
        
        logger.info(f"Gathering data for {ticker} (last {self.LOOKBACK_DAYS} days)")
        
        return {
            'ticker': ticker.upper(),
            'start_date': start_date,
            'end_date': end_date,
            'fundamentals': self._get_fundamentals(ticker),
            'etf_changes': self._get_etf_changes(ticker, start_date),
            'congress_trades': self._get_congress_trades(ticker, start_date),
            'signals': self._get_latest_signals(ticker),
            'research_articles': self._get_research_articles(ticker, start_date),
            'social_sentiment': self._get_social_sentiment(ticker, start_date),
        }
    
    def _format_etf_changes(self, changes: List[Dict]) -> str:
        """Format ETF changes as table.
        
        Args:
            changes: List of ETF change dictionaries
            
        Returns:
            Formatted string
        """
        if not changes:
            return ""
        
        lines = [
            "[ ETF Holdings Changes (Last 3 Months) ]",
            "Date       | ETF  | Action | Shares Changed | % Change",
            "-----------|------|--------|----------------|----------"
        ]
        
        for c in changes[:self.MAX_ETF_CHANGES]:
            date = c.get('date', 'N/A')
            etf = c.get('etf_ticker', 'N/A')
            action = c.get('action', 'N/A')
            share_change = c.get('share_change', 0)
            percent_change = c.get('percent_change', 0)
            lines.append(f"{date} | {etf:4} | {action:6} | {share_change:15,} | {percent_change:8.1f}%")
        
        return "\n".join(lines)
    
    def _format_congress_trades(self, trades: List[Dict]) -> str:
        """Format congress trades as table.
        
        Args:
            trades: List of congress trade dictionaries
            
        Returns:
            Formatted string
        """
        if not trades:
            return ""
        
        lines = [
            "[ Congressional Trading Activity (Last 3 Months) ]",
            "Date       | Politician        | Type     | Amount",
            "-----------|-------------------|----------|----------"
        ]
        
        for t in trades[:self.MAX_CONGRESS_TRADES]:
            date = t.get('transaction_date', 'N/A')
            politician = t.get('politician', t.get('name', 'N/A'))[:17]
            trade_type = t.get('type', 'N/A')
            amount = t.get('amount', 'N/A')
            lines.append(f"{date} | {politician:17} | {trade_type:8} | {amount}")
        
        return "\n".join(lines)
    
    def _format_signals(self, signals: Optional[Dict]) -> str:
        """Format signals data.
        
        Args:
            signals: Signals dictionary or None
            
        Returns:
            Formatted string
        """
        if not signals:
            return ""
        
        lines = ["[ Technical Signals ]"]
        
        overall = signals.get('overall_signal', 'N/A')
        confidence = signals.get('confidence', 0)
        structure = signals.get('structure', {})
        timing = signals.get('timing', {})
        fear = signals.get('fear', {})
        
        lines.append(f"Overall Signal: {overall} (Confidence: {confidence:.0%})")
        lines.append(f"Structure - Trend: {structure.get('trend', 'N/A')}, Pullback: {structure.get('pullback', 'N/A')}, Breakout: {structure.get('breakout', 'N/A')}")
        lines.append(f"Timing - Entry: {timing.get('entry', 'N/A')}, Exit: {timing.get('exit', 'N/A')}")
        lines.append(f"Fear Level: {fear.get('level', 'N/A')}")
        
        return "\n".join(lines)
    
    def _format_articles(self, articles: List[Dict]) -> str:
        """Format research articles.
        
        Args:
            articles: List of article dictionaries
            
        Returns:
            Formatted string
        """
        if not articles:
            return ""
        
        lines = [
            f"[ Research Articles (Last 3 Months) - {len(articles)} articles ]",
            "Title                                    | Source          | Date       | Sentiment",
            "----------------------------------------|-----------------|------------|----------"
        ]
        
        for a in articles[:self.MAX_RESEARCH_ARTICLES]:
            title = (a.get('title', 'N/A') or 'N/A')[:38]
            source = (a.get('source', 'N/A') or 'N/A')[:15]
            date = str(a.get('published_at', a.get('fetched_at', 'N/A')))[:10]
            sentiment = a.get('sentiment', 'N/A') or 'N/A'
            lines.append(f"{title:38} | {source:15} | {date} | {sentiment}")
        
        return "\n".join(lines)
    
    def _format_social_sentiment(self, sentiment: Dict) -> str:
        """Format social sentiment data.
        
        Args:
            sentiment: Sentiment dict with latest_metrics and alerts
            
        Returns:
            Formatted string
        """
        if not sentiment or (not sentiment.get('latest_metrics') and not sentiment.get('alerts')):
            return ""
        
        lines = ["[ Social Sentiment ]"]
        
        metrics = sentiment.get('latest_metrics', [])
        if metrics:
            lines.append("Latest Metrics:")
            for m in metrics[:5]:
                platform = m.get('platform', 'N/A')
                label = m.get('sentiment_label', 'N/A')
                score = m.get('sentiment_score', 0)
                lines.append(f"  {platform}: {label} (score: {score:.2f})")
        
        alerts = sentiment.get('alerts', [])
        if alerts:
            lines.append("\nRecent Alerts (24h):")
            for a in alerts[:5]:
                platform = a.get('platform', 'N/A')
                label = a.get('sentiment_label', 'N/A')
                lines.append(f"  {platform}: {label}")
        
        return "\n".join(lines)
    
    def format_ticker_context(self, data: Dict) -> str:
        """Format all data sources into LLM-friendly text.
        
        Args:
            data: Dict with all ticker data sources
            
        Returns:
            Formatted context string
        """
        sections = []
        
        # Fundamentals
        if data.get('fundamentals'):
            # Format fundamentals manually (format_fundamentals_table expects positions DataFrame)
            fund = data['fundamentals']
            lines = [
                "[ Company Fundamentals ]",
                "Ticker     | Sector               | Industry                  | Country  | Mkt Cap      | P/E    | Div %  | 52W High   | 52W Low",
                "-----------|---------------------|---------------------------|----------|--------------|--------|--------|------------|----------"
            ]
            ticker = data['ticker']
            sector = fund.get('sector', 'N/A') or 'N/A'
            industry = fund.get('industry', 'N/A') or 'N/A'
            country = fund.get('country', 'N/A') or 'N/A'
            market_cap = fund.get('market_cap', 'N/A') or 'N/A'
            pe_ratio = fund.get('pe_ratio', 'N/A') or 'N/A'
            dividend_yield = fund.get('dividend_yield', 'N/A') or 'N/A'
            high_52w = fund.get('high_52w', 'N/A') or 'N/A'
            low_52w = fund.get('low_52w', 'N/A') or 'N/A'
            
            lines.append(f"{ticker:10} | {sector:19} | {industry:25} | {country:8} | {market_cap:12} | {pe_ratio:6} | {dividend_yield:6} | {high_52w:10} | {low_52w:10}")
            sections.append("\n".join(lines))
        
        # ETF changes
        if data.get('etf_changes'):
            sections.append(self._format_etf_changes(data['etf_changes']))
        
        # Congress trades
        if data.get('congress_trades'):
            sections.append(self._format_congress_trades(data['congress_trades']))
        
        # Signals
        if data.get('signals'):
            sections.append(self._format_signals(data['signals']))
        
        # Research articles
        if data.get('research_articles'):
            sections.append(self._format_articles(data['research_articles']))
        
        # Social sentiment
        if data.get('social_sentiment'):
            sentiment_text = self._format_social_sentiment(data['social_sentiment'])
            if sentiment_text:
                sections.append(sentiment_text)
        
        return "\n\n---\n\n".join(sections) if sections else "No data available for this ticker."
    
    def analyze_ticker(self, ticker: str, requested_by: Optional[str] = None) -> Optional[Dict]:
        """Run full analysis on a ticker.
        
        Args:
            ticker: Ticker symbol to analyze
            requested_by: User email who requested (None = scheduled)
            
        Returns:
            Analysis dictionary or None on failure
        """
        ticker_upper = ticker.upper().strip()
        
        try:
            # Gather all data
            data = self.gather_ticker_data(ticker_upper)
            
            # Format context
            context = self.format_ticker_context(data)
            
            # Get prompt
            try:
                from ai_prompts import TICKER_ANALYSIS_PROMPT
                prompt = TICKER_ANALYSIS_PROMPT.format(ticker=ticker_upper, context=context)
            except ImportError:
                logger.error("TICKER_ANALYSIS_PROMPT not found in ai_prompts.py")
                return None
            
            # Analyze with LLM
            model = get_summarizing_model()
            system_prompt = "You are a financial analyst. Return ONLY valid JSON with the exact fields specified."
            
            full_response = ""
            for chunk in self.ollama.query_ollama(
                prompt=prompt,
                model=model,
                stream=True,
                system_prompt=system_prompt,
                json_mode=True,
                temperature=0.1
            ):
                full_response += chunk
            
            # Parse JSON
            response = extract_json(full_response)
            if not response:
                logger.error(f"Failed to parse JSON response for {ticker_upper}")
                return None
            
            # Save analysis
            self._save_analysis(ticker_upper, data, context, response, requested_by)
            
            return response
            
        except Exception as e:
            logger.error(f"Error analyzing ticker {ticker_upper}: {e}", exc_info=True)
            # Record failure in skip list
            self.skip_list.record_failure(ticker_upper, str(e))
            raise
    
    def _save_analysis(self, ticker: str, data: Dict, context: str, response: Dict, requested_by: Optional[str]):
        """Save analysis to ticker_analysis table.
        
        Args:
            ticker: Ticker symbol
            data: Data dict (for counts)
            context: Input context string (for debug panel)
            response: LLM response dict
            requested_by: User email or None
        """
        try:
            analysis_date = datetime.now(timezone.utc).date()
            start_date = data['start_date'].date()
            end_date = data['end_date'].date()
            
            # Generate embedding
            embedding = None
            summary_text = response.get('summary', '') or response.get('analysis_text', '')
            if summary_text:
                try:
                    embedding_list = self.ollama.generate_embedding(summary_text)
                    if embedding_list:
                        embedding = "[" + ",".join(str(float(x)) for x in embedding_list) + "]"
                except Exception as e:
                    logger.warning(f"Failed to generate embedding for {ticker}: {e}")
            
            # Prepare data counts
            etf_count = len(data.get('etf_changes', []))
            congress_count = len(data.get('congress_trades', []))
            articles_count = len(data.get('research_articles', []))
            
            # Insert or update
            query = """
                INSERT INTO ticker_analysis (
                    ticker, analysis_type, analysis_date, data_start_date, data_end_date,
                    sentiment, sentiment_score, confidence_score, themes, summary,
                    analysis_text, reasoning, input_context,
                    etf_changes_count, congress_trades_count, research_articles_count,
                    embedding, model_used, requested_by
                ) VALUES (
                    %s, 'standard', %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s::vector, %s, %s
                )
                ON CONFLICT (ticker, analysis_type, analysis_date)
                DO UPDATE SET
                    sentiment = EXCLUDED.sentiment,
                    sentiment_score = EXCLUDED.sentiment_score,
                    confidence_score = EXCLUDED.confidence_score,
                    themes = EXCLUDED.themes,
                    summary = EXCLUDED.summary,
                    analysis_text = EXCLUDED.analysis_text,
                    reasoning = EXCLUDED.reasoning,
                    input_context = EXCLUDED.input_context,
                    etf_changes_count = EXCLUDED.etf_changes_count,
                    congress_trades_count = EXCLUDED.congress_trades_count,
                    research_articles_count = EXCLUDED.research_articles_count,
                    embedding = EXCLUDED.embedding,
                    updated_at = NOW(),
                    requested_by = EXCLUDED.requested_by
            """
            
            self.postgres.execute_update(query, (
                ticker,
                analysis_date,
                start_date,
                end_date,
                response.get('sentiment'),
                response.get('sentiment_score'),
                response.get('confidence_score'),
                response.get('themes', []),
                response.get('summary'),
                response.get('analysis_text'),
                response.get('reasoning'),
                context,  # input_context for debug panel
                etf_count,
                congress_count,
                articles_count,
                embedding,
                get_summarizing_model(),
                requested_by
            ))
            
            logger.info(f"Saved ticker analysis for {ticker}")
            
        except Exception as e:
            logger.error(f"Error saving analysis for {ticker}: {e}", exc_info=True)
            raise
    
    def get_tickers_to_analyze(self) -> List[Tuple[str, int]]:
        """Get prioritized list of tickers needing analysis.
        
        Returns:
            List of (ticker, priority) tuples.
            Priority: manual=1000, holdings=100, watched=10
        """
        tickers = []
        
        # 1. Manual requests (highest priority) - from queue
        try:
            manual_result = self.supabase.supabase.table('ai_analysis_queue') \
                .select('target_key') \
                .eq('analysis_type', 'ticker') \
                .eq('status', 'pending') \
                .gte('priority', 1000) \
                .execute()
            manual_tickers = [row['target_key'] for row in manual_result.data or []]
            tickers.extend([(t, 1000) for t in manual_tickers])
        except Exception as e:
            logger.warning(f"Error fetching manual requests: {e}")
        
        # 2. Holdings (high priority) - all funds
        try:
            holdings_result = self.supabase.supabase.table('portfolio_positions') \
                .select('ticker') \
                .execute()
            holdings_tickers = list(set([row['ticker'] for row in holdings_result.data or [] if row.get('ticker')]))
            tickers.extend([(t, 100) for t in holdings_tickers if t not in [x[0] for x in tickers]])
        except Exception as e:
            logger.warning(f"Error fetching holdings: {e}")
        
        # 3. Watched tickers (lower priority)
        try:
            watched_result = self.supabase.supabase.table('watched_tickers') \
                .select('ticker') \
                .eq('is_active', True) \
                .execute()
            watched_tickers = [row['ticker'] for row in watched_result.data or [] if row.get('ticker')]
            tickers.extend([(t, 10) for t in watched_tickers if t not in [x[0] for x in tickers]])
        except Exception as e:
            logger.warning(f"Error fetching watched tickers: {e}")
        
        # Filter out skip list and recently analyzed
        filtered = []
        for ticker, priority in tickers:
            if not self.skip_list.should_skip(ticker) and not self._recently_analyzed(ticker):
                filtered.append((ticker, priority))
        
        # Sort by priority descending
        return sorted(filtered, key=lambda x: -x[1])
