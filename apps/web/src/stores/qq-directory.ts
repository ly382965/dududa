import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { workspaceAdapter, type WorkspaceAdapter } from '../services/workspace-adapter'
import type {
  AccountDirectory,
  GroupMemberDirectory,
  NotificationInbox,
  QqNotification,
  WorkspaceEvent,
} from '../types/workspace'

function memberKey(accountId: string, groupId: string): string {
  return `${accountId}:group:${groupId}`
}

function finalState(state: QqNotification['state']): boolean {
  return state === 'accepted' || state === 'rejected'
}

function mergeNotificationItem(current: QqNotification | undefined, incoming: QqNotification): QqNotification {
  if (!current) return { ...incoming }
  const preserveCurrentState =
    finalState(current.state) && !finalState(incoming.state) ||
    current.state === 'handled' && incoming.state === 'pending'
  const state = preserveCurrentState ? current.state : incoming.state
  return {
    ...current,
    ...incoming,
    occurredAt: incoming.occurredAt || current.occurredAt,
    userName: incoming.userName || current.userName,
    groupName: incoming.groupName || current.groupName,
    operatorName: incoming.operatorName || current.operatorName,
    comment: incoming.comment || current.comment,
    state,
    actionable: state === 'pending' && incoming.actionable,
  }
}

export function mergeNotificationItems(
  current: QqNotification[],
  incoming: QqNotification[],
  accountId: string,
): QqNotification[] {
  const merged = new Map(
    current
      .filter((item) => item.accountId === accountId)
      .map((item) => [item.id, { ...item }]),
  )
  for (const item of incoming) {
    if (item.accountId !== accountId) continue
    merged.set(item.id, mergeNotificationItem(merged.get(item.id), item))
  }
  return [...merged.values()]
    .sort((left, right) => right.occurredAt - left.occurredAt || left.id.localeCompare(right.id))
    .slice(0, 500)
}

function observedInbox(accountId: string, items: QqNotification[] = []): NotificationInbox {
  return {
    accountId,
    items,
    limitations: {
      friendHistory: 'NapCat 无法回填普通好友申请；此处保留浏览器已观察到的真实事件。',
      groupHistory: '群申请历史来自 NapCat 系统消息，其他群事件从当前浏览器首次观察开始保留。',
    },
    refreshedAt: 0,
  }
}

