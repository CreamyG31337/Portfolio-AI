from playwright.sync_api import sync_playwright

def verify_toggles():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto("http://localhost:5000/")

            # Wait for content
            page.wait_for_selector("#use-solid-lines")

            # Screenshot
            page.screenshot(path="verification/dashboard_toggles.png", full_page=True)
            print("Screenshot taken: verification/dashboard_toggles.png")

            # Verify structure
            # 1. Solid Lines
            solid_lines_input = page.locator("#use-solid-lines")
            # Check if input has sr-only and peer
            classes = solid_lines_input.get_attribute("class")
            if classes and "peer" in classes and "sr-only" in classes:
                print("PASS: Solid Lines input has correct classes")
            else:
                print(f"FAIL: Solid Lines input has classes '{classes}'")

            # 2. Individual Holdings
            holdings_input = page.locator("#show-individual-holdings")
            classes = holdings_input.get_attribute("class")
            if classes and "peer" in classes and "sr-only" in classes:
                print("PASS: Holdings input has correct classes")
            else:
                print(f"FAIL: Holdings input has classes '{classes}'")

            # 3. Currency
            currency_input = page.locator("#inverse-exchange-rate")
            classes = currency_input.get_attribute("class")
            if classes and "peer" in classes and "sr-only" in classes:
                print("PASS: Currency input has correct classes")
            else:
                print(f"FAIL: Currency input has classes '{classes}'")

        except Exception as e:
            print(f"Error: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    verify_toggles()
