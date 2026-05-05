"""
Bounded parallel execution for research article ingestion steps.

Used by scheduler jobs in ``jobs_research.py`` (and similar) so multiple articles
can be summarized concurrently when ``RESEARCH_ARTICLE_WORKERS`` > 1, while
respecting an overall job deadline.

Worker functions return :class:`ArticleCounters` deltas; the runner sums them.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Sequence, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class ArticleCounters:
    """Per-article or aggregated counters for research ingestion."""

    processed: int = 0
    saved: int = 0
    skipped: int = 0
    blacklisted: int = 0
    irrelevant: int = 0
    failed: int = 0

    def __add__(self, other: ArticleCounters) -> ArticleCounters:
        return ArticleCounters(
            processed=self.processed + other.processed,
            saved=self.saved + other.saved,
            skipped=self.skipped + other.skipped,
            blacklisted=self.blacklisted + other.blacklisted,
            irrelevant=self.irrelevant + other.irrelevant,
            failed=self.failed + other.failed,
        )

    def __iadd__(self, other: ArticleCounters) -> ArticleCounters:
        self.processed += other.processed
        self.saved += other.saved
        self.skipped += other.skipped
        self.blacklisted += other.blacklisted
        self.irrelevant += other.irrelevant
        self.failed += other.failed
        return self


def get_research_article_worker_count() -> int:
    """Max concurrent article workers per job (1–32).

    Reads ``system_settings.research_article_workers`` first, then
    ``RESEARCH_ARTICLE_WORKERS`` (default ``1`` = sequential, unchanged behavior).
    """
    try:
        from settings import get_system_setting

        raw_db = get_system_setting("research_article_workers", default=None)
        if raw_db is not None and str(raw_db).strip() != "":
            n = int(raw_db)
            return max(1, min(32, n))
    except (TypeError, ValueError, Exception):
        pass
    try:
        n = int(os.getenv("RESEARCH_ARTICLE_WORKERS", "1"))
    except ValueError:
        n = 1
    return max(1, min(32, n))


def run_article_pipeline_parallel(
    worker: Callable[[T], ArticleCounters],
    items: Sequence[T],
    *,
    max_workers: int,
    job_start_time: float,
    max_job_duration_sec: float,
) -> ArticleCounters:
    """Run ``worker`` over ``items`` with up to ``max_workers`` threads.

    Stops submitting new work after ``job_start_time + max_job_duration_sec``.
    In-flight tasks are allowed to finish.
    """
    deadline = job_start_time + float(max_job_duration_sec)
    if max_workers <= 1:
        agg = ArticleCounters()
        for item in items:
            if time.time() >= deadline:
                break
            try:
                agg += worker(item)
            except Exception:
                logger.exception("Article worker failed (serial mode)")
                agg.failed += 1
        return agg

    agg = ArticleCounters()
    it = iter(items)
    pending: set = set()

    with ThreadPoolExecutor(max_workers=max_workers) as ex:

        def refill() -> None:
            nonlocal pending
            while len(pending) < max_workers:
                if time.time() >= deadline:
                    return
                try:
                    nxt = next(it)
                except StopIteration:
                    return
                pending.add(ex.submit(worker, nxt))

        refill()
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                try:
                    agg += fut.result()
                except Exception:
                    logger.exception("Article worker failed (parallel mode)")
                    agg.failed += 1
            refill()

    return agg
