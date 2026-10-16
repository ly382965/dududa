import { randomUUID } from 'node:crypto'

import {
  DududaRuntimePreviewClientError,
  type DududaRuntimePreviewClient,
  type DududaRuntimePreviewRequest,
  type DududaRuntimePreviewResult,
  type DududaRuntimeStatus,
} from './dududa-runtime'
import type { OneBotHub } from './onebot-hub'
import type { WorkspaceEvent } from '../src/types/workspace'
import type { PreviewHistory } from '../src/types/preview'

export interface RuntimeV3Request {
  account_id: string
  conversation_id: string
  user_id: string
  message_id: string
  text: string
  mentioned: boolean
  source: 'qq' | 'web'
  preview: boolean
  history?: PreviewHistory
}

export interface RuntimeV3Run {
  runtime: 'dududa-3.0'
  run_id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'ignored'
  route: 'rule' | 'agent' | 'ignore'
  text: string
  thread_id?: string
  turn_id?: string
  model?: string
  reasoning_effort?: 'none' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'
  tool_calls: number
  events: unknown[]
  error?: string
  created_at: string
  latency_ms: number
  context_messages?: number
  context_characters?: number
  context_truncated?: boolean
}

const terminal = new Set(['completed', 'failed', 'cancelled', 'ignored'])
type TokenProvider = string | (() => string)

/** Only talks to the standalone 3.0 host. There is deliberately no 2.0 fallback. */
export class HttpRuntimeV3Client implements DududaRuntimePreviewClient {
  private readonly baseUrl: string

  constructor(
    baseUrl: string,
    private readonly token: TokenProvider,
    private readonly fetchImpl: typeof fetch = fetch,
    private readonly timeoutMs = 180_000,
    private readonly pollMs = 250,
    private readonly qqScopeCount = runtimeV3Scopes(process.env.DUDUDA_V3_QQ_SCOPES).size,
  ) {
    const parsed = new URL(baseUrl)
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('Dududa 3.0 Runtime URL 协议无效')
    this.baseUrl = parsed.toString().replace(/\/$/, '')
  }

  async status(): Promise<DududaRuntimeStatus> {
    const health = await this.request('/v3/health')
    return {
      ready: true,
      modelMapping: {},
      controls: {
        runtime: 'dududa-3.0',
        runtime_enabled: true,
        codex_available: health.codex_available === true,
        version: health.version,
        model: health.model,
        reasoning_effort: health.reasoning_effort,
        qq_scope_count: Math.min(this.qqScopeCount, Number(health.allowed_scope_count) || 0),
        proactive_scope_count: this.qqScopeCount > 0 ? Number(health.proactive_scope_count) || 0 : 0,
      },
      checkedAt: new Date().toISOString(),
    }
  }

  async preview(request: DududaRuntimePreviewRequest): Promise<DududaRuntimePreviewResult> {
    const run = await this.run({
      account_id: request.accountId,
      conversation_id: request.conversationId,
      user_id: 'web-preview',
      message_id: `preview-${randomUUID()}`,
      text: request.prompt,
      mentioned: true,
      source: 'web',
      preview: true,
      ...(request.history ? { history: request.history } : {}),
    })
    const history = run.route === 'agent' ? request.history : undefined
    const messagesRead = run.context_messages ?? 1 + (history?.messages.length ?? 0)
    const charactersRead = run.context_characters ?? request.prompt.length
      + (history?.messages.reduce((total, message) => total + message.content.length, 0) ?? 0)
    const truncated = run.context_truncated ?? history?.truncated ?? false
    return {
      runId: run.run_id,
      candidate: run.text,
      tier: run.route === 'agent' ? 'codex' : 'rules',
      model: run.model || '',
      reasoning: run.route === 'agent' ? run.reasoning_effort ?? 'medium' : 'none',
      answerProfile: 'medium',
      reasonCodes: ['runtime_v3', `runtime_v3.route.${run.route}`, 'runtime.preview.no_send', 'legacy_ui_policy_fields_unused'],
      latencyMs: run.latency_ms,
      generatedAt: run.created_at,
      messagesRead,
      charactersRead,
      outputCalls: 0,
      memoryWrites: 0,
      toolCalls: run.tool_calls,
      capabilityIds: [],
      outcome: run.status === 'ignored' ? 'no_reply' : run.text ? 'response' : 'empty',
      runtimeState: `dududa-3.0:${run.status}`,
      generationObserved: run.route === 'agent' && run.status === 'completed',
      coverage: {
        source: history?.source ?? 'unavailable', partial: true, truncated,
        historyMessagesRead: Math.max(0, messagesRead - 1),
        oldestAt: truncated ? null : history?.messages[0]?.timestamp ?? null,
        newestAt: truncated ? null : history?.messages.at(-1)?.timestamp ?? null,
      },
    }
  }

