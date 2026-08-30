import 'fake-indexeddb/auto'

import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { WorkspaceCache, WorkspaceDatabase } from '../services/database'
import type { InternalTestAgentAdapter } from '../services/internal-test'
import type { WorkspaceAdapter } from '../services/workspace-adapter'
import type {
  InternalTestAgentCatalog,
  InternalTestAgentPolicy,
  InternalTestAgentRequest,
  InternalTestAgentResponse,
  InternalTestAgentScope,
  InternalTestAgentStatus,
} from '../types/internal-test'
import type {
  Account,
  ChatMessage,
  Conversation,
  HistoryPage,
  PermissionPart,
  ReplyDraftPart,
  WorkspaceEvent,
  WorkspaceSnapshot,
} from '../types/workspace'
import { useWorkspace } from './useWorkspace'

const databases: WorkspaceDatabase[] = []

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
        'message.custom_faces',
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
  afterEach(async () => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
    await Promise.all(databases.splice(0).map((database) => database.delete()))
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

  it('orders cached and history messages by timestamp, full-precision sequence, and identity', async () => {
    const owner = account('qq-111111111')
    const target = conversation(owner, '345678901')
    const snapshot: WorkspaceSnapshot = {
      runtime: { status: 'connected', message: 'connected', reverseWebSocketPath: '/onebot/v11/ws' },
      accounts: [owner],
      capabilities: {},
      conversations: [target],
      messages: {},
      sessions: [],
      agentMessages: {},
      runs: [],
      configs: {},
    }
    const newerWithoutSequence = {
      ...message(target),
      id: `${target.id}:newer-without-sequence`,
      messageId: 'newer-without-sequence',
      messageSeq: undefined,
      sequence: undefined,
      timestampMs: 20_000,
    }
    const olderWithoutSequence = {
      ...message(target),
      id: `${target.id}:older-without-sequence`,
      messageId: 'older-without-sequence',
      messageSeq: undefined,
      sequence: undefined,
      timestampMs: 5_000,
    }
    const lowerLargeSequence = {
      ...message(target),
      id: `${target.id}:large-sequence-low`,
      messageId: '9007199254740992',
      messageSeq: '9007199254740992',
      sequence: '9007199254740992',
      timestampMs: 10_000,
    }
    const higherLargeSequence = {
      ...message(target),
      id: `${target.id}:large-sequence-high`,
      messageId: '9007199254740993',
      messageSeq: '9007199254740993',
      sequence: '9007199254740993',
      timestampMs: 10_000,
    }
    const adapter = {
      load: vi.fn(async () => snapshot),
      loadCachedMessages: vi.fn(async () => [newerWithoutSequence, higherLargeSequence]),
      loadHistory: vi.fn(async () => ({
        messages: [olderWithoutSequence, lowerLargeSequence, { ...higherLargeSequence }],
        hasMoreBefore: false,
        hasMoreAfter: false,
      })),
      loadDraft: vi.fn(async () => undefined),
      markRead: vi.fn(async () => undefined),
      cacheMessages: vi.fn(async () => undefined),
      subscribe: vi.fn(() => () => undefined),
    } as unknown as WorkspaceAdapter
    let workspace!: ReturnType<typeof useWorkspace>
    const wrapper = mount(defineComponent({
      setup() {
        workspace = useWorkspace(adapter)
        return () => h('div')
      },
    }))
    await flushPromises()
    await flushPromises()

    expect(workspace.chatMessages.value.map((item) => item.id)).toEqual([
      olderWithoutSequence.id,
      lowerLargeSequence.id,
      higherLargeSequence.id,
      newerWithoutSequence.id,
    ])
    wrapper.unmount()
  })

  it('replays realtime messages received while the initial workspace snapshot is loading', async () => {
    const owner = account('qq-111111111')
    const existingConversation = conversation(owner, '345678901')
    const realtimeConversation = conversation(owner, '456789012')
    realtimeConversation.lastMessage = 'Snapshot 在途时收到的新消息'
    const realtimeMessage = {
      ...message(realtimeConversation),
      id: `${realtimeConversation.id}:202`,
      messageId: '202',
      messageSeq: '202',
      sequence: '202',
      timestampMs: 20_000,
      content: 'Snapshot 在途时收到的新消息',
    }
    const initialSnapshot = deferred<WorkspaceSnapshot>()
    let eventHandler: ((event: WorkspaceEvent) => void) | undefined
    const adapter = {
      load: vi.fn(() => initialSnapshot.promise),
      loadCachedMessages: vi.fn(async () => []),
      loadHistory: vi.fn(async () => ({ messages: [], hasMoreBefore: false, hasMoreAfter: false })),
      loadDraft: vi.fn(async () => undefined),
      markRead: vi.fn(async () => undefined),
      cacheMessages: vi.fn(async () => undefined),
      subscribe: vi.fn((handler: (event: WorkspaceEvent) => void) => {
        eventHandler = handler
        return () => undefined
      }),
    } as unknown as WorkspaceAdapter
    let workspace!: ReturnType<typeof useWorkspace>
    const wrapper = mount(defineComponent({
      setup() {
        workspace = useWorkspace(adapter)
        return () => h('div')
      },
    }))

    eventHandler?.({ type: 'message.created', conversation: realtimeConversation, message: realtimeMessage })
    initialSnapshot.resolve({
      runtime: { status: 'connected', message: 'connected', reverseWebSocketPath: '/onebot/v11/ws' },
      accounts: [owner],
      capabilities: {},
      conversations: [existingConversation],
      messages: {},
      sessions: [],
      agentMessages: {},
      runs: [],
      configs: {},
    })
    await flushPromises()
    await flushPromises()

    expect(workspace.conversations.value.map((item) => item.id)).toContain(realtimeConversation.id)
    workspace.selectConversation(realtimeConversation.id)
    expect(workspace.chatMessages.value).toContainEqual(realtimeMessage)
    wrapper.unmount()
  })

  it('selects and loads the first valid conversation when a refresh removes the active one', async () => {
    const owner = account('qq-111111111')
    const removedConversation = conversation(owner, '345678901')
    const remainingConversation = conversation(owner, '456789012')
    const firstSnapshot: WorkspaceSnapshot = {
      runtime: { status: 'connected', message: 'connected', reverseWebSocketPath: '/onebot/v11/ws' },
      accounts: [owner],
      capabilities: {},
      conversations: [removedConversation],
      messages: {},
      sessions: [],
      agentMessages: {},
      runs: [],
      configs: {},
    }
    const secondSnapshot: WorkspaceSnapshot = {
      ...firstSnapshot,
      conversations: [remainingConversation],
      messages: {},
    }
    const adapter = {
      load: vi.fn()
        .mockResolvedValueOnce(firstSnapshot)
        .mockResolvedValueOnce(secondSnapshot),
      loadCachedMessages: vi.fn(async () => []),
      loadHistory: vi.fn(async () => ({ messages: [], hasMoreBefore: false, hasMoreAfter: false })),
      loadDraft: vi.fn(async () => undefined),
      markRead: vi.fn(async () => undefined),
      subscribe: vi.fn(() => () => undefined),
    } as unknown as WorkspaceAdapter
    let workspace!: ReturnType<typeof useWorkspace>
    const wrapper = mount(defineComponent({
      setup() {
        workspace = useWorkspace(adapter, removedConversation.id)
        return () => h('div')
      },
    }))
    await flushPromises()
    await flushPromises()

    await workspace.load()

    expect(workspace.selectedConversationId.value).toBe(remainingConversation.id)
    expect(workspace.selectedConversation.value).toEqual(expect.objectContaining({ id: remainingConversation.id }))
    expect(adapter.loadHistory).toHaveBeenLastCalledWith(remainingConversation, { limit: 50 })
    wrapper.unmount()
  })

  it('loads and sends only opaque custom-face handles for the selected conversation', async () => {
    const owner = account('qq-111111111')
    const target = conversation(owner, '345678901')
    const snapshot: WorkspaceSnapshot = {
      runtime: { status: 'connected', message: 'connected', reverseWebSocketPath: '/onebot/v11/ws' },
      accounts: [owner],
      capabilities: {},
      conversations: [target],
      messages: {},
      sessions: [],
      agentMessages: {},
      runs: [],
      configs: {},
    }
    const handle = 'a'.repeat(32)
    const catalog = {
      accountId: owner.id,
      conversationId: target.id,
      items: [{
        handle,
        previewUrl: `/api/accounts/${owner.id}/conversations/group/${target.peerId}/custom-faces/${handle}/preview`,
        expiresAt: Date.now() + 60_000,
      }],
      refreshedAt: Date.now(),
    }
    const sentMessage: ChatMessage = {
      ...message(target),
      id: `${target.id}:102`,
      messageId: '102',
      messageSeq: '102',
      senderId: owner.botId,
      senderName: owner.name,
      content: '[表情]',
      segments: [{ type: 'image', summary: '[表情]', sticker: true }],
      mine: true,
    }
    const adapter = {
      load: vi.fn(async () => snapshot),
      loadCachedMessages: vi.fn(async () => []),
      loadHistory: vi.fn(async () => ({ messages: [], hasMoreBefore: false, hasMoreAfter: false })),
      loadDraft: vi.fn(async () => undefined),
      markRead: vi.fn(async () => undefined),
      loadCustomFaces: vi.fn(async () => catalog),
      sendSegments: vi.fn(async () => sentMessage),
      cacheMessages: vi.fn(async () => undefined),
      subscribe: vi.fn(() => () => undefined),
    } as unknown as WorkspaceAdapter
    let workspace!: ReturnType<typeof useWorkspace>
    const wrapper = mount(defineComponent({
      setup() {
        workspace = useWorkspace(adapter)
        return () => h('div')
      },
    }))
    await flushPromises()
    await flushPromises()

    await expect(workspace.loadCustomFaces()).resolves.toEqual(catalog)
    expect(adapter.loadCustomFaces).toHaveBeenCalledWith(target)
    await expect(workspace.sendCustomFace(handle)).resolves.toBe(true)
    expect(adapter.sendSegments).toHaveBeenCalledWith(
      expect.objectContaining({ id: target.id, accountId: owner.id, peerId: target.peerId }),
      [{ type: 'custom_face', handle }],
    )
    expect(workspace.chatMessages.value.at(-1)).toEqual(sentMessage)
    wrapper.unmount()
  })

  it('does not restore a stale cached draft after a successful send clears it', async () => {
    const owner = account('qq-111111111')
    const target = conversation(owner, '345678901')
    const snapshot: WorkspaceSnapshot = {
      runtime: { status: 'connected', message: 'connected', reverseWebSocketPath: '/onebot/v11/ws' },
      accounts: [owner],
      capabilities: {},
      conversations: [target],
      messages: {},
      sessions: [],
      agentMessages: {},
      runs: [],
      configs: {},
    }
    const staleDraft = deferred<{ accountId: string; conversationId: string; content: string; updatedAt: number } | undefined>()
    const sentMessage: ChatMessage = {
      ...message(target),
      id: `${target.id}:102`,
      messageId: '102',
      messageSeq: '102',
      senderId: owner.botId,
      senderName: owner.name,
      content: '已发送',
      segments: [{ type: 'text', text: '已发送' }],
      mine: true,
    }
    const adapter = {
      load: vi.fn(async () => snapshot),
      loadCachedMessages: vi.fn(async () => []),
      loadHistory: vi.fn(async () => ({ messages: [], hasMoreBefore: false, hasMoreAfter: false })),
      loadDraft: vi.fn(() => staleDraft.promise),
      saveDraft: vi.fn(async () => undefined),
      sendSegments: vi.fn(async () => sentMessage),
      cacheMessages: vi.fn(async () => undefined),
      markRead: vi.fn(async () => undefined),
      subscribe: vi.fn(() => () => undefined),
    } as unknown as WorkspaceAdapter
    let workspace!: ReturnType<typeof useWorkspace>
    const wrapper = mount(defineComponent({
      setup() {
        workspace = useWorkspace(adapter)
        return () => h('div')
      },
    }))
    await flushPromises()
    expect(adapter.loadDraft).toHaveBeenCalledWith(target)

    const complete = vi.fn()
    await workspace.sendRichMessage([{ type: 'text', text: '已发送' }], [], complete)
    staleDraft.resolve({
      accountId: owner.id,
      conversationId: target.id,
      content: '不应恢复的旧草稿',
      updatedAt: 1,
    })
    await flushPromises()

    expect(complete).toHaveBeenCalledWith(true)
    expect(workspace.drafts.value[target.id]).toBe('')
    expect(adapter.saveDraft).toHaveBeenCalledWith(
      expect.objectContaining({ accountId: owner.id, conversationId: target.id, content: '' }),
    )
    wrapper.unmount()
  })

  it('restores every valid conversation draft from IndexedDB without crossing account or conversation scopes', async () => {
    const first = account('qq-111111111')
    const second = account('qq-222222222')
    const firstValid = conversation(first, '345678901')
    const firstAccountMismatch = conversation(first, '456789012')
    const secondValid = conversation(second, '345678901')
    const secondConversationMismatch = conversation(second, '567890123')
    const snapshot: WorkspaceSnapshot = {
      runtime: { status: 'connected', message: 'connected', reverseWebSocketPath: '/onebot/v11/ws' },
      accounts: [first, second],
      capabilities: {},
      conversations: [firstValid, firstAccountMismatch, secondValid, secondConversationMismatch],
      messages: {},
      sessions: [],
      agentMessages: {},
      runs: [],
      configs: {},
    }
    const database = new WorkspaceDatabase(`dududa-draft-test-${crypto.randomUUID()}`)
    databases.push(database)
    const storage = new WorkspaceCache(database)
    await storage.saveDraft({
      accountId: first.id,
      conversationId: firstValid.id,
      content: '账号一草稿',
      updatedAt: 1,
    })
    await storage.saveDraft({
      accountId: second.id,
      conversationId: secondValid.id,
      content: '账号二草稿',
      updatedAt: 2,
    })
    await database.drafts.bulkPut([
      {
        id: firstAccountMismatch.id,
        accountId: second.id,
        conversationId: firstAccountMismatch.id,
        content: '不应恢复的串号草稿',
        updatedAt: 3,
      },
      {
        id: secondConversationMismatch.id,
        accountId: second.id,
        conversationId: secondValid.id,
        content: '不应恢复的串会话草稿',
        updatedAt: 4,
      },
    ])
    const loadDraft = vi.fn((target: Conversation) => storage.draft(target.accountId, target.id))
    const adapter = {
      load: vi.fn(async () => snapshot),
      loadCachedMessages: vi.fn(async () => []),
      loadHistory: vi.fn(async () => ({ messages: [], hasMoreBefore: false, hasMoreAfter: false })),
      loadDraft,
      markRead: vi.fn(async () => undefined),
      subscribe: vi.fn(() => () => undefined),
    } as unknown as WorkspaceAdapter
    let workspace!: ReturnType<typeof useWorkspace>
    const wrapper = mount(defineComponent({
      setup() {
        workspace = useWorkspace(adapter)
        return () => h('div')
      },
    }))
    await flushPromises()
    await flushPromises()

    expect(loadDraft).toHaveBeenCalledTimes(snapshot.conversations.length)
    expect(new Set(loadDraft.mock.calls.map(([target]) => target.id))).toEqual(
      new Set(snapshot.conversations.map((item) => item.id)),
    )
    expect(workspace.drafts.value).toEqual({
      [firstValid.id]: '账号一草稿',
      [secondValid.id]: '账号二草稿',
    })
    expect(workspace.chatDraft.value).toBe('账号一草稿')
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

  it('does not let Agent placeholders send QQ messages or approve permissions', async () => {
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
    const sendMessage = vi.fn()
    const adapter = {
      load: async () => snapshot,
      loadCachedMessages: async () => [],
      loadHistory: async () => ({ messages: [], hasMoreBefore: false, hasMoreAfter: false }),
      loadDraft: async () => undefined,
      markRead: async () => undefined,
      sendMessage,
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

    const draft: ReplyDraftPart = {
      type: 'reply_draft',
      id: 'draft-1',
      accountId: owner.id,
      conversationId: target.id,
      content: '不得直发',
      status: 'draft',
    }
    await workspace.approveDraft(draft)
    expect(sendMessage).not.toHaveBeenCalled()
    expect(draft.status).toBe('draft')
    expect(workspace.toast.value).toContain('未发送 QQ 消息')

    const permission: PermissionPart = {
      type: 'permission',
      id: 'permission-1',
      title: '发送消息',
      detail: '请求发送',
      state: 'pending',
    }
    workspace.respondPermission(permission, true)
    expect(permission.state).toBe('pending')
    expect(workspace.toast.value).toContain('状态未变更')
    wrapper.unmount()
  })

  it('uses explicit internal Runtime status and keeps generated candidates in a local no-send session', async () => {
    const owner = account('qq-111111111')
    const target = conversation(owner, '345678901')
    const contextMessages = Array.from({ length: 70 }, (_, index) => {
      const item = message(target)
      const sequence = String(index + 1)
      const content = `真实消息 ${sequence}`
      return {
        ...item,
        id: `${target.id}:${sequence}`,
        messageId: sequence,
        messageSeq: sequence,
        timestampMs: index + 1,
        content,
        segments: [{ type: 'text' as const, text: content }],
      }
    })
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
    const sendMessage = vi.fn()
    const adapter = {
      load: async () => snapshot,
      loadCachedMessages: async () => [],
      loadHistory: async () => ({ messages: contextMessages, hasMoreBefore: false, hasMoreAfter: false }),
      loadDraft: async () => undefined,
      markRead: async () => undefined,
      sendMessage,
      subscribe: () => () => undefined,
    } as unknown as WorkspaceAdapter
    const scope: InternalTestAgentScope = { accountId: owner.id, conversationId: target.id }
    const catalog: InternalTestAgentCatalog = {
      agent: { id: 'dududa', displayName: 'Dududa Agent' },
      selectionModes: ['adaptive', 'preferred', 'locked'],
      pluginModes: ['off', 'auto', 'on', 'locked'],
      models: [
        { id: 'gpt-5.6-luna', tier: 'haiku', displayName: 'Luna', available: true, modalities: ['text'], reasoningLevels: ['low', 'medium'] },
        { id: 'gpt-5.6-terra', tier: 'sonnet', displayName: 'Terra', available: true, modalities: ['text'], reasoningLevels: ['low', 'medium', 'high'] },
        { id: 'gpt-5.6-sol', tier: 'opus', displayName: 'Sol', available: true, modalities: ['text'], reasoningLevels: ['medium', 'high'] },
      ],
      reasoningLevels: ['low', 'medium', 'high'],
      answerProfiles: ['short', 'medium', 'long'],
      replyIntensities: ['quiet', 'normal', 'active'],
      contextLengths: [
        { id: 'compact', messageLimit: 12, characterLimit: 6_000 },
        { id: 'standard', messageLimit: 30, characterLimit: 18_000 },
        { id: 'extended', messageLimit: 60, characterLimit: 36_000 },
      ],
      groupChatStyles: ['restrained', 'natural', 'lively', 'technical'],
      proactiveFrequencies: [
        { id: 'low', probability: 0.02, cooldownSeconds: 1_800, maximumPerHour: 1 },
        { id: 'normal', probability: 0.08, cooldownSeconds: 600, maximumPerHour: 3 },
        { id: 'high', probability: 0.20, cooldownSeconds: 180, maximumPerHour: 8 },
      ],
      replyIntensityNotice: '候选决策初值；当前运行态为 NO SEND，不控制真实消息发送概率。',
      plugins: [{
        id: 'icourse',
        displayName: '评课社区',
        kind: 'mcp',
        installed: true,
        available: false,
        policyManaged: true,
        runtimeTarget: 'web_agent',
        runtimeReadiness: 'unavailable',
        executionKind: 'agent_capability',
        description: '当前唯一真实 MCP Server',
        unavailableReason: '尚未接入 Web Agent 执行链',
      }],
      policyDefaults: {
        enabled: true,
        modelTier: { mode: 'adaptive', preferred: 'sonnet', allowed: ['haiku', 'sonnet', 'opus'] },
        reasoning: { mode: 'adaptive', preferred: 'medium', allowed: ['low', 'medium', 'high'] },
        answerProfile: { mode: 'adaptive', preferred: 'medium', allowed: ['short', 'medium', 'long'] },
        replyIntensity: { mode: 'adaptive', preferred: 'normal', allowed: ['quiet', 'normal', 'active'] },
        contextLength: { mode: 'adaptive', preferred: 'standard', allowed: ['compact', 'standard', 'extended'] },
        groupChatStyle: { mode: 'adaptive', preferred: 'natural', allowed: ['restrained', 'natural', 'lively', 'technical'] },
        proactiveTalk: { frequency: 'low' },
        plugins: { icourse: 'off' },
      },
    }
    const policy: InternalTestAgentPolicy = {
      schemaVersion: 1,
      scope,
      enabled: true,
      modelTier: { mode: 'preferred', preferred: 'sonnet', allowed: ['haiku', 'sonnet', 'opus'] },
      reasoning: { mode: 'adaptive', preferred: 'medium', allowed: ['low', 'medium', 'high'] },
      answerProfile: { mode: 'adaptive', preferred: 'medium', allowed: ['short', 'medium', 'long'] },
      replyIntensity: { mode: 'adaptive', preferred: 'normal', allowed: ['quiet', 'normal', 'active'] },
      contextLength: { mode: 'preferred', preferred: 'standard', allowed: ['compact', 'standard', 'extended'] },
      groupChatStyle: { mode: 'adaptive', preferred: 'natural', allowed: ['restrained', 'natural', 'lively', 'technical'] },
      proactiveTalk: { frequency: 'normal' },
      plugins: { icourse: 'auto' },
    }
    const response: InternalTestAgentResponse = {
      runId: 'run-internal-1',
      candidate: '这是只保留在控制台中的候选回答。',
      tier: 'haiku',
      model: 'gpt-5.6-luna',
      reasoning: 'high',
      answerProfile: 'short',
      replyIntensity: 'active',
      contextLength: 'extended',
      groupChatStyle: 'technical',
      contextUsage: {
        messageLimit: 60,
        characterLimit: 36_000,
        messagesRead: 42,
        charactersRead: 8_640,
      },
      effectiveSelection: {
        scope,
        policySource: 'saved',
        modelTier: 'haiku',
        model: 'gpt-5.6-luna',
        reasoning: 'high',
        answerProfile: 'short',
        replyIntensity: 'active',
        contextLength: 'extended',
        groupChatStyle: 'technical',
        contextUsage: {
          messageLimit: 60,
          characterLimit: 36_000,
          messagesRead: 42,
          charactersRead: 8_640,
        },
        plugins: {
          icourse: {
            mode: 'auto',
            available: false,
            eligible: false,
            selectedForRun: false,
            applicable: false,
            triggerMatched: false,
            runtimeTarget: 'web_agent',
            runtimeReadiness: 'unavailable',
            selectionReason: 'unavailable',
          },
        },
      },
      reasonCodes: ['policy.saved', 'model.preferred_overridden', 'answer_profile.request_hint'],
      latencyMs: 321,
      generatedAt: '2026-08-16T12:00:00.000Z',
      outputCalls: 0,
      memoryWrites: 0,
      toolCalls: 0,
      runtimePath: 'dududa_2_preview',
    }
    const respond = vi.fn(async (_payload: InternalTestAgentRequest) => response)
    const saveAgentConfig = vi.fn(async (_scope: InternalTestAgentScope, next: InternalTestAgentPolicy) => ({
      ...next,
      updatedAt: '2026-08-17T08:00:00.000Z',
    }))
    const agentAdapter: InternalTestAgentAdapter = {
      agentStatus: vi.fn(async (): Promise<InternalTestAgentStatus> => ({
        available: true,
        outputEnabled: false as const,
        providerConfigured: true,
        modelMapping: {
          haiku: 'gpt-5.6-luna',
          sonnet: 'gpt-5.6-terra',
          opus: 'gpt-5.6-sol',
        },
        runtimeControls: {
          passiveAutoReply: {
            actualEnabled: false,
            state: 'disabled',
            rolloutMode: 'off',
            deliveryEnabled: false,
            killSwitch: true,
            summary: '被动自动回复当前实际关闭。',
          },
          proactiveGroupParticipation: {
            actualEnabled: false,
            state: 'disabled',
            stage: 'probe_shadow',
            deliveryEnabled: false,
            summary: '主动参与当前只有 Probe Shadow。',
          },
        },
        warnings: [],
      })),
      agentCatalog: vi.fn(async () => catalog),
      agentConfig: vi.fn(async () => policy),
      saveAgentConfig,
      respond,
    }
    let workspace!: ReturnType<typeof useWorkspace>
    const wrapper = mount(defineComponent({
      setup() {
        workspace = useWorkspace(adapter, '', agentAdapter)
        return () => h('div')
      },
    }))
    await flushPromises()
    await flushPromises()

    expect(workspace.agentAvailable.value).toBe(true)
    expect(agentAdapter.agentConfig).toHaveBeenCalledWith(scope)
    expect(workspace.agentPolicy.value).toMatchObject({
      scope,
      modelTier: { mode: 'preferred', preferred: 'sonnet' },
      answerProfile: { mode: 'adaptive', preferred: 'medium' },
      replyIntensity: { mode: 'adaptive', preferred: 'normal' },
      contextLength: { mode: 'preferred', preferred: 'standard' },
      groupChatStyle: { mode: 'adaptive', preferred: 'natural' },
    })
    workspace.setAnswerProfile('short')
    expect(workspace.answerProfileHint.value).toBe('short')
    expect(workspace.agentPolicy.value?.modelTier.preferred).toBe('sonnet')
    expect(snapshot.sessions).toEqual([])
    await workspace.sendAgentPrompt('总结当前讨论')

    expect(respond).toHaveBeenCalledWith(expect.objectContaining({
      accountId: owner.id,
      conversationId: target.id,
      conversationName: target.name,
      conversationType: 'group',
      prompt: '总结当前讨论',
      answerProfile: 'short',
    }))
    const request = respond.mock.calls[0]?.[0]
    expect(request?.messages).toHaveLength(60)
    expect(request?.messages[0]?.content).toBe('真实消息 11')
    expect(request?.messages.at(-1)?.content).toBe('真实消息 70')
    expect(workspace.answerProfileHint.value).toBeUndefined()
    expect(workspace.conversationSessions.value).toHaveLength(1)
    expect(workspace.agentMessages.value.map((item) => item.role)).toEqual(['operator', 'assistant'])
    expect(workspace.agentMessages.value[1]?.parts).toContainEqual(
      expect.objectContaining({ type: 'text', text: '这是只保留在控制台中的候选回答。' }),
    )
    expect(workspace.selectedRun.value).toMatchObject({
      id: 'run-internal-1',
      status: 'completed',
      model: 'gpt-5.6-luna',
      modelTier: 'haiku',
      reasoning: 'high',
      answerProfile: 'short',
      contextMessages: 42,
      plugins: [],
      runtimePath: 'dududa_2_preview',
      toolCalls: 0,
      reasonCodes: ['policy.saved', 'model.preferred_overridden', 'answer_profile.request_hint'],
      effectiveSelection: response.effectiveSelection,
    })
    const nextPolicy: InternalTestAgentPolicy = {
      ...policy,
      reasoning: { mode: 'locked', preferred: 'high', allowed: ['high'] },
    }
    workspace.updateAgentPolicy(nextPolicy)
    await workspace.saveAgentPolicy()
    expect(saveAgentConfig).toHaveBeenCalledWith(scope, nextPolicy)
    expect(workspace.agentPolicy.value?.reasoning).toEqual({ mode: 'locked', preferred: 'high', allowed: ['high'] })
    expect(sendMessage).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('rechecks Agent Runtime on focus and recovers after an initial connection failure', async () => {
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
    const adapter = {
      load: async () => snapshot,
      loadCachedMessages: async () => [],
      loadHistory: async () => ({ messages: [], hasMoreBefore: false, hasMoreAfter: false }),
      loadDraft: async () => undefined,
      markRead: async () => undefined,
      subscribe: () => () => undefined,
    } as unknown as WorkspaceAdapter
    const agentStatus = vi.fn()
      .mockRejectedValueOnce(new Error('Agent API 尚未启动'))
      .mockResolvedValue({
        available: true,
        outputEnabled: false as const,
        providerConfigured: true,
        modelMapping: {
          haiku: 'gpt-5.6-luna',
          sonnet: 'gpt-5.6-terra',
          opus: 'gpt-5.6-sol',
        },
        runtimeControls: {
          passiveAutoReply: {
            actualEnabled: false,
            state: 'disabled',
            rolloutMode: 'off',
            deliveryEnabled: false,
            killSwitch: true,
            summary: '被动自动回复当前实际关闭。',
          },
          proactiveGroupParticipation: {
            actualEnabled: false,
            state: 'disabled',
            stage: 'probe_shadow',
            deliveryEnabled: false,
            summary: '主动参与当前只有 Probe Shadow。',
          },
        },
        warnings: [],
      } satisfies InternalTestAgentStatus)
    const agentAdapter = {
      agentStatus,
      respond: vi.fn(),
    } as unknown as InternalTestAgentAdapter
    let workspace!: ReturnType<typeof useWorkspace>
    const wrapper = mount(defineComponent({
      setup() {
        workspace = useWorkspace(adapter, '', agentAdapter)
        return () => h('div')
      },
    }))
    await flushPromises()
    await flushPromises()

    expect(workspace.agentAvailable.value).toBe(false)
    expect(workspace.agentRuntimeError.value).toBe('Agent API 尚未启动')

    window.dispatchEvent(new Event('focus'))
    await flushPromises()

    expect(agentStatus).toHaveBeenCalledTimes(2)
    expect(workspace.agentAvailable.value).toBe(true)
    expect(workspace.agentRuntimeError.value).toBe('')
    wrapper.unmount()
  })
})
