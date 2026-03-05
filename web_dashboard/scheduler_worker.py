#!/usr/bin/env python3
"""
Dedicated scheduler worker runtime.

Runs APScheduler without starting the Flask web server process.
Use with SCHEDULER_RUNTIME_MODE=external in web processes.
"""

import logging
import os
import signal
import sys
import time

from scheduler.scheduler_core import is_scheduler_running, shutdown_scheduler, start_scheduler

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    try:
        from log_handler import setup_logging

        setup_logging()
    except Exception:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )


def _shutdown_handler(signum: int, _frame) -> None:
    logger.info("Received signal %s, shutting down scheduler worker", signum)
    try:
        shutdown_scheduler()
    finally:
        sys.exit(0)


def main() -> int:
    _configure_logging()
    logger.info("Starting scheduler worker process")
    logger.info(
        "Runtime config: SCHEDULER_RUNTIME_MODE=%s, SCHEDULER_STATE_DIR=%s",
        os.getenv("SCHEDULER_RUNTIME_MODE", "embedded"),
        os.getenv("SCHEDULER_STATE_DIR", "/tmp"),
    )

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

    started = start_scheduler()
    if not started and not is_scheduler_running():
        logger.error("Failed to start scheduler worker")
        return 1

    logger.info("Scheduler worker is running")
    while True:
        if not is_scheduler_running():
            logger.error("Scheduler heartbeat lost, exiting worker for restart")
            return 2
        time.sleep(15)


if __name__ == "__main__":
    raise SystemExit(main())
