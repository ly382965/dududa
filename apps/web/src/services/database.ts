import Dexie, { type EntityTable } from 'dexie'

import type {
  ChatMessage,
  Conversation,
  ConversationDraft,
  HistoryPage,
  MessageSegment,
  QqNotification,
} from '../types/workspace'
import { createSearchMatcher } from './search'

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

export interface StoredNotification {
  cacheId: string
  accountId: string
  occurredAtMs: number
  observedAtMs: number
  sortAtMs: number
  notification: QqNotification
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

export interface CacheStatistics {
  accountId?: string
  conversationId?: string
  conversationCount: number
  messageCount: number
  eventCount: number
  notificationCount: number
  draftCount: number
  firstTimestampMs?: number
  lastTimestampMs?: number
  estimatedUsage: number
  estimatedQuota: number
}

export interface CacheWriteReceipt {
  requestedMessageCount: number
  persistedMessageCount: number
  coverageRetained: boolean
}

export interface CacheWriteGeneration {
  global: number
  account: number
}

export interface WorkspaceCacheOptions {
  maxMessagesPerConversation?: number
  maxMessagesPerAccount?: number
}

export class WorkspaceDatabase extends Dexie {
  messages!: EntityTable<StoredMessage, 'cacheId'>
  conversations!: EntityTable<StoredConversation, 'id'>
  historyRanges!: EntityTable<StoredHistoryRange, 'id'>
  conversationEvents!: EntityTable<StoredConversationEvent, 'id'>
  drafts!: EntityTable<StoredDraft, 'id'>
  notifications!: EntityTable<StoredNotification, 'cacheId'>

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
    this.version(2).stores({
      notifications: '&cacheId, accountId, [accountId+occurredAtMs]',
    })
    this.version(3).stores({
      notifications: '&cacheId, accountId, [accountId+sortAtMs], [accountId+occurredAtMs]',
    })
  }
}

