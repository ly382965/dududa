import 'fake-indexeddb/auto'

import { afterEach, describe, expect, it } from 'vitest'

import type { ChatMessage, Conversation, HistoryPage } from '../types/workspace'
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
})
