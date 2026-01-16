from flask import Blueprint, jsonify, request, current_app
from auth import require_admin, is_admin
from streamlit_utils import get_supabase_client, SupabaseClient
import logging
import os
import sys
import subprocess
import time
from pathlib import Path

# Configure logger
logger = logging.getLogger(__name__)

fund_bp = Blueprint('fund_routes', __name__)

def validate_fund_name(name: str) -> bool:
    """
    Validate fund name to prevent path traversal and ensure it's safe for filesystem.
    Returns True if valid, False otherwise.
    Allows spaces, letters, numbers, underscores, hyphens.
    Rejects '..', '/', '\\'.
    """
    if not name or not isinstance(name, str):
        return False

    # Check for path traversal characters
    if '..' in name or '/' in name or '\\' in name:
        return False

    # Check for empty or whitespace only
    if not name.strip():
        return False

    return True

@fund_bp.route('/admin/funds')
@require_admin
def admin_funds_page():
    """Render the fund management page"""
    from flask import render_template
    from flask_auth_utils import get_user_email_flask
    from user_preferences import get_user_theme
    from app import get_navigation_context
    
    user_email = get_user_email_flask()
    user_theme = get_user_theme() or 'system'
    
    # Get navigation context
    nav_context = get_navigation_context(current_page='admin_funds')
    
    return render_template('funds.html', 
                         user_email=user_email,
                         user_theme=user_theme,
                         **nav_context)

@fund_bp.route('/api/funds', methods=['GET'])
@require_admin
def get_all_funds():
    """Get all funds with statistics"""
    try:
        from admin_utils import get_cached_funds, get_fund_statistics_batched
        
        # Use cached funds for speed
        funds_data = get_cached_funds()
        fund_names = [f['name'] for f in funds_data]
        
        if not fund_names:
            return jsonify({"funds": []})
            
        # Get batched statistics
        fund_statistics = get_fund_statistics_batched(fund_names)
        
        results = []
        for fund in funds_data:
            name = fund['name']
            stats = fund_statistics.get(name, {"positions": 0, "trades": 0})
            
            results.append({
                "name": name,
                "description": fund.get('description', ''),
                "type": fund.get('fund_type', 'investment'),
                "currency": fund.get('currency', 'CAD'),
                "is_production": fund.get('is_production', False),
                "created_at": fund.get('created_at'),
                "positions": stats["positions"],
                "trades": stats["trades"]
            })
            
        return jsonify({"funds": results})
        
    except Exception as e:
        logger.error(f"Error fetching funds: {e}")
        return jsonify({"error": str(e)}), 500

@fund_bp.route('/api/funds', methods=['POST'])
@require_admin
def create_fund():
    """Create a new fund"""
    try:
        data = request.get_json()
        name = data.get('name')
        description = data.get('description')
        currency = data.get('currency', 'CAD')
        fund_type = data.get('fund_type', 'investment')
        
        if not name:
            return jsonify({"error": "Fund name is required"}), 400
            
        if not validate_fund_name(name):
             return jsonify({"error": "Invalid fund name. Names cannot contain '/', '\\', or '..'"}), 400

        client = get_supabase_client()
        
        # Check if exists
        existing = client.supabase.table("funds").select("name").eq("name", name).execute()
        if existing.data:
            return jsonify({"error": f"Fund '{name}' already exists"}), 400
            
        # Create fund
        client.supabase.table("funds").insert({
            "name": name,
            "description": description,
            "currency": currency,
            "fund_type": fund_type
        }).execute()
        
        # Initialize cash balances
        client.supabase.table("cash_balances").upsert([
            {"fund": name, "currency": "CAD", "amount": 0},
            {"fund": name, "currency": "USD", "amount": 0}
        ]).execute()
        
        return jsonify({"message": f"Fund '{name}' created successfully"}), 201
        
    except Exception as e:
        logger.error(f"Error creating fund: {e}")
        return jsonify({"error": str(e)}), 500

