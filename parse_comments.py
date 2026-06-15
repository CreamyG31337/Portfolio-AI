import sys
try:
    with open('/tmp/pr_comments_output.txt', 'r') as f:
        print(f.read()[-500:])
except Exception as e:
    print(f"Error: {e}")
