<script setup lang="ts">
import { useVirtualizer } from '@tanstack/vue-virtual'
import {
  ArrowDown,
  ArrowLeft,
  BellOff,
  Info,
  LoaderCircle,
  MessageSquareReply,
  PanelRight,
  Search,
  Sparkles,
  Users,
} from '@lucide/vue'
import { computed, nextTick, ref, watch, type ComponentPublicInstance } from 'vue'

import type { ComposerContentSegment } from '../services/composer-content'
import type { Account, ChatMessage, Conversation, CustomFaceCatalog, MessageSegment } from '../types/workspace'
import AppAvatar from './AppAvatar.vue'
import FileSendDialog from './chat/FileSendDialog.vue'
import MergedForwardViewerDialog from './chat/MergedForwardViewerDialog.vue'
import MessageBubble from './chat/MessageBubble.vue'
import MessageComposer, { type PendingComposerFile } from './chat/MessageComposer.vue'
import MessageForwardDialog from './chat/MessageForwardDialog.vue'
import MessageSearchDialog from './chat/MessageSearchDialog.vue'

const props = defineProps<{
  conversation?: Conversation
  account?: Account
  conversations: Conversation[]
  messages: ChatMessage[]
  draft: string
  replyTo: ChatMessage | null
  mentionCandidates: Array<{ userId: string; name: string }>
  canMentionAll: boolean
  selectedMessageId: string
  unreadTargetId?: string
  unreadCount?: number
  agentCollapsed: boolean
  loading: boolean
  error: string
  sending: boolean
  uploadStatus: string
  history: {
    hasMoreBefore: boolean
    hasMoreAfter: boolean
    loadingBefore: boolean
    loadingAfter: boolean
  }
  loadOlder: () => Promise<void>
  loadNewer: () => Promise<void>
  loadLatest: () => Promise<void>
  sendRich: (
    segments: ComposerContentSegment[],
    files: PendingComposerFile[],
    complete: (success: boolean) => void,
  ) => Promise<void>
  sendFiles: (files: File[]) => Promise<boolean>
  loadCustomFaces: () => Promise<CustomFaceCatalog>
  sendCustomFace: (handle: string) => Promise<boolean>
  recallMessage: (message: ChatMessage) => Promise<void>
  refreshMessage: (message: ChatMessage) => Promise<void>
  loadMessageFile: (message: ChatMessage, fileId: string) => Promise<void>
  forwardMessage: (message: ChatMessage, target: Conversation) => Promise<boolean>
  nudgeMessage: (message: ChatMessage) => Promise<void>
}>()

const emit = defineEmits<{
  updateDraft: [conversationId: string, value: string]
  updateReplyTo: [conversationId: string, value: ChatMessage | null]
  sendToAgent: [message: ChatMessage]
  openAgent: []
  back: []
  notify: [message: string]
  openGroup: [groupId: string]
  jumpMessage: [message: ChatMessage]
  consumeUnread: [conversationId: string]
}>()

const messageList = ref<HTMLElement | null>(null)
const showLatest = ref(false)
const searchOpen = ref(false)
const forwardMessage = ref<ChatMessage>()
const forwarding = ref(false)
const forwardId = ref('')
const forwardViewerOpen = ref(false)
const loadingBoundary = ref(false)
const pendingFiles = ref<File[]>([])
let conversationVersion = 0

