import type {
  AccountCapabilityDocument,
  ChatMessage,
  Conversation,
  HistoryPage,
  OutgoingMessageSegment,
  WorkspaceEvent,
  WorkspaceSnapshot,
} from '../types/workspace'
import { workspaceCache, type WorkspaceCache } from './database'

export interface HistoryRequest {
  limit?: number
  before?: string
  after?: string
}

export interface WorkspaceAdapter {
  load(force?: boolean): Promise<WorkspaceSnapshot>
  loadCapabilities(accountId: string): Promise<AccountCapabilityDocument>
  loadCachedMessages(conversation: Conversation, limit?: number): Promise<ChatMessage[]>
  loadHistory(conversation: Conversation, request?: HistoryRequest): Promise<HistoryPage>
  loadMessages(conversation: Conversation, limit?: number): Promise<ChatMessage[]>
  sendSegments(conversation: Conversation, segments: OutgoingMessageSegment[]): Promise<ChatMessage>
  sendMessage(conversation: Conversation, content: string): Promise<ChatMessage>
  cacheMessages(conversation: Conversation, messages: ChatMessage[]): Promise<void>
  markRead(conversation: Conversation): Promise<void>
  subscribe(handler: (event: WorkspaceEvent) => void): () => void
}

interface SendMessageResponse {
  message: ChatMessage
}

export class NapCatWorkspaceAdapter implements WorkspaceAdapter {
  constructor(
    private readonly baseUrl = '',
    private readonly cache: WorkspaceCache = workspaceCache,
  ) {}

  async load(force = false): Promise<WorkspaceSnapshot> {
    const snapshot = await this.request<WorkspaceSnapshot>(`/api/workspace${force ? '?refresh=1' : ''}`)
    await Promise.allSettled(snapshot.conversations.map((conversation) => this.cache.saveConversation(conversation)))
    return snapshot
  }

  async loadCapabilities(accountId: string): Promise<AccountCapabilityDocument> {
    return this.request<AccountCapabilityDocument>(`/api/accounts/${encodeURIComponent(accountId)}/capabilities`)
  }

  async loadCachedMessages(conversation: Conversation, limit = 50): Promise<ChatMessage[]> {
    return this.cache.recentMessages(conversation.accountId, conversation.id, limit).catch(() => [])
  }

  async loadHistory(conversation: Conversation, request: HistoryRequest = {}): Promise<HistoryPage> {
    const search = new URLSearchParams()
    search.set('limit', String(Math.min(Math.max(request.limit ?? 50, 1), 100)))
    if (request.before) search.set('before', request.before)
    if (request.after) search.set('after', request.after)
    const page = await this.request<HistoryPage>(`${this.conversationPath(conversation)}/messages?${search.toString()}`)
    const direction = request.before ? 'before' : request.after ? 'after' : 'initial'
    await this.cache.saveHistoryPage(conversation, page, direction).catch(() => undefined)
    return page
  }

  async loadMessages(conversation: Conversation, limit = 50): Promise<ChatMessage[]> {
    return (await this.loadHistory(conversation, { limit })).messages
  }

  async sendSegments(conversation: Conversation, segments: OutgoingMessageSegment[]): Promise<ChatMessage> {
    const result = await this.request<SendMessageResponse>(`${this.conversationPath(conversation)}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ segments }),
    })
    return result.message
  }

  async sendMessage(conversation: Conversation, content: string): Promise<ChatMessage> {
    const result = await this.request<SendMessageResponse>(`${this.conversationPath(conversation)}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })
    return result.message
  }

  async cacheMessages(conversation: Conversation, messages: ChatMessage[]): Promise<void> {
    await this.cache.saveMessages(conversation, messages).catch(() => undefined)
  }

  async markRead(conversation: Conversation): Promise<void> {
    await this.request<{ ok: true }>(`${this.conversationPath(conversation)}/read`, { method: 'POST' })
  }

  subscribe(handler: (event: WorkspaceEvent) => void): () => void {
    if (typeof EventSource === 'undefined') return () => undefined
    const source = new EventSource(`${this.baseUrl}/api/events`)
    const onEvent = (event: MessageEvent<string>) => {
      try {
        handler(JSON.parse(event.data) as WorkspaceEvent)
      } catch {
        // Ignore malformed events; the next workspace refresh repairs state.
      }
    }
    source.addEventListener('workspace', onEvent as EventListener)
    return () => source.close()
  }

  private conversationPath(conversation: Conversation): string {
    return `/api/accounts/${encodeURIComponent(conversation.accountId)}/conversations/${conversation.type}/${encodeURIComponent(conversation.peerId)}`
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...init?.headers,
      },
    })
    const body = (await response.json().catch(() => ({}))) as { error?: string }
    if (!response.ok) throw new Error(body.error || `请求失败: ${response.status}`)
    return body as T
  }
}

export const workspaceAdapter: WorkspaceAdapter = new NapCatWorkspaceAdapter()
