#!/usr/bin/env python3
"""
Trade Entry
===========

Admin page for entering trades manually or via email parsing.
"""

import streamlit as st
import sys
import os
from pathlib import Path
import pandas as pd
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from auth_utils import is_authenticated, has_admin_access, can_modify_data, get_user_email, redirect_to_login
from streamlit_utils import get_supabase_client, display_dataframe_with_copy, render_sidebar_fund_selector
from supabase_client import SupabaseClient
from navigation import render_navigation

# Import shared utilities
from admin_utils import perf_timer, get_cached_fund_names

# Import log_handler to register PERF logging level
try:
    import log_handler  # noqa: F401 - Import to register PERF level
except ImportError:
    pass

# Performance logging setup
import logging
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(page_title="Trade Entry", page_icon="📈", layout="wide")

# Check authentication - redirect to main page if not logged in
if not is_authenticated():
    redirect_to_login("pages/admin_trade_entry.py")

# Refresh token if needed (auto-refresh before expiry)
from auth_utils import refresh_token_if_needed
if not refresh_token_if_needed():
    # Token refresh failed - session is invalid, redirect to login
    from auth_utils import logout_user
    logout_user(return_to="pages/admin_trade_entry.py")
    st.stop()

# Check admin access (allows both admin and readonly_admin)
if not has_admin_access():
    st.error("❌ Access Denied: Admin privileges required")
    st.info("Only administrators can access this page.")
    st.stop()

# Navigation
render_navigation(show_ai_assistant=True, show_settings=True)

# Standardized sidebar fund selector
with st.sidebar:
    st.markdown("---")
    st.header("📊 Fund Selection")
    global_selected_fund = render_sidebar_fund_selector()

# Header
st.markdown("# 📈 Trade Entry")
st.caption(f"Logged in as: {get_user_email()}")

client = get_supabase_client()
if not client:
    st.error("Failed to connect to database")
