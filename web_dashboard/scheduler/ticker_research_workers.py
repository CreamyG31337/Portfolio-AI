"""Per-result workers for ``ticker_research_job`` (ETF sector + regular ticker SearXNG batches)."""

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
class SectorArticleCtx:
    research_repo: Any
    ollama_client: Optional[Any]
    blacklist: list[str]
    sector: str
    result_deadline: float
    sleep_after_article_sec: float


def process_sector_search_result(ctx: SectorArticleCtx, result: dict) -> ArticleCounters:
    from ollama_client import generate_summary
    from research_utils import extract_article_content, is_domain_blacklisted

    c = ArticleCounters()
    processing_claimed = False
    url = ""
    try:
        if time.time() > ctx.result_deadline:
            return c

        url = result.get("url", "") or ""
        title = result.get("title", "") or ""
        if not url or not title:
            return c

        try:
            from robots_utils import check_url_allowed

            if not check_url_allowed(url):
                logger.debug("Skipping URL disallowed by robots.txt: %s...", url[:60])
                return c
        except ImportError:
            pass

        is_blocked, domain = is_domain_blacklisted(url, ctx.blacklist)
        if is_blocked:
            logger.debug("Skipping blacklisted: %s", domain)
            return c

        processing_claimed = bool(ctx.research_repo.claim_processing_url(url))
        if not processing_claimed:
            logger.debug("Article already being processed by another job thread: %s...", title[:40])
            c.skipped += 1
            return c

        if ctx.research_repo.article_exists(url):
            return c

        logger.info("  Extracting: %s...", title[:40])
        extracted = extract_article_content(url)
        content = extracted.get("content", "")
        if not content:
            return c

        summary = None
        summary_data: dict = {}
        embedding = None
        summary_input = f"Title: {title}\n\n{content}" if title else content
        should_summarize, summary_hash = claim_recent_summary_input(summary_input)
        if not should_summarize:
            logger.info("  ⏭️ Skipping duplicate summary hash %s: %s...", summary_hash, title[:40])
            c.skipped += 1
            return c
        summary_data = generate_summary(summary_input, article_type="Ticker News")

        if isinstance(summary_data, str):
            summary = summary_data
        elif isinstance(summary_data, dict) and summary_data:
            summary = summary_data.get("summary", "")

        market_relevance = summary_data.get("market_relevance") if isinstance(summary_data, dict) else None
        has_sig = has_strong_market_signal(
            title=title,
            content=content,
            required_terms=[ctx.sector],
        )
        if market_relevance == "NOT_MARKET_RELATED" or not has_sig:
            reason = summary_data.get("market_relevance_reason", "") if isinstance(summary_data, dict) else ""
            if not has_sig and market_relevance != "NOT_MARKET_RELATED":
                reason = reason or "No strong market signals detected for sector query"
            c.irrelevant += 1
            logger.info(
                "  🚫 Skipping non-market sector article: %s... Reason: %s",
                title[:40],
                reason or "No market relevance detected",
            )
            return c

        if ctx.ollama_client:
            embedding = ctx.ollama_client.generate_embedding(content)
            if not embedding:
                logger.warning("Failed to generate embedding for sector %s", ctx.sector)

        logic_check = summary_data.get("logic_check") if isinstance(summary_data, dict) else None

        article_id = ctx.research_repo.save_article(
            tickers=None,
            sector=ctx.sector,
            article_type="Ticker News",
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
            sentiment_score=summary_data.get("sentiment_score") if isinstance(summary_data, dict) else None,
            logic_check=logic_check,
        )

        if article_id:
            c.saved += 1
            logger.info("  ✅ Saved sector news: %s", title[:30])

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
                            "  ✅ Saved %s relationship(s) from sector article: %s",
                            relationships_saved,
                            title[:30],
                        )

        if ctx.sleep_after_article_sec > 0:
            time.sleep(ctx.sleep_after_article_sec)
        return c

    except Exception as e:
        logger.error("Error processing sector article for %s: %s", ctx.sector, e)
        c.failed += 1
        return c
    finally:
        if processing_claimed and url:
            ctx.research_repo.release_processing_url(url)


