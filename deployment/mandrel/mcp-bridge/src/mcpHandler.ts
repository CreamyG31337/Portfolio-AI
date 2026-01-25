/**
 * MCP JSON-RPC Request Handler
 * Routes MCP protocol requests to appropriate handlers
 */

import type { JsonRpcRequest, JsonRpcResponse } from './types.js';
import { MandrelClient } from './mandrelClient.js';
import {
  mandrelSchemasToMcpTools,
  mandrelCallToMcpResult,
  extractToolCallParams,
  createJsonRpcError,
} from './converter.js';

export class McpHandler {
  private mandrelClient: MandrelClient;

  constructor(mandrelBaseUrl?: string) {
    this.mandrelClient = new MandrelClient(mandrelBaseUrl);
  }

  /**
   * Handle JSON-RPC request
   */
  async handleRequest(request: JsonRpcRequest): Promise<JsonRpcResponse> {
    // Validate JSON-RPC 2.0 format
    if (request.jsonrpc !== '2.0') {
      return createJsonRpcError(
        request.id,
        -32600,
        'Invalid Request',
        'jsonrpc must be "2.0"'
      );
    }

    if (!request.method) {
      return createJsonRpcError(request.id, -32600, 'Invalid Request', 'method is required');
    }

    // Route to appropriate handler
    try {
      switch (request.method) {
        case 'initialize':
          return await this.handleInitialize(request);

        case 'initialized':
          // Notification - no response needed, but we'll return success anyway
          return {
            jsonrpc: '2.0',
            id: request.id,
            result: {},
          };

        case 'tools/list':
          return await this.handleToolsList(request.id);

        case 'tools/call':
          return await this.handleToolsCall(request);

        case 'ping':
          // Health check method
          return {
            jsonrpc: '2.0',
            id: request.id,
            result: { pong: true },
          };

        default:
          return createJsonRpcError(
            request.id,
            -32601,
            'Method not found',
            `Unknown method: ${request.method}`
          );
      }
    } catch (error: any) {
      return createJsonRpcError(
        request.id,
        -32603,
        'Internal error',
        error.message || 'Unknown error occurred'
      );
    }
  }

  /**
   * Handle initialize request (MCP handshake)
   */
  private async handleInitialize(request: JsonRpcRequest): Promise<JsonRpcResponse> {
    const params = request.params || {};
    
    return {
      jsonrpc: '2.0',
      id: request.id,
      result: {
        protocolVersion: '2024-11-05',
        capabilities: {
          tools: {},
          resources: {},
        },
        serverInfo: {
          name: 'mandrel-mcp-bridge',
          version: '1.0.0',
        },
      },
    };
  }

  /**
   * Handle tools/list request
   */
  private async handleToolsList(
    requestId: string | number | null
  ): Promise<JsonRpcResponse> {
    try {
      const mandrelResponse = await this.mandrelClient.getToolSchemas();
      return mandrelSchemasToMcpTools(mandrelResponse, requestId);
    } catch (error: any) {
      return createJsonRpcError(
        requestId,
        -32000,
        'Server error',
        `Failed to fetch tools: ${error.message}`
      );
    }
  }

  /**
   * Handle tools/call request
   */
  private async handleToolsCall(request: JsonRpcRequest): Promise<JsonRpcResponse> {
    try {
      const { name, arguments: args } = extractToolCallParams(request);
      const mandrelResponse = await this.mandrelClient.callTool(name, args);
      return mandrelCallToMcpResult(mandrelResponse, request.id);
    } catch (error: any) {
      return createJsonRpcError(
        request.id,
        -32000,
        'Server error',
        `Failed to call tool: ${error.message}`
      );
    }
  }
}
