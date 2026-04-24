#!/usr/bin/env python3
"""
Supabase client for portfolio dashboard
Handles all database operations
"""

import os
import json

# Check critical dependencies first
try:
    import pandas as pd
except ImportError:
    print("❌ ERROR: pandas not available")
    print("🔔 SOLUTION: Activate the virtual environment first!")
    print("   PowerShell: & '..\\venv\\Scripts\\Activate.ps1'")
    print("   You should see (venv) in your prompt when activated.")
    raise ImportError("pandas not available. Activate virtual environment.")

from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Any
from decimal import Decimal
import logging
from env_loader import load_project_dotenv

# Repo root + web_dashboard/.env (cwd-independent)
load_project_dotenv()

try:
    from supabase import create_client, Client
except ImportError:
    print("❌ ERROR: Supabase client not available")
    print("🔔 SOLUTION: Activate the virtual environment first!")
    print("   PowerShell: & '..\\venv\\Scripts\\Activate.ps1'")
    print("   You should see (venv) in your prompt when activated.")
    raise ImportError("Supabase client not available. Activate virtual environment.")

logger = logging.getLogger(__name__)
# Reduce noisy debug logging by default; enable with SUPABASE_CLIENT_DEBUG=1
SUPABASE_CLIENT_DEBUG = os.getenv("SUPABASE_CLIENT_DEBUG", "").lower() in ("1", "true", "yes", "on")
if not SUPABASE_CLIENT_DEBUG:
    logger.setLevel(logging.INFO)
SUPABASE_LEGACY_HEADER_INJECTION = os.getenv(
    "SUPABASE_LEGACY_HEADER_INJECTION", "true"
).lower() in ("1", "true", "yes", "on")
SUPABASE_AUTH_DIAGNOSTICS = os.getenv("SUPABASE_AUTH_DIAGNOSTICS", "").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

