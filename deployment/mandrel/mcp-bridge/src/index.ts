/**
 * MCP HTTP Bridge Server
 * Converts MCP JSON-RPC 2.0 protocol to Mandrel REST API
 */

import express, { Request, Response } from 'express';
import type { JsonRpcRequest, JsonRpcResponse } from './types.js';
import { McpHandler } from './mcpHandler.js';
import { MandrelClient } from './mandrelClient.js';
import { createJsonRpcError } from './converter.js';

const app = express();
const PORT = process.env.PORT || 8080;
const MANDREL_BASE_URL = process.env.MANDREL_BASE_URL || 'http://mandrel-mcp:8081';

// Initialize MCP handler
const mcpHandler = new McpHandler(MANDREL_BASE_URL);

// Middleware
app.use(express.json({ limit: '10mb' }));

// CORS headers for Cursor
app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Accept');
  
  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }
  
  next();
});

// Health check endpoint
app.get('/health', async (req: Request, res: Response) => {
  try {
    const mandrelClient = new MandrelClient(MANDREL_BASE_URL);
    const mandrelHealthy = await mandrelClient.healthCheck();
    
    res.json({
      status: 'healthy',
      mandrel: mandrelHealthy ? 'connected' : 'disconnected',
      timestamp: new Date().toISOString(),
    });
  } catch (error: any) {
    res.status(503).json({
      status: 'unhealthy',
      error: error.message,
      timestamp: new Date().toISOString(),
    });
  }
});

// MCP JSON-RPC endpoint
app.post('/', async (req: Request, res: Response) => {
  try {
    const request: JsonRpcRequest = req.body;

    // Validate request format
    if (!request || typeof request !== 'object') {
      const errorResponse: JsonRpcResponse = createJsonRpcError(
        null,
        -32600,
        'Invalid Request',
        'Request body must be a JSON object'
      );
      return res.status(400).json(errorResponse);
    }

    // Handle single request
    const response = await mcpHandler.handleRequest(request);
    res.json(response);
  } catch (error: any) {
    const errorResponse: JsonRpcResponse = createJsonRpcError(
      null,
      -32603,
      'Internal error',
      error.message || 'Unknown error occurred'
    );
    res.status(500).json(errorResponse);
  }
});

// 404 handler
app.use((req: Request, res: Response) => {
  res.status(404).json({
    error: 'Not found',
    path: req.path,
  });
});

// Error handler
app.use((err: Error, req: Request, res: Response, next: any) => {
  console.error('Unhandled error:', err);
  const errorResponse: JsonRpcResponse = createJsonRpcError(
    null,
    -32603,
    'Internal error',
    err.message
  );
  res.status(500).json(errorResponse);
});

// Start server
app.listen(PORT, () => {
  console.log(`MCP HTTP Bridge listening on port ${PORT}`);
  console.log(`Mandrel base URL: ${MANDREL_BASE_URL}`);
  console.log(`Health check: http://localhost:${PORT}/health`);
  console.log(`MCP endpoint: http://localhost:${PORT}/`);
});
