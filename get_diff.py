import subprocess
out = subprocess.check_output(['git', 'show', '87303f362dc86f63226473ace827d89967c7cff2', '--', 'tests/test_flask_watchlist_routes.py']).decode('utf-8')
print(out)
