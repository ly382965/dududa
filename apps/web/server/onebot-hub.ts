import { EventEmitter } from 'node:events'
import { createHash, createHmac, randomUUID, timingSafeEqual } from 'node:crypto'
import type { IncomingMessage } from 'node:http'
import type { Duplex } from 'node:stream'

import { WebSocket, WebSocketServer } from 'ws'

import type {
  Account,
  AccountCapabilityDocument,
  AccountDirectory,
  CapabilityName,
  ChatMessage,
  Conversation,
  CustomFaceCatalog,
  EssenceMessage,
  EssencePage,
  FileSendReceipt,
  ForwardedMessageBundle,
  GroupAnnouncement,
  GroupFilePage,
  GroupMember,
  GroupMemberDirectory,
  GroupPermissions,
  HistoryPage,
  NotificationInbox,
  OperationPermission,
  OutgoingMessageSegment,
  QqNotification,
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
  mapFriendContact,
  mapFriendConversation,
  mapGroupContact,
  mapGroupConversation,
  mapGroupFile,
  mapGroupFolder,
  mapGroupMember,
  mapMessage,
  messagePreview,
  recentConversationType,
  type OneBotFriend,
  type OneBotGroupFile,
  type OneBotGroupFolder,
  type OneBotGroup,
  type OneBotGroupMember,
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
  action: string
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
  packetAvailable: boolean
  refreshedAt: number
  directory: AccountDirectory
  notifications: Map<string, CachedNotification>
  groupMembers: Map<string, { members: GroupMember[]; refreshedAt: number }>
}

interface CachedNotification {
  notification: QqNotification
  flag?: string
  resolveKind?: 'friend' | 'group'
}

interface OneBotGroupSystemItem {
  request_id?: number | string
  invitor_uin?: number | string
  invitor_nick?: string
  actor?: number | string
  requester_nick?: string
  group_id?: number | string
  group_name?: string
  message?: string
  checked?: boolean
}

interface OneBotEssenceItem {
  msg_seq?: number | string
  sender_id?: number | string
  sender_nick?: string
  operator_id?: number | string
  operator_nick?: string
  message_id?: number | string
  operator_time?: number | string
  content?: OneBotSegment[]
}

