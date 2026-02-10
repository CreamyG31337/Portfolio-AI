import os
import re

def audit_file(filepath):
    issues = []
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.splitlines()

    # Regex patterns
    style_attr_pattern = re.compile(r'style="([^"]*)"')
    style_tag_pattern = re.compile(r'<style>(.*?)</style>', re.DOTALL)
    hex_color_pattern = re.compile(r'#[0-9a-fA-F]{3,6}')
    rgb_pattern = re.compile(r'rgb\(\d+,\s*\d+,\s*\d+\)')

    # Check for style attributes
    for i, line in enumerate(lines):
        matches = style_attr_pattern.findall(line)
        for match in matches:
            # Ignore dynamic styles in JS/TS often used for width/height calculations
            if "display: none" in match or "display: block" in match:
                 # These are often toggled by JS, but should use hidden/block classes if possible.
                 # However, purely dynamic styles (like progress bars) are sometimes okay.
                 pass

            issues.append({
                "file": filepath,
                "line": i + 1,
                "issue": "Inline style detected",
                "content": match,
                "suggestion": "Use Tailwind utilities"
            })

        # Check for hex colors in text (excluding known vars or config)
        # This is a bit noisy, so maybe only if inside style="" or similar context?
        # Let's just flag them if they look like hardcoded colors in HTML/JS
        hex_matches = hex_color_pattern.findall(line)
        for match in hex_matches:
             # simplistic filter
             if match.lower() not in ['#fff', '#ffffff', '#000', '#000000']: # common ones
                 issues.append({
                    "file": filepath,
                    "line": i + 1,
                    "issue": "Hardcoded hex color",
                    "content": match,
                    "suggestion": "Use design tokens/Tailwind colors"
                })

    # Check for <style> blocks
    if style_tag_pattern.search(content):
        issues.append({
            "file": filepath,
            "line": 0,
            "issue": "<style> block detected",
            "content": "whole block",
            "suggestion": "Move to CSS or use Tailwind"
        })

    # Check for custom component-like class names that might be better as Flowbite
    # This is heuristic.
    custom_components = ['modal', 'dropdown', 'tooltip', 'alert', 'card', 'btn']
    for i, line in enumerate(lines):
        for comp in custom_components:
             # naive check for class="modal" without flowbite classes
             if f'class="{comp}"' in line or f"class='{comp}'" in line:
                  issues.append({
                    "file": filepath,
                    "line": i + 1,
                    "issue": f"Possible custom {comp}",
                    "content": line.strip()[:50] + "...",
                    "suggestion": f"Check if Flowbite {comp} can be used"
                })

    return issues

def scan_directory(directory, extensions):
    all_issues = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(extensions):
                filepath = os.path.join(root, file)
                all_issues.extend(audit_file(filepath))
    return all_issues

if __name__ == "__main__":
    extensions = ('.html', '.ts', '.js')
    issues = scan_directory('web_dashboard', extensions)

    # Print summary
    for issue in issues:
        print(f"{issue['file']}:{issue['line']} - {issue['issue']} - {issue['content']}")
