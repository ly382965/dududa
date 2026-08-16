import type {
  InternalTestCandidate,
  InternalTestFeedback,
  InternalTestFeedbackResult,
  InternalTestProgress,
  InternalTestSamplesPage,
  InternalTestSamplesQuery,
  InternalTestStatus,
} from '../types/internal-test'

export interface InternalTestAdapter {
  status(): Promise<InternalTestStatus>
  samples(query?: InternalTestSamplesQuery): Promise<InternalTestSamplesPage>
  progress(): Promise<InternalTestProgress>
  generate(windowId: string): Promise<InternalTestCandidate>
  feedback(payload: InternalTestFeedback): Promise<InternalTestFeedbackResult>
}

export class HttpInternalTestAdapter implements InternalTestAdapter {
  constructor(private readonly baseUrl = '') {}

  status(): Promise<InternalTestStatus> {
    return this.request('/api/internal-test/status')
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

  private async request<T>(path: string, payload?: object): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: payload ? 'POST' : 'GET',
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
