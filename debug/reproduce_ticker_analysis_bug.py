#!/usr/bin/env python3
"""
Reproduce the "unsupported format string passed to NoneType.__format__" bug
in the Ticker AI Analysis job.

This script runs a single ticker analysis to capture the full error traceback.
"""

import sys
import os
import logging
import traceback

# Add web_dashboard to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web_dashboard'))

# Setup detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_single_ticker(ticker: str):
    """Run analysis on a single ticker to reproduce the bug."""
    from postgres_client import PostgresClient
    from supabase_client import SupabaseClient
    from ollama_client import get_ollama_client
    from ai_skip_list_manager import AISkipListManager
    from ticker_analysis_service import TickerAnalysisService
    
    print(f"\n{'='*70}")
    print(f"TESTING TICKER: {ticker}")
    print('='*70)
    
    # Initialize clients
    supabase = SupabaseClient(use_service_role=True)
    postgres = PostgresClient()
    ollama = get_ollama_client()
    skip_list = AISkipListManager(supabase)
    
    service = TickerAnalysisService(ollama, supabase, postgres, skip_list)
    
    # Step 1: Gather data
    print("\n[1] Gathering ticker data...")
    try:
        data = service.gather_ticker_data(ticker)
        print(f"    - Fundamentals: {'Yes' if data.get('fundamentals') else 'No'}")
        print(f"    - Price data: {'Yes' if data.get('price_data') else 'No'}")
        print(f"    - ETF changes: {len(data.get('etf_changes', []))}")
        print(f"    - Congress trades: {len(data.get('congress_trades', []))}")
        print(f"    - Signals: {'Yes' if data.get('signals') else 'No'}")
        print(f"    - Research articles: {len(data.get('research_articles', []))}")
        print(f"    - Social sentiment: {'Yes' if data.get('social_sentiment') else 'No'}")
    except Exception as e:
        print(f"    ERROR gathering data: {e}")
        traceback.print_exc()
        return
    
    # Step 2: Check for None values that cause format issues
    print("\n[2] Checking for None values in format-sensitive fields...")
    
    # Check price_data
    price_data = data.get('price_data')
    if price_data:
        problematic_fields = []
        for field in ['current_price', 'daily_change_pct', 'period_change_pct', 
                      'period_high', 'period_low', 'pct_from_period_high', 
                      'pct_from_period_low', 'high_52w', 'low_52w', 
                      'pct_from_52w_high', 'pct_from_52w_low', 
                      'current_volume', 'avg_volume', 'volume_ratio']:
            val = price_data.get(field)
            if val is None:
                problematic_fields.append(field)
        if problematic_fields:
            print(f"    [WARN] Price data has None values: {problematic_fields}")
        else:
            print(f"    [OK] Price data looks OK")
    
    # Check signals
    signals = data.get('signals')
    if signals:
        confidence = signals.get('confidence_score', signals.get('confidence', 0))
        if confidence is None:
            print(f"    [WARN] SIGNALS: confidence is None (will cause format error!)")
        else:
            print(f"    [OK] Signals confidence: {confidence}")
            
        # Check nested dicts
        for key in ['structure_signal', 'timing_signal', 'fear_risk_signal']:
            sub = signals.get(key)
            if sub:
                for k, v in sub.items():
                    if v is None:
                        print(f"    [WARN] SIGNALS: {key}.{k} is None")
    
    # Check ETF changes
    etf_changes = data.get('etf_changes', [])
    for i, c in enumerate(etf_changes[:3]):  # Check first 3
        percent_change = c.get('percent_change')
        share_change = c.get('share_change')
        if percent_change is None:
            print(f"    [WARN] ETF change {i}: percent_change is None")
        if share_change is None:
            print(f"    [WARN] ETF change {i}: share_change is None")
    
    # Check social sentiment
    sentiment = data.get('social_sentiment', {})
    for m in sentiment.get('latest_metrics', [])[:3]:
        score = m.get('sentiment_score')
        if score is None:
            print(f"    [WARN] Social sentiment: sentiment_score is None")
    
    # Step 3: Try formatting context
    print("\n[3] Formatting context (this is where the bug occurs)...")
    try:
        context = service.format_ticker_context(data)
        print(f"    [OK] Context formatted successfully ({len(context)} chars)")
    except Exception as e:
        print(f"    [ERROR] ERROR formatting context: {e}")
        traceback.print_exc()
        return
    
    # Step 4: Run full analysis (optional - requires Ollama)
    if ollama:
        print("\n[4] Running full analysis with LLM...")
        try:
            result = service.analyze_ticker(ticker)
            print(f"    [OK] Analysis completed: {result.get('sentiment')} / {result.get('stance')}")
        except Exception as e:
            print(f"    [ERROR] ERROR in analysis: {e}")
            traceback.print_exc()
    else:
        print("\n[4] Skipping LLM analysis (Ollama not available)")
    
    print("\n" + "="*70)


def main():
    # Get failed tickers from skip list
    from supabase_client import SupabaseClient
    
    supabase = SupabaseClient(use_service_role=True)
    skip_result = supabase.supabase.table('ai_analysis_skip_list') \
        .select('ticker, reason') \
        .order('last_failed_at', desc=True) \
        .limit(5) \
        .execute()
    
    failed_tickers = [r['ticker'] for r in (skip_result.data or [])]
    
    if not failed_tickers:
        print("No failed tickers found. Using default test ticker: NVDA")
        failed_tickers = ['NVDA']
    
    print("Testing these failed tickers:")
    for t in failed_tickers:
        print(f"  - {t}")
    
    # Test the first failed ticker
    test_single_ticker(failed_tickers[0])


if __name__ == "__main__":
    # Allow passing ticker as argument
    if len(sys.argv) > 1:
        test_single_ticker(sys.argv[1].upper())
    else:
        main()
