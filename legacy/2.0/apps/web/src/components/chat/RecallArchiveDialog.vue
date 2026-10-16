<script setup lang="ts">
import { LoaderCircle, RotateCcw, X } from '@lucide/vue'
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { hasRetainedOriginal, publishRecallUpdate, recallService, subscribeRecallUpdates } from '../../services/recall'
import type { Account, ChatMessage, Conversation, MessageSegment, RecallSettings } from '../../types/workspace'
import MessageBubble from './MessageBubble.vue'

const props = defineProps<{ open: boolean; conversation: Conversation; account?: Account }>()
const emit = defineEmits<{
  close: []
  openForward: [segment: Extract<MessageSegment, { type: 'forward' }>, message: ChatMessage]
}>()
const dialog = ref<HTMLElement>()
const settings = ref<RecallSettings>({ enabled: true, retentionDays: 7 })
const messages = ref<ChatMessage[]>([])
const loading = ref(false)
const loaded = ref(false)
const saving = ref(false)
const error = ref('')
const saved = ref(false)
const hasMore = ref(false)
let cursor: string | undefined
let version = 0
let returnFocus: HTMLElement | null = null
let expiryTimer: ReturnType<typeof setInterval> | undefined
let applyingPageSettings = false

function pruneExpired(): void {
  messages.value = messages.value.filter((message) => hasRetainedOriginal(message))
}

async function load(append = false): Promise<void> {
  const requestVersion = ++version
  const conversation = props.conversation
  loading.value = true
  error.value = ''
  try {
    const page = await recallService.load(conversation, append ? cursor : undefined)
    if (requestVersion !== version) return
    settings.value = { ...page.settings }
    loaded.value = true
    applyingPageSettings = true
    try {
      publishRecallUpdate({ type: 'recall.settings.changed', accountId: conversation.accountId,
        conversationId: conversation.id, settings: page.settings })
    } finally { applyingPageSettings = false }
    messages.value = page.settings.enabled
      ? [...new Map([...(append ? messages.value : []), ...page.messages].map((message) => [message.id, message])).values()]
      : []
    pruneExpired()
    hasMore.value = page.hasMore
    cursor = page.nextCursor
  } catch (cause) {
    if (requestVersion === version) error.value = cause instanceof Error ? cause.message : '撤回记录加载失败'
  } finally {
    if (requestVersion === version) loading.value = false
  }
}

async function save(): Promise<void> {
  if (saving.value) return
  const conversationId = props.conversation.id
  saving.value = true
  saved.value = false
  error.value = ''
  try {
    const result = await recallService.saveSettings(props.conversation, { ...settings.value })
    if (!props.open || props.conversation.id !== conversationId) return
    settings.value = result
    saved.value = true
  } catch (cause) {
    if (props.conversation.id === conversationId) error.value = cause instanceof Error ? cause.message : '设置保存失败'
  } finally {
    if (props.conversation.id === conversationId) saving.value = false
  }
}

const unsubscribe = subscribeRecallUpdates((event) => {
  if (applyingPageSettings || !props.open || event.accountId !== props.conversation.accountId || event.conversationId !== props.conversation.id) return
  if (event.type === 'recall.settings.changed') {
    version += 1
    loading.value = false
    loaded.value = true
    settings.value = { ...event.settings }
    if (!event.settings.enabled) {
      messages.value = []
      hasMore.value = false
      return
    }
    messages.value = messages.value.filter((message) => message.recall &&
      (message.recall.recordedAt ?? message.recall.recalledAt) + event.settings.retentionDays * 86_400_000 > Date.now())
  }
  void load()
})

function restoreFocus(): void {
  if (returnFocus?.isConnected) returnFocus.focus()
  returnFocus = null
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    emit('close')
  }
  if (event.key !== 'Tab') return
  const items = [...(dialog.value?.querySelectorAll<HTMLElement>('button, input, a[href], [tabindex="0"]') ?? [])]
    .filter((item) => !item.matches(':disabled'))
  const first = items[0]
  const last = items.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}

watch(() => [props.open, props.conversation.id] as const, async ([open], previous) => {
  version += 1
  clearInterval(expiryTimer)
  messages.value = []
  hasMore.value = false
  loaded.value = false
  loading.value = false
  saving.value = false
  saved.value = false
  error.value = ''
  if (!open) { restoreFocus(); return }
  if (!previous?.[0]) returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  expiryTimer = setInterval(pruneExpired, 12_000)
  void load()
  await nextTick()
  dialog.value?.querySelector<HTMLButtonElement>('[title="关闭撤回记录"]')?.focus()
}, { immediate: true })

