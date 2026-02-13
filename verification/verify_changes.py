from playwright.sync_api import sync_playwright, expect
import time

def verify_changes(page):
    # 1. Verify Jobs Page Accessibility
    print("Navigating to Jobs page...")

    # Mock Jobs API
    page.route("**/api/admin/scheduler/status", lambda route: route.fulfill(
        status=200,
        content_type="application/json",
        body='''{
            "scheduler_running": true,
            "jobs": [
                {
                    "id": "job1",
                    "name": "Test Job",
                    "next_run": "2023-01-01T12:00:00",
                    "trigger": "interval[30s]",
                    "is_running": false,
                    "last_error": null,
                    "parameters": {"test": {"type": "text"}}
                }
            ],
            "is_admin": true
        }'''
    ))

    page.goto("http://localhost:5000/jobs")

    # Wait for job card to appear
    page.wait_for_selector(".job-card")

    # Check for Pause button aria-label
    print("Checking for Pause button aria-label...")
    pause_btn = page.locator('button[title="Pause Job"]')
    expect(pause_btn).to_have_attribute("aria-label", "Pause Job")

    # Check for Parameters button aria-label (Run with Parameters)
    print("Checking for Parameters button aria-label...")
    params_btn = page.locator('button[title="Run with Parameters"]')
    expect(params_btn).to_have_attribute("aria-label", "Run with Parameters")

    # Click parameters to open form
    params_btn.click()

    # Check for Close Parameters button aria-label
    print("Checking for Close Parameters button aria-label...")
    close_btn = page.locator('button[aria-label="Close parameters"]')
    expect(close_btn).to_be_visible()

    page.screenshot(path="verification/jobs_verified.png")
    print("Jobs page verification done.")

    # 2. Verify Settings Page Button State
    print("Navigating to Settings page...")
    page.goto("http://localhost:5000/settings")

    # Mock password change API
    page.route("**/api/auth/change-password", lambda route: route.fulfill(
        status=200,
        content_type="application/json",
        body='{"success": true}'
    ))

    # Type password
    page.fill("#new-password", "password123")
    page.fill("#confirm-password", "password123")

    # Get button
    btn = page.locator("#change-password-btn")
    # Clean whitespace for comparison
    original_html = btn.inner_html().strip()
    print(f"Original Button HTML: '{original_html}'")

    # Click
    btn.click()

    # Wait for success message
    expect(page.locator("#password-success")).to_be_visible()

    # Check if button HTML is restored
    final_html = btn.inner_html().strip()
    print(f"Final Button HTML: '{final_html}'")

    assert original_html == final_html, f"Button HTML mismatch! Original: {original_html}, Final: {final_html}"

    page.screenshot(path="verification/settings_verified.png")
    print("Settings page verification done.")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            verify_changes(page)
        except Exception as e:
            print(f"Verification failed: {e}")
            page.screenshot(path="verification/failure.png")
        finally:
            browser.close()
