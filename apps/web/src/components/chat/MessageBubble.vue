<script setup lang="ts">
import {
  Copy,
  Download,
  FileText,
  Forward,
  MessageSquareReply,
  MoreHorizontal,
  RotateCcw,
  Sparkles,
  Undo2,
} from '@lucide/vue'
import { computed, onBeforeUnmount, ref } from 'vue'

import { linkifiedTextParts, renderMarkdown } from '../../services/markdown'
import type { Account, ChatMessage, Conversation, MessageSegment } from '../../types/workspace'
import AppAvatar from '../AppAvatar.vue'
import QqFace from './QqFace.vue'

const props = defineProps<{
  message: ChatMessage
  conversation: Conversation
  account?: Account
  selected?: boolean
  plusOne?: boolean
  readonly?: boolean
}>()

const emit = defineEmits<{
  reply: [message: ChatMessage]
  recall: [message: ChatMessage]
  refreshMedia: [message: ChatMessage]
  loadFile: [message: ChatMessage, fileId: string]
  plusOne: []
  forward: [message: ChatMessage]
  nudge: [message: ChatMessage]
  jump: [segment: Extract<MessageSegment, { type: 'reply' }>]
  openForward: [segment: Extract<MessageSegment, { type: 'forward' }>]
  sendToAgent: [message: ChatMessage]
}>()

const menuOpen = ref(false)
const copied = ref(false)
const swipeDistance = ref(0)
const requestedMediaRefreshes = new Set<string>()
const largeFace = computed(
  () => props.message.segments.length === 1 && props.message.segments[0]?.type === 'face',
)
const canRecall = computed(
  () =>
    !props.readonly &&
    props.message.mine &&
    props.message.status !== 'recalled' &&
    Boolean(props.message.timestampMs) &&
    Date.now() - props.message.timestampMs! <= 3 * 60_000 &&
    props.account?.capabilities?.['message.recall']?.status === 'supported',
)
const canForward = computed(() => !props.readonly && props.account?.capabilities?.['message.forward']?.status === 'supported')
const canNudge = computed(() => !props.readonly && props.account?.capabilities?.['message.nudge']?.status === 'supported')
const canDownloadFile = computed(() => props.account?.capabilities?.['message.download.file']?.status === 'supported')
let touchStart: { x: number; y: number } | undefined
let longPressTimer: ReturnType<typeof setTimeout> | undefined

function cancelLongPress(): void {
  clearTimeout(longPressTimer)
  longPressTimer = undefined
}

function onTouchStart(event: TouchEvent): void {
  const touch = event.touches[0]
  if (!touch) return
  touchStart = { x: touch.clientX, y: touch.clientY }
  swipeDistance.value = 0
  cancelLongPress()
  longPressTimer = setTimeout(() => {
    menuOpen.value = true
  }, 450)
}

function onTouchMove(event: TouchEvent): void {
  const touch = event.touches[0]
  if (!touch || !touchStart) return
  const deltaX = touch.clientX - touchStart.x
  const deltaY = touch.clientY - touchStart.y
  if (Math.abs(deltaX) > 8 || Math.abs(deltaY) > 8) cancelLongPress()
  if (deltaX > 0 && Math.abs(deltaX) > Math.abs(deltaY)) swipeDistance.value = Math.min(deltaX, 72)
}

function onTouchEnd(): void {
  cancelLongPress()
  if (swipeDistance.value >= 56) emit('reply', props.message)
  swipeDistance.value = 0
  touchStart = undefined
}

async function copyMessage(): Promise<void> {
  await navigator.clipboard.writeText(props.message.content)
  copied.value = true
  window.setTimeout(() => (copied.value = false), 1_500)
  menuOpen.value = false
}

function markdown(segment: Extract<MessageSegment, { type: 'markdown' }>): string {
  return renderMarkdown(segment.content)
}

function refreshMedia(index: number, segment: MessageSegment): void {
  const source = 'url' in segment ? segment.url : undefined
  const key = `${index}:${source ?? 'missing'}`
  if (requestedMediaRefreshes.has(key)) return
  requestedMediaRefreshes.add(key)
  emit('refreshMedia', props.message)
}

