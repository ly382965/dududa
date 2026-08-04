import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

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

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => (resolve = done))
  return { promise, resolve }
}

describe('useWorkspace account-scoped state', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
  })
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

  it('retains the system theme preference while following color-scheme changes', async () => {
    let dark = true
    const listeners = new Set<(event: MediaQueryListEvent) => void>()
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      matches: dark,
      media: '(prefers-color-scheme: dark)',
      onchange: null,
      addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
      removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener),
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => true,
    })))
    window.localStorage.setItem('dududa-theme', 'system')
    const adapter = {
      load: async () => ({
        runtime: { status: 'waiting', message: 'waiting', reverseWebSocketPath: '/onebot/v11/ws' },
        accounts: [],
        conversations: [],
        messages: {},
        sessions: [],
        agentMessages: {},
        runs: [],
        configs: {},
      }),
      subscribe: () => () => undefined,
    } as unknown as WorkspaceAdapter
    let workspace!: ReturnType<typeof useWorkspace>
    const wrapper = mount(defineComponent({
      setup() {
        workspace = useWorkspace(adapter)
        return () => h('div')
      },
    }))
    await flushPromises()

    expect(workspace.theme.value).toBe('system')
    expect(workspace.resolvedTheme.value).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    dark = false
    listeners.forEach((listener) => listener({ matches: dark } as MediaQueryListEvent))
    await flushPromises()
    expect(workspace.theme.value).toBe('system')
    expect(workspace.resolvedTheme.value).toBe('light')
    expect(window.localStorage.getItem('dududa-theme')).toBe('system')
    wrapper.unmount()
  })

  it('persists a group chat-file guard before the request finishes and clears it only on success', async () => {
    const owner = account('qq-111111111')
    const target = conversation(owner, '345678901')
    const snapshot: WorkspaceSnapshot = {
      runtime: { status: 'connected', message: 'connected', reverseWebSocketPath: '/onebot/v11/ws' },
      accounts: [owner],
      conversations: [target],
      messages: {},
      sessions: [],
      agentMessages: {},
      runs: [],
      configs: {},
    }
    const pending = deferred<{ kind: 'file'; name: string; size: number }>()
    const sendFile = vi.fn()
      .mockImplementationOnce(async () => pending.promise)
      .mockResolvedValue({ kind: 'file', name: '真实文件.txt', size: 10 })
    const adapter = {
      load: async () => snapshot,
      loadCachedMessages: async () => [],
      loadHistory: async () => ({ messages: [], hasMoreBefore: false, hasMoreAfter: false }),
      loadDraft: async () => undefined,
      markRead: async () => undefined,
      sendFile,
      subscribe: () => () => undefined,
    } as unknown as WorkspaceAdapter
    let firstWorkspace!: ReturnType<typeof useWorkspace>
    const firstHost = mount(defineComponent({
      setup() {
        firstWorkspace = useWorkspace(adapter)
        return () => h('div')
      },
    }))
    await flushPromises()
    const firstFile = new File(['real bytes'], '真实文件.txt', { type: 'text/plain' })
    const firstSend = firstWorkspace.sendFiles([firstFile])
    await vi.waitFor(() => expect(sendFile).toHaveBeenCalledTimes(1))
    firstHost.unmount()

    let secondWorkspace!: ReturnType<typeof useWorkspace>
    const secondHost = mount(defineComponent({
      setup() {
        secondWorkspace = useWorkspace(adapter)
        return () => h('div')
      },
    }))
    await flushPromises()
    await expect(secondWorkspace.sendFiles([
      new File(['real bytes'], '真实文件.txt', { type: 'text/plain' }),
    ])).resolves.toBe(false)
    expect(sendFile).toHaveBeenCalledTimes(1)

    pending.resolve({ kind: 'file', name: '真实文件.txt', size: 10 })
    await expect(firstSend).resolves.toBe(true)
    await expect(secondWorkspace.sendFiles([
      new File(['real bytes'], '真实文件.txt', { type: 'text/plain' }),
    ])).resolves.toBe(true)
    expect(sendFile).toHaveBeenCalledTimes(2)
    secondHost.unmount()
  })
})
