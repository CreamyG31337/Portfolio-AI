"""Per-ticker benchmark resolution for stance outcome scoring (measurement rig M2a).

Scoring every stance against one index makes ``excess_return`` measure the spread
between that index and the ticker's actual peer group rather than whether the call
was right. The stance universe here is large-cap US, US sector ETFs, and Canadian
TSX listings -- benchmarking all of it against ^RUT (small-cap US) was the mismatch.

Symbol choices are constrained by what ``benchmark_data`` already caches (^GSPC,
^RUT, QQQ, VTI have full history); ^GSPTSE self-populates on first use. ^GSPC is
used rather than SPY for the same reason -- it is already there, and the difference
is immaterial for excess-return purposes.
"""

from __future__ import annotations

from typing import Any

# US large/mid. Already cached with full history.
BENCHMARK_US_BROAD = "^GSPC"
# US small cap. Already cached.
BENCHMARK_US_SMALL = "^RUT"
# Canada broad (TSX Composite). Self-populates on first use.
BENCHMARK_CANADA = "^GSPTSE"

DEFAULT_BENCHMARK = BENCHMARK_US_BROAD

# Below this cap a US listing is scored against the small-cap index instead.
SMALL_CAP_MAX_USD = 2_000_000_000

# Suffixes that identify a Canadian listing on the price provider.
_CANADIAN_SUFFIXES = (".TO", ".V", ".CN", ".NE")

ALL_BENCHMARKS = frozenset({BENCHMARK_US_BROAD, BENCHMARK_US_SMALL, BENCHMARK_CANADA})

# Scoring scheme version stamped on every stance_outcomes row.
#   1 = legacy: every stance scored against a single hardcoded ^RUT
#   2 = per-ticker benchmark (^GSPC / ^RUT / ^GSPTSE)
#
# Bump this when the benchmark RULES change, and re-score deliberately -- never
# rewrite already-scored rows in place under a new scheme without a version bump.
# Aggregates must filter to one version: mixing schemes averages numbers measured
# against different yardsticks, which is the bug this whole exercise started from.
#
# Lives here rather than in the scheduler so both the scoring job and the
# track-record aggregates can agree on it without a cross-package import.
SCORING_VERSION = 2


def is_canadian_listing(
    ticker: str,
    *,
    price_symbol: str | None = None,
    currency: str | None = None,
) -> bool:
    """True when the security trades on a Canadian exchange.

    Checks ``price_symbol`` as well as ``ticker`` because the stored ticker does not
    always carry the exchange suffix -- ``TECK.B`` looks US-shaped but resolves to
    ``TECK-B.TO``. The resolved provider symbol is the more reliable signal, and it
    is already cached on ``securities.price_symbol`` by the scoring job.

    ``currency`` is checked last: 51 of the stance tickers have no ``securities``
    row at all, so currency is NULL for the largest single bucket of the universe.
    Suffix first, metadata second.
    """
    for candidate in (price_symbol, ticker):
        text = str(candidate or "").strip().upper()
        if text.endswith(_CANADIAN_SUFFIXES):
            return True
    return str(currency or "").strip().upper() == "CAD"


def resolve_benchmark(
    ticker: str,
    *,
    market_cap: Any = None,
    price_symbol: str | None = None,
    currency: str | None = None,
    override: str | None = None,
) -> tuple[str, bool]:
    """Return ``(benchmark_symbol, is_fallback)`` for a ticker.

    ``is_fallback`` marks a result chosen without enough information (unknown market
    cap on a US listing). Those default to the broad index but are flagged so the
    share of guessed benchmarks stays visible rather than silently inflating
    confidence in the track record.
    """
    if override:
        return str(override).strip().upper(), False

    if is_canadian_listing(ticker, price_symbol=price_symbol, currency=currency):
        # One Canadian index for now; a TSX small-cap split can come later if the
        # data justifies it.
        return BENCHMARK_CANADA, False

    cap = _to_float(market_cap)
    if cap is None:
        return DEFAULT_BENCHMARK, True
    if cap < SMALL_CAP_MAX_USD:
        return BENCHMARK_US_SMALL, False
    return BENCHMARK_US_BROAD, False


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out <= 0:  # NaN or nonsense
        return None
    return out
