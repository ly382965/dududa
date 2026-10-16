<script setup lang="ts">
import { LoaderCircle, Search, X } from '@lucide/vue'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { workspaceAdapter } from '../../services/workspace-adapter'
import type { ChatMessage, Conversation } from '../../types/workspace'

const props = defineProps<{
  open: boolean
  conversation?: Conversation
  senders: Array<{ userId: string; name: string }>
}>()
const emit = defineEmits<{ close: []; select: [message: ChatMessage] }>()

const query = ref('')
const senderId = ref('')
const startDate = ref('')
const endDate = ref('')
const results = ref<ChatMessage[]>([])
const loading = ref(false)
const error = ref('')
const hasMore = ref(false)
const searched = ref(false)
const hasCachedMessages = ref(true)
const dialog = ref<HTMLElement>()
let returnFocus: HTMLElement | null = null
let version = 0

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
  const items = [...(dialog.value?.querySelectorAll<HTMLElement>('*') ?? [])]
    .filter(item => item.matches('button, input, select, [tabindex="0"]') && !item.matches(':disabled'))
  const first = items[0]
  const last = items.at(-1)
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}

onBeforeUnmount(restoreFocus)

const canSearch = computed(() => Boolean(query.value.trim() || senderId.value || startDate.value || endDate.value))

function dateValue(value: string, end = false): number | undefined {
  if (!value) return undefined
  const [year, month, day] = value.split('-').map(Number)
  if (!year || !month || !day) return undefined
  return new Date(year, month - 1, day + Number(end)).getTime() - Number(end)
}

async function search(append = false): Promise<void> {
  const conversation = props.conversation
  if (!conversation || !canSearch.value) return
  if (startDate.value && endDate.value && startDate.value > endDate.value) {
    error.value = '开始日期不能晚于结束日期'
    return
  }
  const requestVersion = ++version
  loading.value = true
  error.value = ''
  try {
    const page = await workspaceAdapter.searchMessages({
      accountId: conversation.accountId,
      conversationId: conversation.id,
      query: query.value,
      senderId: senderId.value || undefined,
      startTimeMs: dateValue(startDate.value),
      endTimeMs: dateValue(endDate.value, true),
      beforeTimestampMs: append ? results.value.at(-1)?.timestampMs : undefined,
      beforeCacheId: append ? results.value.at(-1)?.id : undefined,
      limit: 50,
    })
    if (requestVersion !== version) return
    results.value = append
      ? [...new Map([...results.value, ...page.messages].map((message) => [message.id, message])).values()]
      : page.messages
    hasMore.value = page.hasMore
    searched.value = true
    if (!page.messages.length) {
      const cached = await workspaceAdapter.loadCachedMessages(conversation, 1)
      if (requestVersion === version) hasCachedMessages.value = cached.length > 0
    }
  } catch (cause) {
    if (requestVersion === version) error.value = cause instanceof Error ? cause.message : '搜索消息失败'
  } finally {
    if (requestVersion === version) loading.value = false
  }
}

