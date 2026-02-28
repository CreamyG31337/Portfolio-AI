from unittest.mock import MagicMock

from scheduler.jobs_dividends import _is_drip_fund, get_fund_dividend_mode


def _mock_client_for_funds_row(row: dict) -> MagicMock:
    client = MagicMock()
    execute_result = MagicMock()
    execute_result.data = [row]
    client.supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = execute_result
    return client


def test_get_fund_dividend_mode_prefers_explicit_db_mode() -> None:
    client = _mock_client_for_funds_row({"dividend_mode": "cash", "fund_type": "tfsa"})
    assert get_fund_dividend_mode("TFSA", client, fund_type="tfsa") == "cash"


def test_get_fund_dividend_mode_falls_back_to_rrsp_rule() -> None:
    client = _mock_client_for_funds_row({"dividend_mode": None, "fund_type": "rrsp"})
    assert get_fund_dividend_mode("RRSP", client, fund_type="rrsp") == "cash"


def test_is_drip_fund_uses_dividend_mode() -> None:
    assert _is_drip_fund("reinvest") is True
    assert _is_drip_fund("cash") is False
