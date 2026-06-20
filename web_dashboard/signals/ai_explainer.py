"""
AI Signal Explainer

Generates a short, human-readable explanation for technical signals.
Inspired by InvestAI's explainer agent, adapted to this dashboard.

Supports provider fallback: Ollama -> GLM (Z.AI) so that signal explanations
are generated even when the primary provider is busy or unavailable.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
import logging

from ollama_client import get_ollama_client
from settings import get_summarizing_model, get_summarizing_fallback_models

logger = logging.getLogger(__name__)


def build_signal_explanation_prompt(
    ticker: str,
    signals: Dict[str, Any],
    ticker_state: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a compact prompt for explaining technical signals.

    When *ticker_state* is provided (the full cross-source state dict),
    we append a compact text summary so the LLM can reference social
    sentiment, congress/insider trades, ETF exposure, and conflicts.
    """
    structure = signals.get("structure", {})
    timing = signals.get("timing", {})
    fear_risk = signals.get("fear_risk", {})
    momentum = signals.get("momentum", {})
    fundamental = signals.get("fundamental", {})
    overall_signal = signals.get("overall_signal", "HOLD")
    confidence = signals.get("confidence", 0.0)

    # Build optional sections only when data exists
    optional_sections = ""
    if momentum:
        optional_sections += f',\n  "momentum": {momentum}'
    if fundamental:
        optional_sections += f',\n  "fundamental": {fundamental}'

    # Adjust bullet count and requirements based on available data
    has_momentum = bool(momentum and momentum.get("bias"))
    has_fundamental = bool(fundamental and fundamental.get("quality"))
    has_state = bool(ticker_state and (
        ticker_state.get("social") or ticker_state.get("congress")
        or ticker_state.get("insider") or ticker_state.get("conflicts")
    ))
    bullet_count = 3
    extra_requirements = ""
    if has_momentum and has_fundamental:
        bullet_count = 5
        extra_requirements = (
            "- Comment on momentum bias and what the composite score implies\n"
            "- Comment on fundamental quality and any standout metrics\n"
        )
    elif has_momentum:
        bullet_count = 4
        extra_requirements = "- Comment on momentum bias and what the composite score implies\n"
    elif has_fundamental:
        bullet_count = 4
        extra_requirements = "- Comment on fundamental quality and any standout metrics\n"

    # If full state is available, increase bullet count and add requirements
    if has_state:
        bullet_count += 2
        extra_requirements += (
            "- Comment on notable cross-source data (social sentiment, congress/insider trades, conflicts)\n"
            "- Highlight any conflicts or divergences between data sources\n"
        )

    # Build the state context block
    state_context = ""
    if ticker_state:
        try:
            from ticker_state import summarize_ticker_state
            summary = summarize_ticker_state(ticker_state)
            if summary and summary.strip():
                state_context = f"\n\nCross-source context:\n{summary}"
        except Exception as e:
            logger.debug("Could not generate state summary for prompt: %s", e)

    prompt = f"""
You are a trading assistant. Explain the technical signals for {ticker} in plain English.
Keep it short and practical for a dashboard user.

Requirements:
- {bullet_count} to {bullet_count + 1} bullet points only
- Each bullet is one sentence
- Mention trend, timing, and fear/risk at least once
{extra_requirements}- End with a short verdict matching the overall signal
- No financial advice disclaimer

Signals (JSON):
{{
  "overall_signal": "{overall_signal}",
  "confidence": {confidence},
  "structure": {structure},
  "timing": {timing},
  "fear_risk": {fear_risk}{optional_sections}
}}{state_context}
""".strip()
    return prompt


def _get_explanation_model_chain(requested_model: Optional[str] = None) -> List[str]:
    """Build ordered model chain: primary model followed by configured/provider fallbacks.

    Mirrors the summarization model chain in ollama_client._get_summary_model_chain()
    so signal explanations benefit from the same fallback behaviour.
    """
    primary = requested_model
    fallback_models: List[str] = []
    try:
        if not primary:
            primary = get_summarizing_model()
        fallback_models = get_summarizing_fallback_models()
    except Exception as e:
        logger.warning("Could not load summarization settings for explainer chain: %s", e)
        if not primary:
            from model_registry import OLLAMA_SUMMARIZING_DEFAULT

            primary = OLLAMA_SUMMARIZING_DEFAULT

    chain = [primary] + fallback_models
    ordered: List[str] = []
    seen: set[str] = set()
    for m in chain:
        if not m:
            continue
        s = str(m).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        ordered.append(s)
    return ordered


