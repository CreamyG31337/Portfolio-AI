#!/usr/bin/env python3
"""
AI Skip List Manager
====================

Manages tickers that should be skipped during AI analysis.
Tracks failed tickers and provides admin visibility.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

class AISkipListManager:
    """Manage tickers that should be skipped during analysis."""
    
    MAX_FAILURES_BEFORE_SKIP = 3
    
    def __init__(self, supabase: SupabaseClient):
        """Initialize skip list manager.
        
        Args:
            supabase: Supabase client instance
        """
        self.supabase = supabase
        self._cache = {}  # In-memory cache: {ticker: should_skip}
    
    def should_skip(self, ticker: str) -> bool:
        """Check if ticker should be skipped.
        
        Args:
            ticker: Ticker symbol to check
            
        Returns:
            True if ticker should be skipped, False otherwise
        """
        ticker_upper = ticker.upper().strip()
        
        # Check cache first
        if ticker_upper in self._cache:
            return self._cache[ticker_upper]
        
        try:
            result = self.supabase.supabase.table('ai_analysis_skip_list') \
                .select('skip_until') \
                .eq('ticker', ticker_upper) \
                .execute()
            
            if not result.data:
                self._cache[ticker_upper] = False
                return False
            
            skip_until = result.data[0].get('skip_until')
            if skip_until is None:
                # Skip forever
                self._cache[ticker_upper] = True
                return True
            
            # Check if skip period has passed
            try:
                skip_until_dt = datetime.fromisoformat(skip_until.replace('Z', '+00:00'))
                should_skip = datetime.now(timezone.utc) < skip_until_dt
                self._cache[ticker_upper] = should_skip
                return should_skip
            except Exception as e:
                logger.warning(f"Error parsing skip_until for {ticker_upper}: {e}")
                # If we can't parse, assume skip forever
                self._cache[ticker_upper] = True
                return True
                
        except Exception as e:
            logger.error(f"Error checking skip list for {ticker_upper}: {e}")
            # On error, don't skip (allow analysis to proceed)
            return False
    
    def record_failure(self, ticker: str, error: str):
        """Record a failure. Auto-skip after MAX_FAILURES_BEFORE_SKIP failures.
        
        Args:
            ticker: Ticker symbol that failed
            error: Error message
        """
        ticker_upper = ticker.upper().strip()
        
        try:
            # Check if already in skip list
            existing = self.supabase.supabase.table('ai_analysis_skip_list') \
                .select('*') \
                .eq('ticker', ticker_upper) \
                .execute()
            
            now = datetime.now(timezone.utc).isoformat()
            
            if existing.data:
                # Update existing
                current_count = existing.data[0].get('failure_count', 1)
                new_count = current_count + 1
                
                update_data = {
                    'failure_count': new_count,
                    'last_failed_at': now,
                    'reason': error
                }
                
                # Auto-skip after MAX_FAILURES_BEFORE_SKIP
                if new_count >= self.MAX_FAILURES_BEFORE_SKIP:
                    update_data['skip_until'] = None  # Skip forever
                    logger.warning(f"Auto-skipping {ticker_upper} after {new_count} failures")
                
                self.supabase.supabase.table('ai_analysis_skip_list') \
                    .update(update_data) \
                    .eq('ticker', ticker_upper) \
                    .execute()
            else:
                # Create new entry
                self.supabase.supabase.table('ai_analysis_skip_list') \
                    .insert({
                        'ticker': ticker_upper,
                        'reason': error,
                        'failure_count': 1,
                        'first_failed_at': now,
                        'last_failed_at': now,
                        'added_by': 'system'
                    }) \
                    .execute()
            
            # Clear cache
            self._cache.pop(ticker_upper, None)
            
        except Exception as e:
            logger.error(f"Error recording failure for {ticker_upper}: {e}")
    
    def get_skip_list(self) -> List[Dict[str, Any]]:
        """Get all skipped tickers for admin UI.
        
        Returns:
            List of skip list entries
        """
        try:
            result = self.supabase.supabase.table('ai_analysis_skip_list') \
                .select('*') \
                .order('last_failed_at', desc=True) \
                .execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Error fetching skip list: {e}")
            return []
    
    def remove_from_skip_list(self, ticker: str):
        """Remove a ticker from skip list (admin action).
        
        Args:
            ticker: Ticker symbol to remove
        """
        ticker_upper = ticker.upper().strip()
        
        try:
            self.supabase.supabase.table('ai_analysis_skip_list') \
                .delete() \
                .eq('ticker', ticker_upper) \
                .execute()
            
            # Clear cache
            self._cache.pop(ticker_upper, None)
            
            logger.info(f"Removed {ticker_upper} from skip list")
        except Exception as e:
            logger.error(f"Error removing {ticker_upper} from skip list: {e}")
            raise