@dataclass
class TickerArticleCtx:
    research_repo: Any
    ollama_client: Optional[Any]
    blacklist: list[str]
    ticker: str
    company: str
    owned_tickers: set[str]
    result_deadline: float
    sleep_after_article_sec: float


def _extract_tickers(summary_data: dict, title: str, article_text: str) -> list[str]:
    from ticker_validator import extract_and_validate_tickers

    return extract_and_validate_tickers(summary_data, title, article_text)


def process_ticker_search_result(ctx: TickerArticleCtx, result: dict) -> ArticleCounters:
    from ollama_client import generate_summary
    from research_utils import extract_article_content, is_domain_blacklisted

    c = ArticleCounters()
    processing_claimed = False
    url = ""
    try:
        if time.time() > ctx.result_deadline:
            return c

        url = result.get("url", "") or ""
        title = result.get("title", "") or ""
        if not url or not title:
            return c

        try:
            from robots_utils import check_url_allowed

            if not check_url_allowed(url):
                logger.debug("Skipping URL disallowed by robots.txt: %s...", url[:60])
                return c
        except ImportError:
            pass

        is_blocked, domain = is_domain_blacklisted(url, ctx.blacklist)
        if is_blocked:
            logger.debug("Skipping blacklisted: %s", domain)
            return c

        processing_claimed = bool(ctx.research_repo.claim_processing_url(url))
        if not processing_claimed:
            logger.debug("Article already being processed by another job thread: %s...", title[:40])
            c.skipped += 1
            return c

        if ctx.research_repo.article_exists(url):
            return c

        logger.info("  Extracting: %s...", title[:40])
        extracted = extract_article_content(url)
        content = extracted.get("content", "")
        if not content:
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
        summary_data = generate_summary(summary_input, article_type="Ticker News")

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

        market_relevance = summary_data.get("market_relevance") if isinstance(summary_data, dict) else None
        required_terms: list[str] = [ctx.ticker]
        if ctx.company and ctx.company.lower() != "none":
            required_terms.append(ctx.company)
        has_sig = has_strong_market_signal(
            title=title,
            content=content,
            tickers=extracted_tickers,
            required_terms=required_terms,
        )
        if market_relevance == "NOT_MARKET_RELATED" or not has_sig:
            reason = summary_data.get("market_relevance_reason", "") if isinstance(summary_data, dict) else ""
            if not has_sig and market_relevance != "NOT_MARKET_RELATED":
                reason = reason or "No strong market signals detected for ticker query"
            c.irrelevant += 1
            logger.info(
                "  🚫 Skipping non-market ticker article: %s... Reason: %s",
                title[:40],
                reason or "No market relevance detected",
            )
            return c

        if ctx.ollama_client:
            embedding = ctx.ollama_client.generate_embedding(content)
            if not embedding:
                logger.warning("Failed to generate embedding for %s", ctx.ticker)

        relevance_score = calculate_relevance_score(
            extracted_tickers, extracted_sector, owned_tickers=ctx.owned_tickers
        )
        logic_check = summary_data.get("logic_check") if isinstance(summary_data, dict) else None

        article_id = ctx.research_repo.save_article(
            tickers=extracted_tickers if extracted_tickers else None,
            sector=extracted_sector,
            article_type="Ticker News",
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

        if article_id:
            c.saved += 1
            logger.info("  ✅ Saved: %s", title[:30])

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
                        logger.info("  ✅ Saved %s relationship(s) from article: %s", relationships_saved, title[:30])

        if ctx.sleep_after_article_sec > 0:
            time.sleep(ctx.sleep_after_article_sec)
        return c

    except Exception as e:
        logger.error("Error processing article for %s: %s", ctx.ticker, e)
        c.failed += 1
        return c
    finally:
        if processing_claimed and url:
            ctx.research_repo.release_processing_url(url)
