"""Tests for Phase K7 transcript filters.

These lock in what §21 *measured*, not what the research models asserted. The
most important tests here are the ones asserting that ``zero_friction`` is a
topic signal rather than a promotion signal — that distinction was established
by falsifying the original claim, and a future refactor should not quietly
restore the broken interpretation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(_WEB) not in sys.path:
    sys.path.insert(0, str(_WEB))

from yt_content_filters import ContentScores, score_transcript  # noqa: E402


def _pad(text: str, words: int = 600) -> str:
    """Pad past the 500-word floor that ``zero_friction`` requires."""
    return text + " filler" * words


class TestBasics:
    def test_empty_transcript_scores_zero_without_dividing_by_zero(self):
        s = score_transcript("")
        assert s.words == 0
        assert s.friction_rate == 0.0
        assert s.speech_density is None
        assert s.zero_friction is False  # too short to mean anything

    def test_whitespace_only_is_treated_as_empty(self):
        assert score_transcript("   \n\t  ").words == 0

    def test_rates_are_per_thousand_words(self):
        # One hit in exactly 1000 words -> rate of 1.0
        text = "dilution " + " ".join(["word"] * 999)
        s = score_transcript(text)
        assert s.words == 1000
        assert s.friction_rate == pytest.approx(1.0)

    def test_speech_density_is_words_per_second(self):
        s = score_transcript(" ".join(["word"] * 300), duration_s=100)
        assert s.speech_density == pytest.approx(3.0)

    def test_speech_density_none_when_duration_missing_or_zero(self):
        assert score_transcript("a b c").speech_density is None
        assert score_transcript("a b c", duration_s=0).speech_density is None


class TestFrictionIsTopicNotIntegrity:
    """§21: friction words track subject matter, not honesty. Do not re-invert."""

    def test_teardown_language_trips_zero_friction(self):
        # A known-primary teardown has no corporate-finance vocabulary at all.
        s = score_transcript(_pad("we measured the VRM and die size on the bench"))
        assert s.zero_friction is True
        assert s.primary_rate > 0

    def test_finance_interview_does_not_trip_zero_friction(self):
        # ...and a mining interview does, paid or not. This is the measured
        # direction: interviews score HIGHER on friction than primary content.
        s = score_transcript(
            _pad("the bought deal caused dilution and the warrant overhang remains")
        )
        assert s.zero_friction is False
        assert s.friction_hits >= 2

    def test_short_transcript_never_trips_zero_friction(self):
        assert score_transcript("nothing financial here").zero_friction is False

    def test_finance_topic_rate_aliases_friction_rate(self):
        s = score_transcript(_pad("burn rate and going concern"))
        assert s.finance_topic_rate == s.friction_rate > 0


class TestDisclosure:
    """The one promotional signal that survived validation."""

    def test_paid_disclosure_detected(self):
        s = score_transcript("This interview was paid for by the company.")
        assert s.disclosed_promotion is True
        assert s.disclosure_hits >= 1

    def test_clean_transcript_has_no_disclosure(self):
        assert score_transcript(_pad("we tested the cooler")).disclosed_promotion is False

    def test_business_relationship_phrasing_detected(self):
        s = score_transcript("We have a business relationship with the issuer.")
        assert s.disclosed_promotion is True


class TestOtherRegisters:
    def test_attribution_flags_derived_content(self):
        s = score_transcript("According to an article by a competitor, sources say otherwise")
        assert s.attribution_rate > 0

    def test_macro_narration_detected(self):
        s = score_transcript("The TAM and CAGR for hyperscalers in this AI boom")
        assert s.macro_rate > 0

    def test_hype_register_detected(self):
        s = score_transcript("This multi-bagger is a hidden gem, buy before it's too late")
        assert s.hype_rate > 0

    def test_keep_matches_returns_evidence(self):
        s = score_transcript("the bought deal and dilution", keep_matches=True)
        assert "friction" in s.matched
        assert any("dilution" in m for m in s.matched["friction"])

    def test_matches_empty_by_default(self):
        assert score_transcript("the bought deal").matched == {}

    def test_scores_are_frozen(self):
        s = score_transcript("hello world")
        with pytest.raises(Exception):
            s.words = 5  # type: ignore[misc]


class TestCaseInsensitivity:
    @pytest.mark.parametrize("text", ["DILUTION", "Dilution", "dilution"])
    def test_friction_terms_case_insensitive(self, text):
        assert score_transcript(_pad(text)).friction_hits >= 1
