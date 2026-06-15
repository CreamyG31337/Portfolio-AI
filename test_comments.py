import json

# Dummy data representing the tool's output to demonstrate logic. The actual tool's response is passed directly to the model.
try:
    with open('/home/jules/.jules/tools/read_pr_comments.py', 'r') as f:
        print(f.read()[:500])
except Exception as e:
    print(f"Error: {e}")
