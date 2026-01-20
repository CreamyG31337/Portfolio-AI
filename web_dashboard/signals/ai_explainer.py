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
    overall_signal = signals.get("overall_signal", "HOLD")
    confidence = signals.get("confidence", 0.0)

    prompt = f"""
You are a trading assistant. Explain the technical signals for {ticker} in plain English.
Keep it short and practical for a dashboard user.

Requirements:
- 3 to 4 bullet points only
- Each bullet is one sentence
- Mention trend, timing, and fear/risk at least once
- End with a short verdict matching the overall signal
- No financial advice disclaimer

Signals (JSON):
{{
  "overall_signal": "{overall_signal}",
  "confidence": {confidence},
  "structure": {structure},
  "timing": {timing},
  "fear_risk": {fear_risk}
}}
""".strip()
    return prompt


def generate_signal_explanation(ticker: str, signals: Dict[str, Any]) -> Optional[str]:
    """Generate an AI explanation for a signal set."""
    client = get_ollama_client()
    if not client:
        logger.warning("Ollama client unavailable; skipping signal explanation")
        return None

    prompt = build_signal_explanation_prompt(ticker, signals)
    model = get_summarizing_model()

    try:
        response = client.generate_completion(
            prompt=prompt,
            model=model,
            temperature=0.2
        )
    except Exception as e:
        logger.error(f"Signal explanation failed for {ticker}: {e}", exc_info=True)
        return None

    if not response:
        return None

    return response.strip()
