"""Industry-thesis pass for INDUSTRY YouTube sources (yt_industry_theses)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

# sys.path is set up by tests/conftest.py.
from yt_industry_theses import (  # noqa: E402
    filter_theses,
    is_industry_source,
    quote_in_transcript,
    run_and_save,
    run_industry_thesis,
)

TRANSCRIPT = (
    "Micron, Samsung and SK hynix control about 90% of global DRAM. "
    "The $285 drive is now well over $1,000. Console memory and storage costs "
    "are expected to double again by the fall of 2027, Microsoft said. "
    "Meanwhile the quarry in Denizli produces travertine."
)


def _thesis(quote: str, *candidates: dict[str, Any]) -> dict[str, Any]:
    return {
        "dynamic": "NAND shortage",
        "quote": quote,
        "direction": "tailwind",
        "beneficiary_profile": "NAND pure-plays",
        "loser_profile": "PC OEMs",
        "candidates": list(candidates),
    }


def _cand(name: str, ticker: str | None, confidence: float, origin: str = "model_knowledge") -> dict[str, Any]:
    return {
        "name": name,
        "ticker": ticker,
        "approx_cap": "mid",
        "side": "long",
        "origin": origin,
        "confidence": confidence,
        "why": "fits",
    }


def _accept_all(ticker: str, _name: str) -> str | None:
    return ticker.upper()


# --- quote verification -----------------------------------------------------


def test_exact_quote_is_found() -> None:
    assert quote_in_transcript("The $285 drive is now well over $1,000.", TRANSCRIPT)


def test_quote_survives_repunctuation_and_a_dropped_word() -> None:
    # GLM re-punctuates and the caption track lost "and storage".
    assert quote_in_transcript(
        "console memory costs are expected to double again by the fall of 2027",
        TRANSCRIPT,
    )


def test_invented_quote_is_rejected() -> None:
    assert not quote_in_transcript(
        "HBM packaging capacity is sold out through 2028 at every OSAT", TRANSCRIPT
    )


def test_too_short_quote_is_rejected() -> None:
    assert not quote_in_transcript("DRAM", TRANSCRIPT)


# --- filtering --------------------------------------------------------------


def test_thesis_without_a_real_quote_is_dropped() -> None:
    data = {"theses": [_thesis("Invented line that never appears anywhere here", _cand("SanDisk", "SNDK", 0.9))]}
    ideas, raw, kept, cands = filter_theses(data, TRANSCRIPT, verify_ticker=_accept_all)
    assert (ideas, raw, kept, cands) == ([], 1, 0, 1)


def test_low_confidence_and_tickerless_candidates_are_dropped() -> None:
    data = {
        "theses": [
            _thesis(
                "The $285 drive is now well over $1,000.",
                _cand("SanDisk", "SNDK", 0.85, origin="transcript"),
                _cand("Corsair", "CRSR", 0.45),
                _cand("Some Private Co", None, 0.9),
                _cand("Kioxia", "null", 0.7),
            )
        ]
    }
    ideas, _, kept, cands = filter_theses(data, TRANSCRIPT, verify_ticker=_accept_all)
    assert kept == 1
    assert cands == 4
    assert [i.ticker for i in ideas] == ["SNDK"]
    assert ideas[0].origin == "transcript"
    assert ideas[0].quote_verified and ideas[0].ticker_verified


def test_unverified_ticker_is_dropped() -> None:
    data = {"theses": [_thesis("The $285 drive is now well over $1,000.", _cand("SanDisk", "SNDKX", 0.9))]}
    ideas, *_ = filter_theses(data, TRANSCRIPT, verify_ticker=lambda t, n: None)
    assert ideas == []


def test_garbage_shapes_do_not_raise() -> None:
    assert filter_theses({}, TRANSCRIPT)[0] == []
    assert filter_theses({"theses": "nope"}, TRANSCRIPT)[0] == []
    assert filter_theses({"theses": [None, {"quote": None}]}, TRANSCRIPT, verify_ticker=_accept_all)[0] == []


# --- GLM call wrapper -------------------------------------------------------


def test_run_industry_thesis_parses_fenced_json() -> None:
    payload = {"theses": [_thesis("The $285 drive is now well over $1,000.", _cand("SanDisk", "SNDK", 0.9))]}
    raw = "```json\n" + json.dumps(payload) + "\n```"
    result = run_industry_thesis(
        title="t", content=TRANSCRIPT, model="glm-x",
        call_fn=lambda title, content, model: raw,
        verify_ticker=_accept_all,
    )
    assert result.error is None
    assert [i.ticker for i in result.ideas] == ["SNDK"]


def test_run_industry_thesis_reports_failures_instead_of_raising() -> None:
    def boom(*_a: Any, **_k: Any) -> str:
        raise TimeoutError("slow")

    assert run_industry_thesis(title="t", content="c", model="m", call_fn=boom).error.startswith("call_failed")
    assert run_industry_thesis(title="t", content="c", model="m", call_fn=lambda *a, **k: "not json").error == "unparseable"


# --- gating + persistence ---------------------------------------------------


def test_is_industry_source() -> None:
    assert is_industry_source({"alpha_mechanism": "INDUSTRY"})
    assert is_industry_source({"alpha_mechanism": "industry"})
    assert not is_industry_source({"alpha_mechanism": "ANALYSIS"})
    assert not is_industry_source(None)


def test_run_and_save_skips_non_industry_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    import yt_industry_theses

    called = MagicMock()
    monkeypatch.setattr(yt_industry_theses, "run_industry_thesis", called)
    pg = MagicMock()
    assert run_and_save(
        postgres_client=pg, article_id="a", title="t", content="c",
        source_metadata={"alpha_mechanism": "TEARDOWN"},
    ) is None
    called.assert_not_called()
    pg.execute_update.assert_not_called()


def test_run_and_save_replaces_the_articles_ideas(monkeypatch: pytest.MonkeyPatch) -> None:
    import yt_industry_theses

    monkeypatch.setattr(yt_industry_theses, "_verify_ticker", _accept_all)
    payload = {"theses": [_thesis("The $285 drive is now well over $1,000.", _cand("SanDisk", "SNDK", 0.9))]}
    monkeypatch.setattr(yt_industry_theses, "call_glm", lambda title, content, model: json.dumps(payload))

    pg = MagicMock()
    pg.execute_many.return_value = 1
    result = run_and_save(
        postgres_client=pg, article_id="art-9", title="t", content=TRANSCRIPT,
        source_metadata={"alpha_mechanism": "INDUSTRY", "video_id": "vid12345678"},
        source="youtube:UCabc",
    )
    assert result is not None and len(result.ideas) == 1
    delete_sql, delete_params = pg.execute_update.call_args.args
    assert "DELETE FROM yt_industry_ideas" in delete_sql and delete_params == ("art-9",)
    insert_sql, rows = pg.execute_many.call_args.args
    assert "INSERT INTO yt_industry_ideas" in insert_sql
    assert rows[0][0] == "art-9" and rows[0][1] == "vid12345678" and rows[0][2] == "youtube:UCabc"
    assert rows[0][11] == "SNDK"


def test_run_and_save_swallows_db_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import yt_industry_theses

    monkeypatch.setattr(
        yt_industry_theses, "run_industry_thesis",
        lambda **_k: SimpleNamespace(error=None, ideas=[], model="m"),
    )
    pg = MagicMock()
    pg.execute_update.side_effect = RuntimeError("relation does not exist")
    # Must not raise: the transcript's normal enrichment already landed.
    assert run_and_save(
        postgres_client=pg, article_id="a", title="t", content="c",
        source_metadata={"alpha_mechanism": "INDUSTRY"},
    ) is None


# --- pipeline hook ----------------------------------------------------------


def test_enrich_saved_transcript_runs_thesis_only_for_industry(monkeypatch: pytest.MonkeyPatch) -> None:
    import ticker_validator
    import yt_industry_theses
    from yt_articles import enrich_saved_transcript

    monkeypatch.setattr(
        ticker_validator, "extract_and_validate_tickers",
        lambda summary_data, title, content: list(summary_data.get("tickers") or []),
    )
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(yt_industry_theses, "run_and_save", lambda **kw: calls.append(kw))

    def summarize(text: str, article_type: str = "") -> dict[str, Any]:
        return {"summary": "s", "conclusion": "c", "tickers": [], "sentiment": "NEUTRAL"}

    repo = MagicMock()
    repo.client = MagicMock()
    for mech in ("ANALYSIS", "INDUSTRY"):
        enrich_saved_transcript(
            research_repo=repo, article_id=f"art-{mech}", title="t", content="body",
            summarize_fn=summarize,
            source_metadata={"alpha_mechanism": mech},
            source="youtube:UCabc",
        )
    assert [c["article_id"] for c in calls] == ["art-INDUSTRY"]
    assert calls[0]["postgres_client"] is repo.client
    assert calls[0]["source"] == "youtube:UCabc"
