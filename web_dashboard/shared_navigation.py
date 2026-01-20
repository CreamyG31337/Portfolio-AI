
"""
Shared navigation configuration for both Streamlit and Flask.
"""

# MIGRATED_PAGES dictionary maps Streamlit page keys to Flask URLs.
# Pages that have been migrated to Flask should be added here.
MIGRATED_PAGES = {
    'dashboard': '/dashboard',
    'settings': '/settings',  # Routed to Flask via Caddy /v2/* handler
    'research': '/research',
    'social_sentiment': '/social_sentiment',
    'signals': '/signals',
    'etf_holdings': '/etf_holdings',
    'congress_trades': '/congress_trades',
    'ticker_details': '/ticker',
    'ai_assistant': '/ai_assistant',
    'admin_funds': '/admin/funds',
    'admin_logs': '/logs',
    'admin_users': '/admin/users',
    'admin_scheduler': '/admin/scheduler',
    'admin_trade_entry': '/admin/trade-entry',
    'admin_contributions': '/admin/contributions',
    'admin_contributors': '/admin/contributors',
    'admin_ai_settings': '/admin/ai-settings',
    'admin_system': '/admin/system',
}

def is_page_migrated(page_key: str) -> bool:
    """Check if a page has been migrated to Flask."""
    return page_key in MIGRATED_PAGES

def get_page_url(page_key: str) -> str:
    """Get the Flask URL for a migrated page."""
    return MIGRATED_PAGES.get(page_key, '#')

def get_navigation_links() -> list:
    """Get list of navigation links with their URLs.
    
    Returns:
        List of dictionaries with 'name', 'page', 'url', and 'icon' keys
    """
    links = [
        {'name': 'Research Repository', 'page': 'research', 'icon': '📚'},
        {'name': 'Social Sentiment', 'page': 'social_sentiment', 'icon': '💬'},
        {'name': 'Technical Signals', 'page': 'signals', 'icon': '📊'},
        {'name': 'ETF Holdings', 'page': 'etf_holdings', 'icon': '💼'},
        {'name': 'Congress Trades', 'page': 'congress_trades', 'icon': '🏛️'},
        {'name': 'Ticker Lookup', 'page': 'ticker_details', 'icon': '🔍'},
        {'name': 'AI Assistant', 'page': 'ai_assistant', 'icon': '🧠'},
        {'name': 'User Preferences', 'page': 'settings', 'icon': '👤'},
    ]
    
    # Add URLs based on migration status
    for link in links:
        if is_page_migrated(link['page']):
            link['url'] = get_page_url(link['page'])
        else:
            # Streamlit MPA URLs: /page_name (not /pages/page_name)
            if link['page'] == 'dashboard':
                link['url'] = '/'
            else:
                link['url'] = f'/{link["page"]}'
    
    return links

# Menu structure matching shared_utils/navigation.py
# Updated to match new URLs
NAVIGATION_STRUCTURE = {
    # ... (rest of the structure if used by other components)
}
