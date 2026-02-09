import os
import sys
from typing import List


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web_dashboard")))

import ollama_client
from newsletter_service import NewsletterService


def test_clean_subject_strips_forward_prefixes() -> None:
    assert NewsletterService.clean_subject("Fwd: Weekly Alpha") == "Weekly Alpha"
    assert NewsletterService.clean_subject(" fw:   Weekly Alpha ") == "Weekly Alpha"
    assert NewsletterService.clean_subject("Re: Fwd: Weekly Alpha") == "Weekly Alpha"


def test_clean_subject_handles_bracket_tag_and_delimiter_variants() -> None:
    assert NewsletterService.clean_subject("[External] Fwd: Weekly Alpha") == "[External] Weekly Alpha"
    assert NewsletterService.clean_subject("Fwd：Weekly Alpha") == "Weekly Alpha"
    assert NewsletterService.clean_subject("Fwd - Weekly Alpha") == "Weekly Alpha"


def test_clean_subject_does_not_alter_regular_subjects() -> None:
    subject = "Forward Looking Market Update"
    assert NewsletterService.clean_subject(subject) == subject


def test_extract_tickers_handles_dollar_and_suffix_symbols() -> None:
    service = NewsletterService()
    text = "We like $NVDA and SHOP.TO, but WE do not care about GDP."

    tickers = service.extract_tickers(text)

    assert "NVDA" in tickers
    assert "SHOP.TO" in tickers
    assert "WE" not in tickers
    assert "GDP" not in tickers


def test_extract_tickers_known_validation_keeps_explicit_unknowns() -> None:
    service = NewsletterService()
    text = "Noise words WE and ALSO are here, plus an explicit $NEWT symbol."

    tickers = service.extract_tickers(
        text,
        validate_known_tickers=True,
        known_tickers={"AAPL", "MSFT"},
    )

    assert "NEWT" in tickers
    assert "WE" not in tickers
    assert "ALSO" not in tickers


def test_generate_embedding_rejects_non_768_dimensions(monkeypatch) -> None:
    class _FakeOllama:
        @staticmethod
        def generate_embedding(_text: str, model: str = "nomic-embed-text") -> List[float]:
            assert model == "nomic-embed-text"
            return [0.1] * 10

    monkeypatch.setattr(ollama_client, "get_ollama_client", lambda: _FakeOllama())

    service = NewsletterService()
    assert service.generate_embedding("hello world") is None
