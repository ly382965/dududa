import { describe, expect, it } from 'vitest'

import {
  editorDocumentToSegments,
  hasComposerContent,
  parseComposerDraft,
  serializeComposerDraft,
} from './composer-content'

describe('Mew-derived composer content', () => {
  it('preserves whitespace and ordered QQ inline segments', () => {
    const segments = editorDocumentToSegments({
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [
            { type: 'text', text: '   ' },
            { type: 'qqMention', attrs: { userId: '123456789', label: '成员' } },
            { type: 'qqFace', attrs: { faceId: '14', name: '微笑' } },
          ],
        },
      ],
    })

    expect(segments).toEqual([
      { type: 'text', text: '   ' },
      { type: 'mention', userId: '123456789', label: '成员', all: false },
      { type: 'face', faceId: '14', name: '微笑', market: false },
    ])
    expect(hasComposerContent(segments)).toBe(true)
  })

  it('converts mention-all and strips transient images from drafts', () => {
    const document = {
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [{ type: 'qqMentionAll' }, { type: 'text', text: ' notice' }],
        },
        {
          type: 'composerImage',
          attrs: { fileId: 'image-1', src: 'blob:https://dududa.test/image-1', alt: 'notice.png' },
        },
      ],
    }

    expect(editorDocumentToSegments(document)).toEqual([
      { type: 'mention', label: '全体成员', all: true },
      { type: 'text', text: ' notice' },
      { type: 'pending_image', fileId: 'image-1', summary: 'notice.png' },
    ])
    expect(serializeComposerDraft(document)).not.toContain('blob:')
    expect(parseComposerDraft(serializeComposerDraft(document))).toEqual({
      type: 'doc',
      content: [{ type: 'paragraph', content: [{ type: 'qqMentionAll' }, { type: 'text', text: ' notice' }] }],
    })
  })
})
