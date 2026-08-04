import { EventEmitter } from 'node:events'
import { createHash, randomUUID, timingSafeEqual } from 'node:crypto'
import type { IncomingMessage } from 'node:http'
import type { Duplex } from 'node:stream'

import { WebSocket, WebSocketServer } from 'ws'

import type {
  Account,
  ChatMessage,
  Conversation,
  WorkspaceEvent,
  WorkspaceSnapshot,
} from '../src/types/workspace'
import {
  accountId,
  applyRecentContact,
  conversationId,
  eventConversation,
  mapAccount,
  mapFriendConversation,
  mapGroupConversation,
  mapMessage,
  messagePreview,
  recentConversationType,
  type OneBotFriend,
  type OneBotGroup,
  type OneBotLoginInfo,
  type OneBotMessage,
  type OneBotRecentContact,
} from './mapper'

interface OneBotResponse<T = unknown> {
  status?: string
  retcode?: number
  data?: T
  message?: string
  wording?: string
  echo?: unknown
}

interface PendingRequest {
  resolve: (value: unknown) => void
  reject: (reason: Error) => void
  timer: ReturnType<typeof setTimeout>
}

interface AccountState {
  selfId: string
  account: Account
  connection: OneBotConnection
  conversations: Map<string, Conversation>
  emittedMessages: Map<string, number>
  compatible: boolean
  refreshedAt: number
}

interface MediaEntry {
  url: string
  expiresAt: number
}

export interface HubOptions {
  token: string
  actionTimeoutMs?: number
  recentConversationCount?: number
  messageHistoryCount?: number
  mediaTtlMs?: number
  mediaMaxEntries?: number
}

const emittedMessageTtlMs = 5 * 60_000
const emittedMessageMaxEntries = 5_000
const defaultMediaTtlMs = 30 * 60_000
const defaultMediaMaxEntries = 2_000

export class OneBotConnection {
  private readonly pending = new Map<string, PendingRequest>()
  private closed = false

  constructor(
    readonly selfId: string,
    private readonly socket: WebSocket,
    private readonly actionTimeoutMs: number,
    private readonly eventHandler: (event: Record<string, unknown>) => void,
    private readonly closeHandler: () => void,
  ) {
    socket.on('message', (data) => this.handleMessage(data.toString()))
    socket.once('close', () => this.handleClose())
    socket.once('error', () => this.handleClose())
  }

  async request<T>(action: string, params: Record<string, unknown> = {}, timeoutMs = this.actionTimeoutMs): Promise<T> {
    if (this.closed || this.socket.readyState !== WebSocket.OPEN) throw new Error('NapCat 连接已断开')
    const echo = randomUUID()
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(echo)
        reject(new Error(`NapCat action 超时: ${action}`))
      }, timeoutMs)
      timer.unref?.()
      this.pending.set(echo, {
        resolve: (value) => resolve(value as T),
        reject,
        timer,
      })
      this.socket.send(JSON.stringify({ action, params, echo }), (error) => {
        if (!error) return
        clearTimeout(timer)
        this.pending.delete(echo)
        reject(error)
      })
    })
  }

  close(code = 1000, reason = 'connection replaced'): void {
    if (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING) {
      this.socket.close(code, reason)
    }
    this.handleClose()
  }

  private handleMessage(payload: string): void {
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(payload) as Record<string, unknown>
    } catch {
      return
    }
    const echo = typeof parsed.echo === 'string' ? parsed.echo : undefined
    if (echo && this.pending.has(echo)) {
      const pending = this.pending.get(echo)!
      clearTimeout(pending.timer)
      this.pending.delete(echo)
      const response = parsed as OneBotResponse
      if (response.status === 'ok' && Number(response.retcode ?? 0) === 0) {
        pending.resolve(response.data)
      } else {
        pending.reject(new Error(response.message || response.wording || `NapCat action 失败: ${response.retcode}`))
      }
      return
    }
    this.eventHandler(parsed)
  }

  private handleClose(): void {
    if (this.closed) return
    this.closed = true
    for (const request of this.pending.values()) {
      clearTimeout(request.timer)
      request.reject(new Error('NapCat 连接已断开'))
    }
    this.pending.clear()
    this.closeHandler()
  }
}

export class OneBotHub extends EventEmitter {
  readonly reverseWebSocketPath = '/onebot/v11/ws'
  private readonly wss = new WebSocketServer({ noServer: true, maxPayload: 50 * 1024 * 1024 })
  private readonly accounts = new Map<string, AccountState>()
  private readonly media = new Map<string, MediaEntry>()
  private readonly actionTimeoutMs: number
  private readonly recentConversationCount: number
  private readonly messageHistoryCount: number
  private readonly mediaTtlMs: number
  private readonly mediaMaxEntries: number
  private closed = false

