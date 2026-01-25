/**
 * TypeScript type definitions for MCP HTTP Bridge
 */

// JSON-RPC 2.0 types
export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: string | number | null;
  method: string;
  params?: any;
}

export interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: string | number | null;
  result?: any;
  error?: JsonRpcError;
}

export interface JsonRpcError {
  code: number;
  message: string;
  data?: any;
}

// Mandrel REST API types
export interface MandrelToolSchema {
  name: string;
  description: string;
  inputSchema: any;
}

export interface MandrelToolSchemasResponse {
  success: boolean;
  tools: MandrelToolSchema[];
  count: number;
  timestamp: string;
  note?: string;
}

export interface MandrelToolCallResponse {
  success: boolean;
  result?: any;
  error?: string;
  type?: string;
}

// MCP Tool types
export interface McpTool {
  name: string;
  description: string;
  inputSchema: any;
}

export interface McpToolsListResult {
  tools: McpTool[];
}

export interface McpToolCallParams {
  name: string;
  arguments?: any;
}
