"""Tests for ETF watchtower holdings parsing and metadata upsert."""

from unittest.mock import MagicMock, patch
import pandas as pd

from web_dashboard.scheduler.jobs_etf_watchtower import (
    fetch_ishares_holdings,
    upsert_securities_metadata,
)

SAMPLE_ISHARES_NEW_FORMAT = """iShares Russell 2000 ETF
Fund Holdings as of,"Nov 11, 2026"
Inception Date,"May 22, 2000"
Shares Outstanding,"275,850,000.00"
Stock,"-"
Bond,"-"
Cash,"-"
Other,"-"

Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price,Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date
"GKOS","GLAUKOS","Health Care","Equity","369,089,959.84","0.47","369,089,959.84","1,493,324.00","247.16","United States","NYSE","USD","1.00","USD","-"
"BTSG","BRIGHTSPRING HEALTH SERVICES INC","Health Care","Equity","316,212,316.04","0.41","316,212,316.04","4,354,342.00","72.62","United States","NASDAQ","USD","1.00","USD","-"
"FROG","JFROG","Information Technology","Equity","309,806,746.77","0.40","309,806,746.77","2,829,027.00","109.51","United States","NASDAQ","USD","1.00","USD","-"

"The content contained herein is owned or licensed by BlackRock and/or its third-party information providers and is protected by applicable copyrights, trademarks, service marks, and/or other intellectual property rights. Such content is solely for your personal, non-commercial use. Accordingly, you may not copy, distribute, modify, post, frame or deep link this content.
Holdings subject to change. See www.iShares.com for the most recent funds holdings.
CAREFULLY CONSIDER THE FUNDS' INVESTMENT OBJECTIVES, RISK FACTORS, AND CHARGES AND EXPENSES BEFORE INVESTING.
©2023 BlackRock, Inc or its affiliates. All rights reserved."
"""

SAMPLE_ISHARES_OLD_FORMAT = """Fund Holdings as of,2024-05-01
Total Net Assets,1000000000

Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Quantity
"AAPL","APPLE INC","Information Technology","Equity","100000.00","5.50","1,000.00"
"MSFT","MICROSOFT CORP","Information Technology","Equity","80000.00","4.20","800.00"
"""

SAMPLE_HTML_ERROR_RESPONSE = """<!DOCTYPE html>
<html lang="en-US">
<head>
<title>iShares Russell 2000 ETF | IWM</title>
<link rel="stylesheet" href="/assets/style.css" />
</head>
<body>
<h1>Product Page</h1>
</body>
</html>
"""


@patch("web_dashboard.scheduler.jobs_etf_watchtower.save_raw_etf_file")
@patch("requests.get")
def test_fetch_ishares_holdings_new_format(mock_get: MagicMock, mock_save_raw: MagicMock) -> None:
    """Parser finds 'Ticker,' header and excludes blank lines and trailing disclaimer."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = SAMPLE_ISHARES_NEW_FORMAT
    mock_response.content = SAMPLE_ISHARES_NEW_FORMAT.encode("utf-8")
    mock_get.return_value = mock_response

    df = fetch_ishares_holdings("IWM", "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/latest-holdings.csv")

    assert df is not None
    assert len(df) == 3
    assert list(df["ticker"]) == ["GKOS", "BTSG", "FROG"]
    assert df["shares"].tolist() == [1493324.0, 4354342.0, 2829027.0]
    assert df["weight_percent"].tolist() == [0.47, 0.41, 0.40]
    assert df["sector"].tolist() == ["Health Care", "Health Care", "Information Technology"]
    assert df["name"].tolist() == ["GLAUKOS", "BRIGHTSPRING HEALTH SERVICES INC", "JFROG"]


@patch("web_dashboard.scheduler.jobs_etf_watchtower.save_raw_etf_file")
@patch("requests.get")
def test_fetch_ishares_holdings_old_format(mock_get: MagicMock, mock_save_raw: MagicMock) -> None:
    """Parser remains backwards-compatible with older iShares CSV structures."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = SAMPLE_ISHARES_OLD_FORMAT
    mock_response.content = SAMPLE_ISHARES_OLD_FORMAT.encode("utf-8")
    mock_get.return_value = mock_response

    df = fetch_ishares_holdings("IWM", "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund")

    assert df is not None
    assert len(df) == 2
    assert list(df["ticker"]) == ["AAPL", "MSFT"]
    assert df["shares"].tolist() == [1000.0, 800.0]
    assert df["weight_percent"].tolist() == [5.50, 4.20]


@patch("web_dashboard.scheduler.jobs_etf_watchtower.save_raw_etf_file")
@patch("requests.get")
def test_fetch_ishares_holdings_html_response_returns_none(mock_get: MagicMock, mock_save_raw: MagicMock) -> None:
    """HTML responses (e.g. product page fallback or bot block) must return None without raising."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = SAMPLE_HTML_ERROR_RESPONSE
    mock_response.content = SAMPLE_HTML_ERROR_RESPONSE.encode("utf-8")
    mock_get.return_value = mock_response

    df = fetch_ishares_holdings("IWM", "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund")

    assert df is None


def test_upsert_securities_metadata() -> None:
    """upsert_securities_metadata runs on a DataFrame without 'Pandas object has no attribute get'."""
    mock_db = MagicMock()
    df = pd.DataFrame([
        {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "sector": "Information Technology",
            "industry": "Consumer Electronics",
            "currency": "USD",
        },
        {
            "ticker": "MSFT",
            "name": "Microsoft Corp.",
            "sector": "Information Technology",
            "industry": "Software",
            "currency": "USD",
        },
        {
            "ticker": "INVALID_LONG_TICKER_NAME_SHOULD_BE_SKIPPED",
            "name": "Skip Me",
            "sector": "Unknown",
            "industry": None,
            "currency": "USD",
        },
    ])

    upsert_securities_metadata(mock_db, df, provider="iShares")

    mock_db.supabase.table.assert_called_with("securities")
    upsert_mock = mock_db.supabase.table().upsert
    upsert_mock.assert_called_once()
    records = upsert_mock.call_args[0][0]
    assert len(records) == 2
    assert records[0]["ticker"] == "AAPL"
    assert records[0]["company_name"] == "Apple Inc."
    assert records[0]["sector"] == "Information Technology"
    assert records[0]["industry"] == "Consumer Electronics"
    assert records[0]["currency"] == "USD"
    assert "last_updated" in records[0]

    assert records[1]["ticker"] == "MSFT"
    assert records[1]["company_name"] == "Microsoft Corp."
