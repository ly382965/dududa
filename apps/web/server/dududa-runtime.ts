import type { PreviewCoverage, PreviewEvidence, PreviewHistory, PreviewOutcome } from '../src/types/preview'

export interface DududaRuntimePreviewRequest {
  accountId: string
  conversationId: string
  prompt: string
  history?: PreviewHistory
}

export interface DududaRuntimePreviewResult extends PreviewEvidence {
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
  capabilityIds: string[]
  coverage?: PreviewCoverage
}

export interface DududaRuntimePreviewClient {
  preview(request: DududaRuntimePreviewRequest): Promise<DududaRuntimePreviewResult>
  status?(): Promise<DududaRuntimeStatus>
}

export interface DududaRuntimeStatus {
  ready: boolean
  controlReason?: 'rollout_config_invalid' | 'rollout_config_current'
  modelMapping: Partial<Record<'haiku' | 'sonnet' | 'opus', string>>
  controls: Record<string, unknown>
  checkedAt: string
  adaptiveActivations?: Array<{
    accountId: string; conversationId: string; pluginId: string
    reason: string; activatedAt: string; messagesRead: number
  }>
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
    return runtimePreviewResult(await this.request('preview', request))
  }

  async status(): Promise<DududaRuntimeStatus> {
    const value = record(await this.request('status'))
    if (!value || typeof value.ready !== 'boolean' || !record(value.controls) || !record(value.modelMapping)) {
      throw new DududaRuntimePreviewClientError('Dududa Runtime 状态返回格式无效', 502)
    }
    const mapping = record(value.modelMapping)!
    return {
      ready: value.ready,
      controlReason: value.controlReason === 'rollout_config_invalid'
        ? 'rollout_config_invalid' : 'rollout_config_current',
      checkedAt: text(value.checkedAt),
      adaptiveActivations: Array.isArray(value.adaptiveActivations) ? value.adaptiveActivations.flatMap(raw => {
        const item = record(raw)
        if (!item || !text(item.pluginId) || !text(item.accountId) || !text(item.conversationId)) return []
        return [{ accountId: text(item.accountId), conversationId: text(item.conversationId),
          pluginId: text(item.pluginId), reason: text(item.reason), activatedAt: text(item.activatedAt),
          messagesRead: typeof item.messagesRead === 'number' ? item.messagesRead : 0 }]
      }) : [],
      modelMapping: Object.fromEntries(['haiku', 'sonnet', 'opus'].flatMap(tier => (
        text(mapping[tier]) ? [[tier, text(mapping[tier])]] : []
      ))),
      controls: Object.fromEntries([
        'runtime_enabled', 'rollout_mode', 'rollout_delivery_enabled',
        'rollout_kill_switch', 'proactive_talk_enabled', 'all_groups',
      ].map(key => [key, record(value.controls)![key]])),
    }
  }

  private async request(path: 'status' | 'preview', request?: DududaRuntimePreviewRequest): Promise<unknown> {
    const apiKey = (typeof this.apiKey === 'function' ? this.apiKey() : this.apiKey).trim()
    if (!apiKey) throw new DududaRuntimePreviewClientError('AstrBot plugin scope API Key 未配置', 503)
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), path === 'status' ? Math.min(5_000, this.timeoutMs) : this.timeoutMs)
    timer.unref?.()
    try {
      const response = await this.fetchImpl(
        `${this.baseUrl}/plugins/extensions/astrbot_plugin_dududa_core/runtime/${path}`,
        {
          method: request ? 'POST' : 'GET',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            'X-API-Key': apiKey,
          },
          ...(request ? { body: JSON.stringify(request) } : {}),
          signal: controller.signal,
        },
      )
      const envelope = await response.json().catch(() => ({})) as Record<string, unknown>
      if (!response.ok || envelope.status === 'error') {
        throw new DududaRuntimePreviewClientError(
          response.status === 401 || response.status === 403
            ? 'AstrBot Runtime 接口认证失败，请检查服务端 plugin scope 凭据'
            : `Dududa Runtime 接口请求失败 (${response.status})`,
          response.ok ? 502 : response.status,
        )
      }
      return envelope.data
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
    || item.outputCalls !== 0
    || item.memoryWrites !== 0
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
    capabilityIds: stringArray(item.capabilityIds),
    outcome: previewOutcome(item.outcome, text(item.candidate)),
    runtimeState: text(item.runtimeState) || 'unknown',
    generationObserved: item.generationObserved === true,
    coverage: previewCoverage(item.coverage),
  }
}

function previewOutcome(value: unknown, candidate: string): PreviewOutcome {
  const supported: PreviewOutcome[] = ['response', 'no_reply', 'deferred', 'failed', 'reaction', 'empty']
  return supported.includes(value as PreviewOutcome) ? value as PreviewOutcome : candidate ? 'response' : 'empty'
}

function previewCoverage(value: unknown): PreviewCoverage | undefined {
  const item = record(value)
  if (!item || !['server_recent', 'synthetic', 'unavailable'].includes(text(item.source))) return undefined
  return {
    source: item.source as PreviewCoverage['source'], partial: true,
    truncated: item.truncated === true,
    historyMessagesRead: nonnegativeInteger(item.historyMessagesRead),
    oldestAt: text(item.oldestAt) || null,
    newestAt: text(item.newestAt) || null,
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
