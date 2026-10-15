import { mkdtemp, rm, stat } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'

import { afterEach, describe, expect, it } from 'vitest'

import type { ChatMessage } from '../src/types/workspace'
import { RecallStore, type RecallStoreOptions } from './recall-store'

const dayMs = 86_400_000
const roots: string[] = []
const stores: RecallStore[] = []
const accountId = 'qq-111111111'
const conversationId = `${accountId}:group:345678901`

function message(sequence: number, owner = accountId, peerId = '345678901'): ChatMessage {
  const scope = `${owner}:group:${peerId}`
  return {
    id: `${scope}:${sequence}`,
    accountId: owner,
    conversationId: scope,
    messageId: String(sequence),
    senderId: '222222222',
    senderName: '测试成员',
    senderAvatar: '',
    timestamp: '12:00',
    timestampMs: 1_000,
    content: `合成消息 ${sequence}`,
    segments: [{ type: 'text', text: `合成消息 ${sequence}` }],
    mine: false,
    status: 'sent',
  }
}

async function temporaryStore(options: Partial<RecallStoreOptions> = {}) {
  const root = await mkdtemp(join(tmpdir(), 'dududa-recall-'))
  roots.push(root)
  const path = join(root, 'private', 'messages.sqlite')
  const store = new RecallStore({ path, ...options })
  stores.push(store)
  return { root, path, store }
}

afterEach(async () => {
  for (const store of stores.splice(0)) store.close()
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })))
})

