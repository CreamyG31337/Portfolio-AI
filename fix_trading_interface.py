with open('portfolio/trading_interface.py', 'r') as f:
    content = f.read()

content = content.replace("name = contributor['Contributor']", "name = contributor.Contributor")
content = content.replace("email = contributor['Email'] if pd.notna(contributor['Email']) and contributor['Email'] else \"No email\"", "email = contributor.Email if pd.notna(contributor.Email) and contributor.Email else \"No email\"")

with open('portfolio/trading_interface.py', 'w') as f:
    f.write(content)
