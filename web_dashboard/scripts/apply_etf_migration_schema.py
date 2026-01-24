#!/usr/bin/env python3
"""
Apply ETF Holdings Migration Schema to Research DB
===================================================

This script applies the necessary schema changes to support
ETF holdings migration from Supabase to Research DB:

1. Adds missing composite index to etf_holdings_log
2. Creates etf_holdings_changes view
3. Creates get_etf_holding_trades function

Usage:
    cd web_dashboard
    python scripts/apply_etf_migration_schema.py
"""

import sys
from pathlib import Path

# Add project paths
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from dotenv import load_dotenv
load_dotenv(project_root / 'web_dashboard' / '.env')

from postgres_client import PostgresClient


def main():
    print("=" * 60)
    print("ETF Holdings Migration - Schema Setup")
    print("=" * 60)
    
    pc = PostgresClient()
    
    # 1. Check if table exists
    print("\n[1/4] Checking etf_holdings_log table exists...")
    result = pc.execute_query("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'etf_holdings_log'
        ) as exists
    """)
    
    if not result or not result[0]['exists']:
        print("  Creating etf_holdings_log table...")
        pc.execute_update("""
            CREATE TABLE IF NOT EXISTS etf_holdings_log (
                date DATE NOT NULL,
                etf_ticker VARCHAR(10) NOT NULL,
                holding_ticker VARCHAR(50) NOT NULL,
                holding_name TEXT,
                shares_held NUMERIC,
                weight_percent NUMERIC,
                market_value NUMERIC,
                created_at TIMESTAMP DEFAULT now(),
                PRIMARY KEY (date, etf_ticker, holding_ticker)
            )
        """)
        print("  [OK] Table created")
    else:
        print("  [OK] Table already exists")
    
    # 2. Add missing composite index (if not exists)
    print("\n[2/4] Checking/creating composite index...")
    result = pc.execute_query("""
        SELECT EXISTS (
            SELECT FROM pg_indexes 
            WHERE indexname = 'idx_ehl_holding_date'
        ) as exists
    """)
    
    if not result or not result[0]['exists']:
        print("  Creating idx_ehl_holding_date index...")
        pc.execute_update("""
            CREATE INDEX IF NOT EXISTS idx_ehl_holding_date 
            ON etf_holdings_log (holding_ticker, date) 
            INCLUDE (etf_ticker, shares_held)
        """)
        print("  [OK] Index created")
    else:
        print("  [OK] Index already exists")
    
    # Also ensure other indexes exist
    print("  Ensuring other indexes exist...")
    pc.execute_update("CREATE INDEX IF NOT EXISTS idx_etf_holdings_date ON etf_holdings_log (date)")
    pc.execute_update("CREATE INDEX IF NOT EXISTS idx_etf_holdings_etf ON etf_holdings_log (etf_ticker, date)")
    pc.execute_update("CREATE INDEX IF NOT EXISTS idx_etf_holdings_ticker ON etf_holdings_log (holding_ticker)")
    print("  [OK] All indexes verified")
    
    # 3. Create view
    print("\n[3/4] Creating etf_holdings_changes view...")
    pc.execute_update("""
        DROP VIEW IF EXISTS etf_holdings_changes CASCADE;
        
        CREATE OR REPLACE VIEW etf_holdings_changes AS
        WITH daily_holdings AS (
            SELECT 
                date,
                etf_ticker,
                holding_ticker,
                shares_held,
                LAG(shares_held) OVER (
                    PARTITION BY etf_ticker, holding_ticker 
                    ORDER BY date
                ) AS prev_shares
            FROM etf_holdings_log
        ),
        changes AS (
            SELECT
                date,
                etf_ticker,
                holding_ticker,
                shares_held AS shares_after,
                prev_shares AS shares_before,
                shares_held - COALESCE(prev_shares, 0) AS share_change,
                CASE 
                    WHEN prev_shares IS NULL OR prev_shares = 0 THEN 100.0
                    ELSE ROUND(((shares_held - prev_shares)::numeric / prev_shares * 100), 2)
                END AS percent_change,
                CASE 
                    WHEN shares_held > COALESCE(prev_shares, 0) THEN 'BUY' 
                    WHEN shares_held < COALESCE(prev_shares, 0) THEN 'SELL'
                    ELSE 'HOLD'
                END AS action
            FROM daily_holdings
            WHERE shares_held != COALESCE(prev_shares, 0)
        )
        SELECT 
            date,
            etf_ticker,
            holding_ticker,
            share_change,
            percent_change,
            action,
            shares_before,
            shares_after
        FROM changes
        WHERE ABS(share_change) >= 1000 OR ABS(percent_change) >= 0.5
    """)
    print("  [OK] View created")
    
    # 4. Create function
    print("\n[4/4] Creating get_etf_holding_trades function...")
    pc.execute_update("""
        DROP FUNCTION IF EXISTS get_etf_holding_trades(text, date, date, text);
        
        CREATE OR REPLACE FUNCTION get_etf_holding_trades(
          p_holding_ticker text,
          p_start_date date,
          p_end_date date,
          p_etf_ticker text default null
        )
        RETURNS TABLE (
          trade_date date,
          etf_ticker text,
          holding_ticker text,
          trade_type text,
          shares_change numeric,
          shares_after numeric
        )
        LANGUAGE sql
        STABLE
        AS $func$
        WITH in_range_etfs AS (
          SELECT DISTINCT e.etf_ticker
          FROM etf_holdings_log e
          WHERE e.holding_ticker = p_holding_ticker
            AND (p_etf_ticker IS NULL OR e.etf_ticker = p_etf_ticker)
            AND e.date BETWEEN p_start_date AND p_end_date
        ),
        seed_prev AS (
          SELECT prev.*
          FROM in_range_etfs t
          JOIN LATERAL (
            SELECT e.*
            FROM etf_holdings_log e
            WHERE e.holding_ticker = p_holding_ticker
              AND e.etf_ticker = t.etf_ticker
              AND e.date < p_start_date
            ORDER BY e.date DESC
            LIMIT 1
          ) prev ON true
        ),
        data AS (
          SELECT e.date, e.etf_ticker, e.holding_ticker, COALESCE(e.shares_held, 0) AS shares_after
          FROM etf_holdings_log e
          WHERE e.holding_ticker = p_holding_ticker
            AND (p_etf_ticker IS NULL OR e.etf_ticker = p_etf_ticker)
            AND e.date BETWEEN p_start_date AND p_end_date

          UNION ALL

          SELECT s.date, s.etf_ticker, s.holding_ticker, COALESCE(s.shares_held, 0) AS shares_after
          FROM seed_prev s
        ),
        calc AS (
          SELECT
            d.*,
            d.shares_after - LAG(d.shares_after) OVER (
              PARTITION BY d.etf_ticker, d.holding_ticker 
              ORDER BY d.date
            ) AS shares_change
          FROM data d
        )
        SELECT
          c.date AS trade_date,
          c.etf_ticker,
          c.holding_ticker,
          CASE
            WHEN c.shares_change > 0 THEN 'Purchase'
            WHEN c.shares_change < 0 THEN 'Sale'
            ELSE NULL
          END AS trade_type,
          c.shares_change,
          c.shares_after
        FROM calc c
        WHERE c.date BETWEEN p_start_date AND p_end_date
          AND c.shares_change IS NOT NULL
          AND c.shares_change <> 0
        ORDER BY c.date ASC, c.etf_ticker ASC;
        $func$
    """)
    print("  [OK] Function created")
    
    print("\n" + "=" * 60)
    print("Schema setup complete!")
    print("=" * 60)
    
    # Verify
    print("\nVerification:")
    result = pc.execute_query("SELECT COUNT(*) as cnt FROM etf_holdings_log")
    print(f"  etf_holdings_log rows: {result[0]['cnt'] if result else 0}")
    
    result = pc.execute_query("""
        SELECT COUNT(*) as cnt FROM pg_indexes WHERE tablename = 'etf_holdings_log'
    """)
    print(f"  Indexes on table: {result[0]['cnt'] if result else 0}")
    
    result = pc.execute_query("""
        SELECT EXISTS (
            SELECT FROM pg_proc WHERE proname = 'get_etf_holding_trades'
        ) as exists
    """)
    print(f"  Function exists: {result[0]['exists'] if result else False}")
    
    result = pc.execute_query("""
        SELECT EXISTS (
            SELECT FROM information_schema.views WHERE table_name = 'etf_holdings_changes'
        ) as exists
    """)
    print(f"  View exists: {result[0]['exists'] if result else False}")


if __name__ == '__main__':
    main()
