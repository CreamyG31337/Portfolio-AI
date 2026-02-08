from web_dashboard.summary_common import parse_summary_response


def test_parse_summary_response_sanitizes_and_dedupes_tickers() -> None:
    raw = """
    {
      "summary": "x",
      "claims": [],
      "fact_check": "",
      "conclusion": "",
      "sentiment": "NEUTRAL",
      "logic_check": "NEUTRAL",
      "tickers": ["$BTCS", "$BTCS", "$NTRB", "$-USD", "$-", "RKLB?", "AAPL"],
      "sectors": [],
      "key_themes": [],
      "companies": [],
      "market_relevance": "MARKET_RELATED",
      "market_relevance_reason": "",
      "relationships": []
    }
    """

    parsed = parse_summary_response(raw)
    assert parsed["tickers"] == ["BTCS", "NTRB", "RKLB", "AAPL"]


def test_parse_summary_response_rejects_placeholder_tickers() -> None:
    raw = """
    {
      "summary": "x",
      "claims": [],
      "fact_check": "",
      "conclusion": "",
      "sentiment": "NEUTRAL",
      "logic_check": "NEUTRAL",
      "tickers": ["$?", "-", "unknown", "N/A"],
      "sectors": [],
      "key_themes": [],
      "companies": [],
      "market_relevance": "MARKET_RELATED",
      "market_relevance_reason": "",
      "relationships": []
    }
    """

    parsed = parse_summary_response(raw)
    assert parsed["tickers"] == []
