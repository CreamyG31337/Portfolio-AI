#!/usr/bin/env python3
"""
Dashboard Entrypoint
====================

Starts the background scheduler before launching Streamlit.
This ensures scheduled tasks run alongside the web application.

Usage:
    python entrypoint.py
    
    # Or via the shell script:
    ./start.sh
"""

import os
import sys
import logging
import subprocess

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Start scheduler and Streamlit."""
    
    # Add web_dashboard to Python path
    web_dashboard_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, web_dashboard_dir)
    
    # Also add parent directory for imports like 'data', 'config', etc.
    parent_dir = os.path.dirname(web_dashboard_dir)
    sys.path.insert(0, parent_dir)
    
    logger.info("=" * 50)
    logger.info("Starting Trading Dashboard with Background Tasks")
    logger.info("=" * 50)
    
    # Start scheduler in a separate thread within this process
    # This keeps it independent of Streamlit's reloads but within the same container
    try:
        import threading
        import time
        # Note: os is already imported at module level - don't re-import here
        from scheduler.scheduler_core import start_scheduler
        
        def _run_scheduler():
            thread_name = threading.current_thread().name
            thread_id = threading.current_thread().ident
            process_id = os.getpid() if hasattr(os, 'getpid') else 'N/A'
            
            try:
                logger.info(f"[PID:{process_id} TID:{thread_id}] [{thread_name}] 🚀 Starting scheduler from entrypoint...")
                # Wait a bit for imports to settle
                time.sleep(2)
                try:
                    start_scheduler()
                    logger.info(f"[PID:{process_id} TID:{thread_id}] ✅ Scheduler started successfully")
                except Exception as e:
                    logger.error(f"[PID:{process_id} TID:{thread_id}] ❌ Failed to start scheduler: {e}", exc_info=True)
                logger.info(f"[PID:{process_id} TID:{thread_id}] [{thread_name}] Scheduler initialization complete")
            except Exception as e:
                logger.error(f"[PID:{process_id} TID:{thread_id}] ❌ Unexpected error in scheduler thread: {e}", exc_info=True)
            finally:
                logger.debug(f"[PID:{process_id} TID:{thread_id}] [{thread_name}] Thread exiting")

        # Start Flask web server (daemon thread, won't block)
        def start_flask_app():
            import threading
            from app import app
            logger.info(f"[PID:{process_id}] Starting Flask web server on port 5000...")
            try:
                app.run(host='0.0.0.0', port=5000, threaded=True)
            except Exception as e:
                logger.error(f"[PID:{process_id}] ❌ Flask web server failed: {e}", exc_info=True)
        
        flask_thread = threading.Thread(target=start_flask_app, daemon=True)
        flask_thread.start()
        logger.info(f"[PID:{process_id}] Flask web server thread started")

        process_id = os.getpid() if hasattr(os, 'getpid') else 'N/A'
        scheduler_thread = threading.Thread(
            target=_run_scheduler,
            name="SchedulerInitThread",
            daemon=True  # Daemon is correct - allows Streamlit to start without blocking
        )
        scheduler_thread.start()
        logger.info(f"[PID:{process_id}] Flask web server thread started")

        # Now start Streamlit (blocks until container stops)
        logger.info("Launching Streamlit application...")
    
    # Verify pages directory exists
    pages_dir = os.path.join(web_dashboard_dir, "pages")
    admin_page = os.path.join(pages_dir, "admin.py")
    
    if not os.path.exists(pages_dir):
        logger.error(f"❌ Pages directory not found at: {pages_dir}")
        logger.error("Streamlit pages will not work. Check Dockerfile COPY command.")
    elif not os.path.exists(admin_page):
        logger.warning(f"⚠️ Admin page not found at: {admin_page}")
        logger.warning("Admin dashboard will not be accessible.")
    else:
        logger.info(f"✅ Pages directory found at: {pages_dir}")
        logger.info(f"✅ Admin page found at: {admin_page}")
    
    streamlit_app = os.path.join(web_dashboard_dir, "streamlit_app.py")
    
    # Get port from environment or use default
    streamlit_port = os.environ.get("STREAMLIT_PORT", "8501")
    flask_port = os.environ.get("FLASK_PORT", "5000")
    
    # Build streamlit command
    # Run Streamlit from web_dashboard directory so it can find pages/ correctly
    # Streamlit resolves pages relative to the directory containing the main script
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        "streamlit_app.py",  # Use relative path - Streamlit will look for pages/ in same directory
        f"--server.port={streamlit_port}",
        "--server.address=0.0.0.0",
        "--server.headless=true"
    ]
    
    # Execute streamlit from web_dashboard directory (this will block and run the web server)
    # Use subprocess with cwd to ensure Streamlit runs from the correct directory
    # IMPORTANT: Set PYTHONPATH explicitly to ensure /app comes FIRST
    # This prevents web_dashboard/utils from shadowing root utils/ directory
    logger.info(f"Running: {' '.join(cmd)}")
    logger.info(f"Working directory: {web_dashboard_dir}")
    logger.info(f"Flask web server running on port 5000 (for v2 routes)")
    logger.info(f"Streamlit app running on port {streamlit_port} (for streamlit UI)")
    
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{parent_dir}:{web_dashboard_dir}:{env.get('PYTHONPATH', '')}"
    subprocess.run(cmd, cwd=web_dashboard_dir, env=env, check=False)


if __name__ == "__main__":
    main()