@fund_bp.route('/api/funds/<fund_name>', methods=['PUT'])
@require_admin
def update_fund(fund_name):
    """Update fund details"""
    try:
        # Note: We don't validate fund_name here because it's in the URL and Flask handles routing.
        # However, checking it doesn't hurt if we use it for anything other than DB lookup.
        # But here it's just used for DB update key.

        data = request.get_json()
        client = get_supabase_client()
        
        # Update fields
        updates = {}
        if 'description' in data: updates['description'] = data['description']
        if 'fund_type' in data: updates['fund_type'] = data['fund_type'] 
        if 'currency' in data: updates['currency'] = data['currency']
        if 'is_production' in data: updates['is_production'] = data['is_production']
        
        if not updates:
            return jsonify({"message": "No changes provided"})
            
        client.supabase.table("funds").update(updates).eq("name", fund_name).execute()
        
        return jsonify({"message": f"Fund '{fund_name}' updated successfully"})
        
    except Exception as e:
        logger.error(f"Error updating fund {fund_name}: {e}")
        return jsonify({"error": str(e)}), 500

@fund_bp.route('/api/funds/rename', methods=['POST'])
@require_admin
def rename_fund():
    """Rename a fund"""
    try:
        data = request.get_json()
        old_name = data.get('old_name')
        new_name = data.get('new_name')
        
        if not old_name or not new_name:
            return jsonify({"error": "Old and new names are required"}), 400
            
        if not validate_fund_name(new_name):
             return jsonify({"error": "Invalid new fund name. Names cannot contain '/', '\\', or '..'"}), 400

        client = get_supabase_client()
        
        # Check new name availability
        existing = client.supabase.table("funds").select("name").eq("name", new_name).execute()
        if existing.data:
            return jsonify({"error": f"Fund '{new_name}' already exists"}), 400
            
        # Update (Cascade should handle relations if DB is configured correctly, otherwise this might fail)
        # Assuming ON UPDATE CASCADE is set up in Postgres
        client.supabase.table("funds").update({"name": new_name}).eq("name", old_name).execute()
        
        return jsonify({"message": f"Fund renamed from '{old_name}' to '{new_name}'"})
        
    except Exception as e:
        logger.error(f"Error renaming fund: {e}")
        return jsonify({"error": str(e)}), 500

@fund_bp.route('/api/funds/<fund_name>', methods=['DELETE'])
@require_admin
def delete_fund(fund_name):
    """Permanently delete a fund"""
    try:
        client = get_supabase_client()
        
        # Manual cleanup of dependent tables first (safer than relying purely on cascades)
        tables = ["portfolio_positions", "trade_log", "cash_balances", "fund_contributions", "fund_thesis"]
        
        for table in tables:
            try:
                client.supabase.table(table).delete().eq("fund", fund_name).execute()
            except Exception as e:
                logger.warning(f"Error cleaning up {table} for {fund_name}: {e}")
                
        # Delete fund
        client.supabase.table("funds").delete().eq("name", fund_name).execute()
        
        return jsonify({"message": f"Fund '{fund_name}' deleted successfully"})
        
    except Exception as e:
        logger.error(f"Error deleting fund {fund_name}: {e}")
        return jsonify({"error": str(e)}), 500

@fund_bp.route('/api/funds/<fund_name>/wipe', methods=['POST'])
@require_admin
def wipe_fund_data(fund_name):
    """Wipe positions and trades for a fund"""
    try:
        data = request.get_json()
        wipe_trades = data.get('wipe_trades', False)
        
        client = get_supabase_client()
        
        # Wipe positions
        client.supabase.table("portfolio_positions").delete().eq("fund", fund_name).execute()
        
        # Wipe trades if requested
        if wipe_trades:
            # Check production status first
            fund_info = client.supabase.table("funds").select("is_production").eq("name", fund_name).execute()
            is_prod = fund_info.data[0].get("is_production", False) if fund_info.data else False
            
            if is_prod and not data.get('force_prod', False):
                return jsonify({"warning": "Cannot wipe trades for production fund without force flag"}), 400
                
            client.supabase.table("trade_log").delete().eq("fund", fund_name).execute()
            
        # Reset cash
        client.supabase.table("cash_balances").update({"amount": 0}).eq("fund", fund_name).execute()
        
        return jsonify({"message": f"Data wiped for '{fund_name}'"})
        
    except Exception as e:
        logger.error(f"Error wiping fund {fund_name}: {e}")
        return jsonify({"error": str(e)}), 500

