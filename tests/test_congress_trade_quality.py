"""Tests for congress trade quality quarantine (fingerprint registry + apply)."""

from __future__ import annotations

from typing import Any

from web_dashboard.utils.congress_trade_quality import (
    KNOWN_BAD_TRADES,
    QUALITY_CORRECTED,
    QUALITY_GARBAGE,
    QUALITY_OK,
    apply_trade_quality_overrides,
    find_matching_rules,
    fingerprint_matches_row,
    is_analysis_eligible,
)


USOU_RULE = next(r for r in KNOWN_BAD_TRADES if r.get("ticker") == "USOU")


class TestEligibility:
    def test_garbage_out_corrected_in(self) -> None:
        assert is_analysis_eligible(QUALITY_OK) is True
        assert is_analysis_eligible(QUALITY_CORRECTED) is True
        assert is_analysis_eligible(QUALITY_GARBAGE) is False
        assert is_analysis_eligible(None) is True
        assert is_analysis_eligible("") is True


class TestRegistryMatch:
    def test_matches_by_bioguide_fingerprint_not_politician_id(self) -> None:
        row = {
            "ticker": "usou",
            "transaction_date": "2026-06-01",
            "type": "purchase",
            "amount": "$1,001-$15,000",
            "owner": "not disclosed",
        }
        matches = find_matching_rules(row, bioguide="C001120")
        assert len(matches) == 1
        assert matches[0]["suggested_ticker"] == "USO"

        # Wrong bioguide → no match even if trade fields align
        assert find_matching_rules(row, bioguide="K000398") == []

    def test_fingerprint_matches_row_ignores_optional_when_absent(self) -> None:
        rule = {
            "ticker": "USOU",
            "transaction_date": "2026-06-01",
            "type": "Purchase",
        }
        row = {
            "ticker": "USOU",
            "transaction_date": "2026-06-01",
            "type": "Purchase",
            "amount": "anything",
            "owner": "Self",
        }
        assert fingerprint_matches_row(rule, row) is True

    def test_amount_mismatch_rejects(self) -> None:
        row = {
            "ticker": "USOU",
            "transaction_date": "2026-06-01",
            "type": "Purchase",
            "amount": "$15,001 - $50,000",
            "owner": "Not-Disclosed",
        }
        assert fingerprint_matches_row(USOU_RULE, row) is False


class _Resp:
    def __init__(self, data: list[dict[str, Any]] | None = None) -> None:
        self.data = data or []


class _FakeQuery:
    def __init__(self, store: "_FakeStore", table: str) -> None:
        self._store = store
        self._table = table
        self._filters: list[tuple[str, Any]] = []
        self._in_filters: list[tuple[str, list[Any]]] = []
        self._limit: int | None = None
        self._op: str = "select"
        self._payload: Any = None
        self._on_conflict: str | None = None

    def select(self, *_args: Any, **_kwargs: Any) -> "_FakeQuery":
        self._op = "select"
        return self

    def eq(self, col: str, val: Any) -> "_FakeQuery":
        self._filters.append((col, val))
        return self

    def in_(self, col: str, vals: list[Any]) -> "_FakeQuery":
        self._in_filters.append((col, list(vals)))
        return self

    def limit(self, n: int) -> "_FakeQuery":
        self._limit = n
        return self

    def update(self, payload: dict[str, Any]) -> "_FakeQuery":
        self._op = "update"
        self._payload = payload
        return self

    def upsert(self, payload: dict[str, Any], on_conflict: str | None = None) -> "_FakeQuery":
        self._op = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def execute(self) -> _Resp:
        return self._store.execute(self)


class _FakeStore:
    """Minimal in-memory stand-in for congress_trades + politicians."""

    def __init__(self) -> None:
        self.politicians = [
            {"id": 99, "bioguide_id": "C001120", "name": "Dan Crenshaw"},
            {"id": 7, "bioguide_id": "K000398", "name": "Thomas Kean"},
        ]
        self.trades: list[dict[str, Any]] = []
        self._next_id = 1
        self.update_log: list[tuple[int, dict[str, Any]]] = []

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self, name)

    def _match_row(self, row: dict[str, Any], query: _FakeQuery) -> bool:
        for col, val in query._filters:
            if row.get(col) != val:
                return False
        for col, vals in query._in_filters:
            if row.get(col) not in vals:
                return False
        return True

    def execute(self, query: _FakeQuery) -> _Resp:
        if query._table == "politicians":
            rows = [p for p in self.politicians if self._match_row(p, query)]
            for col, vals in query._in_filters:
                if col == "bioguide_id":
                    upper = {str(v).upper() for v in vals}
                    rows = [p for p in self.politicians if str(p["bioguide_id"]).upper() in upper]
            return _Resp(rows)

        if query._op == "select":
            rows = [t for t in self.trades if self._match_row(t, query)]
            if query._limit is not None:
                rows = rows[: query._limit]
            return _Resp([dict(r) for r in rows])

        if query._op == "update":
            updated = 0
            for trade in self.trades:
                if self._match_row(trade, query):
                    # Simulate preserve trigger for garbage/corrected
                    old_status = trade.get("quality_status", QUALITY_OK)
                    payload = dict(query._payload)
                    if old_status in (QUALITY_GARBAGE, QUALITY_CORRECTED):
                        for key in ("quality_status", "quality_reason", "suggested_ticker"):
                            if key in payload:
                                payload[key] = trade.get(key)
                        if trade.get("replacement_trade_id") is not None and "replacement_trade_id" in payload:
                            payload["replacement_trade_id"] = trade["replacement_trade_id"]
                    trade.update(payload)
                    self.update_log.append((int(trade["id"]), dict(payload)))
                    updated += 1
            return _Resp([{"updated": updated}])

        if query._op == "upsert":
            payload = dict(query._payload)
            key = (
                payload.get("politician_id"),
                payload.get("ticker"),
                payload.get("transaction_date"),
                payload.get("amount"),
                payload.get("type"),
                payload.get("owner"),
            )
            for trade in self.trades:
                existing_key = (
                    trade.get("politician_id"),
                    trade.get("ticker"),
                    trade.get("transaction_date"),
                    trade.get("amount"),
                    trade.get("type"),
                    trade.get("owner"),
                )
                if existing_key == key:
                    # Preserve quality on garbage/corrected like the DB trigger
                    old_status = trade.get("quality_status", QUALITY_OK)
                    if old_status in (QUALITY_GARBAGE, QUALITY_CORRECTED):
                        for key_name in (
                            "quality_status",
                            "quality_reason",
                            "suggested_ticker",
                            "replacement_trade_id",
                        ):
                            if key_name in payload and trade.get(key_name) is not None:
                                if key_name != "replacement_trade_id" or trade.get(key_name) is not None:
                                    payload[key_name] = trade.get(key_name)
                        # Always preserve status/reason/suggested
                        payload["quality_status"] = trade["quality_status"]
                        payload["quality_reason"] = trade.get("quality_reason")
                        payload["suggested_ticker"] = trade.get("suggested_ticker")
                        if trade.get("replacement_trade_id") is not None:
                            payload["replacement_trade_id"] = trade["replacement_trade_id"]
                    trade.update(payload)
                    return _Resp([dict(trade)])
            payload["id"] = self._next_id
            self._next_id += 1
            if "quality_status" not in payload:
                payload["quality_status"] = QUALITY_OK
            self.trades.append(payload)
            return _Resp([dict(payload)])

        raise AssertionError(f"Unhandled op {query._op} on {query._table}")


