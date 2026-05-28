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

    Hard deadline: returns within ``max_job_duration_sec`` of ``job_start_time``
    even if some worker threads are still blocked on slow I/O. Pending in-flight
    futures are cancelled where possible; already-running threads cannot be
    killed in CPython, but the runner returns regardless so the calling job can
    finish and release any global lock it was holding.

    Background: prior versions used ``wait(pending, return_when=FIRST_COMPLETED)``
    with no timeout. A single hung worker (e.g. a slow URL fetch inside
    trafilatura, or an Ollama call without its own timeout) blocked the runner
    indefinitely, which is what caused ``alpha_research`` to be auto-cleared by
    the stale-AI-lock watchdog at 1h on 2026-05-20 and 2026-05-22.
    """
    deadline = job_start_time + float(max_job_duration_sec)
    agg = ArticleCounters()
    it = iter(items)
    pending: set = set()

    effective_workers = max(1, max_workers)
    ex = ThreadPoolExecutor(max_workers=effective_workers)
    try:

        def refill() -> None:
            nonlocal pending
            while len(pending) < effective_workers:
                if time.time() >= deadline:
                    return
                try:
                    nxt = next(it)
                except StopIteration:
                    return
                pending.add(ex.submit(worker, nxt))

        refill()
        while pending:
            remaining = deadline - time.time()
            if remaining <= 0:
                logger.warning(
                    "Article pipeline deadline reached; %d in-flight task(s) "
                    "remain and will be abandoned",
                    len(pending),
                )
                break
            done, pending = wait(
                pending, timeout=remaining, return_when=FIRST_COMPLETED
            )
            if not done:
                logger.warning(
                    "Article pipeline deadline reached while waiting on "
                    "%d in-flight task(s); abandoning",
                    len(pending),
                )
                break
            for fut in done:
                try:
                    agg += fut.result()
                except Exception:
                    logger.exception("Article worker failed (parallel mode)")
                    agg.failed += 1
            refill()
    finally:
        try:
            ex.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            ex.shutdown(wait=False)

    return agg
