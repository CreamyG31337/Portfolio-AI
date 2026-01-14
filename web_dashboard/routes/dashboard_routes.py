
from flask import Blueprint, jsonify, request, render_template, redirect, url_for, Response
import logging
import time
import pandas as pd
from datetime import datetime, timezone
import json

from auth import require_auth
from flask_auth_utils import get_user_email_flask
from user_preferences import get_user_theme, get_user_currency, get_user_selected_fund, get_user_preference
from flask_data_utils import fetch_dividend_log_flask
from chart_utils import create_currency_exposure_chart
from streamlit_utils import (
    get_current_positions,
    get_trade_log,
    get_cash_balances,
    calculate_portfolio_value_over_time,
    get_user_investment_metrics,
    get_fund_thesis_data,
    fetch_latest_rates_bulk,
    get_investor_count,
    get_biggest_movers,
    get_first_trade_dates
)

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/v2/dashboard')
@require_auth
def dashboard_page():
    """Render the main dashboard page"""
    try:
        # Lazy import to avoid circular dependency
        from app import get_navigation_context
        
        # Check V2 Preference
        v2_enabled = get_user_preference('v2_enabled', default=False)
        if not v2_enabled:
            # If V2 is disabled, redirect to Streamlit (root)
            return redirect('/')
            
        user_email = get_user_email_flask()
        user_theme = get_user_theme() or 'system'
        
        # Determine initial fund
        selected_fund = get_user_selected_fund()
        
        # Navigation context
        nav_context = get_navigation_context(current_page='dashboard')
        
        return render_template('dashboard.html',
                             user_email=user_email,
                             user_theme=user_theme,
                             initial_fund=selected_fund,
                             **nav_context)
    except Exception as e:
        logger.error(f"Error rendering dashboard: {e}", exc_info=True)
        # Fallback with minimal context
        try:
            from app import get_navigation_context
            nav_context = get_navigation_context(current_page='dashboard')
        except Exception:
            # If navigation context also fails, use minimal fallback
            nav_context = {}
        return render_template('dashboard.html', 
                             user_email='User',
                             user_theme='system',
                             initial_fund=None,
                             **nav_context)

