import { EventEmitter } from 'node:events'
import { createHash, createHmac, randomUUID, timingSafeEqual } from 'node:crypto'
import type { IncomingMessage } from 'node:http'
import type { Duplex } from 'node:stream'

import { WebSocket, WebSocketServer } from 'ws'

import type {
  Account,
  AccountCapabilityDocument,
  CapabilityName,
  ChatMessage,
  Conversation,
  FileSendReceipt,
  ForwardedMessageBundle,
  HistoryPage,
  OutgoingMessageSegment,
  UploadReceipt,
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
  type OneBotSegment,
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

class OneBotActionError extends Error {
  constructor(
    message: string,
    readonly outcome: 'rejected' | 'unknown',
  ) {
    super(message)
    this.name = 'OneBotActionError'
  }
}

interface AccountState {
  selfId: string
  account: Account
  connection: OneBotConnection
  conversations: Map<string, Conversation>
  emittedMessages: Map<string, number>
  compatible: boolean
  implementationName: string
  implementationVersion?: string
  refreshedAt: number
}

interface MediaEntry {
  url: string
  expiresAt: number
  kind: 'message' | 'file'
  fileName?: string
}

interface StagedUpload {
  accountId: string
  type: 'group' | 'private'
  peerId: string
  kind: UploadReceipt['kind']
  fileName: string
  mime: string
  size: number
  buffer: Buffer
  expiresAt: number
  consuming: boolean
}

interface OneBotForwardNode {
  type?: string
  data?: {
    user_id?: number | string
    nickname?: string
    time?: number
    message?: Array<OneBotSegment | OneBotForwardNode> | string
    content?: Array<OneBotSegment | OneBotForwardNode> | string
  }
}

export interface HubOptions {
  token: string
  actionTimeoutMs?: number
  recentConversationCount?: number
  messageHistoryCount?: number
  mediaTtlMs?: number
  mediaMaxEntries?: number
  uploadTtlMs?: number
  uploadMaxEntries?: number
  uploadMaxTotalBytes?: number
}

const emittedMessageTtlMs = 5 * 60_000
const emittedMessageMaxEntries = 5_000
const defaultMediaTtlMs = 30 * 60_000
const defaultMediaMaxEntries = 2_000
const defaultUploadTtlMs = 10 * 60_000
const defaultUploadMaxEntries = 32
const defaultUploadMaxTotalBytes = 100 * 1024 * 1024

const capabilityNames: CapabilityName[] = [
  'history.cursor',
  'directory.friends',
  'directory.groups',
  'directory.peer_pin',
  'message.send.text',
  'message.send.mention',
  'message.send.reply',
  'message.send.face',
  'message.send.image',
  'message.send.audio',
  'message.send.video',
  'message.send.file',
  'message.download.file',
  'message.recall',
  'message.forward',
  'message.nudge',
  'message.read',
  'message.custom_faces',
  'request.friend.history',
  'request.group.history',
  'group.members',
  'group.admin',
  'group.kick',
  'group.card',
  'group.rename',
  'group.mute_all',
  'group.quit',
  'group.essence',
  'group.announcements',
  'group.files',
  'group.folder.rename',
]

interface HistoryCursorPayload {
  v: 1
  accountId: string
  type: 'group' | 'private'
  peerId: string
  messageSeq: string
}

export interface HistoryPageRequest {
  limit?: number
  before?: string
  after?: string
}

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
        reject(new OneBotActionError(`NapCat action 超时: ${action}`, 'unknown'))
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
        reject(new OneBotActionError(error.message, 'unknown'))
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
        pending.reject(
          new OneBotActionError(
            response.message || response.wording || `NapCat action 失败: ${response.retcode}`,
            'rejected',
          ),
        )
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
      request.reject(new OneBotActionError('NapCat 连接已断开', 'unknown'))
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
  private readonly uploads = new Map<string, StagedUpload>()
  private readonly actionTimeoutMs: number
  private readonly recentConversationCount: number
  private readonly messageHistoryCount: number
  private readonly mediaTtlMs: number
  private readonly mediaMaxEntries: number
  private readonly uploadTtlMs: number
  private readonly uploadMaxEntries: number
  private readonly uploadMaxTotalBytes: number
  private closed = false

  constructor(private readonly options: HubOptions) {
    super()
    this.actionTimeoutMs = options.actionTimeoutMs ?? 20_000
    this.recentConversationCount = options.recentConversationCount ?? 100
    this.messageHistoryCount = options.messageHistoryCount ?? 50
    this.mediaTtlMs = Math.max(1, Math.floor(options.mediaTtlMs ?? defaultMediaTtlMs))
    this.mediaMaxEntries = Math.max(1, Math.floor(options.mediaMaxEntries ?? defaultMediaMaxEntries))
    this.uploadTtlMs = Math.max(1, Math.floor(options.uploadTtlMs ?? defaultUploadTtlMs))
    this.uploadMaxEntries = Math.max(1, Math.floor(options.uploadMaxEntries ?? defaultUploadMaxEntries))
    this.uploadMaxTotalBytes = Math.max(1, Math.floor(options.uploadMaxTotalBytes ?? defaultUploadMaxTotalBytes))
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
      accounts: states.map((state) => {
        const capabilities = this.capabilityDocument(state)
        return { ...state.account, implementation: capabilities.implementation, capabilities: capabilities.actions }
      }),
      capabilities: Object.fromEntries(states.map((state) => [state.account.id, this.capabilityDocument(state)])),
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

  capabilities(account: string): AccountCapabilityDocument {
    return this.capabilityDocument(this.requireAccount(account))
  }

  assertConversation(account: string, type: 'group' | 'private', peerId: string): void {
    this.requireConversation(account, type, peerId)
  }

  stageMediaUpload(
    account: string,
    type: 'group' | 'private',
    peerId: string,
    input: { buffer: Buffer; fileName: string; mime: string; size: number },
  ): UploadReceipt {
    const state = this.requireConversation(account, type, peerId)
    const kind: UploadReceipt['kind'] = input.mime.startsWith('image/')
      ? 'image'
      : input.mime.startsWith('audio/')
        ? 'audio'
        : input.mime.startsWith('video/')
          ? 'video'
          : (() => {
              throw new Error('该文件类型不能作为媒体消息发送')
            })()
    this.requireCapability(state, `message.send.${kind}` as CapabilityName)
    if (input.size !== input.buffer.length || input.size <= 0 || input.size > 25 * 1024 * 1024) {
      throw new Error('上传文件大小无效')
    }
    const now = Date.now()
    this.pruneUploads(now)
    const uploadId = randomUUID()
    const entry: StagedUpload = {
      accountId: account,
      type,
      peerId,
      kind,
      fileName: input.fileName,
      mime: input.mime,
      size: input.size,
      buffer: input.buffer,
      expiresAt: now + this.uploadTtlMs,
      consuming: false,
    }
    this.uploads.set(uploadId, entry)
    this.pruneUploads(now)
    if (!this.uploads.has(uploadId)) throw new Error('上传暂存空间不足')
    return {
      uploadId,
      kind,
      name: input.fileName,
      mime: input.mime,
      size: input.size,
      expiresAt: entry.expiresAt,
    }
  }

  async sendFile(
    account: string,
    type: 'group' | 'private',
    peerId: string,
    input: { buffer: Buffer; fileName: string; size: number },
  ): Promise<FileSendReceipt> {
    const state = this.requireConversation(account, type, peerId)
    this.requireCapability(state, 'message.send.file')
    if (input.size !== input.buffer.length || input.size <= 0 || input.size > 25 * 1024 * 1024) {
      throw new Error('上传文件大小无效')
    }
    const action = type === 'group' ? 'upload_group_file' : 'upload_private_file'
    const key = type === 'group' ? 'group_id' : 'user_id'
    const result = await state.connection.request<{ file_id?: string | null }>(
      action,
      {
        [key]: peerId,
        file: `base64://${input.buffer.toString('base64')}`,
        name: input.fileName,
      },
      120_000,
    )
    return { kind: 'file', fileId: result.file_id ?? undefined, name: input.fileName, size: input.size }
  }

  async fileDownloadUrl(
    account: string,
    type: 'group' | 'private',
    peerId: string,
    fileId: string,
    fileName = 'QQ文件',
  ): Promise<{ url: string }> {
    const state = this.requireConversation(account, type, peerId)
    this.requireCapability(state, 'message.download.file')
    if (!fileId || fileId.length > 2_048 || /[\u0000-\u001f\u007f]/.test(fileId)) throw new Error('文件标识无效')
    const action = type === 'group' ? 'get_group_file_url' : 'get_private_file_url'
    const result = await state.connection.request<{ url?: string }>(
      action,
      type === 'group' ? { group_id: peerId, file_id: fileId } : { file_id: fileId },
      30_000,
    )
    const url = result.url ? this.registerFileMedia(result.url, fileName) : undefined
    if (!url) throw new Error('NapCat 未返回可用的文件下载地址')
    return { url }
  }

  async history(account: string, type: 'group' | 'private', peerId: string, limit?: number): Promise<ChatMessage[]> {
    return (await this.historyPage(account, type, peerId, { limit })).messages
  }

  async historyPage(
    account: string,
    type: 'group' | 'private',
    peerId: string,
    request: HistoryPageRequest = {},
  ): Promise<HistoryPage> {
    const state = this.requireConversation(account, type, peerId)
    this.requireCapability(state, 'history.cursor')
    const count = Math.min(Math.max(Number(request.limit) || this.messageHistoryCount, 1), 100)
    if (request.before && request.after) throw new Error('before 与 after 不能同时使用')
    const cursor = request.before || request.after
    const decodedCursor = cursor ? this.decodeHistoryCursor(cursor, account, type, peerId) : undefined
    const direction = request.after ? 'after' : 'before'
    const requestCount = decodedCursor ? Math.min(count + 1, 100) : count
    const action = type === 'group' ? 'get_group_msg_history' : 'get_friend_msg_history'
    const key = type === 'group' ? 'group_id' : 'user_id'
    let data: { messages?: OneBotMessage[] }
    try {
      data = await state.connection.request(action, {
        [key]: peerId,
        count: requestCount,
        ...(decodedCursor ? { message_seq: decodedCursor.messageSeq } : {}),
        reverse_order: direction === 'after',
        disable_get_url: false,
        parse_mult_msg: true,
      })
    } catch (error) {
      if (error instanceof Error && /不存在|not found/i.test(error.message)) {
        return { messages: [], hasMoreBefore: false, hasMoreAfter: false }
      }
      throw error
    }
    const rawMessages = data.messages ?? []
    const byId = new Map<string, ChatMessage>()
    rawMessages
      .sort(
        (left, right) =>
          Number(left.time ?? 0) - Number(right.time ?? 0) ||
          Number(left.message_seq ?? left.real_seq ?? 0) - Number(right.message_seq ?? right.real_seq ?? 0),
      )
      .map((raw) =>
        mapMessage(account, state.selfId, raw, (url) => this.registerMedia(url), type === 'private' ? peerId : undefined),
      )
      .filter((message): message is ChatMessage => Boolean(message))
      .filter((message) => !decodedCursor || message.messageSeq !== decodedCursor.messageSeq)
      .forEach((message) => byId.set(message.id, message))
    const mappedMessages = [...byId.values()]
    const messages =
      mappedMessages.length > count
        ? direction === 'before'
          ? mappedMessages.slice(-count)
          : mappedMessages.slice(0, count)
        : mappedMessages
    const firstSeq = messages.find((message) => message.messageSeq)?.messageSeq
    const lastSeq = [...messages].reverse().find((message) => message.messageSeq)?.messageSeq
    return {
      messages,
      beforeCursor: firstSeq ? this.encodeHistoryCursor(account, type, peerId, firstSeq) : undefined,
      afterCursor: lastSeq ? this.encodeHistoryCursor(account, type, peerId, lastSeq) : undefined,
      hasMoreBefore:
        direction === 'before' && (mappedMessages.length > count || rawMessages.length >= requestCount),
      hasMoreAfter:
        direction === 'after' && (mappedMessages.length > count || rawMessages.length >= requestCount),
    }
  }

  async sendText(account: string, type: 'group' | 'private', peerId: string, content: string): Promise<ChatMessage> {
    return this.sendSegments(account, type, peerId, [{ type: 'text', text: content }])
  }

  async sendSegments(
    account: string,
    type: 'group' | 'private',
    peerId: string,
    segments: OutgoingMessageSegment[],
  ): Promise<ChatMessage> {
    const state = this.requireConversation(account, type, peerId)
    for (const segment of segments) {
      const capability: CapabilityName =
        segment.type === 'text'
          ? 'message.send.text'
          : segment.type === 'mention'
            ? 'message.send.mention'
            : segment.type === 'reply'
              ? 'message.send.reply'
              : segment.type === 'face'
                ? 'message.send.face'
                : (`message.send.${segment.type}` as CapabilityName)
      this.requireCapability(state, capability)
    }
    const action = type === 'group' ? 'send_group_msg' : 'send_private_msg'
    const key = type === 'group' ? 'group_id' : 'user_id'
    const reservedUploads: string[] = []
    let outgoing: Array<{ type: string; data: Record<string, string> }>
    let result: { message_id: number | string }
    let actionStarted = false
    try {
      outgoing = segments.map((segment) =>
        this.toOneBotSegment(state, account, type, peerId, segment, reservedUploads),
      )
      actionStarted = true
      result = await state.connection.request<{ message_id: number | string }>(
        action,
        {
          [key]: peerId,
          message: outgoing,
        },
        reservedUploads.length ? 120_000 : this.actionTimeoutMs,
      )
    } catch (error) {
      const retrySafe =
        !actionStarted || (error instanceof OneBotActionError && error.outcome === 'rejected')
      for (const uploadId of reservedUploads) {
        if (!retrySafe) {
          this.uploads.delete(uploadId)
          continue
        }
        const upload = this.uploads.get(uploadId)
        if (upload) upload.consuming = false
      }
      throw error
    }
    reservedUploads.forEach((uploadId) => this.uploads.delete(uploadId))
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
        message: outgoing,
        raw_message: segments.map((segment) => (segment.type === 'text' ? segment.text : '')).join(''),
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
    this.requireCapability(state, 'message.read')
    const action = type === 'group' ? 'mark_group_msg_as_read' : 'mark_private_msg_as_read'
    const key = type === 'group' ? 'group_id' : 'user_id'
    await state.connection.request(action, { [key]: peerId }, 10_000)
  }

  async recallMessage(
    account: string,
    type: 'group' | 'private',
    peerId: string,
    messageId: string,
  ): Promise<void> {
    if (!/^\d{1,24}$/.test(messageId)) throw new Error('消息标识无效')
    const { state, message } = await this.requireMessageInConversation(account, type, peerId, messageId)
    this.requireCapability(state, 'message.recall')
    const senderId = String(message.sender?.user_id ?? message.user_id ?? '')
    if (senderId !== state.selfId) throw new Error('消息标识与本账号撤回权限不匹配')
    await state.connection.request('delete_msg', { message_id: messageId }, 20_000)
    this.broadcast({
      type: 'message.deleted',
      accountId: account,
      conversationId: conversationId(account, type, peerId),
      messageId: `${account}:${type}:${peerId}:${messageId}`,
    })
  }

  async refreshMessage(
    account: string,
    type: 'group' | 'private',
    peerId: string,
    messageId: string,
  ): Promise<ChatMessage> {
    if (!/^\d{1,24}$/.test(messageId)) throw new Error('消息标识无效')
    const { state, message } = await this.requireMessageInConversation(account, type, peerId, messageId)
    this.requireCapability(state, 'history.cursor')
    const mapped = mapMessage(
      account,
      state.selfId,
      message,
      (url) => this.registerMedia(url),
      type === 'private' ? peerId : undefined,
    )
    if (!mapped) throw new Error('NapCat 返回了无法识别的消息')
    return mapped
  }

  async nudge(account: string, type: 'group' | 'private', peerId: string, userId: string): Promise<void> {
    const state = this.requireConversation(account, type, peerId)
    this.requireCapability(state, 'message.nudge')
    if (!/^\d{5,20}$/.test(userId)) throw new Error('QQ 号无效')
    if (type === 'private' && userId !== peerId) throw new Error('戳一戳目标与当前私聊不匹配')
    const action = type === 'group' ? 'group_poke' : 'friend_poke'
    await state.connection.request(action, type === 'group' ? { group_id: peerId, user_id: userId } : { user_id: userId })
  }

  async forwardMessage(
    account: string,
    type: 'group' | 'private',
    peerId: string,
    messageId: string,
    target: { accountId: string; type: 'group' | 'private'; peerId: string },
  ): Promise<{ messageId?: string }> {
    if (!/^\d{1,24}$/.test(messageId)) throw new Error('消息标识无效')
    const source = await this.requireMessageInConversation(account, type, peerId, messageId)
    this.requireCapability(source.state, 'message.forward')
    if (target.accountId !== account) throw new Error('消息转发不能跨 QQ 账号')
    const state = this.requireConversation(target.accountId, target.type, target.peerId)
    const action = type === 'group' ? 'forward_group_single_msg' : 'forward_friend_single_msg'
    const key = target.type === 'group' ? 'group_id' : 'user_id'
    await state.connection.request<null>(action, {
      [key]: target.peerId,
      message_id: messageId,
    })
    return {}
  }

  async forwardedMessages(
    account: string,
    type: 'group' | 'private',
    peerId: string,
    forwardId: string,
  ): Promise<ForwardedMessageBundle> {
    const state = this.requireConversation(account, type, peerId)
    if (!forwardId || forwardId.length > 512) throw new Error('转发消息标识无效')
    const data = await state.connection.request<{ messages?: Array<OneBotForwardNode | OneBotMessage> }>(
      'get_forward_msg',
      { message_id: forwardId },
      30_000,
    )
    const messages = this.mapForwardNodes(account, state, type, peerId, data.messages ?? [], forwardId, {
      remaining: 500,
    })
    return { forwardId, messages }
  }

  mediaUrl(key: string): string | undefined {
    this.pruneMedia(Date.now())
    const entry = this.media.get(key)
    if (!entry || entry.kind !== 'message') return undefined
    this.media.delete(key)
    this.media.set(key, entry)
    return entry.url
  }

  fileMedia(key: string): { url: string; fileName: string } | undefined {
    this.pruneMedia(Date.now())
    const entry = this.media.get(key)
    if (!entry || entry.kind !== 'file') return undefined
    this.media.delete(key)
    this.media.set(key, entry)
    return { url: entry.url, fileName: entry.fileName || 'QQ文件' }
  }

  close(): void {
    if (this.closed) return
    this.closed = true
    for (const state of this.accounts.values()) state.connection.close(1001, 'server shutting down')
    this.accounts.clear()
    this.media.clear()
    this.uploads.clear()
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
      implementationName: 'NapCat.Onebot',
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
        state.connection.request<{ app_name?: string; app_version?: string; protocol_version?: string }>('get_version_info'),
      ])
      if (!this.isCurrent(state)) return
      if (String(login.user_id) !== state.selfId) {
        state.connection.close(1008, 'OneBot self ID mismatch')
        return
      }
      const compatible = version.app_name === 'NapCat.Onebot' && version.protocol_version === 'v11'
      state.compatible = compatible
      state.implementationName = version.app_name || 'Unknown OneBot'
      state.implementationVersion = version.app_version
      state.account = mapAccount(login, this.oneBotAccountStatus(status.online, status.good, compatible))
      await this.refreshAccount(state, true)
      if (!this.isCurrent(state)) return
      this.broadcast({ type: 'runtime.status', status: this.runtimeStatus() })
      this.broadcast({ type: 'capabilities.changed', accountId: state.account.id, capabilities: this.capabilityDocument(state) })
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
        accountId: account,
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

  private requireCapability(state: AccountState, name: CapabilityName): void {
    const capability = this.capabilityDocument(state).actions[name]
    if (capability.status !== 'supported') throw new Error(capability.reason || `QQ 能力当前不可用: ${name}`)
  }

  private broadcast(event: WorkspaceEvent): void {
    this.emit('workspace-event', event)
  }

  private capabilityDocument(state: AccountState): AccountCapabilityDocument {
    const implemented = new Set<CapabilityName>([
      'history.cursor',
      'directory.friends',
      'directory.groups',
      'message.send.text',
      'message.send.mention',
      'message.send.reply',
      'message.send.face',
      'message.send.image',
      'message.send.audio',
      'message.send.video',
      'message.send.file',
      'message.download.file',
      'message.recall',
      'message.forward',
      'message.nudge',
      'message.read',
    ])
    const napCatGaps = new Map<CapabilityName, string>([
      ['directory.peer_pin', '当前 NapCat 未提供 QQ 同步置顶 action'],
      ['request.friend.history', '当前 NapCat 无法回填普通好友申请历史'],
      ['group.folder.rename', '当前 NapCat 未提供群文件夹重命名 action'],
    ])
    const minimumVersions = new Map<CapabilityName, string>([
      ['message.download.file', '4.8.0'],
      ['message.forward', '4.8.0'],
      ['message.nudge', '4.8.0'],
    ])
    const actions = Object.fromEntries(
      capabilityNames.map((name) => {
        if (!state.compatible) return [name, { status: 'unavailable' as const, reason: '连接端不是兼容的 NapCat OneBot v11' }]
        if (state.account.status !== 'online') return [name, { status: 'unavailable' as const, reason: 'QQ 账号连接状态异常' }]
        const minimumVersion = minimumVersions.get(name)
        if (minimumVersion && !this.versionAtLeast(state.implementationVersion, minimumVersion)) {
          return [
            name,
            {
              status: 'unsupported' as const,
              reason: `需要 NapCat ${minimumVersion} 或更高版本，当前为 ${state.implementationVersion || '未知版本'}`,
            },
          ]
        }
        if (implemented.has(name)) return [name, { status: 'supported' as const }]
        return [
          name,
          {
            status: 'unsupported' as const,
            reason: napCatGaps.get(name) || 'NapCat 支持该能力，但 Web 安全网关尚未实现',
          },
        ]
      }),
    ) as Record<CapabilityName, AccountCapabilityDocument['actions'][CapabilityName]>
    return {
      accountId: state.account.id,
      implementation: {
        name: state.implementationName,
        version: state.implementationVersion,
        protocol: 'onebot-v11',
      },
      actions,
    }
  }

  private toOneBotSegment(
    state: AccountState,
    account: string,
    type: 'group' | 'private',
    peerId: string,
    segment: OutgoingMessageSegment,
    reservedUploads: string[],
  ): { type: string; data: Record<string, string> } {
    switch (segment.type) {
      case 'text':
        return { type: 'text', data: { text: segment.text } }
      case 'mention':
        return { type: 'at', data: { qq: segment.all ? 'all' : segment.userId ?? '' } }
      case 'reply':
        return { type: 'reply', data: { id: segment.messageId ?? segment.messageSeq ?? '' } }
      case 'face':
        return { type: 'face', data: { id: segment.faceId } }
      case 'image':
      case 'audio':
      case 'video': {
        const upload = this.uploads.get(segment.uploadId)
        if (!upload || upload.expiresAt <= Date.now()) throw new Error('上传内容已过期，请重新选择文件')
        if (
          upload.accountId !== account ||
          upload.type !== type ||
          upload.peerId !== peerId ||
          upload.kind !== segment.type ||
          !this.isCurrent(state)
        ) {
          throw new Error('上传内容与当前 QQ 会话不匹配')
        }
        if (upload.consuming) throw new Error('上传内容正在发送或已被使用')
        upload.consuming = true
        reservedUploads.push(segment.uploadId)
        return {
          type: segment.type === 'audio' ? 'record' : segment.type,
          data: {
            file: `base64://${upload.buffer.toString('base64')}`,
            ...(segment.type === 'image' ? { summary: segment.name || upload.fileName } : {}),
          },
        }
      }
    }
  }

  private async requireMessageInConversation(
    account: string,
    type: 'group' | 'private',
    peerId: string,
    messageId: string,
  ): Promise<{ state: AccountState; message: OneBotMessage }> {
    const state = this.requireConversation(account, type, peerId)
    const message = await state.connection.request<OneBotMessage>('get_msg', { message_id: messageId }, 10_000)
    if (String(message.message_id ?? '') !== messageId || message.message_type !== type) {
      throw new Error('消息标识与当前 QQ 会话不匹配')
    }
    if (type === 'group') {
      if (String(message.group_id ?? '') !== peerId) throw new Error('消息标识与当前 QQ 会话不匹配')
      return { state, message }
    }

    const senderId = String(message.sender?.user_id ?? message.user_id ?? '')
    const directPeerId = senderId && senderId !== state.selfId ? senderId : String(message.target_id ?? '')
    if (directPeerId === peerId) return { state, message }

    const messageSeq = String(message.message_seq ?? message.real_seq ?? '')
    if (!/^\d{1,24}$/.test(messageSeq)) throw new Error('消息标识与当前 QQ 会话不匹配')
    const history = await state.connection.request<{ messages?: OneBotMessage[] }>(
      'get_friend_msg_history',
      {
        user_id: peerId,
        count: 3,
        message_seq: messageSeq,
        reverse_order: false,
        disable_get_url: true,
        parse_mult_msg: false,
      },
      20_000,
    )
    if (!(history.messages ?? []).some((candidate) => String(candidate.message_id ?? '') === messageId)) {
      throw new Error('消息标识与当前 QQ 会话不匹配')
    }
    return { state, message }
  }

  private mapForwardNodes(
    account: string,
    state: AccountState,
    type: 'group' | 'private',
    peerId: string,
    nodes: Array<OneBotForwardNode | OneBotMessage>,
    path: string,
    budget: { remaining: number },
    depth = 0,
  ): ChatMessage[] {
    const messages: ChatMessage[] = []
    for (let index = 0; index < nodes.length && budget.remaining > 0; index += 1) {
      const raw = nodes[index]!
      const node = raw as OneBotForwardNode
      const nodeData = node.type === 'node' && node.data && typeof node.data === 'object' ? node.data : undefined
      const flat = raw as OneBotMessage & { content?: OneBotMessage['message'] }
      const senderId = String(nodeData?.user_id ?? flat.user_id ?? flat.sender?.user_id ?? state.selfId)
      const rawContent = nodeData?.message ?? nodeData?.content ?? flat.message ?? flat.content ?? []
      const messageId = flat.message_id ?? `forward-${depth}-${index + 1}`
      const mapped = mapMessage(
        account,
        state.selfId,
        {
          ...flat,
          self_id: state.selfId,
          message_type: type,
          group_id: type === 'group' ? peerId : undefined,
          target_id: type === 'private' ? peerId : undefined,
          user_id: senderId,
          sender: {
            ...flat.sender,
            user_id: senderId,
            nickname: nodeData?.nickname ?? flat.sender?.nickname,
          },
          time: nodeData?.time ?? flat.time,
          message_id: messageId,
          message_seq: flat.message_seq ?? messageId,
          message: rawContent as OneBotMessage['message'],
        },
        (url) => this.registerMedia(url),
        type === 'private' ? peerId : undefined,
      )
      if (!mapped) continue
      budget.remaining -= 1
      if (Array.isArray(rawContent)) {
        mapped.segments = mapped.segments.map((segment, segmentIndex) => {
          const rawSegment = rawContent[segmentIndex] as OneBotForwardNode | undefined
          const nested = rawSegment?.type === 'node' ? rawSegment.data?.message ?? rawSegment.data?.content : undefined
          if (!Array.isArray(nested)) return segment
          const nestedMessages =
            depth >= 7
              ? []
              : this.mapForwardNodes(
                  account,
                  state,
                  type,
                  peerId,
                  nested as Array<OneBotForwardNode | OneBotMessage>,
                  `${path}.${index}.${segmentIndex}`,
                  budget,
                  depth + 1,
                )
          return {
            type: 'forward' as const,
            forwardId: `inline:${path}.${index}.${segmentIndex}`,
            count: nestedMessages.length,
            preview: nestedMessages.length ? '嵌套转发消息' : '嵌套转发内容过深或为空',
            messages: nestedMessages,
          }
        })
      }
      messages.push(mapped)
    }
    return messages
  }

  private encodeHistoryCursor(
    account: string,
    type: 'group' | 'private',
    peerId: string,
    messageSeq: string,
  ): string {
    const payload: HistoryCursorPayload = { v: 1, accountId: account, type, peerId, messageSeq }
    const encoded = Buffer.from(JSON.stringify(payload)).toString('base64url')
    const signature = createHmac('sha256', this.options.token).update(encoded).digest('base64url')
    return `${encoded}.${signature}`
  }

  private decodeHistoryCursor(
    cursor: string,
    account: string,
    type: 'group' | 'private',
    peerId: string,
  ): HistoryCursorPayload {
    const [encoded, signature, extra] = cursor.split('.')
    if (!encoded || !signature || extra) throw new Error('历史游标无效')
    const expected = Buffer.from(createHmac('sha256', this.options.token).update(encoded).digest('base64url'))
    const actual = Buffer.from(signature)
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) throw new Error('历史游标无效')
    let payload: HistoryCursorPayload
    try {
      payload = JSON.parse(Buffer.from(encoded, 'base64url').toString('utf8')) as HistoryCursorPayload
    } catch {
      throw new Error('历史游标无效')
    }
    if (
      payload.v !== 1 ||
      payload.accountId !== account ||
      payload.type !== type ||
      payload.peerId !== peerId ||
      !/^\d{1,24}$/.test(payload.messageSeq)
    ) {
      throw new Error('历史游标与当前会话不匹配')
    }
    return payload
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
    return this.registerMediaEntry(source, 'message')
  }

  private registerFileMedia(source: string, fileName: string): string | undefined {
    return this.registerMediaEntry(source, 'file', fileName)
  }

  private registerMediaEntry(source: string, kind: MediaEntry['kind'], fileName?: string): string | undefined {
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
    const key = createHash('sha256').update(`${kind}\0${source}\0${fileName ?? ''}`).digest('hex').slice(0, 32)
    this.media.delete(key)
    this.media.set(key, { url: source, expiresAt: now + this.mediaTtlMs, kind, fileName })
    while (this.media.size > this.mediaMaxEntries) {
      const oldest = this.media.keys().next().value as string | undefined
      if (!oldest) break
      this.media.delete(oldest)
    }
    return `/api/media/${kind}/${key}`
  }

  private pruneMedia(now: number): void {
    for (const [key, entry] of this.media) {
      if (entry.expiresAt <= now) this.media.delete(key)
    }
  }

  private pruneUploads(now: number): void {
    for (const [uploadId, entry] of this.uploads) {
      if (entry.expiresAt <= now) this.uploads.delete(uploadId)
    }
    const totalBytes = () => [...this.uploads.values()].reduce((total, entry) => total + entry.size, 0)
    while (this.uploads.size > this.uploadMaxEntries || totalBytes() > this.uploadMaxTotalBytes) {
      const oldest = this.uploads.keys().next().value as string | undefined
      if (!oldest) break
      this.uploads.delete(oldest)
    }
  }

  private mediaHostAllowed(hostname: string): boolean {
    const host = hostname.toLowerCase()
    return ['qq.com', 'qq.com.cn', 'qpic.cn', 'gtimg.cn', 'qlogo.cn'].some(
      (suffix) => host === suffix || host.endsWith(`.${suffix}`),
    )
  }

  private versionAtLeast(actual: string | undefined, minimum: string): boolean {
    if (!actual) return false
    const parse = (value: string) => value.split('.').slice(0, 3).map((part) => Number.parseInt(part, 10) || 0)
    const left = parse(actual)
    const right = parse(minimum)
    for (let index = 0; index < 3; index += 1) {
      if ((left[index] ?? 0) > (right[index] ?? 0)) return true
      if ((left[index] ?? 0) < (right[index] ?? 0)) return false
    }
    return true
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
