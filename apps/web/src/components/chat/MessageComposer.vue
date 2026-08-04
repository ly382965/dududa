<script setup lang="ts">
import Document from '@tiptap/extension-document'
import HardBreak from '@tiptap/extension-hard-break'
import Paragraph from '@tiptap/extension-paragraph'
import Text from '@tiptap/extension-text'
import { UndoRedo } from '@tiptap/extensions/undo-redo'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import { AtSign, ImagePlus, LoaderCircle, Paperclip, Search, SendHorizontal, Smile, X } from '@lucide/vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import {
  ComposerImageNode,
  composerImageFileIds,
  editorDocumentToSegments,
  hasComposerContent,
  parseComposerDraft,
  QqFaceNode,
  QqMentionAllNode,
  QqMentionNode,
  serializeComposerDraft,
  type ComposerContentSegment,
} from '../../services/composer-content'
import {
  loadQqFaceCatalog,
  qqFaceCatalog,
  qqFaceCatalogError,
  qqFaceCatalogLoading,
  type QqFaceDefinition,
} from '../../services/qq-faces'
import type { AccountCapabilityDocument, CapabilityName, ChatMessage } from '../../types/workspace'

export interface PendingComposerFile {
  fileId: string
  file: File
}

const draft = defineModel<string>('draft', { required: true })
const replyTo = defineModel<ChatMessage | null>('replyTo', { required: true })
const props = withDefaults(
  defineProps<{
    conversationName: string
    mentionCandidates?: Array<{ userId: string; name: string }>
    canMentionAll?: boolean
    capabilities?: AccountCapabilityDocument['actions']
    sending?: boolean
    uploadStatus?: string
  }>(),
  { mentionCandidates: () => [], canMentionAll: false, sending: false, uploadStatus: '' },
)
const emit = defineEmits<{
  send: [segments: ComposerContentSegment[], files: PendingComposerFile[], complete: (success: boolean) => void]
  filesSelected: [files: File[]]
  searchRequested: []
}>()

const pendingImages = new Map<string, { file: File; previewUrl: string }>()
const imageInput = ref<HTMLInputElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const showFaces = ref(false)
const showMentions = ref(false)
const mentionQuery = ref('')
const mentionRange = ref<{ from: number; to: number } | null>(null)
const segments = ref<ComposerContentSegment[]>(editorDocumentToSegments(parseComposerDraft(draft.value)))
let nextImageId = 0
let draftTimer: ReturnType<typeof setTimeout> | undefined
let applyingDraft = false
let lastDraft = draft.value

const faces = computed(() => [
  ...qqFaceCatalog.value.yellowFaces,
  ...qqFaceCatalog.value.superFaces,
  ...qqFaceCatalog.value.emojiFaces,
].slice(0, 180))
const filteredMentions = computed(() => {
  const query = mentionQuery.value.toLocaleLowerCase('zh-CN')
  const candidates = props.mentionCandidates
    .filter((item) => !query || `${item.name} ${item.userId}`.toLocaleLowerCase('zh-CN').includes(query))
    .slice(0, 20)
  return props.canMentionAll && (!query || '全体成员 all'.includes(query))
    ? [{ userId: 'all', name: '全体成员' }, ...candidates]
    : candidates
})
function capabilitySupported(name: CapabilityName): boolean {
  return props.capabilities?.[name]?.status === 'supported'
}

function capabilityTitle(name: CapabilityName, label: string): string {
  const capability = props.capabilities?.[name]
  return capability?.status === 'supported' ? label : capability?.reason || `${label}当前不可用`
}

function segmentSupported(segment: ComposerContentSegment): boolean {
  if (segment.type === 'text') return capabilitySupported('message.send.text')
  if (segment.type === 'mention') return capabilitySupported('message.send.mention')
  if (segment.type === 'reply') return capabilitySupported('message.send.reply')
  if (segment.type === 'face') return capabilitySupported('message.send.face')
  return capabilitySupported('message.send.image')
}

const canCompose = computed(() =>
  [
    'message.send.text',
    'message.send.mention',
    'message.send.face',
    'message.send.image',
  ].some((name) => capabilitySupported(name as CapabilityName)),
)
const canChooseFiles = computed(() =>
  ['message.send.image', 'message.send.audio', 'message.send.video', 'message.send.file'].some((name) =>
    capabilitySupported(name as CapabilityName),
  ),
)
const canSend = computed(
  () =>
    hasComposerContent(segments.value) &&
    segments.value.every(segmentSupported) &&
    (!replyTo.value || capabilitySupported('message.send.reply')) &&
    !props.sending,
)

