"""Tests for the daily critical data backup job.

Scope under test:
* Slug helper (fund name -> filesystem/storage-safe slug)
* CSV rendering for trades (header-only on empty, full rows otherwise)
* CSV rendering for generic table rows (no header on empty + warning, ordered
  columns on non-empty)
* Per-fund trade-log backup helper writes to both destinations on the expected
  paths and tolerates each kind of failure
* Per-table backup helper writes to both destinations, paginates a 2-page
  fetch, and warns loudly on empty tables
* Top-level ``daily_critical_data_backup_job``:
  - happy multi-fund + multi-table run produces both summaries
  - all-destinations failure marks the job failed
  - per-fund unhandled error doesn't stop other funds or table backups
  - per-table fetch failure doesn't stop other tables or the trade-log section
  - missing funds row still backs up tables successfully
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, UTC
from decimal import Decimal
from typing import Any

import pytest


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class _FakeStorageBucket:
    """Captures upload() calls and optionally raises a configured exception."""

    def __init__(self, raise_exc: Exception | None = None) -> None:
        self.uploads: list[dict[str, Any]] = []
        self._raise = raise_exc

    def upload(self, path: str, file: bytes, file_options: dict[str, Any]) -> None:
        if self._raise is not None:
            raise self._raise
        self.uploads.append({"path": path, "file": file, "file_options": file_options})


class _FakeStorage:
    def __init__(self, bucket: _FakeStorageBucket) -> None:
        self._bucket = bucket
        self.opened_buckets: list[str] = []

    def from_(self, name: str) -> _FakeStorageBucket:
        self.opened_buckets.append(name)
        return self._bucket


class _FakeTableQuery:
    """Mimics the Supabase ``table().select().eq()/.range()/.execute()`` chain.

    ``rows`` is the full dataset for the table; pagination via ``range()``
    slices into it. ``raise_exc`` lets a test simulate a server error.
    """

    def __init__(
        self,
        rows: list[dict[str, Any]],
        *,
        raise_exc: Exception | None = None,
    ) -> None:
        self._rows = rows
        self._raise = raise_exc
        self._filter_active = False
        self._range: tuple | None = None

    def select(self, *_a, **_kw) -> _FakeTableQuery:
        return self

    def eq(self, key: str, value: Any) -> _FakeTableQuery:
        # Used by _list_active_funds: filter funds by is_production=True.
        if key == "is_production" and value is True:
            self._filter_active = True
        return self

    def range(self, lo: int, hi: int) -> _FakeTableQuery:
        self._range = (lo, hi)
        return self

    def execute(self) -> Any:
        if self._raise is not None:
            raise self._raise

        data = self._rows
        if self._filter_active:
            data = [r for r in data if r.get("is_production")]

        if self._range is not None:
            lo, hi = self._range
            # Supabase range() is inclusive on both ends.
            data = data[lo : hi + 1]
        return types.SimpleNamespace(data=data)


class _FakeAdminSupabase:
    """Stand-in for ``SupabaseClient(use_service_role=True).supabase``."""

    def __init__(
        self,
        *,
        bucket: _FakeStorageBucket,
        funds_rows: list[dict[str, Any]],
        table_rows: dict[str, list[dict[str, Any]]],
        table_errors: dict[str, Exception] | None = None,
    ) -> None:
        self.storage = _FakeStorage(bucket)
        self._funds_rows = funds_rows
        self._table_rows = table_rows
        self._table_errors = table_errors or {}
        self.calls: dict[str, int] = {}

    def table(self, name: str) -> _FakeTableQuery:
        self.calls[name] = self.calls.get(name, 0) + 1
        if name in self._table_errors:
            return _FakeTableQuery([], raise_exc=self._table_errors[name])
        # The `funds` table is hit twice per run (enumeration via select("name")
        # .eq("is_production", True) AND the full-table backup via select("*").
        # Both should see the same dataset, so we route every "funds" lookup
        # through funds_rows and ignore any override in table_rows.
        if name == "funds":
            return _FakeTableQuery(self._funds_rows)
        return _FakeTableQuery(list(self._table_rows.get(name, [])))


class _FakeAdminClient:
    """Stand-in for ``SupabaseClient(use_service_role=True)``."""

    def __init__(self, supabase: _FakeAdminSupabase) -> None:
        self.supabase = supabase


class _FakeTrade:
    """Mimics ``data.models.trade.Trade`` for the renderer's getattr usage."""

    def __init__(
        self,
        *,
        trade_id: str,
        ticker: str,
        action: str,
        shares: Decimal,
        price: Decimal,
        timestamp: datetime,
        cost_basis: Decimal | None = None,
        pnl: Decimal | None = None,
        currency: str = "CAD",
        reason: str | None = None,
    ) -> None:
        self.trade_id = trade_id
        self.ticker = ticker
        self.action = action
        self.shares = shares
        self.price = price
        self.timestamp = timestamp
        self.cost_basis = cost_basis
        self.pnl = pnl
        self.currency = currency
        self.reason = reason


