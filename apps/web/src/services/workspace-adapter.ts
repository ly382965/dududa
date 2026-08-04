import type { ChatMessage, Conversation, WorkspaceEvent, WorkspaceSnapshot } from '../types/workspace'

export interface WorkspaceAdapter {
  load(force?: boolean): Promise<WorkspaceSnapshot>
  loadMessages(conversation: Conversation, limit?: number): Promise<ChatMessage[]>
  sendMessage(conversation: Conversation, content: string): Promise<ChatMessage>
  markRead(conversation: Conversation): Promise<void>
  subscribe(handler: (event: WorkspaceEvent) => void): () => void
}

interface MessageListResponse {
  messages: ChatMessage[]
}

interface SendMessageResponse {
  message: ChatMessage
}

export class NapCatWorkspaceAdapter implements WorkspaceAdapter {
  constructor(private readonly baseUrl = '') {}

  async load(force = false): Promise<WorkspaceSnapshot> {
    return this.request<WorkspaceSnapshot>(`/api/workspace${force ? '?refresh=1' : ''}`)
  }

  async loadMessages(conversation: Conversation, limit = 50): Promise<ChatMessage[]> {
    const path = this.conversationPath(conversation)
    const result = await this.request<MessageListResponse>(`${path}/messages?limit=${Math.min(Math.max(limit, 1), 100)}`)
    return result.messages
  }

  async sendMessage(conversation: Conversation, content: string): Promise<ChatMessage> {
    const result = await this.request<SendMessageResponse>(`${this.conversationPath(conversation)}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })
    return result.message
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
