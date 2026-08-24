import re

with open('tests/test_jobs_dividends_eligible_shares.py', 'r') as f:
    content = f.read()

new_content = re.sub(
    r'^from unittest\.mock import patch\n"""Tests for dividend eligibility',
    '''"""Tests for dividend eligibility vs trade_log conventions (positive shares, SELL in reason)."""\n\nfrom unittest.mock import patch''',
    content,
    flags=re.DOTALL
)

with open('tests/test_jobs_dividends_eligible_shares.py', 'w') as f:
    f.write(new_content)
