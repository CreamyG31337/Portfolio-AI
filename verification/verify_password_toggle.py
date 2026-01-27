import os
from playwright.sync_api import sync_playwright, expect

def test_password_toggle():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("Navigating to settings...")
        page.goto("http://127.0.0.1:5000/settings")

        # Verify page loaded
        expect(page).to_have_title("User Preferences - Portfolio Dashboard")

        # Locate the new password input
        new_password_input = page.locator("#new-password")

        # Locate the toggle button
        toggle_btn = page.locator("[data-toggle-password='new-password']")

        # Check initial state (should be password)
        print("Checking initial state...")
        expect(new_password_input).to_have_attribute("type", "password")

        # Click toggle
        print("Clicking toggle...")
        toggle_btn.click()

        # Check toggled state (should be text)
        print("Checking toggled state...")
        expect(new_password_input).to_have_attribute("type", "text")

        # Click toggle again
        print("Clicking toggle again...")
        toggle_btn.click()

        # Check reverted state (should be password)
        print("Checking reverted state...")
        expect(new_password_input).to_have_attribute("type", "password")

        # Take screenshot
        os.makedirs("verification", exist_ok=True)
        page.screenshot(path="verification/password_toggle.png")
        print("Screenshot saved to verification/password_toggle.png")

        browser.close()

if __name__ == "__main__":
    test_password_toggle()
