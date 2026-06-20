"""Tests for yahoo SEDI insider parsing (ROADMAP G7)."""

from datetime import date
from decimal import Decimal

import pandas as pd

from web_dashboard.yahoo_sedi_insider_service import (
    SOURCE_YAHOO_SEDI,
    classify_yahoo_text,
    is_canadian_ticker,
    normalize_insider_name,
    parse_price_from_text,
    parse_yahoo_insider_dataframe,
    row_to_insider_trade,
)


def test_is_canadian_ticker():
    assert is_canadian_ticker("GLO.TO") is True
    assert is_canadian_ticker("abc.v") is True
    assert is_canadian_ticker("AAPL") is False


def test_classify_acquisition_and_sale():
    assert classify_yahoo_text("Acquisition in the public market - 1000 shares") == "Purchase"
    assert classify_yahoo_text("Sale at price C$1.23 - 500 shares") == "Sale"
    assert classify_yahoo_text("Exercise of options - 1000 shares") is None
    assert classify_yahoo_text("Stock Gift - 100 shares") is None
    assert classify_yahoo_text("Redemption, retraction - 50 shares") is None


def test_parse_price_from_text():
    assert parse_price_from_text("Sale at price C$1.23 - 500 shares") == Decimal("1.23")
    # Bare "at C$X" form (no "price" token) — the common acquisition layout.
    assert parse_price_from_text("Acquisition - 10000 shares at C$0.45") == Decimal("0.45")
    assert parse_price_from_text("Acquisition - 100 shares at $2.50") == Decimal("2.50")
    assert parse_price_from_text("Acquisition in the public market") is None


def test_normalize_insider_name():
    assert normalize_insider_name("Smith (John)") == "Smith (John)"
    assert normalize_insider_name("  Doe   (Jane)  ") == "Doe (Jane)"


def test_row_to_insider_trade_glo_style():
    row = {
        "Insider": "Leung (Guy)",
        "Start Date": "2026-05-15",
        "Shares": 10000,
        "Value": float("nan"),
        "Text": "Acquisition in the public market - 10000 shares at C$0.45",
        "Transaction": "",
    }
    record = row_to_insider_trade(row, "GLO.TO")
    assert record is not None
    assert record["ticker"] == "GLO.TO"
    assert record["type"] == "Purchase"
    assert record["insider_name"] == "Leung (Guy)"
    assert record["shares"] == 10000
    assert record["source"] == SOURCE_YAHOO_SEDI
    # Price is in the bare "at C$0.45" form (no literal "price" token); it must
    # still be parsed, else the row stores NULL price and breaks upsert dedup.
    assert record["price_per_share"] == 0.45
    assert record["value"] == 4500.0


def test_row_to_insider_trade_sale_with_price():
    row = {
        "Insider": "Jones (Mary)",
        "Start Date": "2026-04-01",
        "Shares": 500,
        "Value": float("nan"),
        "Text": "Sale at price C$2.50 - 500 shares",
    }
    record = row_to_insider_trade(row, "GMIN.TO")
    assert record is not None
    assert record["type"] == "Sale"
    assert record["price_per_share"] == 2.5


def test_row_to_insider_trade_skips_excluded():
    row = {
        "Insider": "Smith (Bob)",
        "Start Date": "2026-04-01",
        "Shares": 1000,
        "Text": "Exercise of options - 1000 shares",
    }
    assert row_to_insider_trade(row, "GLO.TO") is None


def test_row_to_insider_trade_lookback_filter():
    row = {
        "Insider": "Old (Trade)",
        "Start Date": "2020-01-01",
        "Shares": 100,
        "Text": "Acquisition in the public market - 100 shares",
    }
    assert row_to_insider_trade(
        row,
        "GLO.TO",
        lookback_days=365,
        as_of=date(2026, 6, 1),
    ) is None


def test_parse_yahoo_insider_dataframe():
    df = pd.DataFrame([
        {
            "Insider": "A (One)",
            "Start Date": "2026-06-01",
            "Shares": 100,
            "Value": 500.0,
            "Text": "Acquisition in the public market",
        },
        {
            "Insider": "B (Two)",
            "Start Date": "2026-06-02",
            "Shares": 50,
            "Text": "Exercise of options",
        },
    ])
    rows = parse_yahoo_insider_dataframe(df, "CNR.TO")
    assert len(rows) == 1
    assert rows[0]["ticker"] == "CNR.TO"
