import { randomUUID } from 'node:crypto'

import {
  DududaRuntimePreviewClientError,
  type DududaRuntimePreviewClient,
  type DududaRuntimePreviewRequest,
  type DududaRuntimePreviewResult,
  type DududaRuntimeStatus,
} from './dududa-runtime'
import type { OneBotHub, RuntimeMessagePart } from './onebot-hub'
import type { ChatMessage, MessageSegment, WorkspaceEvent } from '../src/types/workspace'
import type { PreviewHistory } from '../src/types/preview'
import { SUMMARY_FORWARD_THRESHOLD, summaryForwardParts } from './summary-delivery'

export interface RuntimeV3Image {
  url: string
  resource_id?: string
  sticker: boolean
  name?: string
  summary?: string
  width?: number
  height?: number
}

export type RuntimeV3Segment =
  | { type: 'text'; text: string }
  | { type: 'mention'; id: string; name: string }
  | ({ type: 'image' } & RuntimeV3Image)
  | { type: 'face'; id: string; name?: string }
  | { type: 'reply'; message_id: string }
  | { type: 'forward'; preview: string }
  | { type: 'light_app'; title: string; url: string; description: string }
  | { type: 'unknown'; summary: string }

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
  sender?: { name: string; card: string; nickname: string; role: 'owner' | 'admin' | 'member' }
  reply?: { message_id: string; sender_id: string; sender_name: string; text: string; images: RuntimeV3Image[] }
  mentions?: Array<{ id: string; name: string }>
  images?: RuntimeV3Image[]
  segments?: RuntimeV3Segment[]
  timestamp?: number
}

export type RuntimeV3ContentAction =
  | { type: 'text'; text: string }
  | { type: 'mention'; user_id: string }
  | { type: 'image'; data?: string; mime?: string; url?: string }
  | { type: 'face'; id: string | number }

export type RuntimeV3Action =
  | RuntimeV3ContentAction
  | { type: 'forward'; nodes: Array<{ name?: string; actions: RuntimeV3ContentAction[] }> }
  | { type: 'reaction'; message_id: string | number; emoji_id: string | number }
  | { type: 'file'; name: string; data: string; mime?: string }

export interface RuntimeV3OutboxItem {
  id: number | string
  account_id: string
  conversation_id: string
  actions: RuntimeV3Action[]
  guard?: { type: 'affinity_greeting'; user_id: string; kind: string; expires_at: number }
}

