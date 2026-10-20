#!/usr/bin/env python3
"""
Backfill Congress Trade Sessions
=================================

This script assigns existing congress trades to sessions using the 7-day gap rule.
Run this once before using --sessions mode to populate the sessions table.

Usage:
    python scripts/backfill_congress_sessions.py [--gap-days 7] [--limit 1000]
"""

import sys
import os
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# Add project root to path
# Add project root to path
# Script is in web_dashboard/scripts/, so project root is up 2 levels
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
env_path = project_root / 'web_dashboard' / '.env'
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

from supabase_client import SupabaseClient
from postgres_client import PostgresClient
from utils.grouping import get_politician_sessions

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def backfill_sessions(gap_days: int = 7, max_group_size: int = 0, limit: int = 0):
    """Backfill sessions for existing trades.
    
    Args:
        gap_days: Maximum gap between trades in same session
        max_group_size: Max trades per session
        limit: Max trades to process (0 = all)
    """
    logger.info("Starting session backfill...")
    
    supabase = SupabaseClient(use_service_role=True)
    postgres = PostgresClient()
    
    # Fetch all trades with pagination
    logger.info("Fetching trades from Supabase...")
    
    all_trades = []
    page_size = 1000
    start = 0
    
    while True:
        query = supabase.supabase.table("congress_trades_enriched")\
            .select("id, politician, transaction_date, ticker, party, state, chamber")\
            .order("transaction_date", desc=False)\
            .order("id")\
            .range(start, start + page_size - 1)
        
        response = query.execute()
        batch = response.data
        
        if not batch:
            break
            
        all_trades.extend(batch)
        logger.info(f"Fetched {len(batch)} trades (total: {len(all_trades)})")
        
        if len(batch) < page_size:
            break
            
        start += page_size
        
        if limit > 0 and len(all_trades) >= limit:
            all_trades = all_trades[:limit]
            break
    
    if not all_trades:
        logger.info("No trades found.")
        return
    
    trades = all_trades
    logger.info(f"Found {len(trades)} trades total")
    
    # Group by politician and create sessions
    logger.info(f"Grouping trades into sessions (gap_days={gap_days}, max_size={max_group_size})...")
    
    politician_sessions = get_politician_sessions(
        trades, 
        gap_days=gap_days,
        max_group_size=max_group_size,
        politician_field='politician',
        date_field='transaction_date'
    )
    
    total_sessions = sum(len(sessions) for sessions in politician_sessions.values())
    logger.info(f"Created {total_sessions} sessions for {len(politician_sessions)} politicians")
    
    # Insert sessions and link trades
    sessions_created = 0
    trades_linked = 0
    
    for politician, sessions in politician_sessions.items():
        for session_trades in sessions:
            if not session_trades:
                continue
            
            # Get session date range
            dates = [t['transaction_date'] for t in session_trades]
            start_date = min(dates)
            end_date = max(dates)
            trade_count = len(session_trades)
            
            # Get first trade for metadata
            first_trade = session_trades[0]
            
            try:
                # Insert session
                result = postgres.execute_query(
                    """
                    INSERT INTO congress_trade_sessions 
                        (politician_name, start_date, end_date, trade_count, needs_reanalysis)
                    VALUES (%s, %s, %s, %s, TRUE)
                    ON CONFLICT (politician_name, start_date, end_date) 
                    DO UPDATE SET 
                        trade_count = EXCLUDED.trade_count,
                        needs_reanalysis = TRUE,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (politician, start_date, end_date, trade_count)
                )
                
                if result and len(result) > 0:
                    session_id = result[0]['id']
                    sessions_created += 1
                    
                    # Link trades to session (upsert analysis records)
                    for trade in session_trades:
                        try:
                            postgres.execute_update(
                                """
                                INSERT INTO congress_trades_analysis 
                                    (trade_id, session_id, model_used, analysis_version)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (trade_id, model_used, analysis_version) 
                                DO UPDATE SET 
                                    session_id = EXCLUDED.session_id
                                """,
                                (trade['id'], session_id, 'granite3.3:8b', 1)
                            )
                            trades_linked += 1
                        except Exception as e:
                            logger.error(f"Failed to link trade {trade['id']}: {e}")
                    
            except Exception as e:
                logger.error(f"Failed to create session for {politician}: {e}")
    
    logger.info(f"\nBackfill complete!")
    logger.info(f"  Sessions created/updated: {sessions_created}")
    logger.info(f"  Trades linked to sessions: {trades_linked}")
    
    # Show stats
    stats_result = postgres.execute_query(
        """
        SELECT 
            COUNT(*) as total_sessions,
            SUM(CASE WHEN needs_reanalysis THEN 1 ELSE 0 END) as pending_analysis
        FROM congress_trade_sessions
        """
    )
    
    if stats_result:
        logger.info(f"  Total sessions in database: {stats_result[0]['total_sessions']}")
        logger.info(f"  Sessions pending analysis: {stats_result[0]['pending_analysis']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Backfill congress trade sessions')
    parser.add_argument('--gap-days', type=int, default=7, 
                        help='Maximum days between trades in same session (default: 7)')
    parser.add_argument('--max-size', type=int, default=100, 
                        help='Maximum trades per session (default: 100, 0=unlimited)')
    parser.add_argument('--limit', type=int, default=0,
                        help='Limit number of trades to process (0 = all)')
    args = parser.parse_args()
    
    backfill_sessions(gap_days=args.gap_days, max_group_size=args.max_size, limit=args.limit)
