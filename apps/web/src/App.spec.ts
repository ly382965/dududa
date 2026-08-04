import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App.vue'
import type { ChatMessage, WorkspaceSnapshot } from './types/workspace'

class FakeEventSource {
  addEventListener() {}
  close() {}
}

const account = {
  id: 'qq-123456789',
  botId: '123456789',
  name: '真实机器人',
  shortName: '真实机器人',
  avatar: '/api/media/avatar/user/123456789',
  status: 'online' as const,
  unread: 0,
  role: 'bot' as const,
  accent: 'cyan' as const,
}

const conversations = [
  {
    id: 'qq-123456789:group:345678901',
    accountId: account.id,
    type: 'group' as const,
    peerId: '345678901',
    name: '真实测试群',
    avatar: '/api/media/avatar/group/345678901',
    lastMessage: '成员：来自 NapCat 的消息',
    lastMessageAt: '18:10',
    unread: 0,
    pinned: false,
    muted: false,
    members: 42,
    updatedAt: 1_785_742_400,
  },
  {
    id: 'qq-123456789:private:456789012',
    accountId: account.id,
    type: 'private' as const,
    peerId: '456789012',
    name: '真实好友',
    avatar: '/api/media/avatar/user/456789012',
    lastMessage: '好友消息',
    lastMessageAt: '17:30',
    unread: 0,
    pinned: false,
    muted: false,
    updatedAt: 1_785_740_000,
  },
]

const historyMessage: ChatMessage = {
  id: 'qq-123456789:group:345678901:101',
  accountId: account.id,
  conversationId: conversations[0]!.id,
  messageId: '101',
  messageSeq: '101',
  senderId: '234567890',
  senderName: '测试成员',
  senderAvatar: '/api/media/avatar/user/234567890',
  timestamp: '18:10',
  timestampMs: 1_785_742_400_000,
  content: '来自真实 NapCat 的消息',
  segments: [{ type: 'text', text: '来自真实 NapCat 的消息' }],
  mine: false,
}

function workspace(accounts = [account]): WorkspaceSnapshot {
  return {
    runtime: {
      status: accounts.length ? 'connected' : 'waiting',
      message: accounts.length ? '1 个 NapCat 账号在线' : '等待 NapCat 反向 WebSocket 连接',
      reverseWebSocketPath: '/onebot/v11/ws',
    },
    accounts,
    conversations: accounts.length ? conversations : [],
    messages: {},
    sessions: [],
    agentMessages: {},
    runs: [],
    configs: {},
  }
}

function mockApi(snapshot = workspace()) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.startsWith('/api/workspace')) return new Response(JSON.stringify(snapshot), { status: 200 })
    if (path.includes('/messages') && init?.method === 'POST') {
      const content = JSON.parse(String(init.body)) as { content: string }
      return new Response(
        JSON.stringify({
          message: {
            ...historyMessage,
            id: 'qq-123456789:group:345678901:102',
            messageId: '102',
            messageSeq: '102',
            senderId: account.botId,
            senderName: account.name,
            senderAvatar: account.avatar,
            content: content.content,
            segments: [{ type: 'text', text: content.content }],
            mine: true,
          },
        }),
        { status: 201 },
      )
    }
    if (path.includes('/messages')) {
      return new Response(
        JSON.stringify({ messages: [historyMessage], hasMoreBefore: false, hasMoreAfter: false }),
        { status: 200 },
      )
    }
    if (path.endsWith('/read')) return new Response(JSON.stringify({ ok: true }), { status: 200 })
    return new Response(JSON.stringify({ error: 'not found' }), { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function mountApp() {
  const wrapper = mount(App)
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('Dududa NapCat workspace', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.stubGlobal('EventSource', FakeEventSource)
  })

  it('shows the NapCat connection state when no account is online', async () => {
    mockApi(workspace([]))
    const wrapper = await mountApp()

    expect(wrapper.find('.connection-screen').exists()).toBe(true)
    expect(wrapper.text()).toContain('等待 QQ 账号接入')
    expect(wrapper.text()).toContain('/onebot/v11/ws')
  })

  it('renders accounts and conversations returned by the real API adapter', async () => {
    mockApi()
    const wrapper = await mountApp()

    expect(wrapper.find('.account-rail').exists()).toBe(true)
    expect(wrapper.find('.conversation-sidebar').exists()).toBe(true)
    expect(wrapper.find('.chat-pane').exists()).toBe(true)
    expect(wrapper.text()).toContain('真实测试群')
    expect(wrapper.text()).toContain('来自真实 NapCat 的消息')
    expect(wrapper.text()).toContain('NapCat 实时连接')
  })

  it('filters the real conversation list', async () => {
    mockApi()
    const wrapper = await mountApp()
    const search = wrapper.get('input[aria-label="搜索会话或消息"]')

    await search.setValue('好友消息')

    const items = wrapper.findAll('.conversation-item')
    expect(items).toHaveLength(1)
    expect(items[0]?.text()).toContain('真实好友')
  })

  it('sends QQ text through the gateway instead of adding a local-only message', async () => {
    const fetchMock = mockApi()
    const wrapper = await mountApp()
    const composer = wrapper.get('textarea[aria-label="QQ 消息输入"]')

    await composer.setValue('真实发送测试')
    await composer.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/messages'),
      expect.objectContaining({ method: 'POST' }),
    )
    expect(wrapper.get('.message-list').text()).toContain('真实发送测试')
  })
})