watch(
  () => [props.open, props.conversation?.id] as const,
  async ([open], previous) => {
    version += 1
    loading.value = false
    hasMore.value = false
    if (!open) {
      await nextTick()
      restoreFocus()
      return
    }
    if (!previous?.[0]) returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (!previous?.[0] || previous[1] !== props.conversation?.id) {
      query.value = ''
      senderId.value = ''
      startDate.value = ''
      endDate.value = ''
      results.value = []
      error.value = ''
      searched.value = false
      hasCachedMessages.value = true
    }
    await nextTick()
    dialog.value?.querySelector<HTMLInputElement>('[aria-label="消息关键词"]')?.focus()
  },
)
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="dialog-backdrop" role="presentation" @mousedown.self="emit('close')">
      <section ref="dialog" class="search-dialog" role="dialog" aria-modal="true" aria-label="搜索消息" @keydown="onKeydown">
        <header><div><strong>搜索消息</strong><small>{{ conversation?.name }}</small></div><button type="button" title="关闭" @click="emit('close')"><X :size="18" /></button></header>
        <form @submit.prevent="search(false)">
          <div class="search-row"><input v-model="query" type="search" aria-label="消息关键词" placeholder="输入关键词" /><button type="submit" :disabled="!canSearch || loading"><LoaderCircle v-if="loading" class="spin" :size="16" /><Search v-else :size="16" />搜索</button></div>
          <div class="filters">
            <label><span>发送人</span><select v-model="senderId"><option value="">全部发送人</option><option v-for="sender in senders" :key="sender.userId" :value="sender.userId">{{ sender.name }} · {{ sender.userId }}</option></select></label>
            <label><span>开始日期</span><input v-model="startDate" type="date" /></label>
            <label><span>结束日期</span><input v-model="endDate" type="date" /></label>
          </div>
        </form>
        <p class="search-scope">仅搜索此浏览器已加载的消息，不代表完整 QQ 历史。可先浏览历史，或在设置中补齐指定日期。</p>
        <div class="search-results" aria-live="polite" :aria-busy="loading">
          <span v-if="error" class="error">{{ error }}</span>
          <button v-for="message in results" :key="message.id" type="button" @click="emit('select', message)">
            <span><strong>{{ message.senderName }}</strong><time>{{ message.timestamp }}</time></span>
            <p>{{ message.content }}</p>
          </button>
          <p v-if="loading" class="empty">正在搜索…</p>
          <p v-else-if="!results.length && !error" class="empty">{{ !searched ? '输入条件搜索已缓存的 QQ 消息' : hasCachedMessages ? '未找到匹配消息，请调整关键词或日期范围' : '此浏览器尚未缓存该会话的消息，请先加载聊天历史' }}</p>
          <button v-if="hasMore" class="load-more" type="button" :disabled="loading" @click="search(true)">加载更多</button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.search-scope { margin: 0; padding: 10px 12px; color: var(--text-secondary); font-size: 12px; line-height: 1.5; }
.dialog-backdrop { position: fixed; z-index: 200; inset: 0; display: grid; place-items: center; background: #0007; padding: 16px; }
.search-dialog { display: flex; width: min(680px, 100%); max-height: min(760px, calc(100dvh - 32px)); flex-direction: column; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); box-shadow: var(--floating-shadow); }
header { display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); padding: 12px 14px; }
header strong, header small { display: block; }
header strong { color: var(--text); font-size: 14px; } header small { color: var(--text-muted); font-size: 10px; }
header button { cursor: pointer; border: 0; color: var(--text-muted); background: transparent; }
form { border-bottom: 1px solid var(--border); padding: 12px; }
.search-row { display: flex; gap: 8px; }
input, select { min-width: 0; height: 36px; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--surface); padding: 0 9px; font: inherit; font-size: 11px; outline: none; }
.search-row input { flex: 1; }
.search-row button, .load-more { display: flex; cursor: pointer; align-items: center; justify-content: center; gap: 5px; border: 0; border-radius: 5px; color: #fff; background: var(--brand); padding: 0 13px; font-size: 11px; }
.filters { display: grid; grid-template-columns: 1.5fr 1fr 1fr; gap: 8px; margin-top: 8px; }
.filters label span { display: block; margin-bottom: 3px; color: var(--text-muted); font-size: 9px; }
.filters input, .filters select { width: 100%; }
.search-results { min-height: 180px; overflow-y: auto; padding: 8px; }
.search-results > button:not(.load-more) { display: block; width: 100%; cursor: pointer; border: 0; border-radius: 5px; color: var(--text); background: transparent; padding: 9px; text-align: left; }
.search-results > button:hover { background: var(--surface-hover); }
.search-results span { display: flex; justify-content: space-between; gap: 8px; }
.search-results strong { font-size: 11px; } .search-results time { color: var(--text-muted); font-size: 9px; }
.search-results p { overflow: hidden; margin: 3px 0 0; color: var(--text-secondary); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.search-results .empty { padding: 60px 10px; text-align: center; white-space: normal; }
.error { display: block; color: var(--danger); padding: 10px; font-size: 10px; }
.load-more { height: 32px; margin: 8px auto; }
.spin { animation: spin 800ms linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 560px) { .filters { grid-template-columns: 1fr 1fr; } .filters label:first-child { grid-column: 1 / -1; } }
</style>
