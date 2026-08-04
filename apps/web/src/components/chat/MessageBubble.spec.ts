import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { Account, ChatMessage, Conversation } from '../../types/workspace'
import MessageBubble from './MessageBubble.vue'

const conversation: Conversation = {
  id: 'qq-123456789:group:345678901',
  accountId: 'qq-123456789',
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

const account = {
  capabilities: Object.fromEntries(
    ['message.recall', 'message.forward', 'message.nudge', 'message.download.file'].map((name) => [
      name,
      { status: 'supported' },
    ]),
  ) as Account['capabilities'],
} as Account

function message(): ChatMessage {
  return {
    id: `${conversation.id}:101`,
    accountId: conversation.accountId,
    conversationId: conversation.id,
    messageId: '101',
    messageSeq: '101',
    senderId: '234567890',
    senderName: '真实成员',
    senderAvatar: '',
    timestamp: '12:00',
    timestampMs: Date.now(),
    content: '@成员 https://example.com',
    segments: [
      { type: 'mention', userId: '234567890', label: '成员', all: false },
      { type: 'text', text: ' https://example.com' },
    ],
    mine: false,
  }
}

describe('MessageBubble', () => {
  it('linkifies text without turning a mention click into a QQ nudge', async () => {
    const wrapper = mount(MessageBubble, { props: { message: message(), conversation, account } })

    await wrapper.get('.mention-segment').trigger('click')
    expect(wrapper.emitted('nudge')).toBeUndefined()
    expect(wrapper.get('a[href="https://example.com"]').attributes('rel')).toContain('noopener')
  })

  it('opens actions by context menu and supports swipe-to-reply', async () => {
    const wrapper = mount(MessageBubble, { props: { message: message(), conversation, account } })
    const row = wrapper.get('.message-row')

    await row.trigger('contextmenu')
    expect(wrapper.find('.message-menu-popover').exists()).toBe(true)

    await row.trigger('touchstart', { touches: [{ clientX: 0, clientY: 20 }] })
    await row.trigger('touchmove', { touches: [{ clientX: 70, clientY: 22 }] })
    await row.trigger('touchend')
    expect(wrapper.emitted('reply')).toHaveLength(1)
  })
})
