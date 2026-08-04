import Dexie, { type EntityTable } from 'dexie'

import type { ChatMessage, Conversation, ConversationDraft, HistoryPage, MessageSegment } from '../types/workspace'

export interface StoredMessage {
  cacheId: string
  accountId: string
  conversationId: string
  timestampMs: number
  messageSeqNumber: number
  message: ChatMessage
}

export interface StoredConversation extends Conversation {
  cachedAt: number
}

export interface StoredHistoryRange {
  id: string
  accountId: string
  conversationId: string
  beforeCursor?: string
  afterCursor?: string
  hasMoreBefore: boolean
  hasMoreAfter: boolean
  updatedAt: number
}

export interface StoredConversationEvent {
  id: string
  accountId: string
  conversationId: string
  type: string
  timestampMs: number
  summary: string
}

export interface StoredDraft extends ConversationDraft {
  id: string
}

export interface MessageSearchRequest {
  accountId: string
  conversationId: string
  query?: string
  senderId?: string
  startTimeMs?: number
  endTimeMs?: number
  beforeTimestampMs?: number
  beforeCacheId?: string
  limit?: number
}

export interface MessageSearchPage {
  messages: ChatMessage[]
  hasMore: boolean
}

export class WorkspaceDatabase extends Dexie {
  messages!: EntityTable<StoredMessage, 'cacheId'>
  conversations!: EntityTable<StoredConversation, 'id'>
  historyRanges!: EntityTable<StoredHistoryRange, 'id'>
  conversationEvents!: EntityTable<StoredConversationEvent, 'id'>
  drafts!: EntityTable<StoredDraft, 'id'>

  constructor(name = 'dududa-workspace-v1') {
    super(name)
    this.version(1).stores({
      messages:
        '&cacheId, accountId, [accountId+conversationId+timestampMs], [accountId+conversationId+messageSeqNumber], [accountId+timestampMs]',
      conversations: '&id, accountId, [accountId+updatedAt], [accountId+cachedAt]',
      historyRanges: '&id, accountId, [accountId+conversationId], [accountId+updatedAt]',
      conversationEvents: '&id, accountId, [accountId+conversationId+timestampMs], [accountId+timestampMs]',
      drafts: '&id, accountId, [accountId+conversationId], [accountId+updatedAt]',
    })
  }
}

