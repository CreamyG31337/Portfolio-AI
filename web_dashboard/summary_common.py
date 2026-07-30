# Shared prompt and parser for article summarization (Ollama and Z.AI/GLM).
# Used by ollama_client.generate_summary, generate_summary_streaming, and _generate_summary_via_zhipu.

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)


# Input-text budget for the summarizer, in characters (roughly chars/4 ≈ tokens).
#
# Historical default was 6000 chars (~1500 tokens), which is fine for short
# news articles but silently drops the closing thesis on long-form newsletters
# (typical 7-15k chars). Modern model contexts are large enough to handle more:
# - Ollama models in model_config.json are 8k-40k tokens (32k typical).
# - Z.AI GLM models are 128k-200k tokens.
# - WebAI Gemini models are 1M-2M tokens.
# So the conservative 6k cap is the bottleneck, not the model.
SUMMARY_MAX_CHARS_DEFAULT = 6000
SUMMARY_MAX_CHARS_NEWSLETTER = 16000  # ~4000 tokens, fits comfortably in 8k+ ctx
# Phase K2: an hour-long earnings call is ~45-50k cleaned caption chars. At the
# 6k default the head+tail cut would drop the entire Q&A, which is the part that
# moves a thesis. Same budget as newsletters — the tail matters for the same
# reason (closing guidance / analyst questions).
SUMMARY_MAX_CHARS_TRANSCRIPT = 16000
# When a long transcript is routed to GLM (Z.AI), allow a larger head+tail window.
# ~48k chars ≈ 12k tokens — still small vs glm-5.2's 1M ctx, large vs Ollama 8–40k.
SUMMARY_MAX_CHARS_TRANSCRIPT_LONG = 48000
SUMMARY_TRUNCATION_MARKER = "\n\n[...content truncated; middle section omitted...]\n\n"

# Long-transcript routing thresholds (Ollama stays on the short path).
TRANSCRIPT_LONG_CHARS_THRESHOLD = SUMMARY_MAX_CHARS_TRANSCRIPT
TRANSCRIPT_LONG_DURATION_S = 20 * 60  # 20 minutes
YOUTUBE_TRANSCRIPT_MODEL_SCOPE = "youtube_transcript"


