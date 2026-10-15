import { mergeAttributes, Node, type JSONContent } from '@tiptap/core'
import Image from '@tiptap/extension-image'

import type { OutgoingMessageSegment } from '../types/workspace'
import { qqFaceUrl } from './qq-faces'

const RICH_DRAFT_PREFIX = 'dududa-rich-v1:'

export type ComposerContentSegment =
  | OutgoingMessageSegment
  | { type: 'pending_image'; fileId: string; summary: string }

export const QqMentionNode = Node.create({
  name: 'qqMention',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: false,
  addAttributes() {
    return { userId: { default: '' }, label: { default: '' } }
  },
  parseHTML() {
    return [
      {
        tag: 'span[data-qq-mention]',
        getAttrs: (element) => {
          if (!(element instanceof HTMLElement)) return false
          return { userId: element.dataset.userId ?? '', label: element.dataset.label ?? '' }
        },
      },
    ]
  },
  renderHTML({ node, HTMLAttributes }) {
    const label = String(node.attrs.label || node.attrs.userId)
    return [
      'span',
      mergeAttributes(HTMLAttributes, {
        'data-qq-mention': '',
        'data-user-id': String(node.attrs.userId),
        'data-label': label,
        class: 'qq-composer-mention',
      }),
      `@${label}`,
    ]
  },
})

export const QqMentionAllNode = Node.create({
  name: 'qqMentionAll',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: false,
  parseHTML() {
    return [{ tag: 'span[data-qq-mention-all]' }]
  },
  renderHTML({ HTMLAttributes }) {
    return [
      'span',
      mergeAttributes(HTMLAttributes, { 'data-qq-mention-all': '', class: 'qq-composer-mention' }),
      '@全体成员',
    ]
  },
})

export const QqFaceNode = Node.create({
  name: 'qqFace',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: false,
  addAttributes() {
    return { faceId: { default: '' }, name: { default: 'QQ 表情' }, isLarge: { default: false } }
  },
  parseHTML() {
    return [
      {
        tag: 'img[data-qq-face]',
        getAttrs: (element) => {
          if (!(element instanceof HTMLElement)) return false
          return {
            faceId: element.dataset.faceId ?? '',
            name: element.getAttribute('alt') ?? 'QQ 表情',
            isLarge: element.dataset.isLarge === 'true',
          }
        },
      },
    ]
  },
  renderHTML({ node, HTMLAttributes }) {
    const faceId = String(node.attrs.faceId || '')
    return [
      'img',
      mergeAttributes(HTMLAttributes, {
        'data-qq-face': '',
        'data-face-id': faceId,
        'data-is-large': String(node.attrs.isLarge === true),
        src: qqFaceUrl(faceId),
        alt: String(node.attrs.name || `QQ 表情 ${faceId}`),
        title: String(node.attrs.name || `QQ 表情 ${faceId}`),
        class: 'qq-composer-face',
        draggable: 'false',
      }),
    ]
  },
})

export const ComposerImageNode = Image.extend({
  name: 'composerImage',
  group: 'block',
  inline: false,
  draggable: true,
  selectable: true,
  addAttributes() {
    return { ...this.parent?.(), fileId: { default: '' } }
  },
  parseHTML() {
    return [{ tag: 'img[data-composer-image]' }]
  },
  renderHTML({ node, HTMLAttributes }) {
    return [
      'img',
      mergeAttributes(HTMLAttributes, {
        'data-composer-image': '',
        'data-file-id': String(node.attrs.fileId || ''),
        class: 'qq-composer-image',
      }),
    ]
  },
})

function plainTextDocument(text: string): JSONContent {
  return {
    type: 'doc',
    content: text.split('\n').map((line) => ({
      type: 'paragraph',
      ...(line ? { content: [{ type: 'text', text: line }] } : {}),
    })),
  }
}

export function parseComposerDraft(draft: string): JSONContent {
  if (!draft.startsWith(RICH_DRAFT_PREFIX)) return plainTextDocument(draft)
  try {
    const document = JSON.parse(draft.slice(RICH_DRAFT_PREFIX.length)) as JSONContent
    return document.type === 'doc' ? document : plainTextDocument('')
  } catch {
    return plainTextDocument('')
  }
}

export function serializeComposerDraft(document: JSONContent): string {
  function removeTransientImages(node: JSONContent): JSONContent | null {
    if (node.type === 'composerImage') return null
    const content = node.content?.flatMap((child) => {
      const sanitized = removeTransientImages(child)
      return sanitized ? [sanitized] : []
    })
    return { ...node, ...(content ? { content } : {}) }
  }
  return `${RICH_DRAFT_PREFIX}${JSON.stringify(removeTransientImages(document) ?? plainTextDocument(''))}`
}

export function composerImageFileIds(document: JSONContent): string[] {
  const ids: string[] = []
  function visit(node: JSONContent): void {
    if (node.type === 'composerImage') {
      const fileId = String(node.attrs?.fileId ?? '')
      if (fileId) ids.push(fileId)
      return
    }
    node.content?.forEach(visit)
  }
  visit(document)
  return ids
}

function appendText(segments: ComposerContentSegment[], value: string): void {
  if (!value) return
  const previous = segments.at(-1)
  if (previous?.type === 'text') previous.text += value
  else segments.push({ type: 'text', text: value })
}

export function editorDocumentToSegments(document: JSONContent): ComposerContentSegment[] {
  const segments: ComposerContentSegment[] = []
  function visit(node: JSONContent): void {
    if (node.type === 'text') {
      appendText(segments, node.text ?? '')
      return
    }
    if (node.type === 'hardBreak') {
      appendText(segments, '\n')
      return
    }
    if (node.type === 'qqMention') {
      const userId = String(node.attrs?.userId ?? '')
      if (/^\d{5,20}$/.test(userId)) {
        segments.push({ type: 'mention', userId, label: String(node.attrs?.label || userId), all: false })
      }
      return
    }
    if (node.type === 'qqMentionAll') {
      segments.push({ type: 'mention', label: '全体成员', all: true })
      return
    }
    if (node.type === 'qqFace') {
      const faceId = String(node.attrs?.faceId || '')
      if (faceId) {
        segments.push({ type: 'face', faceId, name: String(node.attrs?.name || ''), market: false })
      }
      return
    }
    if (node.type === 'composerImage') {
      const fileId = String(node.attrs?.fileId ?? '')
      if (fileId) segments.push({ type: 'pending_image', fileId, summary: String(node.attrs?.alt || '图片') })
      return
    }
    node.content?.forEach((child, index, children) => {
      const previous = children[index - 1]
      if (
        index > 0 &&
        ['doc', 'bulletList', 'orderedList'].includes(node.type ?? '') &&
        previous?.type !== 'composerImage' &&
        child.type !== 'composerImage'
      ) {
        appendText(segments, '\n')
      }
      visit(child)
    })
  }
  visit(document)
  return segments.filter((segment) => segment.type !== 'text' || Boolean(segment.text))
}

export function hasComposerContent(segments: ComposerContentSegment[]): boolean {
  return segments.some((segment) => segment.type !== 'text' || Boolean(segment.text))
}

export function hasComposerDraft(draft: string): boolean {
  return hasComposerContent(editorDocumentToSegments(parseComposerDraft(draft)))
}
