# Settings Page Migration Summary

The Settings page has been successfully migrated from Streamlit to Flask. This document summarizes what was done and how to test it.

## What Was Changed

### New Files Created

1. **`flask_auth_utils.py`** - Flask authentication utilities that read `auth_token` cookie (same as Streamlit)
2. **`shared_navigation.py`** - Navigation component that tracks migrated pages
3. **`templates/settings.html`** - Flask template for Settings page
4. **`static/js/settings.js`** - JavaScript for AJAX form submissions
5. **`CADDYFILE_MIGRATION.md`** - Guide for updating Caddy configuration

### Modified Files

1. **`user_preferences.py`** - Made Flask-compatible (removed Streamlit-only dependencies)
2. **`app.py`** - Added `/settings` route and API endpoints (`/api/settings/timezone`, `/api/settings/currency`, `/api/settings/theme`)
3. **`auth.py`** - Updated `@require_auth` decorator to support both `auth_token` (Streamlit) and `session_token` (Flask legacy) cookies
4. **`navigation.py`** - Updated to check if Settings is migrated and link to Flask route
5. **`pages/settings.py`** - Added redirect to Flask version

## How It Works

1. **Shared Authentication**: Both Flask and Streamlit use the same `auth_token` cookie, enabling seamless navigation
2. **Automatic Redirect**: Streamlit Settings page automatically redirects to Flask version
3. **Navigation Updates**: Streamlit navigation sidebar links to Flask Settings when migrated
4. **AJAX Forms**: Flask Settings page uses AJAX for form submissions (no full page reload)

## Testing Checklist

### Before Starting Flask

1. ✅ Verify Streamlit is running on port 8501
2. ✅ Verify all dependencies are installed
3. ✅ Verify Supabase connection works

### Starting Flask Server

1. Navigate to `web_dashboard` directory
2. Activate virtual environment: `.\venv\Scripts\activate` (Windows) or `source venv/bin/activate` (Linux/Mac)
3. Start Flask: `python app.py`
4. Flask should start on port 5001 (to avoid conflict with NFT calculator on port 5000)
5. You can override the port with: `FLASK_PORT=5001 python app.py`

### Testing Settings Page

1. **Access Settings from Streamlit**:
   - Navigate to any Streamlit page
   - Click "User Preferences" in sidebar
   - Should redirect to Flask Settings page at `/settings`

2. **Direct Access**:
   - Navigate directly to `http://localhost:5001/settings` (or your production URL `/settings`)
   - Should load Flask Settings page

3. **Test Timezone**:
   - Select a timezone
   - Click "Save Timezone"
   - Should see success message
   - Verify preference is saved (check database or reload page)

4. **Test Currency**:
   - Select a currency
   - Click "Save Currency"
   - Should see success message

5. **Test Theme**:
   - Select a theme
   - Click "Save Theme"
   - Should see success message

6. **Test Navigation**:
   - From Flask Settings, click "Dashboard" link
   - Should navigate to Streamlit dashboard
   - From Streamlit, click "User Preferences"
   - Should navigate back to Flask Settings

### Production Deployment

1. **Update Caddyfile** (see `CADDYFILE_MIGRATION.md`):
   - Add `/settings` route to Flask (port 5000)
   - Add `/api/*` route to Flask (for API endpoints)
   - Reload Caddy: `caddy reload`

2. **Flask Container Deployment**:
   - Flask container is automatically deployed via Woodpecker CI/CD (see `.woodpecker.yml`)
   - Container name: `trading-dashboard-flask`
   - Runs on port 5001 (NFT calculator uses 5000)
   - Uses same environment variables as Streamlit container
   - Container is built from `web_dashboard/Dockerfile.flask`

3. **Verify All Servers Running**:
   - Streamlit: `http://localhost:8501` (or check process)
   - Trading Dashboard Flask: `http://localhost:5001` (or check process)
   - NFT Calculator Flask: `http://localhost:5000` (existing, separate app)

## Troubleshooting

### Settings page shows "Authentication required"

- **Cause**: `auth_token` cookie not being read
- **Fix**: Check that cookie is set (check browser dev tools)
- **Fix**: Verify `@require_auth` decorator is working (check Flask logs)

### Settings page redirects to login

- **Cause**: Token expired or invalid
- **Fix**: Log in again through Streamlit to refresh token
- **Fix**: Check token expiration in browser dev tools

### AJAX requests fail

- **Cause**: CORS or authentication issues
- **Fix**: Check browser console for errors
- **Fix**: Verify API endpoints are accessible
- **Fix**: Check Flask logs for errors

### Preferences not saving

- **Cause**: Database connection issue
- **Fix**: Check Supabase connection
- **Fix**: Verify user has valid `user_id`
- **Fix**: Check Flask logs for database errors

## Next Steps

Once Settings page migration is verified working:

1. Migrate next page (e.g., Dashboard, Research Repository)
2. Add page to `MIGRATED_PAGES` in `shared_navigation.py`
3. Update Caddyfile with new route
4. Test navigation between Flask and Streamlit pages
5. Repeat until all pages migrated

## Files Reference

- **Flask Settings**: `web_dashboard/templates/settings.html`
- **Flask Routes**: `web_dashboard/app.py` (lines ~1186-1250)
- **API Endpoints**: `web_dashboard/app.py` (routes starting with `/api/settings/`)
- **Auth Utils**: `web_dashboard/flask_auth_utils.py`
- **User Preferences**: `web_dashboard/user_preferences.py`
- **Navigation**: `web_dashboard/navigation.py` and `web_dashboard/shared_navigation.py`
