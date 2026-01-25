/**
 * Protocol Converter
 * Converts between MCP JSON-RPC 2.0 and Mandrel REST API formats
 */

import type {
  JsonRpcRequest,
  JsonRpcResponse,
  JsonRpcError,
  MandrelToolSchemasResponse,
  MandrelToolCallResponse,
  McpTool,
  McpToolsListResult,
} from './types.js';

/**
 * Convert Mandrel tool schemas response to MCP tools/list result
 */
export function mandrelSchemasToMcpTools(
  mandrelResponse: MandrelToolSchemasResponse,
  requestId: string | number | null
): JsonRpcResponse {
  if (!mandrelResponse.success) {
    return {
      jsonrpc: '2.0',
      id: requestId,
      error: {
        code: -32000,
        message: 'Failed to fetch tools from Mandrel',
        data: mandrelResponse,
      },
    };
  }

  const tools: McpTool[] = mandrelResponse.tools.map((tool) => ({
    name: tool.name,
    description: tool.description,
    inputSchema: tool.inputSchema,
  }));

  const result: McpToolsListResult = {
    tools,
  };

  return {
    jsonrpc: '2.0',
    id: requestId,
    result,
  };
}

/**
 * Convert Mandrel tool call response to MCP tools/call result
 */
export function mandrelCallToMcpResult(
  mandrelResponse: MandrelToolCallResponse,
  requestId: string | number | null
): JsonRpcResponse {
  if (!mandrelResponse.success) {
    return {
      jsonrpc: '2.0',
      id: requestId,
      error: {
        code: -32000,
        message: mandrelResponse.error || 'Tool execution failed',
        data: {
          type: mandrelResponse.type,
        },
      },
    };
  }

  // Mandrel returns result.content format, which matches MCP's expected format
  return {
    jsonrpc: '2.0',
    id: requestId,
    result: mandrelResponse.result || {},
  };
}

/**
 * Extract tool name and arguments from MCP tools/call request
 */
export function extractToolCallParams(request: JsonRpcRequest): { name: string; arguments: any } {
  if (request.method !== 'tools/call') {
    throw new Error('Invalid method for tool call extraction');
  }

  const params = request.params || {};
  const name = params.name;
  const arguments_ = params.arguments || {};

  if (!name || typeof name !== 'string') {
    throw new Error('Tool name is required in params.name');
  }

  return { name, arguments: arguments_ };
}

/**
 * Create JSON-RPC error response
 */
export function createJsonRpcError(
  requestId: string | number | null,
  code: number,
  message: string,
  data?: any
): JsonRpcResponse {
  const error: JsonRpcError = {
    code,
    message,
  };

  if (data !== undefined) {
    error.data = data;
  }

  return {
    jsonrpc: '2.0',
    id: requestId,
    error,
  };
}
