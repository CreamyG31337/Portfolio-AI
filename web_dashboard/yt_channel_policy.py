"""YouTube channel blocklist (Phase K12).

Channels whose videos should never be fetched by the holdings sweep or cited as
evidence by ticker / meta analysis. Policy is "curate the sweep, never disable it"
(ROADMAP K5 re-check, 2026-11-02), so a bad channel is blocked, not the feature.

Override without a deploy via ``system_settings.youtube_channel_blocklist``: a JSON
list of ``{"channel_id": "...", "name": "...", "reason": "..."}``. Either key may be
omitted. Set it to ``[]`` to block nothing. Search hits only carry the channel *name*,
saved transcripts carry both, so entries match on either.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)

SETTING_KEY = "youtube_channel_blocklist"

# Seeded from the 2026-11-02 K5 re-check: sweep-only channels with the worst 30d
# after-cost edge vs the shuffled baseline (n >= 30 stances each). Overlapping daily
# stances, so this is a judgement call, not a significance test.
DEFAULT_BLOCKLIST: tuple[dict[str, str], ...] = (
    {"channel_id": "UCMiJUXvEpHHW5JTnW-ez9EA", "name": "Jerry Romine Stocks", "reason": "K5 30d edge -14.1pp"},
    {"channel_id": "UCYRwlu3w98_bbiek8c2Y-qw", "name": "Scott's Stock Due Diligence", "reason": "K5 30d edge -12.4pp"},
    {"channel_id": "UC8aD-2lWvqnkxKiGH91X1WQ", "name": "Dividend Guy", "reason": "K5 30d edge -11.3pp"},
    {"channel_id": "UCMhXSwYAEQl0hVmqwznBvXQ", "name": "Dougie Finance", "reason": "K5 30d edge -8.3pp"},
    {"channel_id": "UCQvSqObd4nnhUWRm7fkRiRA", "name": "SATYAJIT DASGUPTA", "reason": "K5 30d edge -7.6pp"},
    {"channel_id": "UC4ZDZpC0OvoN4cCGoUSofuA", "name": "Charged Alpha Stock Encyclopedia", "reason": "K5 30d mean excess -8.9"},
    {"channel_id": "UCZXrpiCApKZDbP2SZB-MHBA", "name": "Mining Stocks Today", "reason": "K5 30d mean excess -9.4"},
)


def _norm_name(name: Any) -> str:
    return " ".join(str(name or "").split()).casefold()


def load_blocklist() -> list[dict[str, str]]:
    """Configured entries, else the built-in default. Never raises."""
    raw: Any = None
    try:
        from settings import get_system_setting

        raw = get_system_setting(SETTING_KEY, default=None)
    except Exception as exc:
        logger.debug("Could not read %s, using default: %s", SETTING_KEY, exc)
    if raw is None:
        return [dict(e) for e in DEFAULT_BLOCKLIST]
    if not isinstance(raw, list):
        logger.warning("%s is not a list; using default", SETTING_KEY)
        return [dict(e) for e in DEFAULT_BLOCKLIST]
    return [e for e in raw if isinstance(e, dict) and (e.get("channel_id") or e.get("name"))]


class ChannelBlocklist:
    def __init__(self, entries: Iterable[dict[str, Any]]):
        self.ids = sorted({str(e["channel_id"]).strip() for e in entries if e.get("channel_id")})
        self.names = sorted({_norm_name(e["name"]) for e in entries if e.get("name")})

    def __bool__(self) -> bool:
        return bool(self.ids or self.names)

    def blocks(self, *, channel_id: Any = None, name: Any = None) -> bool:
        if channel_id and str(channel_id).strip() in self.ids:
            return True
        return bool(name) and _norm_name(name) in self.names

    def sql_exclusion(self, alias: str = "") -> tuple[str, tuple]:
        """``AND ...`` fragment dropping blocked-channel transcripts, plus its params.

        Empty when nothing is blocked. COALESCE keeps non-YouTube rows and transcripts
        without channel metadata (a NULL comparison would silently exclude them).
        """
        if not self:
            return "", ()
        p = f"{alias}." if alias else ""
        sql = (
            f" AND NOT ({p}article_type = 'YouTube Transcript' AND ("
            f"COALESCE({p}source_metadata->>'channel_id', '') = ANY(%s::text[]) OR "
            f"lower(COALESCE({p}source_metadata->>'channel', '')) = ANY(%s::text[])))"
        )
        return sql, (list(self.ids), list(self.names))


def get_blocklist() -> ChannelBlocklist:
    return ChannelBlocklist(load_blocklist())