const virtualizerOptions = computed(() => ({
  count: props.messages.length,
  getScrollElement: () => messageList.value,
  estimateSize: () => 92,
  overscan: 10,
  paddingStart: 18,
  paddingEnd: 22,
  getItemKey: (index: number) => props.messages[index]?.id ?? index,
  useAnimationFrameWithResizeObserver: true,
}))
const rowVirtualizer = useVirtualizer<HTMLElement, HTMLElement>(virtualizerOptions)
const virtualRows = computed(() => rowVirtualizer.value.getVirtualItems())
const totalSize = computed(() => rowVirtualizer.value.getTotalSize())
const senders = computed(() => {
  const byId = new Map<string, string>()
  props.messages.forEach((message) => byId.set(message.senderId, message.senderName))
  return [...byId].map(([userId, name]) => ({ userId, name }))
})
const unreadTargetIndex = computed(() => props.messages.findIndex((message) => message.id === props.unreadTargetId))
const plusOneMessage = computed<{ id: string; segments: ComposerContentSegment[] } | null>(() => {
  if (props.conversation?.type !== 'group' || props.history.hasMoreAfter || props.messages.length < 2) return null
  const previous = props.messages.at(-2)
  const current = props.messages.at(-1)
  if (!previous || !current || previous.status === 'recalled' || current.status === 'recalled') return null
  const previousSequence = Number(previous.messageSeq)
  const currentSequence = Number(current.messageSeq)
  if (!Number.isFinite(previousSequence) || currentSequence !== previousSequence + 1) return null
  const resendable = (message: ChatMessage): ComposerContentSegment[] | null => {
    const segments: ComposerContentSegment[] = []
    for (const segment of message.segments) {
      if (segment.type === 'reply') continue
      if (segment.type === 'text' || segment.type === 'mention') segments.push(segment)
      else if (segment.type === 'face' && !segment.market) {
        segments.push({ type: 'face', faceId: segment.faceId, name: segment.name, market: false })
      } else return null
    }
    return segments.length ? segments : null
  }
  const previousSegments = resendable(previous)
  const currentSegments = resendable(current)
  return previousSegments && currentSegments && JSON.stringify(previousSegments) === JSON.stringify(currentSegments)
    ? { id: current.id, segments: currentSegments }
    : null
})

function setRowRef(element: Element | ComponentPublicInstance | null): void {
  if (element instanceof HTMLElement) rowVirtualizer.value.measureElement(element)
}

function nearBottom(): boolean {
  const element = messageList.value
  return Boolean(element && element.scrollHeight - element.scrollTop - element.clientHeight < 80)
}

async function scrollToLatest(): Promise<void> {
  if (props.history.hasMoreAfter) await props.loadLatest()
  await nextTick()
  if (props.messages.length) rowVirtualizer.value.scrollToIndex(props.messages.length - 1, { align: 'end' })
  showLatest.value = false
}

async function loadOlderAtBoundary(): Promise<void> {
  const element = messageList.value
  if (!element || loadingBoundary.value || !props.history.hasMoreBefore || props.history.loadingBefore) return
  loadingBoundary.value = true
  const visible = virtualRows.value.find((row) => row.end > element.scrollTop)
  const anchorId = visible ? props.messages[visible.index]?.id : undefined
  const anchorViewportOffset = visible ? visible.start - element.scrollTop : 0
  try {
    await props.loadOlder()
    await nextTick()
    if (anchorId) {
      const index = props.messages.findIndex((message) => message.id === anchorId)
      if (index >= 0) {
        rowVirtualizer.value.scrollToIndex(index, { align: 'start' })
        await nextTick()
        const row = rowVirtualizer.value.getVirtualItems().find((item) => item.index === index)
        if (row) element.scrollTop = row.start - anchorViewportOffset
      }
    }
  } finally {
    loadingBoundary.value = false
  }
}

function onScroll(): void {
  const element = messageList.value
  if (!element) return
  showLatest.value = !nearBottom()
  if (element.scrollTop < Math.max(420, element.clientHeight * 0.8)) void loadOlderAtBoundary()
  if (
    props.history.hasMoreAfter &&
    !props.history.loadingAfter &&
    element.scrollHeight - element.scrollTop - element.clientHeight < Math.max(420, element.clientHeight * 0.8)
  ) {
    void props.loadNewer()
  }
}

function timeDivider(index: number): string {
  const current = props.messages[index]
  const previous = props.messages[index - 1]
  if (!current?.timestampMs || (previous?.timestampMs && current.timestampMs - previous.timestampMs < 5 * 60_000)) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(current.timestampMs))
}

