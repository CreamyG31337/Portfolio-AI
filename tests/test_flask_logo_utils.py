from web_dashboard.utils.logo_utils import get_ticker_logo_url


def test_class_share_ticker_uses_unavatar_when_website_available() -> None:
    url = get_ticker_logo_url("TECK.B", use_alt=False, website="https://www.teck.com")
    assert url == "https://unavatar.io/teck.com?fallback=false"


def test_regular_ticker_still_uses_parqet() -> None:
    url = get_ticker_logo_url("AAPL", use_alt=False, website="https://www.apple.com")
    assert url is not None
    assert "assets.parqet.com/logos/symbol/AAPL" in url


def test_class_share_without_website_prefers_tsx_style_symbol() -> None:
    url = get_ticker_logo_url("TECK.B", use_alt=False, website=None)
    assert url is not None
    assert "assets.parqet.com/logos/symbol/TECK-B.TO" in url
