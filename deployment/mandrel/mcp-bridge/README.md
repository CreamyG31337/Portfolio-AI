# MCP HTTP Bridge

HTTP bridge service that converts between MCP JSON-RPC 2.0 protocol (used by Cursor) and Mandrel's REST API format.

## Purpose

Mandrel's HTTP bridge uses a custom REST API format, but Cursor expects the standard MCP HTTP transport protocol (JSON-RPC 2.0). This bridge translates between the two formats, enabling Cursor to connect to remote Mandrel servers.

## Architecture

```
Cursor IDE
    ↓ (JSON-RPC 2.0)
MCP Bridge (Port 8082)
    ↓ (REST API)
Mandrel Server (Port 8081)
```

## Protocol Conversion

### tools/list

**MCP JSON-RPC Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list",
  "params": {}
}
```

**Converts to Mandrel REST:**
```
GET http://mandrel-mcp:8081/mcp/tools/schemas
```

**Converts Mandrel Response to MCP JSON-RPC:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [...]
  }
}
```

### tools/call

**MCP JSON-RPC Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "mandrel_ping",
    "arguments": {}
  }
}
```

**Converts to Mandrel REST:**
```
POST http://mandrel-mcp:8081/mcp/tools/mandrel_ping
Body: {"arguments": {}}
```

**Converts Mandrel Response to MCP JSON-RPC:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [...]
  }
}
```

## Endpoints

- `POST /` - MCP JSON-RPC 2.0 endpoint (for Cursor)
- `GET /health` - Health check endpoint

## Environment Variables

- `MANDREL_BASE_URL` - Base URL for Mandrel server (default: `http://mandrel-mcp:8081`)
- `PORT` - Port to listen on (default: `8080`)

## Development

```bash
# Install dependencies
npm install

# Run in development mode
npm run dev

# Run in production mode
npm start
```

## Docker

The bridge is deployed as part of the Mandrel docker-compose stack:

```bash
cd deployment/mandrel
docker-compose up -d mcp-bridge
```

## Testing

Test the bridge with curl:

```bash
# Health check
curl http://localhost:8082/health

# Test tools/list
curl -X POST http://localhost:8082/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# Test tools/call
curl -X POST http://localhost:8082/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"mandrel_ping","arguments":{}}}'
```

## Configuration

Update Cursor's MCP configuration to point to the bridge:

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
