"""
Ticker State Builder
====================

Assembles everything known about a ticker from multiple data sources into a
single structured dict, then condenses it to a compact LLM-ready summary.

Data sources (Supabase):
  - signal_analysis   (signals, momentum, fundamentals scores)
  - securities        (raw fundamental metrics)
  - congress_trades_enriched (politician trades)
  - insider_trades    (corporate insider activity)
Data sources (Research DB / Postgres):
  - social_metrics    (social sentiment)
  - etf_holdings_log  (ETF exposure)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fundamental columns we care about from the securities table
# ---------------------------------------------------------------------------
_FUNDAMENTAL_COLS = [
    "trailing_pe", "forward_pe", "price_to_book", "price_to_sales",
    "peg_ratio", "return_on_equity", "net_margin", "operating_margin",
    "gross_margin", "revenue_growth", "earnings_growth", "current_ratio",
    "debt_to_equity", "free_cash_flow", "short_ratio",
    "short_percent_of_float", "ebitda", "trailing_eps", "forward_eps",
    "dividend_yield",
]


# ===================================================================
# Public API
# ===================================================================

def build_ticker_state(
    ticker: str,
    supabase_client: Any,
    postgres_client: Any = None,
    lookback_days: int = 30,
) -> Dict[str, Any]:
    """Assemble a complete state dict for *ticker*.

    Args:
        ticker: Uppercase ticker symbol (e.g. ``"PLTR"``).
        supabase_client: An initialised ``SupabaseClient`` instance.
        postgres_client: Optional ``PostgresClient`` for the research DB.
                         If ``None``, social sentiment is omitted.
        lookback_days: How far back to look for congress/insider/social data.

    Returns:
        A dict with keys: ticker, as_of, signals, fundamentals, social,
        congress, insider, etf_exposure, conflicts.
    """
    ticker = ticker.upper().strip()
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=lookback_days)).isoformat()

    state: Dict[str, Any] = {
        "ticker": ticker,
        "as_of": now.isoformat(),
        "signals": {},
        "fundamentals": {},
        "social": {},
        "congress": [],
        "insider": [],
        "etf_exposure": {},
        "conflicts": [],
    }

    sb = supabase_client.supabase  # raw Supabase client

    # 1. Signals -----------------------------------------------------------
    state["signals"] = _fetch_signals(sb, ticker)

    # 2. Fundamentals (raw metrics from securities table) ------------------
    state["fundamentals"] = _fetch_fundamentals(sb, ticker)

    # 3. Social sentiment (research DB) ------------------------------------
    if postgres_client:
        state["social"] = _fetch_social(postgres_client, ticker, lookback_days)

    # 4. Congress trades ---------------------------------------------------
    state["congress"] = _fetch_congress(sb, ticker, cutoff)

    # 5. Insider trades ----------------------------------------------------
    state["insider"] = _fetch_insider(sb, ticker, cutoff)

    # 6. ETF exposure (Research DB) ----------------------------------------
    if postgres_client:
        state["etf_exposure"] = _fetch_etf_exposure(postgres_client, ticker)

    # 7. Conflict detection ------------------------------------------------
    state["conflicts"] = _detect_conflicts(state)

    return state


def summarize_ticker_state(state: Dict[str, Any]) -> str:
    """Condense a state dict into a compact text block (~150-250 tokens).

    The output is designed to be pasted directly into an LLM prompt.
    """
    t = state.get("ticker", "???")
    sig = state.get("signals", {})
    fund = state.get("fundamentals", {})
    social = state.get("social", {})
    congress = state.get("congress", [])
    insider = state.get("insider", [])
    etf = state.get("etf_exposure", {})
    conflicts = state.get("conflicts", [])

    # Line 1: overall signal
    overall = sig.get("overall_signal", "N/A")
    conf = sig.get("confidence", 0)
    trend = sig.get("structure", {}).get("trend", "N/A")
    line1 = f"{t} | {overall} {_pct(conf)} conf | Trend: {trend}"

    # Line 2: momentum + fundamentals
    mom = sig.get("momentum", {})
    fun = sig.get("fundamental", {})
    mom_bias = mom.get("bias", "N/A")
    mom_score = mom.get("composite_score", 0)
    fun_quality = fun.get("quality", "N/A")
    fun_score = fun.get("composite_score", 0)
    fun_metrics = fun.get("metrics_available", 0)
    line2 = (
        f"Momentum: {mom_bias} {_pct(mom_score)} | "
        f"Fundamentals: {fun_quality} {_pct(fun_score)} ({fun_metrics} metrics)"
    )

    # Line 3: fear + risk + key timing
    fr = sig.get("fear_risk", {})
    fear = fr.get("fear_level", "N/A")
    risk = fr.get("risk_score", 0)
    rsi = sig.get("timing", {}).get("rsi")
    rsi_str = f" | RSI: {rsi:.0f}" if rsi is not None else ""
    line3 = f"Fear: {fear} | Risk: {risk:.1f}/100{rsi_str}"

    # Line 4: social + congress + insider
    parts4: list[str] = []
    if social:
        s_pct = social.get("sentiment_pct")
        s_count = social.get("post_count", 0)
        s_days = social.get("window_days", 0)
        if s_pct is not None and s_count > 0:
            parts4.append(f"Social: {_pct(s_pct)} bullish ({s_count} posts, {s_days}d)")
    if congress:
        buys = sum(1 for c in congress if c.get("type", "").lower() in ("purchase", "buy"))
        sells = sum(1 for c in congress if c.get("type", "").lower() in ("sale", "sell", "sale_full", "sale_partial"))
        parts4.append(f"Congress: {buys}B/{sells}S")
    if insider:
        net = _insider_net_direction(insider)
        parts4.append(f"Insider: {net}")
    line4 = " | ".join(parts4) if parts4 else "No social/congress/insider data"

    # Line 5: ETF + conflicts
    parts5: list[str] = []
    etf_count = etf.get("etf_count", 0)
    if etf_count:
        parts5.append(f"ETFs: {etf_count} hold")
    if conflicts:
        parts5.append("Conflicts: " + "; ".join(conflicts))
    line5 = " | ".join(parts5) if parts5 else ""

    # Line 6: standout fundamentals (if any)
    standout = _standout_fundamentals(fund)
    line6 = f"Key metrics: {standout}" if standout else ""

    lines = [line1, line2, line3, line4]
    if line5:
        lines.append(line5)
    if line6:
        lines.append(line6)
    return "\n".join(lines)


# ===================================================================
# Internal helpers -- data fetching
# ===================================================================

def _fetch_signals(sb: Any, ticker: str) -> Dict[str, Any]:
    """Get the latest signal_analysis row for *ticker*."""
    try:
        result = sb.table("signal_analysis") \
            .select("*") \
            .eq("ticker", ticker) \
            .order("analysis_date", desc=True) \
            .limit(1) \
            .execute()
        if result.data:
            row = result.data[0]
            return {
                "overall_signal": row.get("overall_signal", "HOLD"),
                "confidence": row.get("confidence_score", 0.0),
                "analysis_date": row.get("analysis_date"),
                "structure": row.get("structure_signal") or {},
                "timing": row.get("timing_signal") or {},
                "fear_risk": row.get("fear_risk_signal") or {},
                "momentum": row.get("momentum_signal") or {},
                "fundamental": row.get("fundamental_signal") or {},
                "explanation": row.get("explanation"),
            }
    except Exception as e:
        logger.warning("Error fetching signals for %s: %s", ticker, e)
    return {}


def _fetch_fundamentals(sb: Any, ticker: str) -> Dict[str, Any]:
    """Get raw fundamental metrics from the securities table."""
    try:
        cols = "ticker," + ",".join(_FUNDAMENTAL_COLS) + ",company_name,sector,industry,market_cap"
        result = sb.table("securities") \
            .select(cols) \
            .eq("ticker", ticker) \
            .limit(1) \
            .execute()
        if result.data:
            row = result.data[0]
            out: Dict[str, Any] = {}
            for col in _FUNDAMENTAL_COLS:
                val = row.get(col)
                if val is not None:
                    try:
                        out[col] = float(val)
                    except (TypeError, ValueError):
                        pass
            # Include company metadata
            for meta_col in ("company_name", "sector", "industry", "market_cap"):
                v = row.get(meta_col)
                if v:
                    out[meta_col] = v
            return out
    except Exception as e:
        logger.warning("Error fetching fundamentals for %s: %s", ticker, e)
    return {}


def _fetch_social(pg: Any, ticker: str, lookback_days: int) -> Dict[str, Any]:
    """Get recent social sentiment from the research DB."""
    try:
        rows = pg.execute_query("""
            SELECT platform, bull_bear_ratio, sentiment_label,
                   sentiment_score, post_count, volume, created_at
            FROM social_metrics
            WHERE ticker = %s
              AND created_at > NOW() - INTERVAL '%s days'
            ORDER BY created_at DESC
            LIMIT 20
        """, (ticker, lookback_days))

        if not rows:
            return {}

        total_posts = 0
        weighted_sentiment = 0.0
        weight_total = 0.0
        platforms: set[str] = set()

        for r in rows:
            platform = r.get("platform", "")
            if platform:
                platforms.add(platform)
            count = r.get("post_count") or r.get("volume") or 0
            ratio = r.get("bull_bear_ratio")
            if ratio is not None and count:
                try:
                    ratio_f = float(ratio)
                    count_f = float(count)
                    weighted_sentiment += ratio_f * count_f
                    weight_total += count_f
                except (TypeError, ValueError):
                    pass
            total_posts += int(count) if count else 0

        sentiment_pct = (weighted_sentiment / weight_total) if weight_total > 0 else None

        return {
            "sentiment_pct": round(sentiment_pct, 3) if sentiment_pct is not None else None,
            "post_count": total_posts,
            "platforms": sorted(platforms),
            "window_days": lookback_days,
        }
    except Exception as e:
        logger.warning("Error fetching social for %s: %s", ticker, e)
    return {}


def _fetch_congress(sb: Any, ticker: str, cutoff_iso: str) -> List[Dict[str, Any]]:
    """Get recent congress trades for *ticker*."""
    try:
        result = sb.table("congress_trades_enriched") \
            .select("politician, type, amount, transaction_date, party") \
            .eq("ticker", ticker) \
            .gte("transaction_date", cutoff_iso[:10]) \
            .order("transaction_date", desc=True) \
            .limit(10) \
            .execute()
        if result.data:
            return [
                {
                    "politician": r.get("politician", "Unknown"),
                    "type": r.get("type", ""),
                    "amount": r.get("amount", ""),
                    "date": r.get("transaction_date", ""),
                    "party": r.get("party", ""),
                }
                for r in result.data
            ]
    except Exception as e:
        logger.warning("Error fetching congress trades for %s: %s", ticker, e)
    return []


def _fetch_insider(sb: Any, ticker: str, cutoff_iso: str) -> List[Dict[str, Any]]:
    """Get recent insider trades for *ticker*."""
    try:
        result = sb.table("insider_trades") \
            .select("insider_name, insider_title, type, shares, value, transaction_date") \
            .eq("ticker", ticker) \
            .gte("transaction_date", cutoff_iso[:10]) \
            .order("transaction_date", desc=True) \
            .limit(10) \
            .execute()
        if result.data:
            return [
                {
                    "name": r.get("insider_name", "Unknown"),
                    "title": r.get("insider_title", ""),
                    "type": r.get("type", ""),
                    "shares": r.get("shares"),
                    "value": r.get("value"),
                    "date": r.get("transaction_date", ""),
                }
                for r in result.data
            ]
    except Exception as e:
        logger.warning("Error fetching insider trades for %s: %s", ticker, e)
    return []


def _fetch_etf_exposure(pc: Any, ticker: str) -> Dict[str, Any]:
    """Get ETF exposure -- which ETFs hold *ticker* and at what weight (Research DB)."""
    try:
        rows = pc.execute_query(
            """
            SELECT etf_ticker, weight_percent, date
            FROM etf_holdings_log
            WHERE holding_ticker = %s
            ORDER BY date DESC
            LIMIT 50
            """,
            (ticker.upper(),),
        )

        if not rows:
            return {"etf_count": 0, "top_etfs": []}

        # Deduplicate: keep latest entry per ETF
        seen: dict[str, dict] = {}
        for r in rows:
            etf = r.get("etf_ticker", "")
            if etf and etf not in seen:
                seen[etf] = {
                    "etf": etf,
                    "weight_pct": r.get("weight_percent"),
                    "date": r.get("date"),
                }

        top_etfs = sorted(
            seen.values(),
            key=lambda x: float(x.get("weight_pct") or 0),
            reverse=True,
        )[:5]

        return {
            "etf_count": len(seen),
            "top_etfs": top_etfs,
        }
    except Exception as e:
        logger.warning("Error fetching ETF exposure for %s: %s", ticker, e)
    return {"etf_count": 0, "top_etfs": []}


# ===================================================================
# Internal helpers -- conflict detection
# ===================================================================

def _detect_conflicts(state: Dict[str, Any]) -> List[str]:
    """Identify notable disagreements across data sources."""
    conflicts: List[str] = []
    sig = state.get("signals", {})
    mom = sig.get("momentum", {})
    fund = sig.get("fundamental", {})
    fear = sig.get("fear_risk", {})
    social = state.get("social", {})
    insider = state.get("insider", [])
    overall = sig.get("overall_signal", "HOLD")

    # 1. Momentum vs. fundamental divergence
    mom_bias = mom.get("bias", "NEUTRAL")
    fund_quality = fund.get("quality", "UNKNOWN")
    if mom_bias == "BULLISH" and fund_quality in ("WEAK", "UNKNOWN"):
        conflicts.append("Bullish momentum with weak/unknown fundamentals — possible speculative run")
    elif mom_bias == "BEARISH" and fund_quality in ("STRONG", "GOOD"):
        conflicts.append("Bearish momentum despite strong fundamentals — possible value opportunity")

    # 2. Signal vs. insider activity
    if insider:
        net = _insider_net_direction(insider)
        if overall in ("BUY", "WATCH") and net == "net selling":
            conflicts.append(f"Signal is {overall} but insiders are net selling")
        elif overall == "SELL" and net == "net buying":
            conflicts.append("Signal is SELL but insiders are net buying")

    # 3. Social euphoria + high fear
    fear_level = fear.get("fear_level", "LOW")
    sentiment_pct = social.get("sentiment_pct")
    if sentiment_pct is not None and sentiment_pct > 0.75 and fear_level in ("HIGH", "EXTREME"):
        conflicts.append("High social bullishness despite elevated fear — sentiment divergence")

    # 4. Strong momentum + extreme fear
    mom_score = mom.get("composite_score", 0.5)
    if mom_score > 0.7 and fear_level in ("HIGH", "EXTREME"):
        conflicts.append("Strong momentum score with high fear level — caution warranted")

    return conflicts


# ===================================================================
# Internal helpers -- formatting
# ===================================================================

def _pct(value: Any) -> str:
    """Format a 0-1 float as a percentage string."""
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "N/A"


def _insider_net_direction(trades: List[Dict[str, Any]]) -> str:
    """Determine net insider direction from a list of trades."""
    buy_value = 0.0
    sell_value = 0.0
    for t in trades:
        ttype = (t.get("type") or "").lower()
        val = t.get("value") or 0
        try:
            val = float(val)
        except (TypeError, ValueError):
            val = 0
        if ttype in ("purchase", "buy", "p - purchase"):
            buy_value += val
        elif ttype in ("sale", "sell", "s - sale", "sale_full", "sale_partial"):
            sell_value += val

    if buy_value > sell_value * 1.5:
        return "net buying"
    elif sell_value > buy_value * 1.5:
        return "net selling"
    return "mixed"


def _standout_fundamentals(fund: Dict[str, Any]) -> str:
    """Pick 3-4 standout metrics from raw fundamentals for the summary."""
    highlights: list[str] = []

    pe = fund.get("forward_pe") or fund.get("trailing_pe")
    if pe is not None:
        highlights.append(f"P/E {pe:.1f}")

    roe = fund.get("return_on_equity")
    if roe is not None:
        highlights.append(f"ROE {roe * 100:.0f}%")

    rev_g = fund.get("revenue_growth")
    if rev_g is not None:
        highlights.append(f"RevGrowth {rev_g * 100:.0f}%")

    de = fund.get("debt_to_equity")
    if de is not None:
        highlights.append(f"D/E {de:.1f}")

    margin = fund.get("net_margin")
    if margin is not None:
        highlights.append(f"Margin {margin * 100:.0f}%")

    return ", ".join(highlights[:4]) if highlights else ""