export const useQqDirectoryStore = defineStore('qq-directory', () => {
  const directories = ref<Record<string, AccountDirectory>>({})
  const notificationInboxes = ref<Record<string, NotificationInbox>>({})
  const memberDirectories = ref<Record<string, GroupMemberDirectory>>({})
  const loading = ref<Record<string, boolean>>({})
  const errors = ref<Record<string, string>>({})
  const resourceVersions = ref<Record<string, number>>({})
  const requestVersions = new Map<string, number>()
  const primedNotificationAccounts = new Set<string>()
  const primingNotificationAccounts = new Set<string>()
  const activeNotificationAccounts = new Set<string>()
  let unsubscribe: (() => void) | undefined
  let notificationPollTimer: ReturnType<typeof setInterval> | undefined
  let adapter: WorkspaceAdapter = workspaceAdapter

  const pendingNotificationCount = computed(() =>
    Object.values(notificationInboxes.value).reduce(
      (total, inbox) => total + inbox.items.filter((item) => item.state === 'pending' && item.actionable).length,
      0,
    ),
  )

  function nextVersion(key: string): number {
    const version = (requestVersions.get(key) ?? 0) + 1
    requestVersions.set(key, version)
    return version
  }

  function current(key: string, version: number): boolean {
    return requestVersions.get(key) === version
  }

  function startEvents(nextAdapter: WorkspaceAdapter = workspaceAdapter): void {
    adapter = nextAdapter
    if (!unsubscribe) unsubscribe = adapter.subscribe(handleEvent)
    if (!notificationPollTimer) {
      notificationPollTimer = setInterval(() => {
        for (const accountId of activeNotificationAccounts) {
          const key = `notifications:${accountId}`
          const inbox = notificationInboxes.value[accountId]
          if (!loading.value[key] && (!inbox || inbox.items.some((item) => item.state === 'pending'))) {
            void loadNotifications(accountId, true)
          }
        }
      }, 30_000)
    }
  }

  function stopEvents(): void {
    unsubscribe?.()
    unsubscribe = undefined
    clearInterval(notificationPollTimer)
    notificationPollTimer = undefined
  }

  async function loadDirectory(accountId: string, refresh = false): Promise<AccountDirectory | undefined> {
    if (!refresh && directories.value[accountId]) return directories.value[accountId]
    const key = `directory:${accountId}`
    const version = nextVersion(key)
    loading.value[key] = true
    errors.value[key] = ''
    try {
      const directory = await adapter.loadDirectory(accountId, refresh)
      if (current(key, version) && directory.accountId === accountId) directories.value[accountId] = directory
      return current(key, version) ? directory : undefined
    } catch (cause) {
      if (current(key, version)) errors.value[key] = cause instanceof Error ? cause.message : '无法加载联系人'
      return undefined
    } finally {
      if (current(key, version)) loading.value[key] = false
    }
  }

  async function loadNotifications(accountId: string, refresh = false): Promise<NotificationInbox | undefined> {
    if (!refresh && notificationInboxes.value[accountId]) return notificationInboxes.value[accountId]
    const key = `notifications:${accountId}`
    const version = nextVersion(key)
    loading.value[key] = true
    errors.value[key] = ''
    try {
      const cached = (await adapter.loadCachedNotifications?.(accountId) ?? []).map((item) => ({
        ...item,
        // A persisted request is historical evidence, not a live NapCat receipt.
        actionable: false,
        actionReason:
          item.state === 'pending'
            ? '仅为浏览器已观察记录，需由当前 NapCat 会话重新确认'
            : item.actionReason,
      }))
      if (current(key, version) && cached.length) {
        const existing = notificationInboxes.value[accountId]
        notificationInboxes.value[accountId] = {
          ...(existing ?? observedInbox(accountId)),
          items: mergeNotificationItems(existing?.items ?? [], cached, accountId),
        }
      }
      const inbox = await adapter.loadNotifications(accountId, refresh)
      if (!current(key, version) || inbox.accountId !== accountId) return undefined
      const merged = {
        ...inbox,
        items: mergeNotificationItems(notificationInboxes.value[accountId]?.items ?? cached, inbox.items, accountId),
      }
      notificationInboxes.value[accountId] = merged
      void adapter.cacheNotifications?.(accountId, merged.items).catch(() => undefined)
      return merged
    } catch (cause) {
      if (current(key, version)) errors.value[key] = cause instanceof Error ? cause.message : '无法加载通知'
      return undefined
    } finally {
      if (current(key, version)) loading.value[key] = false
    }
  }

  async function loadMembers(
    accountId: string,
    groupId: string,
    refresh = false,
  ): Promise<GroupMemberDirectory | undefined> {
    const cacheKey = memberKey(accountId, groupId)
    if (!refresh && memberDirectories.value[cacheKey]) return memberDirectories.value[cacheKey]
    const key = `members:${cacheKey}`
    const version = nextVersion(key)
    loading.value[key] = true
    errors.value[key] = ''
    try {
      const directory = await adapter.loadGroupMembers(accountId, groupId, refresh)
      if (
        current(key, version) &&
        directory.accountId === accountId &&
        directory.groupId === groupId
      ) {
        memberDirectories.value[cacheKey] = directory
      }
      return current(key, version) ? directory : undefined
    } catch (cause) {
      if (current(key, version)) errors.value[key] = cause instanceof Error ? cause.message : '无法加载群成员'
      return undefined
    } finally {
      if (current(key, version)) loading.value[key] = false
    }
  }

  async function resolveNotification(
    accountId: string,
    notificationId: string,
    action: 'accept' | 'reject',
  ): Promise<void> {
    const notification = await adapter.resolveNotification(accountId, notificationId, action)
    if (notification.accountId !== accountId || notification.id !== notificationId) {
      throw new Error('NapCat 返回了不匹配的通知处理结果')
    }
    mergeNotification(notification)
    if (action === 'accept') await loadDirectory(accountId, true)
  }

  async function setAdmin(accountId: string, groupId: string, userId: string, enabled: boolean): Promise<void> {
    await adapter.setGroupAdmin(accountId, groupId, userId, enabled)
    await loadMembers(accountId, groupId, true)
  }

  async function kickMember(accountId: string, groupId: string, userId: string): Promise<void> {
    await adapter.kickGroupMember(accountId, groupId, userId)
    await loadMembers(accountId, groupId, true)
    await loadDirectory(accountId, true)
  }

  async function setCard(accountId: string, groupId: string, userId: string, card: string): Promise<void> {
    await adapter.setGroupCard(accountId, groupId, userId, card)
    await loadMembers(accountId, groupId, true)
  }

  async function renameGroup(accountId: string, groupId: string, name: string): Promise<void> {
    await adapter.renameGroup(accountId, groupId, name)
    await loadDirectory(accountId, true)
  }

  async function setMuteAll(accountId: string, groupId: string, enabled: boolean): Promise<void> {
    await adapter.setGroupMuteAll(accountId, groupId, enabled)
    await loadDirectory(accountId, true)
  }

  async function quitGroup(accountId: string, groupId: string): Promise<void> {
    await adapter.quitGroup(accountId, groupId)
    delete memberDirectories.value[memberKey(accountId, groupId)]
    await loadDirectory(accountId, true)
  }

  function mergeNotification(notification: QqNotification): void {
    const inbox = notificationInboxes.value[notification.accountId] ?? observedInbox(notification.accountId)
    inbox.items = mergeNotificationItems(inbox.items, [notification], notification.accountId)
    notificationInboxes.value[notification.accountId] = inbox
    void adapter.cacheNotifications?.(notification.accountId, inbox.items).catch(() => undefined)
  }

  function handleEvent(event: WorkspaceEvent): void {
    if (event.type === 'notification.changed') {
      if (event.notification.accountId !== event.accountId) return
      const key = `notifications:${event.accountId}`
      nextVersion(key)
      delete loading.value[key]
      delete errors.value[key]
      mergeNotification(event.notification)
      return
    }
    if (event.type === 'directory.changed' && directories.value[event.accountId]) {
      void loadDirectory(event.accountId, true)
      return
    }
    if (event.type === 'group.members.changed') {
      const key = memberKey(event.accountId, event.groupId)
      if (memberDirectories.value[key]) void loadMembers(event.accountId, event.groupId, true)
      return
    }
    if (event.type === 'group.resources.changed') {
      const key = `${event.accountId}:${event.groupId}:${event.resource}`
      resourceVersions.value[key] = (resourceVersions.value[key] ?? 0) + 1
    }
  }

  async function primeNotifications(accountIds: string[]): Promise<void> {
    activeNotificationAccounts.clear()
    accountIds.forEach((accountId) => activeNotificationAccounts.add(accountId))
    const pending = accountIds.flatMap((accountId) => {
      if (primedNotificationAccounts.has(accountId) || primingNotificationAccounts.has(accountId)) return []
      primingNotificationAccounts.add(accountId)
      return [
        loadNotifications(accountId, true).then((inbox) => {
          if (inbox) primedNotificationAccounts.add(accountId)
          else primedNotificationAccounts.delete(accountId)
        }).finally(() => primingNotificationAccounts.delete(accountId)),
      ]
    })
    await Promise.allSettled(pending)
  }

  function invalidateAccountRequests(accountId: string, prefix?: string): void {
    for (const [key, version] of requestVersions) {
      const belongsToAccount =
        key === `directory:${accountId}` ||
        key === `notifications:${accountId}` ||
        key.startsWith(`members:${accountId}:group:`)
      if (belongsToAccount && (!prefix || key.startsWith(prefix))) requestVersions.set(key, version + 1)
    }
  }

  function clearRequestStatus(accountId: string, prefix?: string): void {
    for (const key of new Set([...Object.keys(loading.value), ...Object.keys(errors.value)])) {
      const belongsToAccount =
        key === `directory:${accountId}` ||
        key === `notifications:${accountId}` ||
        key.startsWith(`members:${accountId}:group:`)
      if (belongsToAccount && (!prefix || key.startsWith(prefix))) {
        delete loading.value[key]
        delete errors.value[key]
      }
    }
  }

  function clearAccountState(accountId: string): void {
    invalidateAccountRequests(accountId)
    clearRequestStatus(accountId)
    delete directories.value[accountId]
    delete notificationInboxes.value[accountId]
    for (const key of Object.keys(memberDirectories.value)) {
      if (key.startsWith(`${accountId}:group:`)) delete memberDirectories.value[key]
    }
    primedNotificationAccounts.delete(accountId)
    primingNotificationAccounts.delete(accountId)
  }

  function clearBeforeState(accountId: string, cutoff: number, conversationId?: string): void {
    if (conversationId) return
    invalidateAccountRequests(accountId, 'notifications:')
    clearRequestStatus(accountId, 'notifications:')
    const inbox = notificationInboxes.value[accountId]
    if (inbox) {
      inbox.items = inbox.items.filter((item) => !item.occurredAt || item.occurredAt >= cutoff)
      notificationInboxes.value[accountId] = { ...inbox, items: [...inbox.items] }
    }
    primedNotificationAccounts.delete(accountId)
    primingNotificationAccounts.delete(accountId)
  }

  function clearAllState(): void {
    for (const [key, version] of requestVersions) requestVersions.set(key, version + 1)
    directories.value = {}
    notificationInboxes.value = {}
    memberDirectories.value = {}
    resourceVersions.value = {}
    loading.value = {}
    errors.value = {}
    primedNotificationAccounts.clear()
    primingNotificationAccounts.clear()
  }

  return {
    directories,
    notificationInboxes,
    memberDirectories,
    loading,
    errors,
    resourceVersions,
    pendingNotificationCount,
    startEvents,
    stopEvents,
    loadDirectory,
    loadNotifications,
    primeNotifications,
    loadMembers,
    resolveNotification,
    setAdmin,
    kickMember,
    setCard,
    renameGroup,
    setMuteAll,
    quitGroup,
    clearAccountState,
    clearBeforeState,
    clearAllState,
  }
})

export { memberKey as groupMemberDirectoryKey }