describe('RecallStore', () => {
  it('persists captured forward details through replays and restart, without reviving disabled or expired records', async () => {
    let now = 1_000
    const { store, path } = await temporaryStore({ now: () => now, retentionDays: 1 })
    const original = { ...message(1), content: '[转发消息]', segments: [{ type: 'forward' as const, forwardId: 'bundle' }] }
    const children = [message(2)]
    store.remember(original)
    store.saveForward(accountId, conversationId, original.id, 'bundle', children)
    store.remember(original)
    store.recall(accountId, conversationId, original.id, { recalledAt: now })
    store.remember(original)
    store.close()
    const reopened = new RecallStore({ path, now: () => now })
    stores.push(reopened)
    expect(reopened.get(accountId, conversationId, original.id)).toMatchObject({
      status: 'recalled', segments: [{ type: 'forward', messages: children }], recall: { expiresAt: 1_000 + dayMs },
    })
    expect(reopened.saveForward(accountId, `${accountId}:private:456789012`, original.id, 'bundle', children)).toBeUndefined()
    reopened.setSettings(accountId, conversationId, { enabled: false, retentionDays: 1 })
    expect(reopened.saveForward(accountId, conversationId, original.id, 'bundle', children)).toBeUndefined()
    reopened.setSettings(accountId, conversationId, { enabled: true, retentionDays: 1 })
    expect(reopened.get(accountId, conversationId, original.id)).toBeUndefined()
    reopened.remember(original)
    now += dayMs
    expect(reopened.saveForward(accountId, conversationId, original.id, 'bundle', children)).toBeUndefined()
    expect(reopened.get(accountId, conversationId, original.id)).toBeUndefined()
  })

  it('keeps originals and settings across restarts with private filesystem permissions', async () => {
    let now = 1_000
    const { store, path } = await temporaryStore({ now: () => now })
    const original = message(1)
    expect(store.remember(original)).toEqual(original)
    store.setSettings(accountId, conversationId, { enabled: true, retentionDays: 3 })
    store.close()

    now += 1_000
    const reopened = new RecallStore({ path, now: () => now })
    stores.push(reopened)
    expect(reopened.getSettings(accountId, conversationId)).toEqual({ enabled: true, retentionDays: 3 })
    const recalled = reopened.recall(accountId, conversationId, original.id, { recalledAt: now, operatorId: '333333333' })
    expect(recalled).toMatchObject({
      content: original.content,
      segments: original.segments,
      status: 'recalled',
      recall: { retained: true, recalledAt: now, operatorId: '333333333', expiresAt: 1_000 + 3 * dayMs },
    })
    expect((await stat(path)).mode & 0o777).toBe(0o600)
    expect((await stat(join(path, '..'))).mode & 0o777).toBe(0o700)
    reopened.close()

    const archive = new RecallStore({ path, now: () => now })
    stores.push(archive)
    expect(archive.listRecalled(accountId, conversationId).messages).toEqual([recalled])
  })

  it('expires at the original deadline without extending it on message or recall replays', async () => {
    let now = 1_000
    const { store } = await temporaryStore({ now: () => now, retentionDays: 2 })
    const original = message(1)
    store.remember(original)
    expect(store.expiresAt(accountId, conversationId, original.id)).toBe(now + 2 * dayMs)
    now += dayMs
    store.remember(original)
    store.recall(accountId, conversationId, original.id, { recalledAt: now })
    now += 1_000
    store.remember(original)
    const replay = store.recall(accountId, conversationId, original.id, { recalledAt: now })
    expect(replay?.recall).toMatchObject({ recalledAt: 1_000 + dayMs, expiresAt: 1_000 + 2 * dayMs })

    now = 1_000 + 2 * dayMs - 1
    expect(store.get(accountId, conversationId, original.id)?.content).toBe(original.content)
    now += 1
    expect(store.get(accountId, conversationId, original.id)).toBeUndefined()
    expect(store.expiresAt(accountId, conversationId, original.id)).toBeUndefined()
    expect(store.listRecalled(accountId, conversationId).messages).toEqual([])
  })

  it('deletes disabled conversation data immediately and respects a disabled default', async () => {
    const { store } = await temporaryStore({ defaultEnabled: false })
    const original = message(1)
    expect(store.getSettings(accountId, conversationId)).toEqual({ enabled: false, retentionDays: 7 })
    expect(store.remember(original)).toBeUndefined()
    expect(store.recall(accountId, conversationId, original.id, { recalledAt: 1_000 })).toBeUndefined()

    store.setSettings(accountId, conversationId, { enabled: true, retentionDays: 7 })
    store.remember(original)
    store.recall(accountId, conversationId, original.id, { recalledAt: 1_000 })
    expect(store.listRecalled(accountId, conversationId).messages).toHaveLength(1)
    store.setSettings(accountId, conversationId, { enabled: false, retentionDays: 7 })
    expect(store.listRecalled(accountId, conversationId)).toEqual({
      settings: { enabled: false, retentionDays: 7 }, messages: [], hasMore: false,
    })
    store.setSettings(accountId, conversationId, { enabled: true, retentionDays: 7 })
    expect(store.get(accountId, conversationId, original.id)).toBeUndefined()
  })

  it('shortens existing retention immediately and only applies longer retention to new records', async () => {
    let now = 1_000
    const { store } = await temporaryStore({ now: () => now })
    const original = message(1)
    store.remember(original)
    store.recall(accountId, conversationId, original.id, { recalledAt: now })
    store.setSettings(accountId, conversationId, { enabled: true, retentionDays: 30 })
    expect(store.get(accountId, conversationId, original.id)?.recall?.expiresAt).toBe(now + 7 * dayMs)
    now += 2 * dayMs
    store.setSettings(accountId, conversationId, { enabled: true, retentionDays: 1 })
    expect(store.listRecalled(accountId, conversationId).messages).toEqual([])
    expect(store.get(accountId, conversationId, original.id)).toBeUndefined()

    for (const retentionDays of [0, 31, 1.5, Number.NaN]) {
      expect(() => store.setSettings(accountId, conversationId, { enabled: true, retentionDays })).toThrow('1 至 30 天')
    }
    expect(store.getSettings(accountId, conversationId)).toEqual({ enabled: true, retentionDays: 1 })
  })

  it('isolates account and conversation data and rejects mismatched scopes', async () => {
    const { store } = await temporaryStore()
    const first = message(1)
    const otherAccount = message(1, 'qq-444444444')
    const otherGroup = message(1, accountId, '987654321')
    for (const item of [first, otherAccount, otherGroup]) {
      store.remember(item)
      store.recall(item.accountId, item.conversationId, item.id, { recalledAt: 1_000 })
    }
    expect(store.get(accountId, conversationId, otherAccount.id)).toBeUndefined()
    expect(() => store.get('qq-444444444', conversationId, first.id)).toThrow('不属于当前账号')
    expect(() => store.remember({ ...first, accountId: 'qq-444444444' })).toThrow('不属于当前账号')
    store.setSettings(accountId, conversationId, { enabled: false, retentionDays: 7 })
    expect(store.listRecalled(otherAccount.accountId, otherAccount.conversationId).messages).toHaveLength(1)
    expect(store.listRecalled(accountId, otherGroup.conversationId).messages).toHaveLength(1)
  })

  it('handles recall arriving before the message without inventing originals or losing recall state', async () => {
    let now = 1_000
    const { store } = await temporaryStore({ now: () => now })
    const original = message(1)
    expect(store.recall(accountId, conversationId, original.id, { recalledAt: now })).toBeUndefined()
    expect(store.listRecalled(accountId, conversationId).messages).toEqual([])
    expect(store.remember({ ...original, content: '此消息已撤回', segments: [], status: 'recalled' })).toBeUndefined()
    now += 1_000
    const recovered = store.remember(original)
    expect(recovered).toMatchObject({
      content: original.content,
      status: 'recalled',
      recall: { recalledAt: 1_000, retained: true, expiresAt: 1_000 + 7 * dayMs },
    })
    const replay = store.remember({ ...original, content: '重放替换文字', segments: [{ type: 'text', text: '重放替换文字' }] })
    expect(replay).toEqual(recovered)

    const refreshed = store.remember({
      ...original, segments: [...original.segments, { type: 'image', url: 'https://gchat.qpic.cn/refreshed', summary: '[图片]', sticker: false }],
    })
    expect(refreshed?.segments).toHaveLength(2)
    expect(refreshed?.recall).toEqual(recovered?.recall)
    expect(refreshed?.status).toBe('recalled')
  })

  it('paginates recalled originals stably when timestamps tie', async () => {
    const { store } = await temporaryStore()
    for (const sequence of [1, 2, 3, 4, 5]) {
      const item = message(sequence)
      store.remember(item)
      store.recall(accountId, conversationId, item.id, { recalledAt: sequence === 5 ? 2_000 : 1_000 })
    }
    store.remember(message(6))
    store.recall(accountId, conversationId, message(7).id, { recalledAt: 3_000 })
    const first = store.listRecalled(accountId, conversationId, { limit: 2 })
    expect(first.messages.map((item) => item.messageId)).toEqual(['5', '4'])
    expect(first.hasMore).toBe(true)
    const second = store.listRecalled(accountId, conversationId, { limit: 2, before: first.nextCursor })
    expect(second.messages.map((item) => item.messageId)).toEqual(['3', '2'])
    const third = store.listRecalled(accountId, conversationId, { limit: 2, before: second.nextCursor })
    expect(third.messages.map((item) => item.messageId)).toEqual(['1'])
    expect(third.hasMore).toBe(false)
    expect(third.nextCursor).toBeUndefined()
    expect(() => store.listRecalled(accountId, `${accountId}:group:987654321`, { before: first.nextCursor })).toThrow('当前会话不匹配')
    expect(() => store.listRecalled(accountId, conversationId, { before: 'invalid' })).toThrow('游标无效')
  })

  it('lets the gateway prune expired originals with no browser reads', async () => {
    let now = 1_000
    const { store, path } = await temporaryStore({ now: () => now, retentionDays: 1 })
    store.remember(message(1))
    now += dayMs
    store.prune()
    const database = new DatabaseSync(path, { readOnly: true })
    try {
      expect(database.prepare('SELECT COUNT(*) AS count FROM recall_messages').get()?.count).toBe(0)
    } finally {
      database.close()
    }
  })
})
