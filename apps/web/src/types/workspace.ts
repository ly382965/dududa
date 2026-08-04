export type AccountStatus = 'online' | 'degraded' | 'offline'
export type ConversationType = 'group' | 'private'
export type AgentTab = 'conversation' | 'run' | 'settings'
export type MobilePanel = 'inbox' | 'chat' | 'agent'
export type ThemeMode = 'light' | 'dark'

export type CapabilityName =
  | 'history.cursor'
  | 'directory.friends'
  | 'directory.groups'
  | 'directory.peer_pin'
  | 'message.send.text'
  | 'message.send.mention'
  | 'message.send.reply'
  | 'message.send.face'
  | 'message.send.image'
  | 'message.send.audio'
  | 'message.send.video'
  | 'message.send.file'
  | 'message.download.file'
  | 'message.recall'
  | 'message.forward'
  | 'message.nudge'
  | 'message.read'
  | 'message.custom_faces'
  | 'request.friend.history'
  | 'request.group.history'
  | 'group.members'
  | 'group.admin'
  | 'group.kick'
  | 'group.card'
  | 'group.rename'
  | 'group.mute_all'
  | 'group.quit'
  | 'group.essence'
  | 'group.announcements'
  | 'group.files'
  | 'group.folder.rename'

export type CapabilityStatus = 'supported' | 'unsupported' | 'forbidden' | 'unavailable'

export interface AccountCapability {
  status: CapabilityStatus
  reason?: string
}

export interface AccountCapabilityDocument {
  accountId: string
  implementation: {
    name: string
    version?: string
    protocol: 'onebot-v11'
  }
  actions: Record<CapabilityName, AccountCapability>
}

export interface Account {
  id: string
  botId: string
  name: string
  shortName: string
  avatar: string
  status: AccountStatus
  unread: number
  role: 'bot' | 'operator'
  accent: 'cyan' | 'green' | 'coral'
  implementation?: AccountCapabilityDocument['implementation']
  capabilities?: AccountCapabilityDocument['actions']
}

export interface Conversation {
  id: string
  accountId: string
  type: ConversationType
  peerId: string
  name: string
  avatar: string
  lastMessage: string
  lastMessageAt: string
  unread: number
  pinned: boolean
  muted: boolean
  members?: number
  onlineMembers?: number
  topic?: string
  updatedAt?: number
}

export interface MessageReply {
  sender: string
  content: string
}

export interface MessageAttachment {
  kind: 'image' | 'audio' | 'video' | 'file'
  name?: string
  size?: string
  url?: string
}

export interface TextMessageSegment {
  type: 'text'
  text: string
}

export interface MentionMessageSegment {
  type: 'mention'
  userId?: string
  label: string
  all: boolean
}

export interface ReplyMessageSegment {
  type: 'reply'
  messageId?: string
  messageSeq?: string
  senderId?: string
  senderName?: string
  preview?: string
}

export interface FaceMessageSegment {
  type: 'face'
  faceId: string
  name?: string
  url?: string
  market: boolean
}

export interface MessageResource {
  resourceId?: string
  url?: string
  name?: string
  mime?: string
  size?: number
  width?: number
  height?: number
  duration?: number
}

export interface ImageMessageSegment extends MessageResource {
  type: 'image'
  summary?: string
  sticker: boolean
}

export interface AudioMessageSegment extends MessageResource {
  type: 'audio'
}

export interface VideoMessageSegment extends MessageResource {
  type: 'video'
  thumbnailUrl?: string
}

export interface FileMessageSegment extends MessageResource {
  type: 'file'
  fileId?: string
}

export interface StagedMediaMessageSegment {
  type: 'image' | 'audio' | 'video'
  uploadId: string
  name?: string
}

export interface ForwardMessageSegment {
  type: 'forward'
  forwardId: string
  count?: number
  preview?: string
  messages?: ChatMessage[]
}

export interface MarkdownMessageSegment {
  type: 'markdown'
  content: string
}

export interface LightAppMessageSegment {
  type: 'light_app'
  app?: string
  title?: string
  description?: string
  url?: string
}

export interface UnknownMessageSegment {
  type: 'unknown'
  segmentType: string
  summary: string
}

export type MessageSegment =
  | TextMessageSegment
  | MentionMessageSegment
  | ReplyMessageSegment
  | FaceMessageSegment
  | ImageMessageSegment
  | AudioMessageSegment
  | VideoMessageSegment
  | FileMessageSegment
  | ForwardMessageSegment
  | MarkdownMessageSegment
  | LightAppMessageSegment
  | UnknownMessageSegment

