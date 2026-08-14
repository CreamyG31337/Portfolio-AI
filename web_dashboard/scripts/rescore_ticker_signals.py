#!/usr/bin/env python3
"""Re-score one ticker's signals (and optionally TA + meta) after split-adjust.

Prints the local SignalEngine result. Pass --apply to upsert signal_analysis
(and --with-ai for ticker_analysis + ticker_meta_analysis). Do not enqueue to
prod workers still running old fetch code.

Example:
    python web_dashboard/scripts/rescore_ticker_signals.py MNST
    python web_dashboard/scripts/rescore_ticker_signals.py MNST --apply --with-ai
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent
ROOT = WEB.parent
sys.path[:0] = [str(ROOT), str(WEB)]
os.environ.setdefault("DISABLE_SCHEDULER", "true")

from dotenv import load_dotenv

load_dotenv(WEB / ".env")
load_dotenv(ROOT / ".env")


def _evaluate(ticker: str):
    from market_data.data_fetcher import MarketDataFetcher
    from web_dashboard.signals.signal_engine import SignalEngine

    fundamentals = None
    try:
        from supabase_client import SupabaseClient

        sb = SupabaseClient(use_service_role=True).supabase
        resp = sb.table("securities").select("*").eq("ticker", ticker).limit(1).execute()
        if resp.data:
            fundamentals = resp.data[0]
    except Exception as exc:
        print(f"securities fetch skipped: {exc}")

    fetcher = MarketDataFetcher()
    price_data = fetcher.fetch_price_data(ticker, period="6mo")
    if price_data.df.empty:
        raise SystemExit(f"no price data for {ticker}")

    close = price_data.df["Close"]
    last = float(close.iloc[-1])
    peak = float(close.max())
    from_high = ((last / peak) - 1.0) * 100.0 if peak else 0.0
    signals = SignalEngine().evaluate(ticker, price_data.df, fundamentals=fundamentals)
    fear = signals.get("fear_risk") or {}
    structure = signals.get("structure") or {}
    print(
        f"{ticker} source={price_data.source} bars={len(price_data.df)} "
        f"last={last:.2f} from_high={from_high:.1f}% "
        f"overall={signals.get('overall_signal')} conf={signals.get('confidence')} "
        f"trend={structure.get('trend')} fear={fear.get('fear_level')} "
        f"drawdown={fear.get('drawdown_pct')} risk={fear.get('risk_score')}"
    )
    return signals, price_data


def _upsert_signals(ticker: str, signals: dict) -> None:
    from supabase_client import SupabaseClient

    sb = SupabaseClient(use_service_role=True).supabase
    analysis_date = datetime.now(timezone.utc)
    row = {
        "ticker": ticker,
        "analysis_date": analysis_date.isoformat(),
        "structure_signal": signals.get("structure", {}),
        "timing_signal": signals.get("timing", {}),
        "fear_risk_signal": signals.get("fear_risk", {}),
        "momentum_signal": signals.get("momentum", {}),
        "fundamental_signal": signals.get("fundamental", {}),
        "overall_signal": signals.get("overall_signal", "HOLD"),
        "confidence_score": signals.get("confidence", 0.0),
        "explanation": None,
    }
    sb.table("signal_analysis").upsert(row, on_conflict="ticker,analysis_date").execute()
    print(f"upserted signal_analysis {ticker} @ {analysis_date.isoformat()}")


def _run_ai(ticker: str) -> None:
    from ollama_client import OllamaClient
    from postgres_client import PostgresClient
    from supabase_client import SupabaseClient
    from ticker_analysis_service import TickerAnalysisService
    from meta_analysis_service import TickerMetaAnalysisService

    ollama = OllamaClient()
    supabase = SupabaseClient(use_service_role=True)
    postgres = PostgresClient()
    ta = TickerAnalysisService(ollama, supabase, postgres)
    saved = ta.analyze_ticker(ticker, requested_by="split-adjust-rescore")
    if not saved:
        print(f"ticker_analysis failed for {ticker}")
        return
    print(f"ticker_analysis stance={saved.get('stance')} sentiment={saved.get('sentiment')}")
    meta = TickerMetaAnalysisService(ollama, supabase, postgres)
    row = meta.run_meta_analysis(ticker, requested_by="split-adjust-rescore", force=True)
    if not row:
        print(f"ticker_meta_analysis failed for {ticker}")
        return
    print(f"ticker_meta unified_conviction={row.get('unified_conviction')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", nargs="?", default="MNST")
    parser.add_argument("--apply", action="store_true", help="Upsert signal_analysis")
    parser.add_argument("--with-ai", action="store_true", help="Re-run ticker_analysis + meta")
    args = parser.parse_args()
    ticker = str(args.ticker).upper().strip()
    signals, _price = _evaluate(ticker)
    if not args.apply:
        print("dry-run only; pass --apply to write signal_analysis")
        return 0
    _upsert_signals(ticker, signals)
    if args.with_ai:
        _run_ai(ticker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