const editor = useEditor({
  extensions: [Document, Paragraph, Text, HardBreak, UndoRedo, QqMentionNode, QqMentionAllNode, QqFaceNode, ComposerImageNode],
  content: parseComposerDraft(draft.value),
  editorProps: {
    attributes: { class: 'qq-composer-editor', 'aria-label': 'QQ 消息输入' },
    handleKeyDown: (_view, event) => {
      if (event.key !== 'Enter' || event.shiftKey || event.isComposing || showMentions.value) return false
      event.preventDefault()
      send()
      return true
    },
    handlePaste: (_view, event) => {
      const files = Array.from(event.clipboardData?.files ?? []).filter((file) => file.type.startsWith('image/'))
      if (!files.length) return false
      event.preventDefault()
      insertImages(files)
      return true
    },
    handleDrop: (_view, event) => {
      const files = Array.from(event.dataTransfer?.files ?? []).filter((file) => file.type.startsWith('image/'))
      if (!files.length) return false
      event.preventDefault()
      insertImages(files)
      return true
    },
  },
  onUpdate: () => syncState(),
  onSelectionUpdate: () => updateMentionMenu(),
  onCreate: ({ editor: instance }) => {
    applyingDraft = true
    instance.commands.setContent(parseComposerDraft(draft.value))
    segments.value = editorDocumentToSegments(instance.getJSON())
    instance.setEditable(canCompose.value)
    lastDraft = draft.value
    applyingDraft = false
  },
})

function syncState(): void {
  if (!editor.value) return
  const document = editor.value.getJSON()
  const activeIds = new Set(composerImageFileIds(document))
  for (const [fileId, pending] of pendingImages) {
    if (activeIds.has(fileId)) continue
    URL.revokeObjectURL(pending.previewUrl)
    pendingImages.delete(fileId)
  }
  segments.value = editorDocumentToSegments(document)
  updateMentionMenu()
  if (applyingDraft) return
  clearTimeout(draftTimer)
  const serialized = serializeComposerDraft(document)
  draftTimer = setTimeout(() => {
    lastDraft = serialized
    draft.value = serialized
  }, 250)
}

function updateMentionMenu(): void {
  const instance = editor.value
  if (!instance || !instance.state.selection.empty) {
    closeMentions()
    return
  }
  const { $from } = instance.state.selection
  const before = $from.parent.textBetween(0, $from.parentOffset, undefined, '\ufffc')
  const match = /@([^@\s]{0,24})$/u.exec(before)
  if (!match) {
    closeMentions()
    return
  }
  mentionQuery.value = match[1] ?? ''
  mentionRange.value = { from: $from.pos - match[0].length, to: $from.pos }
  showMentions.value = true
  showFaces.value = false
}

function closeMentions(): void {
  showMentions.value = false
  mentionQuery.value = ''
  mentionRange.value = null
}

function chooseMention(candidate: { userId: string; name: string }): void {
  const range = mentionRange.value
  const instance = editor.value
  if (!instance) return
  const node =
    candidate.userId === 'all'
      ? { type: 'qqMentionAll' }
      : { type: 'qqMention', attrs: { userId: candidate.userId, label: candidate.name } }
  const chain = instance.chain().focus()
  if (range) chain.deleteRange(range)
  chain.insertContent([node, { type: 'text', text: ' ' }]).run()
  closeMentions()
}

function openMention(): void {
  if (!capabilitySupported('message.send.mention')) return
  editor.value?.chain().focus().insertContent('@').run()
  updateMentionMenu()
}

function insertFace(face: QqFaceDefinition): void {
  if (!capabilitySupported('message.send.face')) return
  editor.value
    ?.chain()
    .focus()
    .insertContent({ type: 'qqFace', attrs: { faceId: face.id, name: face.name, isLarge: false } })
    .run()
  showFaces.value = false
}

function toggleFaces(): void {
  if (!capabilitySupported('message.send.face')) return
  showFaces.value = !showFaces.value
  closeMentions()
  if (showFaces.value) void loadQqFaceCatalog().catch(() => undefined)
}

function insertImages(files: Iterable<File>): void {
  if (!capabilitySupported('message.send.image')) return
  const instance = editor.value
  if (!instance) return
  const nodes = Array.from(files)
    .filter((file) => file.type.startsWith('image/'))
    .map((file) => {
      nextImageId += 1
      const fileId = `image-${Date.now()}-${nextImageId}`
      const previewUrl = URL.createObjectURL(file)
      pendingImages.set(fileId, { file, previewUrl })
      return { type: 'composerImage', attrs: { src: previewUrl, alt: file.name || '图片', fileId } }
    })
  if (nodes.length) instance.chain().focus().insertContent([...nodes, { type: 'paragraph' }]).run()
}