  constructor(private readonly options: HubOptions) {
    super()
    this.actionTimeoutMs = options.actionTimeoutMs ?? 20_000
    this.recentConversationCount = options.recentConversationCount ?? 100
    this.messageHistoryCount = options.messageHistoryCount ?? 50
    this.mediaTtlMs = Math.max(1, Math.floor(options.mediaTtlMs ?? defaultMediaTtlMs))
    this.mediaMaxEntries = Math.max(1, Math.floor(options.mediaMaxEntries ?? defaultMediaMaxEntries))
    this.wss.on('connection', (socket, request) => this.acceptConnection(socket, request))
  }

  get configured(): boolean {
    return this.options.token.length >= 16
  }

  handleUpgrade(request: IncomingMessage, socket: Duplex, head: Buffer): boolean {
    const url = new URL(request.url ?? '/', 'http://localhost')
    if (url.pathname !== this.reverseWebSocketPath) return false
    if (!this.configured || !this.authorized(request.headers.authorization)) {
      socket.write('HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n')
      socket.destroy()
      return true
    }
    const selfId = this.headerValue(request.headers['x-self-id'])
    if (!/^\d{5,20}$/.test(selfId)) {
      socket.write('HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n')
      socket.destroy()
      return true
    }
    this.wss.handleUpgrade(request, socket, head, (client) => this.wss.emit('connection', client, request))
    return true
  }

  runtimeStatus(): WorkspaceSnapshot['runtime'] {
    if (!this.configured) {
      return {
        status: 'configuration_error',
        message: '服务端尚未配置 OneBot Access Token',
        reverseWebSocketPath: this.reverseWebSocketPath,
      }
    }
    if (!this.accounts.size) {
      return {
        status: 'waiting',
        message: '等待 NapCat 反向 WebSocket 连接',
        reverseWebSocketPath: this.reverseWebSocketPath,
      }
    }
    const online = [...this.accounts.values()].filter((state) => state.account.status === 'online').length
    return {
      status: 'connected',
      message: `${online}/${this.accounts.size} 个 QQ 账号在线，NapCat 连接正常`,
      reverseWebSocketPath: this.reverseWebSocketPath,
    }
  }

  workspaceSnapshot(): WorkspaceSnapshot {
    const states = [...this.accounts.values()]
    const conversations = states
      .flatMap((state) => [...state.conversations.values()])
      .sort((left, right) => (right.updatedAt ?? 0) - (left.updatedAt ?? 0) || left.name.localeCompare(right.name, 'zh-CN'))
    return {
      runtime: this.runtimeStatus(),
      accounts: states.map((state) => state.account),
      conversations,
      messages: {},
      sessions: [],
      agentMessages: {},
      runs: [],
      configs: {},
    }
  }

  async refreshAll(force = false): Promise<void> {
    await Promise.allSettled([...this.accounts.values()].map((state) => this.refreshAccount(state, force)))
  }

  async history(account: string, type: 'group' | 'private', peerId: string, limit?: number): Promise<ChatMessage[]> {
    const state = this.requireConversation(account, type, peerId)
    const count = Math.min(Math.max(Number(limit) || this.messageHistoryCount, 1), 100)
    const action = type === 'group' ? 'get_group_msg_history' : 'get_friend_msg_history'
    const key = type === 'group' ? 'group_id' : 'user_id'
    let data: { messages?: OneBotMessage[] }
    try {
      data = await state.connection.request(action, {
        [key]: peerId,
        count,
        reverse_order: false,
        disable_get_url: false,
        parse_mult_msg: true,
      })
    } catch (error) {
      if (error instanceof Error && /不存在|not found/i.test(error.message)) return []
      throw error
    }
    return (data.messages ?? [])
      .sort(
        (left, right) =>
          Number(left.time ?? 0) - Number(right.time ?? 0) ||
          Number(left.message_seq ?? left.real_seq ?? 0) - Number(right.message_seq ?? right.real_seq ?? 0),
      )
      .map((raw) =>
        mapMessage(account, state.selfId, raw, (url) => this.registerMedia(url), type === 'private' ? peerId : undefined),
      )
      .filter((message): message is ChatMessage => Boolean(message))
  }

