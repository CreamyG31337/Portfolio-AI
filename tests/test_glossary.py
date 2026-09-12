"""The jargon glossary: one definition per term, reachable from both renderers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from glossary import GLOSSARY, get_glossary, get_term


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


def test_every_term_is_explained_in_plain_english() -> None:
    """A definition that needs its own glossary entry is not a definition."""
    for key, entry in GLOSSARY.items():
        assert entry.get("label"), key
        assert entry.get("short"), key
        assert entry.get("source"), f"{key} must say where the data comes from"
        short = entry["short"]
        assert short[0].isupper(), f"{key}: read as a sentence"
        assert short.rstrip().endswith("."), f"{key}: read as a sentence"
        assert len(short) <= 160, f"{key}: too long for a tooltip ({len(short)})"
        # The terms most likely to confuse a newcomer must not appear inside
        # another term's explanation.
        for jargon in ("thesis", "tier", "LLM"):
            assert jargon not in short or key.lower().startswith(jargon.lower()), (
                f"{key} explains itself with '{jargon}'"
            )


def test_terms_the_ui_actually_renders_are_present() -> None:
    """Guards against a badge being rendered with no way to find out what it means."""
    for key in (
        "TENSION",
        "HOLDS",
        "STALE_THESIS",
        "priority_tier",
        "source_TRADELOG",
        "source_ideas_inbox",
        "notable",
        "status_ingested",
        "status_evaluated",
        "skip_auto",
        "skip_manual",
        "overall_signal",
        "fear_level",
    ):
        assert key in GLOSSARY, key


def test_lookup_helpers() -> None:
    assert get_glossary() is GLOSSARY
    assert get_term("TENSION")["label"] == "Tension"
    assert get_term("no-such-term") is None


@skip_without_plotly
def test_glossary_json_is_embedded_in_pages(client) -> None:
    """src/js/glossary.ts reads this blob; without it TS badges cannot self-explain."""
    pg = MagicMock()
    pg.execute_query.side_effect = [
        [],  # briefs
        [{"total": 0, "last_sweep": None}],  # activity
        [],  # skips
    ]
    verify = patch(
        "auth.auth_manager.verify_session",
        MagicMock(return_value={"user_id": "u", "email": "admin@example.com"}),
    )
    token = patch("flask_auth_utils.get_supabase_access_token", MagicMock(return_value="t"))
    with verify, token, patch("routes.grok_admin_routes.PostgresClient", return_value=pg):
        client.set_cookie("auth_token", "test.token.value")
        resp = client.get("/grok/admin")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="glossary-data"' in html
    assert "TENSION" in html
