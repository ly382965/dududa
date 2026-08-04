import type {
  Account,
  ChatMessage,
  Conversation,
  MessageAttachment,
  MessageSegment,
} from '../src/types/workspace'

export interface OneBotSegment {
  type: string
  data?: Record<string, unknown>
}

export interface OneBotSender {
  user_id?: number | string
  nickname?: string
  card?: string
  role?: string
}

export interface OneBotMessage {
  self_id?: number | string
  time?: number
  message_id?: number | string
  message_seq?: number | string
  real_seq?: number | string
  user_id?: number | string
  target_id?: number | string
  group_id?: number | string
  group_name?: string
  message_type?: string
  post_type?: string
  sender?: OneBotSender
  message?: OneBotSegment[] | string
  raw_message?: string
}

export interface OneBotGroup {
  group_id: number | string
  group_name: string
  group_remark?: string
  member_count?: number
  max_member_count?: number
}

export interface OneBotFriend {
  user_id: number | string
  nickname: string
  remark?: string
}

export interface OneBotRecentContact {
  lastestMsg?: OneBotMessage
  peerUin: string
  remark?: string
  msgTime?: string
  chatType: number
  msgId?: string
  sendNickName?: string
  sendMemberName?: string
  peerName?: string
}

export interface OneBotLoginInfo {
  user_id: number | string
  nickname: string
}

export type RegisterMedia = (url: string) => string | undefined

function text(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}

function boundedText(value: unknown, limit = 20_000): string {
  return text(value).slice(0, limit)
}

function positiveNumber(value: unknown): number | undefined {
  const candidate = Number(value)
  return Number.isFinite(candidate) && candidate > 0 ? candidate : undefined
}

function opaqueResourceId(value: unknown): string | undefined {
  const candidate = text(value)
  if (!candidate || candidate.length > 2_048 || /[\u0000-\u001f\u007f]/.test(candidate)) return undefined
  if (/^(?:file:|data:|blob:|base64:\/\/|[a-zA-Z]:[\\/]|[\\/])/i.test(candidate)) return undefined
  return candidate
}

function safeExternalUrl(value: unknown): string | undefined {
  const candidate = boundedText(value, 2_048)
  if (!candidate) return undefined
  try {
    const url = new URL(candidate)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : undefined
  } catch {
    return undefined
  }
}

function formatTime(timestamp: number): string {
  if (!Number.isFinite(timestamp) || timestamp <= 0) return ''
  const date = new Date(timestamp * 1000)
  const today = new Date()
  if (date.toDateString() === today.toDateString()) {
    return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
  }
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(date)
}

function safeRole(role: unknown): ChatMessage['role'] {
  return role === 'owner' || role === 'admin' || role === 'member' ? role : undefined
}

function parseLightApp(data: Record<string, unknown>): Extract<MessageSegment, { type: 'light_app' }> {
  let parsed: Record<string, unknown> = {}
  const serialized = text(data.data) || text(data.json)
  if (serialized.length <= 128 * 1024) {
    try {
      const value = JSON.parse(serialized) as unknown
      if (value && typeof value === 'object' && !Array.isArray(value)) parsed = value as Record<string, unknown>
    } catch {
      // The summary remains useful even when a third-party card is malformed.
    }
  }
  const meta = parsed.meta && typeof parsed.meta === 'object' ? (parsed.meta as Record<string, unknown>) : {}
  const detail = Object.values(meta).find(
    (value): value is Record<string, unknown> => Boolean(value && typeof value === 'object' && !Array.isArray(value)),
  )
  return {
    type: 'light_app',
    app: boundedText(parsed.app || data.app, 128) || undefined,
    title: boundedText(detail?.title || parsed.prompt || data.title, 512) || undefined,
    description: boundedText(detail?.desc || detail?.summary || data.summary, 2_000) || undefined,
    url: safeExternalUrl(detail?.jumpUrl || detail?.url || data.url),
  }
}

