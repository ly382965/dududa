import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { publishRecallUpdate, recallService } from '../../services/recall'
import type { ChatMessage, Conversation, RecallArchivePage } from '../../types/workspace'
import RecallArchiveDialog from './RecallArchiveDialog.vue'

const conversation: Conversation = { id: 'qq-100001:private:200001', accountId: 'qq-100001', type: 'private',
  peerId: '200001', name: '测试好友', avatar: '', lastMessage: '', lastMessageAt: '', unread: 0, pinned: false, muted: false }
const wrappers: ReturnType<typeof mount>[] = []
function message(id: string, expiresAt = Date.now() + 60_000): ChatMessage {
  return { id: `${conversation.id}:${id}`, messageId: id, accountId: conversation.accountId, conversationId: conversation.id,
    senderId: '200001', senderName: '好友', senderAvatar: '', timestamp: '12:00', mine: false,
    content: `原文${id}`, segments: [{ type: 'text', text: `原文${id}` }], status: 'recalled',
    recall: { retained: true, recalledAt: Date.now(), expiresAt } }
}
async function open(page: RecallArchivePage) {
  vi.spyOn(recallService, 'load').mockResolvedValue(page)
  const wrapper = mount(RecallArchiveDialog, { attachTo: document.body, props: { open: true, conversation } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
afterEach(() => { wrappers.splice(0).forEach((wrapper) => wrapper.unmount()); document.body.innerHTML = ''; vi.restoreAllMocks() })

describe('RecallArchiveDialog', () => {
  it('loads retained private-chat originals, filters expired records and paginates', async () => {
    await open({ settings: { enabled: true, retentionDays: 7 }, messages: [message('101'), message('expired', Date.now() - 1)], hasMore: true, nextCursor: 'next' })
    expect(document.body.textContent).toContain('原文101')
    expect(document.body.textContent).not.toContain('原文expired')
    vi.mocked(recallService.load).mockResolvedValue({ settings: { enabled: true, retentionDays: 7 }, messages: [message('102')], hasMore: false })
    document.querySelector<HTMLButtonElement>('.load-more')!.click()
    await flushPromises()
    expect(recallService.load).toHaveBeenLastCalledWith(conversation, 'next')
    expect(document.body.textContent).toContain('原文101')
    expect(document.body.textContent).toContain('原文102')
  })

  it('saves the per-conversation setting and clears displayed originals on a remote disable', async () => {
    await open({ settings: { enabled: true, retentionDays: 7 }, messages: [message('101')], hasMore: false })
    const save = vi.spyOn(recallService, 'saveSettings').mockResolvedValue({ enabled: false, retentionDays: 3 })
    const toggle = document.querySelector<HTMLInputElement>('input[type="checkbox"]')!
    toggle.click()
    const days = document.querySelector<HTMLInputElement>('input[type="number"]')!
    days.value = '3'
    days.dispatchEvent(new Event('input', { bubbles: true }))
    document.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flushPromises()
    expect(save).toHaveBeenCalledWith(conversation, { enabled: false, retentionDays: 3 })
    publishRecallUpdate({ type: 'recall.settings.changed', accountId: conversation.accountId, conversationId: conversation.id,
      settings: { enabled: false, retentionDays: 3 } })
    await flushPromises()
    expect(document.body.textContent).not.toContain('原文101')
    expect(document.body.textContent).toContain('此会话已关闭防撤回')
  })

  it('ignores an in-flight archive response after the conversation is disabled', async () => {
    let resolve!: (page: RecallArchivePage) => void
    vi.spyOn(recallService, 'load').mockReturnValue(new Promise((done) => { resolve = done }))
    const wrapper = mount(RecallArchiveDialog, { attachTo: document.body, props: { open: true, conversation } })
    wrappers.push(wrapper)
    publishRecallUpdate({ type: 'recall.settings.changed', accountId: conversation.accountId, conversationId: conversation.id,
      settings: { enabled: false, retentionDays: 7 } })
    resolve({ settings: { enabled: true, retentionDays: 7 }, messages: [message('101')], hasMore: false })
    await flushPromises()
    expect(document.body.textContent).not.toContain('原文101')
    expect(document.body.textContent).toContain('此会话已关闭防撤回')
  })
})
