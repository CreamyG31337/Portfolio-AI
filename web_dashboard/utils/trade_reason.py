"""Compatibility shim for utils.trade_reason imports in Flask runtime."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT_MODULE_PATH = Path(__file__).resolve().parents[2] / "utils" / "trade_reason.py"
_SPEC = importlib.util.spec_from_file_location("_root_trade_reason", _ROOT_MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load trade_reason module from {_ROOT_MODULE_PATH}")

_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

normalize_reason_text = _MODULE.normalize_reason_text
is_dividend_reason = _MODULE.is_dividend_reason
is_sell_reason = _MODULE.is_sell_reason
infer_trade_action = _MODULE.infer_trade_action

__all__ = [
    "normalize_reason_text",
    "is_dividend_reason",
    "is_sell_reason",
    "infer_trade_action",
]
