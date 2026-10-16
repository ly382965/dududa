import type { ChatMessage, Conversation, RecallArchivePage, RecallSettings, WorkspaceEvent } from '../types/workspace'

type RecallUpdate = Extract<WorkspaceEvent, { type: 'message.deleted' | 'recall.settings.changed' }>
const listeners = new Set<(update: RecallUpdate) => void>()

export function subscribeRecallUpdates(listener: (update: RecallUpdate) => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function publishRecallUpdate(update: RecallUpdate): void {
  listeners.forEach((listener) => listener(update))
}

export function hasRetainedOriginal(message: ChatMessage, now = Date.now()): boolean {
  return message.status === 'recalled' && message.recall?.retained === true &&
    typeof message.recall.expiresAt === 'number' && message.recall.expiresAt > now
}

export function withoutRecalledOriginal(message: ChatMessage): ChatMessage {
  return {
    ...message,
    status: 'recalled',
    content: '此消息已撤回',
    segments: [],
    attachments: undefined,
    reply: undefined,
    recall: message.recall ? { ...message.recall, retained: false } : undefined,
  }
}

export function expireRecalledOriginal(message: ChatMessage, now = Date.now()): ChatMessage {
  return message.status === 'recalled' && !hasRetainedOriginal(message, now) ? withoutRecalledOriginal(message) : message
}

function conversationPath(conversation: Conversation): string {
  return `/api/accounts/${encodeURIComponent(conversation.accountId)}/conversations/${conversation.type}/${encodeURIComponent(conversation.peerId)}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { Accept: 'application/json', ...init?.headers } })
  const body = await response.json() as { error?: string }
  if (!response.ok) throw new Error(body.error || `请求失败: ${response.status}`)
  return body as T
}

export const recallService = {
  load(conversation: Conversation, before?: string): Promise<RecallArchivePage> {
    const search = new URLSearchParams({ limit: '50' })
    if (before) search.set('before', before)
    return request(`${conversationPath(conversation)}/recalls?${search}`)
  },
  async saveSettings(conversation: Conversation, settings: RecallSettings): Promise<RecallSettings> {
    const saved = await request<RecallSettings>(`${conversationPath(conversation)}/recall-settings`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settings),
    })
    publishRecallUpdate({ type: 'recall.settings.changed', accountId: conversation.accountId, conversationId: conversation.id, settings: saved })
    return saved
  },
}
