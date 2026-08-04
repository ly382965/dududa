import type {
  AccountCapabilityDocument,
  ChatMessage,
  Conversation,
  ConversationDraft,
  FileSendReceipt,
  ForwardedMessageBundle,
  HistoryPage,
  OutgoingMessageSegment,
  UploadReceipt,
  WorkspaceEvent,
  WorkspaceSnapshot,
} from '../types/workspace'
import {
  workspaceCache,
  type MessageSearchPage,
  type MessageSearchRequest,
  type WorkspaceCache,
} from './database'

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
  stageMedia(conversation: Conversation, file: File): Promise<UploadReceipt>
  sendFile(conversation: Conversation, file: File): Promise<FileSendReceipt>
  recallMessage(conversation: Conversation, message: ChatMessage): Promise<void>
  refreshMessage(conversation: Conversation, message: ChatMessage): Promise<ChatMessage>
  forwardMessage(message: ChatMessage, source: Conversation, target: Conversation): Promise<void>
  loadForwarded(conversation: Conversation, forwardId: string): Promise<ForwardedMessageBundle>
  loadFileUrl(conversation: Conversation, fileId: string, fileName?: string): Promise<string>
  nudge(conversation: Conversation, userId: string): Promise<void>
  loadDraft(conversation: Conversation): Promise<ConversationDraft | undefined>
  saveDraft(draft: ConversationDraft): Promise<void>
  searchMessages(request: MessageSearchRequest): Promise<MessageSearchPage>
  cacheMessages(conversation: Conversation, messages: ChatMessage[]): Promise<void>
  deleteCachedMessage(accountId: string, conversationId: string, messageId: string): Promise<void>
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

  async stageMedia(conversation: Conversation, file: File): Promise<UploadReceipt> {
    return this.upload<UploadReceipt>(conversation, file, 'media')
  }

  async sendFile(conversation: Conversation, file: File): Promise<FileSendReceipt> {
    return this.upload<FileSendReceipt>(conversation, file, 'file')
  }

  async recallMessage(conversation: Conversation, message: ChatMessage): Promise<void> {
    await this.request<{ ok: true }>(
      `${this.conversationPath(conversation)}/messages/${encodeURIComponent(message.messageId)}`,
      { method: 'DELETE' },
    )
    await this.cache.deleteMessage(conversation.accountId, conversation.id, message.id).catch(() => undefined)
  }

  async refreshMessage(conversation: Conversation, message: ChatMessage): Promise<ChatMessage> {
    const result = await this.request<SendMessageResponse>(
      `${this.conversationPath(conversation)}/messages/${encodeURIComponent(message.messageId)}`,
    )
    return result.message
  }

  async forwardMessage(message: ChatMessage, source: Conversation, target: Conversation): Promise<void> {
    await this.request<{ messageId?: string }>(
      `${this.conversationPath(source)}/messages/${encodeURIComponent(message.messageId)}/forward`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target: { accountId: target.accountId, type: target.type, peerId: target.peerId },
        }),
      },
    )
  }

  async loadForwarded(conversation: Conversation, forwardId: string): Promise<ForwardedMessageBundle> {
    return this.request<ForwardedMessageBundle>(
      `${this.conversationPath(conversation)}/forwards/${encodeURIComponent(forwardId)}`,
    )
  }

  async loadFileUrl(conversation: Conversation, fileId: string, fileName?: string): Promise<string> {
    const search = new URLSearchParams()
    if (fileName) search.set('name', fileName)
    const result = await this.request<{ url: string }>(
      `${this.conversationPath(conversation)}/files/${encodeURIComponent(fileId)}/url?${search.toString()}`,
    )
    return result.url
  }

  async nudge(conversation: Conversation, userId: string): Promise<void> {
    await this.request<{ ok: true }>(`${this.conversationPath(conversation)}/nudge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ userId }),
    })
  }

  async loadDraft(conversation: Conversation): Promise<ConversationDraft | undefined> {
    return this.cache.draft(conversation.accountId, conversation.id).catch(() => undefined)
  }

  async saveDraft(draft: ConversationDraft): Promise<void> {
    await this.cache.saveDraft(draft).catch(() => undefined)
  }

  async searchMessages(request: MessageSearchRequest): Promise<MessageSearchPage> {
    return this.cache.searchMessages(request).catch(() => ({ messages: [], hasMore: false }))
  }

  async cacheMessages(conversation: Conversation, messages: ChatMessage[]): Promise<void> {
    await this.cache.saveMessages(conversation, messages).catch(() => undefined)
  }

  async deleteCachedMessage(accountId: string, conversationId: string, messageId: string): Promise<void> {
    await this.cache.deleteMessage(accountId, conversationId, messageId).catch(() => undefined)
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

  private async upload<T>(conversation: Conversation, file: File, purpose: 'media' | 'file'): Promise<T> {
    const body = new FormData()
    body.append('file', file, file.name)
    return this.request<T>(`${this.conversationPath(conversation)}/uploads?purpose=${purpose}`, {
      method: 'POST',
      body,
    })
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