async function revealMessage(messageId?: string, messageSeq?: string): Promise<void> {
  const expectedVersion = conversationVersion
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const index = props.messages.findIndex(
      (message) => (messageId && message.messageId === messageId) || (messageSeq && message.messageSeq === messageSeq),
    )
    if (index >= 0) {
      rowVirtualizer.value.scrollToIndex(index, { align: 'center' })
      emit('jumpMessage', props.messages[index]!)
      return
    }
    if (!props.history.hasMoreBefore || expectedVersion !== conversationVersion) break
    await props.loadOlder()
    await nextTick()
  }
  emit('notify', '本地缓存和可用历史中没有找到该消息')
}

function jumpReply(segment: Extract<MessageSegment, { type: 'reply' }>): void {
  void revealMessage(segment.messageId, segment.messageSeq)
}

async function revealUnreadTarget(): Promise<void> {
  const index = unreadTargetIndex.value
  if (index < 0) return
  await nextTick()
  rowVirtualizer.value.scrollToIndex(index, { align: 'center' })
}

function selectSearchResult(message: ChatMessage): void {
  searchOpen.value = false
  void revealMessage(message.messageId, message.messageSeq)
}

function openForwardViewer(segment: Extract<MessageSegment, { type: 'forward' }>): void {
  forwardId.value = segment.forwardId
  forwardViewerOpen.value = true
}

async function submitForward(target: Conversation): Promise<void> {
  if (!forwardMessage.value || forwarding.value) return
  forwarding.value = true
  try {
    if (await props.forwardMessage(forwardMessage.value, target)) forwardMessage.value = undefined
  } finally {
    forwarding.value = false
  }
}

function sendPlusOne(messageId: string): void {
  const repeated = plusOneMessage.value
  if (!repeated || repeated.id !== messageId || props.sending) return
  void props.sendRich(repeated.segments, [], () => undefined)
}

async function sendFavoriteFace(handle: string): Promise<void> {
  if (props.sending) return
  const sending = props.sendCustomFace(handle)
  await nextTick()
  await scrollToLatest()
  await sending
}

function queueFiles(files: File[]): void {
  pendingFiles.value = files
}

async function confirmFiles(): Promise<void> {
  if (!pendingFiles.value.length || props.sending) return
  if (await props.sendFiles(pendingFiles.value)) pendingFiles.value = []
}

function confirmRecall(message: ChatMessage): void {
  if (window.confirm(`确认撤回这条发送给 ${props.conversation?.name || '当前会话'} 的消息？`)) {
    void props.recallMessage(message)
  }
}

watch(
  () => props.conversation?.id,
  async () => {
    conversationVersion += 1
    searchOpen.value = false
    forwardMessage.value = undefined
    forwardViewerOpen.value = false
    pendingFiles.value = []
    await nextTick()
    if (props.unreadTargetId) await revealUnreadTarget()
    else await scrollToLatest()
  },
  { immediate: true },
)

watch(
  () => props.messages.at(-1)?.id,
  async (_next, previous) => {
    if (props.unreadTargetId) {
      await revealUnreadTarget()
      return
    }
    if (!previous || nearBottom()) await scrollToLatest()
    else showLatest.value = true
  },
)

watch([() => props.unreadTargetId, () => props.messages.length], () => void revealUnreadTarget())
</script>

