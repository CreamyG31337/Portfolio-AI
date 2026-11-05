with open('web_dashboard/src/js/users.ts', 'r') as f:
    content = f.read()

content = content.replace('bg-black bg-opacity-50', 'bg-black/50')

with open('web_dashboard/src/js/users.ts', 'w') as f:
    f.write(content)
