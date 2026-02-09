from web_dashboard.scheduler import jobs_common
from web_dashboard.scheduler.jobs_common import claim_recent_summary_input, has_strong_market_signal


def test_has_strong_market_signal_detects_explicit_market_terms() -> None:
    title = "Company shares jump after earnings beat"
    content = "The stock rose 12% after quarterly earnings and guidance updates."
    assert has_strong_market_signal(title=title, content=content)


def test_has_strong_market_signal_rejects_generic_non_market_story() -> None:
    title = "Top 10 new restaurants in Pittsburgh"
    content = "A food and nightlife roundup with menus, atmosphere, and service highlights."
    assert not has_strong_market_signal(title=title, content=content)


def test_has_strong_market_signal_accepts_required_term_match() -> None:
    title = "Tesla expands charging footprint in Europe"
    content = "The company announced additional sites and rollout timelines."
    assert has_strong_market_signal(
        title=title,
        content=content,
        tickers=[],
        required_terms=["TSLA", "Tesla"],
    )


def test_claim_recent_summary_input_blocks_immediate_duplicate() -> None:
    jobs_common._SUMMARY_INPUT_HASHES.clear()
    first_allowed, first_hash = claim_recent_summary_input("Title: X\n\nBody", ttl_seconds=3600)
    second_allowed, second_hash = claim_recent_summary_input("Title: X\n\nBody", ttl_seconds=3600)
    assert first_allowed is True
    assert second_allowed is False
    assert first_hash == second_hash


def test_claim_recent_summary_input_allows_after_ttl(monkeypatch) -> None:
    jobs_common._SUMMARY_INPUT_HASHES.clear()
    clock = {"now": 1_000.0}
    monkeypatch.setattr(jobs_common.time, "time", lambda: clock["now"])

    first_allowed, _ = claim_recent_summary_input("same text", ttl_seconds=2)
    clock["now"] += 3.0
    second_allowed, _ = claim_recent_summary_input("same text", ttl_seconds=2)

    assert first_allowed is True
    assert second_allowed is True