function chooseImages(event: Event): void {
  const input = event.target as HTMLInputElement
  insertImages(input.files ?? [])
  input.value = ''
}

function chooseFiles(event: Event): void {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  if (files.length && canChooseFiles.value) emit('filesSelected', files)
  input.value = ''
}

function send(): void {
  if (!canSend.value) return
  const files = [...pendingImages.entries()].map(([fileId, value]) => ({ fileId, file: value.file }))
  const outgoing: ComposerContentSegment[] = [
    ...(replyTo.value
      ? [
          {
            type: 'reply' as const,
            messageId: replyTo.value.messageId,
            messageSeq: replyTo.value.messageSeq,
          },
        ]
      : []),
    ...segments.value,
  ]
  emit('send', outgoing, files, (success) => {
    if (success) clear()
  })
}

function clear(): void {
  for (const pending of pendingImages.values()) URL.revokeObjectURL(pending.previewUrl)
  pendingImages.clear()
  editor.value?.commands.setContent({ type: 'doc', content: [{ type: 'paragraph' }] })
  replyTo.value = null
  lastDraft = ''
  draft.value = ''
}

function focus(): void {
  editor.value?.commands.focus()
}

watch(draft, (value) => {
  if (!editor.value || value === lastDraft) return
  applyingDraft = true
  editor.value.commands.setContent(parseComposerDraft(value))
  segments.value = editorDocumentToSegments(editor.value.getJSON())
  lastDraft = value
  applyingDraft = false
})

watch(
  canCompose,
  (value) => editor.value?.setEditable(value),
  { immediate: true },
)

onBeforeUnmount(() => {
  clearTimeout(draftTimer)
  if (editor.value && !applyingDraft) {
    const serialized = serializeComposerDraft(editor.value.getJSON())
    if (serialized !== lastDraft) {
      lastDraft = serialized
      draft.value = serialized
    }
  }
  for (const pending of pendingImages.values()) URL.revokeObjectURL(pending.previewUrl)
})

defineExpose({ clear, focus, chooseMention })
</script>

<template>
  <div class="message-composer">
    <div v-if="replyTo" class="composer-reply">
      <div><strong>回复 {{ replyTo.senderName }}</strong><span>{{ replyTo.content }}</span></div>
      <button type="button" title="取消回复" @click="replyTo = null"><X :size="15" /></button>
    </div>
    <div class="composer-toolbar">
      <div>
        <button type="button" :title="capabilityTitle('message.send.face', 'QQ 表情')" :disabled="!capabilitySupported('message.send.face')" @click="toggleFaces"><Smile :size="18" /></button>
        <button type="button" :title="capabilityTitle('message.send.mention', '提及成员')" :disabled="!capabilitySupported('message.send.mention')" @click="openMention"><AtSign :size="18" /></button>
        <button type="button" :title="capabilityTitle('message.send.image', '选择图片')" :disabled="!capabilitySupported('message.send.image')" @click="imageInput?.click()"><ImagePlus :size="18" /></button>
        <button type="button" :title="canChooseFiles ? '选择文件' : '当前账号不支持文件或媒体发送'" :disabled="!canChooseFiles" @click="fileInput?.click()"><Paperclip :size="18" /></button>
        <button type="button" title="搜索聊天记录" @click="emit('searchRequested')"><Search :size="18" /></button>
      </div>
      <small>Enter 发送 · Shift+Enter 换行</small>
    </div>
    <div class="composer-editor-wrap">
      <EditorContent :editor="editor" />
      <div v-if="showMentions" class="mention-picker">
        <button
          v-for="candidate in filteredMentions"
          :key="candidate.userId"
          type="button"
          @mousedown.prevent="chooseMention(candidate)"
        >
          <strong>{{ candidate.name }}</strong><span>{{ candidate.userId === 'all' ? '@全体成员' : candidate.userId }}</span>
        </button>
        <span v-if="!filteredMentions.length">没有匹配的最近发言成员</span>
      </div>
      <div v-if="showFaces" class="face-picker">
        <div v-if="qqFaceCatalogLoading" class="picker-state"><LoaderCircle class="spin" :size="18" />加载 QQ 表情</div>
        <button v-for="face in faces" v-else :key="face.id" type="button" :title="face.name" @click="insertFace(face)">
          <img :src="face.apngUrl || face.pngUrl" :alt="face.name" />
        </button>
        <button v-if="qqFaceCatalogError" class="picker-retry" type="button" @click="loadQqFaceCatalog(true)">重新加载</button>
      </div>
    </div>
    <div class="composer-footer">
      <span>{{ uploadStatus || conversationName }}</span>
      <button class="composer-send" type="button" title="发送消息" :disabled="!canSend" @click="send">
        <LoaderCircle v-if="sending" class="spin" :size="17" />
        <SendHorizontal v-else :size="17" />
      </button>
    </div>
    <input ref="imageInput" hidden type="file" accept="image/*" multiple :disabled="!capabilitySupported('message.send.image')" @change="chooseImages" />
    <input ref="fileInput" hidden type="file" multiple :disabled="!canChooseFiles" @change="chooseFiles" />
  </div>
