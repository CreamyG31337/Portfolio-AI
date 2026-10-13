"""Market detection for holiday handling in the portfolio price job."""
import pytest

from web_dashboard.scheduler.jobs_portfolio import _is_canadian_listing


@pytest.mark.parametrize(
    "ticker, currency, expected",
    [
        ("SHOP.TO", "CAD", True),
        ("WEB.V", "CAD", True),
        ("ABC.CN", "CAD", True),
        ("DLR.U.TO", "USD", True),   # USD-quoted TSX unit: suffix wins
        ("TECK.B", "CAD", True),     # suffix-less CAD holding (Oct 12 2026 Thanksgiving miss)
        ("teck.b", " cad ", True),
        ("AAPL", "USD", False),
        ("BRK.B", "USD", False),     # US share-class dot is not a Canadian suffix
        ("AAPL", None, False),
    ],
)
def test_is_canadian_listing(ticker, currency, expected):
    assert _is_canadian_listing(ticker, currency) is expected
