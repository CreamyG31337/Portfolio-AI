"""Industry-thesis pass for general-interest YouTube channels.

Sources with ``alpha_mechanism = 'INDUSTRY'`` (Business Insider, Maxinomics) make
explainer videos about industries and products. They rarely name a tradable
angle outright, so the normal summary only tags the household names they
mention. This pass asks GLM for the industry dynamics in the video, the kind of
company each dynamic helps or hurts, and specific listed companies that fit.

Measured on 9 videos (2026-11-11, notes in the commit): GLM finds real
second-order angles, but its own verdict marked 8 of 9 videos worth a look,
including a Turkish marble documentary, and most candidates come from the
model's prior knowledge rather than the transcript. So the filtering is done
here in code, not by trusting the model:

- a thesis is kept only when its supporting quote is actually in the transcript;
- a candidate needs ``confidence >= MIN_CONFIDENCE`` (0.6);
- a ticker is kept only when ``ticker_validator`` confirms it exists and its
  real company name matches the name GLM gave.

Survivors go to ``yt_industry_ideas``. They are never written to
``research_articles.tickers``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

INDUSTRY_MECHANISM = "INDUSTRY"

# 0.6, not 0.5: at 0.5 the Turkish marble video still yielded two 0.55 saw-maker
# ideas, while the memory-chip video lost only its borderline names at 0.6.
MIN_CONFIDENCE = float(os.getenv("YT_INDUSTRY_MIN_CONFIDENCE", "0.6"))
# One thesis call took 35-263 s in testing; the shared GLM default (180 s) is too tight.
_TIMEOUT_S = float(os.getenv("YT_INDUSTRY_TIMEOUT_S", "420"))
# glm-5.2 counts reasoning against max_tokens: at 8192 it spent ~6.9k thinking
# and the JSON was cut off mid-candidate. 32k leaves room for both.
_MAX_TOKENS = int(os.getenv("YT_INDUSTRY_MAX_TOKENS", "32768"))
# A thesis quote counts as verified when this share of its words appear in order
# in the transcript (captions are re-punctuated, so exact match is too strict).
_QUOTE_MATCH_RATIO = 0.8

SYSTEM_PROMPT = """You are an equity research analyst. You are given the transcript of a popular
explainer video about an industry, product, or economic trend. The video usually names only
household-name companies. Do NOT summarize it. Turn the industry dynamics it describes into a
search for beneficiaries and losers, including less obvious ones.

Steps:
1. THESES: State the 1-4 concrete, current industry dynamics in the video (shortage, bottleneck,
   policy change, demand shift, cost shift, technology adoption). Each must be supported by a
   short VERBATIM quote copied exactly from the transcript. Skip history, culture, lifestyle and
   purely political content. If the video has no live industry dynamic, return no theses.
2. PROFILE: For each thesis, describe what KIND of company gains or loses. Think second- and
   third-order: suppliers, picks-and-shovels, substitutes, service providers, customers squeezed.
3. CANDIDATES: Name specific publicly listed companies of any size that fit. Set
   origin="transcript" if the video names the company, else origin="model_knowledge".
   Give a ticker only if you are confident it is real and current; otherwise ticker=null.
   Give confidence 0-1 that the company actually fits the profile. Be honest: a loose fit is
   below 0.5.

