"""/api/congress_trades/positions/data must page past PostgREST's 1000-row cap."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from flask_cache_utils import clear_all_caches


class _FakeQuery:
    """Chainable stand-in for a postgrest query over a fixed row list."""

    def __init__(self, rows: list[dict], ranges: list[tuple[int, int]]) -> None:
        self._rows = rows
        self._ranges = ranges
        self._head = False
        self._span: tuple[int, int] | None = None

    def select(self, *_args, count=None, head=False):
        self._head = head
        return self

    def gte(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, start: int, end: int):
        self._span = (start, end)
        self._ranges.append((start, end))
        return self

    def execute(self):
        if self._head:
            return SimpleNamespace(data=[], count=len(self._rows))
        start, end = self._span
        # PostgREST never returns more than 1000 rows per response.
        end = min(end, start + 999)
        return SimpleNamespace(data=self._rows[start : end + 1], count=None)


def _fake_client(rows: list[dict], ranges: list[tuple[int, int]]):
    supabase = SimpleNamespace(table=lambda _name: _FakeQuery(rows, ranges))
    return SimpleNamespace(supabase=supabase)


def test_positions_data_pages_past_postgrest_cap(client) -> None:
    clear_all_caches()
    rows = [
        {"id": i, "ticker": f"T{i}", "politicians": {"name": "Jane Doe" if i % 2 else "John Roe"}}
        for i in range(2500)
    ]
    ranges: list[tuple[int, int]] = []

    with patch("auth.auth_manager.verify_session") as mock_verify, patch(
        "flask_auth_utils.get_supabase_access_token", return_value="fake.jwt.token"
    ), patch("auth.is_admin", return_value=False), patch(
        "flask_data_utils.get_supabase_client_flask",
        return_value=_fake_client(rows, ranges),
    ):
        mock_verify.return_value = {"user_id": "u1", "email": "u1@example.com"}
        client.set_cookie("auth_token", "test.token.value")
        response = client.get(
            "/api/congress_trades/positions/data?period=all&limit=2000&politician=jane"
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert ranges == [(0, 999), (1000, 1999)]
    # Odd ids are Jane's; all 1000 of them within the first 2000 rows survive.
    assert len(payload["positions"]) == 1000
    assert payload["total"] == 2500
