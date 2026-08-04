import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { editorDocumentToSegments, parseComposerDraft, serializeComposerDraft } from '../../services/composer-content'
import type { Account, ChatMessage } from '../../types/workspace'
import MessageComposer from './MessageComposer.vue'

function capabilities(status: 'supported' | 'unsupported' = 'supported'): Account['capabilities'] {
  return Object.fromEntries(
    [
      'message.send.text',
      'message.send.mention',
      'message.send.reply',
      'message.send.face',
      'message.send.image',
      'message.send.audio',
      'message.send.video',
      'message.send.file',
      'message.custom_faces',
    ].map((name) => [name, { status, ...(status === 'unsupported' ? { reason: '测试能力不可用' } : {}) }]),
  ) as Account['capabilities']
}

const reply: ChatMessage | null = null

describe('MessageComposer', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('initializes send state from a restored rich draft', async () => {
    const draft = serializeComposerDraft({
      type: 'doc',
      content: [{ type: 'paragraph', content: [{ type: 'text', text: '恢复的真实草稿' }] }],
    })
    const wrapper = mount(MessageComposer, {
      props: {
        draft,
        replyTo: reply,
        conversationName: '真实群聊',
        capabilities: capabilities(),
      },
    })
    await flushPromises()

    expect(wrapper.get('.composer-send').attributes('disabled')).toBeUndefined()
  })

  it('disables unsupported actions with the capability reason', async () => {
    const wrapper = mount(MessageComposer, {
      props: {
        draft: '',
        replyTo: reply,
        conversationName: '真实群聊',
        capabilities: capabilities('unsupported'),
      },
    })
    await flushPromises()

    expect(wrapper.get('button[title="测试能力不可用"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[aria-label="QQ 消息输入"]').attributes('contenteditable')).toBe('false')
  })

  it('flushes the active document before a keyed conversation unmounts', async () => {
    const updates: string[] = []
    const wrapper = mount(MessageComposer, {
      props: {
        draft: '',
        replyTo: reply,
        conversationName: '账号一群聊',
        capabilities: capabilities(),
        'onUpdate:draft': (value: string) => updates.push(value),
      },
    })
    await flushPromises()
    const editor = wrapper.get('[contenteditable="true"][aria-label="QQ 消息输入"]')
    editor.element.innerHTML = '<p>切换前草稿</p>'
    await editor.trigger('input')
    await flushPromises()

    wrapper.unmount()
    const restored = editorDocumentToSegments(parseComposerDraft(updates.at(-1) ?? ''))
    expect(restored).toEqual([{ type: 'text', text: '切换前草稿' }])
  })

  it('switches between QQ and account-scoped favorite faces without inserting a remote URL into the draft', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 502 })))
    const handle = 'a'.repeat(32)
    const previewUrl = `/api/accounts/qq-123456789/conversations/group/345678901/custom-faces/${handle}/preview`
    const loadCustomFaces = vi.fn(async () => ({
      accountId: 'qq-123456789',
      conversationId: 'qq-123456789:group:345678901',
      items: [{ handle, previewUrl, expiresAt: Date.now() + 60_000 }],
      refreshedAt: Date.now(),
    }))
    const wrapper = mount(MessageComposer, {
      attachTo: document.body,
      props: {
        draft: '保留输入内容',
        replyTo: reply,
        conversationName: '真实群聊',
        capabilities: capabilities(),
        loadCustomFaces,
      },
    })
    await flushPromises()
    const before = wrapper.get('.qq-composer-editor').element.innerHTML

    await wrapper.get('button[title="QQ 表情"]').trigger('click')
    expect(wrapper.find('[data-testid="qq-face-picker"]').exists() || wrapper.text().includes('QQ 表情加载失败')).toBe(true)
    await wrapper.get('button[aria-label="我的收藏"]').trigger('click')
    await flushPromises()

    expect(loadCustomFaces).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-testid="favorite-face-picker"] img').attributes('src')).toBe(previewUrl)
    await wrapper.get('button[aria-label="发送收藏表情 1"]').trigger('click')
    expect(wrapper.emitted('favoriteSelected')?.[0]).toEqual([handle])
    expect(wrapper.get('.qq-composer-editor').element.innerHTML).toBe(before)
    expect(wrapper.find('.face-picker').exists()).toBe(false)
    wrapper.unmount()
  })
})
