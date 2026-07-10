#!/usr/bin/env python3
"""Probe: draft moat theses for holdings using Research DB + optional SearXNG.

Dry-run by default (prints drafts). Pass --write to create Insights theses.
Pass --ticker AAPL to limit to one symbol. Pass --limit N for first N holdings.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPT = Path(__file__).resolve()
_WEB = _SCRIPT.parent.parent
_ROOT = _WEB.parent
for p in (str(_WEB), str(_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from env_loader import load_project_dotenv

load_project_dotenv()


def _holdings(fund: str) -> list[str]:
    from supabase_client import SupabaseClient

    client = SupabaseClient(use_service_role=True)
    positions = client.get_current_positions(fund) or []
    tickers: list[str] = []
    seen: set[str] = set()
    for row in positions:
        t = (row.get("ticker") or row.get("symbol") or "").upper().strip()
        if not t or t in seen:
            continue
        seen.add(t)
        tickers.append(t)
    return sorted(tickers)


def _ticker_articles(pg: Any, ticker: str, limit: int = 8) -> list[dict[str, Any]]:
    rows = pg.execute_query(
        """
        SELECT id, title, article_type, source, summary,
               LEFT(COALESCE(content, ''), 1200) AS content_snip,
               published_at
        FROM research_articles
        WHERE %s = ANY(tickers)
           OR title ILIKE %s
           OR summary ILIKE %s
        ORDER BY COALESCE(published_at, fetched_at) DESC NULLS LAST
        LIMIT %s
        """,
        (ticker, f"%{ticker}%", f"%{ticker}%", limit),
    )
    return [dict(r) for r in rows]


def _semantic_moat(pg: Any, ticker: str, limit: int = 5) -> list[dict[str, Any]]:
    from ollama_client import get_ollama_client

    client = get_ollama_client()
    if not client:
        return []
    query = f"{ticker} competitive moat durable advantage business model"
    emb = client.generate_embedding(query)
    if not emb:
        return []
    embedding_str = "[" + ",".join(str(float(x)) for x in emb) + "]"
    # Prefer ticker-tagged hits; fall back to global similarity.
    rows = pg.execute_query(
        """
        SELECT id, title, article_type, source, summary,
               1 - (embedding <=> %s::vector) AS similarity
        FROM research_articles
        WHERE embedding IS NOT NULL
          AND %s = ANY(tickers)
          AND 1 - (embedding <=> %s::vector) >= 0.35
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (embedding_str, ticker, embedding_str, embedding_str, limit),
    )
    if rows:
        return [dict(r) for r in rows]
    rows = pg.execute_query(
        """
        SELECT id, title, article_type, source, summary,
               1 - (embedding <=> %s::vector) AS similarity
        FROM research_articles
        WHERE embedding IS NOT NULL
          AND (
            title ILIKE %s OR summary ILIKE %s
            OR COALESCE(content, '') ILIKE %s
          )
          AND 1 - (embedding <=> %s::vector) >= 0.40
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (
            embedding_str,
            f"%{ticker}%",
            f"%{ticker}%",
            f"%{ticker}%",
            embedding_str,
            embedding_str,
            limit,
        ),
    )
    return [dict(r) for r in rows]


def _web_search(ticker: str, company_hint: str = "") -> list[dict[str, str]]:
    try:
        from searxng_client import get_searxng_client, check_searxng_health

        if not check_searxng_health():
            return []
        sx = get_searxng_client()
        if not sx:
            return []
        q = f"{ticker} {company_hint} competitive moat competitive advantage".strip()
        data = sx.search_web(q, max_results=5) or {}
        results = data.get("results") or data.get("items") or []
        out: list[dict[str, str]] = []
        for r in results[:5]:
            out.append(
                {
                    "title": str(r.get("title") or ""),
                    "url": str(r.get("url") or ""),
                    "snippet": str(r.get("content") or r.get("snippet") or "")[:400],
                }
            )
        return out
    except Exception as exc:
        print(f"  [searxng] skipped: {exc}")
        return []


def _company_name(pg: Any, ticker: str) -> str:
    rows = pg.execute_query(
        "SELECT name FROM securities WHERE ticker = %s LIMIT 1",
        (ticker,),
    )
    if rows and rows[0].get("name"):
        return str(rows[0]["name"])
    return ""


def _build_context(
    ticker: str,
    company: str,
    articles: list[dict[str, Any]],
    semantic: list[dict[str, Any]],
    web: list[dict[str, str]],
) -> str:
    parts = [f"Ticker: {ticker}", f"Company: {company or 'unknown'}"]
    parts.append("\n## Research DB articles (ticker-tagged / title match)")
    if not articles:
        parts.append("(none found)")
    for a in articles:
        parts.append(
            f"- [{a.get('article_type')}] {a.get('title')} "
            f"(source={a.get('source')})\n  summary: {(a.get('summary') or '')[:500]}\n"
            f"  snip: {(a.get('content_snip') or '')[:500]}"
        )
    parts.append("\n## Semantic search (moat query)")
    if not semantic:
        parts.append("(none found)")
    for a in semantic:
        sim = a.get("similarity")
        sim_s = f"{float(sim):.2f}" if sim is not None else "?"
        parts.append(
            f"- sim={sim_s} [{a.get('article_type')}] {a.get('title')}\n"
            f"  {(a.get('summary') or '')[:500]}"
        )
    parts.append("\n## Web search (SearXNG)")
    if not web:
        parts.append("(unavailable or empty)")
    for w in web:
        parts.append(f"- {w['title']}\n  {w['url']}\n  {w['snippet']}")
    return "\n".join(parts)


def _draft_moat(ticker: str, context: str) -> dict[str, Any]:
    from ollama_client import get_ollama_client

    client = get_ollama_client()
    if not client:
        raise RuntimeError("Ollama client unavailable")

    prompt = f"""You are helping draft a human investment thesis about competitive moat.

Using ONLY the context below, write a JSON object with keys:
- disposition: "bullish" if a credible moat/advantage is supported by evidence,
  "bearish" if evidence is weak/absent or points to no durable advantage,
  "neutral" if mixed/insufficient.
- confidence: 0.0-1.0
- title: short thesis title (no more than 80 chars), prefix with "[LLM draft] "
- body: 3-8 short paragraphs / bullets for an Insights opening note.
  Cite which sources you used (research report titles or URLs).
  Explicitly say if evidence came only from web search vs uploaded research.
  If you cannot find a moat, say so clearly and set disposition bearish or neutral.
- evidence_urls: list of URLs from context worth attaching (may be empty)
- used_local_research: true/false
- used_web: true/false

Return ONLY valid JSON.

CONTEXT:
{context[:9000]}
"""
    import os

    model = os.getenv("OLLAMA_SUMMARIZING_MODEL") or None
    text = client.generate_completion(prompt, model=model, json_mode=True, temperature=0.2)
    if not text:
        raise RuntimeError("generate_completion returned empty")

    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(raw[start : end + 1])
        else:
            parsed = {
                "disposition": "neutral",
                "confidence": 0.2,
                "title": f"[LLM draft] Moat — {ticker}",
                "body": raw[:4000],
                "evidence_urls": [],
                "used_local_research": False,
                "used_web": False,
                "parse_error": True,
            }
    body = parsed.get("body")
    if isinstance(body, list):
        parsed["body"] = "\n\n".join(str(p).strip() for p in body if str(p).strip())
    elif body is not None and not isinstance(body, str):
        parsed["body"] = str(body)
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe moat thesis drafts for holdings")
    parser.add_argument("--fund", default="Project Chimera")
    parser.add_argument("--ticker", action="append", default=[])
    parser.add_argument("--limit", type=int, default=3, help="Max holdings when not using --ticker/--all-holdings")
    parser.add_argument(
        "--all-holdings",
        action="store_true",
        help="Process every holding in --fund (ignores --limit)",
    )
    parser.add_argument("--write", action="store_true", help="Create Insights theses")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip tickers that already have an active thesis (keeps prior drafts)",
    )
    parser.add_argument("--no-web", action="store_true", help="Skip SearXNG")
    parser.add_argument("--author", default="llm-moat-probe@local")
    args = parser.parse_args()

    from postgres_client import PostgresClient
    from user_insights_service import create_thesis, list_theses

    pg = PostgresClient()

    if args.ticker:
        tickers = [t.upper().strip() for t in args.ticker]
    elif args.all_holdings:
        tickers = _holdings(args.fund)
    else:
        tickers = _holdings(args.fund)[: max(1, args.limit)]

    if args.skip_existing:
        existing = list_theses(pg, include_archived=False, limit=500)
        have = {(r.get("ticker") or "").upper() for r in existing}
        before = len(tickers)
        tickers = [t for t in tickers if t not in have]
        print(f"skip-existing: {before - len(tickers)} already have theses, {len(tickers)} remaining")

    print(f"Fund={args.fund} tickers={tickers} write={args.write}")
    print("=" * 60)

    for ticker in tickers:
        print(f"\n### {ticker}", flush=True)
        company = _company_name(pg, ticker)
        articles = _ticker_articles(pg, ticker)
        print(f"  company={company or '?'}")
        print(f"  ticker-tagged articles={len(articles)}")
        semantic: list[dict[str, Any]] = []
        try:
            semantic = _semantic_moat(pg, ticker)
            print(f"  semantic hits={len(semantic)}")
        except Exception as exc:
            print(f"  semantic failed: {exc}")
        web: list[dict[str, str]] = []
        if not args.no_web:
            web = _web_search(ticker, company)
            print(f"  web hits={len(web)}")
        ctx = _build_context(ticker, company, articles, semantic, web)
        try:
            draft = _draft_moat(ticker, ctx)
        except Exception as exc:
            print(f"  draft FAILED: {exc}")
            continue

        print(f"  disposition={draft.get('disposition')} confidence={draft.get('confidence')}")
        print(f"  title={draft.get('title')}")
        print(f"  local={draft.get('used_local_research')} web={draft.get('used_web')}")
        body = str(draft.get("body") or "")
        print("  --- body ---")
        try:
            print(body[:1500])
        except UnicodeEncodeError:
            print(body[:1500].encode("ascii", errors="replace").decode("ascii"))
        print("  ------------")

        if args.write:
            intent = "monitor"
            disp = str(draft.get("disposition") or "neutral").lower()
            if disp not in ("bullish", "bearish", "neutral"):
                disp = "neutral"
            urls = draft.get("evidence_urls") or []
            source_url = urls[0] if urls else None
            detail = create_thesis(
                pg,
                ticker=ticker,
                title=str(draft.get("title") or f"[LLM draft] Moat — {ticker}"),
                disposition=disp,
                intent=intent,
                body=body + "\n\n_(Generated by moat probe script; review before trusting.)_",
                created_by=args.author,
                source_url=source_url,
                source_type="llm_moat_probe",
                tags=["llm_draft", "moat"],
            )
            print(f"  CREATED thesis id={detail.get('id')}", flush=True)

    return 0


if __name__ == "__main__":
    # Ensure web_dashboard imports resolve when run as script
    import os

    os.chdir(_WEB)
    sys.exit(main())