def _env_int(name: str, default: int) -> int:
    """Read a positive int from env, falling back to ``default`` on missing/invalid input."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        logger.warning("Ignoring non-integer env %s=%r; using default %s", name, raw, default)
        return default
    if val <= 0:
        logger.warning("Ignoring non-positive env %s=%s; using default %s", name, val, default)
        return default
    return val


def summary_uses_high_context_budget(
    article_type: str = "",
    *,
    model: str | None = None,
) -> bool:
    """True when summarizer should use the long YouTube transcript character budget.

    Only YouTube Transcript + GLM (Z.AI) gets the expanded window. Ollama and WebAI
    keep the standard transcript cap so local ctx windows are not blown out.
    """
    if (article_type or "").strip().lower() != "youtube transcript":
        return False
    return bool(model and str(model).startswith("glm-"))


def compute_summary_max_chars(article_type: str = "", *, high_context: bool = False) -> int:
    """Return the character budget the summarizer should clamp the article body to.

    Newsletters and video transcripts get a larger budget than the default
    article cap because the actionable thesis usually appears at the bottom;
    cutting the tail loses the most important signal. Operators can override via
    ``AI_SUMMARY_MAX_CHARS``, ``AI_SUMMARY_MAX_CHARS_NEWSLETTER``,
    ``AI_SUMMARY_MAX_CHARS_TRANSCRIPT``, and ``AI_SUMMARY_MAX_CHARS_TRANSCRIPT_LONG``.

    ``high_context=True`` selects the long transcript budget (GLM path for hour-long
    earnings calls). Short Ollama path keeps the standard transcript budget.
    """
    normalized = (article_type or "").strip().lower()
    if normalized == "newsletter":
        return _env_int("AI_SUMMARY_MAX_CHARS_NEWSLETTER", SUMMARY_MAX_CHARS_NEWSLETTER)
    if normalized == "youtube transcript":
        if high_context:
            return _env_int(
                "AI_SUMMARY_MAX_CHARS_TRANSCRIPT_LONG",
                SUMMARY_MAX_CHARS_TRANSCRIPT_LONG,
            )
        return _env_int("AI_SUMMARY_MAX_CHARS_TRANSCRIPT", SUMMARY_MAX_CHARS_TRANSCRIPT)
    return _env_int("AI_SUMMARY_MAX_CHARS", SUMMARY_MAX_CHARS_DEFAULT)


def transcript_needs_high_context(
    content_chars: int,
    *,
    duration_s: int | None = None,
) -> bool:
    """True when a YouTube transcript is too large for a comfortable Ollama summarize."""
    chars = max(0, int(content_chars or 0))
    if chars > TRANSCRIPT_LONG_CHARS_THRESHOLD:
        return True
    if duration_s is not None:
        try:
            if int(duration_s) >= TRANSCRIPT_LONG_DURATION_S:
                return True
        except (TypeError, ValueError):
            pass
    return False


def resolve_youtube_transcript_summary_model(
    content_chars: int,
    *,
    duration_s: int | None = None,
) -> str | None:
    """Pick a model for YouTube transcript summarization.

    **Always** routes YouTube Transcripts to Z.AI GLM (scoped override
    ``ai_summarizing_model_youtube_transcript``, else primary GLM). Short videos used
    to fall through to the Ollama summarizing chain (``OLLAMA_SUMMARIZING_MODEL``,
    often granite), which timed out for minutes before fallback — that made a
    50–100 video nightly run impossible. ``content_chars`` / ``duration_s`` still
    drive the long vs short *character budget* via ``transcript_needs_high_context``;
    they no longer gate the provider.

    **Never** auto-selects a WebAI (cookie) model; a WebAI scoped override is
    ignored and GLM is used instead.
    """
    # Args retained for call-site compatibility and for callers that still want
    # to log whether the long budget applies.
    _ = (content_chars, duration_s)

    try:
        from model_registry import PRIMARY_MODEL_DEFAULT

        glm_default = (PRIMARY_MODEL_DEFAULT or "glm-5.2").strip()
    except Exception:
        glm_default = "glm-5.2"

    raw = None
    try:
        from settings import get_system_setting

        raw = get_system_setting("ai_summarizing_model_youtube_transcript", default=None)
    except Exception:
        raw = None

    candidate = str(raw).strip() if raw else ""
    if not candidate:
        return glm_default

    try:
        from webai_wrapper import is_webai_model

        if is_webai_model(candidate):
            logger.warning(
                "Ignoring WebAI model %r for YouTube transcript; using %s",
                candidate,
                glm_default,
            )
            return glm_default
    except Exception:
        pass

    return candidate


def truncate_for_summary(text: str, max_chars: int) -> str:
    """Trim article body to fit within ``max_chars`` while preserving head + tail.

    Newsletters typically follow a setup-then-conclusion structure where the
    most actionable content (specific tickers, price targets, calls to
    action) lives in the closing paragraphs. A naive ``text[:max_chars]`` cut
    drops that tail; instead we keep ~60% from the start and ~40% from the
    end, joined by a clear marker so the model knows content was omitted.
    """
    if text is None:
        return ""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text

    marker = SUMMARY_TRUNCATION_MARKER
    # Reserve room for the marker so the result truly fits in max_chars.
    budget = max_chars - len(marker)
    if budget <= 0:
        # max_chars is absurdly small; fall back to a plain head cut.
        return text[:max_chars]

    head_len = int(budget * 0.6)
    tail_len = budget - head_len
    head = text[:head_len].rstrip()
    tail = text[-tail_len:].lstrip() if tail_len > 0 else ""
    return f"{head}{marker}{tail}"


def get_summary_system_prompt(article_text: str = "", article_type: str = "") -> str:
    """Return base summary prompt augmented with matching markdown skills.

    Falls back to the unenhanced ``_SUMMARY_SYSTEM_PROMPT`` if skill_loader
    is unavailable or raises.  The fallback is logged at WARNING so silent
    degradation is visible in logs.

    Args:
        article_text: The article body used for keyword-based skill matching.
        article_type: Optional type string (e.g. "Newsletter") used for
            article_types-based skill matching.  Most callers do not pass
            this yet — skills relying solely on article_types triggers will
            only activate when this is provided.
    """
    try:
        from skill_loader import build_enhanced_prompt

        return build_enhanced_prompt(
            _SUMMARY_SYSTEM_PROMPT,
            article_text,
            "summary",
            article_type=article_type,
        )
    except Exception as exc:
        logger.warning("Skill injection failed for summary prompt (falling back to base): %s", exc)
        return _SUMMARY_SYSTEM_PROMPT


def _sanitize_summary_tickers(raw_tickers: Any) -> list[str]:
    """Normalize and validate ticker list returned by LLM summary responses."""
    if isinstance(raw_tickers, str):
        tokens = re.split(r"[\s,;|]+", raw_tickers.strip())
        items = [t.strip("'\"") for t in tokens if t.strip()]
    elif isinstance(raw_tickers, list):
        items = raw_tickers
    else:
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    invalid_tokens = {"", "?", "$", "$?", "N/A", "NONE", "UNKNOWN", "NULL", "-"}

    for item in items:
        if not isinstance(item, str):
            continue

        ticker = item.strip().upper()
        if not ticker:
            continue

        # Normalize common LLM artifacts
        ticker = ticker.lstrip("$")
        ticker = ticker.rstrip("?.,;:!")
        ticker = ticker.strip()

        if ticker in invalid_tokens:
            continue

        # Must start with a letter; allow letters/digits/dot/dash after.
        if not re.fullmatch(r"[A-Z][A-Z0-9\.-]{0,19}", ticker):
            continue

        if ticker not in seen:
            seen.add(ticker)
            cleaned.append(ticker)

    return cleaned


_VALID_TICKER_SENTIMENTS = {"VERY_BULLISH", "BULLISH", "NEUTRAL", "BEARISH", "VERY_BEARISH"}


def _sanitize_ticker_sentiment(raw: Any) -> list[dict[str, str]]:
    """Validate and normalize a ``ticker_sentiment`` array from LLM output.

    Each entry must have ``ticker`` (str), ``sentiment`` (valid enum), and
    ``reason`` (str).  Invalid entries are silently dropped.
    """
    if not isinstance(raw, list):
        return []

    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker", "")).strip().upper()
        sentiment = str(item.get("sentiment", "")).strip().upper()
        reason = str(item.get("reason", "")).strip()

        if not ticker or not sentiment:
            continue
        if sentiment not in _VALID_TICKER_SENTIMENTS:
            continue
        if ticker in seen:
            continue
        seen.add(ticker)
        result.append({"ticker": ticker, "sentiment": sentiment, "reason": reason})
    return result


def _decode_json_string(raw_value: str) -> str:
    """Decode a JSON-escaped string fragment safely."""
    try:
        return json.loads(f"\"{raw_value}\"")
    except Exception:
        return (
            raw_value.replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("\\r", "\r")
            .replace('\\"', '"')
        )


def _extract_json_string_field(payload: str, key: str) -> str | None:
    """Extract a quoted JSON string value for a key from JSON-like text."""
    pattern = rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"'
    match = re.search(pattern, payload, flags=re.DOTALL)
    if not match:
        return None
    return _decode_json_string(match.group(1)).strip()


def _split_loose_array_items(raw_array: str) -> list[str]:
    """Split a JSON-like array body by commas, preserving quoted commas."""
    items: list[str] = []
    current: list[str] = []
    in_quote = False
    escaping = False

    for char in raw_array:
        if escaping:
            current.append(char)
            escaping = False
            continue
        if in_quote and char == "\\":
            current.append(char)
            escaping = True
            continue
        if char == '"':
            current.append(char)
            in_quote = not in_quote
            continue
        if char == "," and not in_quote:
            token = "".join(current).strip()
            if token:
                items.append(token)
            current = []
            continue
        current.append(char)

    token = "".join(current).strip()
    if token:
        items.append(token)
    return items


def _extract_loose_string_array(payload: str, key: str) -> list[str]:
    """Extract a string array from malformed JSON where some items may be unquoted."""
    pattern = rf'"{re.escape(key)}"\s*:\s*\[(.*?)\]'
    match = re.search(pattern, payload, flags=re.DOTALL)
    if not match:
        return []

    values: list[str] = []
    for token in _split_loose_array_items(match.group(1)):
        token = token.strip()
        if not token:
            continue
        if token.startswith('"') and token.endswith('"'):
            try:
                value = json.loads(token)
            except Exception:
                value = token.strip('"')
        else:
            value = token.strip().strip('"').strip("'")

        value_str = str(value).strip()
        if not value_str:
            continue
        if value_str.lower() in {"null", "none"}:
            continue
        values.append(value_str)

    return values


def _extract_relationships_array(payload: str) -> list[dict[str, str]]:
    """Best-effort extraction of relationships from malformed JSON-like payloads."""
    pattern = r'"relationships"\s*:\s*\[(.*?)\]'
    match = re.search(pattern, payload, flags=re.DOTALL)
    if not match:
        return []

    body = match.group(1).strip()
    if not body:
        return []

    try:
        parsed = json.loads(f"[{body}]")
    except Exception:
        return []

    relationships: list[dict[str, str]] = []
    for rel in parsed:
        if isinstance(rel, dict):
            source = str(rel.get("source", "")).strip().upper()
            target = str(rel.get("target", "")).strip().upper()
            rel_type = str(rel.get("type", "")).strip().upper()
            if source and target and rel_type:
                relationships.append({"source": source, "target": target, "type": rel_type})
    return relationships


def _extract_ticker_sentiment_loose(payload: str) -> list[dict[str, str]]:
    """Best-effort extraction of ticker_sentiment array from malformed JSON."""
    pattern = r'"ticker_sentiment"\s*:\s*\[(.*?)\]'
    match = re.search(pattern, payload, flags=re.DOTALL)
    if not match:
        return []

    body = match.group(1).strip()
    if not body:
        return []

    try:
        parsed = json.loads(f"[{body}]")
    except Exception:
        return []

    return _sanitize_ticker_sentiment(parsed)


def _parse_summary_response_loose(raw_response: str) -> dict[str, Any] | None:
    """Recover core fields from malformed JSON-like model output."""
    summary_text = _extract_json_string_field(raw_response, "summary")
    if not summary_text:
        return None

    sentiment = (_extract_json_string_field(raw_response, "sentiment") or "NEUTRAL").upper()
    if sentiment not in ("VERY_BULLISH", "BULLISH", "NEUTRAL", "BEARISH", "VERY_BEARISH"):
        sentiment = "NEUTRAL"

    logic_check = (_extract_json_string_field(raw_response, "logic_check") or "NEUTRAL").upper()
    if logic_check not in ("DATA_BACKED", "HYPE_DETECTED", "NEUTRAL"):
        logic_check = "NEUTRAL"

    market_relevance = (
        _extract_json_string_field(raw_response, "market_relevance") or "UNKNOWN"
    ).upper()
    if market_relevance not in ("MARKET_RELATED", "NOT_MARKET_RELATED"):
        market_relevance = "UNKNOWN"

    sentiment_score_map = {
        "VERY_BULLISH": 2.0,
        "BULLISH": 1.0,
        "NEUTRAL": 0.0,
        "BEARISH": -1.0,
        "VERY_BEARISH": -2.0,
    }

    return {
        "summary": summary_text.strip(),
        "claims": _extract_loose_string_array(raw_response, "claims"),
        "fact_check": (_extract_json_string_field(raw_response, "fact_check") or "").strip(),
        "conclusion": (_extract_json_string_field(raw_response, "conclusion") or "").strip(),
        "sentiment": sentiment,
        "sentiment_score": sentiment_score_map.get(sentiment, 0.0),
        "logic_check": logic_check,
        "tickers": _sanitize_summary_tickers(_extract_loose_string_array(raw_response, "tickers")),
        "ticker_sentiment": _extract_ticker_sentiment_loose(raw_response),
        "sectors": _extract_loose_string_array(raw_response, "sectors"),
        "key_themes": _extract_loose_string_array(raw_response, "key_themes"),
        "companies": _extract_loose_string_array(raw_response, "companies"),
        "market_relevance": market_relevance,
        "market_relevance_reason": (
            _extract_json_string_field(raw_response, "market_relevance_reason") or ""
        ).strip(),
        "relationships": _extract_relationships_array(raw_response),
    }


def parse_summary_response(raw_response: str) -> dict[str, Any]:
    """Parse JSON from model output into the standard summary dict. Handles markdown code blocks and fallback."""
    if not raw_response or not raw_response.strip():
        return {}

    raw_response = raw_response.strip()
    try:
        json_str = raw_response
        if "```json" in json_str:
            start = json_str.find("```json") + 7
            end = json_str.find("```", start)
            if end > start:
                json_str = json_str[start:end].strip()
        elif "```" in json_str:
            start = json_str.find("```") + 3
            end = json_str.find("```", start)
            if end > start:
                json_str = json_str[start:end].strip()

        parsed = json.loads(json_str)

        def extract_strings(value: Any, default: list) -> list:
            if not isinstance(value, list):
                return default
            result = []
            for item in value:
                if isinstance(item, str) and item.strip():
                    result.append(item.strip())
                elif isinstance(item, int | float):
                    result.append(str(item).strip())
            return result

        summary_text = parsed.get("summary", "")
        if not isinstance(summary_text, str):
            summary_text = str(summary_text) if summary_text else ""
        if summary_text:
            lines = summary_text.split("\n")
            summary_text = "\n".join(line.lstrip() for line in lines).strip()

        fact_check = parsed.get("fact_check", "")
        if not isinstance(fact_check, str):
            fact_check = str(fact_check) if fact_check else ""
        conclusion = parsed.get("conclusion", "")
        if not isinstance(conclusion, str):
            conclusion = str(conclusion) if conclusion else ""

        sentiment = (parsed.get("sentiment") or "NEUTRAL")
        if not isinstance(sentiment, str):
            sentiment = str(sentiment) if sentiment else "NEUTRAL"
        sentiment = sentiment.strip().upper()
        if sentiment not in ("VERY_BULLISH", "BULLISH", "NEUTRAL", "BEARISH", "VERY_BEARISH"):
            sentiment = "NEUTRAL"
        sentiment_score_map = {
            "VERY_BULLISH": 2.0, "BULLISH": 1.0, "NEUTRAL": 0.0,
            "BEARISH": -1.0, "VERY_BEARISH": -2.0
        }
        sentiment_score = sentiment_score_map.get(sentiment, 0.0)

        logic_check = (parsed.get("logic_check") or "NEUTRAL")
        if not isinstance(logic_check, str):
            logic_check = str(logic_check) if logic_check else "NEUTRAL"
        logic_check = logic_check.strip().upper()
        if logic_check not in ("DATA_BACKED", "HYPE_DETECTED", "NEUTRAL"):
            logic_check = "NEUTRAL"

        market_relevance = (parsed.get("market_relevance") or "UNKNOWN")
        if not isinstance(market_relevance, str):
            market_relevance = str(market_relevance) if market_relevance else "UNKNOWN"
        market_relevance = market_relevance.strip().upper()
        if market_relevance not in ("MARKET_RELATED", "NOT_MARKET_RELATED"):
            market_relevance = "UNKNOWN"

        market_relevance_reason = parsed.get("market_relevance_reason", "")
        if not isinstance(market_relevance_reason, str):
            market_relevance_reason = str(market_relevance_reason) if market_relevance_reason else ""
        market_relevance_reason = market_relevance_reason.strip()

        relationships = []
        for rel in (parsed.get("relationships") or []):
            if isinstance(rel, dict):
                s = (rel.get("source") or "").strip().upper()
                t = (rel.get("target") or "").strip().upper()
                typ = (rel.get("type") or "").strip().upper()
                if s and t and typ:
                    relationships.append({"source": s, "target": t, "type": typ})

        return {
            "summary": summary_text.strip(),
            "claims": extract_strings(parsed.get("claims"), []),
            "fact_check": fact_check.strip(),
            "conclusion": conclusion.strip(),
            "sentiment": sentiment,
            "sentiment_score": sentiment_score,
            "logic_check": logic_check,
            "tickers": _sanitize_summary_tickers(parsed.get("tickers")),
            "ticker_sentiment": _sanitize_ticker_sentiment(parsed.get("ticker_sentiment")),
            "sectors": extract_strings(parsed.get("sectors"), []),
            "key_themes": extract_strings(parsed.get("key_themes"), []),
            "companies": extract_strings(parsed.get("companies"), []),
            "market_relevance": market_relevance,
            "market_relevance_reason": market_relevance_reason,
            "relationships": relationships,
        }
    except json.JSONDecodeError as e:
        recovered = _parse_summary_response_loose(raw_response)
        if recovered is not None:
            logger.warning(
                "Strict JSON parse failed for summary response; recovered with loose parser: %s",
                e,
            )
            return recovered

        logger.warning(f"Failed to parse JSON from summary response, falling back to text-only: {e}")
        logger.debug(f"Raw response (first 500 chars): {raw_response[:500]}")
        return {
            "summary": raw_response,
            "claims": [],
            "fact_check": "",
            "conclusion": "",
            "sentiment": "NEUTRAL",
            "sentiment_score": 0.0,
            "logic_check": "NEUTRAL",
            "tickers": [],
            "ticker_sentiment": [],
            "sectors": [],
            "key_themes": [],
            "companies": [],
            "market_relevance": "UNKNOWN",
            "market_relevance_reason": "",
            "relationships": [],
        }
    except Exception as e:
        logger.error(f"Unexpected error parsing summary response: {e}", exc_info=True)
        return {
            "summary": raw_response,
            "claims": [],
            "fact_check": "",
            "conclusion": "",
            "sentiment": "NEUTRAL",
            "sentiment_score": 0.0,
            "logic_check": "NEUTRAL",
            "tickers": [],
            "ticker_sentiment": [],
            "sectors": [],
            "key_themes": [],
            "companies": [],
            "market_relevance": "UNKNOWN",
            "market_relevance_reason": "",
            "relationships": [],
        }


_SUMMARY_SYSTEM_PROMPT = """You are a skeptical financial analyst. Analyze the following article using a 3-step Chain of Thought process, then provide a comprehensive analysis in JSON format.

