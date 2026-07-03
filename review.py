import subprocess
import os

result = subprocess.run(["git", "log", "--since='12 hours ago'"], capture_output=True, text=True)

print("Recent commits:")
print(result.stdout)