export interface RuntimeV3Run {
  runtime: 'dududa-3.0'
  run_id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'ignored'
  route: 'rule' | 'agent' | 'observer' | 'ignore'
  text: string
  actions?: RuntimeV3Action[]
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
  response_kind?: 'conversation_summary' | 'chat'
  skills?: string[]
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
          if (!['rule', 'agent', 'observer', 'ignore'].includes(String(run.route)) || typeof run.text !== 'string') {
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

  /** Claims proactive messages; the Host marks them `sending` so they are never handed out twice. */
  async claimOutbox(limit = 10): Promise<RuntimeV3OutboxItem[]> {
    const claimed = await this.request('/v3/outbox/claim', { limit }, 30_000)
    if (!Array.isArray(claimed.items)) throw new DududaRuntimePreviewClientError('Dududa 3.0 Runtime 发件箱返回格式无效', 502)
    return claimed.items as RuntimeV3OutboxItem[]
  }

  async authorizeOutbox(id: number | string, targetValid: boolean): Promise<{
    authorized: boolean; actions?: RuntimeV3Action[]
  }> {
    const receipt = await this.request(`/v3/outbox/${encodeURIComponent(String(id))}/authorize`, {
      target_valid: targetValid,
    })
    return { authorized: receipt.authorized === true,
      ...(Array.isArray(receipt.actions) ? { actions: receipt.actions as RuntimeV3Action[] } : {}) }
  }

  async outboxResult(id: number | string, state: 'sent' | 'unknown', messageId?: string): Promise<void> {
    await this.request(`/v3/outbox/${encodeURIComponent(String(id))}/result`, {
      state, ...(messageId ? { message_id: messageId } : {}),
    })
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
  sendRuntimeMessage: OneBotHub['sendRuntimeMessage']
  sendRuntimeForward: OneBotHub['sendRuntimeForward']
  sendMergedForward: OneBotHub['sendMergedForward']
  setMessageReaction: OneBotHub['setMessageReaction']
  sendFile: OneBotHub['sendFile']
  resolveMediaSource: OneBotHub['resolveMediaSource']
  refreshMessage: OneBotHub['refreshMessage']
  memberDirectory: OneBotHub['memberDirectory']
  validateRuntimeRecipient?: OneBotHub['validateRuntimeRecipient']
}

type RuntimeV3BridgeClient = Pick<HttpRuntimeV3Client, 'run' | 'delivery'>
  & Partial<Pick<HttpRuntimeV3Client, 'claimOutbox' | 'outboxResult' | 'authorizeOutbox'>>

interface DeliveryTarget {
  account: string
  type: 'group' | 'private'
  peerId: string
}

const REQUEST_BYTE_LIMIT = 200 * 1024
const TEXT_LIMIT = 8_000
const PART_LIMIT = 2_000
const SEGMENT_LIMIT = 80
const IMAGE_LIMIT = 16

function clip(value: string | undefined, limit: number): string {
  const text = value ?? ''
  return text.length <= limit ? text : Array.from(text).slice(0, limit).join('')
}

function contentPart(action: RuntimeV3ContentAction): RuntimeMessagePart | undefined {
  if (action.type === 'text') return action.text ? { type: 'text', text: action.text } : undefined
  if (action.type === 'mention') return { type: 'mention', userId: action.user_id }
  if (action.type === 'face') return /^\d{1,6}$/.test(String(action.id)) ? { type: 'face', id: String(action.id) } : undefined
  if (action.data) return { type: 'image', file: `base64://${action.data.replace(/^data:[^,]*;base64,/, '')}` }
  return action.url && /^https?:\/\//i.test(action.url) ? { type: 'image', file: action.url } : undefined
}

function isContentAction(action: RuntimeV3Action): action is RuntimeV3ContentAction {
  return action.type === 'text' || action.type === 'mention' || action.type === 'image' || action.type === 'face'
}

/** `qq-<bot>:group:<id>` / `qq-<bot>:private:<id>` → send target, only for the owning account. */
export function runtimeV3Target(accountId: string, conversationId: string): DeliveryTarget | undefined {
  const match = /^(qq-\d{5,20}):(group|private):(\d{5,20})$/.exec(conversationId)
  if (!match || match[1] !== accountId) return undefined
  return { account: accountId, type: match[2] as 'group' | 'private', peerId: match[3]! }
}

/**
 * Delivery is opt-in per exact account/conversation and claimed durably by the host.
 * `notifyScopes` only receive plain outbox notifications: their messages are never sent to the Host.
 */
export class RuntimeV3QqBridge {
  private closed = false
  private polling = false
  private outboxTimer: NodeJS.Timeout | undefined
  private readonly listener = (event: WorkspaceEvent) => { void this.handle(event).catch(this.onError) }

  constructor(
    private readonly hub: RuntimeV3QqHub,
    private readonly runtime: RuntimeV3BridgeClient,
    private readonly scopes: ReadonlySet<string>,
    private readonly onError: (error: unknown) => void = error => console.error('Dududa 3.0 QQ bridge:', error),
    private readonly outboxIntervalMs = 3_000,
    private readonly notifyScopes: ReadonlySet<string> = new Set(),
  ) {
    hub.on('workspace-event', this.listener)
    this.scheduleOutbox()
  }

  close(): void {
    this.closed = true
    clearTimeout(this.outboxTimer)
    this.outboxTimer = undefined
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
    const plain = message.segments.filter(segment => segment.type === 'text').map(segment => segment.text).join('').trim()
    // Preserve command ownership: a group `/command` aimed at another user is not ours.
    if (conversation.type === 'group' && plain.startsWith('/') && !mentioned
      && message.segments.some(segment => segment.type === 'mention' && !segment.all
        && segment.userId !== botId)) return
    // Recall forwarder commands are handled directly by OneBotHub's RecallForwarder; never pass to the Host.
    const cleanPlain = plain.replace(/^[@＠]?(?:嘟嘟哒|dududa)\s*/i, '').trim()
    if (conversation.type === 'group' && /^\s*\/?(?:开启|关闭)\s*防撤回\s*$/.test(cleanPlain)) return
    const target = { account: message.accountId, type: conversation.type, peerId: conversation.peerId }
    const run = await this.runtime.run(await this.request(message, target, botId, mentioned))
    const actions = run.actions?.length ? run.actions : run.text.trim() ? [{ type: 'text' as const, text: run.text }] : []
    if (this.closed || run.status !== 'completed' || !actions.length) return
    if (!await this.runtime.delivery(run.run_id, 'sending')) return
    try {
      const text = actions.every(action => action.type === 'text')
        ? actions.map(action => action.text).join('') : ''
      let sentId: string | undefined
      if (Array.from(text).length > SUMMARY_FORWARD_THRESHOLD) {
        const parts = summaryForwardParts(text)
        sentId = run.response_kind === 'conversation_summary'
          ? (await this.hub.sendMergedForward(target.account, target.type, target.peerId, parts)).messageId
          : (await this.hub.sendRuntimeForward(target.account, target.type, target.peerId,
            parts.map(text => ({ parts: [{ type: 'text', text }] })))).messageId
      } else {
        sentId = await this.deliver(target, actions)
      }
      await this.runtime.delivery(run.run_id, 'sent', sentId)
    } catch (error) {
      // An interrupted OneBot request may already have sent. Never retry it automatically.
      await this.runtime.delivery(run.run_id, 'unknown').catch(this.onError)
      throw error
    }
  }

  /** One outbox tick: claim, deliver each item in order, report the outcome. Never throws, never overlaps. */
  async pollOutbox(): Promise<void> {
    const { claimOutbox, outboxResult } = this.runtime
    if (this.closed || this.polling || !claimOutbox || !outboxResult) return
    this.polling = true
    try {
      const items = await claimOutbox.call(this.runtime, 10)
      for (const item of items) {
        if (this.closed) break
        const target = runtimeV3Target(item.account_id, item.conversation_id)
        try {
          const scope = `${item.account_id}/${item.conversation_id}`
          const allowed = target && this.scopes.has(scope)
          let actions = Array.isArray(item.actions) ? item.actions : []
          if (item.guard) {
            if (!this.runtime.authorizeOutbox) throw new Error('问候缺少宿主发送授权接口')
            let valid = false
            if (target && allowed && item.guard.type === 'affinity_greeting' && this.hub.validateRuntimeRecipient) {
              try {
                valid = await this.hub.validateRuntimeRecipient(
                  target.account, target.type, target.peerId, item.guard.user_id,
                )
              } catch (error) {
                this.onError(error)
              }
            }
            const authorization = await this.runtime.authorizeOutbox(item.id, valid)
            if (!authorization.authorized) continue
            // Authorization is one-shot. Even if its response was delayed, never send past expiry.
            if (this.closed || !valid || Date.now() / 1_000 > item.guard.expires_at) {
              await outboxResult.call(this.runtime, item.id, 'unknown')
              continue
            }
            actions = authorization.actions ?? actions
          }
          if (!target || !(allowed || (!item.guard && this.notifyScopes.has(scope)))) {
            throw new Error(`发件箱会话未启用: ${item.account_id}/${item.conversation_id}`)
          }
          const sentId = await this.deliver(target, actions)
          await outboxResult.call(this.runtime, item.id, 'sent', sentId)
        } catch (error) {
          // Claimed items are `sending` on the Host; an uncertain send is reported, never retried.
          this.onError(error)
          await outboxResult.call(this.runtime, item.id, 'unknown').catch(this.onError)
        }
      }
    } catch (error) {
      this.onError(error)
    } finally {
      this.polling = false
    }
  }

  private scheduleOutbox(): void {
    if (this.closed || !this.runtime.claimOutbox || !this.runtime.outboxResult || this.outboxIntervalMs <= 0) return
    this.outboxTimer = setTimeout(() => {
      void this.pollOutbox().finally(() => this.scheduleOutbox())
    }, this.outboxIntervalMs)
    this.outboxTimer.unref?.()
  }

  /** Consecutive text/mention/image/face actions become one QQ message; other actions are sent standalone in order. */
  private async deliver(target: DeliveryTarget, actions: RuntimeV3Action[]): Promise<string | undefined> {
    let first: string | undefined
    let pending: RuntimeMessagePart[] = []
    const note = (id: string | undefined) => { first ??= id || undefined }
    const flush = async () => {
      if (!pending.length) return
      const parts = pending
      pending = []
      note((await this.hub.sendRuntimeMessage(target.account, target.type, target.peerId, parts)).messageId)
    }
    for (const action of actions) {
      if (isContentAction(action)) {
        const part = contentPart(action)
        if (part) pending.push(part)
        continue
      }
      await flush()
      if (action.type === 'forward') {
        const nodes = (action.nodes ?? []).map(node => ({
          name: node.name,
          parts: (node.actions ?? []).map(contentPart).filter((part): part is RuntimeMessagePart => Boolean(part)),
        })).filter(node => node.parts.length)
        if (nodes.length) note((await this.hub.sendRuntimeForward(target.account, target.type, target.peerId, nodes)).messageId)
      } else if (action.type === 'reaction') {
        await this.hub.setMessageReaction(target.account, String(action.message_id), String(action.emoji_id))
      } else if (action.type === 'file') {
        const buffer = Buffer.from(action.data ?? '', 'base64')
        const fileName = clip((action.name ?? '').split(/[\\/]/).pop()?.trim() || '文件', 200)
        const receipt = await this.hub.sendFile(target.account, target.type, target.peerId,
          { buffer, fileName, size: buffer.length })
        note(receipt.fileId)
      } else {
        const unexpected: { type?: unknown } = action
        this.onError(new Error(`未知的回复动作: ${String(unexpected.type)}`))
      }
    }
    await flush()
    return first
  }

  private async request(message: ChatMessage, target: DeliveryTarget, botId: string, mentioned: boolean): Promise<RuntimeV3Request> {
    const members = target.type === 'group' && message.segments.some(segment => segment.type === 'mention'
      && !segment.all && segment.userId && segment.label.replace(/^@/, '') === segment.userId)
      ? await this.hub.memberDirectory(target.account, target.peerId).catch(() => undefined)
      : undefined
    const mentionName = (segment: Extract<MessageSegment, { type: 'mention' }>) => {
      if (segment.all) return '全体成员'
      const label = segment.label.replace(/^@/, '')
      const member = label === segment.userId ? members?.members.find(item => item.userId === segment.userId) : undefined
      return clip(member?.card || member?.nickname || label || segment.userId || '成员', 128)
    }
    const image = (segment: { url?: string; resourceId?: string; name?: string; summary?: string; width?: number; height?: number },
      sticker: boolean): RuntimeV3Image | undefined => {
      const url = this.hub.resolveMediaSource(segment.url)
      if (!url) return undefined
      return {
        url, sticker,
        ...(segment.resourceId ? { resource_id: segment.resourceId } : {}),
        ...(segment.name ? { name: segment.name } : {}),
        ...(segment.summary ? { summary: segment.summary } : {}),
        ...(segment.width ? { width: segment.width } : {}),
        ...(segment.height ? { height: segment.height } : {}),
      }
    }
    const imagesOf = (segments: MessageSegment[]) => segments.flatMap(segment => {
      const found = segment.type === 'image' ? image(segment, segment.sticker)
        : segment.type === 'face' && segment.market ? image({ url: segment.url, summary: segment.name }, true) : undefined
      return found ? [found] : []
    }).slice(0, IMAGE_LIMIT)
    const render = (segments: MessageSegment[]) => segments.map(segment => segment.type === 'text' ? segment.text
      : segment.type === 'mention' && segment.userId !== botId ? `@${mentionName(segment)}` : '').join('').trim()

    const segments: RuntimeV3Segment[] = []
    const mentions: Array<{ id: string; name: string }> = []
    for (const segment of message.segments) {
      if (segment.type === 'text') segments.push({ type: 'text', text: clip(segment.text, PART_LIMIT) })
      else if (segment.type === 'mention') {
        const entry = { id: segment.all ? 'all' : segment.userId ?? '', name: mentionName(segment) }
        segments.push({ type: 'mention', ...entry })
        if (segment.userId !== botId) mentions.push(entry)
      } else if (segment.type === 'image') {
        const found = image(segment, segment.sticker)
        segments.push(found ? { type: 'image', ...found } : { type: 'unknown', summary: segment.summary || '[图片]' })
      } else if (segment.type === 'face') {
        const sticker = segment.market ? image({ url: segment.url, summary: segment.name }, true) : undefined
        segments.push(sticker ? { type: 'image', ...sticker }
          : { type: 'face', id: segment.faceId, ...(segment.name ? { name: segment.name } : {}) })
      } else if (segment.type === 'reply') {
        if (segment.messageId) segments.push({ type: 'reply', message_id: segment.messageId })
      } else if (segment.type === 'forward') {
        segments.push({ type: 'forward', preview: clip(segment.preview || '[合并转发]', PART_LIMIT) })
      } else if (segment.type === 'light_app') {
        segments.push({ type: 'light_app', title: clip(segment.title, 512), url: segment.url ?? '',
          description: clip(segment.description, PART_LIMIT) })
      } else {
        const summary = segment.type === 'audio' ? '[语音]' : segment.type === 'video' ? '[视频]'
          : segment.type === 'file' ? `[文件] ${segment.name ?? ''}`.trim()
            : segment.type === 'markdown' ? segment.content : segment.summary
        segments.push({ type: 'unknown', summary: clip(summary, PART_LIMIT) })
      }
    }

    const images = imagesOf(message.segments)
    const replySegment = message.segments.find((segment): segment is Extract<MessageSegment, { type: 'reply' }> =>
      segment.type === 'reply')
    let reply: RuntimeV3Request['reply']
    if (replySegment?.messageId) {
      const quoted = await this.hub.refreshMessage(target.account, target.type, target.peerId, replySegment.messageId)
        .catch(() => undefined)
      reply = {
        message_id: replySegment.messageId,
        sender_id: quoted?.senderId ?? replySegment.senderId ?? '',
        sender_name: clip(quoted?.senderName ?? replySegment.senderName ?? '', 128),
        text: clip(quoted ? render(quoted.segments) || quoted.content : replySegment.preview, PART_LIMIT),
        images: quoted ? imagesOf(quoted.segments) : [],
      }
    }

    const text = render(message.segments)
    const request: RuntimeV3Request = {
      account_id: message.accountId,
      conversation_id: message.conversationId,
      user_id: message.senderId,
      message_id: message.messageId,
      text: clip(text || (images.length ? '' : message.content), TEXT_LIMIT),
      mentioned,
      source: 'qq',
      preview: false,
      sender: {
        name: clip(message.senderName, 128),
        card: message.senderCard ?? '',
        nickname: message.senderNickname ?? '',
        role: message.role ?? 'member',
      },
      ...(reply ? { reply } : {}),
      mentions,
      images,
      segments: segments.slice(0, SEGMENT_LIMIT),
      timestamp: Math.floor((message.timestampMs ?? Date.now()) / 1_000),
    }
    // The Host rejects bodies over 256 KiB; shed the redundant detail first, then the long text.
    const size = () => Buffer.byteLength(JSON.stringify(request))
    if (size() > REQUEST_BYTE_LIMIT) request.segments = request.segments!.slice(0, 10)
    if (size() > REQUEST_BYTE_LIMIT) request.text = clip(request.text, PART_LIMIT)
    return request
  }
}
