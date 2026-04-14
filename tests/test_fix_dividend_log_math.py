"""Unit tests for dividend_log eligibility datafix helpers (no Supabase)."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from scheduler.dividend_log_datafix import (
    legacy_sum_shares_before_ex,
    materially_different,
    parse_ex_date,
    per_share_from_events,
    quantize_reinvested_shares,
    recalc_amounts,
    resolve_per_share,
    row_amounts_need_update,
)
from scheduler.jobs_dividends import DividendEvent


def test_parse_ex_date_string() -> None:
    assert parse_ex_date("2024-06-15") == date(2024, 6, 15)


def test_parse_ex_date_datetime_iso() -> None:
    assert parse_ex_date("2024-06-15T00:00:00+00:00") == date(2024, 6, 15)


def test_per_share_from_events_match() -> None:
    d = date(2024, 3, 1)
    events = [
        DividendEvent(ex_date=d, pay_date=d, amount=0.52, source="yfinance"),
        DividendEvent(ex_date=date(2024, 6, 1), pay_date=date(2024, 6, 3), amount=0.55, source="yfinance"),
    ]
    assert per_share_from_events(events, d) == Decimal("0.52")


def test_per_share_from_events_missing() -> None:
    assert per_share_from_events([], date(2024, 1, 1)) is None


def test_resolve_per_share_prefers_api() -> None:
    d = date(2024, 1, 10)
    events = [DividendEvent(ex_date=d, pay_date=d, amount=0.25, source="nasdaq")]
    ps, src = resolve_per_share("X", d, Decimal("100"), Decimal("999"), events)
    assert ps == Decimal("0.25")
    assert src == "api"


def test_resolve_per_share_fallback() -> None:
    d = date(2024, 1, 10)
    ps, src = resolve_per_share("X", d, Decimal("140"), Decimal("200"), [])
    assert ps == Decimal("0.7")
    assert src == "fallback_gross_over_legacy"


def test_resolve_per_share_fallback_zero_legacy_raises() -> None:
    with pytest.raises(ValueError):
        resolve_per_share("X", date(2024, 1, 10), Decimal("10"), Decimal("0"), [])


def test_recalc_amounts_rrsp_us() -> None:
    g, t, n = recalc_amounts(Decimal("100"), Decimal("0.5"), "rrsp", "AAPL")
    assert g == Decimal("50")
    assert t == Decimal("0")
    assert n == Decimal("50")


def test_recalc_amounts_tfsa_us() -> None:
    g, t, n = recalc_amounts(Decimal("100"), Decimal("0.5"), "tfsa", "AAPL")
    assert g == Decimal("50")
    assert t == Decimal("7.5")
    assert n == Decimal("42.5")


def test_recalc_amounts_canadian() -> None:
    g, t, n = recalc_amounts(Decimal("10"), Decimal("1"), "tfsa", "RY.TO")
    assert g == Decimal("10")
    assert t == Decimal("0")
    assert n == Decimal("10")


def test_quantize_reinvested_shares() -> None:
    assert quantize_reinvested_shares(Decimal("100"), Decimal("25")) == Decimal("4")


def test_materially_different() -> None:
    assert materially_different(Decimal("1"), Decimal("1.000002")) is True
    assert materially_different(Decimal("1"), Decimal("1.0000001")) is False


def test_row_amounts_need_update_true() -> None:
    assert (
        row_amounts_need_update(
            Decimal("100"),
            Decimal("15"),
            Decimal("85"),
            Decimal("2"),
            Decimal("50"),
            Decimal("7.5"),
            Decimal("42.5"),
            Decimal("1.5"),
        )
        is True
    )


def test_row_amounts_need_update_false() -> None:
    assert (
        row_amounts_need_update(
            Decimal("50"),
            Decimal("7.5"),
            Decimal("42.5"),
            Decimal("1.5"),
            Decimal("50"),
            Decimal("7.5"),
            Decimal("42.5"),
            Decimal("1.5"),
        )
        is False
    )


def test_legacy_sum_shares_before_ex() -> None:
    client = MagicMock()
    execute_result = MagicMock()
    execute_result.data = [
        {"shares": 100},
        {"shares": 40},
    ]
    (
        client.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.lt.return_value.order.return_value.execute
    ).return_value = execute_result

    out = legacy_sum_shares_before_ex("F", "T", date(2024, 5, 1), client)
    assert out == Decimal("140")