class _FakeRepository:
    """In-memory replacement for ``SupabaseRepository``."""

    def __init__(
        self,
        fund_name: str,
        trades: list[_FakeTrade],
        bucket: _FakeStorageBucket,
        *,
        raise_on_history: Exception | None = None,
    ) -> None:
        self.fund_name = fund_name
        self.fund = fund_name
        self._trades = trades
        self._raise_on_history = raise_on_history
        # Repo only uses .supabase for storage uploads; safe to give it a
        # minimal shim with just the storage attribute.
        self.supabase = types.SimpleNamespace(storage=_FakeStorage(bucket))

    def get_trade_history(self):
        if self._raise_on_history is not None:
            raise self._raise_on_history
        return list(self._trades)


# --------------------------------------------------------------------------- #
# Common monkeypatch helpers
# --------------------------------------------------------------------------- #


@pytest.fixture
def install_tracking_stub(monkeypatch):
    """Capture mark_job_started/_completed/_failed calls."""
    calls: dict[str, list[dict[str, Any]]] = {
        "started": [],
        "completed": [],
        "failed": [],
    }

    module = types.ModuleType("utils.job_tracking")

    def mark_job_started(job_name, target_date, fund_name=None):
        calls["started"].append(
            {"job_name": job_name, "target_date": target_date, "fund_name": fund_name}
        )

    def mark_job_completed(
        job_name, target_date, fund_name, funds_processed, duration_ms=None, message=None
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

    module.mark_job_started = mark_job_started
    module.mark_job_completed = mark_job_completed
    module.mark_job_failed = mark_job_failed

    monkeypatch.setitem(sys.modules, "utils.job_tracking", module)
    return calls


@pytest.fixture
def silence_log_execution(monkeypatch):
    """Avoid writing to the in-memory _job_logs during tests."""
    import web_dashboard.scheduler.jobs_daily_backup as job_mod

    monkeypatch.setattr(job_mod, "log_job_execution", lambda *a, **kw: None)


def _make_trade(ticker: str, shares: str, price: str) -> _FakeTrade:
    return _FakeTrade(
        trade_id=f"id-{ticker}",
        ticker=ticker,
        action="BUY",
        shares=Decimal(shares),
        price=Decimal(price),
        timestamp=datetime(2026, 5, 23, 14, 30, tzinfo=UTC),
        cost_basis=Decimal(shares) * Decimal(price),
        pnl=Decimal("0"),
        currency="USD",
        reason="unit test",
    )


# --------------------------------------------------------------------------- #
# Slug
# --------------------------------------------------------------------------- #


def test_daily_backup_keeps_repo_root_ahead_of_web_dashboard_path():
    from web_dashboard.scheduler import jobs_daily_backup as job_mod

    project_root_index = sys.path.index(str(job_mod._project_root))
    web_dashboard_index = sys.path.index(str(job_mod._web_dashboard_path))

    assert project_root_index < web_dashboard_index


def test_slugify_fund_name_simple_cases():
    from web_dashboard.scheduler.jobs_daily_backup import slugify_fund_name

    assert slugify_fund_name("TEST") == "test"
    assert slugify_fund_name("Project Chimera") == "project_chimera"
    assert slugify_fund_name("RRSP Lance Webull") == "rrsp_lance_webull"
    assert slugify_fund_name("Fund-With-Hyphens") == "fund_with_hyphens"
    assert slugify_fund_name("Mixed Case 2026 Q1") == "mixed_case_2026_q1"


def test_slugify_fund_name_strips_punctuation_and_empties():
    from web_dashboard.scheduler.jobs_daily_backup import slugify_fund_name

    assert slugify_fund_name("Fund!@#Name") == "fundname"
    assert slugify_fund_name("A   B--C..D") == "a_b_c_d"
    assert slugify_fund_name("") == "unnamed_fund"
    assert slugify_fund_name("   ") == "unnamed_fund"
    assert slugify_fund_name("!!!") == "unnamed_fund"


# --------------------------------------------------------------------------- #
# CSV rendering
# --------------------------------------------------------------------------- #


def test_trades_to_csv_bytes_writes_header_only_for_empty():
    from web_dashboard.scheduler.jobs_daily_backup import (
        TRADE_CSV_COLUMNS,
        _trades_to_csv_bytes,
    )

    payload = _trades_to_csv_bytes([])
    text = payload.decode("utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0] == ",".join(TRADE_CSV_COLUMNS)


def test_trades_to_csv_bytes_renders_full_rows():
    from web_dashboard.scheduler.jobs_daily_backup import _trades_to_csv_bytes

    payload = _trades_to_csv_bytes(
        [_make_trade("AAPL", "10", "150.25"), _make_trade("MSFT", "5", "320.00")]
    )
    text = payload.decode("utf-8")
    lines = text.splitlines()
    assert len(lines) == 3  # header + 2 rows
    assert "AAPL" in lines[1]
    assert "MSFT" in lines[2]
    assert "150.25" in lines[1]  # Decimal precision preserved via str()


def test_rows_to_csv_bytes_empty_returns_no_header():
    from web_dashboard.scheduler.jobs_daily_backup import _rows_to_csv_bytes

    payload, has_header = _rows_to_csv_bytes([])
    assert payload == b""
    assert has_header is False


def test_rows_to_csv_bytes_preserves_column_order_and_handles_sparse_keys():
    """First-row keys win for ordering; later-row-only keys are appended."""
    from web_dashboard.scheduler.jobs_daily_backup import _rows_to_csv_bytes

    rows = [
        {"id": 1, "name": "alpha", "is_production": True},
        {"id": 2, "name": "beta", "is_production": False, "tax_status": "tfsa"},
    ]
    payload, has_header = _rows_to_csv_bytes(rows)
    assert has_header is True

    text = payload.decode("utf-8").splitlines()
    header = text[0].split(",")
    assert header == ["id", "name", "is_production", "tax_status"]
    # Sparse cell becomes empty string for the first row.
    assert text[1].startswith("1,alpha,True,")
    assert text[2].startswith("2,beta,False,tfsa")


# --------------------------------------------------------------------------- #
# Per-fund trade-log backup helper
# --------------------------------------------------------------------------- #


def test_backup_fund_trade_log_happy_path(tmp_path):
    from web_dashboard.scheduler.jobs_daily_backup import _backup_fund_trade_log

    bucket = _FakeStorageBucket()
    trades = [_make_trade("NVDA", "3", "1100.00")]

    def factory(fund_name: str) -> _FakeRepository:
        assert fund_name == "Project Chimera"
        return _FakeRepository(fund_name, trades, bucket)

    row_count, host_ok, storage_ok, warnings = _backup_fund_trade_log(
        "Project Chimera",
        backup_root=tmp_path,
        date_str="2026-05-23",
        repository_factory=factory,
    )

    assert row_count == 1
    assert host_ok is True
    assert storage_ok is True
    assert warnings == []

    # Host path: tmp_path/trade_log/project_chimera_trades.csv
    written = list(tmp_path.rglob("*.csv"))
    assert len(written) == 1
    assert written[0].name == "project_chimera_trades.csv"
    assert written[0].parent.name == "trade_log"

    # Storage path: daily/2026-05-23/trade_log/project_chimera_trades.csv
    assert len(bucket.uploads) == 1
    upload = bucket.uploads[0]
    assert upload["path"] == "daily/2026-05-23/trade_log/project_chimera_trades.csv"
    assert upload["file_options"]["upsert"] == "true"
    assert upload["file_options"]["content-type"] == "text/csv"
    assert b"NVDA" in upload["file"]


def test_backup_fund_trade_log_empty_history_still_writes_header(tmp_path):
    from web_dashboard.scheduler.jobs_daily_backup import _backup_fund_trade_log

    bucket = _FakeStorageBucket()

    def factory(_name: str) -> _FakeRepository:
        return _FakeRepository("TEST", [], bucket)

    row_count, host_ok, storage_ok, warnings = _backup_fund_trade_log(
        "TEST",
        backup_root=tmp_path,
        date_str="2026-01-01",
        repository_factory=factory,
    )

    assert row_count == 0
    assert host_ok is True
    assert storage_ok is True
    assert warnings == []

    host_files = list(tmp_path.rglob("*.csv"))
    assert len(host_files) == 1
    body = host_files[0].read_text(encoding="utf-8").splitlines()
    assert len(body) == 1  # header only
    assert body[0].startswith("trade_id,timestamp,ticker")


def test_backup_fund_trade_log_storage_still_runs_when_host_missing():
    from web_dashboard.scheduler.jobs_daily_backup import _backup_fund_trade_log

    bucket = _FakeStorageBucket()
    trades = [_make_trade("AMZN", "2", "200.00")]

    def factory(_name: str) -> _FakeRepository:
        return _FakeRepository("TEST", trades, bucket)

    row_count, host_ok, storage_ok, warnings = _backup_fund_trade_log(
        "TEST",
        backup_root=None,
        date_str="2026-03-15",
        repository_factory=factory,
    )

    assert row_count == 1
    assert host_ok is False
    assert storage_ok is True
    assert any("host volume not mounted" in w for w in warnings)
    assert len(bucket.uploads) == 1


def test_backup_fund_trade_log_storage_failure_keeps_host_copy(tmp_path):
    from web_dashboard.scheduler.jobs_daily_backup import _backup_fund_trade_log

    bucket = _FakeStorageBucket(raise_exc=RuntimeError("upload boom"))
    trades = [_make_trade("META", "4", "500.00")]

    def factory(_name: str) -> _FakeRepository:
        return _FakeRepository("TEST", trades, bucket)

    row_count, host_ok, storage_ok, warnings = _backup_fund_trade_log(
        "TEST",
        backup_root=tmp_path,
        date_str="2026-06-01",
        repository_factory=factory,
    )

    assert row_count == 1
    assert host_ok is True
    assert storage_ok is False
    assert any("storage upload failed" in w for w in warnings)
    assert list(tmp_path.rglob("*.csv"))


def test_backup_fund_trade_log_bucket_missing_warning(tmp_path):
    from web_dashboard.scheduler.jobs_daily_backup import _backup_fund_trade_log

    bucket = _FakeStorageBucket(
        raise_exc=Exception("Bucket not found: daily-backups")
    )

    def factory(_name: str) -> _FakeRepository:
        return _FakeRepository("TEST", [_make_trade("GOOG", "1", "150.0")], bucket)

    _row_count, _host_ok, storage_ok, warnings = _backup_fund_trade_log(
        "TEST",
        backup_root=tmp_path,
        date_str="2026-06-01",
        repository_factory=factory,
    )

    assert storage_ok is False
    assert any("setup_daily_backup_bucket.py" in w for w in warnings), warnings


def test_backup_fund_trade_log_history_failure_is_total_failure(tmp_path):
    from web_dashboard.scheduler.jobs_daily_backup import _backup_fund_trade_log

    bucket = _FakeStorageBucket()

    def factory(_name: str) -> _FakeRepository:
        return _FakeRepository(
            "TEST", [], bucket, raise_on_history=RuntimeError("postgres down")
        )

    row_count, host_ok, storage_ok, warnings = _backup_fund_trade_log(
        "TEST",
        backup_root=tmp_path,
        date_str="2026-06-01",
        repository_factory=factory,
    )

    assert row_count == 0
    assert host_ok is False
    assert storage_ok is False
    assert any("trade fetch failed" in w for w in warnings)
    assert bucket.uploads == []
    assert list(tmp_path.rglob("*.csv")) == []


# --------------------------------------------------------------------------- #
# Per-table backup helper
# --------------------------------------------------------------------------- #


def test_backup_table_happy_path(tmp_path):
    from web_dashboard.scheduler.jobs_daily_backup import _backup_table

    bucket = _FakeStorageBucket()
    admin = _FakeAdminClient(
        _FakeAdminSupabase(
            bucket=bucket,
            funds_rows=[
                {"id": 1, "name": "Project Chimera", "is_production": True},
                {"id": 2, "name": "TFSA", "is_production": True},
            ],
            table_rows={},
        )
    )

    row_count, host_ok, storage_ok, warnings = _backup_table(
        "funds",
        admin_client=admin,
        backup_root=tmp_path,
        date_str="2026-05-23",
    )

    assert row_count == 2
    assert host_ok is True
    assert storage_ok is True
    assert warnings == []

    host_files = list(tmp_path.rglob("*.csv"))
    assert len(host_files) == 1
    assert host_files[0].name == "funds.csv"
    assert host_files[0].parent.name == "tables"

    assert len(bucket.uploads) == 1
    assert bucket.uploads[0]["path"] == "daily/2026-05-23/tables/funds.csv"
    csv_text = host_files[0].read_text(encoding="utf-8").splitlines()
    assert csv_text[0].startswith("id,name,is_production")
    assert any("Project Chimera" in line for line in csv_text[1:])


def test_backup_table_empty_writes_zero_byte_csv_with_warning(tmp_path):
    from web_dashboard.scheduler.jobs_daily_backup import _backup_table

    bucket = _FakeStorageBucket()
    admin = _FakeAdminClient(
        _FakeAdminSupabase(
            bucket=bucket,
            funds_rows=[],
            table_rows={"ai_analysis_skip_list": []},
        )
    )

    row_count, host_ok, storage_ok, warnings = _backup_table(
        "ai_analysis_skip_list",
        admin_client=admin,
        backup_root=tmp_path,
        date_str="2026-05-23",
    )

    assert row_count == 0
    assert host_ok is True
    assert storage_ok is True
    # The empty-table warning specifically calls out the missing header.
    assert any(
        "empty table" in w and "ai_analysis_skip_list" in w for w in warnings
    ), warnings

    host_file = (tmp_path / "tables" / "ai_analysis_skip_list.csv")
    assert host_file.exists()
    assert host_file.stat().st_size == 0


def test_backup_table_paginates_above_1000_rows(tmp_path, monkeypatch):
    from web_dashboard.scheduler import jobs_daily_backup as job_mod

    # Force a small page size so we don't need 1001 rows in test data.
    monkeypatch.setattr(job_mod, "_TABLE_PAGE_SIZE", 3)

    bucket = _FakeStorageBucket()
    # 7 rows -> 3 pages (3 + 3 + 1)
    rows = [{"id": i, "name": f"row{i}"} for i in range(7)]
    admin = _FakeAdminClient(
        _FakeAdminSupabase(
            bucket=bucket, funds_rows=[], table_rows={"user_profiles": rows}
        )
    )

    row_count, host_ok, storage_ok, warnings = job_mod._backup_table(
        "user_profiles",
        admin_client=admin,
        backup_root=tmp_path,
        date_str="2026-05-23",
    )

    assert row_count == 7
    assert host_ok is True
    assert storage_ok is True
    assert warnings == []

    body = (tmp_path / "tables" / "user_profiles.csv").read_text(encoding="utf-8").splitlines()
    # header + 7 rows
    assert len(body) == 8
    assert "row6" in body[-1]


def test_backup_table_fetch_failure_records_warning_and_skips_writes(tmp_path):
    from web_dashboard.scheduler.jobs_daily_backup import _backup_table

    bucket = _FakeStorageBucket()
    admin = _FakeAdminClient(
        _FakeAdminSupabase(
            bucket=bucket,
            funds_rows=[],
            table_rows={},
            table_errors={"system_settings": RuntimeError("postgres unavailable")},
        )
    )

    row_count, host_ok, storage_ok, warnings = _backup_table(
        "system_settings",
        admin_client=admin,
        backup_root=tmp_path,
        date_str="2026-05-23",
    )

    assert row_count == 0
    assert host_ok is False
    assert storage_ok is False
    assert any("fetch failed" in w for w in warnings)
    assert list(tmp_path.rglob("*.csv")) == []
    assert bucket.uploads == []


# --------------------------------------------------------------------------- #
# Top-level job orchestration
# --------------------------------------------------------------------------- #


def _build_admin_factory(
    bucket: _FakeStorageBucket,
    funds_rows: list[dict[str, Any]],
    table_rows: dict[str, list[dict[str, Any]]] | None = None,
    table_errors: dict[str, Exception] | None = None,
):
    """Helper: produce the factory the job uses to build its admin client."""
    fake = _FakeAdminSupabase(
        bucket=bucket,
        funds_rows=funds_rows,
        table_rows=table_rows or {},
        table_errors=table_errors,
    )
    return lambda: _FakeAdminClient(fake), fake


def test_daily_backup_job_happy_multi_fund_and_multi_table(
    monkeypatch,
    tmp_path,
    install_tracking_stub,
    silence_log_execution,
):
    from web_dashboard.scheduler import jobs_daily_backup as job_mod

    bucket = _FakeStorageBucket()
    funds_rows = [
        {"id": 1, "name": "Project Chimera", "is_production": True},
        {"id": 2, "name": "TFSA", "is_production": True},
    ]
    # Every critical table (except `funds`, which is served from funds_rows
    # to keep enumeration and backup in sync) has at least one row so empty-
    # table warnings stay out of the happy-path summary.
    table_rows = {
        name: [{"id": 1, "placeholder": f"{name}-row"}]
        for name in job_mod.CRITICAL_APP_TABLES
        if name != "funds"
    }
    admin_factory, _ = _build_admin_factory(bucket, funds_rows, table_rows)

    fund_trades = {
        "Project Chimera": [_make_trade("AAPL", "5", "180.00")],
        "TFSA": [_make_trade("VFV.TO", "10", "120.00"), _make_trade("XEQT.TO", "20", "30.00")],
    }

    def repo_factory(fund_name: str) -> _FakeRepository:
        return _FakeRepository(fund_name, fund_trades[fund_name], bucket)

    monkeypatch.setattr(job_mod, "DEFAULT_HOST_BACKUP_ROOT", tmp_path)

    job_mod.daily_critical_data_backup_job(
        repository_factory=repo_factory,
        admin_client_factory=admin_factory,
    )

    # 2 fund uploads + 11 table uploads = 13 storage objects.
    assert len(bucket.uploads) == 2 + len(job_mod.CRITICAL_APP_TABLES)

    paths = sorted(u["path"] for u in bucket.uploads)
    assert any(p.endswith("/trade_log/project_chimera_trades.csv") for p in paths)
    assert any(p.endswith("/trade_log/tfsa_trades.csv") for p in paths)
    assert any(p.endswith("/tables/funds.csv") for p in paths)
    assert any(p.endswith("/tables/contributor_access.csv") for p in paths)

    # Host: per-day folder, then trade_log/ and tables/ subfolders.
    day_folders = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(day_folders) == 1
    daily = day_folders[0]
    assert (daily / "trade_log").is_dir()
    assert (daily / "tables").is_dir()
    assert len(list((daily / "trade_log").glob("*.csv"))) == 2
    assert len(list((daily / "tables").glob("*.csv"))) == len(job_mod.CRITICAL_APP_TABLES)

    # Tracking: one started + one completed, no failures.
    assert len(install_tracking_stub["started"]) == 1
    assert len(install_tracking_stub["completed"]) == 1
    assert install_tracking_stub["failed"] == []
    summary = install_tracking_stub["completed"][0]["message"]
    # Trade-log wording leads; table count follows. User explicitly asked to
    # keep trade_log front-and-centre in the summary even though the scope
    # widened.
    assert "trade_log" in summary
    assert "2 funds" in summary
    assert "11 critical tables" in summary
    assert "trade_log failures: none" in summary
    assert "table failures: none" in summary


def test_daily_backup_job_marks_failed_when_all_destinations_miss(
    monkeypatch,
    tmp_path,
    install_tracking_stub,
    silence_log_execution,
):
    """Single fund + every table broken on BOTH destinations -> failed run."""
    from web_dashboard.scheduler import jobs_daily_backup as job_mod

    bucket = _FakeStorageBucket(raise_exc=RuntimeError("storage gone"))
    funds_rows = [{"id": 1, "name": "TEST", "is_production": True}]
    table_rows = {
        name: [{"id": 1}]
        for name in job_mod.CRITICAL_APP_TABLES
        if name != "funds"
    }
    admin_factory, _ = _build_admin_factory(bucket, funds_rows, table_rows)

    def repo_factory(name: str) -> _FakeRepository:
        return _FakeRepository(name, [_make_trade("AAPL", "1", "1.0")], bucket)

    # Force the host root onto a file path so mkdir() raises -> backup_root None
    blocked = tmp_path / "this_is_a_file"
    blocked.write_text("not a dir")
    monkeypatch.setattr(job_mod, "DEFAULT_HOST_BACKUP_ROOT", blocked)

    job_mod.daily_critical_data_backup_job(
        repository_factory=repo_factory,
        admin_client_factory=admin_factory,
    )

    assert install_tracking_stub["failed"], "expected at least one mark_job_failed call"
    assert install_tracking_stub["completed"] == []
    err = install_tracking_stub["failed"][0]["error"]
    assert "TEST" in err
    assert "trade_log failures" in err
    assert "table failures" in err


def test_daily_backup_job_per_fund_explosion_does_not_stop_others(
    monkeypatch,
    tmp_path,
    install_tracking_stub,
    silence_log_execution,
):
    from web_dashboard.scheduler import jobs_daily_backup as job_mod

    bucket = _FakeStorageBucket()
    funds_rows = [
        {"id": 1, "name": "GoodFund", "is_production": True},
        {"id": 2, "name": "BadFund", "is_production": True},
        {"id": 3, "name": "OtherFund", "is_production": True},
    ]
    table_rows = {
        name: [{"id": 1}]
        for name in job_mod.CRITICAL_APP_TABLES
        if name != "funds"
    }
    admin_factory, _ = _build_admin_factory(bucket, funds_rows, table_rows)

    def repo_factory(name: str) -> _FakeRepository:
        if name == "BadFund":
            raise RuntimeError("repository init exploded")
        return _FakeRepository(name, [_make_trade("AAPL", "1", "1.0")], bucket)

    monkeypatch.setattr(job_mod, "DEFAULT_HOST_BACKUP_ROOT", tmp_path)
    job_mod.daily_critical_data_backup_job(
        repository_factory=repo_factory,
        admin_client_factory=admin_factory,
    )

    paths = sorted(u["path"] for u in bucket.uploads)
    assert any("/trade_log/goodfund_trades.csv" in p for p in paths)
    assert any("/trade_log/otherfund_trades.csv" in p for p in paths)
    assert not any("/trade_log/badfund_trades.csv" in p for p in paths)
    # Tables still got backed up despite the bad fund.
    assert any("/tables/funds.csv" in p for p in paths)

    assert install_tracking_stub["failed"], "expected a mark_job_failed call"
    err = install_tracking_stub["failed"][0]["error"]
    assert "BadFund" in err


def test_daily_backup_job_per_table_failure_does_not_stop_other_tables_or_trade_log(
    monkeypatch,
    tmp_path,
    install_tracking_stub,
    silence_log_execution,
):
    from web_dashboard.scheduler import jobs_daily_backup as job_mod

    bucket = _FakeStorageBucket()
    funds_rows = [{"id": 1, "name": "GoodFund", "is_production": True}]
    table_rows = {
        name: [{"id": 1}]
        for name in job_mod.CRITICAL_APP_TABLES
        if name != "funds"
    }
    # system_settings fetch blows up; every other table is fine.
    table_errors = {"system_settings": RuntimeError("postgres down")}
    admin_factory, _ = _build_admin_factory(bucket, funds_rows, table_rows, table_errors)

    def repo_factory(name: str) -> _FakeRepository:
        return _FakeRepository(name, [_make_trade("AAPL", "1", "1.0")], bucket)

    monkeypatch.setattr(job_mod, "DEFAULT_HOST_BACKUP_ROOT", tmp_path)
    job_mod.daily_critical_data_backup_job(
        repository_factory=repo_factory,
        admin_client_factory=admin_factory,
    )

    paths = sorted(u["path"] for u in bucket.uploads)
    assert any("/trade_log/goodfund_trades.csv" in p for p in paths)
    # All tables except system_settings got uploaded.
    for table in job_mod.CRITICAL_APP_TABLES:
        if table == "system_settings":
            assert not any(p.endswith(f"/tables/{table}.csv") for p in paths)
        else:
            assert any(p.endswith(f"/tables/{table}.csv") for p in paths)

    # Job marked failed because system_settings missed both destinations.
    assert install_tracking_stub["failed"]
    err = install_tracking_stub["failed"][0]["error"]
    assert "system_settings" in err


def test_daily_backup_job_no_funds_still_backs_up_tables(
    monkeypatch,
    tmp_path,
    install_tracking_stub,
    silence_log_execution,
):
    """An empty funds table is not a job failure — we still snapshot config."""
    from web_dashboard.scheduler import jobs_daily_backup as job_mod

    bucket = _FakeStorageBucket()
    # funds_rows=[] -> enumeration finds zero AND the funds table snapshot is
    # an empty 0-byte CSV with a warning. All other tables have one row.
    table_rows = {
        name: [{"id": 1}]
        for name in job_mod.CRITICAL_APP_TABLES
        if name != "funds"
    }
    admin_factory, _ = _build_admin_factory(bucket, funds_rows=[], table_rows=table_rows)

    monkeypatch.setattr(job_mod, "DEFAULT_HOST_BACKUP_ROOT", tmp_path)

    job_mod.daily_critical_data_backup_job(
        repository_factory=lambda _n: pytest.fail("repo factory should not be called"),
        admin_client_factory=admin_factory,
    )

    # No trade-log uploads, but every table got uploaded.
    paths = sorted(u["path"] for u in bucket.uploads)
    assert not any("/trade_log/" in p for p in paths)
    for table in job_mod.CRITICAL_APP_TABLES:
        assert any(p.endswith(f"/tables/{table}.csv") for p in paths)

    # Empty funds table specifically should NOT cause an overall failure -
    # it's a warning at most (data exists in the rows we backed up to disk).
    # In this test funds table is empty so the funds.csv is a 0-byte file
    # with a warning, but it still counted as success on both destinations
    # because both writes succeeded.
    assert install_tracking_stub["completed"], "expected completed call"
    summary = install_tracking_stub["completed"][0]["message"]
    assert "0 funds" in summary
    assert f"{len(job_mod.CRITICAL_APP_TABLES)} critical tables" in summary
