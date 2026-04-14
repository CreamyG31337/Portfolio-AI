"""Scheduled outbound portfolio digest (Mailgun) — one wave per cadence bucket."""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def outbound_portfolio_digest_job() -> None:
    """Run due sends for daily/weekly/biweekly/monthly subscribers (portfolio_digest)."""
    job_id = "outbound_portfolio_digest"
    try:
        from outbound_newsletter_pipeline import run_scheduled_digest_wave
    except Exception as e:
        logger.error("[%s] import failed: %s", job_id, e, exc_info=True)
        return

    summary: Dict[str, Any] = {}
    for cadence in ("daily", "weekly", "biweekly", "monthly"):
        try:
            summary[cadence] = run_scheduled_digest_wave(cadence)
        except Exception as e:
            logger.error("[%s] wave %s failed: %s", job_id, cadence, e, exc_info=True)
            summary[cadence] = {"error": str(e)}
    logger.info("[%s] completed: %s", job_id, summary)
