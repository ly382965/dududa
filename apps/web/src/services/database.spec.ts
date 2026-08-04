import 'fake-indexeddb/auto'

import { afterEach, describe, expect, it } from 'vitest'

import type { ChatMessage, Conversation, HistoryPage, QqNotification } from '../types/workspace'
import { WorkspaceCache, WorkspaceDatabase } from './database'

const databases: WorkspaceDatabase[] = []

function cache(): WorkspaceCache {
  const database = new WorkspaceDatabase(`dududa-test-${crypto.randomUUID()}`)
  databases.push(database)
  return new WorkspaceCache(database)
}

function conversation(accountId: string): Conversation {
  return {
    id: `${accountId}:group:345678901`,
    accountId,
    type: 'group',
    peerId: '345678901',
    name: '真实群聊',
    avatar: '',
    lastMessage: '',
    lastMessageAt: '',
    unread: 0,
    pinned: false,
    muted: false,
    updatedAt: 0,
  }
}

function message(target: Conversation, sequence: number, text: string): ChatMessage {
  return {
    id: `${target.id}:${sequence}`,
    accountId: target.accountId,
    conversationId: target.id,
    messageId: String(sequence),
    messageSeq: String(sequence),
    senderId: '123456789',
    senderName: '群成员',
    senderAvatar: '',
    timestamp: '12:00',
    timestampMs: sequence * 1_000,
    content: text,
    segments: [{ type: 'text', text }],
    mine: false,
  }
}

function page(messages: ChatMessage[]): HistoryPage {
  return { messages, beforeCursor: 'before', afterCursor: 'after', hasMoreBefore: true, hasMoreAfter: false }
}

function notification(accountId: string, id: string, occurredAt: number): QqNotification {
  return {
    id,
    accountId,
    kind: 'friend-request',
    occurredAt,
    userId: '456789012',
    state: 'pending',
    actionable: true,
  }
}

afterEach(async () => {
  await Promise.all(databases.splice(0).map((database) => database.delete()))
})

