#!/usr/bin/env python3
"""
AI Skip List Manager
====================

Manages tickers that should be skipped during AI analysis.
Tracks failed tickers and provides admin visibility.

Skip policy:
- Failures < MAX_FAILURES_BEFORE_SKIP: just record, do not add ``skip_until``.
- Failures >= MAX_FAILURES_BEFORE_SKIP:
    * Permanent markers (delisted, unknown ticker) → ``skip_until = NULL`` (skip forever).
    * Everything else (timeouts, format crashes, JSON parse failures, DB errors) →
      finite ``skip_until`` with exponential backoff so a transient bug cannot
      permanently lock the pipeline.

History: in May 2026 a single ``NoneType.__format__`` crash silently banned 95
tickers forever because the previous policy treated every failure as permanent.
"""

import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta

from supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

PERMANENT_FAILURE_MARKERS: Tuple[str, ...] = (
    "delisted",
    "no such ticker",
    "ticker not found",
    "security not found",
    "symbol not found",
    "invalid ticker",
)


def _classify_failure(error: Optional[str]) -> Tuple[bool, str]:
    """Return ``(is_permanent, classification_label)``.

    Permanent failures are intrinsic to the ticker (e.g. delisted) and warrant a
    forever-skip. Everything else is transient — code/network/data bugs — and
    must get a finite ``skip_until`` so the pipeline self-heals.
    """
    err_lower = (error or "").lower()
    for marker in PERMANENT_FAILURE_MARKERS:
        if marker in err_lower:
            return True, "delisted_or_unknown"
    return False, "transient"


class AISkipListManager:
    """Manage tickers that should be skipped during analysis."""

    MAX_FAILURES_BEFORE_SKIP = 3
    TRANSIENT_SKIP_BASE_HOURS = 24
    TRANSIENT_SKIP_MAX_HOURS = 7 * 24

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
                current_count = existing.data[0].get('failure_count', 1)
                new_count = current_count + 1

                update_data = {
                    'failure_count': new_count,
                    'last_failed_at': now,
                    'reason': error,
                }

                if new_count >= self.MAX_FAILURES_BEFORE_SKIP:
                    is_permanent, classification = _classify_failure(error)
                    if is_permanent:
                        update_data['skip_until'] = None
                        logger.warning(
                            "Permanently skipping %s after %d failures (%s): %s",
                            ticker_upper, new_count, classification, (error or "")[:120],
                        )
                    else:
                        excess = max(0, new_count - self.MAX_FAILURES_BEFORE_SKIP)
                        hours = min(
                            self.TRANSIENT_SKIP_BASE_HOURS * (2 ** excess),
                            self.TRANSIENT_SKIP_MAX_HOURS,
                        )
                        skip_until_dt = datetime.now(timezone.utc) + timedelta(hours=hours)
                        update_data['skip_until'] = skip_until_dt.isoformat()
                        logger.warning(
                            "Transient-skipping %s for %dh after %d failures (%s): %s",
                            ticker_upper, hours, new_count, classification, (error or "")[:120],
                        )

                self.supabase.supabase.table('ai_analysis_skip_list') \
                    .update(update_data) \
                    .eq('ticker', ticker_upper) \
                    .execute()
            else:
                # First failure for this ticker: short transient cooldown so we
                # don't immediately retry, but DON'T permanently ban. Leaving
                # ``skip_until`` unset (NULL) makes ``should_skip`` treat the
                # row as a forever-ban, which is what locked 84 tickers in
                # January 2026 after a single nightly format-string crash.
                first_failure_skip_until = (
                    datetime.now(timezone.utc) + timedelta(hours=1)
                ).isoformat()
                self.supabase.supabase.table('ai_analysis_skip_list') \
                    .insert({
                        'ticker': ticker_upper,
                        'reason': error,
                        'failure_count': 1,
                        'first_failed_at': now,
                        'last_failed_at': now,
                        'skip_until': first_failure_skip_until,
                        'added_by': 'system',
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
    
    def clear_entries_matching(self, reason_substring: str) -> int:
        """Delete skip-list rows whose ``reason`` contains ``reason_substring``.

        Used for triage after a code bug has polluted the skip list (e.g. the
        May 2026 ``NoneType.__format__`` incident).

        Returns the number of rows deleted.
        """
        if not reason_substring:
            return 0
        try:
            existing = (
                self.supabase.supabase.table('ai_analysis_skip_list')
                .select('ticker, reason')
                .ilike('reason', f'%{reason_substring}%')
                .execute()
            )
            tickers = [row['ticker'] for row in (existing.data or [])]
            if not tickers:
                return 0
            self.supabase.supabase.table('ai_analysis_skip_list') \
                .delete() \
                .in_('ticker', tickers) \
                .execute()
            for t in tickers:
                self._cache.pop(t, None)
            logger.info(
                "Cleared %d skip-list entries matching reason substring %r",
                len(tickers), reason_substring,
            )
            return len(tickers)
        except Exception as exc:
            logger.error("Error clearing skip-list entries: %s", exc)
            return 0

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
