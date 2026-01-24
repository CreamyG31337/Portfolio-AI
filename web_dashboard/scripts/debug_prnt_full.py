import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.append(str(Path.cwd()))

from web_dashboard.scheduler.jobs_etf_watchtower import etf_watchtower_job, ETF_CONFIGS

# Configure logging
logging.basicConfig(level=logging.INFO)

# Monkey patch ETF_CONFIGS to only run PRNT
original_configs = ETF_CONFIGS.copy()
ETF_CONFIGS.clear()
ETF_CONFIGS['PRNT'] = original_configs['PRNT']

print("🚀 Running Watchtower Job for ONLY PRNT...")
try:
    etf_watchtower_job()
    print("✅ Job completed")
except Exception as e:
    print(f"❌ Job failed: {e}")
    import traceback
    traceback.print_exc()
