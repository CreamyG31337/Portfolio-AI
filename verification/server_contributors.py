from flask import Flask, render_template
import os
import sys

# Add web_dashboard to path
sys.path.append(os.path.abspath("web_dashboard"))

app = Flask(__name__,
            template_folder="../web_dashboard/templates",
            static_folder="../web_dashboard/static")

@app.route('/contributors')
def contributors():
    # Mock data required by templates
    return render_template('contributors.html',
                           user_theme="light",
                           current_page="contributors",
                           user_email="test@example.com",
                           build_version="1.0.0")

@app.route('/assets/<path:filename>')
def custom_static(filename):
    # Map assets to static
    # web_dashboard/templates/contributors.html calls /assets/js/contributors.js
    # web_dashboard/static structure: css/ js/ img/
    # If the URL is /assets/js/..., we serve from ../web_dashboard/static/js/...
    # But usually /assets/ matches static_folder if configured?
    # server.py used send_static_file, let's see.
    # If filename is 'js/contributors.js', it looks in ../web_dashboard/static/js/contributors.js?
    # Wait, the source is ts. The built js should be in static/js/ ?
    # web_dashboard/src/js/contributors.ts -> compiled to ?
    # Contributors.html script src is: /assets/js/contributors.js

    # Let's assume the build process (if run) puts files in static/js?
    # Or maybe we need to serve from src/js if not built?
    # Browsers can't run TS directly.
    # But I verified build passed. So JS should be there?
    # Let's check web_dashboard/static/js
    return app.send_static_file(filename)

# Mock API endpoints called by contributors.js to avoid 404s/errors in console
@app.route('/api/admin/contributors')
def api_contributors():
    return {"contributors": [
        {"id": "1", "name": "John Doe", "email": "john@example.com"},
        {"id": "2", "name": "Jane Smith", "email": "jane@example.com"}
    ]}

@app.route('/api/admin/users/list')
def api_users():
    return {"users": [
        {"user_id": "u1", "email": "user1@example.com", "full_name": "User One"}
    ]}

@app.route('/api/admin/contributor-access')
def api_access():
    return {"access": []}

@app.context_processor
def inject_globals():
    return dict(csrf_token=lambda: "mock_token")

if __name__ == '__main__':
    app.run(port=5001)