  async run(input: RuntimeV3Request): Promise<RuntimeV3Run> {
    const deadline = Date.now() + this.timeoutMs
    let runId: string | undefined
    try {
      const created = await this.request('/v3/runs', input, this.timeoutMs)
      if (typeof created.run_id !== 'string' || !created.run_id) {
        throw new DududaRuntimePreviewClientError('Dududa 3.0 Runtime 缺少 run_id', 502)
      }
      runId = created.run_id
      while (Date.now() < deadline) {
        const run = await this.request(`/v3/runs/${encodeURIComponent(runId)}`, undefined, deadline - Date.now())
        if (run.run_id !== runId || typeof run.status !== 'string'
          || !['queued', 'running', ...terminal].includes(run.status)) {
          throw new DududaRuntimePreviewClientError('Dududa 3.0 Runtime 任务返回格式无效', 502)
        }
        if (run.status === 'failed' || run.status === 'cancelled') {
          throw new DududaRuntimePreviewClientError(`Dududa 3.0 Runtime 任务${run.status === 'cancelled' ? '已取消' : '失败'}`, 503)
        }
        if (terminal.has(run.status)) {
          if (!['rule', 'agent', 'ignore'].includes(String(run.route)) || typeof run.text !== 'string') {
            throw new DududaRuntimePreviewClientError('Dududa 3.0 Runtime 结果返回格式无效', 502)
          }
          return run as unknown as RuntimeV3Run
        }
        await new Promise(resolve => setTimeout(resolve, Math.max(0, Math.min(this.pollMs, deadline - Date.now()))))
      }
      throw new DududaRuntimePreviewClientError('Dududa 3.0 Runtime 执行超时', 504)
    } catch (error) {
      if (runId && error instanceof DududaRuntimePreviewClientError && error.status === 504) {
        await this.request(`/v3/runs/${encodeURIComponent(runId)}/cancel`, {}).catch(() => undefined)
      }
      throw error
    }
  }

  async delivery(runId: string, state: 'sending' | 'sent' | 'unknown', messageId?: string): Promise<boolean> {
    const receipt = await this.request(`/v3/runs/${encodeURIComponent(runId)}/delivery`, {
      state, ...(messageId ? { message_id: messageId } : {}),
    })
    return receipt.claimed === true
  }

  private async request(path: string, body?: unknown, timeoutMs = 5_000): Promise<Record<string, unknown>> {
    const token = (typeof this.token === 'function' ? this.token() : this.token).trim()
    if (!token) throw new DududaRuntimePreviewClientError('DUDUDA_V3_TOKEN 未配置', 503)
    try {
      const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method: body === undefined ? 'GET' : 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        signal: AbortSignal.timeout(Math.max(1, Math.ceil(timeoutMs))),
      })
      if (!response.ok) {
        throw new DududaRuntimePreviewClientError(
          response.status === 401 || response.status === 403
            ? 'Dududa 3.0 Runtime 认证失败，请检查 DUDUDA_V3_TOKEN'
            : `Dududa 3.0 Runtime 请求失败 (${response.status})`, response.status,
        )
      }
      const value: unknown = await response.json()
      if (!value || typeof value !== 'object' || !('runtime' in value) || value.runtime !== 'dududa-3.0') {
        throw new DududaRuntimePreviewClientError('接口不是 Dududa 3.0 Runtime；已拒绝回退', 502)
      }
      return value as Record<string, unknown>
    } catch (error) {
      if (error instanceof DududaRuntimePreviewClientError) throw error
      const timedOut = error instanceof Error && ['AbortError', 'TimeoutError'].includes(error.name)
      throw new DududaRuntimePreviewClientError(
        timedOut ? 'Dududa 3.0 Runtime 执行超时' : 'Dududa 3.0 Runtime 不可用', timedOut ? 504 : 503,
      )
    }
  }
}

export function runtimeV3Scopes(value = ''): Set<string> {
  return new Set(value.split(',').map(scope => scope.trim()).filter(Boolean))
}

interface RuntimeV3QqHub {
  on(event: 'workspace-event', listener: (event: WorkspaceEvent) => void): unknown
  off(event: 'workspace-event', listener: (event: WorkspaceEvent) => void): unknown
  sendSegments: OneBotHub['sendSegments']
}

/** Delivery is opt-in per exact account/conversation and claimed durably by the host. */
export class RuntimeV3QqBridge {
  private closed = false
  private readonly listener = (event: WorkspaceEvent) => { void this.handle(event).catch(this.onError) }

  constructor(
    private readonly hub: RuntimeV3QqHub,
    private readonly runtime: Pick<HttpRuntimeV3Client, 'run' | 'delivery'>,
    private readonly scopes: ReadonlySet<string>,
    private readonly onError: (error: unknown) => void = error => console.error('Dududa 3.0 QQ bridge:', error),
  ) {
    hub.on('workspace-event', this.listener)
  }

  close(): void {
    this.closed = true
    this.hub.off('workspace-event', this.listener)
  }

  async handle(event: WorkspaceEvent): Promise<void> {
    if (this.closed || event.type !== 'message.created') return
    const { message, conversation } = event
    const botId = message.accountId.replace(/^qq-/, '')
    if (message.mine || message.senderId === botId || message.status === 'recalled'
      || message.accountId !== conversation.accountId || message.conversationId !== conversation.id
      || !this.scopes.has(`${message.accountId}/${message.conversationId}`)) return
    const mentioned = message.segments.some(segment => segment.type === 'mention' && segment.userId === botId)
    const text = message.segments.filter(segment => segment.type === 'text').map(segment => segment.text).join('').trim()
    const run = await this.runtime.run({
      account_id: message.accountId,
      conversation_id: message.conversationId,
      user_id: message.senderId,
      message_id: message.messageId,
      text: text || message.content,
      mentioned,
      source: 'qq',
      preview: false,
    })
    if (this.closed || run.status !== 'completed' || !run.text.trim()) return
    if (!await this.runtime.delivery(run.run_id, 'sending')) return
    try {
      const sent = await this.hub.sendSegments(message.accountId, conversation.type, conversation.peerId, [
        { type: 'text', text: run.text },
      ])
      await this.runtime.delivery(run.run_id, 'sent', sent.messageId)
    } catch (error) {
      // An interrupted OneBot request may already have sent. Never retry it automatically.
      await this.runtime.delivery(run.run_id, 'unknown').catch(this.onError)
      throw error
    }
  }
}
