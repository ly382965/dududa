import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'

import { useQqDirectoryStore } from '../stores/qq-directory'
import type { Account, NotificationInbox } from '../types/workspace'
import NotificationsView from './NotificationsView.vue'

const account: Account = {
  id: 'qq-123456789',
  botId: '123456789',
  name: '真实账号',
  shortName: '真实账号',
  avatar: '',
  status: 'online',
  unread: 0,
  role: 'bot',
  accent: 'cyan',
}

function inbox(): NotificationInbox {
  return {
    accountId: account.id,
    items: [
      {
        id: 'request-1',
        accountId: account.id,
        kind: 'friend-request',
        occurredAt: Date.now(),
        userId: '456789012',
        state: 'pending',
        actionable: true,
      },
    ],
    limitations: { friendHistory: '仅保留已观察事件' },
    refreshedAt: Date.now(),
  }
}

describe('NotificationsView', () => {
  it('renders the current account pending request and refreshes when mounted', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useQqDirectoryStore()
    store.notificationInboxes[account.id] = inbox()
    const load = vi.spyOn(store, 'loadNotifications').mockResolvedValue(store.notificationInboxes[account.id])
    const wrapper = mount(NotificationsView, { props: { account }, global: { plugins: [pinia] } })
    await Promise.resolve()
    expect(load).toHaveBeenCalledWith(account.id, true)
    expect(wrapper.text()).toContain('待处理')
    wrapper.unmount()
  })
})
