from web_dashboard.research_repository import ResearchRepository


def _clear_processing_urls() -> None:
    with ResearchRepository._processing_urls_lock:
        ResearchRepository._processing_urls.clear()


def test_claim_and_release_processing_url() -> None:
    _clear_processing_urls()
    repo = ResearchRepository.__new__(ResearchRepository)
    url = "https://example.com/article"

    assert repo.claim_processing_url(url) is True
    assert repo.claim_processing_url(url) is False

    repo.release_processing_url(url)
    assert repo.claim_processing_url(url) is True
    repo.release_processing_url(url)


def test_processing_guard_is_reentrant_safe() -> None:
    _clear_processing_urls()
    repo = ResearchRepository.__new__(ResearchRepository)
    url = "https://example.com/guarded"

    with repo.processing_guard(url) as first_claimed:
        assert first_claimed is True
        with repo.processing_guard(url) as second_claimed:
            assert second_claimed is False

    assert repo.claim_processing_url(url) is True
    repo.release_processing_url(url)
