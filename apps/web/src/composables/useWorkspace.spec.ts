import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import type { WorkspaceAdapter } from '../services/workspace-adapter'
import type { Account, ChatMessage, Conversation, HistoryPage, WorkspaceEvent, WorkspaceSnapshot } from '../types/workspace'
import { useWorkspace } from './useWorkspace'

function account(id: string): Account {
  const botId = id.slice(3)
  return {
    id,
    botId,
    name: id,
    shortName: id,
    avatar: '',
    status: 'online',
    unread: 0,
    role: 'bot',
    accent: 'cyan',
    capabilities: Object.fromEntries(
      [
        'history.cursor',
        'message.read',
        'message.send.text',
        'message.send.reply',
        'message.send.mention',
        'message.send.face',
        'message.send.image',
        'message.send.audio',
        'message.send.video',
        'message.send.file',
      ].map((name) => [name, { status: 'supported' }]),
    ) as Account['capabilities'],
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

function message(target: Conversation): ChatMessage {
  return {
    id: `${target.id}:101`,
    accountId: target.accountId,
    conversationId: target.id,
    messageId: '101',
    messageSeq: '101',
    senderId: '234567890',
    senderName: '真实成员',
    senderAvatar: '',
    timestamp: '12:00',
    timestampMs: 10_000,
    content: '真实消息',
    segments: [{ type: 'text', text: '真实消息' }],
    mine: false,
  }
}

describe('useWorkspace account-scoped state', () => {
  it('loads the initially selected history once and deletes recalled cache data', async () => {
    const first = account('qq-111111111')
    const second = account('qq-222222222')
    const firstConversation = conversation(first, '345678901')
    const secondConversation = conversation(second, '456789012')
    const historyMessage = message(firstConversation)
    const snapshot: WorkspaceSnapshot = {
      runtime: { status: 'connected', message: 'connected', reverseWebSocketPath: '/onebot/v11/ws' },
      accounts: [first, second],
      capabilities: {},
      conversations: [firstConversation, secondConversation],
      messages: {},
      sessions: [],
      agentMessages: {},
      runs: [],
      configs: {},
    }
    const page: HistoryPage = {
      messages: [historyMessage],
      beforeCursor: 'before',
      afterCursor: 'after',
      hasMoreBefore: true,
      hasMoreAfter: false,
    }
    let eventHandler: ((event: WorkspaceEvent) => void) | undefined
    const adapter = {
      load: vi.fn(async () => snapshot),
      loadCachedMessages: vi.fn(async () => []),
      loadHistory: vi.fn(async () => page),
      loadDraft: vi.fn(async () => undefined),
      markRead: vi.fn(async () => undefined),
      saveDraft: vi.fn(async () => undefined),
      deleteCachedMessage: vi.fn(async () => undefined),
      cacheMessages: vi.fn(async () => undefined),
      subscribe: vi.fn((handler: (event: WorkspaceEvent) => void) => {
        eventHandler = handler
        return () => undefined
      }),
    } as unknown as WorkspaceAdapter
    let workspace!: ReturnType<typeof useWorkspace>
    const host = defineComponent({
      setup() {
        workspace = useWorkspace(adapter)
        return () => h('div')
      },
    })
    const wrapper = mount(host)
    await flushPromises()
    await flushPromises()

    expect(adapter.loadHistory).toHaveBeenCalledTimes(1)
    expect(adapter.markRead).toHaveBeenCalledTimes(1)

    const secondMessage = message(secondConversation)
    eventHandler?.({ type: 'message.created', conversation: secondConversation, message: secondMessage })
    expect(workspace.conversations.value.find((item) => item.id === secondConversation.id)?.unread).toBe(1)
    workspace.selectConversation(secondConversation.id)
    expect(workspace.chatUnread.value).toEqual({ messageId: secondMessage.id, count: 1 })
    workspace.updateChatDraft(firstConversation.id, '账号一草稿')
    await flushPromises()
    expect(adapter.saveDraft).toHaveBeenCalledWith(
      expect.objectContaining({ accountId: first.id, conversationId: firstConversation.id, content: '账号一草稿' }),
    )

    eventHandler?.({
      type: 'message.deleted',
      accountId: first.id,
      conversationId: firstConversation.id,
      messageId: historyMessage.id,
    })
    await flushPromises()
    expect(adapter.deleteCachedMessage).toHaveBeenCalledWith(first.id, firstConversation.id, historyMessage.id)
    expect(snapshot.messages[firstConversation.id]?.[0]).toMatchObject({ status: 'recalled', content: '此消息已撤回' })
    wrapper.unmount()
  })
})