interface OneBotAnnouncement {
  notice_id?: string
  sender_id?: number | string
  publish_time?: number | string
  read_num?: number | string
  message?: {
    text?: string
    image?: Array<{ id?: string }>
    images?: Array<{ id?: string }>
  }
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

interface CustomFaceEntry {
  accountId: string
  type: 'group' | 'private'
  peerId: string
  url: string
  expiresAt: number
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
  groupFileUploadTimeoutMs?: number
  recentConversationCount?: number
  messageHistoryCount?: number
  mediaTtlMs?: number
  mediaMaxEntries?: number
  customFaceTtlMs?: number
  customFaceMaxEntries?: number
  uploadTtlMs?: number
  uploadMaxEntries?: number
  uploadMaxTotalBytes?: number
}

const emittedMessageTtlMs = 5 * 60_000
const emittedMessageMaxEntries = 5_000
const defaultMediaTtlMs = 30 * 60_000
const defaultMediaMaxEntries = 2_000
const defaultCustomFaceTtlMs = 10 * 60_000
const defaultCustomFaceMaxEntries = 1_000
const defaultUploadTtlMs = 10 * 60_000
const defaultUploadMaxEntries = 32
const defaultUploadMaxTotalBytes = 100 * 1024 * 1024
const unknownGroupUploadGuardMs = 10 * 60_000

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
  'request.friend.resolve',
  'request.group.history',
  'request.group.resolve',
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
        action,
        resolve: (value) => resolve(value as T),
        reject,
        timer,
      })
      this.socket.send(JSON.stringify({ action, params, echo }), (error) => {
        if (!error) return
        clearTimeout(timer)
        this.pending.delete(echo)
        reject(new OneBotActionError(`NapCat action 发送失败: ${action}`, 'unknown'))
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
            `NapCat action 被拒绝: ${pending.action} (${Number(response.retcode ?? -1)})`,
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
  private readonly customFaces = new Map<string, CustomFaceEntry>()
  private readonly uploads = new Map<string, StagedUpload>()
  private readonly uncertainGroupUploads = new Map<string, { state: 'inflight' | 'unknown'; expiresAt: number }>()
  private readonly resolvingNotifications = new Set<string>()
  private readonly actionTimeoutMs: number
  private readonly groupFileUploadTimeoutMs: number
  private readonly recentConversationCount: number
  private readonly messageHistoryCount: number
  private readonly mediaTtlMs: number
  private readonly mediaMaxEntries: number
  private readonly customFaceTtlMs: number
  private readonly customFaceMaxEntries: number
  private readonly uploadTtlMs: number
  private readonly uploadMaxEntries: number
  private readonly uploadMaxTotalBytes: number
  private closed = false

  constructor(private readonly options: HubOptions) {
    super()
    this.actionTimeoutMs = options.actionTimeoutMs ?? 20_000
    this.groupFileUploadTimeoutMs = options.groupFileUploadTimeoutMs ?? 120_000
    this.recentConversationCount = options.recentConversationCount ?? 100
    this.messageHistoryCount = options.messageHistoryCount ?? 50
    this.mediaTtlMs = Math.max(1, Math.floor(options.mediaTtlMs ?? defaultMediaTtlMs))
    this.mediaMaxEntries = Math.max(1, Math.floor(options.mediaMaxEntries ?? defaultMediaMaxEntries))
    this.customFaceTtlMs = Math.max(1, Math.floor(options.customFaceTtlMs ?? defaultCustomFaceTtlMs))
    this.customFaceMaxEntries = Math.max(1, Math.floor(options.customFaceMaxEntries ?? defaultCustomFaceMaxEntries))
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

  botId(account: string): string {
    return this.requireAccount(account).account.botId
  }

  async customFaceCatalog(account: string, type: 'group' | 'private', peerId: string): Promise<CustomFaceCatalog> {
    const state = this.requireConversation(account, type, peerId)
    this.requireCapability(state, 'message.custom_faces')
    const data = await state.connection.request<unknown>('fetch_custom_face', { count: 48 }, 30_000)
    if (!Array.isArray(data)) throw new Error('NapCat 收藏表情响应无效')

    const urls = [...new Set(data.filter((item): item is string => typeof item === 'string'))]
      .filter((source) => this.customFaceSourceAllowed(source))
      .slice(0, 48)
    const now = Date.now()
    this.pruneCustomFaces(now)

    const items = urls.map((source) => {
      const handle = createHmac('sha256', this.options.token)
        .update(`custom-face\0${account}\0${type}\0${peerId}\0${source}`)
        .digest('hex')
        .slice(0, 32)
      const expiresAt = now + this.customFaceTtlMs
      this.customFaces.delete(handle)
      this.customFaces.set(handle, { accountId: account, type, peerId, url: source, expiresAt })
      return {
        handle,
        previewUrl: `/api/accounts/${encodeURIComponent(account)}/conversations/${type}/${encodeURIComponent(peerId)}/custom-faces/${handle}/preview`,
        expiresAt,
      }
    })
    while (this.customFaces.size > this.customFaceMaxEntries) {
      const oldest = this.customFaces.keys().next().value as string | undefined
      if (!oldest) break
      this.customFaces.delete(oldest)
    }
    return {
      accountId: account,
      conversationId: conversationId(account, type, peerId),
      items: items.filter((item) => this.customFaces.has(item.handle)),
      refreshedAt: now,
    }
  }

  customFaceUrl(account: string, type: 'group' | 'private', peerId: string, handle: string): string | undefined {
    this.requireConversation(account, type, peerId)
    return this.resolveCustomFace(account, type, peerId, handle)?.url
  }

  async directorySnapshot(account: string, refresh = false): Promise<AccountDirectory> {
    const state = this.requireAccount(account)
    this.requireCapability(state, 'directory.friends')
    this.requireCapability(state, 'directory.groups')
    if (refresh || !state.directory.refreshedAt) await this.refreshAccount(state, true)
    return {
      ...state.directory,
      friends: state.directory.friends.map((friend) => ({ ...friend })),
      groups: state.directory.groups.map((group) => ({ ...group })),
    }
  }

  async notificationInbox(account: string, refresh = false): Promise<NotificationInbox> {
    const state = this.requireAccount(account)
    if (refresh) {
      const capability = this.capabilityDocument(state).actions['request.group.history']
      if (capability.status === 'supported') {
        const data = await state.connection.request<{
          invited_requests?: OneBotGroupSystemItem[]
          InvitedRequest?: OneBotGroupSystemItem[]
          join_requests?: OneBotGroupSystemItem[]
        }>('get_group_system_msg', { count: 50 }, 30_000)
        this.mergeGroupSystemNotifications(
          state,
          data.invited_requests ?? data.InvitedRequest ?? [],
          data.join_requests ?? [],
        )
        await this.refreshGroupRequestPermissions(state, false)
      }
    }
    return {
      accountId: account,
      items: [...state.notifications.values()]
        .map((entry) => ({ ...entry.notification }))
        .sort((left, right) => right.occurredAt - left.occurredAt)
        .slice(0, 500),
      limitations: {
        friendHistory: 'NapCat 无法回填普通好友申请；这里只保留本次服务运行期间观察到的申请。',
      },
      refreshedAt: Date.now(),
    }
  }

  async resolveNotification(
    account: string,
    notificationId: string,
    action: 'accept' | 'reject',
  ): Promise<QqNotification> {
    const state = this.requireAccount(account)
    const cached = state.notifications.get(notificationId)
    if (!cached || !cached.flag || !cached.resolveKind) throw new Error('通知不存在或不可处理')
    if (cached.notification.state !== 'pending') throw new Error('通知已经处理')
    const resolvingKey = `${account}:${notificationId}`
    if (this.resolvingNotifications.has(resolvingKey)) throw new Error('通知正在处理，请等待 NapCat 返回结果')
    this.resolvingNotifications.add(resolvingKey)
    let actionStarted = false
    try {
      const capability: CapabilityName =
        cached.resolveKind === 'friend' ? 'request.friend.resolve' : 'request.group.resolve'
      this.requireCapability(state, capability)
      if (cached.notification.kind === 'group-request') {
        const groupId = cached.notification.groupId
        if (!groupId) throw new Error('群申请缺少群号，无法确认处理权限')
        const directory = await this.memberDirectory(account, groupId, true)
        if (directory.selfRole !== 'owner' && directory.selfRole !== 'admin') {
          throw new Error('只有群主或管理员可以处理入群申请')
        }
      }
      const latestBeforeAction = state.notifications.get(notificationId)
      if (
        this.accounts.get(account) !== state ||
        !latestBeforeAction ||
        latestBeforeAction.flag !== cached.flag ||
        latestBeforeAction.resolveKind !== cached.resolveKind ||
        latestBeforeAction.notification.state !== 'pending'
      ) {
        throw new Error('通知已经处理')
      }
      actionStarted = true
      await state.connection.request(
        cached.resolveKind === 'friend' ? 'set_friend_add_request' : 'set_group_add_request',
        cached.resolveKind === 'friend'
          ? { flag: cached.flag, approve: action === 'accept', remark: '' }
          : { flag: cached.flag, approve: action === 'accept', reason: '' },
        this.actionTimeoutMs,
      )
      const current = state.notifications.get(notificationId) ?? cached
      current.notification = {
        ...current.notification,
        state: action === 'accept' ? 'accepted' : 'rejected',
        actionable: false,
      }
      this.broadcast({ type: 'notification.changed', accountId: account, notification: { ...current.notification } })
      if (action === 'accept') void this.refreshAccount(state, true).then(() => this.broadcast({ type: 'directory.changed', accountId: account }))
      return { ...current.notification }
    } catch (error) {
      if (actionStarted && error instanceof OneBotActionError && error.outcome === 'unknown') {
        const current = state.notifications.get(notificationId) ?? cached
        if (current.notification.state === 'pending') {
          current.notification = {
            ...current.notification,
            state: 'handled',
            actionable: false,
            comment: [current.notification.comment, '处理结果待 NapCat 刷新确认'].filter(Boolean).join(' · '),
          }
          this.broadcast({ type: 'notification.changed', accountId: account, notification: { ...current.notification } })
        }
        if (cached.resolveKind === 'group') void this.notificationInbox(account, true).catch(() => undefined)
      }
      throw error
    } finally {
      this.resolvingNotifications.delete(resolvingKey)
    }
  }

  async memberDirectory(account: string, groupId: string, refresh = false): Promise<GroupMemberDirectory> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.members')
    const cached = state.groupMembers.get(groupId)
    let members = cached?.members
    if (refresh || !cached || Date.now() - cached.refreshedAt > 60_000) {
      const raw = await state.connection.request<OneBotGroupMember[]>(
        'get_group_member_list',
        { group_id: groupId, no_cache: refresh },
        60_000,
      )
      const roleOrder: Record<GroupMember['role'], number> = { owner: 0, admin: 1, member: 2 }
      members = raw
        .map((member) => mapGroupMember(account, groupId, member))
        .filter((member): member is GroupMember => Boolean(member))
        .sort(
          (left, right) =>
            roleOrder[left.role] - roleOrder[right.role] ||
            (left.card || left.nickname || left.userId).localeCompare(right.card || right.nickname || right.userId, 'zh-CN'),
        )
      state.groupMembers.set(groupId, { members, refreshedAt: Date.now() })
    }
    const selfRole = members?.find((member) => member.userId === state.selfId)?.role
    const permissions = this.groupPermissions(state, selfRole)
    if (permissions.mentionAll.allowed) {
      try {
        const atAll = await state.connection.request<{
          can_at_all?: boolean
          remain_at_all_count_for_group?: number | string
          remain_at_all_count_for_self?: number | string
        }>('get_group_at_all_remain', { group_id: groupId }, 15_000)
        if (atAll.can_at_all !== true) {
          permissions.mentionAll = { allowed: false, reason: '当前 QQ 或群聊已没有可用的 @全体成员 次数' }
        }
      } catch {
        permissions.mentionAll = { allowed: false, reason: '暂时无法确认 @全体成员 剩余次数' }
      }
    }
    return {
      accountId: account,
      groupId,
      selfUserId: state.selfId,
      selfRole,
      members: (members ?? []).map((member) => ({ ...member })),
      permissions,
      refreshedAt: state.groupMembers.get(groupId)?.refreshedAt ?? Date.now(),
    }
  }

  async setGroupAdmin(account: string, groupId: string, userId: string, enabled: boolean): Promise<void> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.admin')
    const directory = await this.memberDirectory(account, groupId, true)
    const target = directory.members.find((member) => member.userId === userId)
    if (!target) throw new Error('群成员不存在')
    if (directory.selfRole !== 'owner' || target.userId === state.selfId || target.role === 'owner') {
      throw new Error('当前 QQ 群角色无权设置该成员为管理员')
    }
    await state.connection.request('set_group_admin', { group_id: groupId, user_id: userId, enable: enabled }, 30_000)
    target.role = enabled ? 'admin' : 'member'
    this.replaceCachedMember(state, groupId, target)
    this.broadcast({ type: 'group.members.changed', accountId: account, groupId })
  }

  async kickGroupMember(account: string, groupId: string, userId: string): Promise<void> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.kick')
    const directory = await this.memberDirectory(account, groupId, true)
    const target = directory.members.find((member) => member.userId === userId)
    const permitted =
      target &&
      target.userId !== state.selfId &&
      target.role !== 'owner' &&
      (directory.selfRole === 'owner' || (directory.selfRole === 'admin' && target.role === 'member'))
    if (!permitted) throw new Error('当前 QQ 群角色无权移出该成员')
    await state.connection.request(
      'set_group_kick',
      { group_id: groupId, user_id: userId, reject_add_request: false },
      30_000,
    )
    const cached = state.groupMembers.get(groupId)
    if (cached) cached.members = cached.members.filter((member) => member.userId !== userId)
    this.broadcast({ type: 'group.members.changed', accountId: account, groupId })
  }

  async setGroupCard(account: string, groupId: string, userId: string, card: string): Promise<void> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.card')
    const directory = await this.memberDirectory(account, groupId, true)
    const target = directory.members.find((member) => member.userId === userId)
    if (!target) throw new Error('群成员不存在')
    if (userId !== state.selfId) throw new Error('群名片接口只允许修改当前 QQ 自己的群名片')
    await state.connection.request('set_group_card', { group_id: groupId, user_id: userId, card }, 30_000)
    this.replaceCachedMember(state, groupId, { ...target, card })
    this.broadcast({ type: 'group.members.changed', accountId: account, groupId })
  }

  async renameGroup(account: string, groupId: string, name: string): Promise<void> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.rename')
    const directory = await this.memberDirectory(account, groupId, true)
    this.assertPermission(directory.permissions.rename, '当前 QQ 群角色无权修改群名称')
    await state.connection.request('set_group_name', { group_id: groupId, group_name: name }, 30_000)
    const group = state.directory.groups.find((item) => item.groupId === groupId)
    if (group) group.groupName = name
    const conversation = state.conversations.get(conversationId(account, 'group', groupId))
    if (conversation) {
      conversation.name = group?.remark || name
      conversation.topic = name
    }
    this.broadcast({ type: 'directory.changed', accountId: account })
    this.broadcast({ type: 'workspace.refresh' })
  }

  async setGroupMuteAll(account: string, groupId: string, enabled: boolean): Promise<void> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.mute_all')
    const directory = await this.memberDirectory(account, groupId, true)
    this.assertPermission(directory.permissions.muteAll, '当前 QQ 群角色无权设置全员禁言')
    await state.connection.request('set_group_whole_ban', { group_id: groupId, enable: enabled }, 30_000)
    const group = state.directory.groups.find((item) => item.groupId === groupId)
    if (group) group.wholeMuted = enabled
    this.broadcast({ type: 'directory.changed', accountId: account })
  }

  async quitGroup(account: string, groupId: string): Promise<void> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.quit')
    const directory = await this.memberDirectory(account, groupId, true)
    this.assertPermission(directory.permissions.quit, '当前账号无法退出该群聊')
    await state.connection.request('set_group_leave', { group_id: groupId, is_dismiss: false }, 30_000)
    state.directory.groups = state.directory.groups.filter((group) => group.groupId !== groupId)
    state.conversations.delete(conversationId(account, 'group', groupId))
    state.groupMembers.delete(groupId)
    this.broadcast({ type: 'directory.changed', accountId: account })
    this.broadcast({ type: 'workspace.refresh' })
  }

  async essenceMessages(account: string, groupId: string): Promise<EssencePage> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.essence')
    const raw = await state.connection.request<OneBotEssenceItem[]>('get_essence_msg_list', { group_id: groupId }, 60_000)
    const all = raw.map((item, index) => this.mapEssenceMessage(state, groupId, item, index))
    return { items: all.slice(0, 500), offset: 0, hasMore: false, truncated: all.length > 500 }
  }

  async groupAnnouncements(account: string, groupId: string): Promise<GroupAnnouncement[]> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.announcements')
    const raw = await state.connection.request<OneBotAnnouncement[]>('_get_group_notice', { group_id: groupId }, 60_000)
    return raw.flatMap((announcement) => {
      const rawId = String(announcement.notice_id ?? '')
      if (!rawId || rawId.length > 512) return []
      const images = announcement.message?.images ?? announcement.message?.image ?? []
      const imageUrls = images.flatMap((image) => {
        const imageId = String(image.id ?? '')
        if (!imageId || imageId.length > 512) return []
        const url = this.registerMedia(`https://gdynamic.qpic.cn/gdynamic/${encodeURIComponent(imageId)}/0`)
        return url ? [url] : []
      })
      return [{
        id: this.encodeScopedId('notice', account, groupId, rawId),
        accountId: account,
        groupId,
        senderId: String(announcement.sender_id ?? ''),
        publishTime: Number(announcement.publish_time) || 0,
        content: String(announcement.message?.text ?? '').slice(0, 20_000),
        imageUrls,
        readCount: Number(announcement.read_num) || undefined,
      }]
    })
  }

  async deleteGroupAnnouncement(account: string, groupId: string, announcementId: string): Promise<void> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.announcements')
    const directory = await this.memberDirectory(account, groupId, true)
    this.assertPermission(directory.permissions.deleteAnnouncements, '当前 QQ 群角色无权删除群公告')
    const rawId = this.decodeScopedId('notice', account, groupId, announcementId)
    await state.connection.request('_del_group_notice', { group_id: groupId, notice_id: rawId }, 30_000)
    this.broadcast({ type: 'group.resources.changed', accountId: account, groupId, resource: 'announcements' })
  }

  async groupFiles(account: string, groupId: string, parentId: string, limit: number): Promise<GroupFilePage> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.files')
    const rawParentId = parentId === '/' ? '/' : this.decodeScopedId('folder', account, groupId, parentId)
    const action = rawParentId === '/' ? 'get_group_root_files' : 'get_group_files_by_folder'
    const raw = await state.connection.request<{ files?: OneBotGroupFile[]; folders?: OneBotGroupFolder[] }>(
      action,
      rawParentId === '/'
        ? { group_id: groupId, file_count: limit }
        : { group_id: groupId, folder_id: rawParentId, file_count: limit },
      60_000,
    )
    let permissions = this.groupPermissions(state)
    try {
      permissions = (await this.memberDirectory(account, groupId)).permissions
    } catch {
      permissions.uploadFiles = { allowed: false, reason: '无法确认当前 QQ 的群成员身份' }
      permissions.manageFiles = { allowed: false, reason: '无法确认当前 QQ 的群管理权限' }
    }
    return {
      accountId: account,
      groupId,
      parentId,
      files: (raw.files ?? []).flatMap((file) => {
        const mapped = mapGroupFile(account, groupId, rawParentId, file)
        return mapped
          ? [{ ...mapped, id: this.encodeScopedId('file', account, groupId, mapped.id), parentId }]
          : []
      }),
      folders: (raw.folders ?? []).flatMap((folder) => {
        const mapped = mapGroupFolder(account, groupId, rawParentId, folder)
        return mapped
          ? [{ ...mapped, id: this.encodeScopedId('folder', account, groupId, mapped.id), parentId }]
          : []
      }),
      truncated: (raw.files?.length ?? 0) + (raw.folders?.length ?? 0) >= limit,
      permissions: {
        readFiles: permissions.readFiles,
        uploadFiles: permissions.uploadFiles,
        manageFiles: permissions.manageFiles,
        packetFiles: permissions.packetFiles,
        renameFolders: permissions.renameFolders,
      },
    }
  }

  async groupFileDownloadUrl(
    account: string,
    groupId: string,
    fileId: string,
    fileName: string,
  ): Promise<{ url: string }> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.files')
    this.assertPermission(
      this.groupPermissions(state).packetFiles,
      '当前 NapCat Packet 服务不可用，无法下载群文件',
    )
    const rawFileId = this.decodeScopedId('file', account, groupId, fileId)
    const result = await state.connection.request<{ url?: string }>(
      'get_group_file_url',
      { group_id: groupId, file_id: rawFileId },
      30_000,
    )
    const url = result.url ? this.registerFileMedia(result.url, fileName) : undefined
    if (!url) throw new Error('NapCat 未返回可用的群文件下载地址')
    return { url }
  }

  async uploadGroupResource(
    account: string,
    groupId: string,
    parentId: string,
    input: { buffer: Buffer; fileName: string; size: number },
  ): Promise<FileSendReceipt> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.files')
    const directory = await this.memberDirectory(account, groupId, true)
    this.assertPermission(directory.permissions.uploadFiles, '当前 QQ 群角色无权上传群文件')
    if (input.size !== input.buffer.length || input.size <= 0 || input.size > 25 * 1024 * 1024) {
      throw new Error('上传文件大小无效')
    }
    const folder = parentId === '/' ? undefined : this.decodeScopedId('folder', account, groupId, parentId)
    await this.uploadGroupFileOnce(state, account, groupId, parentId, input, folder)
    this.broadcast({ type: 'group.resources.changed', accountId: account, groupId, resource: 'files' })
    return { kind: 'file', name: input.fileName, size: input.size }
  }

  private async uploadGroupFileOnce(
    state: AccountState,
    account: string,
    groupId: string,
    parentId: string,
    input: { buffer: Buffer; fileName: string; size: number },
    folder?: string,
  ): Promise<{ file_id?: string | null }> {
    const now = Date.now()
    for (const [key, guard] of this.uncertainGroupUploads) {
      if (guard.expiresAt <= now) this.uncertainGroupUploads.delete(key)
    }
    const uploadKey = createHash('sha256')
      .update(account)
      .update('\0')
      .update(groupId)
      .update('\0')
      .update(parentId)
      .update('\0')
      .update(input.fileName)
      .update('\0')
      .update(String(input.size))
      .update('\0')
      .update(input.buffer)
      .digest('hex')
    const existingGuard = this.uncertainGroupUploads.get(uploadKey)
    if (existingGuard && existingGuard.expiresAt > now) {
      throw new Error(
        existingGuard.state === 'inflight'
          ? '相同群文件正在上传；为避免重复上传，本次请求未发送到 NapCat'
          : '相同群文件的上次上传结果未知；为避免重复上传，请先刷新群文件列表，10 分钟后再决定是否重试',
      )
    }
    this.uncertainGroupUploads.set(uploadKey, {
      state: 'inflight',
      expiresAt: now + this.groupFileUploadTimeoutMs + unknownGroupUploadGuardMs,
    })
    try {
      const result = await state.connection.request<{ file_id?: string | null }>(
        'upload_group_file',
        {
          group_id: groupId,
          file: `base64://${input.buffer.toString('base64')}`,
          name: input.fileName,
          ...(folder ? { folder } : {}),
        },
        this.groupFileUploadTimeoutMs,
      )
      this.uncertainGroupUploads.delete(uploadKey)
      return result
    } catch (error) {
      if (error instanceof OneBotActionError && error.outcome === 'unknown') {
        this.uncertainGroupUploads.set(uploadKey, {
          state: 'unknown',
          expiresAt: Date.now() + unknownGroupUploadGuardMs,
        })
        throw new Error('群文件上传结果未知；为避免重复上传，请先刷新群文件列表，10 分钟内不会重放相同文件')
      }
      this.uncertainGroupUploads.delete(uploadKey)
      throw error
    }
  }

  async mutateGroupFile(
    account: string,
    groupId: string,
    fileId: string,
    mutation:
      | { operation: 'move'; currentParentId: string; targetParentId: string }
      | { operation: 'rename'; currentParentId: string; name: string },
  ): Promise<void> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.files')
    const directory = await this.memberDirectory(account, groupId, true)
    this.assertPermission(directory.permissions.manageFiles, '当前 QQ 群角色无权管理群文件')
    this.assertPermission(directory.permissions.packetFiles, '当前 NapCat Packet 服务不可用，无法移动或重命名群文件')
    const rawFileId = this.decodeScopedId('file', account, groupId, fileId)
    const currentParentId =
      mutation.currentParentId === '/'
        ? '/'
        : this.decodeScopedId('folder', account, groupId, mutation.currentParentId)
    if (mutation.operation === 'move') {
      await state.connection.request(
        'move_group_file',
        {
          group_id: groupId,
          file_id: rawFileId,
          current_parent_directory: currentParentId,
          target_parent_directory:
            mutation.targetParentId === '/'
              ? '/'
              : this.decodeScopedId('folder', account, groupId, mutation.targetParentId),
        },
        60_000,
      )
      this.broadcast({ type: 'group.resources.changed', accountId: account, groupId, resource: 'files' })
      return
    }
    await state.connection.request(
      'rename_group_file',
      {
        group_id: groupId,
        file_id: rawFileId,
        current_parent_directory: currentParentId,
        new_name: mutation.name,
      },
      60_000,
    )
    this.broadcast({ type: 'group.resources.changed', accountId: account, groupId, resource: 'files' })
  }

  async deleteGroupFile(account: string, groupId: string, fileId: string): Promise<void> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.files')
    const directory = await this.memberDirectory(account, groupId, true)
    this.assertPermission(directory.permissions.manageFiles, '当前 QQ 群角色无权删除群文件')
    const rawFileId = this.decodeScopedId('file', account, groupId, fileId)
    await state.connection.request('delete_group_file', { group_id: groupId, file_id: rawFileId }, 60_000)
    this.broadcast({ type: 'group.resources.changed', accountId: account, groupId, resource: 'files' })
  }

  async createGroupFolder(account: string, groupId: string, name: string): Promise<void> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.files')
    const directory = await this.memberDirectory(account, groupId, true)
    this.assertPermission(directory.permissions.manageFiles, '当前 QQ 群角色无权创建群文件夹')
    await state.connection.request('create_group_file_folder', { group_id: groupId, folder_name: name }, 60_000)
    this.broadcast({ type: 'group.resources.changed', accountId: account, groupId, resource: 'files' })
  }

  async deleteGroupFolder(account: string, groupId: string, folderId: string): Promise<void> {
    const state = this.requireConversation(account, 'group', groupId)
    this.requireCapability(state, 'group.files')
    const directory = await this.memberDirectory(account, groupId, true)
    this.assertPermission(directory.permissions.manageFiles, '当前 QQ 群角色无权删除群文件夹')
    const rawFolderId = this.decodeScopedId('folder', account, groupId, folderId)
    await state.connection.request('delete_group_folder', { group_id: groupId, folder_id: rawFolderId }, 60_000)
    this.broadcast({ type: 'group.resources.changed', accountId: account, groupId, resource: 'files' })
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
    const result = type === 'group'
      ? await this.uploadGroupFileOnce(state, account, peerId, '/', input)
      : await state.connection.request<{ file_id?: string | null }>(
          'upload_private_file',
          {
            user_id: peerId,
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
        reverse_order: decodedCursor ? direction === 'before' : false,
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
    const boundarySeq = direction === 'before' ? firstSeq : lastSeq
    let hasMoreInDirection = mappedMessages.length > count
    if (!hasMoreInDirection && boundarySeq) {
      try {
        const adjacent = await state.connection.request<{ messages?: OneBotMessage[] }>(action, {
          [key]: peerId,
          count: 2,
          message_seq: boundarySeq,
          reverse_order: direction === 'before',
          disable_get_url: true,
          parse_mult_msg: false,
        })
        hasMoreInDirection = (adjacent.messages ?? []).some((message) => {
          const sequence = String(message.message_seq ?? message.real_seq ?? '')
          return Boolean(sequence) && sequence !== boundarySeq
        })
      } catch (error) {
        // A transient boundary read must not hide a page that was already loaded.
        hasMoreInDirection = !(error instanceof Error && /不存在|not found/i.test(error.message))
      }
    }
    return {
      messages,
      beforeCursor: firstSeq ? this.encodeHistoryCursor(account, type, peerId, firstSeq) : undefined,
      afterCursor: lastSeq ? this.encodeHistoryCursor(account, type, peerId, lastSeq) : undefined,
      hasMoreBefore: direction === 'before' && hasMoreInDirection,
      hasMoreAfter: direction === 'after' && hasMoreInDirection,
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
    if (segments.some((segment) => segment.type === 'mention' && segment.all)) {
      if (type !== 'group') throw new Error('@全体成员只能发送到群聊')
      const directory = await this.memberDirectory(account, peerId, true)
      this.assertPermission(directory.permissions.mentionAll, '当前 QQ 无权提及全体成员')
    }
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
                : segment.type === 'custom_face'
                  ? 'message.custom_faces'
                  : (`message.send.${segment.type}` as CapabilityName)
      this.requireCapability(state, capability)
    }
    const action = type === 'group' ? 'send_group_msg' : 'send_private_msg'
    const key = type === 'group' ? 'group_id' : 'user_id'
    const reservedUploads: string[] = []
    let outgoing: Array<{ type: string; data: Record<string, string | number> }>
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
    this.customFaces.clear()
    this.uploads.clear()
    this.uncertainGroupUploads.clear()
    this.resolvingNotifications.clear()
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
      packetAvailable: false,
      refreshedAt: 0,
      directory: previous?.directory ?? { accountId: id, friends: [], groups: [], refreshedAt: 0 },
      notifications: previous?.notifications ?? new Map(),
      groupMembers: new Map(),
    }
    this.accounts.set(id, state)
    this.broadcast({ type: 'runtime.status', status: this.runtimeStatus() })
    void this.initializeAccount(state)
  }

  private async initializeAccount(state: AccountState): Promise<void> {
    try {
      const [login, status, version, packetAvailable] = await Promise.all([
        state.connection.request<OneBotLoginInfo>('get_login_info'),
        state.connection.request<{ online?: boolean; good?: boolean }>('get_status'),
        state.connection.request<{ app_name?: string; app_version?: string; protocol_version?: string }>('get_version_info'),
        state.connection.request<null>('nc_get_packet_status').then(
          () => true,
          () => false,
        ),
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
      state.packetAvailable = packetAvailable
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
    const [groupsResult, friendsResult, categorizedFriendsResult, recentResult] = await Promise.allSettled([
      state.connection.request<OneBotGroup[]>('get_group_list', { no_cache: false }, 30_000),
      state.connection.request<OneBotFriend[]>('get_friend_list', { no_cache: false }, 60_000),
      state.connection.request<Array<{
        categoryId?: number | string
        categoryName?: string
        buddyList?: OneBotFriend[]
      }>>('get_friends_with_category', {}, 60_000),
      state.connection.request<OneBotRecentContact[]>('get_recent_contact', { count: this.recentConversationCount }, 30_000),
    ])
    if (!this.isCurrent(state)) return
    const anyFulfilled = [groupsResult, friendsResult, categorizedFriendsResult, recentResult].some(
      (result) => result.status === 'fulfilled',
    )
    if (!anyFulfilled) return
    const categorizedFriends =
      categorizedFriendsResult.status === 'fulfilled'
        ? categorizedFriendsResult.value.flatMap((category) =>
            (category.buddyList ?? []).map((friend) => ({
              ...friend,
              categoryId: category.categoryId,
              categoryName: category.categoryName,
            })),
          )
        : []
    const categorizedById = new Map(categorizedFriends.map((friend) => [String(friend.user_id), friend]))
    const rawFriends =
      friendsResult.status === 'fulfilled'
        ? friendsResult.value.map((friend) => ({
            ...friend,
            ...categorizedById.get(String(friend.user_id)),
          }))
        : categorizedFriends.length > 0
          ? categorizedFriends
          : undefined
    const friends =
      rawFriends
        ? rawFriends
            .map((friend) => mapFriendContact(state.account.id, friend))
            .filter((friend): friend is NonNullable<typeof friend> => Boolean(friend))
        : state.directory.friends
    const groups =
      groupsResult.status === 'fulfilled'
        ? groupsResult.value
            .map((group) => mapGroupContact(state.account.id, group))
            .filter((group): group is NonNullable<typeof group> => Boolean(group))
        : state.directory.groups
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
    if (rawFriends) {
      for (const friend of rawFriends) {
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
    state.directory = { accountId: state.account.id, friends, groups, refreshedAt: state.refreshedAt }
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
    if (postType === 'request') {
      const requestType = String(event.request_type ?? '')
      const flag = String(event.flag ?? '')
      const userId = String(event.user_id ?? '')
      if (!flag || flag.length > 2_048 || !/^\d{1,20}$/.test(userId)) return
      const occurredAt = (Number(event.time) || Math.floor(Date.now() / 1_000)) * 1_000
      if (requestType === 'friend') {
        const friend = state.directory.friends.find((candidate) => candidate.userId === userId)
        const kind = 'friend-request' as const
        this.cacheNotification(state, {
          flag,
          resolveKind: 'friend',
          notification: {
            id: this.notificationId(account, kind, flag),
            accountId: account,
            kind,
            occurredAt,
            userId,
            userName: friend?.remark || friend?.nickname || userId,
            comment: String(event.comment ?? '').slice(0, 2_000),
            state: 'pending',
            actionable: true,
          },
        })
        return
      }
      if (requestType === 'group') {
        const groupId = String(event.group_id ?? '')
        if (!/^\d{5,20}$/.test(groupId)) return
        const kind = String(event.sub_type ?? '') === 'invite' ? 'group-invitation' as const : 'group-request' as const
        const group = state.directory.groups.find((candidate) => candidate.groupId === groupId)
        const notificationId = this.notificationId(account, kind, flag)
        this.cacheNotification(state, {
          flag,
          resolveKind: 'group',
          notification: {
            id: notificationId,
            accountId: account,
            kind,
            occurredAt,
            userId,
            groupId,
            groupName: group?.remark || group?.groupName || groupId,
            comment: String(event.comment ?? '').slice(0, 2_000),
            state: 'pending',
            actionable: kind === 'group-invitation',
            actionReason: kind === 'group-request' ? '正在确认当前 QQ 的群管理权限' : undefined,
          },
        })
        if (kind === 'group-request') void this.refreshGroupRequestPermission(state, notificationId, groupId, true)
      }
      return
    }
    if (postType === 'notice') {
      const noticeType = String(event.notice_type ?? '')
      const groupId = String(event.group_id ?? '')
      if (noticeType === 'friend_add') {
        void this.refreshAccount(state, true).then(() => this.broadcast({ type: 'directory.changed', accountId: account }))
        return
      }
      if (noticeType === 'group_upload' && /^\d{5,20}$/.test(groupId)) {
        this.broadcast({ type: 'group.resources.changed', accountId: account, groupId, resource: 'files' })
        return
      }
      if (noticeType === 'essence' && /^\d{5,20}$/.test(groupId)) {
        this.broadcast({ type: 'group.resources.changed', accountId: account, groupId, resource: 'essence' })
        return
      }
      if (noticeType === 'notify' && String(event.sub_type ?? '') === 'group_name' && /^\d{5,20}$/.test(groupId)) {
        const name = String(event.name_new ?? '').slice(0, 128)
        const group = state.directory.groups.find((candidate) => candidate.groupId === groupId)
        if (group && name) group.groupName = name
        const conversation = state.conversations.get(conversationId(account, 'group', groupId))
        if (conversation && name) {
          conversation.name = group?.remark || name
          conversation.topic = name
        }
        this.broadcast({ type: 'directory.changed', accountId: account })
        this.broadcast({ type: 'workspace.refresh' })
        return
      }
      if (noticeType === 'group_ban' && /^\d{5,20}$/.test(groupId) && String(event.user_id ?? '') === '0') {
        const group = state.directory.groups.find((candidate) => candidate.groupId === groupId)
        if (group) group.wholeMuted = Number(event.duration) > 0 || String(event.sub_type ?? '') === 'ban'
        this.broadcast({ type: 'directory.changed', accountId: account })
        return
      }
      if (noticeType === 'group_card' && /^\d{5,20}$/.test(groupId)) {
        const userId = String(event.user_id ?? '')
        const cached = state.groupMembers.get(groupId)
        const member = cached?.members.find((candidate) => candidate.userId === userId)
        if (member) member.card = String(event.card_new ?? '').slice(0, 128)
        this.broadcast({ type: 'group.members.changed', accountId: account, groupId })
        return
      }
      const kind =
        noticeType === 'group_increase'
          ? 'group-member-increase' as const
          : noticeType === 'group_decrease'
            ? 'group-member-decrease' as const
            : noticeType === 'group_admin'
              ? 'group-admin-change' as const
              : undefined
      if (kind && /^\d{5,20}$/.test(groupId)) {
        const userId = String(event.user_id ?? '')
        const operatorId = String(event.operator_id ?? '')
        if (!/^\d{1,20}$/.test(userId)) return
        const occurredAt = (Number(event.time) || Math.floor(Date.now() / 1_000)) * 1_000
        const cachedMembers = state.groupMembers.get(groupId)?.members ?? []
        const user = cachedMembers.find((member) => member.userId === userId)
        const operator = cachedMembers.find((member) => member.userId === operatorId)
        const group = state.directory.groups.find((candidate) => candidate.groupId === groupId)
        this.cacheNotification(state, {
          notification: {
            id: this.notificationId(
              account,
              kind,
              `${occurredAt}:${groupId}:${userId}:${operatorId}:${String(event.sub_type ?? '')}`,
            ),
            accountId: account,
            kind,
            occurredAt,
            userId,
            userName: user?.card || user?.nickname || userId,
            groupId,
            groupName: group?.remark || group?.groupName || groupId,
            operatorId: /^\d{1,20}$/.test(operatorId) ? operatorId : undefined,
            operatorName: operator?.card || operator?.nickname || undefined,
            comment: String(event.sub_type ?? '').slice(0, 128),
            state: 'handled',
            actionable: false,
          },
        })
        state.groupMembers.delete(groupId)
        if (group) {
          if (kind === 'group-member-increase') group.memberCount += 1
          if (kind === 'group-member-decrease') group.memberCount = Math.max(0, group.memberCount - 1)
        }
        this.broadcast({ type: 'group.members.changed', accountId: account, groupId })
        this.broadcast({ type: 'directory.changed', accountId: account })
        if (userId === state.selfId) {
          void this.refreshAccount(state, true).then(() => {
            this.broadcast({ type: 'directory.changed', accountId: account })
            this.broadcast({ type: 'workspace.refresh' })
          })
        }
        return
      }
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
    if (!/^\d{5,20}$/.test(peerId)) {
      throw new Error(`QQ 会话不存在: ${account}:${type}:${peerId}`)
    }
    const id = conversationId(account, type, peerId)
    if (!state.conversations.has(id)) {
      const contact = type === 'group'
        ? state.directory.groups.find((group) => group.groupId === peerId)
        : state.directory.friends.find((friend) => friend.userId === peerId)
      if (!contact) throw new Error(`QQ 会话不存在: ${account}:${type}:${peerId}`)
      state.conversations.set(id, {
        id,
        accountId: account,
        type,
        peerId,
        name: type === 'group' && 'groupName' in contact
          ? contact.remark || contact.groupName || peerId
          : 'nickname' in contact ? contact.remark || contact.nickname || peerId : peerId,
        avatar: contact.avatar,
        lastMessage: '',
        lastMessageAt: '',
        unread: 0,
        pinned: false,
        muted: false,
        members: type === 'group' && 'memberCount' in contact ? contact.memberCount : undefined,
        updatedAt: 0,
      })
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

  private groupPermissions(state: AccountState, selfRole?: GroupMember['role']): GroupPermissions {
    const manager = selfRole === 'owner' || selfRole === 'admin'
    const capability = (name: CapabilityName, roleAllowed = true, roleReason = '当前 QQ 群角色无权执行此操作') => {
      const action = this.capabilityDocument(state).actions[name]
      if (action.status !== 'supported') return { allowed: false, reason: action.reason || `${name} 当前不可用` }
      return roleAllowed ? { allowed: true } : { allowed: false, reason: roleReason }
    }
    return {
      mentionAll: capability('message.send.mention', manager, '只有群主或管理员可以提及全体成员'),
      setAdmin: capability('group.admin', selfRole === 'owner', '只有群主可以设置管理员'),
      kickMembers: capability('group.kick', manager),
      editOwnCard: capability('group.card', Boolean(selfRole), '无法确认当前 QQ 的群成员身份'),
      rename: capability('group.rename', manager),
      muteAll: capability('group.mute_all', manager),
      quit: capability('group.quit', Boolean(selfRole), '无法确认当前 QQ 的群成员身份'),
      readEssence: capability('group.essence'),
      readAnnouncements: capability('group.announcements'),
      deleteAnnouncements: capability('group.announcements', manager),
      readFiles: capability('group.files'),
      uploadFiles: capability('group.files', Boolean(selfRole), '无法确认当前 QQ 的群成员身份'),
      manageFiles: capability('group.files', manager),
      packetFiles: capability(
        'group.files',
        state.packetAvailable,
        '当前 NapCat Packet 服务不可用',
      ),
      renameFolders: capability('group.folder.rename', false, '当前 NapCat 未提供群文件夹重命名 action'),
    }
  }

  private assertPermission(permission: OperationPermission, fallback: string): void {
    if (!permission.allowed) throw new Error(permission.reason || fallback)
  }

  private assertOpaqueId(value: string, message: string): void {
    if (!value || value.length > 2_048 || /[\u0000-\u001f\u007f]/.test(value)) throw new Error(message)
  }

  private encodeScopedId(kind: 'file' | 'folder' | 'notice', accountId: string, groupId: string, value: string): string {
    this.assertOpaqueId(value, `${kind} 标识无效`)
    const encoded = Buffer.from(JSON.stringify({ v: 1, kind, accountId, groupId, value })).toString('base64url')
    const signature = createHmac('sha256', this.options.token).update(encoded).digest('base64url')
    return `${encoded}.${signature}`
  }

  private decodeScopedId(kind: 'file' | 'folder' | 'notice', accountId: string, groupId: string, token: string): string {
    if (!token || token.length > 8_192) throw new Error(`${kind} 标识无效`)
    const [encoded, signature, extra] = token.split('.')
    if (!encoded || !signature || extra) throw new Error(`${kind} 标识无效`)
    const expected = Buffer.from(createHmac('sha256', this.options.token).update(encoded).digest('base64url'))
    const actual = Buffer.from(signature)
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) throw new Error(`${kind} 标识无效`)
    let payload: { v?: unknown; kind?: unknown; accountId?: unknown; groupId?: unknown; value?: unknown }
    try {
      payload = JSON.parse(Buffer.from(encoded, 'base64url').toString('utf8')) as typeof payload
    } catch {
      throw new Error(`${kind} 标识无效`)
    }
    if (
      payload.v !== 1 ||
      payload.kind !== kind ||
      payload.accountId !== accountId ||
      payload.groupId !== groupId ||
      typeof payload.value !== 'string'
    ) {
      throw new Error(`${kind} 标识与当前账号或群聊不匹配`)
    }
    this.assertOpaqueId(payload.value, `${kind} 标识无效`)
    return payload.value
  }

  private replaceCachedMember(state: AccountState, groupId: string, member: GroupMember): void {
    const cached = state.groupMembers.get(groupId)
    if (!cached) return
    cached.members = cached.members.map((candidate) => (candidate.userId === member.userId ? { ...member } : candidate))
  }

  private mapEssenceMessage(
    state: AccountState,
    groupId: string,
    item: OneBotEssenceItem,
    index: number,
  ): EssenceMessage {
    const messageId = String(item.message_id ?? item.msg_seq ?? `essence-${index}`)
    const senderId = String(item.sender_id ?? '')
    const mapped = mapMessage(
      state.account.id,
      state.selfId,
      {
        self_id: state.selfId,
        group_id: groupId,
        message_type: 'group',
        message_id: messageId,
        message_seq: item.msg_seq ?? messageId,
        user_id: senderId,
        sender: { user_id: senderId, nickname: item.sender_nick },
        time: Number(item.operator_time) || 0,
        message: item.content ?? [],
      },
      (url) => this.registerMedia(url),
    )
    return {
      id: `${state.account.id}:${groupId}:essence:${messageId}`,
      accountId: state.account.id,
      groupId,
      messageId,
      senderId,
      senderName: String(item.sender_nick ?? senderId),
      operatorId: String(item.operator_id ?? ''),
      operatorName: String(item.operator_nick ?? item.operator_id ?? ''),
      operatorTime: Number(item.operator_time) || 0,
      content: mapped?.content ?? '[无法解析的精华消息]',
      segments: mapped?.segments ?? [],
    }
  }

  private notificationId(account: string, kind: QqNotification['kind'], seed: string): string {
    return createHash('sha256').update(`${account}\0${kind}\0${seed}`).digest('hex').slice(0, 24)
  }

  private cacheNotification(state: AccountState, entry: CachedNotification, broadcast = true): void {
    const existing = state.notifications.get(entry.notification.id)
    if (existing) {
      const currentState = existing.notification.state
      const incomingState = entry.notification.state
      if (
        ((currentState === 'accepted' || currentState === 'rejected') &&
          incomingState !== 'accepted' && incomingState !== 'rejected') ||
        (currentState === 'handled' && incomingState === 'pending')
      ) {
        entry.notification.state = currentState
        entry.notification.actionable = false
      }
      if (!entry.notification.occurredAt && existing.notification.occurredAt) {
        entry.notification.occurredAt = existing.notification.occurredAt
      }
    }
    state.notifications.delete(entry.notification.id)
    state.notifications.set(entry.notification.id, entry)
    while (state.notifications.size > 500) {
      const oldest = state.notifications.keys().next().value as string | undefined
      if (!oldest) break
      state.notifications.delete(oldest)
    }
    if (broadcast) {
      this.broadcast({
        type: 'notification.changed',
        accountId: state.account.id,
        notification: { ...entry.notification },
      })
    }
  }

  private mergeGroupSystemNotifications(
    state: AccountState,
    invitations: OneBotGroupSystemItem[],
    requests: OneBotGroupSystemItem[],
  ): void {
    const add = (item: OneBotGroupSystemItem, kind: 'group-invitation' | 'group-request') => {
      const flag = String(item.request_id ?? '')
      const groupId = String(item.group_id ?? '')
      const userId = String(item.invitor_uin ?? '')
      if (!flag || !/^\d{5,20}$/.test(groupId) || !/^\d{1,20}$/.test(userId)) return
      this.cacheNotification(
        state,
        {
          flag,
          resolveKind: 'group',
          notification: {
            id: this.notificationId(state.account.id, kind, flag),
            accountId: state.account.id,
            kind,
            occurredAt: 0,
            userId,
            userName: String(item.requester_nick || item.invitor_nick || userId),
            groupId,
            groupName: String(item.group_name || groupId),
            comment: String(item.message || '').slice(0, 2_000),
            state: item.checked ? 'handled' : 'pending',
            actionable: kind === 'group-invitation' && !item.checked,
            actionReason:
              kind === 'group-request' && !item.checked
                ? '正在确认当前 QQ 的群管理权限'
                : undefined,
          },
        },
        false,
      )
    }
    invitations.forEach((item) => add(item, 'group-invitation'))
    requests.forEach((item) => add(item, 'group-request'))
  }

  private async refreshGroupRequestPermissions(state: AccountState, broadcast: boolean): Promise<void> {
    const requests = [...state.notifications.values()].filter(
      (entry) => entry.notification.kind === 'group-request' && entry.notification.state === 'pending',
    )
    for (let index = 0; index < requests.length; index += 4) {
      await Promise.allSettled(
        requests.slice(index, index + 4).map((entry) =>
          this.refreshGroupRequestPermission(
            state,
            entry.notification.id,
            entry.notification.groupId ?? '',
            broadcast,
          ),
        ),
      )
    }
  }

  private async refreshGroupRequestPermission(
    state: AccountState,
    notificationId: string,
    groupId: string,
    broadcast: boolean,
  ): Promise<void> {
    let allowed = false
    let reason = '无法确认当前 QQ 的群管理权限'
    try {
      const directory = await this.memberDirectory(state.account.id, groupId)
      allowed = directory.selfRole === 'owner' || directory.selfRole === 'admin'
      reason = allowed ? '' : '当前 QQ 不是该群的群主或管理员'
    } catch {
      // Keep the request visible but non-actionable when role lookup fails.
    }
    if (this.accounts.get(state.account.id) !== state) return
    const current = state.notifications.get(notificationId)
    if (!current || current.notification.kind !== 'group-request' || current.notification.state !== 'pending') return
    current.notification = {
      ...current.notification,
      actionable: allowed,
      actionReason: reason || undefined,
    }
    if (broadcast) {
      this.broadcast({
        type: 'notification.changed',
        accountId: state.account.id,
        notification: { ...current.notification },
      })
    }
  }

  private capabilityDocument(state: AccountState): AccountCapabilityDocument {
    const implemented = new Set<CapabilityName>([
      'history.cursor',
      'directory.friends',
      'directory.groups',
      'request.friend.resolve',
      'request.group.history',
      'request.group.resolve',
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
      ['message.custom_faces', '4.18.7'],
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
  ): { type: string; data: Record<string, string | number> } {
    switch (segment.type) {
      case 'text':
        return { type: 'text', data: { text: segment.text } }
      case 'mention':
        return { type: 'at', data: { qq: segment.all ? 'all' : segment.userId ?? '' } }
      case 'reply':
        return { type: 'reply', data: { id: segment.messageId ?? segment.messageSeq ?? '' } }
      case 'face':
        return { type: 'face', data: { id: segment.faceId } }
      case 'custom_face': {
        const favorite = this.resolveCustomFace(account, type, peerId, segment.handle)
        if (!favorite || !this.isCurrent(state)) throw new Error('收藏表情句柄已过期或与当前 QQ 会话不匹配')
        return { type: 'image', data: { file: favorite.url, sub_type: 1, summary: '[表情]' } }
      }
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

  private customFaceSourceAllowed(source: string): boolean {
    if (!source || source.length > 8_192) return false
    try {
      const url = new URL(source)
      return ['http:', 'https:'].includes(url.protocol) && this.mediaHostAllowed(url.hostname)
    } catch {
      return false
    }
  }

  private resolveCustomFace(
    account: string,
    type: 'group' | 'private',
    peerId: string,
    handle: string,
  ): CustomFaceEntry | undefined {
    this.pruneCustomFaces(Date.now())
    const entry = this.customFaces.get(handle)
    if (!entry || entry.accountId !== account || entry.type !== type || entry.peerId !== peerId) return undefined
    this.customFaces.delete(handle)
    this.customFaces.set(handle, entry)
    return entry
  }

  private pruneCustomFaces(now: number): void {
    for (const [handle, entry] of this.customFaces) {
      if (entry.expiresAt <= now) this.customFaces.delete(handle)
    }
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