ANALYSIS PROCESS (Chain of Thought):
Step 1 - Identify Claims: Extract specific numbers, dates, percentages, and causal claims made in the article. List all factual assertions with concrete data points.

Step 2 - Fact Check: Perform simple fact-checking to filter out garbage and clickbait. Ask yourself:
- Are the claims plausible? (e.g., "stock up 1000%" is likely clickbait)
- Are there obvious contradictions within the article?
- Does the headline match the content?
- Are there red flags (e.g., "guaranteed returns", "secret method")?
Keep this simple - you're a fact checker, not a PhD economist. Focus on filtering obvious noise.

Step 3 - Conclusion: Summarize the net impact on the stock ticker(s). What does this article actually mean for the stock? Be specific about potential price impact or business implications.

SENTIMENT CATEGORIZATION:
Categorize the article's overall sentiment into exactly ONE of these buckets:
- "VERY_BULLISH" - Game-changing positive news (e.g., massive earnings beat, breakthrough product, major acquisition)
- "BULLISH" - Good news or analysis making a clear positive case (e.g., price target upgrade, partnership, positive guidance, data-backed argument that a stock is undervalued or has superior growth)
- "NEUTRAL" - Noise, standard reporting, mixed results, routine updates, balanced analysis with no clear directional thesis
- "BEARISH" - Bad news or analysis making a clear negative case (e.g., missed earnings, downgrade, data-backed argument that a stock is overvalued or faces headwinds)
- "VERY_BEARISH" - Catastrophic news (e.g., fraud investigation, CEO fired, bankruptcy filing)

