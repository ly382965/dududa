import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { publishRecallUpdate } from '../../services/recall'
import { workspaceAdapter } from '../../services/workspace-adapter'
import type { ChatMessage, Conversation } from '../../types/workspace'
import MergedForwardViewerDialog from './MergedForwardViewerDialog.vue'

const conversation: Conversation = { id: 'qq-123456789:group:345678901', accountId: 'qq-123456789', type: 'group',
  peerId: '345678901', name: '测试群', avatar: '', lastMessage: '', lastMessageAt: '', unread: 0, pinned: false, muted: false }
const child: ChatMessage = { id: 'child', accountId: conversation.accountId, conversationId: conversation.id, messageId: '1',
  senderId: '234567890', senderName: '成员', senderAvatar: '', timestamp: '15:10', content: '保留的转发正文',
  segments: [{ type: 'text', text: '保留的转发正文' }], mine: false }
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach((w) => w.unmount()); document.body.innerHTML = ''; vi.restoreAllMocks() })

describe('MergedForwardViewerDialog', () => {
  it.each(['disabled', 'shortened'] as const)('loads the scoped archive and clears an open viewer when retention is %s', async (change) => {
    const now = Date.now()
    const load = vi.spyOn(workspaceAdapter, 'loadForwarded').mockResolvedValue({ forwardId: 'bundle', messages: [child],
      retention: { recordedAt: now - 2 * 86_400_000, expiresAt: now + 86_400_000 } })
    wrappers.push(mount(MergedForwardViewerDialog, { attachTo: document.body,
      props: { open: true, conversation, forwardId: 'bundle', messageId: '42' } }))
    await flushPromises()
    expect(load).toHaveBeenCalledWith(conversation, 'bundle', '42')
    expect(document.body.textContent).toContain(child.content)
    publishRecallUpdate({ type: 'recall.settings.changed', accountId: conversation.accountId, conversationId: conversation.id,
      settings: { enabled: change !== 'disabled', retentionDays: 1 } })
    await flushPromises()
    expect(document.body.textContent).not.toContain(child.content)
    expect(document.body.textContent).toContain(change === 'disabled' ? '保留内容已清除' : '保留的转发内容已过期')
  })

  it('ignores a pending response after archive retention is disabled', async () => {
    let resolve!: (value: { forwardId: string; messages: ChatMessage[] }) => void
    vi.spyOn(workspaceAdapter, 'loadForwarded').mockReturnValue(new Promise((done) => { resolve = done }))
    wrappers.push(mount(MergedForwardViewerDialog, { attachTo: document.body,
      props: { open: true, conversation, forwardId: 'bundle', messageId: '42' } }))
    publishRecallUpdate({ type: 'recall.settings.changed', accountId: conversation.accountId, conversationId: conversation.id,
      settings: { enabled: false, retentionDays: 7 } })
    resolve({ forwardId: 'bundle', messages: [child] })
    await flushPromises()
    expect(document.body.textContent).not.toContain(child.content)
    expect(document.body.textContent).toContain('保留内容已清除')
  })
})
