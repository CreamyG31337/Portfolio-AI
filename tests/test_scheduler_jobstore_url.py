"""The APScheduler jobstore must use psycopg2, whatever SQLAlchemy's default driver is."""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from web_dashboard.scheduler.scheduler_core import _jobstore_url


@pytest.mark.parametrize(
    "raw",
    [
        "postgresql://u:p@db.example:5432/postgres",
        "postgres://u:p@db.example:5432/postgres",
        "postgresql://u:p@db.example:5432/postgres?sslmode=require",
    ],
)
def test_bare_url_resolves_to_psycopg2(raw):
    url = _jobstore_url(raw)
    assert url.startswith("postgresql+psycopg2://")
    assert make_url(url).get_dialect().driver == "psycopg2"


def test_explicit_driver_is_left_alone():
    raw = "postgresql+psycopg2://u:p@db.example:5432/postgres"
    assert _jobstore_url(raw) == raw
