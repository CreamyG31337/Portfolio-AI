#!/usr/bin/env python3
"""Quick check of ETF data in research DB"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

from postgres_client import PostgresClient

pc = PostgresClient()

# Check data in research DB
result = pc.execute_query('SELECT etf_ticker, COUNT(*) as cnt FROM etf_holdings_log GROUP BY etf_ticker ORDER BY cnt DESC LIMIT 10')
print('Research DB ETF Holdings by ETF:')
for row in result:
    print(f"  {row['etf_ticker']}: {row['cnt']} rows")

print()
result = pc.execute_query('SELECT MIN(date) as min_date, MAX(date) as max_date FROM etf_holdings_log')
print(f"Date range: {result[0]['min_date']} to {result[0]['max_date']}")

print()
result = pc.execute_query('SELECT COUNT(DISTINCT etf_ticker) as cnt FROM etf_holdings_log')
print(f"Total distinct ETFs: {result[0]['cnt']}")
