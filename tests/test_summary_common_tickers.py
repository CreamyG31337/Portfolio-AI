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


def test_parse_summary_response_recovers_malformed_json_arrays() -> None:
    raw = """
    {
      "summary": "- Anthropic funding round may exceed $20 billion.",
      "claims": ["Funding round expected to exceed $20 billion", "$350 billion valuation", Original target was $10 billion, Overwhelming investor demand pushed total beyond $20 billion"],
      "fact_check": "Claims appear plausible.",
      "conclusion": "Positive signal for AI capital markets.",
      "sentiment": "BULLISH",
      "logic_check": "NEUTRAL",
      "tickers": ["ANTH"],
      "sectors": ["Technology", "Artificial Intelligence"],
      "key_themes": ["Major AI investment"],
      "companies": ["OpenAI"],
      "market_relevance": "MARKET_RELATED",
      "market_relevance_reason": "Major funding event influences AI sector sentiment.",
      "relationships": []
    }
    """

    parsed = parse_summary_response(raw)
    assert parsed["tickers"] == ["ANTH"]
    assert parsed["sentiment"] == "BULLISH"
    assert parsed["market_relevance"] == "MARKET_RELATED"
    assert "Original target was $10 billion" in parsed["claims"]
