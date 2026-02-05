from flask import Flask, render_template
import os
import sys

# Add web_dashboard to path
sys.path.append(os.path.abspath("web_dashboard"))

app = Flask(__name__,
            template_folder="../web_dashboard/templates",
            static_folder="../web_dashboard/static")

@app.route('/')
def dashboard():
    # Mock data required by templates
    return render_template('dashboard.html',
                           initial_fund="Test Fund",
                           build_timestamp="dev",
                           CSRF_ENABLED=False,
                           user_theme="light",
                           current_page="dashboard",
                           user_email="test@example.com",
                           build_version="1.0.0") # _footer_content might use build_version

@app.route('/jobs')
def jobs():
    return render_template('jobs.html',
                           current_page='jobs',
                           user_email="test@example.com",
                           user_theme="light",
                           build_version="1.0.0")

@app.route('/settings')
def settings():
    return render_template('settings.html',
                           current_page='settings',
                           user_email="test@example.com",
                           current_timezone="UTC",
                           current_currency="USD",
                           current_theme="light",
                           build_version="1.0.0")

@app.route('/assets/<path:filename>')
def custom_static(filename):
    return app.send_static_file(filename)

@app.context_processor
def inject_globals():
    return dict(csrf_token=lambda: "mock_token")

if __name__ == '__main__':
    app.run(port=5000)
