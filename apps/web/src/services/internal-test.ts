import type {
  InternalTestAgentRequest,
  InternalTestAgentResponse,
  InternalTestAgentCatalog,
  InternalTestAgentPolicy,
  InternalTestAgentScope,
  InternalTestAgentStatus,
  InternalTestCandidate,
  InternalTestFeedback,
  InternalTestFeedbackResult,
  InternalTestProgress,
  InternalTestSamplesPage,
  InternalTestSamplesQuery,
  InternalTestStatus,
  McpConsoleCatalog,
  McpConsoleInvocation,
} from '../types/internal-test'

export interface InternalTestAdapter {
  status(): Promise<InternalTestStatus>
  samples(query?: InternalTestSamplesQuery): Promise<InternalTestSamplesPage>
  progress(): Promise<InternalTestProgress>
  generate(windowId: string): Promise<InternalTestCandidate>
  feedback(payload: InternalTestFeedback): Promise<InternalTestFeedbackResult>
}

export interface InternalTestAgentAdapter {
  agentStatus(): Promise<InternalTestAgentStatus>
  agentCatalog(): Promise<InternalTestAgentCatalog>
  agentConfig(scope: InternalTestAgentScope): Promise<InternalTestAgentPolicy>
  saveAgentConfig(scope: InternalTestAgentScope, policy: InternalTestAgentPolicy): Promise<InternalTestAgentPolicy>
  respond(payload: InternalTestAgentRequest): Promise<InternalTestAgentResponse>
}

export class HttpInternalTestAdapter implements InternalTestAdapter {
  constructor(private readonly baseUrl = '') {}

  status(): Promise<InternalTestStatus> {
    return this.request('/api/internal-test/status')
  }

  agentStatus(): Promise<InternalTestAgentStatus> {
    return this.request('/api/internal-test/agent/status')
  }

  agentCatalog(): Promise<InternalTestAgentCatalog> {
    return this.request('/api/internal-test/agent/catalog')
  }

  agentConfig(scope: InternalTestAgentScope): Promise<InternalTestAgentPolicy> {
    const search = new URLSearchParams({ accountId: scope.accountId, conversationId: scope.conversationId })
    return this.request(`/api/internal-test/agent/config?${search}`)
  }

  saveAgentConfig(
    scope: InternalTestAgentScope,
    policy: InternalTestAgentPolicy,
  ): Promise<InternalTestAgentPolicy> {
    return this.request('/api/internal-test/agent/config', { scope, policy }, 'PUT')
  }

  respond(payload: InternalTestAgentRequest): Promise<InternalTestAgentResponse> {
    return this.request('/api/internal-test/agent/respond', payload)
  }

  mcpCatalog(): Promise<McpConsoleCatalog> {
    return this.request('/api/internal-test/mcp/catalog')
  }

  invokeMcp(capabilityId: string, argumentsValue: Record<string, unknown>): Promise<McpConsoleInvocation> {
    return this.request('/api/internal-test/mcp/invoke', { capabilityId, arguments: argumentsValue })
  }

  samples(query: InternalTestSamplesQuery = {}): Promise<InternalTestSamplesPage> {
    const search = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== '' && value !== 'all') search.set(key, String(value))
    }
    const suffix = search.size ? `?${search}` : ''
    return this.request(`/api/internal-test/samples${suffix}`)
  }

  progress(): Promise<InternalTestProgress> {
    return this.request('/api/internal-test/progress')
  }

  generate(windowId: string): Promise<InternalTestCandidate> {
    return this.request('/api/internal-test/generate', { windowId })
  }

  feedback(payload: InternalTestFeedback): Promise<InternalTestFeedbackResult> {
    return this.request('/api/internal-test/feedback', payload)
  }

  private async request<T>(path: string, payload?: object, method = payload ? 'POST' : 'GET'): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        Accept: 'application/json',
        ...(payload ? { 'Content-Type': 'application/json' } : {}),
      },
      body: payload ? JSON.stringify(payload) : undefined,
    })
    const body = await response.json().catch(() => ({})) as { error?: string }
    if (!response.ok) throw new Error(body.error || `内测请求失败: ${response.status}`)
    return body as T
  }
}

export const internalTestAdapter = new HttpInternalTestAdapter()