onBeforeUnmount(() => { version += 1; unsubscribe(); clearInterval(expiryTimer); restoreFocus() })
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="dialog-backdrop" @mousedown.self="emit('close')">
      <section ref="dialog" class="recall-dialog" role="dialog" aria-modal="true" aria-label="撤回记录" @keydown="onKeydown">
        <header><div><strong>撤回记录</strong><small>{{ conversation.name }}</small></div><button type="button" title="关闭撤回记录" @click="emit('close')"><X :size="18" /></button></header>
        <form @submit.prevent="save">
          <label class="enable-control"><input v-model="settings.enabled" type="checkbox" :disabled="!loaded || saving" />保留此会话的撤回消息</label>
          <div class="settings-row"><label>保存期限 <input v-model.number="settings.retentionDays" type="number" min="1" max="30" required aria-label="撤回消息保存天数" :disabled="!loaded || saving" /> 天</label><button type="submit" :disabled="!loaded || saving || loading"><LoaderCircle v-if="saving" class="spin" :size="14" />保存设置</button><span v-if="saved" role="status">已保存</span></div>
          <p>到期自动清除原文；关闭后会清空此会话已保留的撤回记录。</p>
        </form>
        <div class="archive-info"><span>仅显示服务在线期间捕获的撤回原文。收到消息时会尝试保存附件，未成功保存的附件可能无法打开。</span><button type="button" title="刷新撤回记录" :disabled="loading" @click="load()"><RotateCcw :size="15" /></button></div>
        <p v-if="error" class="error" role="alert">{{ error }}<button type="button" @click="load()">重试</button></p>
        <div class="archive-messages" :aria-busy="loading">
          <div v-for="message in messages" :key="message.id" class="archive-item">
            <MessageBubble :message="message" :conversation="conversation" :account="account" readonly
              @open-forward="(segment, original) => emit('openForward', segment, original)" />
            <small>撤回于 {{ new Date(message.recall!.recalledAt).toLocaleString('zh-CN', { hour12: false }) }}</small>
          </div>
          <p v-if="loading" class="empty" role="status">正在加载撤回记录…</p>
          <p v-else-if="!messages.length && !error" class="empty">{{ settings.enabled ? '还没有保留的撤回消息' : '此会话已关闭防撤回' }}</p>
          <button v-if="hasMore" class="load-more" type="button" :disabled="loading" @click="load(true)">加载更多</button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop { position: fixed; z-index: 200; inset: 0; display: grid; place-items: center; background: #0007; padding: 16px; }
.recall-dialog { display: flex; width: min(700px, 100%); max-height: min(800px, calc(100dvh - 32px)); flex-direction: column; overflow: hidden; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); box-shadow: var(--floating-shadow); }
header { display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); padding: 12px 14px; }
header strong, header small { display: block; } header strong { color: var(--text); font-size: 14px; } header small { margin-top: 3px; color: var(--text-muted); font-size: 11px; }
header button, .archive-info button { cursor: pointer; border: 0; color: var(--text-muted); background: transparent; }
form { border-bottom: 1px solid var(--border); padding: 12px 16px; color: var(--text); font-size: 12px; }
.enable-control, .settings-row { display: flex; align-items: center; gap: 8px; } .settings-row { margin-top: 10px; flex-wrap: wrap; }
input[type='checkbox'] { accent-color: var(--brand); } input[type='number'] { width: 60px; height: 30px; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--surface); padding: 0 6px; }
.settings-row button, .load-more { display: inline-flex; align-items: center; justify-content: center; gap: 5px; cursor: pointer; border: 0; border-radius: 5px; color: #fff; background: var(--brand); padding: 8px 12px; font-size: 11px; }
button:disabled { cursor: default; opacity: .5; } .settings-row > span { color: var(--brand); font-size: 11px; }
form p, .archive-info { margin: 9px 0 0; color: var(--text-muted); font-size: 11px; line-height: 1.5; }
.archive-info { display: flex; align-items: center; gap: 12px; padding: 0 16px 10px; } .archive-info span { flex: 1; }
.archive-messages { min-height: 150px; overflow-y: auto; padding: 12px 16px; background: var(--chat-background); }
.archive-item { margin-bottom: 18px; } .archive-item > small { display: block; margin: 5px 40px; color: var(--text-muted); font-size: 10px; }
.empty { margin: 0; padding: 36px 12px; color: var(--text-muted); font-size: 12px; text-align: center; }
.error { padding: 0 16px; color: var(--danger); font-size: 12px; } .error button { margin-left: 8px; }
.load-more { display: flex; margin: 8px auto; } .spin { animation: spin 800ms linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
</style>
