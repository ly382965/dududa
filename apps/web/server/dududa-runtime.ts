export interface DududaRuntimePreviewRequest {
  accountId: string
  conversationId: string
  prompt: string
}

export interface DududaRuntimePreviewResult {
  runId: string
  candidate: string
  tier: 'haiku' | 'sonnet' | 'opus'
  model: string
  reasoning: 'low' | 'medium' | 'high'
  answerProfile: 'short' | 'medium' | 'long'
  reasonCodes: string[]
  latencyMs: number
  generatedAt: string
  messagesRead: number
  charactersRead: number
  outputCalls: 0
  memoryWrites: 0
  toolCalls: number
}

export interface DududaRuntimePreviewClient {
  preview(request: DududaRuntimePreviewRequest): Promise<DududaRuntimePreviewResult>
}

export class DududaRuntimePreviewClientError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'DududaRuntimePreviewClientError'
  }
}

type ApiKeyProvider = string | (() => string)

export class HttpDududaRuntimePreviewClient implements DududaRuntimePreviewClient {
  private readonly baseUrl: string

  constructor(
    baseUrl: string,
    private readonly apiKey: ApiKeyProvider,
    private readonly fetchImpl: typeof fetch = fetch,
    private readonly timeoutMs = 120_000,
  ) {
    const parsed = new URL(baseUrl)
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('AstrBot Runtime API URL 协议无效')
    this.baseUrl = parsed.toString().replace(/\/$/, '')
  }

  async preview(request: DududaRuntimePreviewRequest): Promise<DududaRuntimePreviewResult> {
    const apiKey = (typeof this.apiKey === 'function' ? this.apiKey() : this.apiKey).trim()
    if (!apiKey) throw new DududaRuntimePreviewClientError('AstrBot plugin scope API Key 未配置', 503)
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.timeoutMs)
    timer.unref?.()
    try {
      const response = await this.fetchImpl(
        `${this.baseUrl}/plugins/extensions/astrbot_plugin_dududa_core/runtime/preview`,
        {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            'X-API-Key': apiKey,
          },
          body: JSON.stringify(request),
          signal: controller.signal,
        },
      )
      const envelope = await response.json().catch(() => ({})) as Record<string, unknown>
      if (!response.ok || envelope.status === 'error') {
        throw new DududaRuntimePreviewClientError(
          text(envelope.message) || `Dududa 2.0 Runtime 预览失败: ${response.status}`,
          response.ok ? 502 : response.status,
        )
      }
      return runtimePreviewResult(envelope.data)
    } catch (error) {
      if (error instanceof DududaRuntimePreviewClientError) throw error
      throw new DududaRuntimePreviewClientError(
        error instanceof Error && error.name === 'AbortError'
          ? 'Dududa 2.0 Runtime 预览超时'
          : 'Dududa 2.0 Runtime 预览接口不可用',
        503,
      )
    } finally {
      clearTimeout(timer)
    }
  }
}

function runtimePreviewResult(value: unknown): DududaRuntimePreviewResult {
  const item = record(value)
  const tier = text(item?.tier)
  const reasoning = text(item?.reasoning)
  const answerProfile = text(item?.answerProfile)
  if (
    !item
    || !text(item.runId)
    || !['haiku', 'sonnet', 'opus'].includes(tier)
    || !['low', 'medium', 'high'].includes(reasoning)
    || !['short', 'medium', 'long'].includes(answerProfile)
  ) {
    throw new DududaRuntimePreviewClientError('Dududa 2.0 Runtime 返回格式无效', 502)
  }
  return {
    runId: text(item.runId),
    candidate: text(item.candidate),
    tier: tier as DududaRuntimePreviewResult['tier'],
    model: text(item.model),
    reasoning: reasoning as DududaRuntimePreviewResult['reasoning'],
    answerProfile: answerProfile as DududaRuntimePreviewResult['answerProfile'],
    reasonCodes: stringArray(item.reasonCodes),
    latencyMs: nonnegativeInteger(item.latencyMs),
    generatedAt: text(item.generatedAt),
    messagesRead: nonnegativeInteger(item.messagesRead),
    charactersRead: nonnegativeInteger(item.charactersRead),
    outputCalls: 0,
    memoryWrites: 0,
    toolCalls: nonnegativeInteger(item.toolCalls),
  }
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(text).filter(Boolean) : []
}

function nonnegativeInteger(value: unknown): number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : 0
}
