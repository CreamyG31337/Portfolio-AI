from flask import Blueprint, render_template, request, jsonify
import logging
from auth import require_auth
from flask_auth_utils import get_user_email_flask
from user_preferences import get_user_theme

logger = logging.getLogger(__name__)

color_test_bp = Blueprint('color_test', __name__)

@color_test_bp.route('/color-test')
@require_auth
def color_test_page():
    """Color testing page for theme development"""
    try:
        # Lazy import to avoid circular import
        from app import get_navigation_context
        
        user_email = get_user_email_flask()
        
        # Navigation context
        nav_context = get_navigation_context(current_page='color_test')
        
        return render_template('color_test.html',
                             user_email=user_email,
                             **nav_context)
    except Exception as e:
        logger.error(f"Error rendering color test page: {e}", exc_info=True)
        # Fallback with minimal context
        try:
            from app import get_navigation_context  # Import here to avoid circular import
            nav_context = get_navigation_context(current_page='color_test')
        except Exception:
            nav_context = {}
        return render_template('color_test.html', 
                             user_email='User',
                             **nav_context)
