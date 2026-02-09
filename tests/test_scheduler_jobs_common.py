from web_dashboard.scheduler.jobs_common import has_strong_market_signal


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
