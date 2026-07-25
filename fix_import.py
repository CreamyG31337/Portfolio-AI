import re

with open('web_dashboard/routes/admin_routes.py', 'r') as f:
    content = f.read()

import_statement = "from supabase_pagination import fetch_all_rows\n"

# Add the import at the top of the file after the other imports
match = re.search(r"import [\w\., ]+", content)
if match:
    # Insert after first import block
    # Simple workaround: Just add it right after `from flask import ...`
    content = content.replace("from flask import ", "from supabase_pagination import fetch_all_rows\nfrom flask import ", 1)

with open('web_dashboard/routes/admin_routes.py', 'w') as f:
    f.write(content)
