from utils.job_tracking import AI_JOB_NAMES


def test_ai_lock_includes_research_collection_jobs() -> None:
    expected = {
        "market_research",
        "ticker_research",
        "opportunity_discovery",
        "alpha_research",
    }
    assert expected.issubset(AI_JOB_NAMES)
