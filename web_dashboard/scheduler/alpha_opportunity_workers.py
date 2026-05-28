"""Per-result workers for ``alpha_research_job`` and ``opportunity_discovery_job``."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from scheduler.article_pipeline import ArticleCounters
from scheduler.jobs_common import claim_recent_summary_input, has_strong_market_signal

logger = logging.getLogger(__name__)

IndexResult = tuple[int, dict]


def _remaining_article_seconds(article_start: float, max_article_duration: float) -> float:
    return max(0.0, max_article_duration - (time.time() - article_start))


def _has_time_for_stage(
    *,
    article_start: float,
    max_article_duration: float,
    min_seconds: float,
    title: str,
    stage: str,
) -> bool:
    remaining = _remaining_article_seconds(article_start, max_article_duration)
    if remaining < min_seconds:
        logger.warning(
            "⏱️  Skipping %s for %s... only %.1fs remain in article budget",
            stage,
            title[:40],
            remaining,
        )
        return False
    return True


@dataclass
class AlphaResearchCtx:
    research_repo: Any
    ollama_client: Any | None
    blacklist: list[str]
    job_id: str
    total_results: int
    max_article_duration: float
    sleep_after_article_sec: float


def process_alpha_research_item(ctx: AlphaResearchCtx, item: IndexResult) -> ArticleCounters:
    """Single SearXNG result for alpha research (claim → extract → summarize → save)."""
    from research_utils import extract_article_content, is_domain_blacklisted
    from ollama_client import generate_summary
    from utils.job_tracking import log_job_step

    idx, result = item
    c = ArticleCounters()
    processing_claimed = False
    url = ""
    article_start = time.time()

    try:
        url = result.get("url", "") or ""
        title = result.get("title", "") or ""

        if not url or not title:
            return c

        processing_claimed = bool(ctx.research_repo.claim_processing_url(url))
        if not processing_claimed:
            logger.debug("Article already being processed by another job thread: %s...", title[:40])
            c.skipped += 1
            return c

        try:
            from robots_utils import check_url_allowed

            if not check_url_allowed(url):
                logger.debug("Skipping URL disallowed by robots.txt: %s...", url[:60])
                c.skipped += 1
                return c
        except ImportError:
            pass

        is_blocked, _domain = is_domain_blacklisted(url, ctx.blacklist)
        if is_blocked:
            logger.debug("Skipping explicitly blacklisted: %s", url[:60])
            return c

        if not _has_time_for_stage(
            article_start=article_start,
            max_article_duration=ctx.max_article_duration,
            min_seconds=5.0,
            title=title,
            stage="extraction",
        ):
            c.failed += 1
            return c

        if ctx.research_repo.article_exists(url):
            logger.debug("Article already exists: %s...", title[:50])
            c.skipped += 1
            return c

        log_job_step(
            ctx.job_id,
            "extract",
            f"Extracting article {idx}/{ctx.total_results}: {title[:60]}",
        )
        logger.info("  💎 Extracting Alpha: %s...", title[:40])
        extracted = extract_article_content(
            url,
            max_seconds=_remaining_article_seconds(article_start, ctx.max_article_duration),
        )

        content = extracted.get("content", "")
        if not content or not extracted.get("success"):
            if extracted.get("error") == "extraction_timeout":
                c.failed += 1
            return c

        if not _has_time_for_stage(
            article_start=article_start,
            max_article_duration=ctx.max_article_duration,
            min_seconds=30.0,
            title=title,
            stage="AI summary",
        ):
            c.failed += 1
            return c

        summary = None
        summary_data: dict = {}
        extracted_tickers: list[str] = []
        extracted_sector = None
        embedding = None

        summary_input = f"Title: {title}\n\n{content}" if title else content
        should_summarize, summary_hash = claim_recent_summary_input(summary_input)
        if not should_summarize:
            logger.info("  ⏭️ Skipping duplicate summary hash %s: %s...", summary_hash, title[:40])
            c.skipped += 1
            return c

        log_job_step(ctx.job_id, "ai_summary", f"Generating AI summary for: {title[:60]}")
        summary_data = generate_summary(summary_input, article_type="Alpha Research")

        if isinstance(summary_data, str):
            summary = summary_data
        elif isinstance(summary_data, dict) and summary_data:
            summary = summary_data.get("summary", "")

            from ticker_validator import extract_and_validate_tickers

            extracted_tickers = extract_and_validate_tickers(
                summary_data,
                title,
                content,
            )
            sectors = summary_data.get("sectors", [])

            if extracted_tickers:
                logger.info("  🎯 Discovered ticker(s): %s", extracted_tickers)

            if sectors:
                extracted_sector = sectors[0]

        market_relevance = (
            summary_data.get("market_relevance") if isinstance(summary_data, dict) else None
        )
        has_market_signal = has_strong_market_signal(
            title=title,
            content=content,
            tickers=extracted_tickers,
        )
        if market_relevance == "NOT_MARKET_RELATED" or not has_market_signal:
            reason = (
                summary_data.get("market_relevance_reason", "")
                if isinstance(summary_data, dict)
                else ""
            )
            if not has_market_signal and market_relevance != "NOT_MARKET_RELATED":
                reason = reason or "No strong market signals detected in article text"
            c.irrelevant += 1
            logger.info(
                "  🚫 Skipping non-market alpha article: %s... Reason: %s",
                title[:50],
                reason or "No market relevance detected",
            )
            return c

        if ctx.ollama_client and _has_time_for_stage(
            article_start=article_start,
            max_article_duration=ctx.max_article_duration,
            min_seconds=15.0,
            title=title,
            stage="embedding",
        ):
            embedding = ctx.ollama_client.generate_embedding(content)

        logic_check = summary_data.get("logic_check") if isinstance(summary_data, dict) else None

        article_id = ctx.research_repo.save_article(
            tickers=extracted_tickers if extracted_tickers else None,
            sector=extracted_sector,
            article_type="Alpha Research",
            title=extracted.get("title") or title,
            url=url,
            summary=summary,
            content=content,
            source=extracted.get("source"),
            published_at=extracted.get("published_at"),
            relevance_score=0.85,
            embedding=embedding,
            claims=summary_data.get("claims") if isinstance(summary_data, dict) else None,
            fact_check=summary_data.get("fact_check") if isinstance(summary_data, dict) else None,
            conclusion=summary_data.get("conclusion") if isinstance(summary_data, dict) else None,
            sentiment=summary_data.get("sentiment") if isinstance(summary_data, dict) else None,
            sentiment_score=(
                summary_data.get("sentiment_score") if isinstance(summary_data, dict) else None
            ),
            logic_check=logic_check,
        )

        if article_id:
            c.saved += 1
            article_dur = time.time() - article_start
            log_job_step(
                ctx.job_id,
                "save",
                f"Saved: {title[:60]} ({article_dur:.0f}s)",
                status="success",
                metadata={"tickers": extracted_tickers} if extracted_tickers else None,
            )
            logger.info("  ✅ Saved Alpha Research: %s", title[:30])

        c.processed += 1
        if ctx.sleep_after_article_sec > 0:
            time.sleep(ctx.sleep_after_article_sec)
        return c

    except Exception as e:
        log_job_step(
            ctx.job_id,
            "error",
            f"Error processing article: {str(e)[:100]}",
            status="failed",
        )
        logger.error("Error processing alpha article: %s", e)
        return c
    finally:
        if processing_claimed and url:
            ctx.research_repo.release_processing_url(url)


@dataclass
class OpportunityDiscoveryCtx:
    research_repo: Any
    ollama_client: Any | None
    blacklist: list[str]
    job_id: str
    total_results: int
    max_article_duration: float
    sleep_after_article_sec: float


def process_opportunity_discovery_item(
    ctx: OpportunityDiscoveryCtx,
    item: IndexResult,
) -> ArticleCounters:
    """Single SearXNG result for opportunity discovery."""
    from research_utils import extract_article_content, is_domain_blacklisted
    from ollama_client import generate_summary
    from research_domain_health import DomainHealthTracker
    from utils.job_tracking import log_job_step

    idx, result = item
    c = ArticleCounters()
    processing_claimed = False
    url = ""
    article_start = time.time()

    try:
        url = result.get("url", "") or ""
        title = result.get("title", "") or ""

        if not url or not title:
            return c

        processing_claimed = bool(ctx.research_repo.claim_processing_url(url))
        if not processing_claimed:
            logger.debug("Article already being processed by another job thread: %s...", title[:40])
            c.skipped += 1
            return c

        try:
            from robots_utils import check_url_allowed

            if not check_url_allowed(url):
                logger.debug("Skipping URL disallowed by robots.txt: %s...", url[:60])
                c.skipped += 1
                return c
        except ImportError:
            pass

        is_blocked, domain = is_domain_blacklisted(url, ctx.blacklist)
        if is_blocked:
            logger.debug("Skipping blacklisted: %s", domain)
            c.blacklisted += 1
            return c

        if not _has_time_for_stage(
            article_start=article_start,
            max_article_duration=ctx.max_article_duration,
            min_seconds=5.0,
            title=title,
            stage="extraction",
        ):
            c.failed += 1
            return c

        if ctx.research_repo.article_exists(url):
            logger.debug("Article already exists: %s...", title[:50])
            c.skipped += 1
            return c

        log_job_step(
            ctx.job_id,
            "extract",
            f"Extracting article {idx}/{ctx.total_results}: {title[:60]}",
        )
        logger.info("  💎 Extracting: %s...", title[:40])
        extracted = extract_article_content(
            url,
            max_seconds=_remaining_article_seconds(article_start, ctx.max_article_duration),
        )

        tracker = DomainHealthTracker()

        content = extracted.get("content", "")
        if not content or not extracted.get("success"):
            error_reason = extracted.get("error", "unknown")
            tracker.record_failure(url, error_reason)
            if error_reason == "extraction_timeout":
                c.failed += 1

            if tracker.should_auto_blacklist(url):
                if tracker.auto_blacklist_domain(url):
                    logger.warning("🚫 AUTO-BLACKLISTED: %s", domain)
                    c.blacklisted += 1
            return c

        if not _has_time_for_stage(
            article_start=article_start,
            max_article_duration=ctx.max_article_duration,
            min_seconds=30.0,
            title=title,
            stage="AI summary",
        ):
            c.failed += 1
            return c

        tracker.record_success(url)

        summary = None
        summary_data: dict = {}
        extracted_tickers: list[str] = []
        extracted_ticker = None
        extracted_sector = None
        embedding = None

        summary_input = f"Title: {title}\n\n{content}" if title else content
        should_summarize, summary_hash = claim_recent_summary_input(summary_input)
        if not should_summarize:
            logger.info("  ⏭️ Skipping duplicate summary hash %s: %s...", summary_hash, title[:40])
            c.skipped += 1
            return c

        log_job_step(ctx.job_id, "ai_summary", f"Generating AI summary for: {title[:60]}")
        summary_data = generate_summary(summary_input, article_type="Opportunity Discovery")

        if isinstance(summary_data, str):
            summary = summary_data
        elif isinstance(summary_data, dict) and summary_data:
            summary = summary_data.get("summary", "")

            from ticker_validator import extract_and_validate_tickers

            extracted_tickers = extract_and_validate_tickers(
                summary_data,
                title,
                content,
            )
            sectors = summary_data.get("sectors", [])

            if extracted_tickers:
                extracted_ticker = extracted_tickers[0]
                logger.info("  🎯 Discovered ticker: %s", extracted_ticker)

            if sectors:
                extracted_sector = sectors[0]

        market_relevance = (
            summary_data.get("market_relevance") if isinstance(summary_data, dict) else None
        )
        has_market_signal = has_strong_market_signal(
            title=title,
            content=content,
            tickers=extracted_tickers,
        )
        if market_relevance == "NOT_MARKET_RELATED" or not has_market_signal:
            reason = (
                summary_data.get("market_relevance_reason", "")
                if isinstance(summary_data, dict)
                else ""
            )
            if not has_market_signal and market_relevance != "NOT_MARKET_RELATED":
                reason = reason or "No strong market signals detected in article text"
            c.irrelevant += 1
            logger.info(
                "  🚫 Skipping non-market opportunity: %s... Reason: %s",
                title[:50],
                reason or "No market relevance detected",
            )
            return c

        if ctx.ollama_client and _has_time_for_stage(
            article_start=article_start,
            max_article_duration=ctx.max_article_duration,
            min_seconds=15.0,
            title=title,
            stage="embedding",
        ):
            embedding = ctx.ollama_client.generate_embedding(content)

        logic_check = summary_data.get("logic_check") if isinstance(summary_data, dict) else None

        article_id = ctx.research_repo.save_article(
            tickers=[extracted_ticker] if extracted_ticker else None,
            sector=extracted_sector,
            article_type="Opportunity Discovery",
            title=extracted.get("title") or title,
            url=url,
            summary=summary,
            content=content,
            source=extracted.get("source"),
            published_at=extracted.get("published_at"),
            relevance_score=0.7,
            embedding=embedding,
            claims=summary_data.get("claims") if isinstance(summary_data, dict) else None,
            fact_check=summary_data.get("fact_check") if isinstance(summary_data, dict) else None,
            conclusion=summary_data.get("conclusion") if isinstance(summary_data, dict) else None,
            sentiment=summary_data.get("sentiment") if isinstance(summary_data, dict) else None,
            sentiment_score=(
                summary_data.get("sentiment_score") if isinstance(summary_data, dict) else None
            ),
            logic_check=logic_check,
        )

        if article_id:
            c.saved += 1
            article_dur = time.time() - article_start
            log_job_step(
                ctx.job_id,
                "save",
                f"Saved: {title[:60]} ({article_dur:.0f}s)",
                status="success",
                metadata={"tickers": extracted_tickers} if extracted_tickers else None,
            )
            logger.info("  ✅ Saved opportunity: %s", title[:30])

            if isinstance(summary_data, dict) and logic_check and logic_check != "HYPE_DETECTED":
                relationships = summary_data.get("relationships", [])
                if relationships and isinstance(relationships, list):
                    initial_confidence = 0.8 if logic_check == "DATA_BACKED" else 0.4

                    from research_utils import normalize_relationship

                    relationships_saved = 0
                    for rel in relationships:
                        if isinstance(rel, dict):
                            source = rel.get("source", "").strip()
                            target = rel.get("target", "").strip()
                            rel_type = rel.get("type", "").strip()

                            if source and target and rel_type:
                                norm_source, norm_target, norm_type = normalize_relationship(
                                    source, target, rel_type
                                )
                                rel_id = ctx.research_repo.save_relationship(
                                    source_ticker=norm_source,
                                    target_ticker=norm_target,
                                    relationship_type=norm_type,
                                    initial_confidence=initial_confidence,
                                    source_article_id=article_id,
                                )
                                if rel_id:
                                    relationships_saved += 1

                    if relationships_saved > 0:
                        logger.info(
                            "  ✅ Saved %s relationship(s) from opportunity article: %s",
                            relationships_saved,
                            title[:30],
                        )

        c.processed += 1
        if ctx.sleep_after_article_sec > 0:
            time.sleep(ctx.sleep_after_article_sec)
        return c

    except Exception as e:
        log_job_step(
            ctx.job_id,
            "error",
            f"Error processing article: {str(e)[:100]}",
            status="failed",
        )
        logger.error("Error processing discovery article: %s", e)
        return c
    finally:
        if processing_claimed and url:
            ctx.research_repo.release_processing_url(url)