Most articles should be "NEUTRAL" - only categorize as BULLISH/BEARISH if there's significant news OR the analysis makes a clear directional case backed by data. For comparative analyses (e.g., "Stock A vs Stock B"), assign sentiment based on the overall investment thesis: if the article argues one company is clearly better positioned with supporting data, that's BULLISH.

LOGIC CHECK CATEGORIZATION:
Categorize the article's quality/reliability into exactly ONE of these buckets:
- "DATA_BACKED" - Article is PRIMARILY a data report: official earnings announcements, revenue releases, SEC filings, company financial statements, economic data releases (GDP, unemployment, inflation numbers). The article's main purpose is to report specific numbers/metrics. Examples: "Apple reports Q3 earnings of $2.50 per share", "GDP grew 3.2% in Q4", "Unemployment rate falls to 3.5%". Articles that are analysis, commentary, opinions, recommendations, or general news that happen to mention numbers should be NEUTRAL.
- "HYPE_DETECTED" - Clickbait, rumors, speculation, unverified claims, sensationalized headlines, articles promising unrealistic returns, heavy use of "might", "could", "potential" without evidence, "this stock will double" type claims
- "NEUTRAL" - DEFAULT category for most articles: analysis pieces, market commentary, opinion articles, recommendations, general news coverage, sector overviews, stock picks, investment advice, market summaries. Even if these articles mention stock prices, percentages, or other numbers, they are NOT primarily data reports - they are analysis/commentary. This should be 70-80% of articles.

