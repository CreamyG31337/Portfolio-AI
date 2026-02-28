import pytest

from routes.fund_routes import normalize_dividend_mode


def test_normalize_dividend_mode_accepts_valid_values() -> None:
    assert normalize_dividend_mode("reinvest") == "reinvest"
    assert normalize_dividend_mode(" CASH ") == "cash"
    assert normalize_dividend_mode(None) == "reinvest"


def test_normalize_dividend_mode_rejects_invalid_value() -> None:
    with pytest.raises(ValueError):
        normalize_dividend_mode("invalid-mode")
