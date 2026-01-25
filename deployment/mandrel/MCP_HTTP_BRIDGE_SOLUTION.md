# Mandrel MCP HTTP Transport Bridge Solution

## Problem

Mandrel's HTTP bridge uses a **custom REST API** format, but Cursor expects the **standard MCP HTTP transport** protocol (JSON-RPC 2.0). This causes connection failures:

- **Cursor expects**: `POST /` with JSON-RPC 2.0 messages
- **Mandrel provides**: `POST /mcp/tools/{toolName}` with REST API format

## Current State

✅ **Mandrel HTTP Bridge Works** (tested):
```bash
curl -X POST http://ts-ubuntu-server:8081/mcp/tools/mandrel_ping \
  -H "Content-Type: application/json" \
  -d '{"arguments":{}}'
# Returns: {"success":true,"result":{...}}
```

❌ **Cursor MCP HTTP Transport Fails**:
- Cursor tries: `POST /` with JSON-RPC format
- Gets: `404 Not found` error
- Falls back to SSE, also gets `404`

## Solution Options

### Option 1: HTTP Bridge/Proxy (Recommended)

Create a lightweight Node.js/Express proxy that:
1. Accepts MCP JSON-RPC requests from Cursor
2. Converts to Mandrel's REST API format
3. Converts responses back to MCP JSON-RPC format

**Pros:**
- No changes to Mandrel codebase
- Can be deployed as separate container
- Easy to maintain and update
- Works immediately

**Cons:**
- Additional service to maintain
- Small latency overhead

### Option 2: Add MCP HTTP Transport to Mandrel

Modify Mandrel's `healthServer.ts` to add a proper MCP HTTP transport endpoint.

**Pros:**
- Native support
- No proxy needed

**Cons:**
- Requires modifying Mandrel source code
- Need to maintain patch across updates
- More complex implementation

### Option 3: STDIO Transport with SSH Tunneling

Use Mandrel's native STDIO transport via SSH tunnel.

**Pros:**
- Uses native MCP protocol
- No code changes needed

**Cons:**
- Complex setup
- Requires SSH tunnel management
- Less convenient than HTTP

## Recommended Implementation: HTTP Bridge

### Architecture

```
Cursor IDE
    ↓ (MCP JSON-RPC)
HTTP Bridge (Port 8082)
    ↓ (REST API)
Mandrel Server (Port 8081)
```

### Bridge Endpoints

**MCP Endpoint** (for Cursor):
- `POST /` - Accepts JSON-RPC 2.0 messages
- `GET /sse` - Server-Sent Events (optional)

**Conversion Logic**:
- JSON-RPC `tools/list` → `GET /mcp/tools/schemas`
- JSON-RPC `tools/call` → `POST /mcp/tools/{toolName}`
- Convert responses to JSON-RPC format

### Implementation Plan

1. **Create bridge service** (`deployment/mandrel/mcp-bridge/`)
2. **Add to docker-compose.yml** as separate service
3. **Update Cursor config** to point to bridge (port 8082)
4. **Test and document**

### Next Steps

1. Create the HTTP bridge service
2. Deploy alongside Mandrel
3. Update Cursor configuration
4. Test connection

## References

- [MCP HTTP Transport Specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [Mandrel GitHub](https://github.com/RidgetopAi/mandrel)
- [MCP JSON-RPC Protocol](https://mcpcat.io/guides/understanding-json-rpc-protocol-mcp)