CRITICAL CLASSIFICATION RULES:
1. If the article is analysis, commentary, opinion, or recommendation → "NEUTRAL" (even if it mentions numbers)
2. If the article is primarily reporting official data/metrics → "DATA_BACKED"
3. If the article is clickbait/rumors → "HYPE_DETECTED"
4. When in doubt, choose "NEUTRAL" - it's the default for most financial news articles.

MARKET RELEVANCE CHECK:
Determine whether the article is related to public markets or market-relevant economics.
- "MARKET_RELATED": The article is about publicly traded companies, stock/credit/crypto markets, ETFs, earnings, IPOs, M&A, SEC/regulatory actions, macroeconomic policy likely to impact markets (rates, inflation, fiscal policy), or industry news tied to listed companies.
- "NOT_MARKET_RELATED": The article is about unrelated topics (sports, celebrity, weather, local crime, lifestyle, travel, etc.) with no meaningful market/financial relevance.
CRITICAL RULES:
1. Do NOT classify as market-related just because an article mentions generic words like "investment", "economy", "jobs", "funding", or "business".
2. Require an explicit tie to public markets, listed securities, market instruments, or named/publicly-traded companies.
3. Lifestyle/entertainment/local-policy/human-interest stories are NOT_MARKET_RELATED even if they mention money or investment plans.
4. If uncertain, choose "NOT_MARKET_RELATED".

