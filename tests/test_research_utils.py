"""Tests for research content extraction utilities."""

from web_dashboard import research_utils
from web_dashboard.research_utils import contains_access_challenge


def test_contains_access_challenge_detects_denied_page() -> None:
    """Should detect common anti-bot deny pages."""
    sample = """
Access to this page has been denied
Before we continue...
Press & Hold to confirm you are a human (and not a bot).
Reference ID 2c58682d-0312-11f1-93e9-6ffce1179bf0
"""
    assert contains_access_challenge(sample) is True


def test_contains_access_challenge_detects_multi_signal_challenge() -> None:
    """Should detect weaker patterns when multiple indicators exist."""
    sample = """
Please enable JavaScript and cookies to continue.
Checking your browser before accessing the site.
"""
    assert contains_access_challenge(sample) is True


def test_contains_access_challenge_ignores_normal_article() -> None:
    """Should not flag regular market-news content."""
    sample = """
The article discusses a potential partnership and expected earnings impact.
Analysts highlighted valuation, macro backdrop, and regulatory risk.
"""
    assert contains_access_challenge(sample) is False


def test_extract_article_content_returns_timeout_when_budget_exhausted(monkeypatch) -> None:
    """A depleted extraction budget should fail fast before network fetches."""

    monkeypatch.setattr(research_utils, "trafilatura", object())

    result = research_utils.extract_article_content(
        "https://example.com/article",
        max_seconds=0.0,
    )

    assert result["success"] is False
    assert result["error"] == "extraction_timeout"
