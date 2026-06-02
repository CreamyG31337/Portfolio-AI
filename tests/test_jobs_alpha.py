"""Focused tests for the alpha_research job's job-tracking contract.

The bug being guarded against here: early-return branches that ran AFTER
``mark_job_started`` used to leave the ``job_executions`` row in
``status='running'`` until the stale-lock cleaner in
``utils/job_tracking.get_running_ai_job`` eventually flipped it to
``failed``. That produced false-positive "failed" rows in the dashboard
even though the job had legitimately no work to do (e.g. no alpha domains
configured, SearXNG offline, no search results).

These tests pin the contract: every code path that runs after
``mark_job_started`` must call either ``mark_job_completed`` or
``mark_job_failed`` exactly once before returning, and skips for
configuration reasons (no domains, no results, SearXNG offline) are
treated as **successful** no-ops -- not failures.
"""

from __future__ import annotations

import sys
import types
from typing import Any


# --------------------------------------------------------------------------- #
# Tracking stub
# --------------------------------------------------------------------------- #


def _install_tracking_stub(monkeypatch) -> dict[str, list[dict[str, Any]]]:
    """Patch the relevant functions on the real ``utils.job_tracking`` module.

    We deliberately patch attributes on the loaded module rather than
    replacing the module in ``sys.modules`` because the production scheduler
    code in ``web_dashboard/scheduler/jobs_watchdog.py`` aggressively
    ``del sys.modules['utils.job_tracking']`` at module-import time to avoid
    shadowing by ``web_dashboard/utils/``. That clobbers any sys.modules
    replacement, but it only runs once per process (top-level module code),
    so by the time tests call this helper -- AFTER they have already imported
    ``web_dashboard.scheduler`` via ``_import_alpha()`` -- the module is
    stable and ``setattr`` on the cached ``utils.job_tracking`` module
    persists for the duration of the test.

    Callers must therefore invoke ``_import_alpha()`` before this helper.
    """
    import utils.job_tracking as job_tracking_mod  # noqa: WPS433

    calls: dict[str, list[dict[str, Any]]] = {
        "started": [],
        "completed": [],
        "failed": [],
        "steps": [],
    }

    def mark_job_started(job_name, target_date, fund_name=None):
        calls["started"].append(
            {"job_name": job_name, "target_date": target_date, "fund_name": fund_name}
        )

    def mark_job_completed(
        job_name,
        target_date,
        fund_name,
        funds_processed,
        duration_ms=None,
        message=None,
    ):
        calls["completed"].append(
            {
                "job_name": job_name,
                "target_date": target_date,
                "fund_name": fund_name,
                "funds_processed": list(funds_processed),
                "duration_ms": duration_ms,
                "message": message,
            }
        )

    def mark_job_failed(job_name, target_date, fund_name, error, duration_ms=None):
        calls["failed"].append(
            {
                "job_name": job_name,
                "target_date": target_date,
                "fund_name": fund_name,
                "error": error,
                "duration_ms": duration_ms,
            }
        )

    def log_job_step(job_id, step, message, status="info"):
        calls["steps"].append(
            {"job_id": job_id, "step": step, "message": message, "status": status}
        )

    def get_running_ai_job(exclude_job_name=None, max_age_hours=1, **_kw):
        return None

    monkeypatch.setattr(job_tracking_mod, "mark_job_started", mark_job_started)
    monkeypatch.setattr(job_tracking_mod, "mark_job_completed", mark_job_completed)
    monkeypatch.setattr(job_tracking_mod, "mark_job_failed", mark_job_failed)
    monkeypatch.setattr(job_tracking_mod, "log_job_step", log_job_step)
    monkeypatch.setattr(job_tracking_mod, "get_running_ai_job", get_running_ai_job)
    return calls


def _patch_log_job_execution(monkeypatch, calls: dict[str, list[dict[str, Any]]]) -> None:
    """Override ``scheduler.scheduler_core.log_job_execution`` in place.

    Importing the real ``web_dashboard.scheduler`` package eagerly pulls in a
    bunch of names from ``scheduler.scheduler_core`` (``get_scheduler``,
    ``start_scheduler``, ...), so we cannot just replace the whole module --
    that breaks the package ``__init__`` if it has not run yet. Instead we
    keep the real module and only swap the one attribute the job actually
    calls.
    """
    calls["executions"] = []
    # Force the real module to load first so the attribute exists.
    import scheduler.scheduler_core as scheduler_core  # noqa: WPS433

    def fake_log_job_execution(job_id, success, message, duration_ms=None):
        calls["executions"].append(
            {
                "job_id": job_id,
                "success": success,
                "message": message,
                "duration_ms": duration_ms,
            }
        )

    monkeypatch.setattr(scheduler_core, "log_job_execution", fake_log_job_execution)


def _install_settings_stub(monkeypatch, *, domains: list[str], queries: list[str]) -> None:
    """Stub ``settings.get_alpha_research_domains`` / ``get_alpha_search_queries``."""
    module = types.ModuleType("settings")

    def get_alpha_research_domains():
        return list(domains)

    def get_alpha_search_queries():
        return list(queries)

    def get_research_domain_blacklist():
        return []

    module.get_alpha_research_domains = get_alpha_research_domains
    module.get_alpha_search_queries = get_alpha_search_queries
    module.get_research_domain_blacklist = get_research_domain_blacklist
    monkeypatch.setitem(sys.modules, "settings", module)


