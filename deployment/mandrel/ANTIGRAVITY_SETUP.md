# Mandrel Setup for Antigravity (VS Code Fork)

## Quick Setup

Antigravity uses the same MCP configuration format as Cursor and VS Code.

### Step 1: Configure MCP Server

**Option A: Via Antigravity UI (Recommended)**

1. Open Antigravity
2. Click the "..." dropdown at the top of the agent panel
3. Select "Manage MCP Servers"
4. Click "View raw config" or "Add Server"
5. Add Mandrel configuration:

```json
{
  "mcpServers": {
    "mandrel": {
      "url": "http://your-server:8082",
      "transport": "http"
    }
  }
}
```

**Option B: Via Config File**

1. Locate Antigravity's MCP config file (typically `~/.antigravity/mcp.json` or similar)
2. Add the Mandrel server configuration (see Option A for format)
3. Restart Antigravity

### Step 2: Important Configuration Details

**Port Configuration:**
- **Use port `8082`** - This is the MCP HTTP Bridge (required for MCP protocol)
- **Do NOT use port `8081`** - That's Mandrel's direct REST API (not MCP-compliant)

**Server URL:**
- Replace `your-server` with your actual server hostname/IP
- For Tailscale: Use your Tailscale hostname (e.g., `ts-ubuntu-server`)
- For local testing: Use `localhost` if running locally

**Example:**
```json
{
  "mcpServers": {
    "mandrel": {
      "url": "http://ts-ubuntu-server:8082",
      "transport": "http"
    }
  }
}
```

### Step 3: Restart and Test

1. **Restart Antigravity** to load the new MCP server configuration
2. **Test connection:**
   - Ask the AI: "Test Mandrel connection - use mandrel_ping"
   - Or manually: `curl http://your-server:8082/health`

### Step 4: Verify Tools Are Available

After restarting, you should see Mandrel tools available in Antigravity:
- Check the agent panel for available tools
- Try: "Use mandrel_ping to test the connection"
- All 27 Mandrel tools should be discoverable

## Troubleshooting

**Connection fails:**
- Verify bridge is running: `curl http://your-server:8082/health`
- Check server is reachable: `ping your-server`
- Verify port 8082 is accessible (not blocked by firewall)

**Tools not appearing:**
- Restart Antigravity after configuration changes
- Check Antigravity logs for MCP connection errors
- Verify the config file syntax is valid JSON

**"Method not found" errors:**
- Ensure you're using port `8082` (bridge), not `8081` (direct API)
- Bridge handles MCP protocol conversion automatically

## Configuration File Locations

Antigravity may store MCP config in:
- `~/.antigravity/mcp.json`
- `~/.config/antigravity/mcp.json`
- Workspace-specific: `.vscode/mcp.json` (if supported)

Check Antigravity documentation for the exact location.

## Available Tools

Once connected, you'll have access to all 27 Mandrel tools:

**System:** `mandrel_ping`, `mandrel_status`, `mandrel_help`, `mandrel_explain`, `mandrel_examples`

**Context:** `context_store`, `context_search`, `context_get_recent`, `context_stats`

**Projects:** `project_list`, `project_create`, `project_switch`, `project_current`, `project_info`

**Decisions:** `decision_record`, `decision_search`, `decision_update`, `decision_stats`

**Tasks:** `task_create`, `task_list`, `task_update`, `task_details`, `task_bulk_update`, `task_progress_summary`

**Search:** `smart_search`, `get_recommendations`, `project_insights`

See `AGENTS.md` for detailed tool documentation.
