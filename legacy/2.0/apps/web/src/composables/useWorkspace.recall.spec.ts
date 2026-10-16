import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { InternalTestAgentAdapter } from '../services/internal-test'
import type { WorkspaceAdapter } from '../services/workspace-adapter'
import type { ChatMessage, Conversation, WorkspaceEvent, WorkspaceSnapshot } from '../types/workspace'
import { useWorkspace } from './useWorkspace'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach((wrapper) => wrapper.unmount()); vi.useRealTimers() })

async function fixture(type: 'group' | 'private' = 'group') {
  const conversation: Conversation = { id: `qq-123456:${type}:234567`, accountId: 'qq-123456', type, peerId: '234567',
    name: '测试会话', avatar: '', lastMessage: '', lastMessageAt: '', unread: 0, pinned: false, muted: false }
  const original: ChatMessage = { id: `${conversation.id}:101`, accountId: conversation.accountId, conversationId: conversation.id,
    messageId: '101', senderId: '234567', senderName: '成员', senderAvatar: '', timestamp: '12:00', timestampMs: Date.now(),
    content: '需要保留的原文', segments: [{ type: 'text', text: '需要保留的原文' }], mine: false }
  const snapshot = { runtime: { status: 'connected', message: '', reverseWebSocketPath: '' }, accounts: [], capabilities: {},
    conversations: [conversation], messages: {}, sessions: [], agentMessages: {}, runs: [], configs: {} } as WorkspaceSnapshot
  let eventHandler!: (event: WorkspaceEvent) => void
  const adapter = {
    load: vi.fn(async () => structuredClone(snapshot)),
    loadDraft: async () => undefined, loadCachedMessages: async () => [],
    loadHistory: vi.fn(async () => ({ messages: [structuredClone(original)], hasMoreBefore: false, hasMoreAfter: false })),
    markRead: async () => undefined, deleteCachedMessage: vi.fn(async () => undefined),
    cacheMessages: vi.fn(async () => undefined),
    recallMessage: vi.fn(async () => undefined),
    subscribe: (listener: (event: WorkspaceEvent) => void) => { eventHandler = listener; return () => undefined },
  }
  const agent = { agentStatus: async () => undefined, agentCatalog: async () => undefined, agentConfig: async () => undefined } as unknown as InternalTestAgentAdapter
  let workspace!: ReturnType<typeof useWorkspace>
  wrappers.push(mount(defineComponent({ setup() { workspace = useWorkspace(adapter as unknown as WorkspaceAdapter, '', agent); return () => h('div') } })))
  await flushPromises()
  const retained: ChatMessage = { ...original, status: 'recalled', recall: { recalledAt: Date.now(), retained: true, expiresAt: Date.now() + 86_400_000 } }
  const recallEvent: WorkspaceEvent = { type: 'message.deleted', accountId: conversation.accountId, conversationId: conversation.id,
    messageId: original.id, message: retained }
  return { workspace, adapter, conversation, original, retained, recallEvent, emit: (event: WorkspaceEvent) => eventHandler(event) }
}

describe('workspace recall retention', () => {
  it.each(['group', 'private'] as const)('preserves server originals in %s chats through later stale history', async (type) => {
    const { workspace, adapter, original, recallEvent, emit } = await fixture(type)
    emit(recallEvent)
    await flushPromises()
    expect(workspace.chatMessages.value[0]).toMatchObject({ status: 'recalled', content: original.content, recall: { retained: true } })
    expect(adapter.deleteCachedMessage).toHaveBeenCalled()
    expect(workspace.conversations.value[0]?.lastMessage).toBe('此消息已撤回')
    await workspace.loadLatestMessages()
    expect(workspace.chatMessages.value[0]).toMatchObject({ status: 'recalled', content: original.content, recall: { retained: true } })
  })

  it('keeps the retained SSE result when a self-recall HTTP request finishes afterwards', async () => {
    const { workspace, adapter, recallEvent, emit } = await fixture()
    adapter.recallMessage.mockImplementation(async () => { emit(recallEvent) })
    await workspace.recallChatMessage(workspace.chatMessages.value[0]!)
    expect(workspace.chatMessages.value[0]).toMatchObject({ status: 'recalled', content: '需要保留的原文', recall: { retained: true } })
  })

  it('clears originals when disabled remotely and rejects a stale retained history response', async () => {
    const { workspace, adapter, conversation, retained, recallEvent, emit } = await fixture()
    emit(recallEvent)
    emit({ type: 'recall.settings.changed', accountId: conversation.accountId, conversationId: conversation.id,
      settings: { enabled: false, retentionDays: 7 } })
    expect(workspace.chatMessages.value[0]).toMatchObject({ content: '此消息已撤回', segments: [], recall: { retained: false } })
    adapter.loadHistory.mockResolvedValue({ messages: [retained], hasMoreBefore: false, hasMoreAfter: false })
    await workspace.loadLatestMessages()
    expect(workspace.chatMessages.value[0]?.content).toBe('此消息已撤回')
  })

  it('clears expired originals before opening or refreshing history', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    const { workspace, adapter, retained, recallEvent, emit } = await fixture()
    emit(recallEvent)
    adapter.loadHistory.mockResolvedValue({ messages: [retained], hasMoreBefore: false, hasMoreAfter: false })
    vi.setSystemTime(retained.recall!.expiresAt! + 1)
    await workspace.loadLatestMessages()
    expect(workspace.chatMessages.value[0]).toMatchObject({ status: 'recalled', content: '此消息已撤回', segments: [], recall: { retained: false } })
  })

  it('applies settings changed while disconnected when the workspace reconnects', async () => {
    const { workspace, adapter, conversation, recallEvent, emit } = await fixture()
    emit(recallEvent)
    const snapshot = await adapter.load()
    adapter.load.mockResolvedValue({ ...snapshot, recallSettings: { [conversation.id]: { enabled: false, retentionDays: 7 } } })
    emit({ type: 'workspace.refresh' })
    await flushPromises()
    expect(workspace.chatMessages.value[0]).toMatchObject({ status: 'recalled', content: '此消息已撤回', recall: { retained: false } })
  })
})