function persistentUrl(value: string | undefined): string | undefined {
  if (!value) return undefined
  if (/^(?:blob:|data:|base64:\/\/|file:)/i.test(value)) return undefined
  if (/^\/assets\//.test(value)) return value
  if (/^\/api\/media\//.test(value)) return undefined
  if (/^(?:[a-zA-Z]:[\\/]|\/[^/])/.test(value)) return undefined
  return value
}

function sanitizeSegment(segment: MessageSegment): MessageSegment {
  if (segment.type === 'face') return { ...segment, url: persistentUrl(segment.url) }
  if (segment.type === 'image' || segment.type === 'audio' || segment.type === 'file') {
    return { ...segment, url: persistentUrl(segment.url) }
  }
  if (segment.type === 'video') {
    return {
      ...segment,
      url: persistentUrl(segment.url),
      thumbnailUrl: persistentUrl(segment.thumbnailUrl),
    }
  }
  return { ...segment }
}

export function sanitizeMessageForStorage(message: ChatMessage): ChatMessage {
  return {
    ...message,
    segments: message.segments.map(sanitizeSegment),
    attachments: message.attachments?.map((attachment) => ({
      ...attachment,
      url: persistentUrl(attachment.url),
    })),
  }
}

function sanitizeDraftContent(content: unknown): unknown {
  const serialized = JSON.stringify(content, (_key, value: unknown) => {
    if (typeof Blob !== 'undefined' && value instanceof Blob) return undefined
    if (typeof value === 'string' && /^(?:blob:|data:|base64:\/\/|file:)/i.test(value)) return undefined
    return value
  })
  if (!serialized) return null
  if (serialized.length > 256 * 1024) throw new Error('草稿超过本地缓存上限')
  return JSON.parse(serialized) as unknown
}

function messageSeqNumber(message: ChatMessage): number {
  const value = Number(message.messageSeq)
  return Number.isSafeInteger(value) && value >= 0 ? value : 0
}

export class WorkspaceCache {
  constructor(readonly database = new WorkspaceDatabase()) {}

  async saveConversation(conversation: Conversation): Promise<void> {
    await this.database.conversations.put({ ...conversation, cachedAt: Date.now() })
  }

  async saveMessages(conversation: Conversation, input: ChatMessage[]): Promise<void> {
    const messages = this.storedMessages(conversation, input)
    await this.database.transaction('rw', this.database.messages, this.database.conversations, async () => {
      if (messages.length) await this.database.messages.bulkPut(messages)
      await this.pruneMessages(conversation.accountId, conversation.id)
      await this.database.conversations.put({ ...conversation, cachedAt: Date.now() })
    })
  }

  async saveHistoryPage(
    conversation: Conversation,
    page: HistoryPage,
    direction: 'initial' | 'before' | 'after' = 'initial',
  ): Promise<void> {
    const messages = this.storedMessages(conversation, page.messages)
    await this.database.transaction(
      'rw',
      this.database.messages,
      this.database.conversations,
      this.database.historyRanges,
      async () => {
        if (messages.length) await this.database.messages.bulkPut(messages)
        await this.pruneMessages(conversation.accountId, conversation.id)
        await this.database.conversations.put({ ...conversation, cachedAt: Date.now() })
        const existing = await this.database.historyRanges.get(conversation.id)
        await this.database.historyRanges.put({
          id: conversation.id,
          accountId: conversation.accountId,
          conversationId: conversation.id,
          beforeCursor:
            direction === 'after' ? existing?.beforeCursor ?? page.beforeCursor : page.beforeCursor ?? existing?.beforeCursor,
          afterCursor:
            direction === 'before' ? existing?.afterCursor ?? page.afterCursor : page.afterCursor ?? existing?.afterCursor,
          hasMoreBefore: direction === 'after' ? existing?.hasMoreBefore ?? page.hasMoreBefore : page.hasMoreBefore,
          hasMoreAfter: direction === 'before' ? existing?.hasMoreAfter ?? page.hasMoreAfter : page.hasMoreAfter,
          updatedAt: Date.now(),
        })
      },
    )
  }

  async recentMessages(accountId: string, conversationId: string, limit = 50): Promise<ChatMessage[]> {
    const bounded = Math.min(Math.max(Math.floor(limit), 1), 5_000)
    const rows = await this.database.messages
      .where('[accountId+conversationId+timestampMs]')
      .between([accountId, conversationId, Dexie.minKey], [accountId, conversationId, Dexie.maxKey])
      .reverse()
      .limit(bounded)
      .toArray()
    return rows.reverse().map((row) => row.message)
  }

  async historyRange(accountId: string, conversationId: string): Promise<StoredHistoryRange | undefined> {
    const range = await this.database.historyRanges.get(conversationId)
    return range?.accountId === accountId ? range : undefined
  }

  async searchMessages(request: MessageSearchRequest): Promise<MessageSearchPage> {
    const limit = Math.min(Math.max(Math.floor(request.limit ?? 50), 1), 100)
    const terms = (request.query ?? '')
      .trim()
      .toLocaleLowerCase('zh-CN')
      .split(/\s+/)
      .filter(Boolean)
    const lower = request.startTimeMs ?? Dexie.minKey
    const upper = Math.min(request.endTimeMs ?? Number.MAX_SAFE_INTEGER, request.beforeTimestampMs ?? Number.MAX_SAFE_INTEGER)
    const rows = await this.database.messages
      .where('[accountId+conversationId+timestampMs]')
      .between([request.accountId, request.conversationId, lower], [request.accountId, request.conversationId, upper], true, true)
      .reverse()
      .filter((row) => {
        if (request.beforeTimestampMs !== undefined) {
          if (row.timestampMs > request.beforeTimestampMs) return false
          if (row.timestampMs === request.beforeTimestampMs) {
            if (!request.beforeCacheId || row.cacheId >= request.beforeCacheId) return false
          }
        }
        if (request.senderId && row.message.senderId !== request.senderId) return false
        const haystack = `${row.message.senderName}\n${row.message.content}`.toLocaleLowerCase('zh-CN')
        return terms.every((term) => haystack.includes(term))
      })
      .limit(limit + 1)
      .toArray()
    return { messages: rows.slice(0, limit).map((row) => row.message), hasMore: rows.length > limit }
  }

  async deleteMessage(accountId: string, conversationId: string, messageId: string): Promise<void> {
    const stored = await this.database.messages.get(messageId)
    if (stored?.accountId === accountId && stored.conversationId === conversationId) {
      await this.database.messages.delete(messageId)
    }
  }

  async saveDraft(draft: ConversationDraft): Promise<void> {
    if (!draft.conversationId.startsWith(`${draft.accountId}:`)) throw new Error('草稿账号与会话不匹配')
    await this.database.drafts.put({
      ...draft,
      id: draft.conversationId,
      content: sanitizeDraftContent(draft.content),
    })
  }

  async draft(accountId: string, conversationId: string): Promise<ConversationDraft | undefined> {
    const draft = await this.database.drafts.get(conversationId)
    if (!draft || draft.accountId !== accountId) return undefined
    return {
      accountId: draft.accountId,
      conversationId: draft.conversationId,
      content: draft.content,
      updatedAt: draft.updatedAt,
    }
  }

  async clearAccount(accountId: string): Promise<void> {
    await this.database.transaction(
      'rw',
      this.database.messages,
      this.database.conversations,
      this.database.historyRanges,
      this.database.conversationEvents,
      this.database.drafts,
      async () => {
        await Promise.all([
          this.database.messages.where('accountId').equals(accountId).delete(),
          this.database.conversations.where('accountId').equals(accountId).delete(),
          this.database.historyRanges.where('accountId').equals(accountId).delete(),
          this.database.conversationEvents.where('accountId').equals(accountId).delete(),
          this.database.drafts.where('accountId').equals(accountId).delete(),
        ])
      },
    )
  }

  async clearAll(): Promise<void> {
    await this.database.delete()
  }

  private storedMessages(conversation: Conversation, input: ChatMessage[]): StoredMessage[] {
    return input
      .filter(
        (message) => message.accountId === conversation.accountId && message.conversationId === conversation.id,
      )
      .map((message) => ({
        cacheId: message.id,
        accountId: conversation.accountId,
        conversationId: conversation.id,
        timestampMs: message.timestampMs ?? 0,
        messageSeqNumber: messageSeqNumber(message),
        message: sanitizeMessageForStorage(message),
      }))
  }

  private async pruneMessages(accountId: string, conversationId: string): Promise<void> {
    const conversationRows = this.database.messages
      .where('[accountId+conversationId+timestampMs]')
      .between([accountId, conversationId, Dexie.minKey], [accountId, conversationId, Dexie.maxKey])
    const conversationExcess = Math.max(0, (await conversationRows.count()) - 5_000)
    if (conversationExcess) {
      const keys = (await conversationRows.limit(conversationExcess).primaryKeys()) as string[]
      await this.database.messages.bulkDelete(keys)
    }
    const accountRows = this.database.messages
      .where('[accountId+timestampMs]')
      .between([accountId, Dexie.minKey], [accountId, Dexie.maxKey])
    const accountExcess = Math.max(0, (await accountRows.count()) - 50_000)
    if (accountExcess) {
      const keys = (await accountRows.limit(accountExcess).primaryKeys()) as string[]
      await this.database.messages.bulkDelete(keys)
    }
  }
}

export const workspaceCache = new WorkspaceCache()