def _generate_explanation_via_glm(prompt: str, model: str, temperature: float = 0.2) -> Optional[str]:
    """Generate a signal explanation using the Z.AI (GLM) chat completions API."""
    try:
        from glm_config import get_zhipu_api_key
        from glm_transport import glm_chat_completion_text
    except ImportError:
        logger.warning("glm_config not available for GLM signal explanation")
        return None

    key = get_zhipu_api_key()
    if not key or not key.strip():
        logger.warning("Z.AI API key not set - cannot generate signal explanation with GLM")
        return None

    messages = [
        {"role": "system", "content": "You are a concise trading assistant that explains technical signals in plain English."},
        {"role": "user", "content": prompt},
    ]

    start = time.time()
    try:
        content = glm_chat_completion_text(
            messages,
            model=model,
            stream=False,
            json_mode=False,
            temperature=float(temperature),
            max_tokens=512,
            timeout=60.0,
            allow_cheap_fallback=True,
        )
        elapsed = time.time() - start
        if content and content.strip() and not content.strip().startswith("GLM "):
            logger.info("GLM signal explanation generated in %.2fs with model=%s", elapsed, model)
            return content.strip()
        logger.warning("Empty GLM response for signal explanation (model=%s)", model)
        return None
    except Exception as e:
        logger.warning("GLM signal explanation failed (model=%s): %s", model, e)
        return None


def _generate_explanation_once(
    prompt: str, model: str, temperature: float = 0.2
) -> Optional[str]:
    """Try generating a signal explanation with a single model/provider.

    Routes to the correct provider based on model name:
    - ``glm-*`` -> Z.AI chat completions
    - everything else -> Ollama generate_completion
    """
    start_ms = time.time()
    result: Optional[str] = None
    error_msg: Optional[str] = None

    try:
        # GLM via Z.AI
        if model.startswith("glm-"):
            result = _generate_explanation_via_glm(prompt, model, temperature)
            return result

        # Ollama
        client = get_ollama_client()
        if not client:
            logger.warning("Ollama client unavailable for model=%s", model)
            return None

        result = client.generate_completion(
            prompt=prompt,
            model=model,
            temperature=temperature,
        )
        return result.strip() if result else None
    except Exception as e:
        error_msg = str(e)
        logger.warning("Explanation generation failed for model=%s: %s", model, e)
        return None
    finally:
        try:
            from ai_audit import (
                _compute_input_hash,
                _detect_caller,
                _detect_provider,
                log_inference,
            )

            log_inference(
                function="generate_signal_explanation",
                model=model,
                provider=_detect_provider(model),
                input_chars=len(prompt),
                input_hash=_compute_input_hash(prompt),
                output_summary=(result or "")[:200],
                duration_ms=int((time.time() - start_ms) * 1000),
                success=bool(result) and error_msg is None,
                error=error_msg,
                caller=_detect_caller(),
            )
        except Exception:
            pass


def generate_signal_explanation(
    ticker: str,
    signals: Dict[str, Any],
    model: Optional[str] = None,
    ticker_state: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Generate an AI explanation for a signal set.

    Uses a provider fallback chain (Ollama -> GLM -> ...) so that an explanation
    is produced even when the primary provider is busy or unavailable.

    When *ticker_state* is provided, the prompt includes cross-source context
    (social sentiment, congress/insider trades, ETF exposure, conflicts).
    """
    prompt = build_signal_explanation_prompt(ticker, signals, ticker_state=ticker_state)
    model_chain = _get_explanation_model_chain(model)

    if not model_chain:
        logger.error("No models available for signal explanation")
        return None

    for idx, candidate in enumerate(model_chain, start=1):
        logger.info(
            "Signal explanation attempt %s/%s for %s using model=%s",
            idx,
            len(model_chain),
            ticker,
            candidate,
        )
        result = _generate_explanation_once(prompt, candidate)
        if result:
            logger.info(
                "Signal explanation for %s generated successfully with model=%s",
                ticker,
                candidate,
            )
            return result
        logger.warning(
            "Signal explanation attempt failed/empty for %s with model=%s",
            ticker,
            candidate,
        )

    logger.error(
        "All signal explanation attempts failed for %s across chain: %s",
        ticker,
        model_chain,
    )
    return None