@fund_bp.route('/api/funds/rebuild', methods=['POST'])
@require_admin
def rebuild_portfolio():
    """Start portfolio rebuild job"""
    try:
        data = request.get_json()
        fund_name = data.get('fund_name')
        
        if not fund_name:
            return jsonify({"error": "Fund name is required"}), 400

        if not validate_fund_name(fund_name):
             return jsonify({"error": "Invalid fund name. Names cannot contain '/', '\\', or '..'"}), 400
            
        # Check for existing rebuild
        import tempfile
        try:
            # Simple check via psutil or file lock
            # Using the same lock file mechanism as Streamlit
            lock_file_path = Path(tempfile.gettempdir()) / "portfolio_rebuild.lock"
            
            # Check if running Logic... (Copying from admin_funds.py)
            # For brevity/robustness in Flask, we will spawn the process and rely on it to manage the lock
            # but we can try to check if it's already running to give fast feedback
            
            pass # Skipping complex check here, let the script handle or fire and forget
        except:
            pass
            
        # Locate script
        # Assuming current structure relative to this file
        # web_dashboard/routes/fund_routes.py -> project_root/debug/rebuild_portfolio_complete.py
        current_dir = Path(__file__).parent 
        project_root = current_dir.parent.parent
        rebuild_script = project_root / "debug" / "rebuild_portfolio_complete.py"
        
        if not rebuild_script.exists():
            # Try Docker path
            rebuild_script = Path("/app/debug/rebuild_portfolio_complete.py")
            if not rebuild_script.exists():
                return jsonify({"error": "Rebuild script not found"}), 500
                
        # Data dir
        # Using f-string here is now safe because validate_fund_name ensures no path traversal
        data_dir = f"trading_data/funds/{fund_name}"
        
        # Launch process
        if os.name == 'nt':
            process = subprocess.Popen(
                ["python", str(rebuild_script), data_dir, fund_name],
                cwd=str(project_root) if project_root.exists() else "/app",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            process = subprocess.Popen(
                ["python", str(rebuild_script), data_dir, fund_name],
                cwd=str(project_root) if project_root.exists() else "/app",
                start_new_session=True
            )
            
        return jsonify({
            "message": f"Rebuild started for {fund_name}",
            "pid": process.pid
        })
        
    except Exception as e:
        logger.error(f"Error starting rebuild: {e}")
        return jsonify({"error": str(e)}), 500

@fund_bp.route('/api/ticker/refresh', methods=['POST'])
@require_admin
def refresh_ticker_metadata():
    """Refresh ticker metadata from yfinance"""
    try:
        data = request.get_json()
        ticker = data.get('ticker')
        currency = data.get('currency', 'USD')
        
        if not ticker:
            return jsonify({"error": "Ticker is required"}), 400
            
        admin_client = SupabaseClient(use_service_role=True)
        success = admin_client.ensure_ticker_in_securities(ticker.upper().strip(), currency)
        
        if success:
             # Fetch updated
             updated = admin_client.supabase.table("securities")\
                .select("ticker, company_name, sector, industry, currency")\
                .eq("ticker", ticker.upper().strip())\
                .execute()
             
             if updated.data:
                 return jsonify({"success": True, "data": updated.data[0]})
        
        return jsonify({"error": f"Failed to refresh metadata for {ticker}"}), 400
        
    except Exception as e:
        logger.error(f"Error refreshing ticker: {e}")
        return jsonify({"error": str(e)}), 500