  async sendText(account: string, type: 'group' | 'private', peerId: string, content: string): Promise<ChatMessage> {
    const state = this.requireConversation(account, type, peerId)
    const action = type === 'group' ? 'send_group_msg' : 'send_private_msg'
    const key = type === 'group' ? 'group_id' : 'user_id'
    const result = await state.connection.request<{ message_id: number | string }>(action, {
      [key]: peerId,
      message: [{ type: 'text', data: { text: content } }],
    })
    let raw: OneBotMessage | undefined
    try {
      raw = await state.connection.request<OneBotMessage>('get_msg', { message_id: result.message_id }, 10_000)
    } catch {
      raw = {
        self_id: state.selfId,
        user_id: state.selfId,
        target_id: peerId,
        group_id: type === 'group' ? peerId : undefined,
        message_type: type,
        message_id: result.message_id,
        message_seq: result.message_id,
        time: Math.floor(Date.now() / 1000),
        sender: { user_id: state.selfId, nickname: state.account.name },
        message: [{ type: 'text', data: { text: content } }],
        raw_message: content,
      }
    }
    raw = {
      ...raw,
      self_id: raw.self_id ?? state.selfId,
      message_type: type,
      group_id: type === 'group' ? peerId : raw.group_id,
      target_id: type === 'private' ? peerId : raw.target_id,
    }
    const message = mapMessage(
      account,
      state.selfId,
      raw,
      (url) => this.registerMedia(url),
      type === 'private' ? peerId : undefined,
    )
    if (!message) throw new Error('NapCat 返回了无法识别的消息')
    const known = state.conversations.get(conversationId(account, type, peerId))
    const conversation = eventConversation(account, state.selfId, raw, known, type === 'private' ? peerId : undefined)
    if (conversation) {
      state.conversations.set(conversation.id, conversation)
      this.broadcastMessage(state, conversation, message)
    }
    return message
  }

  async markRead(account: string, type: 'group' | 'private', peerId: string): Promise<void> {
    const state = this.requireConversation(account, type, peerId)
    const action = type === 'group' ? 'mark_group_msg_as_read' : 'mark_private_msg_as_read'
    const key = type === 'group' ? 'group_id' : 'user_id'
    await state.connection.request(action, { [key]: peerId }, 10_000)
  }

  mediaUrl(key: string): string | undefined {
    this.pruneMedia(Date.now())
    const entry = this.media.get(key)
    if (!entry) return undefined
    this.media.delete(key)
    this.media.set(key, entry)
    return entry.url
  }

  close(): void {
    if (this.closed) return
    this.closed = true
    for (const state of this.accounts.values()) state.connection.close(1001, 'server shutting down')
    this.accounts.clear()
    this.media.clear()
    this.wss.close()
  }

  private acceptConnection(socket: WebSocket, request: IncomingMessage): void {
    const selfId = this.headerValue(request.headers['x-self-id'])
    const id = accountId(selfId)
    const previous = this.accounts.get(id)
    const connection = new OneBotConnection(
      selfId,
      socket,
      this.actionTimeoutMs,
      (event) => this.handleEvent(id, connection, event),
      () => this.removeConnection(id, connection),
    )
    previous?.connection.close(1000, 'new NapCat connection established')
    const state: AccountState = {
      selfId,
      account: mapAccount({ user_id: selfId, nickname: selfId }, 'degraded'),
      connection,
      conversations: previous?.conversations ?? new Map(),
      emittedMessages: new Map(),
      compatible: false,
      refreshedAt: 0,
    }
    this.accounts.set(id, state)
    this.broadcast({ type: 'runtime.status', status: this.runtimeStatus() })
    void this.initializeAccount(state)
  }

  private async initializeAccount(state: AccountState): Promise<void> {
    try {
      const [login, status, version] = await Promise.all([
        state.connection.request<OneBotLoginInfo>('get_login_info'),
        state.connection.request<{ online?: boolean; good?: boolean }>('get_status'),
        state.connection.request<{ app_name?: string; protocol_version?: string }>('get_version_info'),
      ])
      if (!this.isCurrent(state)) return
      if (String(login.user_id) !== state.selfId) {
        state.connection.close(1008, 'OneBot self ID mismatch')
        return
      }
      const compatible = version.app_name === 'NapCat.Onebot' && version.protocol_version === 'v11'
      state.compatible = compatible
      state.account = mapAccount(login, this.oneBotAccountStatus(status.online, status.good, compatible))
      await this.refreshAccount(state, true)
      if (!this.isCurrent(state)) return
      this.broadcast({ type: 'runtime.status', status: this.runtimeStatus() })
      this.broadcast({ type: 'workspace.refresh' })
    } catch {
      if (this.isCurrent(state)) this.setAccountStatus(state, 'degraded')
    }
  }

