"""Weekly retro: monthly Phase L signal re-test section."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web_dashboard"))

from retro_digest_service import _render_signal_retest  # noqa: E402

NOW = datetime(2026, 11, 20, tzinfo=UTC)


def _write(tmp_path: Path, **over) -> Path:
    data = {
        "generated_at": "2026-11-07T08:00:00+00:00",
        "holdout_from": "2026-06-01",
        "holdout_windows": ["2026-06-01", "2026-07-01", "2026-08-03"],
        "confirmed": [],
        "signals": [
            {"signal": "article_burst", "disc_n": 125, "disc_diff": 15.86, "disc_ci": [5.37, 26.12],
             "passed_discovery": True, "hold_n": 705, "hold_diff": -0.08, "hold_ci": [-2.47, 2.4],
             "confirmed": False},
            {"signal": "momentum_top", "disc_n": 550, "disc_diff": 1.2, "disc_ci": [-2.2, 4.7],
             "passed_discovery": False, "hold_n": 820, "hold_diff": -3.46, "hold_ci": [-5.26, -1.48],
             "confirmed": False},
            {"signal": "insider_buy", "disc_n": 465, "disc_diff": -0.26, "disc_ci": [-3.1, 2.7],
             "passed_discovery": False, "hold_n": 482, "hold_diff": -0.67, "hold_ci": [-3.15, 2.05],
             "confirmed": False},
        ],
    }
    data.update(over)
    p = tmp_path / "precursor_latest.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_missing_file_says_not_run(tmp_path: Path) -> None:
    out = _render_signal_retest(tmp_path / "nope.json", now=NOW)
    assert "Not run yet" in out


def test_lists_only_notable_signals(tmp_path: Path) -> None:
    out = _render_signal_retest(_write(tmp_path), now=NOW)
    assert "3 window(s)" in out
    assert "none</strong>" in out
    assert "article_burst" in out and "passed discovery, not holdout" in out
    assert "momentum_top" in out and "holdout only" in out
    assert "insider_buy" not in out  # nothing notable
    assert "STALE" not in out


def test_confirmed_and_stale(tmp_path: Path) -> None:
    p = _write(tmp_path, generated_at="2026-09-01T08:00:00+00:00", confirmed=["article_burst"])
    out = _render_signal_retest(p, now=NOW)
    assert "STALE" in out
    assert "<strong>article_burst</strong>" in out
