#!/usr/bin/env python3
"""
Domain Health Tracking Module
==============================

Tracks domain extraction success/failure rates and manages auto-blacklisting.
"""

import logging
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def normalize_domain(url: str) -> str:
    """Normalize URL to root domain for blacklist matching.
    
    Examples:
        www.msn.com -> msn.com
        finance.yahoo.com -> yahoo.com
        en-us.msn.com -> msn.com
    
    Args:
        url: Full URL or domain
        
    Returns:
        Root domain (e.g., 'msn.com')
    """
    from research_utils import extract_source_from_url
    
    # Get the full hostname
    domain = extract_source_from_url(url)
    
    # Split by dots
    parts = domain.split('.')
    
    # Handle special cases and get root domain
    if len(parts) >= 2:
        # Return last 2 parts as root domain (e.g., msn.com, yahoo.com)
        return '.'.join(parts[-2:])
    
    return domain


class DomainHealthTracker:
    """Tracks domain extraction health and manages auto-blacklisting."""
    
    def __init__(self):
        """Initialize the tracker with database connection."""
        from supabase_client import SupabaseClient
        self.client = SupabaseClient(use_service_role=True)
    
    def record_success(self, url: str) -> None:
        """Record successful extraction, reset consecutive failure counter.
        
        Args:
            url: URL that was successfully extracted
        """
        domain = normalize_domain(url)
        
        try:
            # Check if domain exists
            result = self.client.supabase.table("research_domain_health") \
                .select("domain") \
                .eq("domain", domain) \
                .execute()
            
            now = datetime.now(timezone.utc)
            
            if result.data:
                # Update existing record
                self.client.supabase.table("research_domain_health").update({
                    "total_attempts": self.client.supabase.rpc("increment", {"x": 1}),
                    "total_successes": self.client.supabase.rpc("increment", {"x": 1}),
                    "consecutive_failures": 0,  # Reset counter
                    "last_success_at": now.isoformat(),
                    "last_attempt_at": now.isoformat(),
                    "updated_at": now.isoformat()
                }).eq("domain", domain).execute()
            else:
                # Insert new record
                self.client.supabase.table("research_domain_health").insert({
                    "domain": domain,
                    "total_attempts": 1,
                    "total_successes": 1,
                    "total_failures": 0,
                    "consecutive_failures": 0,
                    "last_success_at": now.isoformat(),
                    "last_attempt_at": now.isoformat()
                }).execute()
            
            logger.debug(f"Recorded success for domain: {domain}")
            
        except Exception as e:
            logger.error(f"Error recording success for {domain}: {e}")
    
    def record_failure(self, url: str, reason: str) -> int:
        """Record extraction failure, increment consecutive failure counter.
        
        Args:
            url: URL that failed extraction
            reason: Failure reason ('download_failed', 'extraction_empty', 'extraction_error')
            
        Returns:
            Current consecutive failure count
        """
        domain = normalize_domain(url)
        
        try:
            # Check if domain exists
            result = self.client.supabase.table("research_domain_health") \
                .select("consecutive_failures") \
                .eq("domain", domain) \
                .execute()
            
            now = datetime.now(timezone.utc)
            consecutive_failures = 1
            
            if result.data:
                # Update existing record
                consecutive_failures = result.data[0].get("consecutive_failures", 0) + 1
                
                self.client.supabase.table("research_domain_health").update({
                    "total_attempts": self.client.supabase.rpc("increment", {"x": 1}),
                    "total_failures": self.client.supabase.rpc("increment", {"x": 1}),
                    "consecutive_failures": consecutive_failures,
                    "last_failure_reason": reason,
                    "last_attempt_at": now.isoformat(),
                    "updated_at": now.isoformat()
                }).eq("domain", domain).execute()
            else:
                # Insert new record
                self.client.supabase.table("research_domain_health").insert({
                    "domain": domain,
                    "total_attempts": 1,
                    "total_successes": 0,
                    "total_failures": 1,
                    "consecutive_failures": 1,
                    "last_failure_reason": reason,
                    "last_attempt_at": now.isoformat()
                }).execute()
            
            logger.debug(f"Recorded failure for domain: {domain} (consecutive: {consecutive_failures})")
            return consecutive_failures
            
        except Exception as e:
            logger.error(f"Error recording failure for {domain}: {e}")
            return 0
    
    def should_auto_blacklist(self, url: str) -> bool:
        """Check if domain should be auto-blacklisted based on consecutive failures.
        
        Args:
            url: URL to check
            
        Returns:
            True if domain should be auto-blacklisted
        """
        from settings import get_system_setting
        
        domain = normalize_domain(url)
        threshold = get_system_setting("auto_blacklist_threshold", default=4)
        
        try:
            result = self.client.supabase.table("research_domain_health") \
                .select("consecutive_failures, auto_blacklisted") \
                .eq("domain", domain) \
                .execute()
            
            if result.data:
                data = result.data[0]
                consecutive = data.get("consecutive_failures", 0)
                already_blacklisted = data.get("auto_blacklisted", False)
                
                return consecutive >= threshold and not already_blacklisted
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking auto-blacklist status for {domain}: {e}")
            return False
    
    def auto_blacklist_domain(self, url: str) -> bool:
        """Add domain to blacklist and mark as auto-blacklisted.
        
        Args:
            url: URL whose domain should be blacklisted
            
        Returns:
            True if successfully blacklisted
        """
        from settings import get_research_domain_blacklist, set_system_setting
        
        domain = normalize_domain(url)
        
        try:
            # Get current blacklist
            current_blacklist = get_research_domain_blacklist()
            
            # Add domain if not already in list
            if domain not in current_blacklist:
                updated_blacklist = current_blacklist + [domain]
                
                # Update blacklist in system settings
                if set_system_setting("research_domain_blacklist", updated_blacklist,
                                     "Domains to skip during market research article extraction (JSON array)"):
                    
                    # Mark domain as auto-blacklisted
                    now = datetime.now(timezone.utc)
                    self.client.supabase.table("research_domain_health").update({
                        "auto_blacklisted": True,
                        "auto_blacklisted_at": now.isoformat(),
                        "updated_at": now.isoformat()
                    }).eq("domain", domain).execute()
                    
                    logger.info(f"✅ Auto-blacklisted domain: {domain}")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error auto-blacklisting domain {domain}: {e}")
            return False
    
    def get_unhealthy_domains(self, min_failures: int = 2) -> list:
        """Get domains with high failure rates.
        
        Args:
            min_failures: Minimum consecutive failures to include
            
        Returns:
            List of domain health records
        """
        try:
            result = self.client.supabase.table("research_domain_health") \
                .select("*") \
                .gte("consecutive_failures", min_failures) \
                .order("consecutive_failures", desc=True) \
                .execute()
            
            return result.data if result.data else []
            
        except Exception as e:
            logger.error(f"Error getting unhealthy domains: {e}")
            return []
