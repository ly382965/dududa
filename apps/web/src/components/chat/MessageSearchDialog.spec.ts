import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { workspaceAdapter } from '../../services/workspace-adapter'
import type { ChatMessage, Conversation } from '../../types/workspace'
import MessageSearchDialog from './MessageSearchDialog.vue'

const conversation: Conversation = { id: 'qq-100001:group:200001', accountId: 'qq-100001', type: 'group',
  peerId: '200001', name: '测试群', avatar: '', lastMessage: '', lastMessageAt: '', unread: 0, pinned: false, muted: false }
const wrappers: ReturnType<typeof mount<typeof MessageSearchDialog>>[] = []
async function open() {
  const wrapper = mount(MessageSearchDialog, { attachTo: document.body, props: { open: false, conversation, senders: [] } })
  wrappers.push(wrapper)
  await wrapper.setProps({ open: true })
  await flushPromises()
  return wrapper
}
async function search() {
  const input = document.querySelector<HTMLInputElement>('[aria-label="消息关键词"]')!
  input.value = '不存在'
  input.dispatchEvent(new Event('input', { bubbles: true }))
  await flushPromises()
  document.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  await flushPromises()
}
describe('message search feedback and keyboard navigation', () => {
  beforeEach(() => {
    vi.spyOn(workspaceAdapter, 'searchMessages').mockResolvedValue({ messages: [], hasMore: false })
    vi.spyOn(workspaceAdapter, 'loadCachedMessages').mockResolvedValue([])
  })
  afterEach(() => {
    wrappers.splice(0).forEach(wrapper => wrapper.unmount())
    document.body.innerHTML = ''
    vi.restoreAllMocks()
  })
  it('distinguishes an empty cache from no matching cached messages', async () => {
    await open()
    expect(document.body.textContent).toContain('输入条件搜索')
    await search()
    expect(document.body.textContent).toContain('此浏览器尚未缓存')
    vi.mocked(workspaceAdapter.loadCachedMessages).mockResolvedValue([{} as ChatMessage])
    await search()
    expect(document.body.textContent).toContain('未找到匹配消息')
    expect(document.body.textContent).not.toContain('此浏览器尚未缓存')
  })
  it('traps Tab, closes on Escape and restores focus to the trigger', async () => {
    const trigger = document.createElement('button')
    document.body.append(trigger)
    trigger.focus()
    const wrapper = await open()
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]')!
    const close = dialog.querySelector<HTMLButtonElement>('button')!
    const last = [...dialog.querySelectorAll<HTMLElement>('input[type="date"]')].at(-1)!
    close.focus()
    close.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(last)
    last.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(close)
    close.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    expect(wrapper.emitted('close')).toHaveLength(1)
    await wrapper.setProps({ open: false })
    await flushPromises()
    expect(document.activeElement).toBe(trigger)
  })
})
