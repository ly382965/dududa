import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { serializeComposerDraft } from '../services/composer-content'
import type { Account, Conversation } from '../types/workspace'
import ConversationSidebar from './ConversationSidebar.vue'

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
    capabilities: {} as Account['capabilities'],
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
    lastMessage: '最后一条真实 QQ 消息',
    lastMessageAt: '12:00',
    unread: 0,
    pinned: false,
    muted: false,
  }
}

describe('ConversationSidebar drafts', () => {
  it('shows Mew-style draft markers only on their account-scoped conversations', async () => {
    const firstAccount = account('qq-111111111')
    const secondAccount = account('qq-222222222')
    const first = conversation(firstAccount, '345678901')
    const second = conversation(secondAccount, '345678901')
    const richMentionDraft = serializeComposerDraft({
      type: 'doc',
      content: [{
        type: 'paragraph',
        content: [{ type: 'qqMention', attrs: { userId: '123456789', label: '真实成员' } }],
      }],
    })
    const wrapper = mount(ConversationSidebar, {
      props: {
        accounts: [firstAccount, secondAccount],
        conversations: [first, second],
        drafts: { [first.id]: richMentionDraft },
        selectedConversationId: first.id,
        selectedAccountId: 'all',
        searchQuery: '',
        unreadOnly: false,
        onlineCount: 2,
      },
    })

    expect(wrapper.findAll('.conversation-item')[0]?.find('.draft-label').text()).toBe('草稿')
    expect(wrapper.findAll('.conversation-item')[1]?.find('.draft-label').exists()).toBe(false)

    await wrapper.setProps({ drafts: { [second.id]: '二号账号草稿' } })
    expect(wrapper.findAll('.conversation-item')[0]?.find('.draft-label').exists()).toBe(false)
    expect(wrapper.findAll('.conversation-item')[1]?.find('.draft-label').text()).toBe('草稿')
  })
})
