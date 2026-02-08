#!/usr/bin/env python3
"""
Lightweight JSONL audit trail for AI inference calls.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent
_AUDIT_DIR = _BASE_DIR / "logs" / "ai_audit"
_thread_local = threading.local()
_cleanup_lock = threading.Lock()
_last_cleanup_date: date | None = None

_INTERNAL_FILES = {"ollama_client.py", "ai_audit.py", "webai_wrapper.py"}


def _compute_input_hash(text: Any) -> str:
    """Return short deterministic hash prefix used to correlate inference inputs."""
    if text is None:
        text = ""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:8]


def _detect_provider(model: str | None) -> str:
    """Infer provider from model naming conventions."""
    model_name = str(model or "")
    if model_name.startswith("glm-"):
        return "glm"
    try:
        from webai_wrapper import is_webai_model

        if is_webai_model(model_name):
            return "webai"
    except Exception:
        pass
    return "ollama"


def _detect_caller() -> str:
    """Return first external caller as module.function."""
    stack = []
    try:
        stack = inspect.stack()
        for frame_info in stack[1:]:
            file_name = Path(frame_info.filename).name.lower()
            if file_name in _INTERNAL_FILES:
                continue
            module = inspect.getmodule(frame_info.frame)
            function_name = frame_info.function or "unknown"
            if module and module.__name__:
                return f"{module.__name__}.{function_name}"
            return f"{Path(frame_info.filename).stem}.{function_name}"
    except Exception:
        return "unknown"
    finally:
        for frame_info in stack:
            del frame_info
    return "unknown"


def set_audit_context(**kwargs: Any) -> None:
    """Set thread-local metadata for audit records."""
    try:
        current = getattr(_thread_local, "context", {})
        if not isinstance(current, dict):
            current = {}
        merged = {**current, **kwargs}
        _thread_local.context = merged
    except Exception as exc:
        logger.debug("Failed to set audit context: %s", exc)


def get_audit_context() -> dict[str, Any]:
    """Get current thread-local audit metadata."""
    try:
        context = getattr(_thread_local, "context", {})
        if isinstance(context, dict):
            return dict(context)
    except Exception as exc:
        logger.debug("Failed to get audit context: %s", exc)
    return {}


def clear_audit_context() -> None:
    """Clear thread-local audit metadata."""
    try:
        if hasattr(_thread_local, "context"):
            delattr(_thread_local, "context")
    except Exception as exc:
        logger.debug("Failed to clear audit context: %s", exc)


def _cleanup_old_logs(max_age_days: int = 30) -> None:
    """Delete dated JSONL logs older than the retention window."""
    try:
        if max_age_days < 0:
            return
        cutoff = date.today() - timedelta(days=max_age_days)
        if not _AUDIT_DIR.exists():
            return
        for path in _AUDIT_DIR.glob("*.jsonl"):
            try:
                file_date = datetime.strptime(path.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if file_date < cutoff:
                path.unlink(missing_ok=True)
    except Exception as exc:
        logger.debug("Failed to cleanup old AI audit logs: %s", exc)


def _run_daily_cleanup_once() -> None:
    """Run cleanup once per calendar day."""
    global _last_cleanup_date
    today = date.today()
    if _last_cleanup_date == today:
        return
    with _cleanup_lock:
        if _last_cleanup_date == today:
            return
        _cleanup_old_logs()
        _last_cleanup_date = today


class AuditLogger:
    """Singleton writer for JSONL AI audit records."""

    _instance: AuditLogger | None = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> AuditLogger:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "_write_lock"):
            self._write_lock = threading.Lock()

    def log_inference(self, **kwargs: Any) -> None:
        """Write one JSONL audit record. Never raises to caller."""
        try:
            _run_daily_cleanup_once()
            _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
            record = self._build_record(**kwargs)
            line = json.dumps(record, ensure_ascii=False, default=str)
            output_file = _AUDIT_DIR / f"{date.today().isoformat()}.jsonl"
            with self._write_lock:
                with output_file.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except Exception as exc:
            logger.debug("Failed to write AI audit inference record: %s", exc)

    def _build_record(self, **kwargs: Any) -> dict[str, Any]:
        timestamp = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        record: dict[str, Any] = {
            "timestamp": timestamp,
            "function": kwargs.pop("function", None),
            "model": kwargs.pop("model", None),
            "provider": kwargs.pop("provider", None),
            "input_chars": kwargs.pop("input_chars", None),
            "input_hash": kwargs.pop("input_hash", None),
            "output_summary": kwargs.pop("output_summary", None),
            "duration_ms": kwargs.pop("duration_ms", None),
            "success": kwargs.pop("success", None),
            "error": kwargs.pop("error", None),
            "tickers_extracted": kwargs.pop("tickers_extracted", None),
            "sentiment": kwargs.pop("sentiment", None),
            "logic_check": kwargs.pop("logic_check", None),
            "market_relevance": kwargs.pop("market_relevance", None),
            "caller": kwargs.pop("caller", None),
            "article_url": kwargs.pop("article_url", None),
            "article_title": kwargs.pop("article_title", None),
        }
        record.update(kwargs)
        if record["provider"] is None:
            record["provider"] = _detect_provider(record["model"])
        return record


_AUDIT_LOGGER = AuditLogger()


def log_inference(**kwargs: Any) -> None:
    """Public helper for writing one AI inference audit entry."""
    _AUDIT_LOGGER.log_inference(**kwargs)
