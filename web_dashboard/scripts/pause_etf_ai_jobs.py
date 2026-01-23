#!/usr/bin/env python3
"""
Pause/Resume ETF AI Analysis Jobs
=================================

Helper script to pause or resume the ETF AI analysis jobs for testing.
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(1, str(project_root / "web_dashboard"))

from dotenv import load_dotenv
load_dotenv(project_root / "web_dashboard" / ".env")

def pause_jobs():
    """Pause both ETF AI analysis jobs."""
    try:
        from scheduler.scheduler_core import get_scheduler, pause_job
        
        scheduler = get_scheduler()
        
        jobs_to_pause = ['etf_group_analysis', 'ticker_analysis']
        
        for job_id in jobs_to_pause:
            job = scheduler.get_job(job_id)
            if job:
                pause_job(job_id)
                print(f"[OK] Paused: {job_id}")
            else:
                print(f"[INFO] Job not found: {job_id} (may not be registered yet)")
        
        print("\n[SUCCESS] Jobs paused. They will not run on schedule.")
        print("You can now test them manually without interference.")
        
    except Exception as e:
        print(f"[ERROR] Failed to pause jobs: {e}")
        import traceback
        traceback.print_exc()

def resume_jobs():
    """Resume both ETF AI analysis jobs."""
    try:
        from scheduler.scheduler_core import get_scheduler, resume_job
        
        scheduler = get_scheduler()
        
        jobs_to_resume = ['etf_group_analysis', 'ticker_analysis']
        
        for job_id in jobs_to_resume:
            job = scheduler.get_job(job_id)
            if job:
                resume_job(job_id)
                print(f"[OK] Resumed: {job_id}")
            else:
                print(f"[INFO] Job not found: {job_id}")
        
        print("\n[SUCCESS] Jobs resumed. They will run on schedule again.")
        
    except Exception as e:
        print(f"[ERROR] Failed to resume jobs: {e}")
        import traceback
        traceback.print_exc()

def check_status():
    """Check status of both jobs."""
    try:
        from scheduler.scheduler_core import get_scheduler
        
        scheduler = get_scheduler()
        
        jobs_to_check = ['etf_group_analysis', 'ticker_analysis']
        
        print("Job Status:")
        print("=" * 60)
        
        for job_id in jobs_to_check:
            job = scheduler.get_job(job_id)
            if job:
                next_run = getattr(job, 'next_run_time', None)
                status = "PAUSED" if next_run is None else "ACTIVE"
                print(f"{job_id}: {status}")
                if next_run:
                    print(f"  Next run: {next_run}")
            else:
                print(f"{job_id}: NOT REGISTERED")
        
    except Exception as e:
        print(f"[ERROR] Failed to check status: {e}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Pause/Resume ETF AI analysis jobs")
    parser.add_argument('action', choices=['pause', 'resume', 'status'], 
                       help='Action to perform')
    
    args = parser.parse_args()
    
    if args.action == 'pause':
        pause_jobs()
    elif args.action == 'resume':
        resume_jobs()
    elif args.action == 'status':
        check_status()