function assertConversationScope(accountId: string, conversationId: string): void {
  if (!conversationId.startsWith(`${accountId}:`)) throw new Error('缓存范围不属于当前 QQ 账号')
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
  private readonly maxMessagesPerConversation: number
  private readonly maxMessagesPerAccount: number
  private globalGeneration = 0
  private readonly accountGenerations = new Map<string, number>()

  constructor(
    readonly database = new WorkspaceDatabase(),
    options: WorkspaceCacheOptions = {},
  ) {
    this.maxMessagesPerConversation = Math.max(1, Math.floor(options.maxMessagesPerConversation ?? 20_000))
    this.maxMessagesPerAccount = Math.max(
      this.maxMessagesPerConversation,
      Math.floor(options.maxMessagesPerAccount ?? 100_000),
    )
  }

  async saveConversation(conversation: Conversation): Promise<void> {
    assertConversationScope(conversation.accountId, conversation.id)
    await this.database.conversations.put({ ...conversation, cachedAt: Date.now() })
  }

  async saveMessages(conversation: Conversation, input: ChatMessage[]): Promise<void> {
    assertConversationScope(conversation.accountId, conversation.id)
    const messages = this.storedMessages(conversation, input)
    await this.database.transaction('rw', this.database.messages, this.database.conversations, this.database.historyRanges, async () => {
      if (messages.length) await this.database.messages.bulkPut(messages)
      await this.pruneMessages(conversation.accountId, conversation.id)
      await this.database.conversations.put({ ...conversation, cachedAt: Date.now() })
    })
  }

  async saveHistoryPage(
    conversation: Conversation,
    page: HistoryPage,
    direction: 'initial' | 'before' | 'after' = 'initial',
    generation?: CacheWriteGeneration,
  ): Promise<CacheWriteReceipt> {
    assertConversationScope(conversation.accountId, conversation.id)
    const messages = this.storedMessages(conversation, page.messages)
    const skipped = (): CacheWriteReceipt => ({
      requestedMessageCount: messages.length,
      persistedMessageCount: 0,
      coverageRetained: false,
    })
    if (generation && !this.writeGenerationCurrent(conversation.accountId, generation)) return skipped()
    return this.database.transaction(
      'rw',
      this.database.messages,
      this.database.conversations,
      this.database.historyRanges,
      async () => {
        if (generation && !this.writeGenerationCurrent(conversation.accountId, generation)) return skipped()
        if (messages.length) await this.database.messages.bulkPut(messages)
        const prunedConversations = await this.pruneMessages(conversation.accountId, conversation.id)
        await this.database.conversations.put({ ...conversation, cachedAt: Date.now() })
        if (!prunedConversations.has(conversation.id)) {
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
        }
        const persistedMessageCount = (await this.database.messages.bulkGet(messages.map((message) => message.cacheId)))
          .filter(Boolean).length
        return {
          requestedMessageCount: messages.length,
          persistedMessageCount,
          coverageRetained: !prunedConversations.has(conversation.id),
        }
      },
    )
  }

  async recentMessages(accountId: string, conversationId: string, limit = 50): Promise<ChatMessage[]> {
    assertConversationScope(accountId, conversationId)
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
    assertConversationScope(accountId, conversationId)
    const range = await this.database.historyRanges.get(conversationId)
    return range?.accountId === accountId ? range : undefined
  }

  async searchMessages(request: MessageSearchRequest): Promise<MessageSearchPage> {
    assertConversationScope(request.accountId, request.conversationId)
    const limit = Math.min(Math.max(Math.floor(request.limit ?? 50), 1), 100)
    const matchesQuery = createSearchMatcher(request.query ?? '')
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
        return matchesQuery(`${row.message.senderName}\n${row.message.content}`)
      })
      .limit(limit + 1)
      .toArray()
    return { messages: rows.slice(0, limit).map((row) => row.message), hasMore: rows.length > limit }
  }

  async deleteMessage(accountId: string, conversationId: string, messageId: string): Promise<void> {
    assertConversationScope(accountId, conversationId)
    const stored = await this.database.messages.get(messageId)
    if (stored?.accountId === accountId && stored.conversationId === conversationId) {
      await this.database.messages.delete(messageId)
    }
  }

  async saveDraft(draft: ConversationDraft): Promise<void> {
    try {
      assertConversationScope(draft.accountId, draft.conversationId)
    } catch {
      throw new Error('草稿账号与会话不匹配')
    }
    await this.database.drafts.put({
      ...draft,
      id: draft.conversationId,
      content: sanitizeDraftContent(draft.content),
    })
  }

  async draft(accountId: string, conversationId: string): Promise<ConversationDraft | undefined> {
    assertConversationScope(accountId, conversationId)
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
    this.accountGenerations.set(accountId, (this.accountGenerations.get(accountId) ?? 0) + 1)
    await this.database.transaction(
      'rw',
      [
        this.database.messages,
        this.database.conversations,
        this.database.historyRanges,
        this.database.conversationEvents,
        this.database.drafts,
        this.database.notifications,
      ],
      async () => {
        await Promise.all([
          this.database.messages.where('accountId').equals(accountId).delete(),
          this.database.conversations.where('accountId').equals(accountId).delete(),
          this.database.historyRanges.where('accountId').equals(accountId).delete(),
          this.database.conversationEvents.where('accountId').equals(accountId).delete(),
          this.database.drafts.where('accountId').equals(accountId).delete(),
          this.database.notifications.where('accountId').equals(accountId).delete(),
        ])
      },
    )
  }

  async clearBefore(accountId: string, beforeTimestampMs: number, conversationId?: string): Promise<number> {
    if (!Number.isFinite(beforeTimestampMs) || beforeTimestampMs <= 0) throw new Error('缓存清理日期无效')
    if (conversationId) {
      assertConversationScope(accountId, conversationId)
      const [conversation, range] = await Promise.all([
        this.database.conversations.get(conversationId),
        this.database.historyRanges.get(conversationId),
      ])
      if (conversation?.accountId !== accountId || (range && range.accountId !== accountId)) {
        throw new Error('缓存范围不属于当前 QQ 账号')
      }
    }
    this.accountGenerations.set(accountId, (this.accountGenerations.get(accountId) ?? 0) + 1)
    const messages = conversationId
      ? this.database.messages
          .where('[accountId+conversationId+timestampMs]')
          .between([accountId, conversationId, Dexie.minKey], [accountId, conversationId, beforeTimestampMs], true, false)
      : this.database.messages
          .where('[accountId+timestampMs]')
          .between([accountId, Dexie.minKey], [accountId, beforeTimestampMs], true, false)
    const events = conversationId
      ? this.database.conversationEvents
          .where('[accountId+conversationId+timestampMs]')
          .between([accountId, conversationId, Dexie.minKey], [accountId, conversationId, beforeTimestampMs], true, false)
      : this.database.conversationEvents
          .where('[accountId+timestampMs]')
          .between([accountId, Dexie.minKey], [accountId, beforeTimestampMs], true, false)
    const [messageKeys, eventKeys] = await Promise.all([messages.primaryKeys(), events.primaryKeys()])
    const notificationKeys = conversationId
      ? []
      : ((await this.database.notifications
          .where('[accountId+occurredAtMs]')
          .between([accountId, 1], [accountId, beforeTimestampMs], true, false)
          .primaryKeys()) as string[])
    await this.database.transaction(
      'rw',
      this.database.messages,
      this.database.conversationEvents,
      this.database.historyRanges,
      this.database.notifications,
      async () => {
        await this.database.messages.bulkDelete(messageKeys as string[])
        await this.database.conversationEvents.bulkDelete(eventKeys as string[])
        await this.database.notifications.bulkDelete(notificationKeys)
        if (conversationId) await this.database.historyRanges.delete(conversationId)
        else await this.database.historyRanges.where('accountId').equals(accountId).delete()
      },
    )
    return messageKeys.length + eventKeys.length + notificationKeys.length
  }

  async saveNotifications(accountId: string, input: QqNotification[]): Promise<void> {
    if (input.some((notification) => notification.accountId !== accountId)) {
      throw new Error('通知缓存账号不匹配')
    }
    await this.database.transaction('rw', this.database.notifications, async () => {
      const observedAtMs = Date.now()
      const rows = await Promise.all(
        input
          .filter((notification) => notification.accountId === accountId)
          .map(async (notification) => {
            const cacheId = `${accountId}:${notification.id}`
            const existing = await this.database.notifications.get(cacheId)
            const occurredAtMs = Number.isFinite(notification.occurredAt) && notification.occurredAt > 0
              ? notification.occurredAt
              : 0
            const firstObservedAtMs = existing?.observedAtMs || observedAtMs
            return {
              cacheId,
              accountId,
              occurredAtMs,
              observedAtMs: firstObservedAtMs,
              sortAtMs: occurredAtMs || existing?.sortAtMs || firstObservedAtMs,
              notification: { ...notification },
            }
          }),
      )
      if (rows.length) await this.database.notifications.bulkPut(rows)
      const accountRows = this.database.notifications
        .where('[accountId+sortAtMs]')
        .between([accountId, Dexie.minKey], [accountId, Dexie.maxKey])
      const excess = Math.max(0, (await accountRows.count()) - 500)
      if (excess) {
        const keys = (await accountRows.limit(excess).primaryKeys()) as string[]
        await this.database.notifications.bulkDelete(keys)
      }
    })
  }

  async cachedNotifications(accountId: string, limit = 500): Promise<QqNotification[]> {
    const bounded = Math.min(Math.max(Math.floor(limit), 1), 500)
    const rows = await this.database.notifications
      .where('[accountId+sortAtMs]')
      .between([accountId, Dexie.minKey], [accountId, Dexie.maxKey])
      .reverse()
      .limit(bounded)
      .toArray()
    return rows
      .filter((row) => row.notification.accountId === accountId)
      .map((row) => ({ ...row.notification }))
  }

  async statistics(accountId?: string, conversationId?: string): Promise<CacheStatistics> {
    if (conversationId) assertConversationScope(accountId ?? '', conversationId)
    const messages = conversationId
      ? this.database.messages
          .where('[accountId+conversationId+timestampMs]')
          .between([accountId ?? '', conversationId, Dexie.minKey], [accountId ?? '', conversationId, Dexie.maxKey])
      : accountId
        ? this.database.messages.where('accountId').equals(accountId)
        : this.database.messages.toCollection()
    const events = conversationId
      ? this.database.conversationEvents
          .where('[accountId+conversationId+timestampMs]')
          .between([accountId ?? '', conversationId, Dexie.minKey], [accountId ?? '', conversationId, Dexie.maxKey])
      : accountId
        ? this.database.conversationEvents.where('accountId').equals(accountId)
        : this.database.conversationEvents.toCollection()
    const conversations = accountId
      ? this.database.conversations.where('accountId').equals(accountId)
      : this.database.conversations.toCollection()
    const [messageRows, eventCount, notificationCount, conversationCount, draftCount, estimate] = await Promise.all([
      messages.toArray(),
      events.count(),
      conversationId
        ? Promise.resolve(0)
        : accountId
          ? this.database.notifications.where('accountId').equals(accountId).count()
          : this.database.notifications.count(),
      conversationId
        ? this.database.conversations
            .get(conversationId)
            .then((conversation) => Number(conversation?.accountId === accountId))
        : conversations.count(),
      conversationId
        ? this.database.drafts.get(conversationId).then((draft) => Number(draft?.accountId === accountId))
        : accountId
          ? this.database.drafts.where('accountId').equals(accountId).count()
          : this.database.drafts.count(),
      typeof navigator !== 'undefined' && navigator.storage?.estimate
        ? navigator.storage.estimate()
        : Promise.resolve({ usage: 0, quota: 0 }),
    ])
    const timestamps = messageRows.map((row) => row.timestampMs).filter((value) => Number.isFinite(value) && value > 0)
    return {
      accountId,
      conversationId,
      conversationCount,
      messageCount: messageRows.length,
      eventCount,
      notificationCount,
      draftCount,
      firstTimestampMs: timestamps.length ? Math.min(...timestamps) : undefined,
      lastTimestampMs: timestamps.length ? Math.max(...timestamps) : undefined,
      estimatedUsage: estimate.usage ?? 0,
      estimatedQuota: estimate.quota ?? 0,
    }
  }

  async clearAll(): Promise<void> {
    this.globalGeneration += 1
    this.accountGenerations.clear()
    await this.database.transaction(
      'rw',
      [
        this.database.messages,
        this.database.conversations,
        this.database.historyRanges,
        this.database.conversationEvents,
        this.database.drafts,
        this.database.notifications,
      ],
      async () => {
        await Promise.all([
          this.database.messages.clear(),
          this.database.conversations.clear(),
          this.database.historyRanges.clear(),
          this.database.conversationEvents.clear(),
          this.database.drafts.clear(),
          this.database.notifications.clear(),
        ])
      },
    )
  }

  captureWriteGeneration(accountId: string): CacheWriteGeneration {
    return {
      global: this.globalGeneration,
      account: this.accountGenerations.get(accountId) ?? 0,
    }
  }

  private writeGenerationCurrent(accountId: string, generation: CacheWriteGeneration): boolean {
    return generation.global === this.globalGeneration && generation.account === (this.accountGenerations.get(accountId) ?? 0)
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

  private async pruneMessages(accountId: string, conversationId: string): Promise<Set<string>> {
    const prunedConversations = new Set<string>()
    const conversationRows = this.database.messages
      .where('[accountId+conversationId+timestampMs]')
      .between([accountId, conversationId, Dexie.minKey], [accountId, conversationId, Dexie.maxKey])
    const conversationExcess = Math.max(0, (await conversationRows.count()) - this.maxMessagesPerConversation)
    if (conversationExcess) {
      const rows = await conversationRows.limit(conversationExcess).toArray()
      await this.database.messages.bulkDelete(rows.map((row) => row.cacheId))
      rows.forEach((row) => prunedConversations.add(row.conversationId))
    }
    const accountRows = this.database.messages
      .where('[accountId+timestampMs]')
      .between([accountId, Dexie.minKey], [accountId, Dexie.maxKey])
    const accountExcess = Math.max(0, (await accountRows.count()) - this.maxMessagesPerAccount)
    if (accountExcess) {
      const rows = await accountRows.limit(accountExcess).toArray()
      await this.database.messages.bulkDelete(rows.map((row) => row.cacheId))
      rows.forEach((row) => prunedConversations.add(row.conversationId))
    }
    if (prunedConversations.size) await this.database.historyRanges.bulkDelete([...prunedConversations])
    return prunedConversations
  }
}

export const workspaceCache = new WorkspaceCache()