export function normalizeSegment(segment: OneBotSegment, registerMedia: RegisterMedia): MessageSegment {
  const data = segment.data ?? {}
  switch (segment.type) {
    case 'text':
      return { type: 'text', text: boundedText(data.text) }
    case 'at': {
      const qq = text(data.qq || data.user_id)
      const all = qq === 'all' || qq === '0'
      return {
        type: 'mention',
        userId: all ? undefined : qq || undefined,
        label: boundedText(data.name || data.text, 128) || (all ? '全体成员' : qq),
        all,
      }
    }
    case 'reply':
      return {
        type: 'reply',
        messageId: boundedText(data.id || data.message_id, 128) || undefined,
        messageSeq: boundedText(data.seq || data.message_seq, 128) || undefined,
        senderId: boundedText(data.qq || data.user_id, 24) || undefined,
        senderName: boundedText(data.name, 128) || undefined,
        preview: boundedText(data.text || data.preview, 1_000) || undefined,
      }
    case 'face':
    case 'mface': {
      const source = text(data.url)
      return {
        type: 'face',
        faceId: boundedText(data.id || data.face_id || data.emoji_id, 128) || 'unknown',
        name: boundedText(data.summary || data.name, 128) || undefined,
        url: source ? registerMedia(source) : undefined,
        market: segment.type === 'mface',
      }
    }
    case 'image': {
      const source = text(data.url) || text(data.file)
      return {
        type: 'image',
        resourceId: opaqueResourceId(data.resource_id || data.file_id),
        url: source ? registerMedia(source) : undefined,
        name: boundedText(data.name, 256) || undefined,
        mime: boundedText(data.mime || data.content_type, 128) || undefined,
        size: positiveNumber(data.file_size || data.size),
        width: positiveNumber(data.width),
        height: positiveNumber(data.height),
        summary: boundedText(data.summary, 256) || undefined,
        sticker: Boolean(data.sub_type === 1 || data.type === 'flash' || data.is_emoji),
      }
    }
    case 'record': {
      const source = text(data.url) || text(data.file)
      return {
        type: 'audio',
        resourceId: opaqueResourceId(data.resource_id || data.file_id),
        url: source ? registerMedia(source) : undefined,
        name: boundedText(data.name, 256) || undefined,
        mime: boundedText(data.mime || data.content_type, 128) || undefined,
        size: positiveNumber(data.file_size || data.size),
        duration: positiveNumber(data.duration),
      }
    }
    case 'video': {
      const source = text(data.url) || text(data.file)
      const thumbnail = text(data.thumb || data.thumbnail)
      return {
        type: 'video',
        resourceId: opaqueResourceId(data.resource_id || data.file_id),
        url: source ? registerMedia(source) : undefined,
        thumbnailUrl: thumbnail ? registerMedia(thumbnail) : undefined,
        name: boundedText(data.name, 256) || undefined,
        mime: boundedText(data.mime || data.content_type, 128) || undefined,
        size: positiveNumber(data.file_size || data.size),
        duration: positiveNumber(data.duration),
        width: positiveNumber(data.width),
        height: positiveNumber(data.height),
      }
    }
    case 'file':
    case 'onlinefile': {
      const source = text(data.url)
      return {
        type: 'file',
        fileId: opaqueResourceId(data.file_id || data.id),
        resourceId: opaqueResourceId(data.resource_id),
        url: source ? registerMedia(source) : undefined,
        name: boundedText(data.name || data.file_name, 512) || '文件',
        mime: boundedText(data.mime || data.content_type, 128) || undefined,
        size: positiveNumber(data.file_size || data.size),
      }
    }
    case 'forward':
    case 'node':
      return {
        type: 'forward',
        forwardId: boundedText(data.id || data.forward_id || data.resid, 512) || 'unknown',
        count: positiveNumber(data.count),
        preview: boundedText(data.summary || data.preview, 1_000) || undefined,
      }
    case 'markdown':
      return { type: 'markdown', content: boundedText(data.content || data.data, 64 * 1024) }
    case 'json':
    case 'xml':
    case 'miniapp':
    case 'light_app':
      return parseLightApp(data)
    default:
      return {
        type: 'unknown',
        segmentType: boundedText(segment.type, 128) || 'unknown',
        summary: `[不支持的消息: ${boundedText(segment.type, 128) || 'unknown'}]`,
      }
  }
}