onBeforeUnmount(cancelLongPress)
</script>

<template>
  <article
    class="message-row"
    :class="{ mine: message.mine, selected, recalled: message.status === 'recalled', 'menu-open': menuOpen }"
    :data-message-id="message.id"
    :style="{ transform: `translate3d(${swipeDistance}px, 0, 0)` }"
    @contextmenu.prevent="!readonly && (menuOpen = true)"
    @touchstart="!readonly && onTouchStart($event)"
    @touchmove="!readonly && onTouchMove($event)"
    @touchend="!readonly && onTouchEnd()"
    @touchcancel="!readonly && onTouchEnd()"
  >
    <span class="swipe-indicator" :class="{ ready: swipeDistance >= 56 }"><MessageSquareReply :size="15" /></span>
    <button
      class="message-avatar-button"
      type="button"
      :title="canNudge ? `戳一戳 ${message.senderName}` : message.senderName"
      @dblclick="canNudge && emit('nudge', message)"
    >
      <AppAvatar :src="message.senderAvatar" :name="message.senderName" size="sm" />
    </button>
    <div class="message-column">
      <div class="message-meta">
        <span>{{ message.senderName }}</span>
        <span v-if="message.role === 'owner'" class="role-tag owner">群主</span>
        <span v-else-if="message.role === 'admin'" class="role-tag">管理员</span>
        <time>{{ message.timestamp }}</time>
      </div>
      <div class="message-and-actions">
        <div class="message-bubble" :class="{ bot: message.bot, 'large-face': largeFace }">
          <em v-if="message.status === 'recalled'" class="recalled-label">此消息已撤回</em>
          <template v-else>
            <template v-for="(segment, index) in message.segments" :key="`${message.id}-${index}`">
              <span v-if="segment.type === 'text'" class="message-text">
                <template v-for="(part, partIndex) in linkifiedTextParts(segment.text)" :key="partIndex">
                  <a v-if="part.href" :href="part.href" target="_blank" rel="noopener noreferrer nofollow">{{ part.text }}</a>
                  <template v-else>{{ part.text }}</template>
                </template>
              </span>
              <span
                v-else-if="segment.type === 'mention'"
                class="mention-segment"
              >
                @{{ segment.label || segment.userId || '全体成员' }}
              </span>
              <button
                v-else-if="segment.type === 'reply'"
                class="reply-segment"
                type="button"
                @click="emit('jump', segment)"
              >
                <strong>{{ segment.senderName || '引用消息' }}</strong>
                <span>{{ segment.preview || `消息 ${segment.messageSeq || segment.messageId || ''}` }}</span>
              </button>
              <QqFace
                v-else-if="segment.type === 'face'"
                :face-id="segment.faceId"
                :large="largeFace"
                :url="segment.url"
                :name="segment.name"
                :market="segment.market"
                @failed="segment.url && refreshMedia(index, segment)"
              />
              <a
                v-else-if="segment.type === 'image' && segment.url"
                class="media-link"
                :href="segment.url"
                target="_blank"
                rel="noopener noreferrer"
              >
                <img class="message-image" :src="segment.url" :alt="segment.summary || segment.name || '聊天图片'" @error="refreshMedia(index, segment)" />
              </a>
              <button v-else-if="segment.type === 'image'" class="unsupported-segment" type="button" @click="refreshMedia(index, segment)">图片暂时不可用 · 重新获取</button>
              <audio v-else-if="segment.type === 'audio' && segment.url" class="message-audio" :src="segment.url" controls preload="metadata" @error="refreshMedia(index, segment)" />
              <button v-else-if="segment.type === 'audio'" class="unsupported-segment" type="button" @click="refreshMedia(index, segment)">语音暂时不可用 · 重新获取</button>
              <video v-else-if="segment.type === 'video' && segment.url" class="message-video" :src="segment.url" controls preload="metadata" @error="refreshMedia(index, segment)" />
              <button v-else-if="segment.type === 'video'" class="unsupported-segment" type="button" @click="refreshMedia(index, segment)">视频暂时不可用 · 重新获取</button>
              <a
                v-else-if="segment.type === 'file' && segment.url"
                class="file-segment"
                :href="segment.url"
                target="_blank"
                rel="noopener noreferrer"
              >
                <FileText :size="22" />
                <span><strong>{{ segment.name || '文件' }}</strong><small>{{ segment.size ? `${segment.size} B` : '' }}</small></span>
                <Download :size="16" />
              </a>
              <button
                v-else-if="segment.type === 'file'"
                class="file-segment disabled"
                type="button"
                :disabled="!segment.fileId || !canDownloadFile"
                :title="account?.capabilities?.['message.download.file']?.reason || '获取文件下载地址'"
                @click="segment.fileId && emit('loadFile', message, segment.fileId)"
              >
                <FileText :size="22" />
                <span><strong>{{ segment.name || '文件' }}</strong><small>{{ segment.fileId && canDownloadFile ? '点击获取下载地址' : '下载地址不可用' }}</small></span>
              </button>
              <button
                v-else-if="segment.type === 'forward'"
                class="forward-segment"
                type="button"
                @click="emit('openForward', segment)"
              >
                <Forward :size="17" />
                <span><strong>合并转发消息</strong><small>{{ segment.preview || (segment.count ? `${segment.count} 条消息` : '点击查看') }}</small></span>
              </button>
              <div v-else-if="segment.type === 'markdown'" class="markdown-segment" v-html="markdown(segment)" />
              <a
                v-else-if="segment.type === 'light_app' && segment.url"
                class="light-app-segment"
                :href="segment.url"
                target="_blank"
                rel="noopener noreferrer"
              >
                <strong>{{ segment.title || segment.app || '卡片消息' }}</strong>
                <span>{{ segment.description }}</span>
              </a>
              <span v-else-if="segment.type === 'light_app'" class="light-app-segment">
                <strong>{{ segment.title || segment.app || '卡片消息' }}</strong>
                <span>{{ segment.description }}</span>
              </span>
              <span v-else-if="segment.type === 'unknown'" class="unsupported-segment">{{ segment.summary }}</span>
            </template>
          </template>
          <button v-if="message.runId && !readonly" class="run-link" type="button" @click="emit('sendToAgent', message)">
            <Sparkles :size="12" />由 Agent {{ message.runId }} 生成
          </button>
        </div>
        <button v-if="plusOne && !readonly" class="plus-one" type="button" title="发送相同消息" @click="emit('plusOne')">+1</button>
        <div v-if="!readonly" class="message-actions">
          <button type="button" title="回复" @click="emit('reply', message)"><MessageSquareReply :size="14" /></button>
          <button type="button" title="交给 Agent" @click="emit('sendToAgent', message)"><Sparkles :size="14" /></button>
          <div class="message-menu">
            <button type="button" title="更多" @click="menuOpen = !menuOpen"><MoreHorizontal :size="14" /></button>
            <div v-if="menuOpen" class="message-menu-popover">
              <button class="mobile-menu-only" type="button" @click="emit('reply', message); menuOpen = false">
                <MessageSquareReply :size="14" />回复
              </button>
              <button type="button" @click="copyMessage"><Copy :size="14" />{{ copied ? '已复制' : '复制' }}</button>
              <button v-if="canForward" type="button" @click="emit('forward', message); menuOpen = false">
                <Forward :size="14" />转发
              </button>
              <button v-if="canNudge" type="button" @click="emit('nudge', message); menuOpen = false">
                <RotateCcw :size="14" />戳一戳
              </button>
              <button v-if="canRecall" class="danger" type="button" @click="emit('recall', message); menuOpen = false">
                <Undo2 :size="14" />撤回
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </article>
  <Teleport to="body">
    <button v-if="menuOpen && !readonly" class="mobile-message-dismiss" type="button" aria-label="关闭消息操作" @click="menuOpen = false" />
    <div v-if="menuOpen && !readonly" class="mobile-message-menu" role="menu" aria-label="消息操作">
      <button type="button" @click="emit('reply', message); menuOpen = false"><MessageSquareReply :size="14" />回复</button>
      <button type="button" @click="copyMessage"><Copy :size="14" />{{ copied ? '已复制' : '复制' }}</button>
      <button v-if="canForward" type="button" @click="emit('forward', message); menuOpen = false"><Forward :size="14" />转发</button>
      <button v-if="canNudge" type="button" @click="emit('nudge', message); menuOpen = false"><RotateCcw :size="14" />戳一戳</button>
      <button v-if="canRecall" class="danger" type="button" @click="emit('recall', message); menuOpen = false"><Undo2 :size="14" />撤回</button>
    </div>
  </Teleport>
