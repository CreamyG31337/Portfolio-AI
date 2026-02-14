from playwright.sync_api import sync_playwright
import os

def verify_auth_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            # Navigate to auth page (port 5001)
            page.goto("http://localhost:5001/auth")

            # Wait for page to load
            page.wait_for_selector("h1")

            # Take screenshot
            output_path = os.path.join("verification", "auth_page.png")
            page.screenshot(path=output_path)
            print(f"Screenshot taken: {output_path}")

        except Exception as e:
            print(f"Error: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    verify_auth_page()
