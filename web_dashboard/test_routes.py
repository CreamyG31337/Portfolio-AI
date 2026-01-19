#!/usr/bin/env python3
"""Test script to verify admin routes work correctly"""

from flask import Flask
app = Flask(__name__)
app.secret_key = "test"

# Register admin blueprint
print("Registering admin blueprint...")
try:
    from routes.admin_routes import admin_bp
    app.register_blueprint(admin_bp)
    print("✅ Admin blueprint registered successfully")
except Exception as e:
    print(f"❌ Failed to register admin blueprint: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

# Print all registered routes
print("\n=== Registered Admin Routes ===")
admin_routes = [r for r in app.url_map.iter_rules() if 'admin' in r.endpoint]
for rule in admin_routes:
    methods = ', '.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
    print(f"  {rule.rule:50} [{methods:20}] -> {rule.endpoint}")

# Test specific routes that you mentioned are 404ing
print("\n=== Testing Specific Routes ===")
test_routes = [
    '/api/admin/scheduler/status',
    '/logs',
    '/admin/users',
    '/admin/scheduler',
    '/admin/system',
]

for route in test_routes:
    matching_rules = [r for r in app.url_map.iter_rules() if r.rule == route]
    if matching_rules:
        rule = matching_rules[0]
        methods = ', '.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
        print(f"✅ {route:40} [{methods}]")
    else:
        print(f"❌ {route:40} NOT FOUND")
        
print(f"\n=== Total Routes: {len(list(app.url_map.iter_rules()))} ===")
