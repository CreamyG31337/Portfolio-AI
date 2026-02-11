import os
import time
import sys
from playwright.sync_api import sync_playwright

# Configuration
BASE_URL = "https://ai-trading.drifting.space"
EMAIL = "admin.test@tradingbot.local"
PASSWORD = "vtg6Su2crPMvejomltTN"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "images")

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def set_theme(page, theme):
    print(f"  Setting theme to: {theme}")
    try:
        page.evaluate(f"""() => {{
            if (window.themeManager) {{
                window.themeManager.setTheme('{theme}');
            }}
        }}""")
        time.sleep(0.5) # Allow transition
    except Exception as e:
        print(f"  Warning setting theme: {e}")

def login(page):
    print("Logging in...")
    page.goto(f"{BASE_URL}/")
    page.fill('input[name="email"]', EMAIL)
    page.fill('input[name="password"]', PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{BASE_URL}/dashboard")
    print("Login successful.")

def capture_screenshots():
    ensure_dir(OUTPUT_DIR)
    
    with sync_playwright() as p:
        # Use standard chromium, headless
        browser = p.chromium.launch(headless=True)
        # Larger viewport for better quality
        context = browser.new_context(viewport={'width': 1920, 'height': 1080}, permissions=['clipboard-read', 'clipboard-write'])
        page = context.new_page()

        # 1. Login Page (Light Mode - Cropped to Form)
        print("Capturing Login Page...")
        page.goto(f"{BASE_URL}/")
        try:
            # Wait for form to be visible
            page.wait_for_selector("#login-form", state="visible")
            # Capture only the login form element
            page.locator("#login-form").screenshot(path=os.path.join(OUTPUT_DIR, "login_page.png"))
            print("  Login page captured (cropped).")
        except Exception as e:
            print(f"  Warning: Could not crop login form, capturing full page: {e}")
            page.screenshot(path=os.path.join(OUTPUT_DIR, "login_page.png"))

        # 2. Login
        login(page)

        # Ensure TFSA is selected
        print("Selecting TFSA fund...")
        try:
            # Check if dropdown exists (admin might have it differently or multiple funds)
            # Admin usually has access to all funds, so we should be able to select TFSA if it exists.
            # If not, we might need to handle it. safely.
            page.wait_for_selector('#global-fund-select', state='attached', timeout=5000)
            page.select_option('#global-fund-select', label='TFSA')
            page.wait_for_load_state('networkidle')
            time.sleep(2) # Extra time for UI update
        except Exception as e:
            print(f"Warning: Could not select TFSA (might be default or not available): {e}")

        # 3. Dashboard (Light Mode)
        print("Capturing Dashboard (Light)...")
        page.goto(f"{BASE_URL}/dashboard")
        page.wait_for_load_state('networkidle')
        set_theme(page, 'light')
        
        # Wait for Plotly chart to render (remove loading spinner)
        try:
            print("  Waiting for chart to render...")
            page.wait_for_selector(".js-plotly-plot", state="visible", timeout=10000)
            time.sleep(2) # Extra buffer for animation
        except Exception as e:
            print(f"  Warning: Chart did not load in time: {e}")

        # Full page capture for dashboard
        page.screenshot(path=os.path.join(OUTPUT_DIR, "dashboard_overview.png"), full_page=True)

        # 4. Settings (Light Mode)
        print("Capturing Settings (Light)...")
        page.goto(f"{BASE_URL}/settings")
        page.wait_for_load_state('networkidle')
        set_theme(page, 'light')
        page.screenshot(path=os.path.join(OUTPUT_DIR, "settings_page.png"), full_page=True)

        # 5. AI Research (Dark Mode - Feature)
        print("Capturing AI Research (Dark)...")
        page.goto(f"{BASE_URL}/research")
        page.wait_for_load_state('networkidle')
        set_theme(page, 'dark')
        page.screenshot(path=os.path.join(OUTPUT_DIR, "ai_research_page.png"), full_page=True)
        
        # 6. Signals Page (Light Mode - Feature Replacement)
        # Since catching a specific ticker is flaky without data, capture the Signals capability page
        print("Capturing Signals Page (Light)...")
        page.goto(f"{BASE_URL}/signals")
        page.wait_for_load_state('networkidle')
        set_theme(page, 'light')
        page.screenshot(path=os.path.join(OUTPUT_DIR, "signals_page.png"), full_page=True)

        # 7. Congress Trades (Light Mode)
        print("Capturing Congress Trades (Light)...")
        page.goto(f"{BASE_URL}/congress_trades")
        page.wait_for_load_state('networkidle')
        set_theme(page, 'light')
        page.screenshot(path=os.path.join(OUTPUT_DIR, "congress_trades_page.png"), full_page=True)



        # 8. Insider Trades (Light Mode)
        print("Capturing Insider Trades (Light)...")
        try:
            page.goto(f"{BASE_URL}/insider_trades", timeout=60000)
            page.wait_for_load_state('networkidle', timeout=60000)
            set_theme(page, 'light')
            time.sleep(5)
            page.screenshot(path=os.path.join(OUTPUT_DIR, "insider_trades_page.png"), full_page=True)
            print("  Captured Insider Trades.")
        except Exception as e:
            print(f"  Error capturing Insider Trades: {e}")

        # 9. System Logs (Dark Mode - Admin Feature)
        print("Capturing System Logs (Dark)...")
        try:
            page.goto(f"{BASE_URL}/logs", timeout=60000)
            page.wait_for_load_state('networkidle')
            set_theme(page, 'dark')
            page.screenshot(path=os.path.join(OUTPUT_DIR, "system_logs_page.png"), full_page=True)
            print("  Captured System Logs.")
        except Exception as e:
            print(f"  Error capturing System Logs: {e}")

        # 10. Ticker Details - AAPL (Light Mode - Attempt)
        # Trying a standard ticker that likely exists or will render gracefully
        print("Capturing Ticker Details - AAPL (Light)...")
        try:
            page.goto(f"{BASE_URL}/ticker/AAPL", timeout=60000)
            page.wait_for_load_state('networkidle')
            set_theme(page, 'light')
            try:
                # Wait for charts if they exist
                page.wait_for_selector(".js-plotly-plot", state="visible", timeout=10000)
                time.sleep(1)
            except:
                pass
            page.screenshot(path=os.path.join(OUTPUT_DIR, "ticker_details_aapl.png"), full_page=True)
            print("  Captured Ticker Details.")
        except Exception as e:
            print(f"  Error capturing Ticker Details: {e}")

        browser.close()
        print(f"Screenshots saved to {OUTPUT_DIR}")

if __name__ == "__main__":
    try:
        capture_screenshots()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