</template>

<style scoped>
.message-composer { position: relative; display: flex; min-height: 150px; flex-direction: column; border-top: 1px solid var(--border); background: var(--surface); padding: 7px 13px 9px; }
.composer-reply { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 0 3px 5px; border-left: 2px solid var(--brand); background: var(--surface-subtle); padding: 5px 7px; }
.composer-reply div { min-width: 0; }
.composer-reply strong, .composer-reply span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.composer-reply strong { color: var(--brand-strong); font-size: 10px; }
.composer-reply span { color: var(--text-muted); font-size: 9px; }
.composer-reply button { cursor: pointer; border: 0; color: var(--text-muted); background: transparent; }
.composer-toolbar, .composer-footer { display: flex; align-items: center; justify-content: space-between; }
.composer-toolbar > div { display: flex; gap: 2px; }
.composer-toolbar button { display: grid; width: 30px; height: 28px; cursor: pointer; place-items: center; border: 0; border-radius: 5px; color: var(--text-muted); background: transparent; }
.composer-toolbar button:hover { color: var(--brand-strong); background: var(--surface-hover); }
.composer-toolbar button:disabled { cursor: not-allowed; opacity: .38; }
.composer-toolbar small { color: var(--text-muted); font-size: 9px; }
.composer-editor-wrap { position: relative; min-height: 72px; flex: 1; }
:deep(.qq-composer-editor) { min-height: 68px; max-height: 190px; overflow-y: auto; color: var(--text); padding: 7px 5px; font-size: 12px; line-height: 1.55; outline: none; }
:deep(.qq-composer-editor p) { margin: 0; }
:deep(.qq-composer-mention) { color: var(--brand-strong); font-weight: 650; }
:deep(.qq-composer-face) { display: inline-block; width: 24px; height: 24px; object-fit: contain; vertical-align: middle; }
:deep(.qq-composer-image) { display: block; max-width: 240px; max-height: 130px; margin: 5px 0; border-radius: 6px; object-fit: contain; }
.mention-picker, .face-picker { position: absolute; z-index: 40; left: 4px; bottom: calc(100% + 4px); max-height: 260px; overflow-y: auto; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); box-shadow: var(--floating-shadow); padding: 5px; }
.mention-picker { display: grid; width: min(300px, calc(100vw - 40px)); }
.mention-picker button { display: flex; cursor: pointer; align-items: center; justify-content: space-between; gap: 12px; border: 0; border-radius: 4px; color: var(--text); background: transparent; padding: 7px 8px; text-align: left; }
.mention-picker button:hover { background: var(--surface-hover); }
.mention-picker span, .mention-picker button span { color: var(--text-muted); font-size: 9px; }
.face-picker { display: grid; width: min(390px, calc(100vw - 40px)); grid-template-columns: repeat(9, 34px); gap: 3px; }
.face-picker button { display: grid; width: 34px; height: 34px; cursor: pointer; place-items: center; border: 0; border-radius: 4px; background: transparent; }
.face-picker button:hover { background: var(--surface-hover); }
.face-picker img { width: 25px; height: 25px; object-fit: contain; }
.picker-state { display: flex; grid-column: 1 / -1; align-items: center; justify-content: center; gap: 7px; color: var(--text-muted); padding: 18px; font-size: 10px; }
.face-picker .picker-retry { width: auto; grid-column: 1 / -1; color: var(--danger); }
.composer-footer { height: 31px; color: var(--text-muted); font-size: 9px; }
.composer-send { display: grid; width: 38px; height: 30px; cursor: pointer; place-items: center; border: 0; border-radius: 6px; color: #fff; background: var(--brand); }
.composer-send:disabled { cursor: not-allowed; opacity: .42; }
.spin { animation: spin 800ms linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 560px) { .composer-toolbar small { display: none; } .face-picker { grid-template-columns: repeat(7, 34px); } }
</style>
