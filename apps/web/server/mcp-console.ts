import type {
  McpConsoleCatalog,
  McpConsoleInvocation,
} from '../src/types/internal-test'

export interface McpConsoleClient {
  catalog(): Promise<McpConsoleCatalog>
  invoke(capabilityId: string, argumentsValue: Record<string, unknown>): Promise<McpConsoleInvocation>
}

export class McpConsoleClientError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'McpConsoleClientError'
  }
}

export class UnavailableMcpConsoleClient implements McpConsoleClient {
  constructor(private readonly reason = 'MCP Console 后端未配置') {}

  async catalog(): Promise<McpConsoleCatalog> {
    return { schemaVersion: 1, available: false, servers: [], capabilities: [], reason: this.reason }
  }

  async invoke(): Promise<McpConsoleInvocation> {
    throw new McpConsoleClientError(this.reason, 503)
  }
}

export class HttpMcpConsoleClient implements McpConsoleClient {
  private readonly baseUrl: string

  constructor(baseUrl: string, private readonly timeoutMs = 120_000) {
    const parsed = new URL(baseUrl)
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('MCP Console URL 协议无效')
    this.baseUrl = parsed.toString().replace(/\/$/, '')
  }

  async catalog(): Promise<McpConsoleCatalog> {
    const value = await this.request<Omit<McpConsoleCatalog, 'available'>>('/v1/catalog')
    return { ...value, available: true }
  }

  invoke(capabilityId: string, argumentsValue: Record<string, unknown>): Promise<McpConsoleInvocation> {
    return this.request('/v1/invoke', { capabilityId, arguments: argumentsValue })
  }

  private async request<T>(path: string, payload?: object): Promise<T> {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.timeoutMs)
    timer.unref?.()
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        method: payload ? 'POST' : 'GET',
        headers: {
          Accept: 'application/json',
          ...(payload ? { 'Content-Type': 'application/json' } : {}),
        },
        body: payload ? JSON.stringify(payload) : undefined,
        signal: controller.signal,
      })
      const body = await response.json().catch(() => ({})) as { error?: string }
      if (!response.ok) {
        throw new McpConsoleClientError(body.error || `MCP Console 请求失败: ${response.status}`, response.status)
      }
      return body as T
    } catch (error) {
      if (error instanceof McpConsoleClientError) throw error
      throw new McpConsoleClientError(
        error instanceof Error && error.name === 'AbortError' ? 'MCP 调用超时' : 'MCP Console 后端不可用',
        503,
      )
    } finally {
      clearTimeout(timer)
    }
  }
}