export type OutgoingMessageSegment =
  | TextMessageSegment
  | Pick<MentionMessageSegment, 'type' | 'userId' | 'label' | 'all'>
  | Pick<ReplyMessageSegment, 'type' | 'messageId' | 'messageSeq'>
  | Pick<FaceMessageSegment, 'type' | 'faceId' | 'name' | 'market'>
  | StagedMediaMessageSegment

export interface UploadReceipt {
  uploadId: string
  kind: 'image' | 'audio' | 'video'
  name: string
  mime: string
  size: number
  expiresAt: number
}

export interface FileSendReceipt {
  kind: 'file'
  fileId?: string
  name: string
  size: number
}

export interface ForwardedMessageBundle {
  forwardId: string
  messages: ChatMessage[]
}

export interface ChatMessage {
  id: string
  accountId: string
  conversationId: string
  messageId: string
  messageSeq?: string
  senderId: string
  senderName: string
  senderAvatar: string
  timestamp: string
  content: string
  segments: MessageSegment[]
  mine: boolean
  bot?: boolean
  role?: 'owner' | 'admin' | 'member'
  reply?: MessageReply
  attachments?: MessageAttachment[]
  reactions?: Array<{ emoji: string; count: number }>
  runId?: string
  status?: 'sent' | 'failed' | 'recalled'
  timestampMs?: number
  sequence?: string
}

export interface HistoryPage {
  messages: ChatMessage[]
  beforeCursor?: string
  afterCursor?: string
  hasMoreBefore: boolean
  hasMoreAfter: boolean
}

export interface ConversationDraft {
  accountId: string
  conversationId: string
  content: unknown
  updatedAt: number
}

export interface AgentSession {
  id: string
  conversationId: string
  title: string
  updatedAt: string
  status: 'idle' | 'running' | 'waiting_approval'
  agent: string
  model: string
}

export interface TextPart {
  type: 'text'
  text: string
}

export interface StatusPart {
  type: 'status'
  label: string
  tone: 'neutral' | 'success' | 'warning'
}

export interface ToolPart {
  type: 'tool'
  id: string
  name: string
  title: string
  status: 'running' | 'completed' | 'error'
  duration?: string
  input: string
  output?: string
}

export interface PermissionPart {
  type: 'permission'
  id: string
  title: string
  detail: string
  state: 'pending' | 'allowed' | 'denied'
}

export interface ReplyDraftPart {
  type: 'reply_draft'
  id: string
  accountId: string
  conversationId: string
  triggerMessageId?: string
  content: string
  status: 'draft' | 'sent' | 'discarded'
}

export type AgentPart = TextPart | StatusPart | ToolPart | PermissionPart | ReplyDraftPart

export interface AgentMessage {
  id: string
  sessionId: string
  role: 'operator' | 'assistant' | 'system'
  author: string
  timestamp: string
  parts: AgentPart[]
}

export interface AgentRunStep {
  id: string
  label: string
  detail: string
  status: 'completed' | 'running' | 'waiting'
  duration?: string
}

export interface AgentRun {
  id: string
  conversationId: string
  sessionId: string
  status: 'running' | 'waiting_approval' | 'completed'
  triggerSender: string
  triggerAvatar: string
  triggerContent: string
  startedAt: string
  duration: string
  tokens: string
  cost: string
  contextMessages: number
  model: string
  steps: AgentRunStep[]
}

export interface AgentConfig {
  enabled: boolean
  agent: string
  model: string
  reasoning: 'low' | 'medium' | 'high'
  trigger: 'mention' | 'keyword' | 'manual' | 'observe'
  contextMessages: number
  includeReplyChain: boolean
  includeImages: boolean
  longTermMemory: boolean
  tools: Record<'course' | 'web' | 'groupFiles' | 'shell', boolean>
  sendPermission: 'ask' | 'allow' | 'deny'
  toolPermission: 'ask' | 'allow' | 'deny'
}

export interface WorkspaceSnapshot {
  runtime: {
    status: 'connected' | 'waiting' | 'configuration_error'
    message: string
    reverseWebSocketPath: string
  }
  accounts: Account[]
  capabilities?: Record<string, AccountCapabilityDocument>
  conversations: Conversation[]
  messages: Record<string, ChatMessage[]>
  sessions: AgentSession[]
  agentMessages: Record<string, AgentMessage[]>
  runs: AgentRun[]
  configs: Record<string, AgentConfig>
}

export type WorkspaceEvent =
  | { type: 'workspace.refresh' }
  | { type: 'message.created'; conversation: Conversation; message: ChatMessage }
  | { type: 'message.deleted'; accountId: string; conversationId: string; messageId: string }
  | { type: 'capabilities.changed'; accountId: string; capabilities: AccountCapabilityDocument }
  | { type: 'runtime.status'; status: WorkspaceSnapshot['runtime'] }
