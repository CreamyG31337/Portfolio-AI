# Mandrel Deployment Architecture: Why We Have This Issue

## The Problem

We deployed Mandrel **remotely** (on Ubuntu server) and tried to connect via **HTTP transport**, but Mandrel doesn't fully implement MCP HTTP transport - it only has a REST API bridge.

## Standard MCP Server Deployment Models

### Model 1: Local Installation with STDIO (Standard)

**How it works:**
- MCP server runs **locally** on your machine
- Cursor spawns the server process directly
- Communication via STDIO (standard input/output pipes)
- **No network required** - process-to-process communication

**Configuration in Cursor:**
```json
{
  "mcpServers": {
    "mandrel": {
      "command": "node",
      "args": ["/path/to/mandrel/mcp-server/src/main.ts"],
      "transport": "stdio"
    }
  }
}
```

**Pros:**
- ✅ Native MCP protocol support
- ✅ Lowest latency
- ✅ No network configuration
- ✅ Standard practice for MCP servers
- ✅ Works out of the box

**Cons:**
- ❌ Must run on same machine as Cursor
- ❌ Requires Node.js installed locally
- ❌ Requires PostgreSQL accessible locally (or remote DB connection)

### Model 2: Remote Installation with HTTP Transport (What We Did)

**How it works:**
- MCP server runs on **remote server**
- Cursor connects via HTTP
- Requires proper MCP HTTP transport implementation

**Configuration in Cursor:**
```json
{
  "mcpServers": {
    "mandrel": {
      "url": "http://your-server:8081",
      "transport": "http"
    }
  }
}
```

**Pros:**
- ✅ Can run on dedicated server
- ✅ Can share across multiple clients
- ✅ Better for enterprise/team use

**Cons:**
- ❌ Requires proper MCP HTTP transport implementation
- ❌ **Mandrel doesn't fully support this** (only has REST API)
- ❌ Higher latency
- ❌ More complex setup

## Why We Have This Issue

**We chose Model 2 (remote HTTP) but:**
1. Mandrel's HTTP bridge is a **REST API**, not a proper **MCP HTTP transport**
2. Cursor expects **JSON-RPC 2.0** format via `POST /`
3. Mandrel provides **REST endpoints** like `POST /mcp/tools/{toolName}`
4. **Mismatch** = Connection fails

## What We Should Have Done

### Option A: Local Installation (Recommended for Single User)

**Install Mandrel locally on Windows:**
1. Install Node.js on Windows
2. Clone Mandrel repository
3. Configure PostgreSQL connection (can still use remote DB)
4. Use STDIO transport in Cursor

**Pros:**
- ✅ Works immediately (no HTTP transport needed)
- ✅ Standard MCP setup
- ✅ Lower latency
- ✅ No bridge/proxy needed

**Cons:**
- ❌ Requires local Node.js installation
- ❌ Mandrel process runs on your machine
- ❌ Can't easily share with team

### Option B: Remote with HTTP Bridge (What We're Building)

**Keep remote deployment but add HTTP bridge:**
1. Keep Mandrel on Ubuntu server
2. Add HTTP bridge service to convert MCP JSON-RPC ↔ REST API
3. Point Cursor to bridge instead of Mandrel directly

**Pros:**
- ✅ Keeps remote deployment
- ✅ Can share with team
- ✅ No local Node.js needed

**Cons:**
- ❌ Additional service to maintain
- ❌ Extra latency hop
- ❌ More complex architecture

## Recommendation

**For single-user development:**
- **Use local installation with STDIO** (Option A)
- Simpler, standard, works immediately

**For team/enterprise:**
- **Use remote with HTTP bridge** (Option B)
- More complex but enables sharing

## Next Steps

1. **Decide on deployment model:**
   - Local (STDIO) - simpler, standard
   - Remote (HTTP bridge) - more complex but shareable

2. **If local:**
   - Install Mandrel on Windows
   - Configure STDIO transport in Cursor
   - Connect to remote PostgreSQL

3. **If remote:**
   - Build HTTP bridge service
   - Deploy alongside Mandrel
   - Update Cursor config

## References

- [MCP Transport Comparison](https://mcpcat.io/guides/comparing-stdio-sse-streamablehttp)
- [Cursor MCP Configuration](https://cursor.com/docs/context/mcp)
- [MCP HTTP Transport Spec](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
