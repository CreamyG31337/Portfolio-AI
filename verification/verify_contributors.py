from playwright.sync_api import Page, expect, sync_playwright
import time

def test_contributors_tabs(page: Page):
    # 1. Arrange: Go to the contributors page.
    page.goto("http://localhost:5001/contributors")

    # 2. Assert initial state: "View Contributors" tab should be active/visible.
    # The tab button should have aria-selected="true"
    view_tab = page.get_by_role("tab", name="View Contributors")
    expect(view_tab).to_have_attribute("aria-selected", "true")

    # The panel should be visible
    view_panel = page.locator("#tab-content-view")
    expect(view_panel).to_be_visible()

    # 3. Act: Click "Split Contributor" tab.
    split_tab = page.get_by_role("tab", name="Split Contributor")
    split_tab.click()

    # 4. Assert: "Split Contributor" tab should be selected, panel visible.
    expect(split_tab).to_have_attribute("aria-selected", "true")
    split_panel = page.locator("#tab-content-split")
    expect(split_panel).to_be_visible()

    # "View Contributors" panel should be hidden
    expect(view_panel).not_to_be_visible()

    # 5. Screenshot
    page.screenshot(path="verification/contributors_tabs.png")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            test_contributors_tabs(page)
        finally:
            browser.close()
