"""Per-item worker for ``rss_feed_ingest_job``."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from scheduler.article_pipeline import ArticleCounters
from scheduler.jobs_common import (
    calculate_relevance_score,
    claim_recent_summary_input,
    has_strong_market_signal,
)

logger = logging.getLogger(__name__)


@dataclass
class RssFeedItemCtx:
    research_repo: Any
    ollama_client: Optional[Any]
    owned_tickers: set[str]
    feed_name: str
    sleep_after_article_sec: float


def _extract_tickers(summary_data: dict, title: str, article_text: str) -> list[str]:
    from ticker_validator import extract_and_validate_tickers

    return extract_and_validate_tickers(summary_data, title, article_text)


def process_rss_feed_item(ctx: RssFeedItemCtx, item: dict) -> ArticleCounters:
    from ollama_client import generate_summary
    from research_utils import extract_article_content

    c = ArticleCounters()
    try:
        url = item.get("url")
        title = item.get("title")
        content = item.get("content", "")

        if not url or not title:
            return c

        try:
            from robots_utils import check_url_allowed

            if not check_url_allowed(url):
                logger.info("  Skipping URL disallowed by robots.txt: %s...", url[:60])
                c.skipped += 1
                return c
        except ImportError:
            pass

        if ctx.research_repo.article_exists(url):
            logger.debug("Article already exists: %s...", title[:50])
            c.skipped += 1
            return c

        if not content or len(content) < 200:
            logger.info("  Extracting full content: %s...", title[:40])
            extracted = extract_article_content(url)

            if extracted.get("error") == "paid_subscription":
                if extracted.get("archive_submitted"):
                    logger.info("  Paywalled article submitted to archive, saving for retry: %s...", title[:40])
                    article_id = ctx.research_repo.save_article(
                        tickers=None,
                        sector=None,
                        article_type="Market News",
                        title=title,
                        url=url,
                        summary="[Paywalled - Submitted to archive for processing]",
                        content="[Paywalled - Submitted to archive for processing]",
                        source=item.get("source"),
                        published_at=item.get("published_at"),
                        relevance_score=0.0,
                        embedding=None,
                    )
                    if article_id:
                        ctx.research_repo.mark_archive_submitted(article_id, url)
                        c.skipped += 1
                        logger.info("  Saved paywalled article for archive retry: %s", article_id)
                else:
                    logger.info("  Skipping paid subscription article: %s...", title[:40])
                    c.skipped += 1
                return c

            content = extracted.get("content", "")
            if not content:
                logger.warning("Failed to extract content for %s...", title[:40])
                return c

        summary = None
        summary_data: dict = {}
        extracted_tickers: Sequence[str] = item.get("tickers", []) or []
        extracted_tickers = list(extracted_tickers)
        extracted_sector = None
        embedding = None

        summary_input = f"Title: {title}\n\n{content}" if title else content
        should_summarize, summary_hash = claim_recent_summary_input(summary_input)
        if not should_summarize:
            logger.info("  ⏭️ Skipping duplicate summary hash %s: %s...", summary_hash, title[:40])
            c.skipped += 1
            return c
        summary_data = generate_summary(summary_input, article_type="Market News")

        if isinstance(summary_data, str):
            summary = summary_data
        elif isinstance(summary_data, dict) and summary_data:
            summary = summary_data.get("summary", "")
            if not extracted_tickers:
                extracted_tickers = _extract_tickers(summary_data, str(title), str(content))
            sectors = summary_data.get("sectors", [])
            if sectors:
                extracted_sector = sectors[0]

        market_relevance = summary_data.get("market_relevance") if isinstance(summary_data, dict) else None
        has_sig = has_strong_market_signal(title=str(title), content=str(content), tickers=extracted_tickers)
        if market_relevance == "NOT_MARKET_RELATED" or not has_sig:
            reason = summary_data.get("market_relevance_reason", "") if isinstance(summary_data, dict) else ""
            if not has_sig and market_relevance != "NOT_MARKET_RELATED":
                reason = reason or "No strong market signals detected in RSS content"
            c.irrelevant += 1
            logger.info(
                "  🚫 Skipping non-market RSS item: %s... Reason: %s",
                title[:40],
                reason or "No market relevance detected",
            )
            return c

        if ctx.ollama_client:
            embedding = ctx.ollama_client.generate_embedding(content)

        relevance_score = calculate_relevance_score(
            extracted_tickers if extracted_tickers else [],
            extracted_sector,
            owned_tickers=list(ctx.owned_tickers) if ctx.owned_tickers else None,
        )
        logic_check = summary_data.get("logic_check") if isinstance(summary_data, dict) else None

        article_id = ctx.research_repo.save_article(
            tickers=extracted_tickers if extracted_tickers else None,
            sector=extracted_sector,
            article_type="Market News",
            title=title,
            url=url,
            summary=summary,
            content=content,
            source=item.get("source"),
            published_at=item.get("published_at"),
            relevance_score=relevance_score,
            embedding=embedding,
            claims=summary_data.get("claims") if isinstance(summary_data, dict) else None,
            fact_check=summary_data.get("fact_check") if isinstance(summary_data, dict) else None,
            conclusion=summary_data.get("conclusion") if isinstance(summary_data, dict) else None,
            sentiment=summary_data.get("sentiment") if isinstance(summary_data, dict) else None,
            sentiment_score=summary_data.get("sentiment_score") if isinstance(summary_data, dict) else None,
            logic_check=logic_check,
        )

        if article_id:
            c.saved += 1
            logger.info("  ✅ Saved: %s...", title[:40])

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
                        logger.info("  ✅ Saved %s relationship(s)", relationships_saved)

        c.processed += 1
        if ctx.sleep_after_article_sec > 0:
            time.sleep(ctx.sleep_after_article_sec)
        return c

    except Exception as e:
        logger.error("Error processing RSS item: %s", e)
        c.failed += 1
        return c
