from flask import Flask, render_template, send_from_directory
import os
import sys

# Add web_dashboard to python path
sys.path.append(os.path.abspath('web_dashboard'))

app = Flask(__name__,
            template_folder='../web_dashboard/templates',
            static_folder='../web_dashboard/static')

@app.context_processor
def inject_globals():
    return {
        'csrf_token': lambda: 'mock-csrf-token',
        'build_timestamp': '2024-01-01',
        'user_theme': 'light',
        'current_page': 'ticker_details',
        'user_email': 'test@example.com'
    }

@app.route('/ticker_details')
def ticker_details():
    return render_template('ticker_details.html',
                           default_model='gpt-4',
                           model_config={'models': {'gpt-4': {'num_ctx': 8192}}})

@app.route('/assets/<path:path>')
def send_assets(path):
    return send_from_directory('../web_dashboard/static', path)

@app.route('/')
def index():
    return "Verification Server Running"

if __name__ == '__main__':
    app.run(port=5000)
