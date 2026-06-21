import os
import re

def find_tailwind_issues(directory):
    issues = []

    # Simple regex to catch inline styles
    style_regex = re.compile(r'style\s*=\s*["\']([^"\']+)["\']')

    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(('.html', '.js', '.jsx', '.ts', '.tsx')):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        for i, line in enumerate(lines):
                            if 'style=' in line:
                                issues.append((filepath, i+1, line.strip()))
                except Exception as e:
                    print(f"Could not read {filepath}: {e}")

    return issues

if __name__ == '__main__':
    issues = find_tailwind_issues('web_dashboard/templates/')
    print(f"Found {len(issues)} lines with inline styles.")
    for issue in issues[:10]:
        print(f"{issue[0]}:{issue[1]} - {issue[2]}")
