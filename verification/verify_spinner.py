from playwright.sync_api import sync_playwright
import time

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Navigate
        page.goto("http://127.0.0.1:5000/ticker_details")

        # 1. Verify Spinner
        # Reveal spinner
        page.eval_on_selector("#loading-spinner", "el => el.classList.remove('hidden')")

        # Take screenshot of spinner
        spinner = page.locator("#loading-spinner")
        spinner.screenshot(path="verification/spinner.png")
        print("Captured spinner.png")

        # Hide spinner again
        page.eval_on_selector("#loading-spinner", "el => el.classList.add('hidden')")

        # 2. Verify Tooltip
        # Find the P/E ratio tooltip icon
        # It's inside a group relative inline-block
        # Text: Trailing P/E

        # We need to make sure the tooltip is visible.
        # The tooltip uses group-hover:visible.
        # Playwright hover should trigger it.

        # Let's target the info circle next to "Trailing P/E"
        # Since I can't easily select by text "Trailing P/E" parent then find icon, I'll use a selector.
        # It's inside #basic-info-section, but that section is hidden by default!

        # I need to show #basic-info-section first.
        page.eval_on_selector("#basic-info-section", "el => el.classList.remove('hidden')")

        # Now hover the icon
        # The structure is: text "Trailing P/E" -> div.group -> i.fa-info-circle
        # I'll select the .fa-info-circle inside the first .bg-dashboard-background inside .grid

        icons = page.locator(".fa-info-circle")
        first_icon = icons.first
        first_icon.hover()

        # Wait for tooltip transition (200ms)
        time.sleep(0.5)

        # Screenshot the tooltip area
        # The tooltip is absolute positioned relative to the group div.
        # capturing the whole basic info card
        card = page.locator("#basic-info-section")
        card.screenshot(path="verification/tooltip.png")
        print("Captured tooltip.png")

        browser.close()

if __name__ == "__main__":
    run()
