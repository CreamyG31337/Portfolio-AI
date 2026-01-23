#!/usr/bin/env python3
"""
Ticker Analysis Service
=======================

Analyzes individual tickers with 3 months of multi-source data:
- ETF changes (all ETFs that held this ticker)
- Congress trades
- Signals (technical analysis)
- Fundamentals
- Research articles
- Social sentiment

Formats data like AI context builder and sends to LLM for analysis.
"""

import json
import re
import logging
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timedelta, timezone
import pandas as pd

from supabase_client import SupabaseClient
from postgres_client import PostgresClient
from ollama_client import OllamaClient
from ai_skip_list_manager import AISkipListManager
from ai_context_builder import (
    format_fundamentals_table,
    format_trades
)
from settings import get_summarizing_model

# Try importing yfinance for price data
try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False
    yf = None

logger = logging.getLogger(__name__)

# Helper to extract JSON from text
def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract first JSON block found in text using regex."""
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except:
            pass
    return None

class TickerAnalysisService:
    """Analyze a ticker with 3 months of multi-source data."""
    
    LOOKBACK_DAYS = 90
    MAX_ETF_CHANGES = 50
    MAX_CONGRESS_TRADES = 30
    MAX_RESEARCH_ARTICLES = 10
    SKIP_IF_ANALYZED_WITHIN_HOURS = 24
    
    def __init__(self, ollama: OllamaClient, supabase: SupabaseClient, postgres: PostgresClient, skip_list: AISkipListManager):
        """Initialize ticker analysis service.
        
        Args:
            ollama: Ollama client for LLM analysis
            supabase: Supabase client for querying data
            postgres: Postgres client for Research DB queries
            skip_list: Skip list manager
        """
        self.ollama = ollama
        self.supabase = supabase
        self.postgres = postgres
        self.skip_list = skip_list
    
    def _recently_analyzed(self, ticker: str) -> bool:
        """Check if ticker was analyzed within SKIP_IF_ANALYZED_WITHIN_HOURS.
        
        Args:
            ticker: Ticker symbol to check
            
        Returns:
            True if recently analyzed, False otherwise
        """
        try:
            result = self.postgres.execute_query("""
                SELECT 1 FROM ticker_analysis 
                WHERE ticker = %s 
                AND updated_at > NOW() - make_interval(hours => %s)
                LIMIT 1
            """, (ticker.upper(), self.SKIP_IF_ANALYZED_WITHIN_HOURS))
            return len(result) > 0
        except Exception as e:
            logger.warning(f"Error checking recent analysis for {ticker}: {e}")
            return False

    def _resolve_analysis_model(self, model_override: Optional[str]) -> str:
        """Resolve which model to use for analysis."""
        if model_override:
            try:
                from webai_wrapper import is_webai_model
                if is_webai_model(model_override) or model_override.startswith("glm-"):
                    logger.warning(
                        "Model %s is not supported for ticker analysis; falling back to default",
                        model_override
                    )
                    return get_summarizing_model()
            except Exception as e:
                logger.warning("Failed to validate model override %s: %s", model_override, e)
                return get_summarizing_model()
            return model_override

        return get_summarizing_model()
    
    def _get_fundamentals(self, ticker: str) -> Optional[Dict]:
        """Get fundamentals from securities table.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Fundamentals dict or None
        """
        try:
            result = self.supabase.supabase.table('securities') \
                .select('*') \
                .eq('ticker', ticker.upper()) \
                .execute()
            if not result.data:
                return None

            fundamentals = result.data[0]
            missing_fields = [
                fundamentals.get('trailing_pe'),
                fundamentals.get('dividend_yield'),
                fundamentals.get('fifty_two_week_high'),
                fundamentals.get('fifty_two_week_low')
            ]
            if any(value is None for value in missing_fields) and HAS_YFINANCE:
                try:
                    ticker_upper = ticker.upper().strip()
                    ticker_obj = yf.Ticker(ticker_upper)
                    info = ticker_obj.info or {}

                    updates = {}
                    trailing_pe = info.get('trailingPE')
                    dividend_yield = info.get('dividendYield')
                    high_52w = info.get('fiftyTwoWeekHigh')
                    low_52w = info.get('fiftyTwoWeekLow')

                    if trailing_pe is not None:
                        updates['trailing_pe'] = float(trailing_pe)
                        fundamentals['trailing_pe'] = float(trailing_pe)
                    if dividend_yield is not None:
                        updates['dividend_yield'] = float(dividend_yield)
                        fundamentals['dividend_yield'] = float(dividend_yield)
                    if high_52w is not None:
                        updates['fifty_two_week_high'] = float(high_52w)
                        fundamentals['fifty_two_week_high'] = float(high_52w)
                    if low_52w is not None:
                        updates['fifty_two_week_low'] = float(low_52w)
                        fundamentals['fifty_two_week_low'] = float(low_52w)

                    if updates:
                        self.supabase.supabase.table('securities') \
                            .update(updates) \
                            .eq('ticker', ticker_upper) \
                            .execute()
                except Exception as e:
                    logger.warning(f"Error refreshing fundamentals for {ticker}: {e}")

            return fundamentals
        except Exception as e:
            logger.warning(f"Error fetching fundamentals for {ticker}: {e}")
            return None
    
    def _get_etf_changes(self, ticker: str, start_date: datetime) -> List[Dict]:
        """Get ETF changes for this ticker (all ETFs that held it).
        
        Args:
            ticker: Ticker symbol
            start_date: Start of lookback period
            
        Returns:
            List of ETF change dictionaries
        """
        try:
            start_str = start_date.strftime('%Y-%m-%d')
            result = self.supabase.supabase.from_('etf_holdings_changes') \
                .select('*') \
                .eq('holding_ticker', ticker.upper()) \
                .gte('date', start_str) \
                .order('date', desc=True) \
                .limit(self.MAX_ETF_CHANGES) \
                .execute()
            return result.data or []
        except Exception as e:
            logger.warning(f"Error fetching ETF changes for {ticker}: {e}")
            return []
    
    def _get_congress_trades(self, ticker: str, start_date: datetime) -> List[Dict]:
        """Get congress trades for this ticker.
        
        Args:
            ticker: Ticker symbol
            start_date: Start of lookback period
            
        Returns:
            List of congress trade dictionaries
        """
        try:
            start_str = start_date.strftime('%Y-%m-%d')
            result = self.supabase.supabase.table('congress_trades_enriched') \
                .select('*') \
                .eq('ticker', ticker.upper()) \
                .gte('transaction_date', start_str) \
                .order('transaction_date', desc=True) \
                .limit(self.MAX_CONGRESS_TRADES) \
                .execute()
            return result.data or []
        except Exception as e:
            logger.warning(f"Error fetching congress trades for {ticker}: {e}")
            return []
    
    def _get_latest_signals(self, ticker: str) -> Optional[Dict]:
        """Get latest signals for this ticker.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Signals dict or None
        """
        try:
            # Get latest signal from signal_analysis table
            result = self.supabase.supabase.table('signal_analysis') \
                .select('*') \
                .eq('ticker', ticker.upper()) \
                .order('analysis_date', desc=True) \
                .limit(1) \
                .execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning(f"Error fetching signals for {ticker}: {e}")
            return None
    
    def _get_research_articles(self, ticker: str, start_date: datetime) -> List[Dict]:
        """Get research articles for this ticker.
        
        Args:
            ticker: Ticker symbol
            start_date: Start of lookback period
            
        Returns:
            List of article dictionaries
        """
        try:
            start_str = start_date.isoformat()
            result = self.postgres.execute_query("""
                SELECT id, title, url, summary, source, published_at, fetched_at,
                       relevance_score, sentiment, sentiment_score, article_type
                FROM research_articles
                WHERE (tickers @> ARRAY[%s]::text[] OR ticker = %s)
                  AND fetched_at >= %s
                ORDER BY fetched_at DESC
                LIMIT %s
            """, (ticker.upper(), ticker.upper(), start_str, self.MAX_RESEARCH_ARTICLES))
            return result or []
        except Exception as e:
            logger.warning(f"Error fetching research articles for {ticker}: {e}")
            return []
    
    def _get_social_sentiment(self, ticker: str, start_date: datetime) -> Dict:
        """Get social sentiment for this ticker.
        
        Args:
            ticker: Ticker symbol
            start_date: Start of lookback period
            
        Returns:
            Dict with latest_metrics and alerts
        """
        try:
            start_str = start_date.isoformat()
            # Latest metrics per platform
            latest = self.postgres.execute_query("""
                SELECT DISTINCT ON (platform)
                    ticker, platform, volume, sentiment_label, sentiment_score,
                    bull_bear_ratio, created_at
                FROM social_metrics
                WHERE ticker = %s
                ORDER BY platform, created_at DESC
                LIMIT 10
            """, (ticker.upper(),))
            
            # Extreme alerts (last 24 hours)
            alerts = self.postgres.execute_query("""
                SELECT DISTINCT ON (platform, sentiment_label)
                    ticker, platform, sentiment_label, sentiment_score, created_at
                FROM social_metrics
                WHERE ticker = %s
                  AND sentiment_label IN ('EUPHORIC', 'FEARFUL', 'BULLISH')
                  AND created_at > NOW() - INTERVAL '24 hours'
                ORDER BY platform, sentiment_label, created_at DESC
                LIMIT 10
            """, (ticker.upper(),))
            
            return {
                'latest_metrics': latest or [],
                'alerts': alerts or []
            }
        except Exception as e:
            logger.warning(f"Error fetching social sentiment for {ticker}: {e}")
            return {'latest_metrics': [], 'alerts': []}
    
    def _get_price_data(self, ticker: str, days: int = 90) -> Optional[Dict]:
        """Get OHLCV price data and compute key metrics.
        
        Args:
            ticker: Ticker symbol
            days: Number of days of history
            
        Returns:
            Dict with price metrics or None
        """
        if not HAS_YFINANCE:
            logger.warning("yfinance not available, skipping price data")
            return None
        
        try:
            ticker_upper = ticker.upper().strip()
            logger.info(f"Fetching price data for {ticker_upper} (last {days} days)")
            
            ticker_obj = yf.Ticker(ticker_upper)
            
            # Get historical data
            hist = ticker_obj.history(period=f"{days}d", auto_adjust=False)
            
            if hist.empty:
                logger.warning(f"No price data available for {ticker_upper}")
                return None
            
            # Current price info
            current_price = float(hist['Close'].iloc[-1])
            current_volume = int(hist['Volume'].iloc[-1])
            
            # Period highs/lows
            period_high = float(hist['High'].max())
            period_low = float(hist['Low'].min())
            period_high_date = hist['High'].idxmax().strftime('%Y-%m-%d')
            period_low_date = hist['Low'].idxmin().strftime('%Y-%m-%d')
            
            # Price changes
            if len(hist) >= 2:
                prev_close = float(hist['Close'].iloc[-2])
                daily_change = current_price - prev_close
                daily_change_pct = (daily_change / prev_close) * 100 if prev_close > 0 else 0
            else:
                daily_change = 0
                daily_change_pct = 0
            
            # Period change (from start)
            start_price = float(hist['Close'].iloc[0])
            period_change = current_price - start_price
            period_change_pct = (period_change / start_price) * 100 if start_price > 0 else 0
            
            # Distance from highs/lows
            pct_from_high = ((current_price - period_high) / period_high) * 100 if period_high > 0 else 0
            pct_from_low = ((current_price - period_low) / period_low) * 100 if period_low > 0 else 0
            
            # Volume analysis
            avg_volume = int(hist['Volume'].mean())
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
            
            # Recent OHLCV data (last 10 days for context)
            recent_data = []
            for idx in hist.tail(10).itertuples():
                recent_data.append({
                    'date': idx.Index.strftime('%Y-%m-%d'),
                    'open': round(float(idx.Open), 2),
                    'high': round(float(idx.High), 2),
                    'low': round(float(idx.Low), 2),
                    'close': round(float(idx.Close), 2),
                    'volume': int(idx.Volume)
                })
            
            # Try to get 52-week data for broader context
            try:
                hist_52w = ticker_obj.history(period="1y", auto_adjust=False)
                if not hist_52w.empty:
                    high_52w = float(hist_52w['High'].max())
                    low_52w = float(hist_52w['Low'].min())
                    pct_from_52w_high = ((current_price - high_52w) / high_52w) * 100
                    pct_from_52w_low = ((current_price - low_52w) / low_52w) * 100
                else:
                    high_52w = period_high
                    low_52w = period_low
                    pct_from_52w_high = pct_from_high
                    pct_from_52w_low = pct_from_low
            except Exception:
                high_52w = period_high
                low_52w = period_low
                pct_from_52w_high = pct_from_high
                pct_from_52w_low = pct_from_low
            
            return {
                'current_price': round(current_price, 2),
                'daily_change': round(daily_change, 2),
                'daily_change_pct': round(daily_change_pct, 2),
                'period_days': days,
                'period_change_pct': round(period_change_pct, 2),
                'period_high': round(period_high, 2),
                'period_high_date': period_high_date,
                'period_low': round(period_low, 2),
                'period_low_date': period_low_date,
                'pct_from_period_high': round(pct_from_high, 2),
                'pct_from_period_low': round(pct_from_low, 2),
                'high_52w': round(high_52w, 2),
                'low_52w': round(low_52w, 2),
                'pct_from_52w_high': round(pct_from_52w_high, 2),
                'pct_from_52w_low': round(pct_from_52w_low, 2),
                'current_volume': current_volume,
                'avg_volume': avg_volume,
                'volume_ratio': round(volume_ratio, 2),
                'recent_ohlcv': recent_data
            }
            
        except Exception as e:
            logger.warning(f"Error fetching price data for {ticker}: {e}")
            return None
    
    def gather_ticker_data(self, ticker: str) -> Dict:
        """Gather 3 months of data from all sources.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Dict with all data sources
        """
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=self.LOOKBACK_DAYS)
        
        logger.info(f"Gathering data for {ticker} (last {self.LOOKBACK_DAYS} days)")
        
        return {
            'ticker': ticker.upper(),
            'start_date': start_date,
            'end_date': end_date,
            'fundamentals': self._get_fundamentals(ticker),
            'price_data': self._get_price_data(ticker, self.LOOKBACK_DAYS),
            'etf_changes': self._get_etf_changes(ticker, start_date),
            'congress_trades': self._get_congress_trades(ticker, start_date),
            'signals': self._get_latest_signals(ticker),
            'research_articles': self._get_research_articles(ticker, start_date),
            'social_sentiment': self._get_social_sentiment(ticker, start_date),
        }
    
    def _format_price_data(self, price_data: Optional[Dict]) -> str:
        """Format price data as tables for LLM context.
        
        Args:
            price_data: Price metrics dictionary or None
            
        Returns:
            Formatted string with price summary and recent OHLCV
        """
        if not price_data:
            return ""
        
        lines = ["[ Price Data & Technical Context ]"]
        
        # Summary metrics
        lines.append("")
        lines.append("Current Price Metrics:")
        lines.append(f"  Current Price: ${price_data.get('current_price', 0):.2f}")
        lines.append(f"  Daily Change: {price_data.get('daily_change_pct', 0):+.2f}%")
        lines.append(f"  {price_data.get('period_days', 90)}-Day Change: {price_data.get('period_change_pct', 0):+.2f}%")
        lines.append("")
        lines.append("Price Range ({} days):".format(price_data.get('period_days', 90)))
        lines.append(f"  Period High: ${price_data.get('period_high', 0):.2f} ({price_data.get('period_high_date', 'N/A')})")
        lines.append(f"  Period Low: ${price_data.get('period_low', 0):.2f} ({price_data.get('period_low_date', 'N/A')})")
        lines.append(f"  From Period High: {price_data.get('pct_from_period_high', 0):.1f}%")
        lines.append(f"  From Period Low: {price_data.get('pct_from_period_low', 0):+.1f}%")
        lines.append("")
        lines.append("52-Week Range:")
        lines.append(f"  52-Week High: ${price_data.get('high_52w', 0):.2f} ({price_data.get('pct_from_52w_high', 0):.1f}% from current)")
        lines.append(f"  52-Week Low: ${price_data.get('low_52w', 0):.2f} ({price_data.get('pct_from_52w_low', 0):+.1f}% from current)")
        lines.append("")
        lines.append("Volume Analysis:")
        lines.append(f"  Current Volume: {price_data.get('current_volume', 0):,}")
        lines.append(f"  Avg Volume: {price_data.get('avg_volume', 0):,}")
        lines.append(f"  Volume Ratio: {price_data.get('volume_ratio', 1.0):.2f}x average")
        
        # Recent OHLCV table
        recent = price_data.get('recent_ohlcv', [])
        if recent:
            lines.append("")
            lines.append("Recent Price Action (Last 10 Days):")
            lines.append("Date       | Open    | High    | Low     | Close   | Volume")
            lines.append("-----------|---------|---------|---------|---------|------------")
            for day in recent:
                lines.append(
                    f"{day['date']} | ${day['open']:7.2f} | ${day['high']:7.2f} | "
                    f"${day['low']:7.2f} | ${day['close']:7.2f} | {day['volume']:,}"
                )
        
        return "\n".join(lines)
    
    def _format_etf_changes(self, changes: List[Dict]) -> str:
        """Format ETF changes as table.
        
        Args:
            changes: List of ETF change dictionaries
            
        Returns:
            Formatted string
        """
        if not changes:
            return ""
        
        lines = [
            "[ ETF Holdings Changes (Last 3 Months) ]",
            "Date       | ETF  | Action | Shares Changed | % Change",
            "-----------|------|--------|----------------|----------"
        ]
        
        for c in changes[:self.MAX_ETF_CHANGES]:
            date = c.get('date', 'N/A')
            etf = c.get('etf_ticker', 'N/A')
            action = c.get('action', 'N/A')
            share_change = c.get('share_change', 0)
            percent_change = c.get('percent_change', 0)
            lines.append(f"{date} | {etf:4} | {action:6} | {share_change:15,} | {percent_change:8.1f}%")
        
        return "\n".join(lines)
    
    def _format_congress_trades(self, trades: List[Dict]) -> str:
        """Format congress trades as table.
        
        Args:
            trades: List of congress trade dictionaries
            
        Returns:
            Formatted string
        """
        if not trades:
            return ""
        
        lines = [
            "[ Congressional Trading Activity (Last 3 Months) ]",
            "Date       | Politician        | Type     | Amount",
            "-----------|-------------------|----------|----------"
        ]
        
        for t in trades[:self.MAX_CONGRESS_TRADES]:
            date = t.get('transaction_date', 'N/A')
            politician = t.get('politician', t.get('name', 'N/A'))[:17]
            trade_type = t.get('type', 'N/A')
            amount = t.get('amount', 'N/A')
            lines.append(f"{date} | {politician:17} | {trade_type:8} | {amount}")
        
        return "\n".join(lines)
    
    def _format_signals(self, signals: Optional[Dict]) -> str:
        """Format signals data.
        
        Args:
            signals: Signals dictionary or None
            
        Returns:
            Formatted string
        """
        if not signals:
            return ""
        
        lines = ["[ Technical Signals ]"]
        
        overall = signals.get('overall_signal', 'N/A')
        confidence = signals.get('confidence_score', signals.get('confidence', 0))
        structure = signals.get('structure_signal', signals.get('structure', {}))
        timing = signals.get('timing_signal', signals.get('timing', {}))
        fear = signals.get('fear_risk_signal', signals.get('fear', {}))

        trend = structure.get('trend', 'N/A')
        pullback = structure.get('pullback', 'N/A')
        breakout = structure.get('breakout', 'N/A')

        volume_ok = timing.get('volume_ok')
        rsi = timing.get('rsi')
        cci = timing.get('cci')

        volume_str = "N/A" if volume_ok is None else ("OK" if volume_ok else "Low")
        rsi_str = "N/A" if rsi is None else f"{rsi:.1f}"
        cci_str = "N/A" if cci is None else f"{cci:.1f}"

        fear_level = fear.get('fear_level', 'N/A')
        risk_score = fear.get('risk_score')
        recommendation = fear.get('recommendation', 'N/A')
        risk_score_str = "N/A" if risk_score is None else f"{risk_score:.1f}/100"

        lines.append(f"Overall Signal: {overall} (Confidence: {confidence:.0%})")
        lines.append(f"Structure - Trend: {trend}, Pullback: {pullback}, Breakout: {breakout}")
        lines.append(f"Timing - Volume: {volume_str}, RSI: {rsi_str}, CCI: {cci_str}")
        lines.append(f"Fear & Risk - Level: {fear_level}, Score: {risk_score_str}, Rec: {recommendation}")
        
        return "\n".join(lines)
    
    def _format_articles(self, articles: List[Dict]) -> str:
        """Format research articles.
        
        Args:
            articles: List of article dictionaries
            
        Returns:
            Formatted string
        """
        if not articles:
            return ""
        
        lines = [
            f"[ Research Articles (Last 3 Months) - {len(articles)} articles ]",
            "Title                                    | Source          | Date       | Sentiment",
            "----------------------------------------|-----------------|------------|----------"
        ]
        
        for a in articles[:self.MAX_RESEARCH_ARTICLES]:
            title = (a.get('title', 'N/A') or 'N/A')[:38]
            source = (a.get('source', 'N/A') or 'N/A')[:15]
            date = str(a.get('published_at', a.get('fetched_at', 'N/A')))[:10]
            sentiment = a.get('sentiment', 'N/A') or 'N/A'
            lines.append(f"{title:38} | {source:15} | {date} | {sentiment}")
        
        return "\n".join(lines)
    
    def _format_social_sentiment(self, sentiment: Dict) -> str:
        """Format social sentiment data.
        
        Args:
            sentiment: Sentiment dict with latest_metrics and alerts
            
        Returns:
            Formatted string
        """
        if not sentiment or (not sentiment.get('latest_metrics') and not sentiment.get('alerts')):
            return ""
        
        lines = ["[ Social Sentiment ]"]
        
        metrics = sentiment.get('latest_metrics', [])
        if metrics:
            lines.append("Latest Metrics:")
            for m in metrics[:5]:
                platform = m.get('platform', 'N/A')
                label = m.get('sentiment_label') or 'N/A'
                score = m.get('sentiment_score') or 0
                lines.append(f"  {platform}: {label} (score: {score:.2f})")
        
        alerts = sentiment.get('alerts', [])
        if alerts:
            lines.append("\nRecent Alerts (24h):")
            for a in alerts[:5]:
                platform = a.get('platform', 'N/A')
                label = a.get('sentiment_label', 'N/A')
                lines.append(f"  {platform}: {label}")
        
        return "\n".join(lines)
    
    def format_ticker_context(self, data: Dict) -> str:
        """Format all data sources into LLM-friendly text.
        
        Args:
            data: Dict with all ticker data sources
            
        Returns:
            Formatted context string
        """
        sections = []
        
        # Fundamentals
        if data.get('fundamentals'):
            # Format fundamentals manually (format_fundamentals_table expects positions DataFrame)
            fund = data['fundamentals']
            lines = [
                "[ Company Fundamentals ]",
                "Ticker     | Sector               | Industry                  | Country  | Mkt Cap      | P/E    | Div %  | 52W High   | 52W Low",
                "-----------|---------------------|---------------------------|----------|--------------|--------|--------|------------|----------"
            ]
            ticker = data['ticker']
            sector = str(fund.get('sector', 'N/A') or 'N/A')
            industry = str(fund.get('industry', 'N/A') or 'N/A')
            country = str(fund.get('country', 'N/A') or 'N/A')
            market_cap = fund.get('market_cap', 'N/A') or 'N/A'
            pe_ratio = fund.get('trailing_pe', fund.get('pe_ratio', 'N/A')) or 'N/A'
            dividend_yield = fund.get('dividend_yield', 'N/A') or 'N/A'
            high_52w = fund.get('fifty_two_week_high', fund.get('high_52w', 'N/A')) or 'N/A'
            low_52w = fund.get('fifty_two_week_low', fund.get('low_52w', 'N/A')) or 'N/A'

            # Align columns with fixed widths
            sector_trunc = (sector[:20] if len(sector) > 20 else sector).ljust(20)
            industry_trunc = (industry[:25] if len(industry) > 25 else industry).ljust(25)
            country_trunc = (country[:8] if len(country) > 8 else country).ljust(8)
            market_cap_trunc = (str(market_cap)[:12] if market_cap != 'N/A' else "N/A").ljust(12)
            pe_trunc = (str(pe_ratio)[:6] if pe_ratio != 'N/A' else "N/A").ljust(6)
            div_trunc = (str(dividend_yield)[:6] if dividend_yield != 'N/A' else "N/A").ljust(6)
            high_trunc = (str(high_52w)[:10] if high_52w != 'N/A' else "N/A").ljust(10)
            low_trunc = (str(low_52w)[:10] if low_52w != 'N/A' else "N/A").ljust(10)
            ticker_padded = ticker.ljust(10)

            lines.append(
                f"{ticker_padded} | {sector_trunc} | {industry_trunc} | {country_trunc} | "
                f"{market_cap_trunc} | {pe_trunc} | {div_trunc} | {high_trunc} | {low_trunc}"
            )
            sections.append("\n".join(lines))
        
        # Price data (OHLCV and metrics)
        if data.get('price_data'):
            sections.append(self._format_price_data(data['price_data']))
        
        # ETF changes
        if data.get('etf_changes'):
            sections.append(self._format_etf_changes(data['etf_changes']))
        
        # Congress trades
        if data.get('congress_trades'):
            sections.append(self._format_congress_trades(data['congress_trades']))
        
        # Signals
        if data.get('signals'):
            sections.append(self._format_signals(data['signals']))
        
        # Research articles
        if data.get('research_articles'):
            sections.append(self._format_articles(data['research_articles']))
        
        # Social sentiment
        if data.get('social_sentiment'):
            sentiment_text = self._format_social_sentiment(data['social_sentiment'])
            if sentiment_text:
                sections.append(sentiment_text)
        
        return "\n\n---\n\n".join(sections) if sections else "No data available for this ticker."
    
    def analyze_ticker(
        self,
        ticker: str,
        requested_by: Optional[str] = None,
        model_override: Optional[str] = None
    ) -> Optional[Dict]:
        """Run full analysis on a ticker.
        
        Args:
            ticker: Ticker symbol to analyze
            requested_by: User email who requested (None = scheduled)
            
        Returns:
            Analysis dictionary or None on failure
        """
        ticker_upper = ticker.upper().strip()
        
        try:
            # Gather all data
            data = self.gather_ticker_data(ticker_upper)
            
            # Format context
            context = self.format_ticker_context(data)
            
            # Get prompt
            try:
                from ai_prompts import TICKER_ANALYSIS_PROMPT
                prompt = TICKER_ANALYSIS_PROMPT.format(ticker=ticker_upper, context=context)
            except ImportError:
                logger.error("TICKER_ANALYSIS_PROMPT not found in ai_prompts.py")
                return None
            
            # Analyze with LLM
            model = self._resolve_analysis_model(model_override)
            system_prompt = "You are a financial analyst. Return ONLY valid JSON with the exact fields specified."
            
            full_response = ""
            for chunk in self.ollama.query_ollama(
                prompt=prompt,
                model=model,
                stream=True,
                system_prompt=system_prompt,
                json_mode=True,
                temperature=0.1
            ):
                full_response += chunk
            
            # Parse JSON
            response = extract_json(full_response)
            if not response:
                logger.error(f"Failed to parse JSON response for {ticker_upper}")
                return None
            
            # Save analysis
            self._save_analysis(ticker_upper, data, context, response, requested_by, model)
            
            return response
            
        except Exception as e:
            logger.error(f"Error analyzing ticker {ticker_upper}: {e}", exc_info=True)
            # Record failure in skip list
            self.skip_list.record_failure(ticker_upper, str(e))
            raise
    
    def _save_analysis(
        self,
        ticker: str,
        data: Dict,
        context: str,
        response: Dict,
        requested_by: Optional[str],
        model_used: str
    ):
        """Save analysis to ticker_analysis table.
        
        Args:
            ticker: Ticker symbol
            data: Data dict (for counts)
            context: Input context string (for debug panel)
            response: LLM response dict
            requested_by: User email or None
        """
        try:
            analysis_date = datetime.now(timezone.utc).date()
            start_date = data['start_date'].date()
            end_date = data['end_date'].date()
            
            # Generate embedding
            embedding = None
            summary_text = response.get('summary', '') or response.get('analysis_text', '')
            if summary_text:
                try:
                    embedding_list = self.ollama.generate_embedding(summary_text)
                    if embedding_list:
                        embedding = "[" + ",".join(str(float(x)) for x in embedding_list) + "]"
                except Exception as e:
                    logger.warning(f"Failed to generate embedding for {ticker}: {e}")
            
            # Prepare data counts
            etf_count = len(data.get('etf_changes', []))
            congress_count = len(data.get('congress_trades', []))
            articles_count = len(data.get('research_articles', []))
            
            # Prepare key_levels as JSON string for JSONB column
            key_levels = response.get('key_levels')
            key_levels_json = json.dumps(key_levels) if key_levels else None
            
            # Insert or update
            query = """
                INSERT INTO ticker_analysis (
                    ticker, analysis_type, analysis_date, data_start_date, data_end_date,
                    sentiment, sentiment_score, confidence_score, themes, summary,
                    analysis_text, reasoning, input_context,
                    stance, timeframe, entry_zone, target_price, stop_loss,
                    key_levels, catalysts, risks, invalidation,
                    etf_changes_count, congress_trades_count, research_articles_count,
                    embedding, model_used, requested_by
                ) VALUES (
                    %s, 'standard', %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s::jsonb, %s, %s, %s,
                    %s, %s, %s,
                    %s::vector, %s, %s
                )
                ON CONFLICT (ticker, analysis_type, analysis_date)
                DO UPDATE SET
                    sentiment = EXCLUDED.sentiment,
                    sentiment_score = EXCLUDED.sentiment_score,
                    confidence_score = EXCLUDED.confidence_score,
                    themes = EXCLUDED.themes,
                    summary = EXCLUDED.summary,
                    analysis_text = EXCLUDED.analysis_text,
                    reasoning = EXCLUDED.reasoning,
                    input_context = EXCLUDED.input_context,
                    stance = EXCLUDED.stance,
                    timeframe = EXCLUDED.timeframe,
                    entry_zone = EXCLUDED.entry_zone,
                    target_price = EXCLUDED.target_price,
                    stop_loss = EXCLUDED.stop_loss,
                    key_levels = EXCLUDED.key_levels,
                    catalysts = EXCLUDED.catalysts,
                    risks = EXCLUDED.risks,
                    invalidation = EXCLUDED.invalidation,
                    etf_changes_count = EXCLUDED.etf_changes_count,
                    congress_trades_count = EXCLUDED.congress_trades_count,
                    research_articles_count = EXCLUDED.research_articles_count,
                    embedding = EXCLUDED.embedding,
                    updated_at = NOW(),
                    requested_by = EXCLUDED.requested_by
            """
            
            self.postgres.execute_update(query, (
                ticker,
                analysis_date,
                start_date,
                end_date,
                response.get('sentiment'),
                response.get('sentiment_score'),
                response.get('confidence_score'),
                response.get('themes', []),
                response.get('summary'),
                response.get('analysis_text'),
                response.get('reasoning'),
                context,  # input_context for debug panel
                response.get('stance'),
                response.get('timeframe'),
                response.get('entry_zone'),
                response.get('target_price'),
                response.get('stop_loss'),
                key_levels_json,
                response.get('catalysts', []),
                response.get('risks', []),
                response.get('invalidation'),
                etf_count,
                congress_count,
                articles_count,
                embedding,
                model_used,
                requested_by
            ))
            
            logger.info(f"Saved ticker analysis for {ticker}")
            
        except Exception as e:
            logger.error(f"Error saving analysis for {ticker}: {e}", exc_info=True)
            raise
    
    def get_tickers_to_analyze(self) -> List[Tuple[str, int]]:
        """Get prioritized list of tickers needing analysis.
        
        Returns:
            List of (ticker, priority) tuples.
            Priority: manual=1000, holdings=100, watched=10
        """
        seen: set[str] = set()
        tickers: List[Tuple[str, int]] = []
        
        # 1. Manual requests (highest priority) - from queue
        # Store queue IDs so we can mark them complete after processing
        self._pending_manual_queue_ids: List[int] = []
        try:
            manual_result = self.supabase.supabase.table('ai_analysis_queue') \
                .select('id, target_key') \
                .eq('analysis_type', 'ticker') \
                .eq('status', 'pending') \
                .gte('priority', 1000) \
                .execute()
            for row in manual_result.data or []:
                ticker = row['target_key']
                if ticker and ticker not in seen:
                    seen.add(ticker)
                    tickers.append((ticker, 1000))
                    self._pending_manual_queue_ids.append(row['id'])
        except Exception as e:
            logger.warning(f"Error fetching manual requests: {e}")
        
        # 2. Holdings (high priority) - all funds
        try:
            holdings_result = self.supabase.supabase.table('portfolio_positions') \
                .select('ticker') \
                .execute()
            for row in holdings_result.data or []:
                ticker = row.get('ticker')
                if ticker and ticker not in seen:
                    seen.add(ticker)
                    tickers.append((ticker, 100))
        except Exception as e:
            logger.warning(f"Error fetching holdings: {e}")
        
        # 3. Watched tickers (lower priority)
        try:
            watched_result = self.supabase.supabase.table('watched_tickers') \
                .select('ticker') \
                .eq('is_active', True) \
                .execute()
            for row in watched_result.data or []:
                ticker = row.get('ticker')
                if ticker and ticker not in seen:
                    seen.add(ticker)
                    tickers.append((ticker, 10))
        except Exception as e:
            logger.warning(f"Error fetching watched tickers: {e}")
        
        # Filter out skip list and recently analyzed
        filtered = []
        for ticker, priority in tickers:
            if not self.skip_list.should_skip(ticker) and not self._recently_analyzed(ticker):
                filtered.append((ticker, priority))
        
        # Sort by priority descending
        return sorted(filtered, key=lambda x: -x[1])
    
    def mark_manual_request_complete(self, ticker: str, success: bool = True, error_message: Optional[str] = None) -> None:
        """Mark a manual queue request as complete or failed.
        
        Args:
            ticker: Ticker symbol that was processed
            success: Whether analysis succeeded
            error_message: Error message if failed
        """
        try:
            status = 'completed' if success else 'failed'
            update_data = {
                'status': status,
                'processed_at': datetime.now(timezone.utc).isoformat()
            }
            if error_message:
                update_data['error_message'] = error_message
            
            self.supabase.supabase.table('ai_analysis_queue') \
                .update(update_data) \
                .eq('analysis_type', 'ticker') \
                .eq('target_key', ticker.upper()) \
                .eq('status', 'pending') \
                .execute()
        except Exception as e:
            logger.warning(f"Error marking manual request complete for {ticker}: {e}")
