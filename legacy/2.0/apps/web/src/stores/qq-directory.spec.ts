import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { WorkspaceAdapter } from '../services/workspace-adapter'
import type { AccountDirectory, GroupMemberDirectory, NotificationInbox, QqNotification, WorkspaceEvent } from '../types/workspace'
import { groupMemberDirectoryKey, useQqDirectoryStore } from './qq-directory'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => (resolve = done))
  return { promise, resolve }
}

function directory(accountId: string, name: string): AccountDirectory {
  return {
    accountId,
    friends: [{ accountId, userId: '456789012', nickname: name, remark: '', avatar: '' }],
    groups: [],
    refreshedAt: Date.now(),
  }
}

function requestNotification(
  accountId: string,
  overrides: Partial<QqNotification> = {},
): QqNotification {
  return {
    id: 'request-1',
    accountId,
    kind: 'friend-request',
    occurredAt: 1_000,
    userId: '456789012',
    state: 'pending',
    actionable: true,
    ...overrides,
  }
}

describe('qq directory store', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.useRealTimers())

  it('ignores a stale same-account response without losing another account', async () => {
    const first = deferred<AccountDirectory>()
    const second = deferred<AccountDirectory>()
    const calls: Array<Promise<AccountDirectory>> = [first.promise, second.promise]
    const adapter = {
      loadDirectory: async () => calls.shift()!,
      subscribe: () => () => undefined,
    } as unknown as WorkspaceAdapter
    const store = useQqDirectoryStore()
    store.startEvents(adapter)

    const firstLoad = store.loadDirectory('qq-111111111', true)
    const secondLoad = store.loadDirectory('qq-111111111', true)
    second.resolve(directory('qq-111111111', '新结果'))
    await secondLoad
    first.resolve(directory('qq-111111111', '迟到结果'))
    await firstLoad

    expect(store.directories['qq-111111111']?.friends[0]?.nickname).toBe('新结果')
  })

  it('partitions group members and observed notifications by account', async () => {
    const memberDirectory = (accountId: string): GroupMemberDirectory => ({
      accountId,
      groupId: '345678901',
      selfUserId: accountId.slice(3),
      selfRole: 'admin',
      members: [],
      permissions: {
        mentionAll: { allowed: true },
        setAdmin: { allowed: false },
        kickMembers: { allowed: true },
        editOwnCard: { allowed: true },
        rename: { allowed: true },
        muteAll: { allowed: true },
        quit: { allowed: true },
        readEssence: { allowed: true },
        readAnnouncements: { allowed: true },
        deleteAnnouncements: { allowed: true },
        readFiles: { allowed: true },
        uploadFiles: { allowed: true },
        manageFiles: { allowed: true },
        packetFiles: { allowed: true },
        renameFolders: { allowed: false },
      },
      refreshedAt: Date.now(),
    })
    const inbox = (accountId: string): NotificationInbox => ({
      accountId,
      items: [],
      limitations: { friendHistory: '仅观察事件' },
      refreshedAt: Date.now(),
    })
    const adapter = {
      loadGroupMembers: async (accountId: string) => memberDirectory(accountId),
      loadNotifications: async (accountId: string) => inbox(accountId),
      subscribe: () => () => undefined,
    } as unknown as WorkspaceAdapter
    const store = useQqDirectoryStore()
    store.startEvents(adapter)
    await Promise.all([
      store.loadMembers('qq-111111111', '345678901'),
      store.loadMembers('qq-222222222', '345678901'),
      store.loadNotifications('qq-111111111'),
      store.loadNotifications('qq-222222222'),
    ])

    expect(store.memberDirectories[groupMemberDirectoryKey('qq-111111111', '345678901')]?.selfUserId).toBe('111111111')
    expect(store.memberDirectories[groupMemberDirectoryKey('qq-222222222', '345678901')]?.selfUserId).toBe('222222222')
    expect(Object.keys(store.notificationInboxes)).toEqual(['qq-111111111', 'qq-222222222'])
  })

  it('preserves an SSE terminal receipt and timestamp when a stale HTTP refresh finishes later', async () => {
    const accountId = 'qq-111111111'
    const response = deferred<NotificationInbox>()
    let handler: ((event: WorkspaceEvent) => void) | undefined
    const adapter = {
      loadCachedNotifications: async () => [],
      loadNotifications: async () => response.promise,
      cacheNotifications: vi.fn().mockResolvedValue(undefined),
      subscribe: (next: (event: WorkspaceEvent) => void) => {
        handler = next
        return () => undefined
      },
    } as unknown as WorkspaceAdapter
    const store = useQqDirectoryStore()
    store.startEvents(adapter)
    const loading = store.loadNotifications(accountId, true)
    await Promise.resolve()
    handler?.({
      type: 'notification.changed',
      accountId,
      notification: requestNotification(accountId, { state: 'accepted', actionable: false, occurredAt: 5_000 }),
    })
    response.resolve({
      accountId,
      items: [requestNotification(accountId, { state: 'handled', actionable: false, occurredAt: 0 })],
      limitations: { friendHistory: '仅观察事件' },
      refreshedAt: 6_000,
    })
    await loading

    expect(store.notificationInboxes[accountId]?.items[0]).toMatchObject({
      state: 'accepted',
      actionable: false,
      occurredAt: 5_000,
    })
  })

  it('restores cached pending requests as read-only until the current NapCat session confirms them', async () => {
    const accountId = 'qq-111111111'
    let handler: ((event: WorkspaceEvent) => void) | undefined
    const adapter = {
      loadCachedNotifications: async () => [requestNotification(accountId)],
      loadNotifications: async () => ({
        accountId,
        items: [],
        limitations: { friendHistory: '仅观察事件' },
        refreshedAt: Date.now(),
      }),
      cacheNotifications: vi.fn().mockResolvedValue(undefined),
      subscribe: (next: (event: WorkspaceEvent) => void) => {
        handler = next
        return () => undefined
      },
    } as unknown as WorkspaceAdapter
    const store = useQqDirectoryStore()
    store.startEvents(adapter)
    await store.loadNotifications(accountId, true)
    expect(store.notificationInboxes[accountId]?.items[0]?.actionable).toBe(false)

    handler?.({ type: 'notification.changed', accountId, notification: requestNotification(accountId) })
    expect(store.notificationInboxes[accountId]?.items[0]?.actionable).toBe(true)

    handler?.({
      type: 'notification.changed',
      accountId,
      notification: requestNotification(accountId, {
        actionable: false,
        actionReason: '当前 QQ 已不再是群管理员',
      }),
    })
    expect(store.notificationInboxes[accountId]?.items[0]).toMatchObject({
      actionable: false,
      actionReason: '当前 QQ 已不再是群管理员',
    })

    handler?.({
      type: 'notification.changed',
      accountId: 'qq-222222222',
      notification: requestNotification(accountId, { id: 'cross-account' }),
    })
    expect(store.notificationInboxes[accountId]?.items.some((item) => item.id === 'cross-account')).toBe(false)
  })

  it('rejects a notification mutation receipt for another account or request', async () => {
    const accountId = 'qq-111111111'
    const adapter = {
      resolveNotification: async () => requestNotification('qq-222222222'),
      subscribe: () => () => undefined,
    } as unknown as WorkspaceAdapter
    const store = useQqDirectoryStore()
    store.startEvents(adapter)

    await expect(store.resolveNotification(accountId, 'request-1', 'accept')).rejects.toThrow('不匹配')
  })

  it('retries initial failures and refreshes pending notifications globally every 30 seconds', async () => {
    vi.useFakeTimers()
    const accountId = 'qq-111111111'
    const loadNotifications = vi.fn()
      .mockRejectedValueOnce(new Error('temporary failure'))
      .mockResolvedValue({
        accountId,
        items: [requestNotification(accountId)],
        limitations: { friendHistory: '仅观察事件' },
        refreshedAt: Date.now(),
      })
    const adapter = {
      loadCachedNotifications: async () => [],
      loadNotifications,
      cacheNotifications: vi.fn().mockResolvedValue(undefined),
      subscribe: () => () => undefined,
    } as unknown as WorkspaceAdapter
    const store = useQqDirectoryStore()
    store.startEvents(adapter)
    await store.primeNotifications([accountId])
    expect(loadNotifications).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(30_000)
    expect(loadNotifications).toHaveBeenCalledTimes(2)
    expect(store.notificationInboxes[accountId]?.items[0]?.state).toBe('pending')

    await vi.advanceTimersByTimeAsync(30_000)
    expect(loadNotifications).toHaveBeenCalledTimes(3)
    store.notificationInboxes[accountId]!.items[0]!.state = 'accepted'
    store.notificationInboxes[accountId]!.items[0]!.actionable = false
    await vi.advanceTimersByTimeAsync(30_000)
    expect(loadNotifications).toHaveBeenCalledTimes(3)
    store.stopEvents()
  })

  it('does not restore late responses after account, date-range, or global cleanup', async () => {
    vi.useFakeTimers()
    const accountDirectory = deferred<AccountDirectory>()
    const globalDirectory = deferred<AccountDirectory>()
    const notificationResponse = deferred<NotificationInbox>()
    const loadNotifications = vi.fn()
      .mockImplementationOnce(async () => notificationResponse.promise)
      .mockResolvedValue({
        accountId: 'qq-333333333',
        items: [],
        limitations: { friendHistory: '仅观察事件' },
        refreshedAt: 4_000,
      })
    const adapter = {
      loadDirectory: async (accountId: string) =>
        accountId === 'qq-111111111' ? accountDirectory.promise : globalDirectory.promise,
      loadCachedNotifications: async () => [],
      loadNotifications,
      cacheNotifications: vi.fn().mockResolvedValue(undefined),
      subscribe: () => () => undefined,
    } as unknown as WorkspaceAdapter
    const store = useQqDirectoryStore()
    store.startEvents(adapter)

    const accountLoad = store.loadDirectory('qq-111111111', true)
    store.clearAccountState('qq-111111111')
    accountDirectory.resolve(directory('qq-111111111', '不应恢复的账号联系人'))
    await accountLoad
    expect(store.directories['qq-111111111']).toBeUndefined()

    const globalLoad = store.loadDirectory('qq-222222222', true)
    store.clearAllState()
    globalDirectory.resolve(directory('qq-222222222', '不应恢复的全局联系人'))
    await globalLoad
    expect(store.directories['qq-222222222']).toBeUndefined()

    const notificationLoad = store.primeNotifications(['qq-333333333'])
    await Promise.resolve()
    store.clearBeforeState('qq-333333333', 2_000)
    notificationResponse.resolve({
      accountId: 'qq-333333333',
      items: [requestNotification('qq-333333333', { occurredAt: 1_000 })],
      limitations: { friendHistory: '仅观察事件' },
      refreshedAt: 3_000,
    })
    await notificationLoad
    expect(store.notificationInboxes['qq-333333333']).toBeUndefined()
    expect(store.loading['notifications:qq-333333333']).toBeUndefined()
    expect(store.errors['notifications:qq-333333333']).toBeUndefined()
    await vi.advanceTimersByTimeAsync(30_000)
    expect(loadNotifications).toHaveBeenCalledTimes(2)
    store.stopEvents()
  })

  it('does not invalidate a longer QQ account whose ID only shares a prefix', async () => {
    const response = deferred<AccountDirectory>()
    const adapter = {
      loadDirectory: async () => response.promise,
      subscribe: () => () => undefined,
    } as unknown as WorkspaceAdapter
    const store = useQqDirectoryStore()
    store.startEvents(adapter)

    const loading = store.loadDirectory('qq-123456', true)
    store.clearAccountState('qq-12345')
    response.resolve(directory('qq-123456', '应保留的长账号结果'))
    await loading

    expect(store.directories['qq-123456']?.friends[0]?.nickname).toBe('应保留的长账号结果')
    store.stopEvents()
  })

  it('does not overlap slow polls and stops polling removed accounts or a stopped store', async () => {
    vi.useFakeTimers()
    const first = 'qq-111111111'
    const second = 'qq-222222222'
    const slow = deferred<NotificationInbox>()
    const counts = new Map<string, number>()
    const loadNotifications = vi.fn(async (accountId: string) => {
      const count = (counts.get(accountId) ?? 0) + 1
      counts.set(accountId, count)
      if (accountId === first && count === 2) return slow.promise
      return {
        accountId,
        items: [requestNotification(accountId)],
        limitations: { friendHistory: '仅观察事件' },
        refreshedAt: Date.now(),
      }
    })
    const adapter = {
      loadCachedNotifications: async () => [],
      loadNotifications,
      cacheNotifications: vi.fn().mockResolvedValue(undefined),
      subscribe: () => () => undefined,
    } as unknown as WorkspaceAdapter
    const store = useQqDirectoryStore()
    store.startEvents(adapter)
    await store.primeNotifications([first, second])
    expect(counts).toEqual(new Map([[first, 1], [second, 1]]))

    await vi.advanceTimersByTimeAsync(30_000)
    expect(counts).toEqual(new Map([[first, 2], [second, 2]]))
    await vi.advanceTimersByTimeAsync(30_000)
    expect(counts).toEqual(new Map([[first, 2], [second, 3]]))

    await store.primeNotifications([first])
    await vi.advanceTimersByTimeAsync(30_000)
    expect(counts).toEqual(new Map([[first, 2], [second, 3]]))
    slow.resolve({
      accountId: first,
      items: [requestNotification(first)],
      limitations: { friendHistory: '仅观察事件' },
      refreshedAt: Date.now(),
    })
    await Promise.resolve()
    store.stopEvents()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(counts).toEqual(new Map([[first, 2], [second, 3]]))
  })
})
