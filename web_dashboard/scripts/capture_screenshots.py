import os
import time
import sys
from playwright.sync_api import sync_playwright

# Configuration
BASE_URL = "https://ai-trading.drifting.space"
EMAIL = "guest.test@tradingbot.local"
PASSWORD = "316hejN^%vg^vG!BrL7n"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "images")

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def set_theme(page, theme):
    print(f"  Setting theme to: {theme}")
    page.evaluate(f"window.themeManager.setTheme('{theme}')")
    time.sleep(1) # Allow transition

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
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
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
            page.select_option('#global-fund-select', label='TFSA')
            page.wait_for_load_state('networkidle')
            time.sleep(2) # Extra time for UI update
        except Exception as e:
            print(f"Warning: Could not select TFSA: {e}")

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

        browser.close()
        print(f"Screenshots saved to {OUTPUT_DIR}")

if __name__ == "__main__":
    try:
        capture_screenshots()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
