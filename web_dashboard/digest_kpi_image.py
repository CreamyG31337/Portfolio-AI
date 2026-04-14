"""Render small KPI PNGs for outbound digest emails."""

from __future__ import annotations

import io
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def render_kpi_png(kind: str, summary: Dict[str, Any]) -> bytes:
    """kind: 'value' | 'week' — returns PNG bytes or empty placeholder on failure."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("Pillow not installed; KPI image skipped")
        return _minimal_png()

    w, h = 320, 80
    img = Image.new("RGB", (w, h), color=(30, 41, 59))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    cur = str(summary.get("display_currency") or "CAD")
    if kind == "value":
        text = f"Total: {summary.get('total_value', 0):,.2f} {cur}"
    else:
        text = (
            f"5d: {summary.get('five_day_change', 0):+.2f} {cur} "
            f"({summary.get('five_day_change_pct', 0):+.2f}%)"
        )
    draw.text((12, 28), text, fill=(226, 232, 240), font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _minimal_png() -> bytes:
    """1x1 transparent PNG."""
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def placeholder_expired_png() -> bytes:
    """Same dimensions as KPI strip for email layout stability."""
    try:
        from PIL import Image, ImageDraw, ImageFont

        w, h = 320, 80
        img = Image.new("RGB", (w, h), color=(51, 65, 85))
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        draw.text((12, 28), "Summary expired — log in", fill=(148, 163, 184), font=font)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return _minimal_png()