  private async refreshAccount(state: AccountState, force: boolean): Promise<void> {
    if (!force && Date.now() - state.refreshedAt < 15_000) return
    const [groupsResult, friendsResult, recentResult] = await Promise.allSettled([
      state.connection.request<OneBotGroup[]>('get_group_list', { no_cache: false }, 30_000),
      state.connection.request<OneBotFriend[]>('get_friend_list', { no_cache: false }, 60_000),
      state.connection.request<OneBotRecentContact[]>('get_recent_contact', { count: this.recentConversationCount }, 30_000),
    ])
    if (!this.isCurrent(state)) return
    const anyFulfilled = [groupsResult, friendsResult, recentResult].some((result) => result.status === 'fulfilled')
    if (!anyFulfilled) return
    const next = new Map<string, Conversation>()
    if (groupsResult.status === 'fulfilled') {
      for (const group of groupsResult.value) {
        const mapped = mapGroupConversation(state.account.id, group)
        const conversation = this.preserveConversationActivity(mapped, state.conversations.get(mapped.id))
        next.set(conversation.id, conversation)
      }
    } else {
      for (const conversation of state.conversations.values()) {
        if (conversation.type === 'group') next.set(conversation.id, conversation)
      }
    }
    if (friendsResult.status === 'fulfilled') {
      for (const friend of friendsResult.value) {
        const mapped = mapFriendConversation(state.account.id, friend)
        const conversation = this.preserveConversationActivity(mapped, state.conversations.get(mapped.id))
        next.set(conversation.id, conversation)
      }
    } else {
      for (const conversation of state.conversations.values()) {
        if (conversation.type === 'private') next.set(conversation.id, conversation)
      }
    }
    if (recentResult.status === 'fulfilled') {
      for (const recent of recentResult.value) {
        const type = recentConversationType(Number(recent.chatType))
        if (!type) continue
        const id = conversationId(state.account.id, type, String(recent.peerUin))
        const existing = next.get(id) ?? state.conversations.get(id)
        const fallback =
          existing ??
          (type === 'group'
            ? mapGroupConversation(state.account.id, { group_id: recent.peerUin, group_name: recent.peerName || recent.peerUin })
            : mapFriendConversation(state.account.id, { user_id: recent.peerUin, nickname: recent.peerName || recent.peerUin }))
        next.set(id, applyRecentContact(fallback, recent))
      }
    }
    state.conversations = next
    state.refreshedAt = Date.now()
  }

  private handleEvent(account: string, connection: OneBotConnection, event: Record<string, unknown>): void {
    const state = this.accounts.get(account)
    if (!state || state.connection !== connection) return
    const postType = String(event.post_type ?? '')
    if (postType && String(event.self_id ?? '') !== state.selfId) {
      connection.close(1008, 'OneBot event self ID mismatch')
      return
    }
    if (postType === 'meta_event' && String(event.meta_event_type ?? '') === 'heartbeat') {
      const status = event.status
      if (status && typeof status === 'object' && typeof (status as { online?: unknown }).online === 'boolean') {
        const heartbeat = status as { online: boolean; good?: unknown }
        this.setAccountStatus(state, this.oneBotAccountStatus(heartbeat.online, heartbeat.good, state.compatible), true)
      }
      return
    }
    if (postType === 'notice' && String(event.notice_type ?? '') === 'bot_offline') {
      this.setAccountStatus(state, 'offline', true)
      return
    }
    if ((postType === 'message' || postType === 'message_sent') && event.message_type) {
      const raw = event as unknown as OneBotMessage
      const message = mapMessage(account, state.selfId, raw, (url) => this.registerMedia(url))
      if (!message) return
      const type = raw.message_type === 'group' ? 'group' : 'private'
      const peerId = type === 'group' ? String(raw.group_id ?? '') : message.mine ? String(raw.target_id ?? '') : String(raw.user_id ?? '')
      const known = state.conversations.get(conversationId(account, type, peerId))
      const conversation = eventConversation(account, state.selfId, raw, known)
      if (!conversation) return
      state.conversations.set(conversation.id, conversation)
      this.broadcastMessage(state, conversation, message)
      return
    }
    if (postType === 'notice' && String(event.notice_type ?? '').includes('recall')) {
      const type = event.group_id ? 'group' : 'private'
      const peerId = String(event.group_id ?? event.user_id ?? '')
      const rawMessageId = String(event.message_id ?? '')
      if (!peerId || !rawMessageId) return
      this.broadcast({
        type: 'message.deleted',
        conversationId: conversationId(account, type, peerId),
        messageId: `${account}:${type}:${peerId}:${rawMessageId}`,
      })
    }
  }

