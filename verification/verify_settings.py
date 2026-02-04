import http.server
import socketserver
import threading
import time
from playwright.sync_api import sync_playwright, expect

PORT = 8000
Handler = http.server.SimpleHTTPRequestHandler

def start_server():
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving at port {PORT}")
        httpd.serve_forever()

def verify_settings():
    # Start server in background
    thread = threading.Thread(target=start_server, daemon=True)
    thread.start()
    time.sleep(1) # Wait for server to start

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        url = f"http://localhost:{PORT}/verification/mock_settings.html"
        print(f"Navigating to {url}")
        page.goto(url)

        # 1. Verify role="alert" exists
        print("Verifying role='alert'...")
        password_success = page.locator("#password-success")
        expect(password_success).to_have_attribute("role", "alert")
        print("✓ role='alert' found on password-success")

        timezone_success = page.locator("#timezone-success")
        expect(timezone_success).to_have_attribute("role", "alert")
        print("✓ role='alert' found on timezone-success")

        # 2. Verify Spinner
        print("Verifying spinner...")
        page.fill("#new-password", "password123")
        page.fill("#confirm-password", "password123")

        submit_btn = page.locator("#change-password-btn")

        # Click and verify spinner immediately
        submit_btn.click()

        # We expect the inner HTML to change to include fa-spinner
        # The mock fetch has 1s delay, so we have time to check
        spinner = submit_btn.locator(".fa-spinner")
        expect(spinner).to_be_visible()
        print("✓ Spinner visible during submission")

        # Take screenshot while spinner is visible
        page.screenshot(path="verification/verification.png")
        print("Screenshot saved to verification/verification.png")

        browser.close()

if __name__ == "__main__":
    verify_settings()
