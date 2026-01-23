#!/usr/bin/env python3
"""
ETF Group Analysis Service
==========================

Analyzes ETF holdings changes as a group for one date.
Generates research articles with AI analysis.
"""

import json
import re
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone

from supabase_client import SupabaseClient
from ollama_client import OllamaClient
from research_repository import ResearchRepository
from settings import get_summarizing_model

# ETF Names (copied from scheduler.jobs_etf_watchtower to avoid circular import)
ETF_NAMES = {
    "ARKK": "ARK Innovation ETF",
    "ARKQ": "ARK Autonomous Technology & Robotics ETF",
    "ARKW": "ARK Next Generation Internet ETF",
    "ARKG": "ARK Genomic Revolution ETF",
    "ARKF": "ARK Fintech Innovation ETF",
    "ARKX": "ARK Space Exploration & Innovation ETF",
    "IZRL": "ARK Israel Innovative Technology ETF",
    "PRNT": "The 3D Printing ETF",
    "IVV": "iShares Core S&P 500 ETF",
    "IWM": "iShares Russell 2000 ETF",
    "IWC": "iShares Micro-Cap ETF",
    "IWO": "iShares Russell 2000 Growth ETF",
}

logger = logging.getLogger(__name__)

# Helper to extract JSON from text (handles models that return extra text)
def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract first JSON block found in text using regex."""
    try:
        # First, try direct parse
        return json.loads(text.strip())
    except json.JSONDecodeError:
        try:
            # Find the first { and last }
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except:
            pass
    return None

class ETFGroupAnalysisService:
    """Analyze ETF holdings changes as a group for one date."""
    
    MAX_CHANGES_PER_PROMPT = 200  # Limit context size
    
    def __init__(self, ollama: OllamaClient, supabase: SupabaseClient, repo: ResearchRepository):
        """Initialize ETF group analysis service.
        
        Args:
            ollama: Ollama client for LLM analysis
            supabase: Supabase client for querying changes
            repo: Research repository for saving articles
        """
        self.ollama = ollama
        self.supabase = supabase
        self.repo = repo
    
    def get_changes_for_date(self, etf_ticker: str, date: datetime) -> List[Dict]:
        """Query the view to get changes for a specific ETF/date.
        
        Args:
            etf_ticker: ETF ticker symbol
            date: Date to analyze
            
        Returns:
            List of change dictionaries
        """
        try:
            date_str = date.strftime('%Y-%m-%d')
            result = self.supabase.supabase.from_('etf_holdings_changes') \
                .select('*') \
                .eq('etf_ticker', etf_ticker) \
                .eq('date', date_str) \
                .execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Error querying ETF changes for {etf_ticker} on {date_str}: {e}")
            return []
    
    def format_changes_for_llm(self, changes: List[Dict]) -> str:
        """Format changes as a table for LLM input.
        
        Args:
            changes: List of change dictionaries
            
        Returns:
            Formatted string table
        """
        if not changes:
            return "No changes found."
        
        # Sort by absolute share_change (descending) and truncate
        sorted_changes = sorted(changes, key=lambda x: abs(x.get('share_change', 0)), reverse=True)
        truncated = sorted_changes[:self.MAX_CHANGES_PER_PROMPT]
        
        lines = ["| Ticker | Action | Shares Changed | % Change |"]
        lines.append("|--------|--------|----------------|----------|")
        for c in truncated:
            ticker = c.get('holding_ticker', 'N/A')
            action = c.get('action', 'N/A')
            share_change = c.get('share_change', 0)
            percent_change = c.get('percent_change', 0)
            lines.append(f"| {ticker} | {action} | {share_change:,} | {percent_change:.1f}% |")
        
        if len(changes) > len(truncated):
            lines.append(f"\n*({len(changes) - len(truncated)} smaller changes omitted)*")
        
        return "\n".join(lines)
    
    def analyze_group(self, etf_ticker: str, date: datetime) -> Optional[Dict]:
        """Analyze all changes for an ETF on a date.
        
        Args:
            etf_ticker: ETF ticker symbol
            date: Date to analyze
            
        Returns:
            Analysis dictionary with sentiment, themes, etc., or None if no changes
        """
        changes = self.get_changes_for_date(etf_ticker, date)
        if not changes:
            logger.info(f"No changes found for {etf_ticker} on {date.strftime('%Y-%m-%d')}")
            return None
        
        logger.info(f"Analyzing {len(changes)} changes for {etf_ticker} on {date.strftime('%Y-%m-%d')}")
        
        # Format changes for LLM
        changes_table = self.format_changes_for_llm(changes)
        
        # Get prompt from ai_prompts
        try:
            from ai_prompts import ETF_GROUP_ANALYSIS_PROMPT
            prompt = ETF_GROUP_ANALYSIS_PROMPT.format(
                etf_ticker=etf_ticker,
                etf_name=ETF_NAMES.get(etf_ticker, etf_ticker),
                date=date.strftime('%Y-%m-%d'),
                change_count=len(changes),
                changes_table=changes_table
            )
        except ImportError:
            logger.error("ETF_GROUP_ANALYSIS_PROMPT not found in ai_prompts.py")
            return None
        
        # Analyze with LLM
        model = get_summarizing_model()
        system_prompt = "You are a financial analyst. Return ONLY valid JSON with the exact fields specified."
        
        try:
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
                logger.error(f"Failed to parse JSON response for {etf_ticker}")
                return None
            
            # Save as research article
            article_id = self.repo.save_article(
                title=f"{etf_ticker} Holdings Analysis - {date.strftime('%Y-%m-%d')}",
                url=f"etf-analysis://{etf_ticker}/{date.strftime('%Y-%m-%d')}",  # Unique URL
                content=response.get('analysis', ''),
                summary=response.get('summary', ''),
                source="ETF AI Analysis",
                article_type="ETF Analysis",
                tickers=[c.get('holding_ticker') for c in changes[:10] if c.get('holding_ticker')],
                sentiment=response.get('sentiment'),
                sentiment_score=response.get('sentiment_score'),
                published_at=date.replace(tzinfo=timezone.utc)
            )
            
            if article_id:
                logger.info(f"Saved ETF analysis article for {etf_ticker} on {date.strftime('%Y-%m-%d')}")
            else:
                logger.warning(f"Failed to save article for {etf_ticker}")
            
            return response
            
        except Exception as e:
            logger.error(f"Error analyzing ETF group {etf_ticker} on {date.strftime('%Y-%m-%d')}: {e}", exc_info=True)
            return None