export function normalizeSegments(segments: OneBotSegment[], registerMedia: RegisterMedia): MessageSegment[] {
  return segments.slice(0, 1_000).map((segment) => normalizeSegment(segment, registerMedia))
}

function normalizedSegmentPreview(segment: MessageSegment): string {
  switch (segment.type) {
    case 'text':
      return segment.text
    case 'mention':
      return `@${segment.label || segment.userId || '成员'}`
    case 'reply':
      return ''
    case 'face':
      return segment.name || '[表情]'
    case 'image':
      return segment.summary || '[图片]'
    case 'audio':
      return '[语音]'
    case 'video':
      return '[视频]'
    case 'file':
      return `[文件] ${segment.name || ''}`.trim()
    case 'forward':
      return '[转发消息]'
    case 'markdown':
      return segment.content
    case 'light_app':
      return segment.title || segment.description || '[卡片消息]'
    case 'unknown':
      return segment.summary
  }
}

export function messagePreview(message: OneBotMessage | undefined): string {
  if (!message) return ''
  if (Array.isArray(message.message)) {
    return normalizeSegments(message.message, () => undefined)
      .map(normalizedSegmentPreview)
      .join('')
      .replace(/\s+/g, ' ')
      .trim()
  }
  return text(message.message) || text(message.raw_message)
}

