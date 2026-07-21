"""Executive vs congress session conflict prompts (ROADMAP H6)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "web_dashboard"
    / "scripts"
    / "analyze_congress_trades_batch.py"
)


def _load_batch_module():
    """Load the batch script as a module without executing ``main``."""
    # Match script path layout so ``data.committee_jurisdictions`` resolves.
    web_dashboard = SCRIPT_PATH.parent.parent
    repo_root = web_dashboard.parent
    for path in (str(web_dashboard), str(repo_root)):
        if path not in sys.path:
            sys.path.insert(0, path)

    name = "_analyze_congress_trades_batch_h6"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_batch = _load_batch_module()


def test_is_executive_chamber() -> None:
    assert _batch.is_executive_chamber("Executive") is True
    assert _batch.is_executive_chamber("executive") is True
    assert _batch.is_executive_chamber(" House ") is False
    assert _batch.is_executive_chamber(None) is False


def test_build_session_conflict_prompt_executive_skips_committees() -> None:
    with patch.object(_batch, "get_committee_context") as mock_committees:
        prompt = _batch.build_session_conflict_prompt(
            politician="Donald Trump",
            party="R",
            state="USA",
            chamber="Executive",
            trade_count=2,
            trades_table="| NVDA | Purchase |",
            committees="Should not be used",
        )

    mock_committees.assert_not_called()
    assert "Committee Powers & Jurisdictions" not in prompt
    assert "Executive-branch" in prompt or "Executive" in prompt
    assert "policy control" in prompt.casefold() or "Policy control" in prompt
    assert "NVDA" in prompt
    assert "CONFLICT_BUY" in prompt


def test_build_session_conflict_prompt_house_uses_committee_rubric() -> None:
    with patch.object(
        _batch,
        "get_committee_context",
        return_value="Armed Services: defense contractors",
    ) as mock_committees:
        prompt = _batch.build_session_conflict_prompt(
            politician="Jane Legislator",
            party="D",
            state="CA",
            chamber="House",
            trade_count=1,
            trades_table="| LMT | Purchase |",
            committees="Armed Services",
        )

    mock_committees.assert_called_once_with("Armed Services")
    assert "Committee Powers & Jurisdictions" in prompt
    assert "Armed Services: defense contractors" in prompt
    assert "Congressional trading sessions" in prompt
    assert "LMT" in prompt


def test_analyze_trade_uses_executive_prompt(monkeypatch) -> None:
    """Queue workers call analyze_trade — must not use committee PROMPT_TEMPLATE."""
    captured: dict = {}

    def _fake_collect(ollama, prompt="", **_kwargs):
        captured["prompt"] = prompt
        return (
            '{"conflict_score": 0.2, "confidence_score": 0.7, "reasoning": "ok"}',
            "test-model",
        )

    monkeypatch.setattr(_batch, "collect_with_summary_model_chain", _fake_collect)
    context = {
        "politician": "Donald Trump",
        "party": "R",
        "state": "USA",
        "chamber": "Executive",
        "owner": "Self",
        "committees": "Unknown",
        "ticker": "NVDA",
        "company_name": "NVIDIA",
        "sector": "Technology",
        "description": None,
        "date": "2026-03-01",
        "type": "Purchase",
        "amount": "$15,001 - $50,000",
    }
    result = _batch.analyze_trade(object(), context, "test-model")
    assert result["conflict_score"] == 0.2
    assert "Committee Assignments" not in captured["prompt"]
    assert "executive" in captured["prompt"].casefold()
    assert "NVDA" in captured["prompt"]