describe('WorkspaceCache', () => {
  it('partitions identical QQ conversations and drafts by account', async () => {
    const storage = cache()
    const first = conversation('qq-111111111')
    const second = conversation('qq-222222222')
    await storage.saveHistoryPage(first, page([message(first, 1, '账号一消息')]))
    await storage.saveHistoryPage(second, page([message(second, 1, '账号二消息')]))
    await storage.saveDraft({ accountId: first.accountId, conversationId: first.id, content: { text: '一号草稿' }, updatedAt: 1 })
    await storage.saveDraft({ accountId: second.accountId, conversationId: second.id, content: { text: '二号草稿' }, updatedAt: 2 })

    expect((await storage.recentMessages(first.accountId, first.id))[0]?.content).toBe('账号一消息')
    expect((await storage.recentMessages(second.accountId, second.id))[0]?.content).toBe('账号二消息')
    expect(await storage.draft(first.accountId, first.id)).toMatchObject({ content: { text: '一号草稿' } })
    expect(await storage.draft(second.accountId, second.id)).toMatchObject({ content: { text: '二号草稿' } })

    await storage.clearAccount(first.accountId)
    expect(await storage.recentMessages(first.accountId, first.id)).toEqual([])
    expect((await storage.recentMessages(second.accountId, second.id))[0]?.content).toBe('账号二消息')
  })

  it('does not persist ephemeral browser media or local paths', async () => {
    const storage = cache()
    const target = conversation('qq-111111111')
    const rich = message(target, 2, '[图片]')
    rich.segments = [
      { type: 'image', url: 'blob:secret', summary: '[图片]', sticker: false },
      { type: 'video', url: 'file:///tmp/private.mp4', thumbnailUrl: 'data:image/png;base64,abc' },
    ]
    rich.attachments = [{ kind: 'image', url: 'base64://private' }]

    await storage.saveHistoryPage(target, page([rich]))
    const stored = (await storage.recentMessages(target.accountId, target.id))[0]!

    expect(stored.segments).toEqual([
      { type: 'image', url: undefined, summary: '[图片]', sticker: false },
      { type: 'video', url: undefined, thumbnailUrl: undefined },
    ])
    expect(stored.attachments).toEqual([{ kind: 'image', url: undefined }])
  })

  it('refuses a draft whose account does not own the conversation key', async () => {
    const storage = cache()
    await expect(
      storage.saveDraft({
        accountId: 'qq-111111111',
        conversationId: 'qq-222222222:group:345678901',
        content: { text: '串号草稿' },
        updatedAt: 1,
      }),
    ).rejects.toThrow('草稿账号与会话不匹配')
  })

  it('refuses conversation cache writes whose encoded account does not match', async () => {
    const storage = cache()
    const target = conversation('qq-111111111')
    target.id = 'qq-222222222:group:345678901'

    await expect(storage.saveConversation(target)).rejects.toThrow('不属于当前 QQ 账号')
    await expect(storage.saveHistoryPage(target, page([]))).rejects.toThrow('不属于当前 QQ 账号')
  })

  it('preserves draft text that resembles a path while removing ephemeral URLs', async () => {
    const storage = cache()
    const target = conversation('qq-111111111')
    await storage.saveDraft({
      accountId: target.accountId,
      conversationId: target.id,
      content: { text: '/help 和 /tmp/说明', preview: 'blob:temporary-image' },
      updatedAt: 1,
    })

    expect(await storage.draft(target.accountId, target.id)).toMatchObject({
      content: { text: '/help 和 /tmp/说明' },
    })
  })

  it('paginates every cached message when timestamps are identical', async () => {
    const storage = cache()
    const target = conversation('qq-111111111')
    const messages = [message(target, 1, '第一条'), message(target, 2, '第二条'), message(target, 3, '第三条')]
    messages.forEach((item) => (item.timestampMs = 10_000))
    await storage.saveHistoryPage(target, page(messages))

    const first = await storage.searchMessages({
      accountId: target.accountId,
      conversationId: target.id,
      query: '条',
      limit: 2,
    })
    expect(first.messages.map((item) => item.messageId)).toEqual(['3', '2'])
    expect(first.hasMore).toBe(true)
    const cursor = first.messages.at(-1)!
    const second = await storage.searchMessages({
      accountId: target.accountId,
      conversationId: target.id,
      query: '条',
      beforeTimestampMs: cursor.timestampMs,
      beforeCacheId: cursor.id,
      limit: 2,
    })
    expect(second.messages.map((item) => item.messageId)).toEqual(['1'])
    expect(second.hasMore).toBe(false)
  })

  it('merges before and after coverage without losing the opposite cursor', async () => {
    const storage = cache()
    const target = conversation('qq-111111111')
    await storage.saveHistoryPage(target, {
      messages: [message(target, 10, '初始')],
      beforeCursor: 'before-10',
      afterCursor: 'after-10',
      hasMoreBefore: true,
      hasMoreAfter: false,
    })
    await storage.saveHistoryPage(
      target,
      {
        messages: [message(target, 5, '更早')],
        beforeCursor: 'before-5',
        afterCursor: 'after-5',
        hasMoreBefore: false,
        hasMoreAfter: true,
      },
      'before',
    )

    expect(await storage.historyRange(target.accountId, target.id)).toMatchObject({
      beforeCursor: 'before-5',
      afterCursor: 'after-10',
      hasMoreBefore: false,
      hasMoreAfter: false,
    })
  })

  it('invalidates history coverage and reports a page that pruning could not retain', async () => {
    const database = new WorkspaceDatabase(`dududa-test-${crypto.randomUUID()}`)
    databases.push(database)
    const storage = new WorkspaceCache(database, { maxMessagesPerConversation: 2, maxMessagesPerAccount: 4 })
    const target = conversation('qq-111111111')
    await storage.saveHistoryPage(target, page([message(target, 2, '第二条'), message(target, 3, '第三条')]))

    const receipt = await storage.saveHistoryPage(
      target,
      page([message(target, 1, '被边界裁剪的更早消息')]),
      'before',
    )

    expect(receipt).toEqual({ requestedMessageCount: 1, persistedMessageCount: 0, coverageRetained: false })
    expect(await storage.historyRange(target.accountId, target.id)).toBeUndefined()
    expect((await storage.recentMessages(target.accountId, target.id)).map((item) => item.messageId)).toEqual(['2', '3'])
  })

  it('reports and clears only the selected account cache without QQ mutations', async () => {
    const storage = cache()
    const first = conversation('qq-111111111')
    const second = conversation('qq-222222222')
    const oldMessage = message(first, 1, '旧消息')
    oldMessage.timestampMs = 1_000
    const newMessage = message(first, 2, '新消息')
    newMessage.timestampMs = 3_000
    const otherMessage = message(second, 1, '其他账号')
    otherMessage.timestampMs = 1_000
    await storage.saveHistoryPage(first, page([oldMessage, newMessage]))
    await storage.saveHistoryPage(second, page([otherMessage]))

    expect(await storage.statistics(first.accountId)).toMatchObject({
      accountId: first.accountId,
      conversationCount: 1,
      messageCount: 2,
      firstTimestampMs: 1_000,
      lastTimestampMs: 3_000,
    })

    expect(await storage.clearBefore(first.accountId, 2_000)).toBe(1)
    expect((await storage.recentMessages(first.accountId, first.id)).map((item) => item.content)).toEqual(['新消息'])
    expect((await storage.recentMessages(second.accountId, second.id)).map((item) => item.content)).toEqual(['其他账号'])
    expect(await storage.historyRange(first.accountId, first.id)).toBeUndefined()
  })

  it('persists bounded account-scoped notifications and preserves unknown event times during date cleanup', async () => {
    const storage = cache()
    const accountId = 'qq-111111111'
    await storage.saveNotifications(accountId, [
      notification(accountId, 'known', 1_000),
      notification(accountId, 'unknown', 0),
    ])

    expect((await storage.cachedNotifications(accountId)).map((item) => item.id)).toEqual(['unknown', 'known'])
    expect(await storage.clearBefore(accountId, 2_000)).toBe(1)
    expect((await storage.cachedNotifications(accountId)).map((item) => item.id)).toEqual(['unknown'])
    expect(await storage.statistics(accountId)).toMatchObject({ notificationCount: 1 })

    await expect(
      storage.saveNotifications(accountId, [notification('qq-222222222', 'cross-account', Date.now())]),
    ).rejects.toThrow('通知缓存账号不匹配')
  })

  it('keeps only the newest 500 observed notifications per account and can clear every account', async () => {
    const storage = cache()
    const first = 'qq-111111111'
    const second = 'qq-222222222'
    await storage.saveNotifications(
      first,
      Array.from({ length: 501 }, (_, index) => notification(first, `first-${index}`, index + 1)),
    )
    await storage.saveNotifications(second, [notification(second, 'second', 10)])

    const firstItems = await storage.cachedNotifications(first)
    expect(firstItems).toHaveLength(500)
    expect(firstItems.some((item) => item.id === 'first-0')).toBe(false)
    expect(await storage.cachedNotifications(second)).toHaveLength(1)

    await storage.clearAll()
    expect(await storage.cachedNotifications(first)).toEqual([])
    expect(await storage.cachedNotifications(second)).toEqual([])
  })
})