else:
    try:
        # Get available funds
        fund_names = get_cached_fund_names()
        
        if not fund_names:
            st.warning("No funds available. Create a fund first in Fund Management.")
        elif global_selected_fund is None:
            st.warning("Please select a fund from the sidebar.")
        else:
            # Trade form
            st.subheader("Enter Trade")
            
            # Use the fund from sidebar
            trade_fund = global_selected_fund
            
            # Display selected fund
            st.info(f"📊 Selected Fund: **{trade_fund}**")
            
            col1, col2 = st.columns(2)
            
            with col1:
                trade_action = st.selectbox("Action", options=["BUY", "SELL"], key="trade_action")
                trade_ticker = st.text_input("Ticker Symbol", placeholder="e.g., AAPL, MSFT", key="trade_ticker").upper()
            
            with col2:
                trade_shares = st.number_input("Shares", min_value=0.000001, value=1.0, step=1.0, format="%.6f", key="trade_shares")
                trade_price = st.number_input("Price ($)", min_value=0.01, value=100.0, step=0.01, format="%.2f", key="trade_price")
                trade_currency = st.selectbox("Currency", options=["USD", "CAD"], key="trade_currency")
            
            # Optional fields
            with st.expander("Additional Options", expanded=False):
                trade_reason = st.text_input("Reason/Notes", placeholder="e.g., Limit order filled", key="trade_reason")
                trade_date = st.date_input("Trade Date", value=datetime.now(), key="trade_date")
                trade_time = st.time_input("Trade Time", value=datetime.now().time(), key="trade_time")
            
            # Ticker validation
            if trade_ticker:
                ticker_check = client.supabase.table("securities").select("ticker, company_name, currency, sector, industry").eq("ticker", trade_ticker).execute()
                if ticker_check.data:
                    ticker_data = ticker_check.data[0]
                    company_name = ticker_data.get('company_name', trade_ticker)
                    currency = ticker_data.get('currency', 'USD')
                    sector = ticker_data.get('sector')
                    industry = ticker_data.get('industry')
                    
                    # Check if metadata is incomplete
                    is_incomplete = (
                        not company_name or 
                        company_name == trade_ticker or 
                        company_name == 'Unknown' or
                        (not sector and not industry)
                    )
                    
                    # Automatically try to fetch missing metadata if incomplete
                    if is_incomplete:
                        try:
                            admin_client = SupabaseClient(use_service_role=True)
                            admin_client.ensure_ticker_in_securities(trade_ticker, currency or trade_currency)
                            # Re-fetch to get updated data
                            ticker_check = client.supabase.table("securities").select("ticker, company_name, currency, sector, industry").eq("ticker", trade_ticker).execute()
                            if ticker_check.data:
                                ticker_data = ticker_check.data[0]
                                company_name = ticker_data.get('company_name', trade_ticker)
                                sector = ticker_data.get('sector')
                                industry = ticker_data.get('industry')
                                is_incomplete = (
                                    not company_name or 
                                    company_name == trade_ticker or 
                                    company_name == 'Unknown' or
                                    (not sector and not industry)
                                )
                        except Exception as fetch_error:
                            logger.warning(f"Could not auto-fetch metadata for {trade_ticker}: {fetch_error}")
                    
                    col_info, col_refresh = st.columns([3, 1])
                    with col_info:
                        if is_incomplete:
                            st.warning(f"⚠️ {company_name} ({currency}) - Metadata incomplete (missing sector/industry)")
                        else:
                            sector_industry = f" - {sector}" if sector else ""
                            if industry:
                                sector_industry += f" / {industry}"
                            st.success(f"✅ {company_name} ({currency}){sector_industry}")
                    
                    with col_refresh:
                        if st.button("🔄 Refresh", key="refresh_ticker_metadata", help="Refresh company name, sector, and industry from yfinance"):
                            try:
                                admin_client = SupabaseClient(use_service_role=True)
                                admin_client.ensure_ticker_in_securities(trade_ticker, currency or trade_currency)
                                st.success(f"✅ Refreshed metadata for {trade_ticker}")
                                st.cache_data.clear()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error refreshing metadata: {e}")
                else:
                    # Ticker doesn't exist - try to fetch metadata automatically
                    try:
                        admin_client = SupabaseClient(use_service_role=True)
                        admin_client.ensure_ticker_in_securities(trade_ticker, trade_currency)
                        # Re-check to see if it was added
                        ticker_check = client.supabase.table("securities").select("ticker, company_name, currency, sector, industry").eq("ticker", trade_ticker).execute()
                        if ticker_check.data:
                            ticker_data = ticker_check.data[0]
                            company_name = ticker_data.get('company_name', trade_ticker)
                            currency = ticker_data.get('currency', trade_currency)
                            sector = ticker_data.get('sector')
                            industry = ticker_data.get('industry')
                            
                            is_incomplete = (
                                not company_name or 
                                company_name == trade_ticker or 
                                company_name == 'Unknown' or
                                (not sector and not industry)
                            )
                            
                            if is_incomplete:
                                st.warning(f"⚠️ {company_name} ({currency}) - Metadata incomplete (missing sector/industry)")
                            else:
                                sector_industry = f" - {sector}" if sector else ""
                                if industry:
                                    sector_industry += f" / {industry}"
                                st.success(f"✅ {company_name} ({currency}){sector_industry}")
                        else:
                            st.warning(f"⚠️ Ticker '{trade_ticker}' not found. Will be added when trade is submitted.")
                    except Exception as fetch_error:
                        logger.warning(f"Could not auto-fetch metadata for {trade_ticker}: {fetch_error}")
                        st.warning(f"⚠️ Ticker '{trade_ticker}' not in securities table. Will be added when trade is submitted.")
            
            # Calculate totals
            total_value = trade_shares * trade_price
            st.info(f"💵 Total Value: ${total_value:,.2f} {trade_currency}")
            
            if st.button("📈 Submit Trade", type="primary", disabled=not can_modify_data()):
                if not can_modify_data():
                    st.error("❌ Read-only admin cannot submit trades")
                    st.stop()
                if not trade_ticker:
                    st.error("Please enter a ticker symbol")
                elif trade_shares <= 0:
                    st.error("Shares must be greater than 0")
                elif trade_price <= 0:
                    st.error("Price must be greater than 0")
                else:
                    try:
                        # Combine date and time
                        trade_datetime = datetime.combine(trade_date, trade_time)
                        
                        # Create service role client once for admin operations (bypasses RLS)
                        admin_client = SupabaseClient(use_service_role=True)
                        
                        # Ensure ticker exists in securities table with proper company name from yfinance
                        admin_client.ensure_ticker_in_securities(trade_ticker, trade_currency)
                        
                        # Calculate cost basis and P&L
                        cost_basis = trade_shares * trade_price
                        pnl = 0
                        
                        # Calculate P&L for SELL trades using FIFO
                        if trade_action == "SELL":
                            try:
                                from collections import deque
                                from decimal import Decimal
                                
                                # Get existing trades for this ticker (FIFO order)
                                existing_trades = client.supabase.table("trade_log") \
                                    .select("shares, price, reason") \
                                    .eq("fund", trade_fund) \
                                    .eq("ticker", trade_ticker) \
                                    .order("date") \
                                    .execute()
                                
                                # Build FIFO lot queue
                                lots = deque()
                                for t in (existing_trades.data or []):
                                    reason_upper = str(t.get('reason', '')).upper()
                                    is_buy = 'BUY' in reason_upper or ('SELL' not in reason_upper and 'sell' not in reason_upper.lower())
                                    is_sell = 'SELL' in reason_upper or 'sell' in reason_upper.lower() or 'limit sell' in reason_upper.lower() or 'market sell' in reason_upper.lower()
                                    
                                    if is_buy:
                                        lots.append((Decimal(str(t['shares'])), Decimal(str(t['price']))))
                                    elif is_sell:
                                        # Remove from lots (FIFO)
                                        remaining = Decimal(str(t['shares']))
                                        while remaining > 0 and lots:
                                            lot_shares, lot_price = lots[0]
                                            if lot_shares <= remaining:
                                                remaining -= lot_shares
                                                lots.popleft()
                                            else:
                                                lots[0] = (lot_shares - remaining, lot_price)
                                                remaining = Decimal('0')
                                
                                # Calculate P&L for this SELL
                                sell_shares = Decimal(str(trade_shares))
                                total_cost = Decimal('0')
                                remaining = sell_shares
                                
                                while remaining > 0 and lots:
                                    lot_shares, lot_price = lots[0]
                                    if lot_shares <= remaining:
                                        total_cost += lot_shares * lot_price
                                        remaining -= lot_shares
                                        lots.popleft()
                                    else:
                                        total_cost += remaining * lot_price
                                        lots[0] = (lot_shares - remaining, lot_price)
                                        remaining = Decimal('0')
                                
                                proceeds = Decimal(str(trade_shares * trade_price))
                                pnl = float(proceeds - total_cost)
                                
                            except Exception as calc_error:
                                logger.warning(f"Could not calculate P&L for SELL: {calc_error}")
                                pnl = 0
                        
                        # Build reason - ensure action is included for proper inference
                        if trade_reason:
                            reason_lower = trade_reason.lower()
                            has_buy = 'buy' in reason_lower
                            has_sell = 'sell' in reason_lower or 'limit sell' in reason_lower or 'market sell' in reason_lower
                            
                            if trade_action == "SELL" and not has_sell:
                                final_reason = f"{trade_reason} - SELL"
                            elif trade_action == "BUY" and not has_buy and not has_sell:
                                final_reason = f"{trade_reason} - BUY"
                            else:
                                final_reason = trade_reason
                        else:
                            final_reason = f"{trade_action} order"
                        
                        # Insert trade
                        trade_data = {
                            "fund": trade_fund,
                            "ticker": trade_ticker,
                            "shares": float(trade_shares),
                            "price": float(trade_price),
                            "cost_basis": float(cost_basis),
                            "pnl": float(pnl),
                            "reason": final_reason,
                            "currency": trade_currency,
                            "date": trade_datetime.isoformat()
                        }
                        
                        admin_client.supabase.table("trade_log").insert(trade_data).execute()
                        
                        # Now update portfolio positions using unified trade entry function
                        try:
                            from decimal import Decimal
                            from data.models.trade import Trade
                            from portfolio.trade_processor import TradeProcessor
                            from data.repositories.repository_factory import RepositoryFactory
                            
                            # Create Trade object from form data
                            trade = Trade(
                                ticker=trade_ticker,
                                action=trade_action,
                                shares=Decimal(str(trade_shares)),
                                price=Decimal(str(trade_price)),
                                timestamp=trade_datetime,
                                cost_basis=Decimal(str(cost_basis)),
                                pnl=Decimal(str(pnl)) if pnl else None,
                                reason=final_reason,
                                currency=trade_currency
                            )
                            
                            # Get fund data directory
                            try:
                                fund_info_result = admin_client.supabase.table("funds").select("data_directory").eq("name", trade_fund).execute()
                                if fund_info_result.data and len(fund_info_result.data) > 0:
                                    data_dir = fund_info_result.data[0].get('data_directory')
                                else:
                                    data_dir = f"trading_data/funds/{trade_fund}"
                            except Exception:
                                data_dir = f"trading_data/funds/{trade_fund}"
                            
                            # Create repository instance
                            try:
                                repository = RepositoryFactory.create_dual_write_repository(fund_name=trade_fund, data_directory=data_dir)
                            except Exception:
                                from data.repositories.supabase_repository import SupabaseRepository
                                repository = SupabaseRepository(trade_fund)
                            
                            # Process trade entry using unified function
                            processor = TradeProcessor(repository)
                            success = processor.process_trade_entry(trade, clear_caches=True, trade_already_saved=True)
                            
                            if not success:
                                st.warning("⚠️ Trade saved but position update may have failed. Please check holdings.")
                            
                        except Exception as process_error:
                            logger.error(f"Failed to update portfolio positions: {process_error}", exc_info=True)
                            st.warning(f"⚠️ Trade saved but position update failed: {str(process_error)[:100]}. Please run manual rebuild.")
                        
                        # DETECT BACKDATING AND TRIGGER REBUILD
                        is_backdated = trade_datetime.date() < datetime.now().date()
                        
                        if is_backdated:
                            try:
                                project_root = Path(__file__).parent.parent.parent
                                if str(project_root) not in sys.path:
                                    sys.path.insert(0, str(project_root))
                                
                                from web_dashboard.utils.background_rebuild import trigger_background_rebuild, find_running_rebuild_jobs
                                
                                had_running_job = len(find_running_rebuild_jobs(trade_fund)) > 0
                                
                                job_id = trigger_background_rebuild(trade_fund, trade_datetime.date())
                                
                                if job_id:
                                    if had_running_job:
                                        st.info(f"📊 Previous rebuild cancelled. Restarting from {trade_datetime.date()}... (Job ID: {job_id})")
                                    else:
                                        st.toast(f"⏳ Rebuilding positions from {trade_date}...", icon="📊")
                                        st.info(f"📊 Position recalculation started in background. Check the Jobs page to monitor progress (Job ID: {job_id})")
                                else:
                                    st.warning("⚠️ Could not trigger automatic rebuild. Please run manual rebuild from Fund Management tab.")
                                
                            except Exception as rebuild_error:
                                logger.error(f"Failed to trigger rebuild: {rebuild_error}")
                                st.warning(f"⚠️ Automatic rebuild failed: {str(rebuild_error)[:100]}. Please run manual rebuild.")
                        
                        # Show success message
                        st.success(f"✅ Trade recorded: {trade_action} {trade_shares} shares of {trade_ticker} @ ${trade_price}")
                        
                    except Exception as e:
                        st.error(f"Error recording trade: {e}")
            
            # Recent trades - filtered by fund and excluding DRIP
            st.divider()
            st.subheader("Recent Trades")
            
            # Initialize pagination state
            if 'recent_trades_page' not in st.session_state:
                st.session_state.recent_trades_page = 0
            if 'recent_trades_per_page' not in st.session_state:
                st.session_state.recent_trades_per_page = 20
            
            # Get total count (excluding DRIP) for pagination
            total_trades_result = client.supabase.table("trade_log")\
                .select("id", count="exact")\
                .eq("fund", trade_fund)\
                .neq("reason", "DRIP")\
                .execute()
            total_trades = total_trades_result.count if hasattr(total_trades_result, 'count') else 0
            
            # Calculate pagination
            total_pages = max(1, (total_trades + st.session_state.recent_trades_per_page - 1) // st.session_state.recent_trades_per_page)
            current_page = st.session_state.recent_trades_page
            offset = current_page * st.session_state.recent_trades_per_page
            
            # Fetch paginated trades (excluding DRIP, filtered by fund)
            recent_trades = client.supabase.table("trade_log")\
                .select("*")\
                .eq("fund", trade_fund)\
                .neq("reason", "DRIP")\
                .order("date", desc=True)\
                .range(offset, offset + st.session_state.recent_trades_per_page - 1)\
                .execute()
            
            if recent_trades.data:
                trades_df = pd.DataFrame(recent_trades.data)
                
                # Format date column for display
                if 'date' in trades_df.columns:
                    trades_df['date'] = pd.to_datetime(trades_df['date']).dt.strftime('%Y-%m-%d %H:%M')
                
                # Add action column for clarity
                def get_action_display(row):
                    reason = str(row.get('reason', '')).lower()
                    if 'sell' in reason or 'limit sell' in reason or 'market sell' in reason:
                        return 'SELL'
                    return 'BUY'
                
                trades_df['action'] = trades_df.apply(get_action_display, axis=1)
                
                display_cols = ["date", "action", "ticker", "shares", "price", "currency"]
                available_cols = [c for c in display_cols if c in trades_df.columns]
                
                # Format price column as currency
                display_trades_df = trades_df[available_cols].copy()
                if 'price' in display_trades_df.columns:
                    display_trades_df['price'] = display_trades_df['price'].apply(lambda x: f"${float(x):.2f}" if pd.notna(x) else "$0.00")
                
                display_dataframe_with_copy(display_trades_df, label="Recent Trades", key_suffix="admin_recent_trades", use_container_width=True)
                
                # Pagination controls
                if total_pages > 1:
                    col_page_info, col_page_prev, col_page_next, col_per_page = st.columns([2, 1, 1, 2])
                    
                    with col_page_info:
                        st.caption(f"Page {current_page + 1} of {total_pages} ({total_trades} total trades)")
                    
                    with col_page_prev:
                        if st.button("◀ Previous", disabled=(current_page == 0), key="prev_page"):
                            st.session_state.recent_trades_page = max(0, current_page - 1)
                            st.rerun()
                    
                    with col_page_next:
                        if st.button("Next ▶", disabled=(current_page >= total_pages - 1), key="next_page"):
                            st.session_state.recent_trades_page = min(total_pages - 1, current_page + 1)
                            st.rerun()
                    
                    with col_per_page:
                        per_page_options = [10, 20, 50, 100]
                        new_per_page = st.selectbox(
                            "Trades per page",
                            options=per_page_options,
                            index=per_page_options.index(st.session_state.recent_trades_per_page) if st.session_state.recent_trades_per_page in per_page_options else 1,
                            key="trades_per_page_select"
                        )
                        if new_per_page != st.session_state.recent_trades_per_page:
                            st.session_state.recent_trades_per_page = new_per_page
                            st.session_state.recent_trades_page = 0  # Reset to first page
                            st.rerun()
            else:
                st.info(f"No recent trades for {trade_fund} (excluding DRIP transactions)")
            
            # Email Trade Entry section
            st.divider()
            st.subheader("📧 Email Trade Entry")
            st.caption("Paste a trade confirmation email to auto-parse and add the trade")
            
            # Initialize session state for parsed trade
            if 'parsed_trade' not in st.session_state:
                st.session_state.parsed_trade = None
            
            email_fund = st.selectbox("Fund for Email Trade", options=fund_names, key="email_trade_fund")
            
            email_text = st.text_area(
                "Paste email content here",
                height=150,
                placeholder="""Your order has been filled
Symbol: AAPL
Type: Buy
Shares: 10
Average price: US$150.00
Total cost: $1,500.00
Time: December 19, 2025 09:30 EST""",
                key="email_trade_text"
            )
            
            col_parse, col_clear = st.columns([1, 1])
            
            with col_parse:
                if st.button("🔍 Parse Email", type="secondary"):
                    if not email_text.strip():
                        st.error("Please paste email content first")
                    else:
                        try:
                            project_root = Path(__file__).parent.parent.parent
                            if str(project_root) not in sys.path:
                                sys.path.insert(0, str(project_root))
                            
                            from utils.email_trade_parser import EmailTradeParser
                            
                            parser = EmailTradeParser()
                            trade = parser.parse_email_trade(email_text)
                            
                            if trade:
                                st.session_state.parsed_trade = trade
                                st.success("✅ Trade parsed successfully!")
                            else:
                                st.error("❌ Could not parse trade from email. Check the format and try again.")
                                st.session_state.parsed_trade = None
                                
                        except Exception as e:
                            st.error(f"Error parsing email: {e}")
                            st.session_state.parsed_trade = None
            
            with col_clear:
                if st.button("🗑️ Clear", type="secondary"):
                    st.session_state.parsed_trade = None
                    st.rerun()
            
            # Show parsed trade preview and save option
            if st.session_state.parsed_trade:
                trade = st.session_state.parsed_trade
                
                st.markdown("### 📋 Parsed Trade Preview")
                
                col_left, col_right = st.columns(2)
                
                with col_left:
                    st.write(f"**Ticker:** {trade.ticker}")
                    # Infer action from reason
                    reason_lower = (trade.reason or '').lower()
                    inferred_action = 'SELL' if ('sell' in reason_lower or 'limit sell' in reason_lower or 'market sell' in reason_lower) else 'BUY'
                    st.write(f"**Action:** {inferred_action}")
                    st.write(f"**Shares:** {trade.shares}")
                
                with col_right:
                    st.write(f"**Price:** ${trade.price}")
                    st.write(f"**Currency:** {trade.currency}")
                    st.write(f"**Total:** ${trade.cost_basis:.2f}")
                
                st.write(f"**Timestamp:** {trade.timestamp}")
                
                # Confirm and save button
                if st.button("✅ Confirm & Save Trade", type="primary", disabled=not can_modify_data()):
                    if not can_modify_data():
                        st.error("❌ Read-only admin cannot save trades")
                        st.stop()
                    try:
                        # Use the parsed trade to save (similar logic to manual trade entry above)
                        admin_client = SupabaseClient(use_service_role=True)
                        admin_client.ensure_ticker_in_securities(trade.ticker, trade.currency)
                        
                        # Insert the trade
                        trade_data = {
                            "fund": email_fund,
                            "ticker": trade.ticker,
                            "shares": float(trade.shares),
                            "price": float(trade.price),
                            "cost_basis": float(trade.cost_basis),
                            "pnl": float(trade.pnl) if trade.pnl else 0,
                            "reason": trade.reason or f"EMAIL TRADE - {inferred_action}",
                            "currency": trade.currency,
                            "date": trade.timestamp.isoformat()
                        }
                        
                        admin_client.supabase.table("trade_log").insert(trade_data).execute()
                        
                        # Update portfolio positions
                        try:
                            from decimal import Decimal
                            from data.models.trade import Trade as TradeModel
                            from portfolio.trade_processor import TradeProcessor
                            from data.repositories.repository_factory import RepositoryFactory
                            
                            trade_obj = TradeModel(
                                ticker=trade.ticker,
                                action=inferred_action,
                                shares=Decimal(str(trade.shares)),
                                price=Decimal(str(trade.price)),
                                timestamp=trade.timestamp,
                                cost_basis=Decimal(str(trade.cost_basis)),
                                pnl=Decimal(str(trade.pnl)) if trade.pnl else None,
                                reason=trade.reason or f"EMAIL TRADE - {inferred_action}",
                                currency=trade.currency
                            )
                            
                            data_dir = f"trading_data/funds/{email_fund}"
                            try:
                                repository = RepositoryFactory.create_dual_write_repository(fund_name=email_fund, data_directory=data_dir)
                            except Exception:
                                from data.repositories.supabase_repository import SupabaseRepository
                                repository = SupabaseRepository(email_fund)
                            
                            processor = TradeProcessor(repository)
                            processor.process_trade_entry(trade_obj, clear_caches=True, trade_already_saved=True)
                            
                        except Exception as process_error:
                            logger.error(f"Failed to update portfolio positions: {process_error}", exc_info=True)
                            st.warning(f"⚠️ Trade saved but position update failed: {str(process_error)[:100]}. Please run manual rebuild.")
                        
                        st.toast(f"✅ Trade saved: {inferred_action} {trade.shares} {trade.ticker} @ ${trade.price}", icon="✅")
                        st.session_state.parsed_trade = None
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"Error saving trade: {e}")
                    
    except Exception as e:
        st.error(f"Error loading trade entry: {e}")

