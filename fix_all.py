import re
import os

# 1. Fix congress_positions.ts
file_path = 'web_dashboard/src/js/congress_positions.ts'
with open(file_path, 'r') as f:
    content = f.read()

old_return = """            // TODO(palette): Replace hardcoded hex colors + inline styles here (and in the
            // Dollar Return renderer below) with semantic Tailwind tokens so dark themes work,
            // e.g. `<span class="font-semibold ${cls}">` where cls is text-theme-success-text /
            // text-theme-error-text / text-text-secondary. (Palette audit PR #347, item 1)
            cellRenderer: (params: any) => {
                if (params.value == null) return '--';
                const val = params.value;
                const color = val > 0 ? '#4ade80' : val < 0 ? '#f87171' : '#9ca3af';
                const sign = val > 0 ? '+' : '';
                return `<span style="color: ${color}; font-weight: 600;">${sign}${val.toFixed(1)}%</span>`;
            },"""

new_return = """            cellRenderer: (params: any) => {
                if (params.value == null) return '--';
                const val = params.value;
                const cls = val > 0 ? 'text-theme-success-text' : val < 0 ? 'text-theme-error-text' : 'text-text-secondary';
                const sign = val > 0 ? '+' : '';
                return `<span class="font-semibold ${cls}">${sign}${val.toFixed(1)}%</span>`;
            },"""

content = content.replace(old_return, new_return)

old_pnl = """            cellRenderer: (params: any) => {
                if (params.value == null) return '--';
                const val = params.value;
                const color = val > 0 ? '#4ade80' : val < 0 ? '#f87171' : '#9ca3af';
                return `<span style="color: ${color}; font-weight: 600;">${formatDollars(val)}</span>`;
            },"""

new_pnl = """            cellRenderer: (params: any) => {
                if (params.value == null) return '--';
                const val = params.value;
                const cls = val > 0 ? 'text-theme-success-text' : val < 0 ? 'text-theme-error-text' : 'text-text-secondary';
                return `<span class="font-semibold ${cls}">${formatDollars(val)}</span>`;
            },"""

content = content.replace(old_pnl, new_pnl)

with open(file_path, 'w') as f:
    f.write(content)
print("Fixed congress_positions.ts")


# 2. Fix CSS and auth.html (.btn-outline-accent)
auth_file = 'web_dashboard/templates/auth.html'
with open(auth_file, 'r') as f:
    auth_content = f.read()

auth_content = auth_content.replace('btn-outline-accent', 'btn-outline')

with open(auth_file, 'w') as f:
    f.write(auth_content)
print("Fixed auth.html")

css_path = 'web_dashboard/static/css/input.css'
with open(css_path, 'r') as f:
    css_content = f.read()

old_btn = """    /* Standardized button styles */
    /* TODO(palette): `.btn-outline` and `.btn-outline-accent` below have identical @apply
       declarations (duplicate utility). Collapse to one class (or make `-accent` differ
       intentionally) and update call sites. (Palette audit PR #365) */
    .btn-outline {
        @apply text-accent bg-transparent border border-accent hover:bg-accent/10 focus:ring-4 focus:ring-accent/30 font-medium rounded-lg text-sm px-4 py-2 focus:outline-hidden transition-colors duration-200;
    }

    .btn-outline-accent {
        @apply text-accent bg-transparent border border-accent hover:bg-accent/10 focus:ring-4 focus:ring-accent/30 font-medium rounded-lg text-sm px-4 py-2 focus:outline-hidden transition-colors duration-200;
    }"""

new_btn = """    /* Standardized button styles */
    .btn-outline {
        @apply text-accent bg-transparent border border-accent hover:bg-accent/10 focus:ring-4 focus:ring-accent/30 font-medium rounded-lg text-sm px-4 py-2 focus:outline-hidden transition-colors duration-200;
    }"""

css_content = css_content.replace(old_btn, new_btn)


# 3. Fix .card abstraction
def replacer(match):
    classes = match.group(1).split()
    if 'card' in classes:
        classes.remove('card')
        classes.extend(['bg-dashboard-surface', 'rounded-lg', 'border', 'border-border'])
    return 'class="' + ' '.join(classes) + '"'

for root, _, files in os.walk('web_dashboard/templates'):
    for file in files:
        if file.endswith('.html'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r') as f:
                html_content = f.read()
            new_html_content = re.sub(r'class="([^"]*?)"', replacer, html_content)
            if new_html_content != html_content:
                with open(filepath, 'w') as f:
                    f.write(new_html_content)
                print(f"Updated {filepath}")

for root, _, files in os.walk('web_dashboard/src/js'):
    for file in files:
        if file.endswith('.ts'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r') as f:
                ts_content = f.read()
            new_ts_content = re.sub(r'class="([^"]*?)"', replacer, ts_content)
            if new_ts_content != ts_content:
                with open(filepath, 'w') as f:
                    f.write(new_ts_content)
                print(f"Updated {filepath}")

old_card = """    /* TODO(palette): `.card` is a thin `@apply` wrapper over 4 utilities. Audit flagged
       it as @apply overuse vs utility-first. Evaluate inlining these utilities at call
       sites (or keep only if reused widely enough to justify the abstraction). (Palette audit PR #365) */
    .card {
        @apply bg-dashboard-surface rounded-lg border border-border;
    }"""

css_content = css_content.replace(old_card, "")

with open(css_path, 'w') as f:
    f.write(css_content)
print("Fixed input.css")