class SupabaseClient:
    """Client for interacting with Supabase database"""
    
    def __init__(self, user_token: Optional[str] = None, refresh_token: Optional[str] = None, use_service_role: bool = False):
        """Initialize Supabase client
        
        Args:
            user_token: Optional JWT token from authenticated user (respects RLS)
            use_service_role: If True, use service role key (bypasses RLS, admin only)
        """
        self.url = os.getenv("SUPABASE_URL")
        
        if use_service_role:
            # Use service role key for admin operations (bypasses RLS)
            self.key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            if not self.key:
                raise ValueError("SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY must be set for admin operations")
        else:
            # Always use publishable key to initialize client (required by Supabase Python library)
            self.key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
            if not self.key:
                raise ValueError("SUPABASE_PUBLISHABLE_KEY or SUPABASE_ANON_KEY must be set")
        
        if not self.url or not self.key:
            logger.error(f"Missing environment variables - URL: {bool(self.url)}, KEY: {bool(self.key)}")
            raise ValueError("SUPABASE_URL and appropriate key must be set")
        
        # Create client with publishable/service role key
        self.supabase: Client = create_client(self.url, self.key)
        self._legacy_header_injection_enabled = SUPABASE_LEGACY_HEADER_INJECTION
        self._auth_diagnostics: Dict[str, Any] = {
            "legacy_header_injection_enabled": self._legacy_header_injection_enabled,
            "token_provided": bool(user_token),
            "token_valid": None,
            "set_session_attempted": False,
            "set_session_success": False,
            "legacy_header_injection_applied": False,
            "rpc_header_reinjection_count": 0,
        }
        
        # If user token provided, set it as the auth session
        if user_token and not use_service_role:
            # Store token for use in queries
            self._user_token = user_token
            
            logger.debug(f"[SUPABASE_CLIENT] Initializing with user token (length: {len(user_token)})")
            
            # Check if token is expired BEFORE calling set_session()
            # Calling set_session() with an expired token causes JWT validation errors
            token_is_valid = True
            try:
                import base64
                import json as json_lib
                import time as time_mod
                token_parts = user_token.split('.')
                if len(token_parts) >= 2:
                    payload = token_parts[1]
                    payload += '=' * (4 - len(payload) % 4)
                    decoded = base64.urlsafe_b64decode(payload)
                    token_data = json_lib.loads(decoded)
                    exp = token_data.get('exp', 0)
                    if exp > 0 and exp < time_mod.time():
                        logger.warning(f"[SUPABASE_CLIENT] ⚠️ Token is EXPIRED (exp={exp}, now={int(time_mod.time())}). Skipping set_session().")
                        token_is_valid = False
            except Exception as e:
                logger.debug(f"[SUPABASE_CLIENT] Could not parse token expiry: {e}")
            self._auth_diagnostics["token_valid"] = token_is_valid
            
            # CRITICAL: Set Authorization header on ALL request paths
            # The Supabase Python SDK uses multiple internal clients (postgrest, auth, etc.)
            # We need to ensure the Authorization header is set for ALL of them
            
            # Only call set_session if token is not expired
            if token_is_valid:
                try:
                    self._auth_diagnostics["set_session_attempted"] = True
                    # Method 1: Set session via auth client (standard approach)
                    # This is the CORRECT way - it sets auth headers globally for ALL requests
                    # including RPC calls, table queries, etc.
                    if refresh_token:
                        # Use both tokens for proper session
                        self.supabase.auth.set_session(
                            access_token=user_token,
                            refresh_token=refresh_token
                        )
                        self._auth_diagnostics["set_session_success"] = True
                        logger.debug("[SUPABASE_CLIENT] ✅ Successfully called auth.set_session() with refresh_token")
                    else:
                        # Try with empty refresh_token as fallback
                        self.supabase.auth.set_session(
                            access_token=user_token,
                            refresh_token=""
                        )
                        self._auth_diagnostics["set_session_success"] = True
                        logger.debug("[SUPABASE_CLIENT] ⚠️ Called auth.set_session() without refresh_token (may not work for RPC)")
                except Exception as e:
                    logger.warning(f"[SUPABASE_CLIENT] ❌ auth.set_session() failed: {e}")
                    # Check if this is a signature/JWT validation error - if so, mark session as invalid
                    # so the auth middleware can force a logout/redirect
                    error_str = str(e).lower()
                    if "invalid jwt" in error_str or "signature" in error_str or "token" in error_str:
                        try:
                            from flask import request, has_request_context
                            if has_request_context():
                                request._supabase_session_invalid = True
                                logger.warning("[SUPABASE_CLIENT] 🚨 Marked session as invalid due to JWT error")
                        except ImportError:
                            pass  # Not in Flask context
            else:
                # Token is expired - mark session as invalid so refresh flow can handle it
                try:
                    from flask import request, has_request_context
                    if has_request_context():
                        request._supabase_session_invalid = True
                        logger.warning("[SUPABASE_CLIENT] 🚨 Marked session as invalid due to expired token")
                except ImportError:
                    pass  # Not in Flask context
            if self._legacy_header_injection_enabled:
                self._apply_legacy_header_injection(user_token)
            elif SUPABASE_AUTH_DIAGNOSTICS:
                logger.info(
                    "[SUPABASE_CLIENT] Legacy header injection disabled "
                    "(SUPABASE_LEGACY_HEADER_INJECTION=false); using set_session-only path"
                )
            
            logger.debug("[SUPABASE_CLIENT] Completed user token initialization")

        if SUPABASE_AUTH_DIAGNOSTICS:
            logger.info("[SUPABASE_CLIENT] Auth diagnostics: %s", self._auth_diagnostics)

    def _apply_legacy_header_injection(self, user_token: str) -> None:
        """Apply legacy header mutations for SDK compatibility.

        This is intentionally feature-flagged and can be disabled with
        SUPABASE_LEGACY_HEADER_INJECTION=false for staged rollout.
        """
        # Method 2: Set Authorization header directly on postgrest client
        try:
            logger.debug(f"[SUPABASE_CLIENT] postgrest exists: {hasattr(self.supabase, 'postgrest')}")
            if hasattr(self.supabase, 'postgrest') and self.supabase.postgrest:
                logger.debug(f"[SUPABASE_CLIENT] postgrest.session exists: {hasattr(self.supabase.postgrest, 'session')}")
                logger.debug(f"[SUPABASE_CLIENT] postgrest.auth exists: {hasattr(self.supabase.postgrest, 'auth')}")
                if hasattr(self.supabase.postgrest, 'session'):
                    self.supabase.postgrest.session.headers["Authorization"] = f"Bearer {user_token}"
                    logger.debug("[SUPABASE_CLIENT] ✅ Set Authorization header on postgrest.session")
                elif hasattr(self.supabase.postgrest, 'auth'):
                    self.supabase.postgrest.auth(user_token)
                    logger.debug("[SUPABASE_CLIENT] ✅ Called postgrest.auth()")
                else:
                    logger.warning("[SUPABASE_CLIENT] ❌ No postgrest.session or postgrest.auth() available")
        except Exception as e:
            logger.warning(f"[SUPABASE_CLIENT] ❌ Could not set postgrest headers: {e}")

        # Method 3: Set headers on underlying clients used by some SDK paths
        try:
            logger.debug(f"[SUPABASE_CLIENT] options exists: {hasattr(self.supabase, 'options')}")
            if hasattr(self.supabase, 'options') and self.supabase.options:
                logger.debug(f"[SUPABASE_CLIENT] options.headers exists: {hasattr(self.supabase.options, 'headers')}")
                if not hasattr(self.supabase.options, 'headers'):
                    self.supabase.options.headers = {}
                self.supabase.options.headers["Authorization"] = f"Bearer {user_token}"
                logger.debug("[SUPABASE_CLIENT] ✅ Set Authorization header in client options")

            logger.debug(f"[SUPABASE_CLIENT] rest exists: {hasattr(self.supabase, 'rest')}")
            if hasattr(self.supabase, 'rest') and self.supabase.rest and hasattr(self.supabase.rest, 'session'):
                self.supabase.rest.session.headers["Authorization"] = f"Bearer {user_token}"
                logger.debug("[SUPABASE_CLIENT] ✅ Set Authorization header on rest.session")

            logger.debug(f"[SUPABASE_CLIENT] _client exists: {hasattr(self.supabase, '_client')}")
            if hasattr(self.supabase, '_client') and hasattr(self.supabase._client, 'headers'):
                self.supabase._client.headers["Authorization"] = f"Bearer {user_token}"
                logger.debug("[SUPABASE_CLIENT] ✅ Set Authorization header on _client")

            self._auth_diagnostics["legacy_header_injection_applied"] = True
        except Exception as e:
            logger.warning(f"[SUPABASE_CLIENT] ❌ Could not set client-level headers: {e}")
    
    def test_connection(self) -> bool:
        """Test database connection"""
        try:
            result = self.supabase.table("cash_balances").select("*").limit(1).execute()
            return True
        except Exception as e:
            logger.error(f"❌ Supabase connection failed: {e}")
            return False
    
    def rpc(self, function_name: str, params: dict = None) -> Any:
        """Call RPC function with guaranteed Authorization header
        
        This method ensures the Authorization header is set correctly before making
        the RPC call, which is required for auth.uid() to work in SQL functions.
        
        Args:
            function_name: Name of the RPC function to call
            params: Parameters to pass to the function (optional)
            
        Returns:
            Result of the RPC call
            
        Raises:
            Exception: If RPC call fails
        """
        if not hasattr(self.supabase, 'postgrest'):
            raise ValueError("Supabase client does not have postgrest attribute")
        
        postgrest = self.supabase.postgrest
        
        # Optional legacy re-injection before RPC.
        if self._legacy_header_injection_enabled and hasattr(self, '_user_token') and self._user_token:
            # Set header directly on session - this is more reliable than postgrest.auth()
            if hasattr(postgrest, 'session'):
                session_headers = postgrest.session.headers
                
                # Headers object type - check if it supports dict-like assignment
                try:
                    # Try setting directly (works for most header types)
                    session_headers['Authorization'] = f'Bearer {self._user_token}'
                except Exception as header_error:
                    # Fallback for httpx.Headers which might require different approach
                    logger.warning(f"Could not set Authorization header directly: {header_error}")
                    # For httpx, try merging
                    try:
                        from httpx import Headers
                        if isinstance(session_headers, Headers):
                            new_headers = session_headers.copy()
                            new_headers['Authorization'] = f'Bearer {self._user_token}'
                            postgrest.session.headers = new_headers
                    except ImportError:
                        pass
                self._auth_diagnostics["rpc_header_reinjection_count"] += 1
        
        # Now make the RPC call
        # The session should have the Authorization header set above
        # Always pass params (even if empty) as SyncPostgrestClient.rpc() requires it
        result = postgrest.rpc(function_name, params or {}).execute()
        
        # Verify header was set (for debugging)
        if hasattr(self, '_user_token') and self._user_token:
            final_auth = postgrest.session.headers.get('Authorization', '')
            if not final_auth or self._user_token not in final_auth:
                logger.warning(f"[RPC] Authorization header was NOT included in RPC call for {function_name}")
            else:
                logger.debug(f"[RPC] Authorization header was included: {final_auth[:30]}...")
        
        return result
    
    def ensure_ticker_in_securities(self, ticker: str, currency: str, company_name: Optional[str] = None) -> bool:
        """Ensure ticker exists in securities table with metadata from yfinance.
        
        This method is called on first trade to populate the securities table.
        It checks if the ticker exists and has company metadata. If not, it fetches
        from yfinance and inserts/updates the record.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL', 'SHOP.TO')
            currency: Currency code ('CAD' or 'USD')
            company_name: Optional company name if already known (avoids yfinance call)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if ticker already exists with complete metadata
            existing = self.supabase.table("securities").select("ticker, company_name, sector, industry").eq("ticker", ticker).execute()
            
            # Check if ticker exists with valid metadata (not just ticker name, has sector/industry)
            existing_company_name = None
            has_complete_metadata = False
            
            if existing.data:
                existing_company_name = existing.data[0].get('company_name')
                existing_sector = existing.data[0].get('sector')
                existing_industry = existing.data[0].get('industry')
                
                # Consider metadata complete if:
                # 1. Company name exists and is not just the ticker, not 'Unknown', and not empty
                # 2. Has sector or industry (indicates yfinance data was fetched)
                # Note: We also check if company_name is NULL/empty to ensure we fetch even if ticker exists
                if (existing_company_name and 
                    existing_company_name != ticker and 
                    existing_company_name != 'Unknown' and
                    existing_company_name.strip() and
                    (existing_sector or existing_industry)):
                    has_complete_metadata = True
                # If company_name is NULL or 'Unknown', we need to fetch (even if sector/industry exist)
                elif not existing_company_name or existing_company_name == 'Unknown' or not existing_company_name.strip():
                    has_complete_metadata = False
            
            # If ticker exists with complete metadata, no need to update
            if has_complete_metadata:
                logger.debug(f"Ticker {ticker} already exists in securities table with complete metadata")
                return True
            
            # Need to fetch/update metadata from yfinance
            metadata = {
                'ticker': ticker,
                'currency': currency
            }
            
            # If company_name parameter was provided and ticker doesn't have complete metadata, use it
            # Otherwise fetch from yfinance to get full metadata including sector/industry
            if company_name and company_name.strip() and not existing.data:
                # Only use provided company_name if ticker doesn't exist at all
                metadata['company_name'] = company_name.strip()
            else:
                # Always fetch from yfinance to get complete metadata (company_name, sector, industry, etc.)
                try:
                    import yfinance as yf
                    from web_dashboard.ticker_utils import _get_yfinance_ticker_candidates

                    info = None
                    for yf_symbol in _get_yfinance_ticker_candidates(ticker):
                        try:
                            candidate = yf.Ticker(yf_symbol).info
                            if candidate and candidate.get("symbol"):
                                info = candidate
                                logger.debug(
                                    "yfinance resolved %s via candidate %s",
                                    ticker,
                                    yf_symbol,
                                )
                                break
                        except Exception as cand_err:
                            logger.debug(
                                "yfinance candidate %s failed for %s: %s",
                                yf_symbol,
                                ticker,
                                cand_err,
                            )
                    
                    if info:
                        # Get company name (prefer longName over shortName)
                        metadata['company_name'] = info.get('longName') or info.get('shortName', 'Unknown')
                        
                        # Get additional metadata
                        metadata['sector'] = info.get('sector')
                        metadata['industry'] = info.get('industry')
                        metadata['country'] = info.get('country')
                        
                        # Get company website (for domain-based logo lookups)
                        website = info.get('website')
                        if website:
                            metadata['website'] = website.strip()

                        # Get market cap (store as text since it can be very large)
                        market_cap = info.get('marketCap')
                        if market_cap:
                            metadata['market_cap'] = str(market_cap)
                        
                        # Get company description (longBusinessSummary) - store in description column
                        company_description = (
                            info.get('longBusinessSummary') or 
                            info.get('longDescription') or 
                            info.get('description')
                        )
                        if company_description:
                            metadata['description'] = company_description.strip()

                        # Populate fundamental metrics (all optional, skip on None)
                        _YFINANCE_FUNDAMENTAL_MAP = {
                            'trailingPE': 'trailing_pe',
                            'dividendYield': 'dividend_yield',
                            'fiftyTwoWeekHigh': 'fifty_two_week_high',
                            'fiftyTwoWeekLow': 'fifty_two_week_low',
                            'forwardPE': 'forward_pe',
                            'priceToBook': 'price_to_book',
                            'priceToSalesTrailing12Months': 'price_to_sales',
                            'pegRatio': 'peg_ratio',
                            'returnOnEquity': 'return_on_equity',
                            'profitMargins': 'net_margin',
                            'operatingMargins': 'operating_margin',
                            'grossMargins': 'gross_margin',
                            'revenueGrowth': 'revenue_growth',
                            'earningsGrowth': 'earnings_growth',
                            'currentRatio': 'current_ratio',
                            'debtToEquity': 'debt_to_equity',
                            'freeCashflow': 'free_cash_flow',
                            'shortRatio': 'short_ratio',
                            'shortPercentOfFloat': 'short_percent_of_float',
                            'ebitda': 'ebitda',
                            'trailingEps': 'trailing_eps',
                            'forwardEps': 'forward_eps',
                        }
                        for yf_key, db_col in _YFINANCE_FUNDAMENTAL_MAP.items():
                            raw = info.get(yf_key)
                            if raw is not None:
                                try:
                                    metadata[db_col] = float(raw)
                                except (TypeError, ValueError):
                                    pass
                        
                        logger.debug(f"Fetched metadata for {ticker}: {metadata.get('company_name')}, sector={metadata.get('sector')}, industry={metadata.get('industry')}")
                    else:
                        logger.warning(f"No yfinance info available for {ticker}")
                        metadata['company_name'] = 'Unknown'
                        
                except Exception as yf_error:
                    logger.warning(f"Failed to fetch yfinance data for {ticker}: {yf_error}")
                    metadata['company_name'] = 'Unknown'
            
            # Set last_updated timestamp
            metadata['last_updated'] = datetime.now(timezone.utc).isoformat()
            
            # Upsert into securities table
            result = self.supabase.table("securities").upsert(metadata, on_conflict="ticker").execute()
            
            logger.info(f"✅ Ensured {ticker} in securities table: {metadata.get('company_name')}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error ensuring ticker {ticker} in securities table: {e}")
            return False
    
    def upsert_portfolio_positions(self, positions_df: pd.DataFrame) -> bool:
        """Insert or update portfolio positions"""
        try:
            if positions_df.empty:
                return True
            
            # Extract unique tickers and ensure they exist in securities table
            unique_tickers = positions_df['Ticker'].unique()
            for ticker in unique_tickers:
                # Get currency for this ticker (use first occurrence)
                ticker_rows = positions_df[positions_df['Ticker'] == ticker]
                currency = ticker_rows.iloc[0].get('Currency', 'USD') if 'Currency' in ticker_rows.columns else 'USD'
                
                # Get company name if available (avoid yfinance call if we already have it)
                company_name = ticker_rows.iloc[0].get('Company') if 'Company' in ticker_rows.columns else None
                
                # Ensure ticker is in securities table
                self.ensure_ticker_in_securities(ticker, currency, company_name)
            
            # Convert DataFrame to list of dictionaries
            # NOTE: total_value is a GENERATED COLUMN - do not include it in inserts
            positions = []
            for _, row in positions_df.iterrows():
                positions.append({
                    "ticker": row["Ticker"],
                    "shares": float(row["Shares"]),
                    "price": float(row["Current Price"]),
                    "cost_basis": float(row["Cost Basis"]),
                    # "total_value": market_value,  # REMOVED: Generated column - DB calculates automatically
                    "pnl": float(row["PnL"]),
                    "date": row["Date"].isoformat() if pd.notna(row["Date"]) else datetime.now(timezone.utc).isoformat()
                })
            
            # Upsert positions (insert or update on conflict)
            # Use on_conflict to handle duplicates based on unique constraint (fund, date, ticker)
            # Note: This requires fund to be included in positions - if not provided, this will fail
            # The unique constraint is on (fund, date::date, ticker) via idx_portfolio_positions_unique
            # For functional indexes, we reference the index name or use column names
            # PostgREST will use the unique index automatically if column names match
            result = self.supabase.table("portfolio_positions").upsert(
                positions,
                on_conflict="fund,date,ticker"
            ).execute()
            logger.info(f"✅ Upserted {len(positions)} portfolio positions")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error upserting portfolio positions: {e}")
            return False
    
    def upsert_trade_log(self, trades_df: pd.DataFrame) -> bool:
        """Insert or update trade log"""
        try:
            if trades_df.empty:
                return True

            # trade_log.fund is NOT NULL in schema; require it explicitly.
            fund_col = "Fund" if "Fund" in trades_df.columns else ("fund" if "fund" in trades_df.columns else None)
            if fund_col is None:
                raise ValueError("upsert_trade_log requires a 'Fund' column in trades_df")
            
            # Extract unique tickers and ensure they exist in securities table
            unique_tickers = trades_df['Ticker'].unique()
            for ticker in unique_tickers:
                # Get currency for this ticker (use first occurrence)
                ticker_rows = trades_df[trades_df['Ticker'] == ticker]
                currency = ticker_rows.iloc[0].get('Currency', 'USD') if 'Currency' in ticker_rows.columns else 'USD'
                
                # Ensure ticker is in securities table (no company name in trade log)
                self.ensure_ticker_in_securities(ticker, currency, None)
            
            # Convert DataFrame to list of dictionaries
            trades = []
            from utils.trade_reason import infer_trade_action

            for _, row in trades_df.iterrows():
                fund_value = str(row.get(fund_col) or "").strip()
                if not fund_value:
                    raise ValueError("upsert_trade_log encountered row with missing/empty fund")
                reason_str = str(row["Reason"])
                act = infer_trade_action(reason_str, default="BUY")
                if act not in ("BUY", "SELL", "DIVIDEND"):
                    act = "BUY"
                trades.append({
                    "fund": fund_value,
                    "date": row["Date"].isoformat() if pd.notna(row["Date"]) else datetime.now(timezone.utc).isoformat(),
                    "ticker": row["Ticker"],
                    "shares": float(row["Shares"]),
                    "price": float(row["Price"]),
                    "cost_basis": float(row["Cost Basis"]),
                    "pnl": float(row["PnL"]),
                    "reason": reason_str,
                    "action": act,
                })
            
            # Insert trades (no upsert needed for trade log)
            result = self.supabase.table("trade_log").insert(trades).execute()
            logger.info(f"✅ Inserted {len(trades)} trade log entries")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error inserting trade log: {e}")
            return False
    
    def upsert_cash_balances(self, cash_balances: Dict[str, float]) -> bool:
        """Update cash balances"""
        try:
            for currency, amount in cash_balances.items():
                result = self.supabase.table("cash_balances").update({
                    "amount": float(amount),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("currency", currency).execute()
            
            logger.info(f"✅ Updated cash balances: {cash_balances}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error updating cash balances: {e}")
            return False
    
    def get_current_positions(self, fund: Optional[str] = None) -> List[Dict]:
        """Get current positions (wrapper for latest_positions table)"""
        try:
            query = self.supabase.table("latest_positions").select("*")
            if fund:
                query = query.eq("fund", fund)
            result = query.execute()
            return result.data
        except Exception as e:
            logger.error(f"❌ Error getting current positions: {e}")
            return []
    
    def get_trade_log(self, limit: int = 100, fund: Optional[str] = None) -> List[Dict]:
        """Get recent trade log entries with company names, optionally filtered by fund"""
        try:
            # Select trade_log columns and join with securities for company_name
            query = self.supabase.table("trade_log").select(
                "*, securities(company_name)"
            ).order("date", desc=True).limit(limit)
            
            if fund:
                query = query.eq("fund", fund)
            
            result = query.execute()
            
            # Flatten the nested securities object for easier consumption
            trades = []
            for row in result.data:
                trade = row.copy()
                # Extract company_name from nested securities object
                if 'securities' in trade and trade['securities']:
                    trade['company_name'] = trade['securities'].get('company_name')
                    del trade['securities']  # Remove the nested object
                else:
                    trade['company_name'] = None
                trades.append(trade)
            
            return trades
        except Exception as e:
            logger.error(f"❌ Error getting trade log: {e}")
            return []
    
    def get_cash_balances(self, fund: Optional[str] = None) -> Dict[str, float]:
        """Get current cash balances, optionally filtered by fund"""
        try:
            query = self.supabase.table("cash_balances").select("*")
            if fund:
                query = query.eq("fund", fund)
            result = query.execute()
            balances = {}
            for row in result.data:
                key = f"{row['fund']}_{row['currency']}" if not fund else row["currency"]
                balances[key] = float(row["amount"])
            return balances
        except Exception as e:
            logger.error(f"❌ Error getting cash balances: {e}")
            return {"CAD": 0.0, "USD": 0.0}
    
    def get_available_funds(self) -> List[str]:
        """Get list of all available funds"""
        try:
            result = self.supabase.table("portfolio_positions").select("fund").execute()
            funds = list(set(row["fund"] for row in result.data))
            return sorted(funds)
        except Exception as e:
            logger.error(f"❌ Error getting available funds: {e}")
            return []
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Calculate and return performance metrics"""
        try:
            # Get current positions
            positions = self.get_current_positions()
            
            # Calculate metrics - use correct column names from latest_positions view
            total_value = sum(float(pos.get("market_value", 0) or 0) for pos in positions)
            total_cost_basis = sum(float(pos.get("cost_basis", 0) or 0) for pos in positions)
            unrealized_pnl = sum(float(pos.get("unrealized_pnl", 0) or 0) for pos in positions)
            performance_pct = (unrealized_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0
            
            # Get trade statistics
            trades = self.get_trade_log(limit=1000)
            total_trades = len(trades)
            winning_trades = len([t for t in trades if t["pnl"] > 0])
            losing_trades = len([t for t in trades if t["pnl"] < 0])
            
            return {
                "total_value": round(total_value, 2),
                "total_cost_basis": round(total_cost_basis, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "performance_pct": round(performance_pct, 2),
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades
            }
            
        except Exception as e:
            logger.error(f"❌ Error calculating performance metrics: {e}")
            return {
                "total_value": 0,
                "total_cost_basis": 0,
                "unrealized_pnl": 0,
                "performance_pct": 0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0
            }
    
    def get_daily_performance_data(self, days: int = 30, fund: Optional[str] = None) -> List[Dict]:
        """Get daily performance data for charting, optionally filtered by fund"""
        try:
            # Get performance metrics data
            query = self.supabase.table("performance_metrics").select(
                "date, total_value, cost_basis, unrealized_pnl, performance_pct, fund"
            ).gte("date", (datetime.now() - pd.Timedelta(days=days)).isoformat()).order("date")
            
            if fund:
                query = query.eq("fund", fund)
            
            result = query.execute()
            
            if not result.data:
                return []
            
            # Process performance metrics data - return as DataFrame-like structure
            df = pd.DataFrame(result.data)
            df["date"] = pd.to_datetime(df["date"])
            df["performance_index"] = df["performance_pct"] + 100
            
            # Return as list of dictionaries with the exact format the chart expects
            daily_data = []
            for _, row in df.iterrows():
                daily_data.append({
                    "date": row["date"].strftime('%Y-%m-%d'),  # Convert to string for JSON serialization
                    "performance_index": round(float(row["performance_index"]), 2),
                    "total_value": round(float(row["total_value"]), 2),
                    "cost_basis": round(float(row["cost_basis"]), 2),
                    "unrealized_pnl": round(float(row["unrealized_pnl"]), 2),
                    "performance_pct": round(float(row["performance_pct"]), 2)
                })
            
            return sorted(daily_data, key=lambda x: x["date"])
            
        except Exception as e:
            logger.error(f"❌ Error getting daily performance data: {e}")
            return []
    
    # =====================================================
    # EXCHANGE RATES METHODS
    # =====================================================
    
    def get_exchange_rate(self, date: datetime, from_currency: str = 'USD', to_currency: str = 'CAD') -> Optional[Decimal]:
        """Get exchange rate for a specific date.
        
        Returns the most recent rate on or before the target date.
        
        Args:
            date: Target date for the exchange rate
            from_currency: Source currency (default: 'USD')
            to_currency: Target currency (default: 'CAD')
            
        Returns:
            Exchange rate as Decimal, or None if not found
        """
        try:
            # Ensure date is timezone-aware
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            
            query = self.supabase.table("exchange_rates").select("rate").eq(
                "from_currency", from_currency
            ).eq("to_currency", to_currency).lte("timestamp", date.isoformat()).order(
                "timestamp", desc=True
            ).limit(1)
            
            result = query.execute()
            
            if result.data and len(result.data) > 0:
                return Decimal(str(result.data[0]['rate']))
            else:
                logger.debug(f"No exchange rate found for {from_currency}/{to_currency} on {date}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error getting exchange rate: {e}")
            return None
    
    def get_exchange_rates(self, start_date: datetime, end_date: datetime, 
                          from_currency: str = 'USD', to_currency: str = 'CAD') -> List[Dict]:
        """Get exchange rates for a date range.
        
        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            from_currency: Source currency (default: 'USD')
            to_currency: Target currency (default: 'CAD')
            
        Returns:
            List of dictionaries with 'timestamp' and 'rate' keys
        """
        try:
            # Ensure dates are timezone-aware
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            
            query = self.supabase.table("exchange_rates").select("timestamp, rate").eq(
                "from_currency", from_currency
            ).eq("to_currency", to_currency).gte(
                "timestamp", start_date.isoformat()
            ).lte("timestamp", end_date.isoformat()).order("timestamp")
            
            result = query.execute()
            
            return result.data if result.data else []
            
        except Exception as e:
            logger.error(f"❌ Error getting exchange rates: {e}")
            return []
    
    def get_latest_exchange_rate(self, from_currency: str = 'USD', to_currency: str = 'CAD') -> Optional[Decimal]:
        """Get the most recent exchange rate.
        
        Args:
            from_currency: Source currency (default: 'USD')
            to_currency: Target currency (default: 'CAD')
            
        Returns:
            Latest exchange rate as Decimal, or None if not found
        """
        try:
            query = self.supabase.table("exchange_rates").select("rate").eq(
                "from_currency", from_currency
            ).eq("to_currency", to_currency).order("timestamp", desc=True).limit(1)
            
            result = query.execute()
            
            if result.data and len(result.data) > 0:
                return Decimal(str(result.data[0]['rate']))
            else:
                logger.debug(f"No exchange rate found for {from_currency}/{to_currency}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error getting latest exchange rate: {e}")
            return None
    
    def upsert_exchange_rate(self, date: datetime, rate: Decimal, 
                            from_currency: str = 'USD', to_currency: str = 'CAD') -> bool:
        """Insert or update a single exchange rate.
        
        Args:
            date: Date for the exchange rate
            rate: Exchange rate value
            from_currency: Source currency (default: 'USD')
            to_currency: Target currency (default: 'CAD')
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Truncate to date only (midnight UTC) to ensure one rate per day
            date = date.replace(hour=0, minute=0, second=0, microsecond=0)
            
            rate_data = {
                'from_currency': from_currency,
                'to_currency': to_currency,
                'rate': float(rate),
                'timestamp': date.isoformat()
            }
            
            result = self.supabase.table("exchange_rates").upsert(
                rate_data,
                on_conflict="from_currency,to_currency,timestamp"
            ).execute()
            
            logger.info(f"✅ Upserted exchange rate: {from_currency}/{to_currency} = {rate} on {date.date()}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error upserting exchange rate: {e}")
            return False
    
    def upsert_exchange_rates(self, rates: List[Dict]) -> bool:
        """Bulk insert or update exchange rates.
        
        Args:
            rates: List of dictionaries with keys: 'timestamp', 'rate', 'from_currency', 'to_currency'
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not rates:
                return True
            
            # Ensure all timestamps are properly formatted
            formatted_rates = []
            for rate in rates:
                formatted_rate = rate.copy()
                
                # Ensure timestamp is ISO format and truncated to date only (midnight UTC)
                if isinstance(formatted_rate.get('timestamp'), datetime):
                    timestamp = formatted_rate['timestamp']
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                    # Truncate to midnight UTC
                    timestamp = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
                    formatted_rate['timestamp'] = timestamp.isoformat()
                elif isinstance(formatted_rate.get('timestamp'), str):
                    # If it's a string, try to parse and truncate
                    try:
                        dt = datetime.fromisoformat(formatted_rate['timestamp'].replace('Z', '+00:00'))
                        dt = dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
                        formatted_rate['timestamp'] = dt.isoformat()
                    except:
                        pass
                
                # Ensure rate is float
                if isinstance(formatted_rate.get('rate'), Decimal):
                    formatted_rate['rate'] = float(formatted_rate['rate'])
                
                formatted_rates.append(formatted_rate)
            
            result = self.supabase.table("exchange_rates").upsert(
                formatted_rates,
                on_conflict="from_currency,to_currency,timestamp"
            ).execute()
            
            logger.info(f"✅ Upserted {len(formatted_rates)} exchange rates")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error upserting exchange rates: {e}")
            return False
    
    # =====================================================
    # BENCHMARK DATA CACHING METHODS
    # =====================================================
    
    def get_benchmark_data(self, ticker: str, start_date: datetime, end_date: datetime) -> Optional[List[Dict]]:
        """Get benchmark data from cache.
        
        Args:
            ticker: Benchmark ticker symbol (e.g., '^GSPC', 'QQQ')
            start_date: Start date for data range
            end_date: End date for data range
            
        Returns:
            List of dictionaries with keys: date, open, high, low, close, volume
            Returns None if no data found in cache
        """
        try:
            # Ensure dates are timezone-aware
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            
            query = self.supabase.table("benchmark_data").select(
                "date, open, high, low, close, volume"
            ).eq("ticker", ticker).gte(
                "date", start_date.date().isoformat()
            ).lte(
                "date", end_date.date().isoformat()
            ).order("date")
            
            result = query.execute()
            
            if result.data and len(result.data) > 0:
                logger.debug(f"Cache hit: {len(result.data)} rows for {ticker}")
                return result.data
            else:
                logger.debug(f"Cache miss: No data for {ticker} in date range")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error getting benchmark data from cache: {e}")
            return None
    
    def cache_benchmark_data(self, ticker: str, data: List[Dict]) -> bool:
        """Insert benchmark data into cache (upsert on conflict).
        
        Args:
            ticker: Benchmark ticker symbol (e.g., '^GSPC', 'QQQ')
            data: List of dictionaries with keys: Date, Open, High, Low, Close, Volume
                 (follows yfinance naming conventions)
                 
        Returns:
            True if successful, False otherwise
        """
        try:
            if not data:
                return True
            
            # Convert yfinance format to our database format
            formatted_data = []
            for row in data:
                # Skip rows with missing Close price (required field)
                close_val = row.get('Close')
                if close_val is None or pd.isna(close_val) or close_val == 0:
                    logger.warning(f"Skipping row with invalid Close price for {ticker}: {close_val}")
                    continue
                
                # Handle both datetime and date objects
                date_val = row.get('Date')
                if date_val is None:
                    logger.warning(f"Skipping row with missing Date for {ticker}")
                    continue
                    
                if isinstance(date_val, datetime):
                    date_str = date_val.date().isoformat()
                elif hasattr(date_val, 'isoformat'):
                    date_str = date_val.isoformat()
                else:
                    date_str = str(date_val)
                
                try:
                    formatted_row = {
                        'ticker': ticker,
                        'date': date_str,
                        'close': float(close_val),
                    }
                    
                    # Add optional fields if available (with error handling)
                    if 'Open' in row and row['Open'] is not None:
                        try:
                            formatted_row['open'] = float(row['Open'])
                        except (ValueError, TypeError):
                            pass  # Skip invalid values
                    if 'High' in row and row['High'] is not None:
                        try:
                            formatted_row['high'] = float(row['High'])
                        except (ValueError, TypeError):
                            pass
                    if 'Low' in row and row['Low'] is not None:
                        try:
                            formatted_row['low'] = float(row['Low'])
                        except (ValueError, TypeError):
                            pass
                    if 'Volume' in row and row['Volume'] is not None:
                        try:
                            formatted_row['volume'] = int(row['Volume'])
                        except (ValueError, TypeError):
                            pass
                    
                    formatted_data.append(formatted_row)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error formatting row for {ticker}: {e}")
                    continue
            
            # Upsert into database
            result = self.supabase.table("benchmark_data").upsert(
                formatted_data,
                on_conflict="ticker,date"
            ).execute()
            
            logger.info(f"✅ Cached {len(formatted_data)} rows of benchmark data for {ticker}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error caching benchmark data: {e}")
            return False

    def delete_all_benchmark_data(self) -> bool:
        """Remove every row from ``benchmark_data`` (reconstructible via ``benchmark_refresh_job``).

        Does not touch any other table. PostgREST requires a filter; all realistic rows have
        ``date >= 1970-01-01``.
        """
        try:
            self.supabase.table("benchmark_data").delete().gte("date", "1970-01-01").execute()
            logger.info("Deleted all rows from benchmark_data")
            return True
        except Exception as e:
            logger.error("❌ Error deleting benchmark_data: %s", e)
            return False

    def delete_benchmark_futures_invalid_volume_in_range(
        self, ticker: str, range_start: date, range_end: date
    ) -> bool:
        """Remove *continuous* futures rows with NULL, non-positive, or below-floor volume.

        Deletes stale rows that sanitizer would skip on ingest so the next upsert can replace them.
        """
        if not str(ticker).endswith("=F"):
            return True
        from scheduler.benchmark_futures_quality import yahoo_futures_min_reported_volume

        start_s = range_start.isoformat()
        end_s = range_end.isoformat()
        min_v = yahoo_futures_min_reported_volume(ticker)
        try:
            self.supabase.table("benchmark_data").delete().eq("ticker", ticker).gte(
                "date", start_s
            ).lte("date", end_s).lte("volume", 0).execute()
            self.supabase.table("benchmark_data").delete().eq("ticker", ticker).gte(
                "date", start_s
            ).lte("date", end_s).is_("volume", "null").execute()
            if min_v is not None and min_v > 0:
                self.supabase.table("benchmark_data").delete().eq("ticker", ticker).gte(
                    "date", start_s
                ).lte("date", end_s).lt("volume", min_v).execute()
            return True
        except Exception as e:
            logger.error(
                "❌ Error deleting invalid-volume futures benchmark rows for %s: %s", ticker, e
            )
            return False
    
    def batch_update_securities(self, updates: List[Dict[str, Any]]) -> bool:
        """Batch update securities table with fundamentals data.
        
        Args:
            updates: List of dictionaries containing:
                - ticker (required): Stock ticker symbol
                - trailing_pe: P/E ratio
                - dividend_yield: Dividend yield as percent (e.g., 2.5 for 2.5%)
                - fifty_two_week_high: 52-week high price
                - fifty_two_week_low: 52-week low price
                - last_updated: ISO timestamp (defaults to now if not provided)
                
        Returns:
            True if successful, False otherwise
        """
        try:
            if not updates:
                return True
            
            # Ensure each update has last_updated timestamp
            formatted_updates = []
            for update in updates:
                formatted_update = update.copy()
                if 'last_updated' not in formatted_update:
                    formatted_update['last_updated'] = datetime.now(timezone.utc).isoformat()
                formatted_updates.append(formatted_update)
            
            # Batch upsert
            result = self.supabase.table("securities").upsert(
                formatted_updates,
                on_conflict="ticker"
            ).execute()
            
            logger.info(f"✅ Batch updated {len(formatted_updates)} securities with fundamentals")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error batch updating securities: {e}")
            return False
