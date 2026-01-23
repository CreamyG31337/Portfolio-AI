#!/usr/bin/env python3
"""
Test Running ETF AI Jobs
========================

Actually runs the jobs to test for errors.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
web_dashboard_path = project_root / "web_dashboard"
sys.path.insert(1, str(web_dashboard_path))

from dotenv import load_dotenv

# Load environment variables
env_path = web_dashboard_path / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

def test_etf_group_analysis_job():
    """Test running the ETF group analysis job."""
    print("\n" + "=" * 60)
    print("Testing ETF Group Analysis Job")
    print("=" * 60)
    
    try:
        print("\n[INFO] Importing job function directly...")
        # Import directly from the file to avoid scheduler __init__ circular import
        import importlib.util
        job_file = web_dashboard_path / "scheduler" / "jobs_etf_analysis.py"
        spec = importlib.util.spec_from_file_location("jobs_etf_analysis", job_file)
        jobs_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(jobs_module)
        etf_group_analysis_job = jobs_module.etf_group_analysis_job
        print("[OK] Job function imported")
        
        print("\n[INFO] Running job (this may take a moment)...")
        etf_group_analysis_job()
        print("[OK] Job completed successfully!")
        return True
        
    except Exception as e:
        print(f"[ERROR] Job failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ticker_analysis_job():
    """Test running the ticker analysis job."""
    print("\n" + "=" * 60)
    print("Testing Ticker Analysis Job")
    print("=" * 60)
    
    try:
        print("\n[INFO] Importing job function directly...")
        # Import directly from the file to avoid scheduler __init__ circular import
        import importlib.util
        job_file = web_dashboard_path / "scheduler" / "jobs_ticker_analysis.py"
        spec = importlib.util.spec_from_file_location("jobs_ticker_analysis", job_file)
        jobs_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(jobs_module)
        ticker_analysis_job = jobs_module.ticker_analysis_job
        print("[OK] Job function imported")
        
        print("\n[INFO] Running job (this may take a while - 2 hour max)...")
        print("[INFO] Job will stop after 2 hours or when all tickers are processed")
        ticker_analysis_job()
        print("[OK] Job completed successfully!")
        return True
        
    except Exception as e:
        print(f"[ERROR] Job failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run job tests."""
    print("=" * 60)
    print("ETF AI Analysis Jobs - Runtime Test")
    print("=" * 60)
    
    import argparse
    parser = argparse.ArgumentParser(description="Test ETF AI analysis jobs")
    parser.add_argument(
        '--job',
        choices=['etf_group', 'ticker', 'both'],
        default='etf_group',
        help='Which job to test (default: etf_group)'
    )
    
    args = parser.parse_args()
    
    results = []
    
    if args.job in ['etf_group', 'both']:
        results.append(("ETF Group Analysis", test_etf_group_analysis_job()))
    
    if args.job in ['ticker', 'both']:
        results.append(("Ticker Analysis", test_ticker_analysis_job()))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "[OK]" if result else "[FAIL]"
        print(f"{status} {name}")
    
    print(f"\n{passed}/{total} jobs passed")
    
    if passed == total:
        print("\n[SUCCESS] All jobs ran successfully!")
    else:
        print("\n[WARNING] Some jobs failed. Check errors above.")

if __name__ == "__main__":
    main()