PER-TICKER SENTIMENT:
For EACH ticker you extract, provide an individual sentiment assessment:
- ticker: the ticker symbol (must match one from the "tickers" array)
- sentiment: "BULLISH", "BEARISH", or "NEUTRAL"
- reason: one sentence explaining the directional thesis for THIS specific ticker based on the article
This is especially important for comparative articles (e.g., "Stock A vs Stock B") where overall sentiment may be NEUTRAL but individual tickers have clear directional signals.

EXTRACTION REQUIREMENTS:
1. Generate a comprehensive summary with 5-7+ bullet points covering all key information
2. Extract stock ticker symbols ONLY for companies that are SUBSTANTIVELY DISCUSSED in the article
   - CRITICAL: Only include tickers for companies the article is ABOUT or ANALYZES in detail.
   - Do NOT extract tickers for companies that are merely mentioned in passing (e.g., "unlike Amazon..." in an article about a different company). The company must be a SUBJECT of the article.
   - The scraped text may contain noise from the webpage (related articles, trending tickers, other stories). Focus on what the article is actually analyzing, not stray ticker mentions.
   - Each ticker you extract MUST appear in your summary bullet points AND in ticker_sentiment with a reason. If you can't write a sentiment reason for it, don't include it.
   - Tickers are SHORT symbols (1-10 characters), typically 1-5 uppercase letters
   - May include exchange suffixes like .TO, .V, .CN, .TSX
   - Do NOT extract company names (e.g., "Apple Inc" is NOT a ticker, "AAPL" is)
   - Do NOT extract long phrases or descriptions
   - CRITICAL: Do NOT extract financial abbreviations, metrics, or jargon as tickers.
     Common FALSE POSITIVES to avoid: CAGR (growth rate), EV (enterprise value),
     FCF (free cash flow), TBV (tangible book value), PE (price-earnings ratio),
     EBITDA, ROI, ROE, ROA, CAPEX, OPEX, ARR (annual recurring revenue),
     MRR, TAM, SAM, AWS (Amazon Web Services), GCP (Google Cloud Platform),
     WACC, DCF, IRR, ROIC, NIM, NAV, AUM, SPAC, LBO, RAAS, SAAS, PAAS, IAAS.
     These are financial TERMS, not stock symbols. When in doubt, omit.
   - First, look for explicit ticker symbols mentioned in the article (e.g., $AMZN, (WMT))
   - If no explicit tickers found BUT the article is clearly about specific companies, infer the likely ticker(s)
   - For well-known companies, provide your best guess of the ticker symbol
   - Do NOT use placeholders or uncertain forms like "$?", "-", "UNKNOWN", or "RKLB?"
   - If uncertain, omit the ticker instead of guessing with markers
   - Examples: "Apple" → "AAPL", "Microsoft" → "MSFT", "Tesla" → "TSLA", "NVIDIA" → "NVDA"
