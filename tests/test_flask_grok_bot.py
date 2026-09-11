"""Flask + service tests for Grok Bot watchlist queue and brief ingest."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from grok_bot_service import (
    GrokBotAuthError,
    GrokBotRequestError,
    DEFAULT_WATCHLIST_FUNDS,
    build_queue,
    eligible_watchlist_rows,
    get_watchlist_funds,
    parse_brief_payloads,
    select_queue_items,
    upsert_briefs,
    utc_today,
    verify_grok_bot_token,
)


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

TOKEN = "test-grok-bot-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _watch(
    ticker: str,
    *,
    tier: str = "A",
    source: str = "watchlist_ui",
    active: bool = True,
    fund: str = "TEST",
) -> dict:
    return {
        "fund": fund,
        "ticker": ticker,
        "priority_tier": tier,
        "is_active": active,
        "source": source,
    }


def test_eligible_watchlist_skips_c_tier_and_ideas_inbox() -> None:
    rows = eligible_watchlist_rows(
        [
            _watch("AAA", tier="A"),
            _watch("BBB", tier="B"),
            _watch("CCC", tier="C"),
            _watch("DDD", tier="A", source="ideas_inbox"),
            _watch("EEE", tier="A", active=False),
        ]
    )
    assert [r["ticker"] for r in rows] == ["AAA", "BBB"]


def test_eligible_merges_chimera_and_webull() -> None:
    rows = eligible_watchlist_rows(
        [
            _watch("AAA", tier="B", fund="Project Chimera"),
            _watch("AAA", tier="A", fund="RRSP Lance Webull"),
            _watch("BBB", tier="B", fund="RRSP Lance Webull"),
        ]
    )
    by_ticker = {r["ticker"]: r for r in rows}
    assert by_ticker["AAA"]["priority_tier"] == "A"
    assert by_ticker["AAA"]["funds"] == ["Project Chimera", "RRSP Lance Webull"]
    assert by_ticker["BBB"]["funds"] == ["RRSP Lance Webull"]


def test_default_watchlist_funds_are_chimera_and_webull(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROK_WATCHLIST_FUNDS", raising=False)
    monkeypatch.delenv("GROK_WATCHLIST_FUND", raising=False)
    assert get_watchlist_funds() == list(DEFAULT_WATCHLIST_FUNDS)


def test_select_queue_prefers_a_then_never_briefed() -> None:
    today = date(2026, 9, 9)
    watchlist = [
        _watch("OLD_A", tier="A"),
        _watch("NEW_A", tier="A"),
        _watch("NEW_B", tier="B"),
        _watch("DONE", tier="A"),
    ]
    last = {
        "OLD_A": {
            "sweep_date": date(2026, 9, 8),
            "created_at": datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
            "cited_urls": ["https://x.com/1"],
        },
        "DONE": {
            "sweep_date": today,
            "created_at": datetime(2026, 9, 9, 11, 0, tzinfo=UTC),
            "cited_urls": [],
        },
    }
    items = select_queue_items(watchlist, last, today=today, limit=5)
    tickers = [i["ticker"] for i in items]
    assert "DONE" not in tickers
    assert tickers[0] == "NEW_A"
    assert tickers[1] == "OLD_A"
    assert tickers[2] == "NEW_B"
    assert items[1]["last_cited_urls"] == ["https://x.com/1"]


def test_parse_brief_single_and_batch() -> None:
    one = parse_brief_payloads(
        {
            "ticker": "aaa",
            "body": "quiet day",
            "notable": False,
            "posts": [{"url": "https://x.com/a/status/1", "summary": "hi"}],
        }
    )
    assert one[0]["ticker"] == "AAA"
    assert one[0]["cited_urls"] == ["https://x.com/a/status/1"]

    batch = parse_brief_payloads(
        {
            "briefs": [
                {"ticker": "AAA", "body": "one"},
                {"ticker": "BBB", "body": "two", "themes": ["pump"]},
            ]
        }
    )
    assert len(batch) == 2


def test_parse_brief_rejects_too_many_posts() -> None:
    posts = [{"url": f"https://x.com/{i}"} for i in range(9)]
    with pytest.raises(GrokBotRequestError, match="at most 8"):
        parse_brief_payloads({"ticker": "AAA", "body": "x", "posts": posts})


def test_parse_brief_rejects_empty_body() -> None:
    with pytest.raises(GrokBotRequestError, match="body is required"):
        parse_brief_payloads({"ticker": "AAA", "body": "  "})


def test_verify_token_compare_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROK_BOT_TOKEN", TOKEN)
    verify_grok_bot_token(f"Bearer {TOKEN}")
    with pytest.raises(GrokBotAuthError) as missing:
        verify_grok_bot_token(None)
    assert missing.value.status_code == 401
    with pytest.raises(GrokBotAuthError) as bad:
        verify_grok_bot_token("Bearer wrong")
    assert bad.value.status_code == 401
    monkeypatch.delenv("GROK_BOT_TOKEN", raising=False)
    with pytest.raises(GrokBotAuthError) as unset:
        verify_grok_bot_token(f"Bearer {TOKEN}")
    assert unset.value.status_code == 503


def test_upsert_rejects_unknown_ticker() -> None:
    pg = MagicMock()
    with pytest.raises(GrokBotRequestError, match="not on watchlist"):
        upsert_briefs(
            pg,
            funds=["TEST"],
            briefs=parse_brief_payloads({"ticker": "ZZZ", "body": "nope"}),
            ticker_funds={"AAA": ["TEST"]},
        )
    pg.execute_query.assert_not_called()


def test_build_queue_caps_at_daily_remaining() -> None:
    today = date(2026, 9, 9)
    watchlist = [_watch("AAA"), _watch("BBB"), _watch("CCC"), _watch("DDD")]
    pg = MagicMock()
    pg.execute_query.side_effect = [
        [],  # no prior briefs
        [{"n": 3}],  # 3 distinct tickers already briefed today -> 2 slots left
    ]
    with patch("grok_bot_service.get_active_watchlist_rows", return_value=watchlist):
        items = build_queue(pg, MagicMock(), funds=["TEST"], today=today, limit=5)
    assert [i["ticker"] for i in items] == ["AAA", "BBB"]


def test_parse_sweep_date_only_today_or_yesterday() -> None:
    today = utc_today()
    ok = parse_brief_payloads({"ticker": "AAA", "body": "x", "sweep_date": today.isoformat()})
    assert ok[0]["sweep_date"] == today
    ok_yday = parse_brief_payloads(
        {"ticker": "AAA", "body": "x", "sweep_date": (today - timedelta(days=1)).isoformat()}
    )
    assert ok_yday[0]["sweep_date"] == today - timedelta(days=1)
    with pytest.raises(GrokBotRequestError, match="today or yesterday"):
        parse_brief_payloads(
            {"ticker": "AAA", "body": "x", "sweep_date": (today - timedelta(days=2)).isoformat()}
        )
    with pytest.raises(GrokBotRequestError, match="today or yesterday"):
        parse_brief_payloads(
            {"ticker": "AAA", "body": "x", "sweep_date": (today + timedelta(days=1)).isoformat()}
        )


def test_parse_brief_post_url_scheme_and_theme_truncation() -> None:
    with pytest.raises(GrokBotRequestError, match="http:// or https://"):
        parse_brief_payloads(
            {"ticker": "AAA", "body": "x", "posts": [{"url": "ftp://x.com/status/1"}]}
        )
    briefs = parse_brief_payloads(
        {
            "ticker": "AAA",
            "body": "x",
            "themes": ["p" * 150],
            "posts": [{"url": "HTTPS://x.com/status/1"}],
        }
    )
    assert briefs[0]["themes"] == ["p" * 100]
    assert briefs[0]["cited_urls"] == ["HTTPS://x.com/status/1"]


def test_upsert_preserves_status_when_body_and_posts_unchanged() -> None:
    today = utc_today()
    briefs = parse_brief_payloads({"ticker": "AAA", "body": "same", "sweep_date": today})
    pg = MagicMock()
    pg.execute_query.side_effect = [
        [{"ticker": "AAA"}],  # already briefed today
        [{"n": 1}],  # distinct tickers today
        [
            {
                "id": uuid4(),
                "fund": "TEST",
                "ticker": "AAA",
                "sweep_date": today,
                "body": "same",
                "themes": [],
                "posts": [],
                "notable": False,
                "cited_urls": [],
                "status": "evaluated",
                "created_at": datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
                "updated_at": datetime(2026, 9, 9, 12, 5, tzinfo=UTC),
            }
        ],
    ]
    stored = upsert_briefs(
        pg,
        funds=["TEST"],
        briefs=briefs,
        ticker_funds={"AAA": ["TEST"]},
    )
    assert stored[0]["status"] == "evaluated"
    insert_sql = " ".join(pg.execute_query.call_args_list[2].args[0].split())
    assert (
        "CASE WHEN grok_x_briefs.body IS DISTINCT FROM EXCLUDED.body"
        " OR grok_x_briefs.posts IS DISTINCT FROM EXCLUDED.posts"
        " THEN 'ingested' ELSE grok_x_briefs.status END" in insert_sql
    )
    assert "status = EXCLUDED.status" not in insert_sql


def test_upsert_daily_cap_and_same_day_retry() -> None:
    today = utc_today()
    briefs = parse_brief_payloads(
        {
            "briefs": [
                {"ticker": "NEW1", "body": "a", "sweep_date": today.isoformat()},
                {"ticker": "NEW2", "body": "b", "sweep_date": today.isoformat()},
            ]
        }
    )
    pg = MagicMock()
    pg.execute_query.side_effect = [
        [],  # neither NEW1 nor NEW2 has a row today
        [{"n": 4}],  # 4 distinct today; 2 new would be 6
    ]
    with pytest.raises(GrokBotRequestError) as cap:
        upsert_briefs(
            pg,
            funds=["TEST"],
            briefs=briefs,
            ticker_funds={"NEW1": ["TEST"], "NEW2": ["TEST"]},
        )
    assert cap.value.status_code == 429

    row_id = uuid4()
    retry_pg = MagicMock()
    retry_pg.execute_query.side_effect = [
        [{"ticker": "NEW1"}, {"ticker": "NEW2"}],
        [{"n": 2}],
        [
            {
                "id": row_id,
                "fund": "TEST",
                "ticker": "NEW1",
                "sweep_date": today,
                "body": "a",
                "themes": [],
                "posts": [],
                "notable": False,
                "cited_urls": [],
                "status": "ingested",
                "created_at": datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
                "updated_at": datetime(2026, 9, 9, 12, 5, tzinfo=UTC),
            }
        ],
        [
            {
                "id": uuid4(),
                "fund": "TEST",
                "ticker": "NEW2",
                "sweep_date": today,
                "body": "b",
                "themes": [],
                "posts": [],
                "notable": False,
                "cited_urls": [],
                "status": "ingested",
                "created_at": datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
                "updated_at": datetime(2026, 9, 9, 12, 5, tzinfo=UTC),
            }
        ],
    ]
    stored = upsert_briefs(
        retry_pg,
        funds=["TEST"],
        briefs=briefs,
        ticker_funds={"NEW1": ["TEST"], "NEW2": ["TEST"]},
    )
    assert len(stored) == 2
    assert stored[0]["status"] == "ingested"


@skip_without_plotly
def test_queue_requires_token(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROK_BOT_TOKEN", TOKEN)
    resp = client.get("/api/grok/queue")
    assert resp.status_code == 401


@skip_without_plotly
def test_queue_rejects_bad_token(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROK_BOT_TOKEN", TOKEN)
    resp = client.get("/api/grok/queue", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


@skip_without_plotly
def test_queue_unconfigured(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROK_BOT_TOKEN", raising=False)
    resp = client.get("/api/grok/queue", headers=AUTH)
    assert resp.status_code == 503


@skip_without_plotly
def test_queue_ok(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROK_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("GROK_WATCHLIST_FUNDS", "TEST")
    items = [
        {
            "ticker": "AAA",
            "priority_tier": "A",
            "fund": "TEST",
            "funds": ["TEST"],
            "last_brief_at": None,
            "last_cited_urls": [],
        }
    ]
    with patch("routes.grok_bot_routes.PostgresClient", return_value=MagicMock()), patch(
        "routes.grok_bot_routes.get_admin_supabase_client", return_value=MagicMock()
    ), patch("routes.grok_bot_routes.build_queue", return_value=items) as mock_q:
        resp = client.get("/api/grok/queue", headers=AUTH)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["funds"] == ["TEST"]
    assert body["data"][0]["ticker"] == "AAA"
    mock_q.assert_called_once()


@skip_without_plotly
def test_briefs_not_on_watchlist(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROK_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("GROK_WATCHLIST_FUNDS", "TEST")
    with patch("routes.grok_bot_routes.PostgresClient", return_value=MagicMock()), patch(
        "routes.grok_bot_routes.get_admin_supabase_client", return_value=MagicMock()
    ), patch("routes.grok_bot_routes.watchlist_ticker_funds", return_value={"AAA": ["TEST"]}):
        resp = client.post(
            "/api/grok/briefs",
            json={"ticker": "ZZZ", "body": "nope"},
            headers=AUTH,
        )
    assert resp.status_code == 400
    assert "watchlist" in resp.get_json()["error"]


@skip_without_plotly
def test_briefs_upsert_ok(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROK_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("GROK_WATCHLIST_FUNDS", "TEST")
    stored = [
        {
            "id": str(uuid4()),
            "fund": "TEST",
            "ticker": "AAA",
            "sweep_date": "2026-09-09",
            "status": "ingested",
            "notable": False,
        }
    ]
    with patch("routes.grok_bot_routes.PostgresClient", return_value=MagicMock()), patch(
        "routes.grok_bot_routes.get_admin_supabase_client", return_value=MagicMock()
    ), patch(
        "routes.grok_bot_routes.watchlist_ticker_funds", return_value={"AAA": ["TEST"]}
    ), patch(
        "routes.grok_bot_routes.upsert_briefs", return_value=stored
    ):
        resp = client.post(
            "/api/grok/briefs",
            json={"ticker": "AAA", "body": "quiet", "notable": False},
            headers=AUTH,
        )
    assert resp.status_code == 200
    assert resp.get_json()["data"][0]["ticker"] == "AAA"


@skip_without_plotly
def test_briefs_daily_cap(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROK_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("GROK_WATCHLIST_FUNDS", "TEST")
    with patch("routes.grok_bot_routes.PostgresClient", return_value=MagicMock()), patch(
        "routes.grok_bot_routes.get_admin_supabase_client", return_value=MagicMock()
    ), patch(
        "routes.grok_bot_routes.watchlist_ticker_funds", return_value={"FFF": ["TEST"]}
    ), patch(
        "routes.grok_bot_routes.upsert_briefs",
        side_effect=GrokBotRequestError("daily cap of 5 tickers reached", status_code=429),
    ):
        resp = client.post(
            "/api/grok/briefs",
            json={"ticker": "FFF", "body": "too many"},
            headers=AUTH,
        )
    assert resp.status_code == 429
