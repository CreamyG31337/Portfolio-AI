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
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()

        # 1. Login Page (Light Mode)
        print("Capturing Login Page...")
        page.goto(f"{BASE_URL}/")
        # Ensure light mode on login page if possible (might default to system)
        # We can try to set it via local storage before reload, but usually login is neutral.
        page.screenshot(path=os.path.join(OUTPUT_DIR, "login_page.png"))

        # 2. Login
        login(page)

        # 3. Dashboard (Light Mode)
        print("Capturing Dashboard (Light)...")
        page.goto(f"{BASE_URL}/dashboard")
        page.wait_for_load_state('networkidle')
        set_theme(page, 'light')
        page.screenshot(path=os.path.join(OUTPUT_DIR, "dashboard_overview.png"))

        # 4. Settings (Light Mode)
        print("Capturing Settings (Light)...")
        page.goto(f"{BASE_URL}/settings")
        page.wait_for_load_state('networkidle')
        set_theme(page, 'light')
        page.screenshot(path=os.path.join(OUTPUT_DIR, "settings_page.png"))

        # 5. AI Research (Dark Mode - Feature)
        print("Capturing AI Research (Dark)...")
        page.goto(f"{BASE_URL}/research")
        page.wait_for_load_state('networkidle')
        set_theme(page, 'dark')
        page.screenshot(path=os.path.join(OUTPUT_DIR, "ai_research_page.png"))
        
        # 6. Dashboard (Dark Mode - Feature)
        print("Capturing Dashboard (Dark)...")
        page.goto(f"{BASE_URL}/dashboard")
        page.wait_for_load_state('networkidle')
        set_theme(page, 'dark')
        page.screenshot(path=os.path.join(OUTPUT_DIR, "dashboard_dark.png"))

        browser.close()
        print(f"Screenshots saved to {OUTPUT_DIR}")

if __name__ == "__main__":
    try:
        capture_screenshots()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