  private removeConnection(account: string, connection: OneBotConnection): void {
    const current = this.accounts.get(account)
    if (!current || current.connection !== connection) return
    this.accounts.delete(account)
    this.broadcast({ type: 'runtime.status', status: this.runtimeStatus() })
    this.broadcast({ type: 'workspace.refresh' })
  }

  private requireAccount(account: string): AccountState {
    const state = this.accounts.get(account)
    if (!state) throw new Error(`NapCat 账号未连接: ${account}`)
    return state
  }

  private requireConversation(account: string, type: 'group' | 'private', peerId: string): AccountState {
    const state = this.requireAccount(account)
    if (!/^\d{5,20}$/.test(peerId) || !state.conversations.has(conversationId(account, type, peerId))) {
      throw new Error(`QQ 会话不存在: ${account}:${type}:${peerId}`)
    }
    return state
  }

  private broadcast(event: WorkspaceEvent): void {
    this.emit('workspace-event', event)
  }

  private broadcastMessage(state: AccountState, conversation: Conversation, message: ChatMessage): void {
    const now = Date.now()
    for (const [id, expiresAt] of state.emittedMessages) {
      if (expiresAt <= now) state.emittedMessages.delete(id)
    }
    if (state.emittedMessages.has(message.id)) return
    state.emittedMessages.set(message.id, now + emittedMessageTtlMs)
    while (state.emittedMessages.size > emittedMessageMaxEntries) {
      const oldest = state.emittedMessages.keys().next().value as string | undefined
      if (!oldest) break
      state.emittedMessages.delete(oldest)
    }
    this.broadcast({ type: 'message.created', conversation, message })
  }

  private setAccountStatus(state: AccountState, status: Account['status'], suppressRefreshActions = false): void {
    if (!this.isCurrent(state) || state.account.status === status) return
    state.account.status = status
    if (suppressRefreshActions) state.refreshedAt = Date.now()
    this.broadcast({ type: 'runtime.status', status: this.runtimeStatus() })
    this.broadcast({ type: 'workspace.refresh' })
  }

  private oneBotAccountStatus(online: unknown, good: unknown, compatible: boolean): Account['status'] {
    if (online === false) return 'offline'
    return online === true && good === true && compatible ? 'online' : 'degraded'
  }

  private preserveConversationActivity(conversation: Conversation, previous?: Conversation): Conversation {
    if (!previous) return conversation
    return {
      ...conversation,
      lastMessage: previous.lastMessage,
      lastMessageAt: previous.lastMessageAt,
      unread: previous.unread,
      pinned: previous.pinned,
      muted: previous.muted,
      updatedAt: previous.updatedAt,
    }
  }

  private isCurrent(state: AccountState): boolean {
    return this.accounts.get(accountId(state.selfId))?.connection === state.connection
  }

  private registerMedia(source: string): string | undefined {
    if (!source) return undefined
    let url: URL
    try {
      url = new URL(source)
    } catch {
      return undefined
    }
    if (!['http:', 'https:'].includes(url.protocol) || !this.mediaHostAllowed(url.hostname)) return undefined
    const now = Date.now()
    this.pruneMedia(now)
    const key = createHash('sha256').update(source).digest('hex').slice(0, 32)
    this.media.delete(key)
    this.media.set(key, { url: source, expiresAt: now + this.mediaTtlMs })
    while (this.media.size > this.mediaMaxEntries) {
      const oldest = this.media.keys().next().value as string | undefined
      if (!oldest) break
      this.media.delete(oldest)
    }
    return `/api/media/message/${key}`
  }

  private pruneMedia(now: number): void {
    for (const [key, entry] of this.media) {
      if (entry.expiresAt <= now) this.media.delete(key)
    }
  }

  private mediaHostAllowed(hostname: string): boolean {
    const host = hostname.toLowerCase()
    return ['qq.com', 'qq.com.cn', 'qpic.cn', 'gtimg.cn', 'qlogo.cn'].some(
      (suffix) => host === suffix || host.endsWith(`.${suffix}`),
    )
  }

  private authorized(header: string | undefined): boolean {
    if (!header?.startsWith('Bearer ')) return false
    const actual = Buffer.from(header.slice(7))
    const expected = Buffer.from(this.options.token)
    return actual.length === expected.length && timingSafeEqual(actual, expected)
  }

  private headerValue(value: string | string[] | undefined): string {
    return Array.isArray(value) ? value[0] ?? '' : value ?? ''
  }

}
