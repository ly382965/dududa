import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useQqDirectoryStore } from '../stores/qq-directory'
import type { Account } from '../types/workspace'
import ContactsView from './ContactsView.vue'

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

describe('ContactsView', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('searches real contacts by pinyin and emits account-scoped targets', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useQqDirectoryStore()
    store.directories[account.id] = {
      accountId: account.id,
      friends: [
        { accountId: account.id, userId: '456789012', nickname: '张三', remark: '', categoryName: '同学', avatar: '' },
        { accountId: account.id, userId: '567890123', nickname: '李四', remark: '', categoryName: '好友', avatar: '' },
      ],
      groups: [
        { accountId: account.id, groupId: '345678901', groupName: '科大开发群', remark: '', memberCount: 42, avatar: '' },
      ],
      refreshedAt: Date.now(),
    }
    const wrapper = mount(ContactsView, { props: { account }, global: { plugins: [pinia] } })

    await wrapper.get('input[aria-label="搜索联系人"]').setValue('zs')
    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).not.toContain('李四')
    await wrapper.get('.contact-main').trigger('click')
    expect(wrapper.emitted('openConversation')?.[0]).toEqual(['private', '456789012'])

    await wrapper.findAll('.segmented-control button')[1]!.trigger('click')
    await wrapper.get('input[aria-label="搜索联系人"]').setValue('kd')
    expect(wrapper.text()).toContain('科大开发群')
    await wrapper.get('.group-settings').trigger('click')
    expect(wrapper.emitted('openGroup')?.[0]).toEqual(['345678901'])
  })
})
