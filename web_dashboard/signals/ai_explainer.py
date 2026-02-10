"""
AI Signal Explainer

Generates a short, human-readable explanation for technical signals.
Inspired by InvestAI's explainer agent, adapted to this dashboard.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import logging

from ollama_client import get_ollama_client
from settings import get_summarizing_model

logger = logging.getLogger(__name__)


def build_signal_explanation_prompt(ticker: str, signals: Dict[str, Any]) -> str:
    """Build a compact prompt for explaining technical signals."""
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
}}
""".strip()
    return prompt


def generate_signal_explanation(
    ticker: str, signals: Dict[str, Any], model: Optional[str] = None
) -> Optional[str]:
    """Generate an AI explanation for a signal set.
    Uses the given model if provided and supported (Ollama); otherwise the default summarizing model.
    WebAI/GLM models are not supported here and fall back to the default.
    """
    client = get_ollama_client()
    if not client:
        logger.warning("Ollama client unavailable; skipping signal explanation")
        return None

    prompt = build_signal_explanation_prompt(ticker, signals)
    resolved = model
    if resolved:
        try:
            from webai_wrapper import is_webai_model
            if is_webai_model(resolved) or (resolved or "").startswith("glm-"):
                logger.warning(
                    "Model %s is not supported for signal explanation; using default",
                    resolved,
                )
                resolved = None
        except Exception:
            resolved = None
    if not resolved:
        resolved = get_summarizing_model()

    try:
        response = client.generate_completion(
            prompt=prompt,
            model=resolved,
            temperature=0.2
        )
    except Exception as e:
        logger.error(f"Signal explanation failed for {ticker}: {e}", exc_info=True)
        return None

    if not response:
        return None

    return response.strip()