</template>

<style scoped>
.message-row { position: relative; display: flex; max-width: 100%; touch-action: pan-y; align-items: flex-start; gap: 9px; padding: 5px 2px; border-radius: 6px; transition: transform 140ms ease-out; }
.message-row.mine { flex-direction: row-reverse; }
.message-row.selected { background: var(--warning-soft); }
.message-avatar-button { cursor: pointer; border: 0; background: transparent; padding: 0; }
.message-column { display: flex; min-width: 0; max-width: min(640px, 82%); flex-direction: column; align-items: flex-start; }
.message-row.mine .message-column { align-items: flex-end; }
.message-meta { display: flex; align-items: center; gap: 6px; margin: 0 3px 5px; color: var(--text-secondary); font-size: 10px; }
.message-row.mine .message-meta { flex-direction: row-reverse; }
.message-meta time { color: var(--text-muted); font-size: 9px; font-variant-numeric: tabular-nums; }
.role-tag { border-radius: 4px; color: var(--brand-strong); background: var(--brand-soft-strong); padding: 1px 4px; font-size: 9px; }
.role-tag.owner { color: var(--warning); background: var(--warning-soft); }
.message-and-actions { display: flex; align-items: center; gap: 7px; }
.message-row.mine .message-and-actions { flex-direction: row-reverse; }
.message-bubble { overflow: hidden; border: 1px solid var(--bubble-border); border-radius: 3px 8px 8px; color: var(--text); background: var(--message-incoming); box-shadow: var(--bubble-shadow); padding: 9px 12px; font-size: 12px; line-height: 1.65; }
.message-row.mine .message-bubble { border-color: var(--message-outgoing-border); border-radius: 8px 3px 8px 8px; background: var(--message-outgoing); }
.message-bubble.large-face { border-color: transparent; background: transparent; box-shadow: none; padding: 0; }
.message-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.mention-segment { color: var(--brand-strong); font-weight: 650; }
.message-text a { color: var(--brand-strong); text-decoration: underline; text-underline-offset: 2px; }
.reply-segment { display: flex; width: 100%; cursor: pointer; flex-direction: column; margin: -2px 0 7px; border: 0; border-left: 2px solid var(--brand); color: var(--text-secondary); background: transparent; padding: 0 0 0 8px; text-align: left; font-size: 10px; }
.reply-segment strong { color: var(--brand-strong); }
.reply-segment span { overflow: hidden; max-width: 340px; text-overflow: ellipsis; white-space: nowrap; }
.media-link { display: block; }
.message-image, .message-video { display: block; width: min(380px, 100%); max-height: 340px; margin-top: 7px; border-radius: 6px; object-fit: contain; background: #0000000a; }
.message-audio { display: block; width: min(320px, 72vw); margin-top: 7px; }
.file-segment, .forward-segment, .light-app-segment { display: flex; width: min(300px, 100%); align-items: center; gap: 9px; margin-top: 6px; border: 1px solid var(--border); border-radius: 6px; color: var(--text); background: var(--surface); padding: 9px; text-decoration: none; text-align: left; }
.forward-segment { cursor: pointer; }
.file-segment span, .forward-segment span, .light-app-segment { min-width: 0; flex-direction: column; align-items: flex-start; }
.file-segment strong, .file-segment small, .forward-segment strong, .forward-segment small, .light-app-segment strong, .light-app-segment span { display: block; overflow: hidden; max-width: 100%; text-overflow: ellipsis; white-space: nowrap; }
.file-segment small, .forward-segment small, .light-app-segment span { color: var(--text-muted); font-size: 9px; }
.file-segment.disabled { color: var(--text-muted); }
.file-segment.disabled:not(:disabled) { cursor: pointer; }
.unsupported-segment { display: inline-flex; margin: 2px; border: 0; border-radius: 4px; color: var(--text-muted); background: var(--surface-muted); padding: 3px 6px; font: inherit; font-size: 10px; }
button.unsupported-segment { cursor: pointer; }
.markdown-segment :deep(p) { margin: 0 0 5px; }
.markdown-segment :deep(p:last-child) { margin-bottom: 0; }
.markdown-segment :deep(pre) { overflow-x: auto; border-radius: 5px; background: var(--surface-muted); padding: 8px; }
.recalled-label { color: var(--text-muted); font-size: 10px; }
.run-link { display: flex; cursor: pointer; align-items: center; gap: 4px; margin-top: 7px; border: 0; color: var(--brand-strong); background: transparent; padding: 0; font-size: 9px; }
.plus-one { min-width: 32px; height: 26px; cursor: pointer; border: 1px solid var(--border); border-radius: 5px; color: var(--brand-strong); background: var(--surface); padding: 0 7px; font-size: 10px; font-weight: 700; }
.message-actions { display: flex; visibility: hidden; align-items: center; gap: 2px; opacity: 0; }
.message-row:hover .message-actions, .message-row.selected .message-actions { visibility: visible; opacity: 1; }
.message-actions > button, .message-menu > button { display: grid; width: 27px; height: 27px; cursor: pointer; place-items: center; border: 1px solid var(--border); border-radius: 5px; color: var(--text-muted); background: var(--surface); }
.message-menu { position: relative; }
.message-menu-popover { position: absolute; z-index: 30; right: 0; bottom: 32px; display: grid; min-width: 110px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); box-shadow: 0 12px 32px #0003; padding: 4px; }
.message-menu-popover button { display: flex; cursor: pointer; align-items: center; gap: 7px; border: 0; border-radius: 4px; color: var(--text); background: transparent; padding: 7px 8px; font-size: 11px; }
.message-menu-popover button:hover { background: var(--surface-hover); }
.message-menu-popover button.danger { color: var(--danger); }
.mobile-menu-only { display: none !important; }
.mobile-message-menu, .mobile-message-dismiss { display: none; }
.swipe-indicator { position: absolute; top: 50%; left: -23px; display: grid; width: 24px; height: 24px; transform: translateY(-50%); place-items: center; border-radius: 50%; color: var(--text-muted); background: var(--surface); opacity: 0; transition: opacity 120ms ease; }
.message-row[style*="translate3d(0px"] .swipe-indicator { opacity: 0; }
.swipe-indicator.ready { color: var(--brand-strong); opacity: 1; }
@media (max-width: 860px) {
  .message-column { max-width: calc(100% - 42px); }
  .message-actions { display: none; }
  .message-menu-popover { display: none; }
  .mobile-message-dismiss { position: fixed; z-index: 259; inset: 0; display: block; cursor: default; border: 0; background: #0002; }
  .mobile-message-menu { position: fixed; z-index: 260; right: 10px; bottom: 76px; left: 10px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 3px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); box-shadow: var(--floating-shadow); padding: 6px; }
  .mobile-message-menu button { display: flex; min-width: 0; min-height: 38px; cursor: pointer; align-items: center; justify-content: center; gap: 7px; border: 0; border-radius: 5px; color: var(--text); background: transparent; font-size: 11px; }
  .mobile-message-menu button:active { background: var(--surface-hover); }
  .mobile-message-menu button.danger { color: var(--danger); }
}
</style>
