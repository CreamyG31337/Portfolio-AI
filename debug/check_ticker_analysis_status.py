#!/usr/bin/env python3
"""Check Ticker AI Analysis Job Status"""

import sys
import os

# Add web_dashboard to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web_dashboard'))

from postgres_client import PostgresClient
from supabase_client import SupabaseClient

print('=' * 70)
print('TICKER AI ANALYSIS JOB STATUS')
print('=' * 70)

# 1. Check Research DB for ticker analyses
print('\n[1] TICKER ANALYSIS RESULTS (Research DB)')
print('-' * 70)
try:
    postgres = PostgresClient()
    
    # Count total analyses
    count_result = postgres.execute_query('SELECT COUNT(*) as total FROM ticker_analysis')
    total = count_result[0]['total'] if count_result else 0
    print(f'Total analyses in database: {total}')
    
    # Get recent analyses
    recent = postgres.execute_query('''
        SELECT ticker, analysis_date, sentiment, stance, confidence_score,
               etf_changes_count, congress_trades_count, research_articles_count,
               model_used, requested_by,
               updated_at
        FROM ticker_analysis
        ORDER BY updated_at DESC
        LIMIT 15
    ''')
    
    if recent:
        print(f'\nRecent analyses ({len(recent)} shown):')
        print(f'{"Ticker":<8} {"Date":<12} {"Sentiment":<10} {"Stance":<6} {"Conf":<6} {"ETF":<4} {"Cong":<4} {"Art":<4} {"Model":<15}')
        print('-' * 90)
        for r in recent:
            ticker = r.get('ticker', 'N/A')[:7]
            date = str(r.get('analysis_date', 'N/A'))[:10]
            sentiment = (r.get('sentiment') or 'N/A')[:9]
            stance = (r.get('stance') or 'N/A')[:5]
            conf = f"{r.get('confidence_score', 0):.2f}" if r.get('confidence_score') else 'N/A'
            etf = str(r.get('etf_changes_count', 0))
            cong = str(r.get('congress_trades_count', 0))
            art = str(r.get('research_articles_count', 0))
            model = (r.get('model_used') or 'N/A')[:14]
            print(f'{ticker:<8} {date:<12} {sentiment:<10} {stance:<6} {conf:<6} {etf:<4} {cong:<4} {art:<4} {model:<15}')
    else:
        print('No analyses found in database!')
        recent = []
        
except Exception as e:
    print(f'Error querying Research DB: {e}')
    recent = []

# 2. Check Supabase for job execution history
print('\n' + '=' * 70)
print('[2] JOB EXECUTION HISTORY (Supabase)')
print('-' * 70)
try:
    supabase = SupabaseClient(use_service_role=True)
    
    result = supabase.supabase.table('job_executions') \
        .select('job_name, target_date, status, started_at, completed_at, duration_ms, error_message') \
        .eq('job_name', 'ticker_analysis') \
        .order('started_at', desc=True) \
        .limit(10) \
        .execute()
    
    if result.data:
        print(f'Recent job executions ({len(result.data)} shown):')
        print(f'{"Date":<12} {"Status":<12} {"Duration":<12} {"Error":<40}')
        print('-' * 80)
        for r in result.data:
            date = str(r.get('target_date', 'N/A'))[:10]
            status = r.get('status', 'N/A')[:11]
            duration = f"{r.get('duration_ms', 0) / 1000:.1f}s" if r.get('duration_ms') else 'N/A'
            error = (r.get('error_message') or '')[:39]
            print(f'{date:<12} {status:<12} {duration:<12} {error:<40}')
    else:
        print('No job executions found for ticker_analysis')
        
except Exception as e:
    print(f'Error querying job executions: {e}')

# 3. Check skip list
print('\n' + '=' * 70)
print('[3] AI ANALYSIS SKIP LIST (Failed Tickers)')
print('-' * 70)
try:
    skip_result = supabase.supabase.table('ai_analysis_skip_list') \
        .select('ticker, reason, failure_count, last_failed_at, skip_until') \
        .order('last_failed_at', desc=True) \
        .limit(10) \
        .execute()
    
    if skip_result.data:
        print(f'Skipped tickers ({len(skip_result.data)} shown):')
        print(f'{"Ticker":<10} {"Failures":<10} {"Reason":<50}')
        print('-' * 75)
        for r in skip_result.data:
            ticker = r.get('ticker', 'N/A')[:9]
            failures = str(r.get('failure_count', 0))
            reason = (r.get('reason') or 'N/A')[:49]
            print(f'{ticker:<10} {failures:<10} {reason:<50}')
    else:
        print('No tickers in skip list (good!)')
        
except Exception as e:
    print(f'Error querying skip list: {e}')

# 4. Check what tickers SHOULD be analyzed (holdings + watched)
print('\n' + '=' * 70)
print('[4] TICKERS PENDING ANALYSIS')
print('-' * 70)
try:
    # Get holdings
    holdings = supabase.supabase.table('portfolio_positions') \
        .select('ticker') \
        .execute()
    holding_tickers = set(r.get('ticker') for r in (holdings.data or []) if r.get('ticker'))
    
    # Get watched
    watched = supabase.supabase.table('watched_tickers') \
        .select('ticker') \
        .eq('is_active', True) \
        .execute()
    watched_tickers = set(r.get('ticker') for r in (watched.data or []) if r.get('ticker'))
    
    print(f'Holdings tickers: {len(holding_tickers)}')
    print(f'Watched tickers: {len(watched_tickers)}')
    print(f'Total unique tickers to analyze: {len(holding_tickers | watched_tickers)}')
    
    # Check which have recent analyses
    if holding_tickers:
        holding_list = list(holding_tickers)[:20]  # Check first 20
        analyzed = postgres.execute_query('''
            SELECT DISTINCT ticker FROM ticker_analysis
            WHERE ticker = ANY(%s)
            AND updated_at > NOW() - INTERVAL '7 days'
        ''', (holding_list,))
        analyzed_tickers = set(r['ticker'] for r in (analyzed or []))
        
        not_analyzed = [t for t in holding_list if t not in analyzed_tickers]
        print(f'\nHoldings analyzed in last 7 days: {len(analyzed_tickers)}/{len(holding_list)}')
        if not_analyzed:
            print(f'Holdings NOT analyzed recently: {not_analyzed[:10]}')
            
except Exception as e:
    print(f'Error checking pending tickers: {e}')

print('\n' + '=' * 70)
print('TICKERS TO CHECK IN UI:')
print('-' * 70)
if recent:
    tickers_to_check = [r.get('ticker') for r in recent[:5] if r.get('ticker')]
    print('Check these tickers in the web dashboard to see AI analysis:')
    for t in tickers_to_check:
        print(f'  - {t}: /ticker/{t}')
else:
    print('No analyzed tickers found - the job may not have run yet.')