Return JSON only:
{"theses":[{"dynamic":"...","quote":"...","direction":"tailwind|headwind",
  "beneficiary_profile":"...","loser_profile":"...",
  "candidates":[{"name":"...","ticker":"...|null","approx_cap":"micro|small|mid|large",
    "side":"long|short","origin":"transcript|model_knowledge","confidence":0.0,"why":"one line"}]}]}"""


@dataclass
class Idea:
    thesis_index: int
    dynamic: str
    quote: str
    quote_verified: bool
    direction: Optional[str]
    beneficiary_profile: Optional[str]
    loser_profile: Optional[str]
    company_name: str
    ticker: Optional[str]
    ticker_verified: bool
    side: Optional[str]
    approx_cap: Optional[str]
    origin: Optional[str]
    confidence: float
    why: Optional[str]


@dataclass
class ThesisResult:
    model: str = ""
    raw_theses: int = 0
    kept_theses: int = 0
    raw_candidates: int = 0
    ideas: list[Idea] = field(default_factory=list)
    error: Optional[str] = None


def is_industry_source(row_or_metadata: Mapping[str, Any] | None) -> bool:
    mechanism = (row_or_metadata or {}).get("alpha_mechanism")
    return str(mechanism or "").strip().upper() == INDUSTRY_MECHANISM


# --- quote verification -----------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text or "").lower().replace("’", "'")
    return _WORD_RE.findall(folded)


def quote_in_transcript(quote: str, transcript: str) -> bool:
    """True when the quote appears in the transcript, tolerating caption noise.

    Exact word-sequence match first; otherwise accept when a window of the
    transcript shares at least ``_QUOTE_MATCH_RATIO`` of the quote's words in
    order (captions drop or mishear the odd word, and GLM re-punctuates).
    """
    q = _words(quote)
    if len(q) < 4:
        return False
    t = _words(transcript)
    if not t:
        return False
    joined_t = " " + " ".join(t) + " "
    if " " + " ".join(q) + " " in joined_t:
        return True

    need = max(4, int(len(q) * _QUOTE_MATCH_RATIO + 0.999))
    window = int(len(q) * 1.5) + 2
    openers = set(q[:3])
    for start in (i for i, w in enumerate(t) if w in openers):
        # Greedy in-order match: each transcript word may match the next quote
        # word or skip up to two quote words the captions lost.
        qi = 0
        hits = 0
        for w in t[start : start + window]:
            if qi >= len(q):
                break
            look = q[qi : qi + 3]
            if w in look:
                qi += look.index(w) + 1
                hits += 1
        if hits >= need:
            return True
    return False


# --- GLM call + parsing -----------------------------------------------------


def _parse_json(raw: str) -> Optional[dict[str, Any]]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _default_model() -> str:
    try:
        from model_registry import PRIMARY_MODEL_DEFAULT

        return (PRIMARY_MODEL_DEFAULT or "glm-5.3").strip()
    except Exception:
        return "glm-5.3"


def call_glm(title: str, content: str, *, model: str) -> str:
    from glm_transport import glm_chat_completion_text

    user = f"Title: {title}\n\n{content}" if title else content
    return glm_chat_completion_text(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        model=model,
        json_mode=True,
        temperature=0.2,
        max_tokens=_MAX_TOKENS,
        timeout=_TIMEOUT_S,
        allow_cheap_fallback=False,
    )


def _verify_ticker(ticker: str, company_name: str) -> Optional[str]:
    """Return the normalized ticker if it is real and matches ``company_name``."""
    try:
        from research_utils import normalize_ticker, validate_ticker_format
        from ticker_validator import _get_real_company_name, _names_match
    except Exception as exc:  # pragma: no cover - import guard
        logger.warning("Ticker validation unavailable: %s", exc)
        return None
    raw = str(ticker or "").strip().upper().lstrip("$")
    if not raw or not validate_ticker_format(raw):
        return None
    normalized = normalize_ticker(raw) or raw
    real_name = _get_real_company_name(normalized)
    if not real_name:
        return None
    # The check is "does this symbol belong to the company GLM says it does",
    # which catches invented or stale tickers. Compare names directly:
    # ``validate_extracted_tickers`` also keeps any symbol that appears as a word
    # in its context, and GLM's "GMM S.p.A." would then pass as NYSE:GMM.
    if _names_match(company_name, real_name):
        return normalized
    logger.info(
        "Industry ticker %s rejected: belongs to %r, GLM said %r",
        normalized, real_name, company_name,
    )
    return None


def _as_float(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _clean(value: Any, limit: int = 2000) -> Optional[str]:
    text = str(value or "").strip()
    return text[:limit] or None


def filter_theses(
    data: Mapping[str, Any],
    transcript: str,
    *,
    min_confidence: float = MIN_CONFIDENCE,
    verify_ticker: Callable[[str, str], Optional[str]] = _verify_ticker,
) -> tuple[list[Idea], int, int, int]:
    """Apply the code-side filters. Returns (ideas, raw_theses, kept_theses, raw_candidates)."""
    theses = data.get("theses") if isinstance(data, Mapping) else None
    if not isinstance(theses, list):
        return [], 0, 0, 0

    ideas: list[Idea] = []
    kept_theses = 0
    raw_candidates = 0
    for index, thesis in enumerate(theses):
        if not isinstance(thesis, Mapping):
            continue
        candidates = thesis.get("candidates") or []
        raw_candidates += len(candidates) if isinstance(candidates, list) else 0
        dynamic = _clean(thesis.get("dynamic"))
        quote = _clean(thesis.get("quote"), 1000) or ""
        if not dynamic or not quote_in_transcript(quote, transcript):
            logger.info("Industry thesis %d dropped: quote not found in transcript", index)
            continue
        kept_theses += 1
        direction = _clean(thesis.get("direction"), 10)
        for cand in candidates if isinstance(candidates, list) else []:
            if not isinstance(cand, Mapping):
                continue
            name = _clean(cand.get("name"), 300)
            confidence = _as_float(cand.get("confidence"))
            if not name or confidence < min_confidence:
                continue
            raw_ticker = str(cand.get("ticker") or "").strip()
            if raw_ticker.lower() in ("", "null", "none", "n/a"):
                raw_ticker = ""
            ticker = verify_ticker(raw_ticker, name) if raw_ticker else None
            if raw_ticker and not ticker:
                logger.info("Industry idea %s (%s) dropped: ticker not verified", name, raw_ticker)
                continue
            if not ticker:
                # No usable symbol means nothing to act on or score later.
                continue
            side = str(cand.get("side") or "").strip().lower()
            origin = str(cand.get("origin") or cand.get("source") or "").strip().lower()
            ideas.append(
                Idea(
                    thesis_index=index,
                    dynamic=dynamic,
                    quote=quote,
                    quote_verified=True,
                    direction=direction,
                    beneficiary_profile=_clean(thesis.get("beneficiary_profile")),
                    loser_profile=_clean(thesis.get("loser_profile")),
                    company_name=name,
                    ticker=ticker,
                    ticker_verified=True,
                    side=side if side in ("long", "short") else None,
                    approx_cap=_clean(cand.get("approx_cap"), 10),
                    origin=origin if origin in ("transcript", "model_knowledge") else None,
                    confidence=round(confidence, 2),
                    why=_clean(cand.get("why"), 1000),
                )
            )
    return ideas, len(theses), kept_theses, raw_candidates


def run_industry_thesis(
    *,
    title: str,
    content: str,
    model: str | None = None,
    call_fn: Callable[..., str] | None = None,
    verify_ticker: Callable[[str, str], Optional[str]] = _verify_ticker,
) -> ThesisResult:
    """Run the GLM thesis prompt on one transcript and filter the result. Never raises."""
    result = ThesisResult(model=model or _default_model())
    call = call_fn or call_glm
    try:
        raw = call(title, content, model=result.model)
    except Exception as exc:
        result.error = f"call_failed: {exc}"
        logger.warning("Industry thesis GLM call failed: %s", exc)
        return result
    data = _parse_json(raw)
    if data is None:
        result.error = "unparseable"
        logger.warning("Industry thesis response unparseable: %s", (raw or "")[:240])
        return result
    ideas, raw_theses, kept, raw_cands = filter_theses(
        data, content, verify_ticker=verify_ticker
    )
    result.ideas = ideas
    result.raw_theses = raw_theses
    result.kept_theses = kept
    result.raw_candidates = raw_cands
    return result


def save_ideas(
    postgres_client: Any,
    *,
    article_id: str,
    video_id: str | None,
    source: str | None,
    result: ThesisResult,
) -> int:
    """Replace this article's ideas with ``result.ideas``. Returns rows written."""
    postgres_client.execute_update(
        "DELETE FROM yt_industry_ideas WHERE article_id = %s", (article_id,)
    )
    if not result.ideas:
        return 0
    rows = [
        (
            article_id,
            video_id,
            source,
            idea.thesis_index,
            idea.dynamic,
            idea.quote,
            idea.quote_verified,
            idea.direction,
            idea.beneficiary_profile,
            idea.loser_profile,
            idea.company_name,
            idea.ticker,
            idea.ticker_verified,
            idea.side,
            idea.approx_cap,
            idea.origin,
            idea.confidence,
            idea.why,
            result.model,
        )
        for idea in result.ideas
    ]
    return postgres_client.execute_many(
        """
        INSERT INTO yt_industry_ideas (
            article_id, video_id, source, thesis_index, dynamic, quote,
            quote_verified, direction, beneficiary_profile, loser_profile,
            company_name, ticker, ticker_verified, side, approx_cap, origin,
            confidence, why, model
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        rows,
    )


def run_and_save(
    *,
    postgres_client: Any,
    article_id: str,
    title: str,
    content: str,
    source_metadata: Mapping[str, Any] | None,
    source: str | None = None,
) -> ThesisResult | None:
    """Thesis pass for one saved transcript, if its source is INDUSTRY. Never raises.

    A failure here must not fail the transcript's normal enrichment, which has
    already succeeded by the time this runs.
    """
    if not is_industry_source(source_metadata):
        return None
    meta = dict(source_metadata or {})
    try:
        result = run_industry_thesis(title=title, content=content)
        if result.error is None:
            written = save_ideas(
                postgres_client,
                article_id=article_id,
                video_id=meta.get("video_id"),
                source=source or (f"youtube:{meta['channel_id']}" if meta.get("channel_id") else None),
                result=result,
            )
            logger.info(
                "Industry thesis for article %s: %d/%d theses kept, %d of %d candidates saved",
                article_id,
                result.kept_theses,
                result.raw_theses,
                written,
                result.raw_candidates,
            )
        return result
    except Exception as exc:
        logger.error("Industry thesis pass failed for article %s: %s", article_id, exc, exc_info=True)
        return None


__all__: Sequence[str] = (
    "INDUSTRY_MECHANISM",
    "Idea",
    "ThesisResult",
    "filter_theses",
    "is_industry_source",
    "quote_in_transcript",
    "run_and_save",
    "run_industry_thesis",
    "save_ideas",
)
