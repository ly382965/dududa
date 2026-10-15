import { describe, expect, it } from 'vitest'

import type { ChatMessage, Conversation, HistoryPage } from '../types/workspace'
import { backfillHistory } from './history-backfill'
import type { WorkspaceAdapter } from './workspace-adapter'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => (resolve = done))
  return { promise, resolve }
}

function conversation(accountId = 'qq-123456789'): Conversation {
  return {
    id: `${accountId}:group:345678901`,
    accountId,
    type: 'group',
    peerId: '345678901',
    name: '群聊',
    avatar: '',
    lastMessage: '',
    lastMessageAt: '',
    unread: 0,
    pinned: false,
    muted: false,
  }
}

function message(target: Conversation, id: number, timestampMs: number): ChatMessage {
  return {
    id: `${target.id}:${id}`,
    accountId: target.accountId,
    conversationId: target.id,
    messageId: String(id),
    messageSeq: String(id),
    senderId: '234567890',
    senderName: '成员',
    senderAvatar: '',
    timestamp: '',
    timestampMs,
    content: String(id),
    segments: [{ type: 'text', text: String(id) }],
    mine: false,
  }
}

describe('backfillHistory', () => {
  it('advances one opaque cursor chain sequentially until the requested start time', async () => {
    const target = conversation()
    const beforeValues: Array<string | undefined> = []
    const cacheRequirements: Array<boolean | undefined> = []
    const pages: HistoryPage[] = [
      { messages: [message(target, 30, 3_000)], beforeCursor: 'opaque-30', hasMoreBefore: true, hasMoreAfter: false },
      { messages: [message(target, 20, 2_000)], beforeCursor: 'opaque-20', hasMoreBefore: true, hasMoreAfter: false },
      { messages: [message(target, 10, 1_000)], beforeCursor: 'opaque-10', hasMoreBefore: true, hasMoreAfter: false },
    ]
    const adapter = {
      loadHistory: async (_conversation: Conversation, request?: { before?: string }) => {
        beforeValues.push(request?.before)
        cacheRequirements.push((request as { cacheRequired?: boolean } | undefined)?.cacheRequired)
        return pages[beforeValues.length - 1]!
      },
    } as unknown as WorkspaceAdapter

    const result = await backfillHistory([target], 1_500, 3_500, new AbortController().signal, () => undefined, adapter)

    expect(beforeValues).toEqual([undefined, 'opaque-30', 'opaque-20'])
    expect(cacheRequirements).toEqual([true, true, true])
    expect(result).toMatchObject({ completedConversations: 1, failedConversations: 0, fetchedMessages: 3, coveredMessages: 2 })
  })

  it('stops a conversation when NapCat repeats an opaque cursor', async () => {
    const target = conversation()
    const adapter = {
      loadHistory: async () => ({
        messages: [message(target, 30, 3_000)],
        beforeCursor: 'same-cursor',
        hasMoreBefore: true,
        hasMoreAfter: false,
      }),
    } as unknown as WorkspaceAdapter

    const result = await backfillHistory([target], 500, 4_000, new AbortController().signal, () => undefined, adapter)

    expect(result).toMatchObject({ completedConversations: 0, failedConversations: 1 })
  })

  it('rejects a cross-account backfill scope', async () => {
    await expect(
      backfillHistory(
        [conversation('qq-123456789'), conversation('qq-987654321')],
        1,
        2,
        new AbortController().signal,
        () => undefined,
        {} as WorkspaceAdapter,
      ),
    ).rejects.toThrow('不能跨 QQ 账号')
  })

  it('reports a bounded run as truncated instead of complete', async () => {
    const target = conversation()
    const adapter = {
      loadHistory: async () => ({
        messages: [message(target, 30, 3_000)],
        beforeCursor: 'opaque-30',
        hasMoreBefore: true,
        hasMoreAfter: false,
      }),
    } as unknown as WorkspaceAdapter

    const result = await backfillHistory(
      [target],
      500,
      4_000,
      new AbortController().signal,
      () => undefined,
      adapter,
      { maxPagesPerConversation: 1 },
    )

    expect(result).toMatchObject({
      completedConversations: 0,
      failedConversations: 0,
      truncatedConversations: 1,
    })
    expect(result.truncations[0]).toMatchObject({ conversationId: target.id, reason: expect.stringContaining('1 页') })
  })

  it('does not count a terminal page that resolves after cancellation', async () => {
    const target = conversation()
    const pending = deferred<HistoryPage>()
    const adapter = { loadHistory: async () => pending.promise } as unknown as WorkspaceAdapter
    const controller = new AbortController()
    const run = backfillHistory([target], 500, 4_000, controller.signal, () => undefined, adapter)

    controller.abort()
    pending.resolve({
      messages: [message(target, 30, 3_000)],
      beforeCursor: 'opaque-30',
      hasMoreBefore: false,
      hasMoreAfter: false,
    })

    await expect(run).resolves.toMatchObject({
      cancelled: true,
      completedConversations: 0,
      fetchedMessages: 0,
    })
  })
})