function segmentAttachments(segments: MessageSegment[]): MessageAttachment[] {
  const attachments: MessageAttachment[] = []
  for (const segment of segments) {
    if (segment.type === 'image' || segment.type === 'audio' || segment.type === 'video' || segment.type === 'file') {
      attachments.push({
        kind: segment.type,
        name: segment.name || (segment.type === 'file' ? '文件' : undefined),
        size: segment.size ? formatBytes(segment.size) : undefined,
        url: segment.url,
      })
    }
  }
  return attachments
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 102.4) / 10} KB`
  return `${Math.round(bytes / 1024 / 102.4) / 10} MB`
}

export function accountId(selfId: string): string {
  return `qq-${selfId}`
}

export function conversationId(account: string, type: 'group' | 'private', peerId: string): string {
  return `${account}:${type}:${peerId}`
}

export function userAvatar(userId: string): string {
  return `/api/media/avatar/user/${encodeURIComponent(userId)}`
}

export function groupAvatar(groupId: string): string {
  return `/api/media/avatar/group/${encodeURIComponent(groupId)}`
}

export function mapAccount(login: OneBotLoginInfo, status: Account['status'] = 'online'): Account {
  const selfId = String(login.user_id)
  return {
    id: accountId(selfId),
    botId: selfId,
    name: login.nickname || selfId,
    shortName: login.nickname || selfId,
    avatar: userAvatar(selfId),
    status,
    unread: 0,
    role: 'bot',
    accent: 'cyan',
  }
}

export function mapGroupConversation(account: string, group: OneBotGroup): Conversation {
  const peerId = String(group.group_id)
  return {
    id: conversationId(account, 'group', peerId),
    accountId: account,
    type: 'group',
    peerId,
    name: group.group_remark || group.group_name || peerId,
    avatar: groupAvatar(peerId),
    lastMessage: '',
    lastMessageAt: '',
    unread: 0,
    pinned: false,
    muted: false,
    members: group.member_count,
    topic: group.group_name,
    updatedAt: 0,
  }
}

export function mapFriendConversation(account: string, friend: OneBotFriend): Conversation {
  const peerId = String(friend.user_id)
  return {
    id: conversationId(account, 'private', peerId),
    accountId: account,
    type: 'private',
    peerId,
    name: friend.remark || friend.nickname || peerId,
    avatar: userAvatar(peerId),
    lastMessage: '',
    lastMessageAt: '',
    unread: 0,
    pinned: false,
    muted: false,
    topic: '私聊',
    updatedAt: 0,
  }
}

export function recentConversationType(chatType: number): 'group' | 'private' | undefined {
  if (chatType === 2) return 'group'
  if (chatType === 1) return 'private'
  return undefined
}

export function applyRecentContact(
  conversation: Conversation,
  recent: OneBotRecentContact,
): Conversation {
  const timestamp = Number(recent.msgTime || recent.lastestMsg?.time || 0)
  const sender = recent.sendMemberName || recent.sendNickName
  const preview = messagePreview(recent.lastestMsg)
  return {
    ...conversation,
    name: recent.remark || recent.peerName || conversation.name,
    lastMessage: sender && conversation.type === 'group' ? `${sender}：${preview}` : preview,
    lastMessageAt: formatTime(timestamp),
    updatedAt: timestamp,
  }
}

export function mapMessage(
  account: string,
  selfId: string,
  raw: OneBotMessage,
  registerMedia: RegisterMedia,
  privatePeerId?: string,
): ChatMessage | undefined {
  if (raw.self_id !== undefined && text(raw.self_id) !== selfId) return undefined
  const messageType = raw.message_type === 'group' ? 'group' : raw.message_type === 'private' ? 'private' : undefined
  if (!messageType) return undefined
  const senderId = text(raw.sender?.user_id || raw.user_id)
  const peerId =
    messageType === 'group'
      ? text(raw.group_id)
      : privatePeerId || (senderId === selfId ? text(raw.target_id) || senderId : senderId)
  if (!peerId || !senderId) return undefined
  const segments = Array.isArray(raw.message) ? raw.message : []
  const messageId = text(raw.message_id) || text(raw.message_seq || raw.real_seq) || `${raw.time ?? Date.now()}-${senderId}`
  const messageSeq = text(raw.message_seq || raw.real_seq) || undefined
  const senderName = text(raw.sender?.card) || text(raw.sender?.nickname) || senderId
  const normalizedSegments = Array.isArray(raw.message)
    ? normalizeSegments(segments, registerMedia)
    : [{ type: 'text' as const, text: boundedText(raw.message || raw.raw_message) }]
  const content = normalizedSegments.map(normalizedSegmentPreview).join('').replace(/\s+/g, ' ').trim() || '[空消息]'
  const replySegment = normalizedSegments.find(
    (segment): segment is Extract<MessageSegment, { type: 'reply' }> => segment.type === 'reply',
  )
  const conversation = conversationId(account, messageType, peerId)
  const timestampSeconds = Number(raw.time ?? 0)
  return {
    id: `${conversation}:${messageId}`,
    accountId: account,
    conversationId: conversation,
    messageId,
    messageSeq,
    senderId,
    senderName,
    senderAvatar: userAvatar(senderId),
    timestamp: formatTime(Number(raw.time ?? 0)),
    content,
    segments: normalizedSegments,
    mine: senderId === selfId,
    bot: senderId === selfId,
    role: safeRole(raw.sender?.role),
    reply: replySegment
      ? { sender: replySegment.senderName || '引用消息', content: replySegment.preview || '查看被引用的消息' }
      : undefined,
    attachments: segmentAttachments(normalizedSegments),
    status: 'sent',
    timestampMs: Number.isFinite(timestampSeconds) && timestampSeconds > 0 ? timestampSeconds * 1_000 : undefined,
    sequence: messageSeq,
  }
}

export function eventConversation(
  account: string,
  selfId: string,
  raw: OneBotMessage,
  known?: Conversation,
  privatePeerId?: string,
): Conversation | undefined {
  const type = raw.message_type === 'group' ? 'group' : raw.message_type === 'private' ? 'private' : undefined
  if (!type) return undefined
  const senderId = text(raw.sender?.user_id || raw.user_id)
  const peerId =
    type === 'group' ? text(raw.group_id) : privatePeerId || (senderId === selfId ? text(raw.target_id) || senderId : senderId)
  if (!peerId) return undefined
  const timestamp = Number(raw.time ?? 0)
  const senderName = text(raw.sender?.card) || text(raw.sender?.nickname)
  const preview = messagePreview(raw)
  const base: Conversation =
    known ??
    (type === 'group'
      ? mapGroupConversation(account, { group_id: peerId, group_name: text(raw.group_name) || peerId })
      : mapFriendConversation(account, { user_id: peerId, nickname: senderName || peerId }))
  return {
    ...base,
    lastMessage: type === 'group' && senderName ? `${senderName}：${preview}` : preview,
    lastMessageAt: formatTime(timestamp),
    updatedAt: timestamp,
  }
}