3. Identify all sectors/industries discussed (e.g., "Financial Services", "Technology", "Healthcare")
4. List key themes and topics (e.g., "crypto revenue", "subscription growth", "market expansion")
5. Extract company names mentioned (e.g., "Robinhood", "NVIDIA") - these go in "companies" field, NOT "tickers"

RELATIONSHIP EXTRACTION:
Extract corporate relationships mentioned in the text. Return a list of JSON objects in the 'relationships' field.

**CRITICAL: Use stock tickers (e.g., AAPL) for source/target if known. If the ticker is unknown, use the capitalized company name.**

Format: { "source": "TICKER", "target": "TICKER", "type": "TYPE" }

Allowed relationship types:
- SUPPLIER: Source supplies Target (e.g., "TSMC supplies Apple" → source: "TSM", target: "AAPL", type: "SUPPLIER")
- CUSTOMER: Source is a customer of Target (e.g., "Apple buys from TSMC" → source: "TSM", target: "AAPL", type: "SUPPLIER" - note: CUSTOMER relationships should be converted to SUPPLIER with supplier as source)
- COMPETITOR: Direct rivalry between companies
- PARTNER: Joint venture, collaboration, strategic partnership
- PARENT: Source owns/is parent of Target
- SUBSIDIARY: Source is subsidiary of Target
- LITIGATION: Lawsuits or legal disputes between companies

