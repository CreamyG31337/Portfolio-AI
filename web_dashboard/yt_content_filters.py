"""Transcript quality filters (Phase K7) — cheap, deterministic, no LLM call.

`PHASE_K_TREND_LAYER_PLAN.md` §2. Every heuristic here was **double-nominated by
two independent research models** across `PHASE_K_SOURCE_LIST.md` §17 and §19,
which is the bar we adopted after §8 found that models' *blocklists* of named
channels had zero overlap while their described *tells* converged.

.. warning::

   **Double-nomination is evidence, not proof — measured 2026-07-30, source list
   §21.** The headline tell (paid-IR interviews score *zero* on friction words)
   was validated against 109 known-primary tech transcripts and 12 mining
   interviews, and it **runs backwards**: friction words are more common in the
   mining interviews (median 0.20/1k, max 1.46) than in the primary tech corpus
   (median 0.00), and 95% of *known-primary* videos trip ``zero_friction`` while
   only 33% of the interviews do. The channel that openly discloses paid
   production scored the **highest** friction of any group.

   The reason is that these are **corporate-finance words**: they track subject
   matter, not integrity. A teardown never discusses dilution; a mining interview
   always does, paid or not. So ``friction_rate`` is retained as a *topic*
   feature and must **not** be used as a promotion detector.

   ``disclosure_hits`` is the one signal that survived validation. Read the
   docstrings below for what each score is now known to do.

These are **features, not gates** (source list §20). A promotional transcript is
scored and kept, never dropped: the promotion score is itself the input to the
K11 promotion-wave detector, which is a risk signal on names we already hold.

Scores are per 1,000 words so a 3-hour stream and a 5-minute explainer compare.

What is deliberately *not* here:

- **True caption-gap detection** (§17's b-roll tell) needs cue timestamps, and
  ``fetch_caption_text`` discards them — it keeps snippet text only. ``speech_density``
  is the available proxy: silent b-roll and on-screen-chart segments depress
  words-per-second against wall-clock duration. Real gap detection is a K7
  follow-up that has to plumb cue timings through K1.
- Any LLM scoring. The point of these is to run over the whole corpus for free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

# --- §19 friction words -----------------------------------------------------
# Both uranium research models, independently: paid-IR interviews score *zero*
# on the vocabulary that causes an executive discomfort. This is the single
# best filter any research round produced, and it is a word count.
_FRICTION_TERMS: tuple[str, ...] = (
    r"burn rate",
    r"dilution|dilutive",
    r"warrant overhang|warrants outstanding",
    r"bought deal",
    r"G&A|general and administrative",
    r"cost overrun|over budget",
    r"inferred (resource|only)",
    r"AISC|all[- ]in sustaining",
    r"going concern",
    r"cash runway|months of cash",
    r"impairment|write[- ]down",
    r"covenant|debt maturity",
    r"share count|fully diluted",
    r"permit(ting)? (delay|slip)|behind schedule",
)

# --- §8 derived-content attribution ----------------------------------------
# Generalised from the inline heuristic in ``scripts/stage0_yield.py`` so the
# ingest path and the Stage 0 harness can share one definition.
_ATTRIBUTION_TERMS: tuple[str, ...] = (
    r"according to (an? )?(article|report|post|tweet|story|source)",
    r"a (report|story|article|piece) (from|by)",
    r"as reported by|per a report",
    r"if we look at this tweet",
    r"sources say|rumou?r has it",
    r"analysts say|the street (thinks|expects)",
    r"a new report by|research from",
    r"headlines? (say|read)",
)

# --- §17 + §19 macro narration ---------------------------------------------
# "A technician fixing a chiller does not discuss total addressable market."
_MACRO_TERMS: tuple[str, ...] = (
    r"\bTAM\b|total addressable market",
    r"\bCAGR\b",
    r"hyperscalers?",
    r"structural (deficit|shortage)",
    r"(nuclear|AI|energy) (renaissance|boom|revolution)",
    r"the grid can'?t keep up",
    r"secular (tailwind|growth)",
    r"in this video,? we('ll| will)? (explore|discuss|break down)",
)

# --- §19 promotional register ----------------------------------------------
_HYPE_TERMS: tuple[str, ...] = (
    r"multi[- ]?bagger",
    r"game[- ]?changer",
    r"\b(10|20|50|100)x\b",
    r"must[- ](own|buy)",
    r"before it'?s too late",
    r"hidden gem|under the radar",
    r"to the moon",
    r"life[- ]changing (money|wealth|gains)",
    r"can'?t lose|no[- ]brainer",
)

# §19 both models: the interview-as-IR-vehicle tell. Promoters hand over the
# microphone with a pitch prompt instead of asking an operational question.
_STORY_PROMPT_TERMS: tuple[str, ...] = (
    r"walk (us|me) through the story",
    r"tell (us|me) about the (opportunity|story|company)",
    r"for (investors|those) new to the story",
    r"what'?s the (value proposition|investment thesis|elevator pitch)",
    r"why should investors",
    r"give us the (overview|30,?000 foot)",
)

# §19: paid pieces bury a rapid legal paragraph at the very end.
_DISCLOSURE_TERMS: tuple[str, ...] = (
    r"paid (for )?by|compensated by|sponsored by",
    r"business relationship with",
    r"disseminated on behalf of",
    r"we (own|hold) shares|long position in",
    r"this (is|was) (a )?(paid|sponsored) (interview|production|content)",
)

# Primary-observation register — weak positive evidence.
_PRIMARY_TERMS: tuple[str, ...] = (
    r"we (tested|measured|benchmarked|tore down|disassembled)",
    r"on the bench|in our lab|our testing",
    r"lead times?|backorder(ed)?|out of stock",
    r"part number|error code|serial number",
    r"bill of materials|\bBOM\b",
    r"die size|\bVRM\b|\bTDP\b|wafer|lithograph",
    r"failure (mode|rate|analysis)",
    r"we (called|spoke to|asked) (the|our)",
)


def _compile(terms: Sequence[str]) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{t})" for t in terms), re.IGNORECASE)


_FRICTION = _compile(_FRICTION_TERMS)
_ATTRIBUTION = _compile(_ATTRIBUTION_TERMS)
_MACRO = _compile(_MACRO_TERMS)
_HYPE = _compile(_HYPE_TERMS)
_STORY_PROMPT = _compile(_STORY_PROMPT_TERMS)
_DISCLOSURE = _compile(_DISCLOSURE_TERMS)
_PRIMARY = _compile(_PRIMARY_TERMS)

_WORD_RE = re.compile(r"\b[\w'-]+\b")


@dataclass(frozen=True)
class ContentScores:
    """Per-transcript filter features. All rates are per 1,000 words."""

    words: int
    friction_rate: float
    friction_hits: int
    attribution_rate: float
    macro_rate: float
    hype_rate: float
    story_prompt_hits: int
    disclosure_hits: int
    primary_rate: float
    # Words per second against wall-clock duration; None when duration unknown.
    # Low values indicate silent b-roll / on-screen graphics (§17 proxy).
    speech_density: Optional[float] = None
    matched: dict[str, list[str]] = field(default_factory=dict)

    @property
    def zero_friction(self) -> bool:
        """No corporate-finance vocabulary in a transcript long enough to matter.

        **Not a promotion signal** — §21 measured this at 95% across the
        known-primary tech corpus versus 33% on mining interviews, i.e. exactly
        inverted from §19's claim. It is a usable *topic* discriminator: true
        means "this video does not discuss corporate finance", which is what
        separates a teardown from an interview, not honest from paid.
        """
        return self.words >= 500 and self.friction_hits == 0

    @property
    def disclosed_promotion(self) -> bool:
        """Explicit paid-content disclosure in the transcript.

        The **only** promotional signal that survived §21 validation: the
        openly-compensated channel scored a median of 2 disclosure hits against
        0 for the primary corpus. It detects *disclosed* payment, so it finds
        honest promoters and by construction misses covert ones — useful as a
        K11 input, useless as a completeness guarantee.
        """
        return self.disclosure_hits > 0

    @property
    def finance_topic_rate(self) -> float:
        """Density of corporate-finance vocabulary. A topic feature, not a quality one.

        Retained under an honest name after §21 falsified its use as a promotion
        detector. Useful for routing (does this transcript discuss the issuer's
        balance sheet at all?) and as a K9 trend input.
        """
        return self.friction_rate


def score_transcript(
    text: str,
    *,
    duration_s: Optional[int] = None,
    keep_matches: bool = False,
) -> ContentScores:
    """Score one cleaned transcript. Pure function, no I/O, no model call."""
    body = text or ""
    words = len(_WORD_RE.findall(body))
    if words == 0:
        return ContentScores(
            words=0,
            friction_rate=0.0,
            friction_hits=0,
            attribution_rate=0.0,
            macro_rate=0.0,
            hype_rate=0.0,
            story_prompt_hits=0,
            disclosure_hits=0,
            primary_rate=0.0,
            speech_density=None,
        )

    per_k = 1000.0 / words

    friction = [m.group(0) for m in _FRICTION.finditer(body)]
    attribution = [m.group(0) for m in _ATTRIBUTION.finditer(body)]
    macro = [m.group(0) for m in _MACRO.finditer(body)]
    hype = [m.group(0) for m in _HYPE.finditer(body)]
    story = [m.group(0) for m in _STORY_PROMPT.finditer(body)]
    disclosure = [m.group(0) for m in _DISCLOSURE.finditer(body)]
    primary = [m.group(0) for m in _PRIMARY.finditer(body)]

    density: Optional[float] = None
    if duration_s and duration_s > 0:
        density = round(words / float(duration_s), 3)

    matched: dict[str, list[str]] = {}
    if keep_matches:
        matched = {
            "friction": sorted({m.lower() for m in friction}),
            "attribution": sorted({m.lower() for m in attribution}),
            "macro": sorted({m.lower() for m in macro}),
            "hype": sorted({m.lower() for m in hype}),
            "story_prompt": sorted({m.lower() for m in story}),
            "disclosure": sorted({m.lower() for m in disclosure}),
            "primary": sorted({m.lower() for m in primary}),
        }

    return ContentScores(
        words=words,
        friction_rate=round(len(friction) * per_k, 3),
        friction_hits=len(friction),
        attribution_rate=round(len(attribution) * per_k, 3),
        macro_rate=round(len(macro) * per_k, 3),
        hype_rate=round(len(hype) * per_k, 3),
        story_prompt_hits=len(story),
        disclosure_hits=len(disclosure),
        primary_rate=round(len(primary) * per_k, 3),
        speech_density=density,
        matched=matched,
    )
