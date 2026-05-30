from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from scheduler.jobs_dividends import (
    DividendEvent,
    _credit_cash_dividend,
    _is_drip_fund,
    get_fund_dividend_mode,
    insert_drip_transaction,
)


def _mock_client_for_funds_row(row: dict) -> MagicMock:
    client = MagicMock()
    execute_result = MagicMock()
    execute_result.data = [row]
    client.supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = execute_result
    return client


def _mock_client_for_cash_balances(existing_amount: float | None) -> tuple[MagicMock, MagicMock]:
    """Build client mock where cash_balances select returns optional existing row."""
    client = MagicMock()
    cash_table = MagicMock()
    select_execute = MagicMock()
    select_execute.data = [{"amount": existing_amount}] if existing_amount is not None else []
    cash_table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        select_execute
    )
    cash_table.upsert.return_value.execute.return_value = MagicMock()

    def table_side_effect(table_name: str) -> MagicMock:
        if table_name == "cash_balances":
            return cash_table
        return MagicMock()

    client.supabase.table.side_effect = table_side_effect
    return client, cash_table


def _sample_event() -> DividendEvent:
    return DividendEvent(
        ex_date=date(2026, 5, 1),
        pay_date=date(2026, 5, 15),
        amount=0.50,
        source="nasdaq",
    )


def test_get_fund_dividend_mode_prefers_explicit_db_mode() -> None:
    client = _mock_client_for_funds_row({"dividend_mode": "cash", "fund_type": "tfsa"})
    assert get_fund_dividend_mode("TFSA", client, fund_type="tfsa") == "cash"


def test_get_fund_dividend_mode_falls_back_to_rrsp_rule() -> None:
    client = _mock_client_for_funds_row({"dividend_mode": None, "fund_type": "rrsp"})
    assert get_fund_dividend_mode("RRSP", client, fund_type="rrsp") == "cash"


def test_is_drip_fund_uses_dividend_mode() -> None:
    assert _is_drip_fund("reinvest") is True
    assert _is_drip_fund("cash") is False


def test_cash_dividend_credits_cash_balances() -> None:
    client, cash_table = _mock_client_for_cash_balances(2339.58)
    _credit_cash_dividend(client, "RRSP Lance Webull", "USD", Decimal("10.72"))

    upsert_call = cash_table.upsert.call_args
    payload = upsert_call[0][0]
    assert payload["fund"] == "RRSP Lance Webull"
    assert payload["currency"] == "USD"
    assert payload["amount"] == 2350.30
    assert upsert_call[1]["on_conflict"] == "fund,currency"


def test_cash_dividend_handles_missing_cash_row() -> None:
    client, cash_table = _mock_client_for_cash_balances(None)
    _credit_cash_dividend(client, "RRSP Lance Webull", "cad", Decimal("48.50"))

    payload = cash_table.upsert.call_args[0][0]
    assert payload["currency"] == "CAD"
    assert payload["amount"] == 48.50


@patch("scheduler.jobs_dividends.get_price_on_date", return_value=Decimal("100.00"))
@patch("scheduler.jobs_dividends.calculate_eligible_shares", return_value=Decimal("10"))
@patch("scheduler.jobs_dividends._credit_cash_dividend")
def test_drip_dividend_does_not_touch_cash_balances(
    mock_credit: MagicMock,
    _mock_eligible: MagicMock,
    _mock_price: MagicMock,
) -> None:
    client = MagicMock()
    client.ensure_ticker_in_securities.return_value = True
    trade_insert = MagicMock()
    trade_insert.data = [{"id": "trade-uuid-1"}]
    div_insert = MagicMock()
    client.supabase.table.return_value.insert.return_value.execute.side_effect = [
        trade_insert,
        div_insert,
    ]

    ok = insert_drip_transaction(
        "Project Chimera",
        "JNJ",
        _sample_event(),
        "tfsa",
        "reinvest",
        client,
    )

    assert ok is True
    mock_credit.assert_not_called()


@patch(
    "scheduler.jobs_dividends._credit_cash_dividend",
    side_effect=RuntimeError("cash upsert failed"),
)
@patch("scheduler.jobs_dividends.get_price_on_date", return_value=Decimal("100.00"))
@patch("scheduler.jobs_dividends.calculate_eligible_shares", return_value=Decimal("10"))
def test_cash_credit_failure_does_not_abort_dividend_log(
    _mock_eligible: MagicMock,
    _mock_price: MagicMock,
    _mock_credit: MagicMock,
) -> None:
    client = MagicMock()
    client.ensure_ticker_in_securities.return_value = True
    div_insert = MagicMock()
    client.supabase.table.return_value.insert.return_value.execute.return_value = div_insert

    ok = insert_drip_transaction(
        "RRSP Lance Webull",
        "JNJ",
        _sample_event(),
        "rrsp",
        "cash",
        client,
    )

    assert ok is True
    client.supabase.table("dividend_log").insert.assert_called_once()
