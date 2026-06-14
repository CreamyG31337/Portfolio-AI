import os
import re

for root, dirs, files in os.walk('web_dashboard/templates'):
    for file in files:
        if file.endswith('.html'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            # Replace Ghost Button Inconsistencies with `.btn-outline` or `.btn-outline-accent`
            # Look for exact class string that matches `.btn-outline` defined in `input.css`:
            # text-accent bg-transparent border border-accent hover:bg-accent/10 focus:ring-4 focus:ring-accent/30 font-medium rounded-lg text-sm px-4 py-2 focus:outline-hidden transition-colors duration-200

            # Also replace "shadow-lg p-6 mb-6 hover:-translate-y-0.5 transition-transform duration-200" with `.card` utility plus any remaining things
            # Actually `.card` in `input.css` is `@apply bg-dashboard-surface rounded-lg border border-border;`

            pass
