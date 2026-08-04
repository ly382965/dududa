import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

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
    ].map((name) => [name, { status, ...(status === 'unsupported' ? { reason: '测试能力不可用' } : {}) }]),
  ) as Account['capabilities']
}

const reply: ChatMessage | null = null

describe('MessageComposer', () => {
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
})
