import 'fake-indexeddb/auto'

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { workspaceCache } from '../services/database'
import * as historyService from '../services/history-backfill'
import { useQqDirectoryStore } from '../stores/qq-directory'
import type { Account, Conversation } from '../types/workspace'
import SettingsView from './SettingsView.vue'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => (resolve = done))
  return { promise, resolve }
}

function account(id: string): Account {
  return {
    id,
    botId: id.slice(3),
    name: id,
    shortName: id,
    avatar: '',
    status: 'online',
    unread: 0,
    role: 'bot',
    accent: 'cyan',
  }
}

function conversation(owner: Account, peerId: string): Conversation {
  return {
    id: `${owner.id}:group:${peerId}`,
    accountId: owner.id,
    type: 'group',
    peerId,
    name: `${owner.name} 群聊`,
    avatar: '',
    lastMessage: '',
    lastMessageAt: '',
    unread: 0,
    pinned: false,
    muted: false,
  }
}

function progress(cancelled = false): historyService.HistoryBackfillProgress {
  return {
    completedConversations: cancelled ? 0 : 1,
    totalConversations: 1,
    fetchedMessages: 1,
    coveredMessages: 1,
    failedConversations: 0,
    truncatedConversations: 0,
    truncations: [],
    cancelled,
  }
}

afterEach(() => vi.restoreAllMocks())

describe('SettingsView', () => {
  it('offers system theme and clears every account cache plus in-memory notification projections', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const first = account('qq-111111111')
    const store = useQqDirectoryStore()
    store.notificationInboxes[first.id] = {
      accountId: first.id,
      items: [],
      limitations: { friendHistory: '仅观察事件' },
      refreshedAt: 0,
    }
    vi.spyOn(workspaceCache, 'statistics').mockResolvedValue({
      conversationCount: 0,
      messageCount: 0,
      eventCount: 0,
      notificationCount: 0,
      draftCount: 0,
      estimatedUsage: 0,
      estimatedQuota: 0,
    })
    const clearAll = vi.spyOn(workspaceCache, 'clearAll').mockResolvedValue(undefined)
    const wrapper = mount(SettingsView, {
      props: { account: first, conversations: [conversation(first, '345678901')], theme: 'light' },
      global: { plugins: [pinia] },
    })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text().includes('跟随系统'))!.trigger('click')
    expect(wrapper.emitted('setTheme')?.at(-1)).toEqual(['system'])
    await wrapper.findAll('button').find((button) => button.text().includes('清理全部账号'))!.trigger('click')
    await wrapper.findAll('.confirm-strip button').find((button) => button.text().includes('确认清理'))!.trigger('click')
    await flushPromises()

    expect(clearAll).toHaveBeenCalledOnce()
    expect(store.notificationInboxes).toEqual({})
  })

  it('does not let an aborted old backfill clear or cancel a newer account run', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const first = account('qq-111111111')
    const second = account('qq-222222222')
    const firstRun = deferred<historyService.HistoryBackfillProgress>()
    const secondRun = deferred<historyService.HistoryBackfillProgress>()
    const signals: AbortSignal[] = []
    vi.spyOn(workspaceCache, 'statistics').mockResolvedValue({
      conversationCount: 1,
      messageCount: 0,
      eventCount: 0,
      notificationCount: 0,
      draftCount: 0,
      estimatedUsage: 0,
      estimatedQuota: 0,
    })
    vi.spyOn(historyService, 'backfillHistory')
      .mockImplementationOnce(async (_items, _start, _end, signal) => {
        signals.push(signal)
        return firstRun.promise
      })
      .mockImplementationOnce(async (_items, _start, _end, signal) => {
        signals.push(signal)
        return secondRun.promise
      })
    const wrapper = mount(SettingsView, {
      props: {
        account: first,
        conversations: [conversation(first, '345678901'), conversation(second, '456789012')],
        theme: 'system',
      },
      global: { plugins: [pinia] },
    })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('开始补齐'))!.trigger('click')
    await flushPromises()
    expect(signals[0]?.aborted).toBe(false)

    await wrapper.setProps({ account: second })
    await flushPromises()
    expect(signals[0]?.aborted).toBe(true)
    await wrapper.findAll('button').find((button) => button.text().includes('开始补齐'))!.trigger('click')
    await flushPromises()
    firstRun.resolve(progress(true))
    await flushPromises()

    const cancel = wrapper.findAll('button').find((button) => button.text().trim() === '中止')
    expect(cancel).toBeDefined()
    await cancel!.trigger('click')
    expect(signals[1]?.aborted).toBe(true)
    secondRun.resolve(progress(true))
    await flushPromises()
  })

  it('reports a partial history backfill as incomplete when any conversation fails', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const owner = account('qq-111111111')
    vi.spyOn(workspaceCache, 'statistics').mockResolvedValue({
      conversationCount: 2,
      messageCount: 1,
      eventCount: 0,
      notificationCount: 0,
      draftCount: 0,
      estimatedUsage: 0,
      estimatedQuota: 0,
    })
    vi.spyOn(historyService, 'backfillHistory').mockResolvedValue({
      ...progress(),
      completedConversations: 1,
      failedConversations: 1,
      totalConversations: 2,
    })
    const wrapper = mount(SettingsView, {
      props: {
        account: owner,
        conversations: [conversation(owner, '345678901'), conversation(owner, '345678902')],
        theme: 'system',
      },
      global: { plugins: [pinia] },
    })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('开始补齐'))!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('1 个会话读取失败，当前缓存并不完整')
  })
})
