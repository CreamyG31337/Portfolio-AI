"""Tests for insider trades fetch job parsing and fetch fallback."""

from unittest.mock import MagicMock, patch

from web_dashboard.scheduler.jobs_insiders import (
    _extract_bracketed_array,
    _fetch_insider_trades_from_source,
    _parse_insider_trades_from_html,
)

SAMPLE_TRADE = {
    "rptOwnerName": "SMITH JOHN",
    "officerTitle": "CEO",
    "issuerTradingSymbol": "TEST",
    "transactionCode": "Purchase",
    "transactionShares": 100,
    "transactionPricePerShare": 10.5,
    "transactionDate": "Jun 20, 2026",
    "fileDate": "Jun 22, 2026 (8:00 PM)",
}

SAMPLE_HTML = f"""
<html><body>
<script>
let recentInsiderTransactionsData = [{SAMPLE_TRADE!r}];
let topMonthlyInsiderTransactionsData = [];
</script>
</body></html>
"""


def test_extract_bracketed_array_finds_balanced_literal():
    literal = _extract_bracketed_array(
        "let recentInsiderTransactionsData = [{'a': 1}, {'b': 2}];",
        "recentInsiderTransactionsData",
    )
    assert literal == "[{'a': 1}, {'b': 2}]"


def test_parse_insider_trades_from_html():
    trades = _parse_insider_trades_from_html(SAMPLE_HTML)
    assert len(trades) == 1
    assert trades[0]["issuerTradingSymbol"] == "TEST"


@patch("web_dashboard.scheduler.jobs_insiders.get_web_fetch_client")
@patch("web_dashboard.scheduler.jobs_insiders.fetch_page_via_flaresolverr")
def test_fetch_retries_direct_when_flaresolverr_html_unusable(
    mock_flare: MagicMock,
    mock_client_factory: MagicMock,
):
    mock_flare.return_value = "<html><body>cloudflare challenge</body></html>"
    mock_client = MagicMock()
    mock_client.fetch_direct_html.return_value = SAMPLE_HTML
    mock_client_factory.return_value = mock_client

    trades, method = _fetch_insider_trades_from_source("https://example.com/insiders/")

    assert method == "direct"
    assert len(trades) == 1
    mock_client.fetch_direct_html.assert_called_once()


@patch("web_dashboard.scheduler.jobs_insiders.get_web_fetch_client")
@patch("web_dashboard.scheduler.jobs_insiders.fetch_page_via_flaresolverr")
def test_fetch_uses_flaresolverr_when_parseable(
    mock_flare: MagicMock,
    mock_client_factory: MagicMock,
):
    mock_flare.return_value = SAMPLE_HTML

    trades, method = _fetch_insider_trades_from_source("https://example.com/insiders/")

    assert method == "flaresolverr"
    assert len(trades) == 1
    mock_client_factory.return_value.fetch_direct_html.assert_not_called()
