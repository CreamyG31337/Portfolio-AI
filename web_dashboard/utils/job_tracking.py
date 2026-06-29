"""Compatibility shim for utils.job_tracking imports in Flask runtime."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT_MODULE_PATH = Path(__file__).resolve().parents[2] / "utils" / "job_tracking.py"
_SPEC = importlib.util.spec_from_file_location("_root_job_tracking", _ROOT_MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load job_tracking module from {_ROOT_MODULE_PATH}")

_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

__all__ = [name for name in dir(_MODULE) if not name.startswith("_")]
globals().update({name: getattr(_MODULE, name) for name in __all__})
