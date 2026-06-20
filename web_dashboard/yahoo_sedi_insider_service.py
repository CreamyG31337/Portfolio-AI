"""Yahoo-sourced SEDI insider transactions for Canadian tickers (ROADMAP G7).

Parses ``yfinance.Ticker(t).insider_transactions`` for ``.TO``/``.V`` symbols and
maps rows into the Supabase ``insider_trades`` schema with ``source='yahoo_sedi'``.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

logger = logging.getLogger(__name__)

SOURCE_YAHOO_SEDI = "yahoo_sedi"
SOURCE_SEC_FORM4 = "sec_form4"

_CANADIAN_SUFFIXES = (".TO", ".V")

# Text prefixes that are NOT open-market conviction trades.
_EXCLUDED_TEXT_PREFIXES = (
    "exercise of options",
    "stock gift",
    "redemption, retraction",
    "redemption or retraction",
    "grant of options",
    "award of options",
    "conversion of securities",
)

# Yahoo SEDI text gives the per-share price as either "at price C$1.23" or the
# bare "... shares at C$0.45" form, so "price" must be optional after "at". The
# \b keeps "at" inside words like "format" from matching a stray currency token.
_PRICE_RE = re.compile(
    r"\b(?:price|at)\s+(?:C?\$|US\$|\$)\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)


def is_canadian_ticker(ticker: str) -> bool:
    upper = (ticker or "").upper().strip()
    return any(upper.endswith(suffix) for suffix in _CANADIAN_SUFFIXES)


def normalize_insider_name(raw: Any) -> str:
    name = str(raw or "").strip()
    if not name:
        return ""
    # Yahoo SEDI format: "Surname (First)" — keep as-is but collapse whitespace.
    return " ".join(name.split())


def classify_yahoo_text(text: Any) -> str | None:
    """Return Purchase, Sale, or None (noise / unclassified)."""
    raw = str(text or "").strip()
    if not raw:
        return None
    lower = raw.lower()
    for prefix in _EXCLUDED_TEXT_PREFIXES:
        if lower.startswith(prefix):
            return None
    if lower.startswith("acquisition in the public market"):
        return "Purchase"
    if lower.startswith("sale at price") or lower.startswith("disposition at price"):
        return "Sale"
    if " sale " in f" {lower} " or lower.startswith("sale "):
        return "Sale"
    if " purchase " in f" {lower} " or "acquisition" in lower:
        return "Purchase"
    return None


def parse_price_from_text(text: Any) -> Decimal | None:
    raw = str(text or "")
    match = _PRICE_RE.search(raw)
    if not match:
        return None
    try:
        d = Decimal(match.group(1).replace(",", ""))
        if not d.is_finite() or d < 0:
            return None
        return d.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "date") and callable(value.date):
        try:
            return value.date()
        except Exception:
            pass
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _parse_shares(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        shares = int(float(value))
        return shares if shares > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_value(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        d = Decimal(str(value))
        if not d.is_finite():
            return None
        return d.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _row_get(row: Mapping[str, Any] | Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return None


def row_to_insider_trade(
    row: Mapping[str, Any] | Any,
    ticker: str,
    *,
    lookback_days: int | None = None,
    as_of: date | None = None,
) -> dict[str, Any] | None:
    """Map one yfinance insider_transactions row to an insider_trades upsert dict."""
    text = _row_get(row, "Text")
    trade_type = classify_yahoo_text(text)
    if not trade_type:
        return None

    insider_name = normalize_insider_name(_row_get(row, "Insider"))
    if not insider_name:
        return None

    transaction_date = _parse_date(_row_get(row, "Start Date"))
    if not transaction_date:
        return None

    if lookback_days is not None and lookback_days > 0:
        ref = as_of or date.today()
        if (ref - transaction_date).days > lookback_days:
            return None

    shares = _parse_shares(_row_get(row, "Shares"))
    if shares is None:
        return None

    price = _parse_value(_row_get(row, "Value"))
    price_per_share: Decimal | None = parse_price_from_text(text)
    if price is None and price_per_share is not None:
        price = (price_per_share * Decimal(shares)).quantize(Decimal("0.01"))
    elif price is not None and price_per_share is None and shares:
        price_per_share = (price / Decimal(shares)).quantize(Decimal("0.01"))

    disclosure_dt = datetime.combine(transaction_date, datetime.min.time(), tzinfo=timezone.utc)

    record: dict[str, Any] = {
        "ticker": ticker.upper().strip(),
        "insider_name": insider_name,
        "insider_title": "",
        "transaction_date": transaction_date.isoformat(),
        "disclosure_date": disclosure_dt.isoformat(),
        "type": trade_type,
        "shares": shares,
        "price_per_share": float(price_per_share) if price_per_share is not None else None,
        "value": float(price) if price is not None else None,
        "notes": str(text).strip()[:500] if text else None,
        "source": SOURCE_YAHOO_SEDI,
    }
    return record


def parse_yahoo_insider_dataframe(
    df: Any,
    ticker: str,
    *,
    lookback_days: int | None = None,
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """Parse all rows from a yfinance insider_transactions DataFrame."""
    if df is None:
        return []
    try:
        empty = df.empty  # type: ignore[attr-defined]
    except Exception:
        empty = False
    if empty:
        return []

    out: list[dict[str, Any]] = []
    for record in df.to_dict("records"):  # type: ignore[union-attr]
        parsed = row_to_insider_trade(
            record,
            ticker,
            lookback_days=lookback_days,
            as_of=as_of,
        )
        if parsed:
            out.append(parsed)
    return out


def fetch_yahoo_insider_rows(
    ticker: str,
    *,
    lookback_days: int | None = 365,
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """Fetch and parse insider_transactions for one ticker via yfinance."""
    if not is_canadian_ticker(ticker):
        return []
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not available for yahoo_sedi fetch")
        return []

    try:
        df = yf.Ticker(ticker).insider_transactions
    except Exception as exc:
        logger.warning("yahoo_sedi fetch failed for %s: %s", ticker, exc)
        return []

    return parse_yahoo_insider_dataframe(
        df,
        ticker,
        lookback_days=lookback_days,
        as_of=as_of,
    )
