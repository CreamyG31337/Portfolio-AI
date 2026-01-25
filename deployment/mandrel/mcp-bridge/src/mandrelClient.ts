/**
 * Mandrel REST API Client
 * Handles HTTP requests to Mandrel server
 */

import axios, { AxiosInstance } from 'axios';
import type { MandrelToolSchemasResponse, MandrelToolCallResponse } from './types.js';

export class MandrelClient {
  private client: AxiosInstance;
  private baseUrl: string;

  constructor(baseUrl: string = process.env.MANDREL_BASE_URL || 'http://mandrel-mcp:8081') {
    this.baseUrl = baseUrl.replace(/\/$/, ''); // Remove trailing slash
    this.client = axios.create({
      baseURL: this.baseUrl,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });
  }

  /**
   * Get all tool schemas from Mandrel
   */
  async getToolSchemas(): Promise<MandrelToolSchemasResponse> {
    try {
      const response = await this.client.get<MandrelToolSchemasResponse>('/mcp/tools/schemas');
      return response.data;
    } catch (error: any) {
      throw new Error(`Failed to fetch tool schemas: ${error.message}`);
    }
  }

  /**
   * Call a Mandrel tool
   */
  async callTool(toolName: string, arguments_: any = {}): Promise<MandrelToolCallResponse> {
    try {
      const response = await this.client.post<MandrelToolCallResponse>(
        `/mcp/tools/${toolName}`,
        { arguments: arguments_ }
      );
      return response.data;
    } catch (error: any) {
      if (error.response) {
        // Mandrel returned an error response
        return {
          success: false,
          error: error.response.data?.error || error.message,
          type: error.response.data?.type || 'UnknownError',
        };
      }
      throw new Error(`Failed to call tool ${toolName}: ${error.message}`);
    }
  }

  /**
   * Health check
   */
  async healthCheck(): Promise<boolean> {
    try {
      const response = await this.client.get('/health');
      return response.status === 200;
    } catch {
      return false;
    }
  }
}