<template>
  <main class="chat-pane">
    <template v-if="conversation">
      <header class="chat-header">
        <button class="icon-button mobile-back" type="button" title="返回会话" @click="emit('back')"><ArrowLeft :size="20" /></button>
        <AppAvatar class="chat-header__avatar" :src="conversation.avatar" :name="conversation.name" size="sm" />
        <div class="chat-heading">
          <div class="chat-heading__title"><h2>{{ conversation.name }}</h2><span v-if="conversation.type === 'group'" class="type-chip">群</span><BellOff v-if="conversation.muted" :size="13" /></div>
          <p v-if="conversation.type === 'group'">{{ conversation.members || 0 }} 位成员 · {{ conversation.topic || conversation.peerId }}</p>
          <p v-else>来自 {{ account?.name }} · {{ conversation.peerId }}</p>
        </div>
        <div class="chat-actions">
          <button class="icon-button" type="button" title="搜索聊天记录" @click="searchOpen = true"><Search :size="18" /></button>
          <button v-if="conversation.type === 'group'" class="icon-button secondary-action" type="button" title="群聊管理" @click="emit('openGroup', conversation.peerId)"><Users :size="18" /></button>
          <button class="icon-button agent-toggle" :class="{ active: !agentCollapsed }" type="button" title="Agent Console" @click="emit('openAgent')"><PanelRight :size="18" /></button>
        </div>
      </header>

      <section ref="messageList" class="message-list" aria-label="聊天消息" @scroll.passive="onScroll">
        <div v-if="loading && !messages.length" class="chat-empty"><LoaderCircle class="spin" :size="27" /><strong>正在从 NapCat 读取消息</strong></div>
        <div v-else-if="error && !messages.length" class="chat-empty error-state"><Info :size="27" /><strong>{{ error }}</strong></div>
        <div v-else-if="messages.length" class="virtual-list" :style="{ height: `${totalSize}px` }">
          <div
            v-for="row in virtualRows"
            :key="String(row.key)"
            :ref="setRowRef"
            class="virtual-row"
            :data-index="row.index"
            :style="{ transform: `translateY(${row.start}px)` }"
          >
            <div v-if="timeDivider(row.index)" class="date-divider"><span>{{ timeDivider(row.index) }}</span></div>
            <div v-if="messages[row.index]!.id === unreadTargetId" class="unread-divider">
              <button type="button" @click="conversation && emit('consumeUnread', conversation.id)">
                {{ unreadCount || 1 }} 条新消息
              </button>
            </div>
            <MessageBubble
              :message="messages[row.index]!"
              :conversation="conversation"
              :account="account"
              :selected="messages[row.index]!.id === selectedMessageId"
              :plus-one="plusOneMessage?.id === messages[row.index]!.id"
              @reply="emit('updateReplyTo', conversation.id, $event)"
              @recall="confirmRecall"
              @refresh-media="refreshMessage"
              @load-file="loadMessageFile"
              @plus-one="sendPlusOne(messages[row.index]!.id)"
              @forward="forwardMessage = $event"
              @nudge="nudgeMessage"
              @jump="jumpReply"
              @open-forward="openForwardViewer"
              @send-to-agent="emit('sendToAgent', $event)"
            />
          </div>
        </div>
        <div v-else-if="!loading && !error" class="chat-empty"><MessageSquareReply :size="30" /><strong>还没有消息</strong></div>
        <button v-if="history.loadingBefore" class="history-loading top" type="button" disabled><LoaderCircle class="spin" :size="14" />加载更早消息</button>
        <button v-if="showLatest" class="latest-button" type="button" @click="scrollToLatest"><ArrowDown :size="16" />回到最新</button>
      </section>

      <MessageComposer
        :key="conversation.id"
        :draft="draft"
        :reply-to="replyTo"
        :conversation-name="conversation.name"
        :mention-candidates="mentionCandidates"
        :can-mention-all="canMentionAll"
        :capabilities="account?.capabilities"
        :load-custom-faces="loadCustomFaces"
        :sending="sending"
        :upload-status="uploadStatus"
        @update:draft="emit('updateDraft', conversation.id, $event)"
        @update:reply-to="emit('updateReplyTo', conversation.id, $event)"
        @send="sendRich"
        @files-selected="queueFiles"
        @favorite-selected="sendFavoriteFace"
        @search-requested="searchOpen = true"
      />

      <MessageSearchDialog :open="searchOpen" :conversation="conversation" :senders="senders" @close="searchOpen = false" @select="selectSearchResult" />
      <MessageForwardDialog
        :open="Boolean(forwardMessage)"
        :message="forwardMessage"
        :source="conversation"
        :conversations="conversations"
        :sending="forwarding"
        @close="forwardMessage = undefined"
        @submit="submitForward"
      />
      <MergedForwardViewerDialog
        :open="forwardViewerOpen"
        :conversation="conversation"
        :account="account"
        :forward-id="forwardId"
        @close="forwardViewerOpen = false"
        @refresh-media="refreshMessage"
        @load-file="loadMessageFile"
      />
      <FileSendDialog
        :open="Boolean(pendingFiles.length)"
        :files="pendingFiles"
        :conversation-name="conversation.name"
        :busy="sending"
        :status="uploadStatus"
        @cancel="pendingFiles = []"
        @confirm="confirmFiles"
      />
    </template>
    <div v-else class="chat-placeholder"><Sparkles :size="34" /><strong>选择一个会话</strong></div>
  </main>
