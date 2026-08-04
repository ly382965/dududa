import type { Account, ChatMessage, Conversation, MessageAttachment } from '../src/types/workspace'

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

function segmentPreview(segment: OneBotSegment): string {
  const data = segment.data ?? {}
  switch (segment.type) {
    case 'text':
      return text(data.text)
    case 'at':
      return `@${text(data.name) || text(data.qq)}`
    case 'image':
      return text(data.summary) || '[图片]'
    case 'record':
      return '[语音]'
    case 'video':
      return '[视频]'
    case 'file':
    case 'onlinefile':
      return `[文件] ${text(data.name)}`.trim()
    case 'reply':
      return ''
    case 'face':
    case 'mface':
      return text(data.summary) || '[表情]'
    case 'forward':
    case 'node':
      return '[转发消息]'
    case 'json':
    case 'xml':
    case 'miniapp':
      return '[卡片消息]'
    default:
      return `[${segment.type}]`
  }
}

export function messagePreview(message: OneBotMessage | undefined): string {
  if (!message) return ''
  if (Array.isArray(message.message)) {
    return message.message.map(segmentPreview).join('').replace(/\s+/g, ' ').trim()
  }
  return text(message.message) || text(message.raw_message)
}

function segmentAttachments(segments: OneBotSegment[], registerMedia: RegisterMedia): MessageAttachment[] {
  const attachments: MessageAttachment[] = []
  for (const segment of segments) {
    const data = segment.data ?? {}
    if (segment.type === 'image') {
      const source = text(data.url) || text(data.file)
      const url = registerMedia(source)
      if (url) attachments.push({ kind: 'image', url, name: text(data.summary) || undefined })
      continue
    }
    if (segment.type === 'file' || segment.type === 'onlinefile') {
      const size = Number(data.file_size ?? data.size)
      attachments.push({
        kind: 'file',
        name: text(data.name) || text(data.file) || '文件',
        size: Number.isFinite(size) && size > 0 ? formatBytes(size) : undefined,
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
  const messageType = raw.message_type === 'group' ? 'group' : raw.message_type === 'private' ? 'private' : undefined
  if (!messageType) return undefined
  const senderId = text(raw.sender?.user_id || raw.user_id)
  const peerId =
    messageType === 'group'
      ? text(raw.group_id)
      : privatePeerId || (senderId === selfId ? text(raw.target_id) || senderId : senderId)
  if (!peerId || !senderId) return undefined
  const segments = Array.isArray(raw.message) ? raw.message : []
  const messageId = text(raw.message_id) || `${raw.time ?? Date.now()}-${senderId}`
  const senderName = text(raw.sender?.card) || text(raw.sender?.nickname) || senderId
  const content = messagePreview(raw) || '[空消息]'
  const replySegment = segments.find((segment) => segment.type === 'reply')
  return {
    id: `${account}:${messageType}:${peerId}:${messageId}`,
    senderId,
    senderName,
    senderAvatar: userAvatar(senderId),
    timestamp: formatTime(Number(raw.time ?? 0)),
    content,
    mine: senderId === selfId,
    bot: senderId === selfId,
    role: safeRole(raw.sender?.role),
    reply: replySegment ? { sender: '引用消息', content: '查看被引用的消息' } : undefined,
    attachments: segmentAttachments(segments, registerMedia),
    sequence: text(raw.message_seq || raw.real_seq) || undefined,
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
