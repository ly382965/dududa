export type AccountStatus = 'online' | 'degraded' | 'offline'
export type ConversationType = 'group' | 'private'
export type AgentTab = 'conversation' | 'run' | 'settings'
export type MobilePanel = 'inbox' | 'chat' | 'agent'
export type ThemeMode = 'light' | 'dark'

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
  kind: 'image' | 'file'
  name?: string
  size?: string
  url?: string
}

export interface ChatMessage {
  id: string
  senderId: string
  senderName: string
  senderAvatar: string
  timestamp: string
  content: string
  mine: boolean
  bot?: boolean
  role?: 'owner' | 'admin' | 'member'
  reply?: MessageReply
  attachments?: MessageAttachment[]
  reactions?: Array<{ emoji: string; count: number }>
  runId?: string
  sequence?: string
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
  | { type: 'message.deleted'; conversationId: string; messageId: string }
  | { type: 'runtime.status'; status: WorkspaceSnapshot['runtime'] }