</template>

<style scoped>
.chat-pane { display: flex; min-width: 0; min-height: 0; flex-direction: column; background: var(--chat-background); }
.chat-header { display: flex; height: 64px; min-width: 0; flex: 0 0 auto; align-items: center; gap: 10px; border-bottom: 1px solid var(--border); background: var(--surface-glass); padding: 0 14px 0 18px; backdrop-filter: blur(12px); }
.mobile-back, .chat-header__avatar { display: none; }.chat-heading { min-width: 0; flex: 1; }.chat-heading__title { display: flex; min-width: 0; align-items: center; gap: 7px; }.chat-heading h2 { overflow: hidden; margin: 0; color: var(--text); font-size: 15px; text-overflow: ellipsis; white-space: nowrap; }.chat-heading p { overflow: hidden; margin: 3px 0 0; color: var(--text-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.type-chip { display: grid; width: 19px; height: 17px; place-items: center; border-radius: 4px; color: var(--brand-strong); background: var(--brand-soft-strong); font-size: 9px; font-weight: 700; }
.chat-actions { display: flex; align-items: center; gap: 2px; }.agent-toggle.active { color: var(--brand-strong); background: var(--brand-soft); }
.message-list { position: relative; min-height: 0; flex: 1; overflow-y: auto; overscroll-behavior: contain; padding: 0 clamp(14px, 3vw, 34px); }.virtual-list { position: relative; width: 100%; }.virtual-row { position: absolute; top: 0; left: 0; width: 100%; padding-bottom: 8px; }.date-divider { display: flex; align-items: center; justify-content: center; padding: 8px 0; }.date-divider span { border: 1px solid var(--border); border-radius: 4px; color: var(--text-muted); background: var(--surface-glass); padding: 3px 8px; font-size: 9px; }
.unread-divider { display: flex; align-items: center; gap: 8px; padding: 7px 0; }.unread-divider::before, .unread-divider::after { height: 1px; flex: 1; background: var(--brand-border); content: ''; }.unread-divider button { cursor: pointer; border: 0; color: var(--brand-strong); background: transparent; padding: 2px 5px; font-size: 9px; }
.latest-button { position: sticky; z-index: 20; left: 50%; bottom: 14px; display: flex; cursor: pointer; transform: translateX(-50%); align-items: center; gap: 5px; border: 1px solid var(--border); border-radius: 16px; color: var(--brand-strong); background: var(--surface); box-shadow: var(--floating-shadow); padding: 7px 11px; font-size: 10px; }.history-loading { position: sticky; z-index: 20; left: 50%; display: flex; transform: translateX(-50%); align-items: center; gap: 5px; border: 0; border-radius: 12px; color: var(--text-muted); background: var(--surface-glass); padding: 5px 9px; font-size: 9px; }.history-loading.top { top: 8px; }
.chat-empty, .chat-placeholder { display: flex; height: 100%; min-height: 180px; flex-direction: column; align-items: center; justify-content: center; gap: 10px; color: var(--text-muted); }.chat-empty strong, .chat-placeholder strong { color: var(--text-secondary); font-size: 12px; }.error-state { color: var(--danger); }.spin { animation: spin 800ms linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1120px) { .chat-header__avatar { display: inline-grid; }.secondary-action { display: none; } }
@media (max-width: 860px) { .chat-header { height: 60px; padding: 0 10px; }.mobile-back, .chat-header__avatar { display: grid; }.chat-heading p { max-width: 52vw; }.message-list { padding: 0 10px; } }
@media (max-width: 480px) { .chat-header__avatar { display: none; }.chat-heading p { max-width: 45vw; } }
</style>
