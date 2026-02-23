import threading
import time
import os
import sys
from flask import Flask, render_template

# Ensure web_dashboard is in path if needed, though we use relative paths for templates/static
sys.path.append(os.path.abspath("web_dashboard"))

app = Flask(__name__,
            template_folder="../web_dashboard/templates",
            static_folder="../web_dashboard/static")

@app.route('/')
def auth():
    return render_template('auth.html',
                           CSRF_ENABLED=True,
                           build_timestamp="Dev Build")

@app.route('/assets/<path:filename>')
def custom_static(filename):
    return app.send_static_file(filename)

@app.context_processor
def inject_globals():
    return dict(csrf_token=lambda: "mock_token_123")

def run_server():
    app.run(port=5002, use_reloader=False)

# Playwright part
from playwright.sync_api import sync_playwright

def verify():
    # Start server
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2) # Give server time to start

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto("http://localhost:5002/")

            # Wait for form
            page.wait_for_selector("#login-form")

            # Check classes on email input
            email_input = page.locator("#login-email")
            classes = email_input.get_attribute("class")
            print(f"Login Email Classes: {classes}")

            if "form-input-theme" in classes:
                print("SUCCESS: .form-input-theme class found on login email.")
            else:
                print("FAILURE: .form-input-theme class NOT found on login email.")

            # Check classes on login button
            login_btn = page.locator("#login-btn")
            btn_classes = login_btn.get_attribute("class")
            print(f"Login Button Classes: {btn_classes}")

            if "btn-outline" in btn_classes:
                print("SUCCESS: .btn-outline class found on login button.")
            else:
                print("FAILURE: .btn-outline class NOT found on login button.")

            # Screenshot
            os.makedirs("verification", exist_ok=True)
            output_path = os.path.join("verification", "auth_fix_verification.png")
            page.screenshot(path=output_path)
            print(f"Screenshot saved to {output_path}")

        except Exception as e:
            print(f"Error during verification: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    verify()