def _install_searxng_stub(monkeypatch, *, healthy: bool, client=object()) -> None:
    module = types.ModuleType("searxng_client")

    def get_searxng_client():
        return client

    def check_searxng_health():
        return healthy

    module.get_searxng_client = get_searxng_client
    module.check_searxng_health = check_searxng_health
    monkeypatch.setitem(sys.modules, "searxng_client", module)


def _install_ollama_stub(monkeypatch) -> None:
    module = types.ModuleType("ollama_client")

    def get_ollama_client():
        return object()

    module.get_ollama_client = get_ollama_client
    monkeypatch.setitem(sys.modules, "ollama_client", module)


def _install_research_repo_stub(monkeypatch) -> None:
    module = types.ModuleType("research_repository")

    class ResearchRepository:
        def __init__(self, *_a, **_kw):
            pass

    module.ResearchRepository = ResearchRepository
    monkeypatch.setitem(sys.modules, "research_repository", module)


def _import_alpha():
    """Import the alpha job module.

    No reimport / cache busting is needed -- ``alpha_research_job`` re-resolves
    all of its tracking utilities through ``import``/``sys.modules`` at every
    call, so swapping the stubs via ``monkeypatch`` between imports and the
    call site is enough.
    """
    from web_dashboard.scheduler import jobs_alpha as job_mod  # noqa: WPS433

    return job_mod


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_no_domains_or_queries_is_success_not_running_leak(monkeypatch):
    """The originally-reported bug: empty config used to leave a running row.

    Order matters: ``_import_alpha`` must run BEFORE ``_install_tracking_stub``
    because importing ``web_dashboard.scheduler`` transitively pulls in
    ``jobs_watchdog`` whose module-level code wipes ``utils.job_tracking``
    out of ``sys.modules``. After that one-time scrub the module is stable
    and our setattr patches survive.
    """
    job_mod = _import_alpha()
    calls = _install_tracking_stub(monkeypatch)
    _patch_log_job_execution(monkeypatch, calls)
    _install_settings_stub(monkeypatch, domains=[], queries=[])
    _install_searxng_stub(monkeypatch, healthy=True)
    _install_ollama_stub(monkeypatch)
    _install_research_repo_stub(monkeypatch)

    job_mod.alpha_research_job()

    # Started exactly once...
    assert len(calls["started"]) == 1
    assert calls["started"][0]["job_name"] == "alpha_research"

    # ...and CLEARED via mark_job_completed (success), never mark_job_failed.
    assert len(calls["completed"]) == 1, calls
    assert calls["failed"] == []
    assert "No alpha domains or queries configured" in calls["completed"][0]["message"]

    # log_job_execution also reports success so the UI does not show a red row.
    assert any(
        e["job_id"] == "alpha_research" and e["success"] is True
        for e in calls["executions"]
    )


def test_searxng_offline_is_success_skip_not_failure(monkeypatch):
    """SearXNG being down is an intentional skip, not an execution failure."""
    job_mod = _import_alpha()
    calls = _install_tracking_stub(monkeypatch)
    _patch_log_job_execution(monkeypatch, calls)
    _install_settings_stub(monkeypatch, domains=["a.com"], queries=["x"])
    _install_searxng_stub(monkeypatch, healthy=False)
    _install_ollama_stub(monkeypatch)
    _install_research_repo_stub(monkeypatch)

    job_mod.alpha_research_job()

    assert len(calls["started"]) == 1
    assert len(calls["completed"]) == 1
    assert calls["failed"] == []
    assert "SearXNG is not available" in calls["completed"][0]["message"]


def test_missing_dependency_marks_failed(monkeypatch):
    """A real ImportError during dep loading is a true failure -> mark_job_failed."""
    job_mod = _import_alpha()
    calls = _install_tracking_stub(monkeypatch)
    _patch_log_job_execution(monkeypatch, calls)
    # Force the in-function ``from searxng_client import ...`` to fail by
    # installing a sentinel module that does not export the required names.
    # Removing the module isn't enough because conftest.py keeps web_dashboard
    # on sys.path -- the real searxng_client lives there and would be picked
    # up. A module without the attribute causes ImportError on ``from ... import``.
    broken = types.ModuleType("searxng_client")
    monkeypatch.setitem(sys.modules, "searxng_client", broken)

    job_mod.alpha_research_job()

    assert len(calls["started"]) == 1
    assert calls["completed"] == []
    assert len(calls["failed"]) == 1, calls
    assert "Missing dependency" in calls["failed"][0]["error"]
    # log_job_execution should reflect the failure too.
    assert any(
        e["job_id"] == "alpha_research" and e["success"] is False
        for e in calls["executions"]
    )


def test_ai_lock_active_returns_before_mark_started(monkeypatch):
    """When another AI job holds the lock, we must return without creating a row."""
    job_mod = _import_alpha()
    calls = _install_tracking_stub(monkeypatch)
    _patch_log_job_execution(monkeypatch, calls)

    # Override the lock check to claim another AI job is currently running.
    import utils.job_tracking as job_tracking_mod  # noqa: WPS433
    monkeypatch.setattr(
        job_tracking_mod, "get_running_ai_job", lambda **_kw: "rebalance"
    )

    job_mod.alpha_research_job()

    # CRITICAL: no row created and nothing to clear.
    assert calls["started"] == []
    assert calls["completed"] == []
    assert calls["failed"] == []
