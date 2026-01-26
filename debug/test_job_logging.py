"""
Test script to manually run jobs that weren't showing recent logs.

This script allows you to test each job individually to verify logging works.
"""

import os
import sys
from pathlib import Path

# Add project root and web_dashboard to path
project_root = Path(__file__).resolve().parent.parent
web_dashboard = project_root / 'web_dashboard'
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(web_dashboard))

# Set up logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_refresh_securities_metadata():
    """Test refresh_securities_metadata job"""
    print("\n" + "="*60)
    print("TESTING: refresh_securities_metadata")
    print("="*60)
    try:
        from scheduler.jobs_securities import refresh_securities_metadata_job
        refresh_securities_metadata_job()
        print("✅ Job completed successfully")
    except Exception as e:
        print(f"❌ Job failed: {e}")
        import traceback
        traceback.print_exc()

def test_log_cleanup():
    """Test log_cleanup job"""
    print("\n" + "="*60)
    print("TESTING: log_cleanup")
    print("="*60)
    try:
        from scheduler.jobs import cleanup_log_files_job
        cleanup_log_files_job()
        print("✅ Job completed successfully")
    except Exception as e:
        print(f"❌ Job failed: {e}")
        import traceback
        traceback.print_exc()

def test_symbol_article_scraper():
    """Test symbol_article_scraper job"""
    print("\n" + "="*60)
    print("TESTING: symbol_article_scraper")
    print("="*60)
    try:
        from scheduler.jobs_symbol_articles import symbol_article_scraper_job
        symbol_article_scraper_job()
        print("✅ Job completed successfully")
    except Exception as e:
        print(f"❌ Job failed: {e}")
        import traceback
        traceback.print_exc()

def test_social_metrics_cleanup():
    """Test social_metrics_cleanup job"""
    print("\n" + "="*60)
    print("TESTING: social_metrics_cleanup")
    print("="*60)
    try:
        from scheduler.jobs_social import cleanup_social_metrics_job
        cleanup_social_metrics_job()
        print("✅ Job completed successfully")
    except Exception as e:
        print(f"❌ Job failed: {e}")
        import traceback
        traceback.print_exc()

def test_dividend_processing():
    """Test dividend_processing job"""
    print("\n" + "="*60)
    print("TESTING: dividend_processing")
    print("="*60)
    try:
        from scheduler.jobs_dividends import process_dividends_job
        process_dividends_job()
        print("✅ Job completed successfully")
    except Exception as e:
        print(f"❌ Job failed: {e}")
        import traceback
        traceback.print_exc()

def test_benchmark_refresh():
    """Test benchmark_refresh job"""
    print("\n" + "="*60)
    print("TESTING: benchmark_refresh")
    print("="*60)
    try:
        from scheduler.jobs_metrics import benchmark_refresh_job
        benchmark_refresh_job()
        print("✅ Job completed successfully")
    except Exception as e:
        print(f"❌ Job failed: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Run all tests or a specific test"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Test jobs that weren\'t logging properly')
    parser.add_argument('--job', choices=[
        'securities', 'log_cleanup', 'symbol_article_scraper', 'social_cleanup', 
        'dividend', 'benchmark', 'all'
    ], default='all', help='Which job to test (default: all)')
    
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("JOB LOGGING TEST SCRIPT")
    print("="*60)
    print("\nThis script tests jobs that weren't showing recent logs.")
    print("After running, check the Jobs Scheduler page in the web dashboard")
    print("to see if logs appear in 'Recent Logs' section.\n")
    
    if args.job == 'all':
        test_refresh_securities_metadata()
        test_log_cleanup()
        test_seeking_alpha_symbol()
        test_social_metrics_cleanup()
        test_dividend_processing()
        test_benchmark_refresh()
        print("\n" + "="*60)
        print("ALL TESTS COMPLETE")
        print("="*60)
        print("\nCheck the Jobs Scheduler page in the web dashboard")
        print("to verify logs appear in 'Recent Logs' section.")
    elif args.job == 'securities':
        test_refresh_securities_metadata()
    elif args.job == 'log_cleanup':
        test_log_cleanup()
    elif args.job == 'symbol_article_scraper':
        test_seeking_alpha_symbol()
    elif args.job == 'social_cleanup':
        test_social_metrics_cleanup()
    elif args.job == 'dividend':
        test_dividend_processing()
    elif args.job == 'benchmark':
        test_benchmark_refresh()

if __name__ == '__main__':
    main()