Examples:
- "Nvidia's supply constraints at TSMC are limiting H100 production" → [{ "source": "NVDA", "target": "TSM", "type": "SUPPLIER" }]
- "Apple buys chips from TSMC" → [{ "source": "TSM", "target": "AAPL", "type": "SUPPLIER" }]
- "Google competes with Microsoft in cloud services" → [{ "source": "GOOG", "target": "MSFT", "type": "COMPETITOR" }]

If no relationships are found, use empty array [].

CRITICAL: Return ONLY valid, parseable JSON. Do NOT include:
- Explanatory text before or after the JSON
- Comments (// or /* */)
- Markdown formatting
- Any text outside the JSON object

The "summary" field must be a single STRING with bullet points separated by newlines (\\n), NOT an array.

Return your response as a valid JSON object with these exact fields:
{
  "summary": "• First key point...\\n• Second key point...\\n• Third key point...\\n• Fourth key point...\\n• Fifth key point...",
  "claims": ["Claim 1 with specific numbers/dates", "Claim 2 with percentages", "Claim 3..."],
  "fact_check": "Simple fact-checking analysis: Are claims plausible? Any obvious contradictions? Filter garbage/clickbait.",
  "conclusion": "Net impact on ticker(s): What does this article mean for the stock? Specific price impact or business implications.",
  "sentiment": "VERY_BULLISH" | "BULLISH" | "NEUTRAL" | "BEARISH" | "VERY_BEARISH",
  "logic_check": "DATA_BACKED" | "HYPE_DETECTED" | "NEUTRAL",
  "tickers": ["TICKER1", "TICKER2"],
  "ticker_sentiment": [{"ticker": "TICKER1", "sentiment": "BULLISH", "reason": "One sentence reason"}, {"ticker": "TICKER2", "sentiment": "BEARISH", "reason": "One sentence reason"}],
  "sectors": ["Sector1", "Sector2"],
  "key_themes": ["theme1", "theme2"],
  "companies": ["Company1", "Company2"],
  "market_relevance": "MARKET_RELATED" | "NOT_MARKET_RELATED",
  "market_relevance_reason": "Short reason (1 sentence)",
  "relationships": [{"source": "TICKER1", "target": "TICKER2", "type": "SUPPLIER"}, ...]
}

If no tickers, sectors, themes, companies, or relationships are found, use empty arrays []. The ticker_sentiment array should have one entry per ticker (same tickers as the "tickers" array). The sentiment, logic_check, and market_relevance fields are REQUIRED and must be exactly one of the values listed above. Return ONLY the JSON object, nothing else."""