class _FakeClient:
    def __init__(self, store: _FakeStore) -> None:
        self.supabase = store


class TestApplyOverrides:
    def test_fresh_db_path_marks_garbage_and_creates_sibling(self) -> None:
        store = _FakeStore()
        store.trades.append(
            {
                "id": 1,
                "politician_id": 99,
                "ticker": "USOU",
                "chamber": "House",
                "transaction_date": "2026-06-01",
                "disclosure_date": "2026-06-18",
                "type": "Purchase",
                "amount": "$1,001 - $15,000",
                "owner": "Not-Disclosed",
                "party": "Republican",
                "state": "TX",
                "asset_type": "Stock",
                "price": None,
                "notes": None,
                "quality_status": QUALITY_OK,
                "quality_reason": None,
                "suggested_ticker": None,
                "replacement_trade_id": None,
            }
        )
        store._next_id = 2
        client = _FakeClient(store)
        stats = apply_trade_quality_overrides(client)
        assert stats["matched"] == 1
        assert stats["marked_garbage"] == 1
        assert stats["siblings_ensured"] == 1
        assert stats["linked"] == 1

        garbage = next(t for t in store.trades if t["ticker"] == "USOU")
        assert garbage["quality_status"] == QUALITY_GARBAGE
        assert garbage["suggested_ticker"] == "USO"
        assert garbage["replacement_trade_id"] is not None

        sibling = next(t for t in store.trades if t["id"] == garbage["replacement_trade_id"])
        assert sibling["ticker"] == "USO"
        assert sibling["quality_status"] == QUALITY_CORRECTED
        assert is_analysis_eligible(sibling["quality_status"])
        assert not is_analysis_eligible(garbage["quality_status"])

    def test_second_apply_idempotent_no_duplicate_sibling(self) -> None:
        store = _FakeStore()
        store.trades.append(
            {
                "id": 1,
                "politician_id": 99,
                "ticker": "USOU",
                "chamber": "House",
                "transaction_date": "2026-06-01",
                "disclosure_date": "2026-06-18",
                "type": "Purchase",
                "amount": "$1,001 - $15,000",
                "owner": "Not-Disclosed",
                "party": "Republican",
                "state": "TX",
                "asset_type": "Stock",
                "price": None,
                "notes": None,
                "quality_status": QUALITY_OK,
                "quality_reason": None,
                "suggested_ticker": None,
                "replacement_trade_id": None,
            }
        )
        store._next_id = 2
        client = _FakeClient(store)
        apply_trade_quality_overrides(client)
        stats2 = apply_trade_quality_overrides(client)
        assert stats2["matched"] == 1
        assert stats2["marked_garbage"] == 0
        uso_rows = [t for t in store.trades if t["ticker"] == "USO"]
        assert len(uso_rows) == 1

    def test_trigger_preserves_quality_on_notes_update(self) -> None:
        store = _FakeStore()
        store.trades.append(
            {
                "id": 10,
                "politician_id": 99,
                "ticker": "USOU",
                "chamber": "House",
                "transaction_date": "2026-06-01",
                "disclosure_date": "2026-06-18",
                "type": "Purchase",
                "amount": "$1,001 - $15,000",
                "owner": "Not-Disclosed",
                "quality_status": QUALITY_GARBAGE,
                "quality_reason": "bad",
                "suggested_ticker": "USO",
                "replacement_trade_id": 99,
                "notes": "old",
            }
        )
        client = _FakeClient(store)
        (
            client.supabase.table("congress_trades")
            .update({"notes": "re-ingest note", "quality_status": QUALITY_OK})
            .eq("id", 10)
            .execute()
        )
        row = store.trades[0]
        assert row["notes"] == "re-ingest note"
        assert row["quality_status"] == QUALITY_GARBAGE
        assert row["suggested_ticker"] == "USO"
        assert row["replacement_trade_id"] == 99
