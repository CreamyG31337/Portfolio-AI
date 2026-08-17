"""Flask: Phase 3 sector_insights (sector_meta primary + ETF Analysis fallback)."""

from datetime import date, datetime, timedelta, timezone, UTC
from unittest.mock import MagicMock, patch

import pytest


def _sector_row(**overrides):
    """Build a sector_meta_analysis row with sensible defaults; override per test."""
    base = {
        "id": "row-id",
        "sector": "Technology",
        "run_date": date(2026, 5, 10),
        "sector_stance": "BULLISH",
        "momentum_state": "STABLE",
        "news_pressure": "POSITIVE",
        "rotation_rank": 1,
        "confidence": 0.5,
        "key_drivers": ["a"],
        "risk_flags": ["r"],
        "as_of": datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 10, 8, 5, tzinfo=UTC),
        "model_used": "qwen3.8:27b-mtp-q4_K_M",
    }
    base.update(overrides)
    return base


def test_sector_freshness_buckets():
    """``_sector_freshness`` returns expected bucket label and css class."""
    from routes.etf_routes import _sector_freshness

    now = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)

    fresh = _sector_freshness(now - timedelta(hours=2), now=now)
    assert fresh["label"].startswith("Fresh")
    assert "emerald" in fresh["class"]

    recent = _sector_freshness(now - timedelta(hours=36), now=now)
    assert recent["label"].startswith("Recent")
    assert "blue" in recent["class"]

    aging = _sector_freshness(now - timedelta(days=4), now=now)
    assert aging["label"].startswith("Aging")
    assert "amber" in aging["class"]

    stale = _sector_freshness(now - timedelta(days=10), now=now)
    assert stale["label"].startswith("Stale")
    assert "red" in stale["class"]

    none_val = _sector_freshness(None, now=now)
    assert none_val["label"] == "Unknown freshness"


def test_sector_meta_insights_rows_attach_chip_classes_and_freshness():
    from routes.etf_routes import _sector_meta_insights_rows

    rows = _sector_meta_insights_rows([_sector_row()])
    assert len(rows) == 1
    row = rows[0]

    assert "green" in row["sector_stance_class"]  # BULLISH -> green chip
    assert "blue" in row["momentum_state_class"]  # STABLE -> blue chip
    assert "green" in row["news_pressure_class"]  # POSITIVE -> green chip
    assert row["confidence_pct"] == "50%"
    assert row["freshness_label"]  # populated
    assert row["sector_display"] == "Technology"


def test_sector_meta_insights_rows_sorted_by_rotation_then_confidence():
    """Rotation rank descending wins over recency; __UNTAGGED__ sinks to bottom."""
    from routes.etf_routes import _sector_meta_insights_rows

    rows = _sector_meta_insights_rows([
        _sector_row(sector="Energy", rotation_rank=1, confidence=0.9, sector_stance="BULLISH"),
        _sector_row(sector="__UNTAGGED__", rotation_rank=99, confidence=0.99),
        _sector_row(sector="Health Care", rotation_rank=5, confidence=0.4, sector_stance="MIXED"),
        _sector_row(sector="Financials", rotation_rank=5, confidence=0.8, sector_stance="NEUTRAL"),
        _sector_row(sector="Materials", rotation_rank=None, confidence=0.95),
    ])
    sectors = [r["sector"] for r in rows]
    # Highest rotation_rank first; ties broken by confidence; missing rank falls
    # below numeric ranks; __UNTAGGED__ always last.
    assert sectors == [
        "Financials",   # rank=5, conf=0.80
        "Health Care",  # rank=5, conf=0.40
        "Energy",       # rank=1, conf=0.90
        "Materials",    # rank=None, conf=0.95
        "__UNTAGGED__", # forced last
    ]


def test_sector_meta_insights_rows_handles_unknown_enums():
    """Unknown enum values fall back to a neutral chip class instead of crashing."""
    from routes.etf_routes import _sector_meta_insights_rows

    rows = _sector_meta_insights_rows([
        _sector_row(sector_stance="GIBBERISH", momentum_state=None, news_pressure="UNKNOWN", confidence=None, rotation_rank="bad"),
    ])
    row = rows[0]
    assert row["sector_stance_class"]
    assert row["momentum_state_class"]
    assert "gray" in row["news_pressure_class"]
    assert row["confidence_pct"] is None
    assert row["rotation_rank_num"] is None


def test_shared_navigation_includes_sector_insights():
    """Sector insights must be listed for Flask/Streamlit shared nav (sidebar source of truth)."""
    from shared_navigation import get_navigation_links

    pages = [link["page"] for link in get_navigation_links()]
    assert "sector_insights" in pages