@dashboard_bp.route('/api/dashboard/latest-timestamp', methods=['GET'])
@require_auth
def get_latest_timestamp():
    """Get the latest timestamp from portfolio_positions (same as Streamlit)"""
    fund = request.args.get('fund')
    if not fund or fund.lower() == 'all':
        fund = None
    
    try:
        from streamlit_utils import get_supabase_client
        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Database client unavailable"}), 500
        
        # Query latest date from portfolio_positions (same as Streamlit)
        query = client.supabase.table("portfolio_positions").select("date")
        if fund:
            query = query.eq("fund", fund)
        
        result = query.order("date", desc=True).limit(1).execute()
        
        if result.data and result.data[0].get('date'):
            from dateutil import parser
            max_date = result.data[0]['date']
            
            # Parse and convert to datetime (same logic as Streamlit)
            if isinstance(max_date, str):
                latest_timestamp = parser.parse(max_date)
            elif hasattr(max_date, 'to_pydatetime'):
                latest_timestamp = max_date.to_pydatetime()
            elif isinstance(max_date, pd.Timestamp):
                latest_timestamp = max_date.to_pydatetime()
            else:
                latest_timestamp = max_date
            
            # Ensure timezone-aware (UTC)
            if latest_timestamp.tzinfo is None:
                latest_timestamp = latest_timestamp.replace(tzinfo=timezone.utc)
            
            return jsonify({
                "timestamp": latest_timestamp.isoformat(),
                "formatted": latest_timestamp.strftime("%Y-%m-%d %I:%M:%S %p")
            })
        else:
            return jsonify({"error": "No data found"}), 404
    except Exception as e:
        logger.error(f"Error fetching latest timestamp: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route('/api/dashboard/summary', methods=['GET'])
@require_auth
def get_dashboard_summary():
    """Get top-level dashboard metrics"""
    fund = request.args.get('fund')
    # Convert 'all' or empty string to None for aggregate view
    if not fund or fund.lower() == 'all':
        fund = None
        
    display_currency = get_user_currency() or 'CAD'
    
    logger.info(f"[Dashboard API] /api/dashboard/summary called - fund={fund}, currency={display_currency}")
    start_time = time.time()
    
    try:
        # Fetch Data
        logger.debug(f"[Dashboard API] Fetching positions for fund={fund}")
        positions_df = get_current_positions(fund)
        logger.debug(f"[Dashboard API] Positions fetched: {len(positions_df)} rows")
        
        logger.debug(f"[Dashboard API] Fetching cash balances for fund={fund}")
        cash_balances = get_cash_balances(fund)
        logger.debug(f"[Dashboard API] Cash balances: {cash_balances}")
        
        # Calculate Rates
        all_currencies = set()
        if not positions_df.empty:
            all_currencies.update(positions_df['currency'].fillna('CAD').astype(str).str.upper().unique().tolist())
        all_currencies.update([str(c).upper() for c in cash_balances.keys()])
        
        logger.debug(f"[Dashboard API] Currencies found: {all_currencies}")
        rate_map = fetch_latest_rates_bulk(list(all_currencies), display_currency)
        logger.debug(f"[Dashboard API] Exchange rates fetched: {len(rate_map)} rates")
        def get_rate(curr): return rate_map.get(str(curr).upper(), 1.0)
        
        # Metrics Calculation
        portfolio_value_no_cash = 0.0
        total_pnl = 0.0
        day_pnl = 0.0
        
        if not positions_df.empty:
            rates = positions_df['currency'].fillna('CAD').astype(str).str.upper().map(get_rate)
            portfolio_value_no_cash = (positions_df['market_value'].fillna(0) * rates).sum()
            total_pnl = (positions_df['unrealized_pnl'].fillna(0) * rates).sum()
            
            if 'daily_pnl' in positions_df.columns:
                 day_pnl = (positions_df['daily_pnl'].fillna(0) * rates).sum()
        
        # Cash
        total_cash = 0.0
        for curr, amount in cash_balances.items():
            if amount > 0:
                total_cash += amount * get_rate(curr)
                
        total_value = portfolio_value_no_cash + total_cash
        
        # Percentages
        day_pnl_pct = 0.0
        if (total_value - day_pnl) > 0:
            day_pnl_pct = (day_pnl / (total_value - day_pnl)) * 100
            
        unrealized_pnl_pct = 0.0
        cost_basis = portfolio_value_no_cash - total_pnl
        if cost_basis > 0:
            unrealized_pnl_pct = (total_pnl / cost_basis) * 100
            
        # Thesis Data
        logger.debug(f"[Dashboard API] Fetching thesis data for fund={fund}")
        thesis = get_fund_thesis_data(fund) if fund else None
        logger.debug(f"[Dashboard API] Thesis data: {'found' if thesis else 'not found'}")
        
        # Investor & Holdings Count
        investor_count = get_investor_count(fund)
        holdings_count = len(positions_df) if not positions_df.empty else 0
        
        # Calculate Exchange Rates for Display
        # fetch_latest_rates_bulk returns rate FROM key TO display_currency
        # If display_currency is CAD:
        # USD -> CAD rate is in rate_map['USD'] (e.g. 1.40)
        # CAD -> USD rate is 1 / rate_map['USD'] (e.g. 0.71)
        # If display_currency is USD:
        # CAD -> USD rate is in rate_map['CAD'] (e.g. 0.71)
        # USD -> CAD rate is 1 / rate_map['CAD'] (e.g. 1.40)
        
        usd_cad_rate = 1.0
        cad_usd_rate = 1.0
        
        if display_currency == 'CAD':
            usd_cad_rate = rate_map.get('USD', 1.0)
            if usd_cad_rate > 0:
                cad_usd_rate = 1.0 / usd_cad_rate
        elif display_currency == 'USD':
            cad_usd_rate = rate_map.get('CAD', 1.0)
            if cad_usd_rate > 0:
                usd_cad_rate = 1.0 / cad_usd_rate
        
        exchange_rates = {
            "USD_CAD": usd_cad_rate,
            "CAD_USD": cad_usd_rate
        }
        
        processing_time = time.time() - start_time
        response = {
            "total_value": total_value,
            "cash_balance": total_cash,
            "day_change": day_pnl,
            "day_change_pct": day_pnl_pct,
            "unrealized_pnl": total_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "display_currency": display_currency,
            "thesis": thesis,
            "investor_count": investor_count,
            "holdings_count": holdings_count,
            "exchange_rates": exchange_rates,
            "from_cache": False,
            "processing_time": processing_time
        }
        
        logger.info(f"[Dashboard API] Summary calculated successfully - total_value={total_value:.2f} {display_currency}, processing_time={processing_time:.3f}s")
        return jsonify(response)
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error calculating dashboard summary (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500

@dashboard_bp.route('/api/dashboard/charts/performance', methods=['GET'])
def get_performance_chart():
    """Get portfolio performance chart as Plotly JSON.
    
    GET /api/dashboard/charts/performance
    
    Query Parameters:
        fund (str): Fund name (optional)
        range (str): Time range - '1M', '3M', '6M', '1Y', or 'ALL' (default: 'ALL')
        use_solid (str): 'true' to use solid lines for benchmarks (default: 'false')
        theme (str): Chart theme - 'dark', 'light', 'midnight-tokyo', 'abyss' (optional)
        
    Returns:
        JSON response with Plotly chart data:
            - data: Array of trace objects
            - layout: Layout configuration
            
    Error Responses:
        500: Server error during data fetch
    """
    import plotly.utils
    from chart_utils import create_portfolio_value_chart
    
    fund = request.args.get('fund') or None
    # Convert empty string to None
    if fund == '':
        fund = None
    time_range = request.args.get('range', 'ALL') # '1M', '3M', '6M', '1Y', 'ALL'
    use_solid = request.args.get('use_solid', 'false').lower() == 'true'
    display_currency = get_user_currency() or 'CAD'
    
    logger.info(f"[Dashboard API] /api/dashboard/charts/performance called - fund={fund}, range={time_range}, currency={display_currency}")
    start_time = time.time()
    
    try:
        # Translate 'All' or empty to None for the backend
        if not fund or fund.lower() == 'all':
            fund = None
            
        from flask_data_utils import calculate_portfolio_value_over_time_flask as calculate_portfolio_value_over_time
        
        days_map = {
            '1M': 30,
            '3M': 90,
            '6M': 180,
            '1Y': 365,
            'ALL': None
        }
        days = days_map.get(time_range)
        logger.debug(f"[Dashboard API] Calculating portfolio value over time - days={days}, fund={fund}")
        
        df = calculate_portfolio_value_over_time(fund, days=days, display_currency=display_currency)
        logger.debug(f"[Dashboard API] Portfolio value data fetched: {len(df)} rows")
        
        # DEBUG: Log performance_index values to diagnose the 0,1,2,3... issue
        if not df.empty and 'performance_index' in df.columns:
            first_10_idx = df['performance_index'].head(10).tolist()
            last_10_idx = df['performance_index'].tail(10).tolist()
            logger.info(f"[DEBUG] Performance Index BEFORE chart creation - First 10: {first_10_idx}, Last 10: {last_10_idx}, Min: {df['performance_index'].min():.2f}, Max: {df['performance_index'].max():.2f}")
            if 'cost_basis' in df.columns:
                first_investment = df[df['cost_basis'] > 0]
                if not first_investment.empty:
                    logger.info(f"[DEBUG] First investment day: {first_investment.iloc[0]['date']}, cost_basis: {first_investment.iloc[0]['cost_basis']}, performance_index: {first_investment.iloc[0]['performance_index']}")
        
        if df.empty:
            logger.warning(f"[Dashboard API] No portfolio value data found for fund={fund}, range={time_range}")
            # Return empty Plotly chart
            import plotly.graph_objs as go
            fig = go.Figure()
            fig.add_annotation(
                text="No data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
            from plotly_utils import serialize_plotly_figure
            return Response(
                serialize_plotly_figure(fig),
                mimetype='application/json'
            )
        
        # All benchmarks are now passed to the chart (S&P 500 visible, others in legend)
        all_benchmarks = ['sp500', 'qqq', 'russell2000', 'vti']
        
        # Create Plotly chart using shared function (same as Streamlit)
        fig = create_portfolio_value_chart(
            df,
            fund_name=fund,
            show_normalized=True,  # Show percentage change from baseline
            show_benchmarks=all_benchmarks,  # All benchmarks (S&P 500 visible, others in legend)
            show_weekend_shading=True,
            use_solid_lines=use_solid,
            display_currency=display_currency
        )
        
        # DEBUG: Log the actual y-values being sent to the chart
        if fig.data and len(fig.data) > 0:
            portfolio_trace = fig.data[0]  # First trace is usually the portfolio
            if hasattr(portfolio_trace, 'y') and portfolio_trace.y is not None:
                y_values = list(portfolio_trace.y)[:20] if len(portfolio_trace.y) > 20 else list(portfolio_trace.y)
                logger.info(f"[DEBUG] Chart y-values (first 20): {y_values}, Total points: {len(portfolio_trace.y)}")
        
        # Apply theme to chart (similar to ticker chart)
        client_theme = request.args.get('theme', '').strip().lower()
        if not client_theme or client_theme not in ['dark', 'light', 'midnight-tokyo', 'abyss']:
            # Get user theme preference from backend
            user_theme = get_user_theme() or 'system'
            theme = user_theme if user_theme in ['dark', 'light', 'midnight-tokyo', 'abyss'] else 'light'
        else:
            theme = client_theme
        
        # Apply theme to chart data (convert to dict, apply theme, return as JSON)
        from chart_utils import get_chart_theme_config
        from plotly_utils import serialize_plotly_figure
        
        # Serialize figure with numpy array conversion
        chart_json = serialize_plotly_figure(fig)
        chart_data = json.loads(chart_json)
        
        # DEBUG: Log the y-values in the JSON being sent to frontend
        if 'data' in chart_data and len(chart_data['data']) > 0:
            portfolio_data = chart_data['data'][0]
            if 'y' in portfolio_data:
                y_values_json = portfolio_data['y'][:20] if len(portfolio_data['y']) > 20 else portfolio_data['y']
                logger.info(f"[DEBUG] JSON y-values being sent to frontend (first 20): {y_values_json}")
        
        theme_config = get_chart_theme_config(theme)
        
        # Update layout for theme
        if 'layout' in chart_data:
            chart_data['layout']['template'] = theme_config['template']
            chart_data['layout']['paper_bgcolor'] = theme_config['paper_bgcolor']
            chart_data['layout']['plot_bgcolor'] = theme_config['plot_bgcolor']
            chart_data['layout']['font'] = {'color': theme_config['font_color']}
            
            # Update grid colors for both axes if they exist
            if 'xaxis' in chart_data['layout']:
                chart_data['layout']['xaxis']['gridcolor'] = theme_config['grid_color']
                chart_data['layout']['xaxis']['zerolinecolor'] = theme_config['grid_color']
            if 'yaxis' in chart_data['layout']:
                chart_data['layout']['yaxis']['gridcolor'] = theme_config['grid_color']
                chart_data['layout']['yaxis']['zerolinecolor'] = theme_config['grid_color']
            
            # Update legend background if it exists
            if 'legend' in chart_data['layout']:
                chart_data['layout']['legend']['bgcolor'] = theme_config['legend_bg_color']
            
            # Update shapes (baseline line and weekend shading)
            if 'shapes' in chart_data['layout']:
                for shape in chart_data['layout']['shapes']:
                    if shape.get('type') == 'line' and shape.get('y0') == shape.get('y1'):
                        # This is the baseline hline
                        if 'line' in shape:
                            shape['line']['color'] = theme_config['baseline_line_color']
                    elif shape.get('type') == 'rect' and 'fillcolor' in shape:
                        # This is weekend shading
                        shape['fillcolor'] = theme_config['weekend_shading_color']
        
        processing_time = time.time() - start_time
        logger.info(f"[Dashboard API] Performance chart created - {len(df)} data points, use_solid={use_solid}, theme={theme}, processing_time={processing_time:.3f}s")
        
        # Return Plotly JSON with theme applied
        return Response(
            json.dumps(chart_data),
            mimetype='application/json'
        )
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error fetching performance chart (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500


@dashboard_bp.route('/api/dashboard/charts/individual-holdings', methods=['GET'])
def get_individual_holdings_chart():
    """Get individual stock performance chart as Plotly JSON.
    
    GET /api/dashboard/charts/individual-holdings
    
    Query Parameters:
        fund (str): Fund name (required)
        days (int): Number of days - 7, 30, or 0 for all (default: 7)
        filter (str): Stock filter - 'all', 'winners', 'losers', 'top5', 'bottom5', 'cad', 'usd' (default: 'all')
        use_solid (str): 'true' to use solid lines for benchmarks (default: 'false')
        theme (str): Chart theme - 'dark', 'light', 'midnight-tokyo', 'abyss' (optional)
        
    Returns:
        JSON response with Plotly chart data and metadata
            
    Error Responses:
        400: Fund is required
        500: Server error during data fetch
    """
    import plotly.utils
    from chart_utils import create_individual_holdings_chart, get_chart_theme_config
    from flask_data_utils import get_individual_holdings_performance_flask
    from plotly_utils import serialize_plotly_figure
    
    fund = request.args.get('fund')
    if not fund or fund.lower() == 'all':
        return jsonify({"error": "Fund name is required for individual holdings chart"}), 400
    
    days = int(request.args.get('days', '7'))
    stock_filter = request.args.get('filter', 'all')
    use_solid = request.args.get('use_solid', 'false').lower() == 'true'
    client_theme = request.args.get('theme', '').strip().lower()
    
    logger.info(f"[Dashboard API] /api/dashboard/charts/individual-holdings called - fund={fund}, days={days}, filter={stock_filter}")
    start_time = time.time()
    
    try:
        # Get holdings data
        holdings_df = get_individual_holdings_performance_flask(fund, days=days)
        
        if holdings_df.empty:
            logger.warning(f"[Dashboard API] No individual holdings data found for fund={fund}, days={days}")
            import plotly.graph_objs as go
            fig = go.Figure()
            fig.add_annotation(
                text="No holdings data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
            return Response(
                serialize_plotly_figure(fig),
                mimetype='application/json'
            )
        
        # Apply stock filter
        if stock_filter != 'all' and not holdings_df.empty:
            latest_per_ticker = holdings_df.sort_values('date').groupby('ticker').last().reset_index()
            tickers_to_show = latest_per_ticker['ticker'].tolist()
            
            if stock_filter == 'winners':
                if 'return_pct' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['return_pct'].fillna(0) > 0]['ticker'].tolist()
            elif stock_filter == 'losers':
                if 'return_pct' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['return_pct'].fillna(0) < 0]['ticker'].tolist()
            elif stock_filter == 'daily_winners':
                if 'daily_pnl_pct' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['daily_pnl_pct'].fillna(0) > 0]['ticker'].tolist()
            elif stock_filter == 'daily_losers':
                if 'daily_pnl_pct' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['daily_pnl_pct'].fillna(0) < 0]['ticker'].tolist()
            elif stock_filter == 'top5':
                if 'return_pct' in latest_per_ticker.columns:
                    top_5 = latest_per_ticker.nlargest(5, 'return_pct')
                    tickers_to_show = top_5['ticker'].tolist()
            elif stock_filter == 'bottom5':
                if 'return_pct' in latest_per_ticker.columns:
                    bottom_5 = latest_per_ticker.nsmallest(5, 'return_pct')
                    tickers_to_show = bottom_5['ticker'].tolist()
            elif stock_filter == 'cad':
                if 'currency' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['currency'] == 'CAD']['ticker'].tolist()
            elif stock_filter == 'usd':
                if 'currency' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['currency'] == 'USD']['ticker'].tolist()
            elif stock_filter.startswith('sector:'):
                sector_name = stock_filter.replace('sector:', '')
                if 'sector' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['sector'] == sector_name]['ticker'].tolist()
            elif stock_filter.startswith('industry:'):
                industry_name = stock_filter.replace('industry:', '')
                if 'industry' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['industry'] == industry_name]['ticker'].tolist()
            
            holdings_df = holdings_df[holdings_df['ticker'].isin(tickers_to_show)].copy()
        
        # All benchmarks (S&P 500 visible, others in legend)
        all_benchmarks = ['sp500', 'qqq', 'russell2000', 'vti']
        
        # Create chart
        fig = create_individual_holdings_chart(
            holdings_df,
            fund_name=fund,
            show_benchmarks=all_benchmarks,
            show_weekend_shading=True,
            use_solid_lines=use_solid
        )
        
        # Apply theme
        if not client_theme or client_theme not in ['dark', 'light', 'midnight-tokyo', 'abyss']:
            user_theme = get_user_theme() or 'system'
            theme = user_theme if user_theme in ['dark', 'light', 'midnight-tokyo', 'abyss'] else 'light'
        else:
            theme = client_theme
        
        chart_json = serialize_plotly_figure(fig)
        chart_data = json.loads(chart_json)
        
        theme_config = get_chart_theme_config(theme)
        
        # Update layout for theme
        if 'layout' in chart_data:
            chart_data['layout']['template'] = theme_config['template']
            chart_data['layout']['paper_bgcolor'] = theme_config['paper_bgcolor']
            chart_data['layout']['plot_bgcolor'] = theme_config['plot_bgcolor']
            chart_data['layout']['font'] = {'color': theme_config['font_color']}
            
            if 'xaxis' in chart_data['layout']:
                chart_data['layout']['xaxis']['gridcolor'] = theme_config['grid_color']
            if 'yaxis' in chart_data['layout']:
                chart_data['layout']['yaxis']['gridcolor'] = theme_config['grid_color']
            if 'legend' in chart_data['layout']:
                chart_data['layout']['legend']['bgcolor'] = theme_config['legend_bg_color']
        
        # Get metadata for filter dropdowns
        sectors = sorted([s for s in holdings_df['sector'].dropna().unique() if s]) if 'sector' in holdings_df.columns else []
        industries = sorted([i for i in holdings_df['industry'].dropna().unique() if i]) if 'industry' in holdings_df.columns else []
        num_stocks = holdings_df['ticker'].nunique()
        
        processing_time = time.time() - start_time
        logger.info(f"[Dashboard API] Individual holdings chart created - {num_stocks} stocks, processing_time={processing_time:.3f}s")
        
        # Return chart data with metadata
        response_data = {
            **chart_data,
            'metadata': {
                'num_stocks': num_stocks,
                'sectors': sectors,
                'industries': industries,
                'days': days,
                'filter': stock_filter
            }
        }
        
        return Response(
            json.dumps(response_data),
            mimetype='application/json'
        )
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error fetching individual holdings chart (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500


@dashboard_bp.route('/api/dashboard/charts/allocation', methods=['GET'])
def get_allocation_charts():
    """Get allocation chart as Plotly JSON (Sector pie chart).
    
    GET /api/dashboard/charts/allocation
    
    Query Parameters:
        fund (str): Fund name (optional)
        theme (str): Chart theme - 'dark', 'light', 'midnight-tokyo', 'abyss' (optional)
        
    Returns:
        JSON response with Plotly chart data:
            - data: Array of trace objects (pie chart)
            - layout: Layout configuration
            
    Error Responses:
        500: Server error during data fetch
    """
    import plotly.utils
    from chart_utils import create_sector_allocation_chart
    from user_preferences import get_user_theme
    
    fund = request.args.get('fund')
    # Convert 'all' or empty string to None for aggregate view
    if not fund or fund.lower() == 'all':
        fund = None
    
    client_theme = request.args.get('theme', '').strip().lower()
    display_currency = get_user_currency() or 'CAD'
    
    logger.info(f"[Dashboard API] /api/dashboard/charts/allocation called - fund={fund}, currency={display_currency}")
    start_time = time.time()
    
    try:
        logger.debug(f"[Dashboard API] Fetching positions for allocation chart")
        positions_df = get_current_positions(fund)
        logger.debug(f"[Dashboard API] Positions fetched: {len(positions_df)} rows")
        
        # Debug: Log sample of market_value data
        if not positions_df.empty and 'market_value' in positions_df.columns:
            sample_values = positions_df['market_value'].head(10).tolist()
            total_market_value = positions_df['market_value'].sum()
            logger.info(f"[Dashboard API] Sample market_value values: {sample_values}")
            logger.info(f"[Dashboard API] Total market_value: {total_market_value}")
            logger.info(f"[Dashboard API] Market_value column type: {positions_df['market_value'].dtype}")
            logger.info(f"[Dashboard API] Market_value null count: {positions_df['market_value'].isna().sum()}")
        
        if positions_df.empty:
            logger.warning(f"[Dashboard API] No positions found for allocation chart - fund={fund}")
            # Return empty Plotly chart
            import plotly.graph_objs as go
            fig = go.Figure()
            fig.add_annotation(
                text="No data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
            from plotly_utils import serialize_plotly_figure
            return Response(
                serialize_plotly_figure(fig),
                mimetype='application/json'
            )
        
        # Create Plotly pie chart using shared function (same as Streamlit)
        # Pass display_currency to ensure all values are converted before aggregation
        fig = create_sector_allocation_chart(positions_df, fund_name=fund, display_currency=display_currency)
        
        # Update height to match container (700px) and increase bottom margin for legend
        fig.update_layout(
            height=700,
            margin=dict(l=20, r=20, t=50, b=100)  # Increased bottom margin for legend
        )
        
        # Apply theme to chart (similar to ticker chart)
        if not client_theme or client_theme not in ['dark', 'light', 'midnight-tokyo', 'abyss']:
            # Get user theme preference from backend
            from user_preferences import get_user_theme
            user_theme = get_user_theme() or 'system'
            theme = user_theme if user_theme in ['dark', 'light', 'midnight-tokyo', 'abyss'] else 'light'
        else:
            theme = client_theme
        
        # Apply theme to chart data (convert to dict, apply theme, return as JSON)
        from chart_utils import get_chart_theme_config
        from plotly_utils import serialize_plotly_figure
        
        # Serialize figure with numpy array conversion
        chart_json = serialize_plotly_figure(fig)
        chart_data = json.loads(chart_json)
        theme_config = get_chart_theme_config(theme)
        
        # Update layout for theme
        if 'layout' in chart_data:
            chart_data['layout']['template'] = theme_config['template']
            chart_data['layout']['paper_bgcolor'] = theme_config['paper_bgcolor']
            chart_data['layout']['plot_bgcolor'] = theme_config['plot_bgcolor']
            chart_data['layout']['font'] = {'color': theme_config['font_color']}
            
            # Update legend background if it exists
            if 'legend' in chart_data['layout']:
                chart_data['layout']['legend']['bgcolor'] = theme_config['legend_bg_color']
        
        processing_time = time.time() - start_time
        logger.info(f"[Dashboard API] Sector allocation chart created - theme={theme}, processing_time={processing_time:.3f}s")
        
        # Return Plotly JSON with theme applied
        return Response(
            json.dumps(chart_data),
            mimetype='application/json'
        )
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error fetching allocation charts (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500

@dashboard_bp.route('/api/dashboard/charts/pnl', methods=['GET'])
@require_auth
def get_pnl_chart():
    """Get P&L by Position chart as Plotly JSON.
    
    GET /api/dashboard/charts/pnl
    
    Query Parameters:
        fund (str): Fund name (optional)
        theme (str): Chart theme - 'dark', 'light', 'midnight-tokyo', 'abyss' (optional)
        
    Returns:
        JSON response with Plotly chart data:
            - data: Array of trace objects (bar chart)
            - layout: Layout configuration
            
    Error Responses:
        500: Server error during data fetch
    """
    from chart_utils import create_pnl_chart, get_chart_theme_config
    from plotly_utils import serialize_plotly_figure
    from flask_data_utils import fetch_dividend_log_flask
    
    fund = request.args.get('fund')
    # Convert 'all' or empty string to None for aggregate view
    if not fund or fund.lower() == 'all':
        fund = None
    
    client_theme = request.args.get('theme', '').strip().lower()
    display_currency = get_user_currency() or 'CAD'
    
    logger.info(f"[Dashboard API] /api/dashboard/charts/pnl called - fund={fund}, currency={display_currency}")
    start_time = time.time()
    
    try:
        logger.debug(f"[Dashboard API] Fetching positions for P&L chart")
        positions_df = get_current_positions(fund)
        logger.debug(f"[Dashboard API] Positions fetched: {len(positions_df)} rows")
        
        if positions_df.empty:
            logger.warning(f"[Dashboard API] No positions found for P&L chart - fund={fund}")
            # Return empty Plotly chart
            import plotly.graph_objs as go
            fig = go.Figure()
            fig.add_annotation(
                text="No P&L data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
            return Response(
                serialize_plotly_figure(fig),
                mimetype='application/json'
            )
        
        # Check for P&L columns
        if 'pnl' not in positions_df.columns and 'unrealized_pnl' not in positions_df.columns:
            logger.warning(f"[Dashboard API] No P&L columns found in positions data")
            import plotly.graph_objs as go
            fig = go.Figure()
            fig.add_annotation(
                text="No P&L data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
            return Response(
                serialize_plotly_figure(fig),
                mimetype='application/json'
            )
        
        # Fetch dividend data
        dividend_data = []
        try:
            dividend_data = fetch_dividend_log_flask(days_lookback=365, fund=fund)
            logger.debug(f"[Dashboard API] Dividend data fetched: {len(dividend_data)} records")
        except Exception as e:
            logger.warning(f"[Dashboard API] Could not fetch dividend data: {e}")
        
        # Create P&L chart using shared function (same as Streamlit)
        fig = create_pnl_chart(
            positions_df,
            fund_name=fund,
            display_currency=display_currency,
            dividend_data=dividend_data
        )
        
        # Update height to match container (500px)
        fig.update_layout(
            height=500,
            margin=dict(l=20, r=20, t=50, b=100)
        )
        
        # Apply theme to chart
        if not client_theme or client_theme not in ['dark', 'light', 'midnight-tokyo', 'abyss']:
            # Get user theme preference from backend
            user_theme = get_user_theme() or 'system'
            theme = user_theme if user_theme in ['dark', 'light', 'midnight-tokyo', 'abyss'] else 'light'
        else:
            theme = client_theme
        
        # Serialize figure with numpy array conversion
        chart_json = serialize_plotly_figure(fig)
        chart_data = json.loads(chart_json)
        theme_config = get_chart_theme_config(theme)
        
        # Update layout for theme
        if 'layout' in chart_data:
            chart_data['layout']['template'] = theme_config['template']
            chart_data['layout']['paper_bgcolor'] = theme_config['paper_bgcolor']
            chart_data['layout']['plot_bgcolor'] = theme_config['plot_bgcolor']
            chart_data['layout']['font'] = {'color': theme_config['font_color']}
            
            # Update legend background if it exists
            if 'legend' in chart_data['layout']:
                chart_data['layout']['legend']['bgcolor'] = theme_config['legend_bg_color']
        
        processing_time = time.time() - start_time
        logger.info(f"[Dashboard API] P&L chart created - theme={theme}, processing_time={processing_time:.3f}s")
        
        # Return Plotly JSON with theme applied
        return Response(
            json.dumps(chart_data),
            mimetype='application/json'
        )
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error fetching P&L chart (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500

@dashboard_bp.route('/api/dashboard/holdings', methods=['GET'])
def get_holdings_data():
    """Get content for holdings table"""
    fund = request.args.get('fund')
    # Convert 'all' or empty string to None for aggregate view
    if not fund or fund.lower() == 'all':
        fund = None
        
    display_currency = get_user_currency() or 'CAD'
    
    logger.info(f"[Dashboard API] /api/dashboard/holdings called - fund={fund}, currency={display_currency}")
    start_time = time.time()
    
    try:
        logger.debug(f"[Dashboard API] Fetching positions for holdings table")
        positions_df = get_current_positions(fund)
        logger.debug(f"[Dashboard API] Positions fetched: {len(positions_df)} rows")
        
        if positions_df.empty:
            logger.warning(f"[Dashboard API] No positions found for holdings - fund={fund}")
            return jsonify({"data": []})
        
        # Get first trade dates for "Opened" column
        first_trade_dates = get_first_trade_dates(fund)
            
        # Get rates
        all_currencies = positions_df['currency'].fillna('CAD').astype(str).str.upper().unique().tolist()
        rate_map = fetch_latest_rates_bulk(all_currencies, display_currency)
        def get_rate(curr): return rate_map.get(str(curr).upper(), 1.0)
        rates = positions_df['currency'].fillna('CAD').astype(str).str.upper().map(get_rate)
        
        # Process data and calculate converted values first
        converted_data = []
        for idx, row in positions_df.iterrows():
            rate = get_rate(row.get('currency', 'CAD'))
            market_val = (row.get('market_value', 0) or 0) * rate
            converted_data.append(market_val)
        
        # Calculate total portfolio value in display currency for weight calculation
        total_portfolio_value = sum(converted_data) if converted_data else 0
        
        # Process data
        data = []
        for idx, row in positions_df.iterrows():
            ticker = row.get('ticker')
            
            # Handle nested securities data
            company_name = ticker # Default
            sector = ""
            if isinstance(row.get('securities'), dict):
                company_name = row['securities'].get('company_name') or ticker
                sector = row['securities'].get('sector') or ""
            
            # Use 'shares' from latest_positions view (not 'quantity')
            shares = row.get('shares', 0) or 0
            cost_basis = row.get('cost_basis', 0) or 0
            current_price = row.get('current_price', 0) or 0
            
            # Calculate average price from cost_basis / shares
            avg_price = (cost_basis / shares) if shares > 0 else 0
            
            # Values in Display Currency
            rate = get_rate(row.get('currency', 'CAD'))
            market_val = (row.get('market_value', 0) or 0) * rate
            pnl = (row.get('unrealized_pnl', 0) or 0) * rate
            day_pnl = (row.get('daily_pnl', 0) or 0) * rate
            five_day_pnl = (row.get('five_day_pnl', 0) or 0) * rate
            
            # Use P&L percentages from view (already calculated correctly)
            pnl_pct = row.get('return_pct', 0) or 0
            day_pnl_pct = row.get('daily_pnl_pct', 0) or 0
            five_day_pnl_pct = row.get('five_day_pnl_pct', 0) or 0
            
            # Calculate weight as percentage of total portfolio (in display currency)
            weight = (market_val / total_portfolio_value * 100) if total_portfolio_value > 0 else 0
            
            # Get opened date
            opened_date = None
            if ticker in first_trade_dates:
                try:
                    opened_date = first_trade_dates[ticker].strftime('%m-%d-%y')
                except:
                    opened_date = None
            
            # Get stop loss if available (might not be in view)
            stop_loss = row.get('stop_loss', None)
                
            data.append({
                "ticker": ticker,
                "name": company_name,
                "sector": sector,
                "shares": shares,
                "opened": opened_date,
                "avg_price": avg_price * rate,  # Avg price in display currency
                "price": current_price * rate,  # Current price in display currency
                "value": market_val,
                "day_change": day_pnl,
                "day_change_pct": day_pnl_pct,
                "total_return": pnl,
                "total_return_pct": pnl_pct,
                "five_day_pnl": five_day_pnl,
                "five_day_pnl_pct": five_day_pnl_pct,
                "weight": weight,
                "stop_loss": stop_loss,
                "currency": row.get('currency', 'CAD') # Original currency
            })
            
        # Sort by weight desc (matching console app default)
        data.sort(key=lambda x: x.get('weight', 0), reverse=True)
        
        processing_time = time.time() - start_time
        logger.info(f"[Dashboard API] Holdings data prepared - {len(data)} holdings, processing_time={processing_time:.3f}s")
        
        return jsonify({"data": data})
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error fetching holdings (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500

@dashboard_bp.route('/api/dashboard/activity', methods=['GET'])
def get_recent_activity():
    """Get recent transactions"""
    fund = request.args.get('fund')
    # Convert 'all' or empty string to None for aggregate view
    if not fund or fund.lower() == 'all':
        fund = None
        
    limit = int(request.args.get('limit', 10))
    display_currency = get_user_currency() or 'CAD'
    
    logger.info(f"[Dashboard API] /api/dashboard/activity called - fund={fund}, limit={limit}, currency={display_currency}")
    start_time = time.time()
    
    try:
        logger.debug(f"[Dashboard API] Fetching trade log for activity")
        trades_df = get_trade_log(limit=limit, fund=fund)
        logger.debug(f"[Dashboard API] Trade log fetched: {len(trades_df)} rows")
        
        if trades_df.empty:
            logger.warning(f"[Dashboard API] No trades found for activity - fund={fund}")
            return jsonify({"data": []})
        
        data = []
        for _, row in trades_df.iterrows():
            # Format logic
            date_str = row['date'].strftime('%Y-%m-%d') if hasattr(row['date'], 'strftime') else str(row['date'])
            ticker = row.get('ticker')
            action = "BUY" if row.get('shares', 0) > 0 else "SELL"
            
            data.append({
                "date": date_str,
                "ticker": ticker,
                "action": action,
                "shares": abs(row.get('shares', 0)),
                "price": row.get('price', 0),
                "amount": abs(row.get('amount', 0)) # Assuming amount col exists, else calculate
            })
            
        processing_time = time.time() - start_time
        logger.info(f"[Dashboard API] Activity data prepared - {len(data)} activities, processing_time={processing_time:.3f}s")
        
        return jsonify({"data": data})
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error fetching activity (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500

@dashboard_bp.route('/api/dashboard/dividends', methods=['GET'])
@require_auth
def get_dividend_data():
    """Get dividend metrics and log.
    
    Returns:
        JSON with metrics (total LTM, tax, etc.) and list of dividend events.
    """
    fund = request.args.get('fund')
    if not fund or fund.lower() == 'all':
        fund = None
        
    display_currency = get_user_currency() or 'CAD'
    
    try:
        # Fetch dividend data (last 365 days for LTM metrics)
        # Returns a list of dicts, not a DataFrame
        dividend_list = fetch_dividend_log_flask(days_lookback=365, fund=fund)
        
        if not dividend_list:
            return jsonify({
                "metrics": {
                    "total_dividends": 0.0,
                    "total_us_tax": 0.0,
                    "largest_dividend": 0.0,
                    "largest_ticker": "N/A",
                    "reinvested_shares": 0.0,
                    "payout_events": 0
                },
                "log": []
            })
            
        # Calculate Metrics (LTM) from list of dicts
        # Columns: net_amount, gross_amount, reinvested_shares, pay_date, ticker
        total_dividends = sum(float(d.get('net_amount', 0) or 0) for d in dividend_list)
        # Tax = gross - net
        total_us_tax = sum(
            float(d.get('gross_amount', 0) or 0) - float(d.get('net_amount', 0) or 0) 
            for d in dividend_list
        )
        
        # Find largest dividend
        largest_dividend = 0.0
        largest_ticker = "N/A"
        for d in dividend_list:
            amt = float(d.get('net_amount', 0) or 0)
            if amt > largest_dividend:
                largest_dividend = amt
                largest_ticker = d.get('ticker', 'N/A')
        
        # Calculate Reinvested Shares (DRIP)
        total_reinvested = sum(float(d.get('reinvested_shares', 0) or 0) for d in dividend_list)
            
        payout_events = len(dividend_list)
        
        # Prepare Log (for table) - already sorted by pay_date desc from query
        log_data = []
        for row in dividend_list:
            pay_date = row.get('pay_date', '')
            net_amt = float(row.get('net_amount', 0) or 0)
            gross_amt = float(row.get('gross_amount', 0) or 0)
            reinvested = float(row.get('reinvested_shares', 0) or 0)
            log_data.append({
                "date": pay_date if isinstance(pay_date, str) else str(pay_date),
                "ticker": row.get('ticker', ''),
                "amount": net_amt,
                "tax": gross_amt - net_amt,
                "shares": reinvested,
                "type": "DRIP" if reinvested > 0 else "CASH"
            })
            
        return jsonify({
            "metrics": {
                "total_dividends": total_dividends,
                "total_us_tax": total_us_tax,
                "largest_dividend": largest_dividend,
                "largest_ticker": largest_ticker,
                "reinvested_shares": total_reinvested,
                "payout_events": payout_events
            },
            "log": log_data,
            "currency": display_currency
        })
        
    except Exception as e:
        logger.error(f"Error fetching dividend data: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route('/api/dashboard/charts/currency', methods=['GET'])
def get_currency_chart():
    """Get currency exposure chart as Plotly JSON."""
    fund = request.args.get('fund')
    if not fund or fund.lower() == 'all':
        fund = None
        
    theme = request.args.get('theme', 'light')
    
    try:
        positions_df = get_current_positions(fund)
        cash_balances = get_cash_balances(fund)
        
        # Create chart using shared utility
        # Note: create_currency_exposure_chart takes positions_df and fund_name
        # We pass fund as fund_name since the function signature expects fund_name, not cash_balances
        from chart_utils import create_currency_exposure_chart, get_chart_theme_config
        from plotly_utils import serialize_plotly_figure

        fig = create_currency_exposure_chart(positions_df, fund_name=fund)
        
        if not fig:
             return jsonify({"error": "Could not create chart"}), 500
             
        # Update height
        fig.update_layout(height=350, margin=dict(l=20, r=20, t=30, b=20))
        
        # Apply theme
        chart_json = serialize_plotly_figure(fig)
        chart_data = json.loads(chart_json)
        theme_config = get_chart_theme_config(theme)
        
        if 'layout' in chart_data:
            chart_data['layout']['template'] = theme_config['template']
            chart_data['layout']['paper_bgcolor'] = theme_config['paper_bgcolor']
            chart_data['layout']['plot_bgcolor'] = theme_config['plot_bgcolor']
            chart_data['layout']['font'] = {'color': theme_config['font_color']}
            
        return Response(json.dumps(chart_data), mimetype='application/json')
        
    except Exception as e:
        logger.error(f"Error creating currency chart: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route('/api/dashboard/exchange-rate', methods=['GET'])
def get_exchange_rate_data():
    """Get current exchange rate and 90-day historical data.
    
    GET /api/dashboard/exchange-rate
    
    Query Parameters:
        inverse (bool): If true, show CAD/USD instead of USD/CAD (default: false)
        
    Returns:
        JSON response with current rate and historical data for chart
    """
    from datetime import timedelta
    from exchange_rates_utils import get_supabase_client
    
    inverse = request.args.get('inverse', 'false').lower() == 'true'
    theme = request.args.get('theme', 'light')
    
    try:
        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Could not connect to database"}), 500
        
        # Get latest rate
        latest_rate = client.get_latest_exchange_rate('USD', 'CAD')
        
        # Get 90-day historical rates
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=90)
        historical_rates = client.get_exchange_rates(start_date, end_date, 'USD', 'CAD')
        
        # Prepare response
        current_rate = float(latest_rate) if latest_rate else None
        if inverse and current_rate:
            current_rate = 1.0 / current_rate
        
        # Prepare chart data
        chart_data = None
        if historical_rates:
            import plotly.graph_objects as go
            from chart_utils import get_chart_theme_config
            from plotly_utils import serialize_plotly_figure
            
            dates = []
            rates = []
            for r in historical_rates:
                timestamp = r.get('timestamp')
                rate = r.get('rate')
                if timestamp and rate:
                    if isinstance(timestamp, str):
                        dates.append(timestamp)
                    else:
                        dates.append(timestamp.isoformat())
                    rate_val = float(rate)
                    rates.append(1.0 / rate_val if inverse else rate_val)
            
            if dates and rates:
                y_label = 'CAD/USD' if inverse else 'USD/CAD'
                chart_title = f'{y_label} Rate (90 Days)'
                
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=dates,
                    y=rates,
                    mode='lines',
                    name=y_label,
                    line=dict(color='#3b82f6', width=2),
                    hovertemplate='%{x|%b %d}<br>%{y:.4f}<extra></extra>'
                ))
                
                fig.update_layout(
                    title=chart_title,
                    xaxis_title='Date',
                    yaxis_title='Rate',
                    template='plotly_white',
                    height=250,
                    margin=dict(l=40, r=20, t=40, b=30),
                    showlegend=False
                )
                
                # Apply theme
                chart_json = serialize_plotly_figure(fig)
                chart_data = json.loads(chart_json)
                theme_config = get_chart_theme_config(theme)
                
                if 'layout' in chart_data:
                    chart_data['layout']['template'] = theme_config['template']
                    chart_data['layout']['paper_bgcolor'] = theme_config['paper_bgcolor']
                    chart_data['layout']['plot_bgcolor'] = theme_config['plot_bgcolor']
                    chart_data['layout']['font'] = {'color': theme_config['font_color']}
        
        return jsonify({
            "current_rate": current_rate,
            "rate_label": "CAD/USD" if inverse else "USD/CAD",
            "rate_help": "1 CAD = X USD" if inverse else "1 USD = X CAD",
            "inverse": inverse,
            "chart": chart_data
        })
        
    except Exception as e:
        logger.error(f"Error fetching exchange rate data: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/dashboard/movers', methods=['GET'])
@require_auth
def get_movers_data():
    """Get top gainers and losers for the day.
    
    GET /api/dashboard/movers
    
    Query Parameters:
        fund (str): Fund name (optional)
        limit (int): Number of movers to return per category (default: 10)
        
    Returns:
        JSON response with gainers and losers arrays
    """
    fund = request.args.get('fund')
    if not fund or fund.lower() == 'all':
        fund = None
        
    limit = int(request.args.get('limit', 10))
    display_currency = get_user_currency() or 'CAD'
    
    logger.info(f"[Dashboard API] /api/dashboard/movers called - fund={fund}, limit={limit}, currency={display_currency}")
    start_time = time.time()
    
    try:
        positions_df = get_current_positions(fund)
        
        if positions_df.empty:
            logger.warning(f"[Dashboard API] No positions found for movers - fund={fund}")
            return jsonify({"gainers": [], "losers": []})
        
        movers = get_biggest_movers(positions_df, display_currency, limit=limit)
        
        def df_to_list(df):
            if df.empty:
                return []
            result = []
            for _, row in df.iterrows():
                item = {
                    "ticker": row.get('ticker', ''),
                    "company_name": row.get('company_name', row.get('ticker', '')),
                }
                if 'daily_pnl_pct' in row:
                    item["daily_pnl_pct"] = float(row['daily_pnl_pct']) if pd.notna(row['daily_pnl_pct']) else None
                elif 'return_pct' in row:
                    item["daily_pnl_pct"] = float(row['return_pct']) if pd.notna(row['return_pct']) else None
                if 'pnl_display' in row:
                    item["daily_pnl"] = float(row['pnl_display']) if pd.notna(row['pnl_display']) else None
                if 'five_day_pnl_pct' in row:
                    item["five_day_pnl_pct"] = float(row['five_day_pnl_pct']) if pd.notna(row['five_day_pnl_pct']) else None
                if 'five_day_pnl_display' in row:
                    item["five_day_pnl"] = float(row['five_day_pnl_display']) if pd.notna(row['five_day_pnl_display']) else None
                if 'return_pct' in row and 'daily_pnl_pct' in df.columns:
                    item["total_return_pct"] = float(row['return_pct']) if pd.notna(row['return_pct']) else None
                if 'total_pnl_display' in row:
                    item["total_pnl"] = float(row['total_pnl_display']) if pd.notna(row['total_pnl_display']) else None
                if 'current_price' in row:
                    item["current_price"] = float(row['current_price']) if pd.notna(row['current_price']) else None
                if 'market_value' in row:
                    item["market_value"] = float(row['market_value']) if pd.notna(row['market_value']) else None
                result.append(item)
            return result
        
        gainers = df_to_list(movers['gainers'])
        losers = df_to_list(movers['losers'])
        
        processing_time = time.time() - start_time
        logger.info(f"[Dashboard API] Movers data prepared - {len(gainers)} gainers, {len(losers)} losers, processing_time={processing_time:.3f}s")
        
        return jsonify({
            "gainers": gainers,
            "losers": losers,
            "display_currency": display_currency,
            "processing_time": processing_time
        })
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error fetching movers (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500
