"""Single source of truth for the jargon this dashboard puts on screen.

Terms are rendered two ways from this one dict:
  - Jinja:  {% from "components/_help_tip.html" import help_tip %}  {{ help_tip('TENSION') }}
  - TS:     import { helpTip } from './glossary';   helpTip('TENSION')

Both produce the same Flowbite tooltip already used on the Signals page, so a
term defined here is explained identically everywhere it appears.

Each entry:
  label  — how the term is written on screen
  short  — one plain-English sentence. Written for someone who has never used
           this app: no other jargon, no abbreviations, no cross-references.
  source — where the value comes from (which job, table or human action), so a
           viewer can answer "why am I seeing this?" without reading the code.

Adding a term here is the whole job — no template or TS change is needed to
make it available.
"""

from __future__ import annotations

from typing import Any

GLOSSARY: dict[str, dict[str, str]] = {
    # ---- Insights / thesis review -------------------------------------------
    "TENSION": {
        "label": "Tension",
        "short": "An AI review disagrees with your written reasoning for holding this stock.",
        "source": "Advisory review by the local AI; it never changes your position or notes.",
    },
    "HOLDS": {
        "label": "Holds",
        "short": "An AI review looked at your reasoning and found nothing that contradicts it.",
        "source": "Advisory review by the local AI.",
    },
    "STALE_THESIS": {
        "label": "Stale",
        "short": "Your reasoning for this stock hasn't been revisited in a long time and may be out of date.",
        "source": "Advisory review by the local AI, based on how long since you last reviewed it.",
    },
    "INSUFFICIENT_DATA": {
        "label": "Insufficient data",
        "short": "There wasn't enough saved research for the AI to say anything useful.",
        "source": "Advisory review by the local AI.",
    },
    "ALIGNED": {
        "label": "Aligned",
        "short": "A second AI review agrees with the first one's call.",
        "source": "Action queue AI review.",
    },
    "disposition": {
        "label": "Disposition",
        "short": "Your stated stance on a stock: bullish, bearish, or neutral.",
        "source": "Set by you when you write or edit a thesis.",
    },
    "intent": {
        "label": "Intent",
        "short": "What you said you plan to do about this stock, such as add, trim, or hold.",
        "source": "Set by you when you write or edit a thesis.",
    },
    "weak": {
        "label": "Weak",
        "short": "Your written reasoning for this stock has little or no supporting evidence attached.",
        "source": "Flagged automatically when nothing has been linked as evidence.",
    },
    "dual_tension": {
        "label": "Dual tension",
        "short": "A live trading signal and your own written reasoning disagree about this stock.",
        "source": "Computed when the attention shortlist is built.",
    },
    "advise": {
        "label": "Advise",
        "short": "A ranked shortlist of what the system thinks deserves attention first. Suggestions only.",
        "source": "Rebuilt from the action queue, saved reviews, and watchlist signals. Nothing is traded automatically.",
    },
    "market_regime": {
        "label": "Market regime",
        "short": "A one-word read of overall market conditions, from calm and risk-taking to fearful and defensive.",
        "source": "Calculated from volatility and market breadth, not written by an AI.",
    },
    "days_to_exit": {
        "label": "Days to exit",
        "short": "How long selling the whole position would take at a tenth of the stock's normal daily volume.",
        "source": "Calculated from recent trading volume.",
    },
    "source_watchlist_search": {
        "label": "Added by search",
        "short": "Someone added this stock using the search bar on the watchlist page.",
        "source": "Manual entry on the watchlist page.",
    },
    "source_ticker_ui": {
        "label": "Added from details page",
        "short": "Someone added this stock while looking at its own details page.",
        "source": "Manual entry from the stock's details page.",
    },
    "thesis_due": {
        "label": "Due for review",
        "short": "Enough time has passed that this stock's reasoning is scheduled for another look.",
        "source": "Calculated from when you last reviewed the thesis.",
    },
    # ---- Watchlist ----------------------------------------------------------
    "priority_tier": {
        "label": "Priority tier",
        "short": "How closely this stock is watched: A is highest attention, B is routine, C is barely watched.",
        "source": "Set by you on the watchlist; controls which stocks the automated jobs spend time on.",
    },
    "tier_A": {
        "label": "A tier",
        "short": "Highest attention. These names are checked first by the research and sweep jobs.",
        "source": "Set by you on the watchlist.",
    },
    "tier_B": {
        "label": "B tier",
        "short": "Routine attention. Checked after A-tier names, when there is room.",
        "source": "Set by you on the watchlist.",
    },
    "tier_C": {
        "label": "C tier",
        "short": "Barely watched. Skipped by most automated jobs.",
        "source": "Set by you on the watchlist.",
    },
    "source_TRADELOG": {
        "label": "From your trades",
        "short": "This stock is on the watchlist because you have traded or held it.",
        "source": "Added automatically from your trade log.",
    },
    "source_ideas_inbox": {
        "label": "From discovery",
        "short": "A discovery job suggested this stock; you have not necessarily traded it.",
        "source": "Added automatically by an ideas/discovery job, not by you.",
    },
    "source_watchlist_ui": {
        "label": "Added by you",
        "short": "You added this stock to the watchlist by hand.",
        "source": "Manual entry on the watchlist page.",
    },
    # ---- Grok Bot X sweep ---------------------------------------------------
    "grok_brief": {
        "label": "X brief",
        "short": "A short written summary of what people were saying about a stock on X (Twitter).",
        "source": "Written each weekday morning by the Grok Bot, which reads X and files one brief per stock.",
    },
    "notable": {
        "label": "Notable",
        "short": "The Bot judged this day's X chatter worth your attention, rather than routine noise.",
        "source": "Decided by the Grok Bot when it writes the brief.",
    },
    "status_ingested": {
        "label": "Ingested",
        "short": "Saved, but nothing has read it yet.",
        "source": "Set when the Bot files a brief.",
    },
    "status_evaluated": {
        "label": "Evaluated",
        "short": "An AI review has already read this brief and taken it into account.",
        "source": "Set after the thesis review job uses the brief.",
    },
    "status_ignored": {
        "label": "Ignored",
        "short": "Marked as not worth acting on.",
        "source": "Set by a review step.",
    },
    "skip_auto": {
        "label": "Auto skip",
        "short": "Searching X for this stock found nothing, so it was dropped from the daily sweep to save money.",
        "source": "Added automatically when a sweep finds no posts. Remove it to start sweeping again.",
    },
    "skip_manual": {
        "label": "Manual skip",
        "short": "Someone decided this stock isn't worth searching X for, usually a broad index fund.",
        "source": "Added by hand on this page. Remove it to start sweeping again.",
    },
    "sweep": {
        "label": "Sweep",
        "short": "One morning run where the Bot searches X for up to five watchlist stocks.",
        "source": "Runs weekday mornings; each run costs a small amount of X credit.",
    },
    # ---- Signals / analysis -------------------------------------------------
    "overall_signal": {
        "label": "Overall signal",
        "short": "A combined buy/hold/sell read from several separate indicators.",
        "source": "Calculated from price and volume data, not written by an AI.",
    },
    "fear_level": {
        "label": "Fear level",
        "short": "How stressed the market looks right now, from calm to panicked.",
        "source": "Calculated from volatility and breadth measures.",
    },
    "confidence": {
        "label": "Confidence",
        "short": "How strongly the indicators agree with each other. Low confidence means mixed messages.",
        "source": "Calculated from how many indicators point the same way.",
    },
    "conviction": {
        "label": "Conviction",
        "short": "The AI's combined read on a stock after weighing all saved research.",
        "source": "Written by the ticker meta-analysis job.",
    },
    "stance": {
        "label": "Stance",
        "short": "Whether a source is positive, negative, or neutral on a stock.",
        "source": "Recorded per source so calls can be scored later.",
    },
    # ---- Other briefing sections -------------------------------------------
    "confluence_event": {
        "label": "Confluence",
        "short": "Several different signals pointed at the same stock at the same time.",
        "source": "Calculated by comparing recent signals across sources.",
    },
    "dilution_flag": {
        "label": "Dilution flag",
        "short": "A warning that a company may be issuing new shares, which reduces the value of existing ones.",
        "source": "Detected from regulatory filings.",
    },
    "insider_cluster": {
        "label": "Insider cluster",
        "short": "Several company executives bought their own company's stock around the same time.",
        "source": "Detected from insider trading disclosures.",
    },
    "congress_herd": {
        "label": "Congress herd",
        "short": "Several US politicians disclosed buying the same stock around the same time.",
        "source": "Detected from public congressional trade disclosures.",
    },
    "alpha_idea": {
        "label": "Alpha idea",
        "short": "A stock a research article suggested might be worth a look.",
        "source": "Extracted from research articles the system collected.",
    },
}


def get_glossary() -> dict[str, dict[str, str]]:
    """The whole glossary, for the Jinja context processor and the JSON blob."""
    return GLOSSARY


def get_term(key: str) -> dict[str, Any] | None:
    return GLOSSARY.get(key)
