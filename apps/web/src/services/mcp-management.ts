import type {
  McpServerCheckResult,
  McpServerInstallRequest,
  McpServerInstallResult,
} from '../types/mcp-management'

export interface McpManagementAdapter {
  check(serverId: string): Promise<McpServerCheckResult>
  install(request: McpServerInstallRequest): Promise<McpServerInstallResult>
}

export class HttpMcpManagementAdapter implements McpManagementAdapter {
  constructor(private readonly baseUrl = '') {}

  install(request: McpServerInstallRequest): Promise<McpServerInstallResult> {
    return this.request('/api/mcp/install', request)
  }

  check(serverId: string): Promise<McpServerCheckResult> {
    return this.request('/api/mcp/check', { serverId })
  }

  private async request<T>(path: string, payload: object): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    })
    const body = await response.json().catch(() => ({})) as { error?: string }
    if (!response.ok) throw new Error(body.error || `MCP 管理请求失败: ${response.status}`)
    return body as T
  }
}

export const mcpManagementAdapter = new HttpMcpManagementAdapter()
