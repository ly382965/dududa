import 'fake-indexeddb/auto'

import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ChatMessage, Conversation, HistoryPage } from '../types/workspace'
import { WorkspaceCache, WorkspaceDatabase } from './database'
import { NapCatWorkspaceAdapter } from './workspace-adapter'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => (resolve = done))
  return { promise, resolve }
}

const databases: WorkspaceDatabase[] = []

function fixture() {
  const accountId = 'qq-123456789'
  const conversation: Conversation = {
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
  }
  const message: ChatMessage = {
    id: `${conversation.id}:101`,
    accountId,
    conversationId: conversation.id,
    messageId: '101',
    messageSeq: '101',
    senderId: '234567890',
    senderName: '真实成员',
    senderAvatar: '',
    timestamp: '12:00',
    timestampMs: 1_000,
    content: '清理前发出的慢请求',
    segments: [{ type: 'text', text: '清理前发出的慢请求' }],
    mine: false,
  }
  const page: HistoryPage = { messages: [message], hasMoreBefore: false, hasMoreAfter: false }
  const database = new WorkspaceDatabase(`dududa-adapter-test-${crypto.randomUUID()}`)
  databases.push(database)
  const cache = new WorkspaceCache(database)
  return { accountId, conversation, page, cache, adapter: new NapCatWorkspaceAdapter('', cache) }
}

afterEach(async () => {
  vi.unstubAllGlobals()
  await Promise.all(databases.splice(0).map((database) => database.delete()))
})

describe('NapCat workspace cache cleanup barrier', () => {
  it.each(['account', 'all', 'before'] as const)(
    'does not persist a history response that predates %s cleanup',
    async (mode) => {
      const { accountId, conversation, page, cache, adapter } = fixture()
      const response = deferred<Response>()
      vi.stubGlobal('fetch', vi.fn(async () => response.promise))
      const loading = adapter.loadHistory(conversation)

      if (mode === 'account') await cache.clearAccount(accountId)
      else if (mode === 'all') await cache.clearAll()
      else await cache.clearBefore(accountId, 2_000)
      response.resolve(new Response(JSON.stringify(page), { status: 200 }))

      await expect(loading).resolves.toEqual(page)
      expect(await cache.recentMessages(accountId, conversation.id)).toEqual([])
    },
  )
})
