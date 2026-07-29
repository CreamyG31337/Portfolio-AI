"""Per-article worker for ``market_research_job`` (SearXNG batch)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from scheduler.article_pipeline import ArticleCounters
from scheduler.jobs_common import (
    calculate_relevance_score,
    claim_recent_summary_input,
    has_strong_market_signal,
)

logger = logging.getLogger(__name__)


@dataclass
class MarketResearchCtx:
    job_id: str
    job_start_time: float
    research_repo: Any
    ollama_client: Optional[Any]
    blacklist: list[str]
    total_results: int
    max_job_duration: float
    max_article_duration: float


def _extract_tickers(summary_data: dict, title: str, article_text: str) -> list[str]:
    from ticker_validator import extract_and_validate_tickers

    return extract_and_validate_tickers(summary_data, title, article_text)


def process_market_research_pair(ctx: MarketResearchCtx, pair: tuple[int, dict]) -> ArticleCounters:
    """Process one SearXNG result: claim URL, extract, summarize, save."""
    from ollama_client import generate_summary
    from research_utils import extract_article_content, is_domain_blacklisted
    from utils.job_tracking import log_job_step

    idx, result = pair
    c = ArticleCounters()
    if time.time() - ctx.job_start_time > ctx.max_job_duration:
        return c

    article_start = time.time()
    processing_claimed = False
    url = ""
    try:
        url = result.get("url", "") or ""
        title = result.get("title", "") or ""

        if not url or not title:
            return c

        processing_claimed = bool(ctx.research_repo.claim_processing_url(url))
        if not processing_claimed:
            logger.debug("Article already being processed by another job thread: %s...", title[:50])
            c.skipped += 1
            return c

        try:
            from robots_utils import check_url_allowed

            if not check_url_allowed(url):
                logger.info("ℹ️ Skipping URL disallowed by robots.txt: %s...", url[:60])
                c.skipped += 1
                return c
        except ImportError:
            pass

        is_blocked, domain = is_domain_blacklisted(url, ctx.blacklist)
        if is_blocked:
            logger.info("ℹ️ Skipping blacklisted domain: %s", domain)
            c.blacklisted += 1
            return c

        if ctx.research_repo.article_exists(url):
            logger.debug("Article already exists: %s...", title[:50])
            c.skipped += 1
            return c

        from story_identity import try_corroborate_incoming_story

        story_match = try_corroborate_incoming_story(
            ctx.research_repo,
            title=title,
            source=result.get("engine") or result.get("source"),
            url=url,
        )
        if story_match is not None:
            logger.info(
                "  🔗 Story corroboration (skip extract): matched %s… sim=%.3f%s",
                story_match.title[:50],
                story_match.similarity,
                " [containment]" if story_match.via_containment else "",
            )
            c.skipped += 1
            return c

        if time.time() - article_start > ctx.max_article_duration:
            logger.warning("⏱️  Article timeout (%.1fs) - skipping: %s...", time.time() - article_start, title[:50])
            return c

        log_job_step(ctx.job_id, "extract", f"Extracting article {idx}/{ctx.total_results}: {title[:60]}")
        logger.info("  Extracting content: %s...", title[:50])
        extracted = extract_article_content(url)

        if time.time() - article_start > ctx.max_article_duration:
            logger.warning(
                "⏱️  Article timeout after extraction (%.1fs) - skipping AI: %s...",
                time.time() - article_start,
                title[:50],
            )
            return c

        if extracted.get("error") == "paid_subscription":
            if extracted.get("archive_submitted"):
                logger.info("Paywalled article submitted to archive, saving for retry: %s...", title[:50])
                article_id = ctx.research_repo.save_article(
                    tickers=None,
                    sector=None,
                    article_type="Market News",
                    title=title,
                    url=url,
                    summary="[Paywalled - Submitted to archive for processing]",
                    content="[Paywalled - Submitted to archive for processing]",
                    source=extracted.get("source"),
                    published_at=None,
                    relevance_score=0.0,
                    embedding=None,
                )
                if article_id:
                    ctx.research_repo.mark_archive_submitted(article_id, url)
                    c.skipped += 1
                    logger.info("Saved paywalled article for archive retry: %s", article_id)
            else:
                logger.info("Skipping paid subscription article: %s...", title[:50])
                c.skipped += 1
            return c

        from research_domain_health import DomainHealthTracker, normalize_domain
        from settings import get_system_setting

        tracker = DomainHealthTracker()
        threshold = get_system_setting("auto_blacklist_threshold", default=4)

        content = extracted.get("content", "")
        if not content or not extracted.get("success"):
            error_reason = extracted.get("error", "unknown")
            failure_count = tracker.record_failure(url, error_reason)
            dom = normalize_domain(url)
            logger.warning(
                "⚠️ Domain extraction failed: %s (failure %s/%s) - Reason: %s",
                dom,
                failure_count,
                threshold,
                error_reason,
            )
            if tracker.should_auto_blacklist(url):
                if tracker.auto_blacklist_domain(url):
                    logger.warning(
                        "🚫 AUTO-BLACKLISTED: %s (%s consecutive failures of type: %s)",
                        dom,
                        failure_count,
                        error_reason,
                    )
                    c.blacklisted += 1
                else:
                    logger.warning("Failed to auto-blacklist %s", dom)
            return c

        tracker.record_success(url)

        article_elapsed = time.time() - article_start
        remaining_time = ctx.max_article_duration - article_elapsed
        if remaining_time < 60:
            logger.warning(
                "⏱️  Not enough time for AI processing (%.1fs remaining) - skipping: %s...",
                remaining_time,
                title[:50],
            )
            return c

        summary = None
        summary_data: dict = {}
        extracted_tickers: list[str] = []
        extracted_sector = None
        embedding = None
        log_job_step(ctx.job_id, "ai_summary", f"Generating AI summary for: {title[:60]}")
        logger.info("  Generating summary for: %s...", title[:50])
        summary_input = f"Title: {title}\n\n{content}" if title else content
        should_summarize, summary_hash = claim_recent_summary_input(summary_input)
        if not should_summarize:
            logger.info("  ⏭️ Skipping duplicate summary hash %s: %s...", summary_hash, title[:50])
            c.skipped += 1
            return c
        summary_data = generate_summary(summary_input, article_type="Market News")

        if isinstance(summary_data, str):
            summary = summary_data
        elif isinstance(summary_data, dict) and summary_data:
            summary = summary_data.get("summary", "")
            extracted_tickers = _extract_tickers(summary_data, title, content)
            if extracted_tickers:
                logger.info("Extracted %s validated ticker(s): %s", len(extracted_tickers), extracted_tickers)
            sectors = summary_data.get("sectors", [])
            if sectors:
                extracted_sector = sectors[0]
                logger.info("Extracted sector from article: %s", extracted_sector)
            if extracted_tickers or sectors:
                logger.debug(
                    "Extracted metadata - Tickers: %s, Sectors: %s, Themes: %s",
                    extracted_tickers,
                    sectors,
                    summary_data.get("key_themes", []),
                )

        if not summary:
            logger.warning("Failed to generate summary for %s...", title[:50])

        market_relevance = summary_data.get("market_relevance") if isinstance(summary_data, dict) else None
        has_sig = has_strong_market_signal(title=title, content=content, tickers=extracted_tickers)
        if market_relevance == "NOT_MARKET_RELATED" or not has_sig:
            reason = summary_data.get("market_relevance_reason", "") if isinstance(summary_data, dict) else ""
            if not has_sig and market_relevance != "NOT_MARKET_RELATED":
                reason = reason or "No strong market signals detected in article text"
            c.irrelevant += 1
            logger.info(
                "  🚫 Skipping non-market article: %s... Reason: %s",
                title[:50],
                reason or "No market relevance detected",
            )
            return c

        if ctx.ollama_client:
            logger.debug("Generating embedding for: %s...", title[:50])
            embedding = ctx.ollama_client.generate_embedding(content)
            if not embedding:
                logger.warning("Failed to generate embedding for %s...", title[:50])
        else:
            logger.debug("Ollama not available - skipping embedding generation")

        relevance_score = calculate_relevance_score(extracted_tickers, extracted_sector, owned_tickers=None)
        logic_check = summary_data.get("logic_check") if isinstance(summary_data, dict) else None

        article_id = ctx.research_repo.save_article(
            tickers=extracted_tickers if extracted_tickers else None,
            sector=extracted_sector,
            article_type="Market News",
            title=extracted.get("title") or title,
            url=url,
            summary=summary,
            content=content,
            source=extracted.get("source"),
            published_at=extracted.get("published_at"),
            relevance_score=relevance_score,
            embedding=embedding,
            claims=summary_data.get("claims") if isinstance(summary_data, dict) else None,
            fact_check=summary_data.get("fact_check") if isinstance(summary_data, dict) else None,
            conclusion=summary_data.get("conclusion") if isinstance(summary_data, dict) else None,
            sentiment=summary_data.get("sentiment") if isinstance(summary_data, dict) else None,
            sentiment_score=summary_data.get("sentiment_score") if isinstance(summary_data, dict) else None,
            logic_check=logic_check,
        )

        article_duration = time.time() - article_start

        if article_id:
            c.saved += 1
            log_job_step(
                ctx.job_id,
                "save",
                f"Saved: {title[:60]} ({article_duration:.0f}s)",
                status="success",
                metadata={"tickers": extracted_tickers} if extracted_tickers else None,
            )
            logger.info("✅ Saved article in %.1fs: %s...", article_duration, title[:50])

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
                            "✅ Saved %s relationship(s) from article: %s...",
                            relationships_saved,
                            title[:50],
                        )
        else:
            logger.warning("Failed to save article: %s...", title[:50])

        c.processed += 1
        return c

    except Exception as e:
        article_duration = time.time() - article_start
        title_safe = result.get("title", "Unknown")[:50] if result else "Unknown"
        log_job_step(ctx.job_id, "error", f"Error processing article: {str(e)[:100]}", status="failed")
        logger.error("❌ Error processing article after %.1fs '%s...': %s", article_duration, title_safe, e)
        return c
    finally:
        if processing_claimed and url:
            ctx.research_repo.release_processing_url(url)
