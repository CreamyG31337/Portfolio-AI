"""
Test Insider Trades Job
========================

Test script to verify the insider trades job works correctly.
Run this to test the QuiverQuant scraper without running the full scheduler.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

# Configure logging
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def main():
    """Run the insider trades job."""
    try:
        logger.info("=" * 80)
        logger.info("Testing Insider Trades Job")
        logger.info("=" * 80)

        # Import the job
        from web_dashboard.scheduler.jobs_insiders import fetch_insider_trades_job

        # Run the job
        logger.info("Running fetch_insider_trades_job()...")
        fetch_insider_trades_job()

        logger.info("=" * 80)
        logger.info("Test completed successfully!")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        return 1

    return 0

if __name__ == "__main__":
    exit(main())
