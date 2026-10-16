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
  it('distinguishes an uncaptured forward from a saved original and includes its source when opening', async () => {
    const original: ChatMessage = { ...message(), status: 'recalled', segments: [{ type: 'forward', forwardId: 'bundle' }],
      recall: { recalledAt: Date.now(), retained: true, expiresAt: Date.now() + 60_000 } }
    const wrapper = mount(MessageBubble, { props: { message: original, conversation, account } })
    expect(wrapper.text()).toContain('已撤回 · 转发内容未完整保存')
    expect(wrapper.text()).not.toContain('原文已保留')
    await wrapper.get('.forward-segment').trigger('click')
    expect(wrapper.emitted('openForward')?.[0]).toEqual([original.segments[0], original])
    await wrapper.setProps({ message: { ...original, segments: [{ type: 'forward', forwardId: 'bundle', messages: [message()] }] } })
    expect(wrapper.text()).toContain('已撤回 · 原文已保留')
    wrapper.unmount()
  })

  it('displays retained originals with a recall label and hides expired originals', async () => {
    const recalled: ChatMessage = { ...message(), status: 'recalled', recall: {
      recalledAt: Date.now(), retained: true, expiresAt: Date.now() + 60_000,
    } }
    const wrapper = mount(MessageBubble, { props: { message: recalled, conversation, account } })
    expect(wrapper.text()).toContain('已撤回 · 原文已保留')
    expect(wrapper.find('a[href="https://example.com"]').exists()).toBe(true)
    await wrapper.setProps({ message: { ...recalled, recall: { ...recalled.recall!, expiresAt: Date.now() - 1 } } })
    expect(wrapper.text()).toContain('此消息已撤回')
    expect(wrapper.find('a[href="https://example.com"]').exists()).toBe(false)
    wrapper.unmount()
  })

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