def test_ensure_flask_sidebar_navigation_links_restores_sector_if_stripped():
    from shared_navigation import ensure_flask_sidebar_navigation_links, get_navigation_links

    stripped = [dict(x) for x in get_navigation_links() if x["page"] != "sector_insights"]
    assert "sector_insights" not in {x["page"] for x in stripped}
    fixed = ensure_flask_sidebar_navigation_links(stripped)
    pages = [x["page"] for x in fixed]
    assert "sector_insights" in pages
    etf_i = pages.index("etf_holdings")
    assert pages.index("sector_insights") == etf_i + 1


def _has_plotly() -> bool:
    try:
        import plotly.graph_objs  # noqa: F401
    except ImportError:
        return False
    return True


skip_without_plotly = pytest.mark.skipif(
    not _has_plotly(),
    reason="plotly required to import web_dashboard.app (see conftest)",
)


@skip_without_plotly
def test_sector_insights_nav_link_visible_when_v2_enabled_false(app):
    """Flask-only Sector insights must stay in the sidebar even when v2_enabled is false."""
    with app.test_request_context("/"):
        with patch("user_preferences._is_authenticated", return_value=True), patch(
            "user_preferences.get_user_preference",
            side_effect=lambda key, default=None: False if key == "v2_enabled" else default,
        ), patch("user_preferences.get_user_selected_fund", return_value=None), patch(
            "user_preferences.get_user_theme", return_value="system"
        ), patch("flask_data_utils.get_available_funds_flask", return_value=[]):
            from app import get_navigation_context

            ctx = get_navigation_context(current_page=None)
    sector = next((l for l in ctx["navigation_links"] if l.get("page") == "sector_insights"), None)
    assert sector is not None
    assert sector["show"] is True
    assert sector["url"] == "/sector_insights"


@pytest.fixture
def auth_ok():
    uid = "550e8400-e29b-41d4-a716-446655440000"
    with patch(
        "auth.auth_manager.verify_session",
        return_value={"user_id": uid, "email": "user@example.com"},
    ), patch(
        "flask_auth_utils.refresh_token_if_needed_flask",
        return_value=(True, None, None, None),
    ), patch("flask_auth_utils.get_user_id_flask", return_value=uid), patch(
        "flask_auth_utils.get_user_email_flask", return_value="user@example.com"
    ):
        yield


@skip_without_plotly
def test_sector_insights_lists_etf_analysis_rows(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    mock_article = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "title": "ARKK Holdings Analysis - 2026-05-01",
        "summary": "Test summary for rotation context.",
        "tickers": ["TSLA", "COIN"],
        "sentiment": "NEUTRAL",
        "source": "ETF AI Analysis",
        "published_at": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        "fetched_at": datetime(2026, 5, 1, 18, 0, tzinfo=UTC),
    }
    with patch(
        "routes.etf_routes.ResearchRepository",
        return_value=MagicMock(
            list_recent_sector_meta_analysis=MagicMock(return_value=[]),
            get_recent_articles=MagicMock(return_value=[mock_article]),
        ),
    ):
        resp = client.get("/sector_insights")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Phase 3d (2026-05): the legacy "experimental" / "honest labeling" banner
    # was removed once sector_meta_analysis became the primary surface. We now
    # just confirm the ETF Analysis fallback content actually renders.
    assert "ARKK Holdings Analysis" in body
    assert "Test summary for rotation context." in body


@skip_without_plotly
def test_sector_insights_empty_state(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    with patch(
        "routes.etf_routes.ResearchRepository",
        return_value=MagicMock(
            list_recent_sector_meta_analysis=MagicMock(return_value=[]),
            get_recent_articles=MagicMock(return_value=[]),
        ),
    ):
        resp = client.get("/sector_insights")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "No sector meta rows or ETF Analysis articles" in body


@skip_without_plotly
def test_sector_insights_primary_sector_meta_rows(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    mock_repo = MagicMock()
    mock_repo.list_recent_sector_meta_analysis.return_value = [
        {
            "id": "660e8400-e29b-41d4-a716-446655440001",
            "sector": "Technology",
            "run_date": date(2026, 5, 10),
            "sector_stance": "BULLISH",
            "momentum_state": "STABLE",
            "news_pressure": "POSITIVE",
            "rotation_rank": 2,
            "confidence": 0.72,
            "key_drivers": ["ETF flows skew constructive"],
            "risk_flags": ["sample risk"],
            "as_of": datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
            "model_used": "qwen3.8:27b-mtp-q4_K_M",
            "updated_at": datetime(2026, 5, 10, 8, 5, tzinfo=UTC),
            "full_result": {},
        }
    ]
    with patch("routes.etf_routes.ResearchRepository", return_value=mock_repo):
        resp = client.get("/sector_insights")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Technology" in body
    assert "BULLISH" in body
    assert "sector meta row" in body.lower()
    mock_repo.get_recent_articles.assert_not_called()


@skip_without_plotly
def test_sector_insights_requires_auth(client):
    resp = client.get("/sector_insights")
    assert resp.status_code == 302
    assert "/auth" in resp.headers.get("Location", "")
