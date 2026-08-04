<script setup lang="ts">
import { ArrowLeft, LoaderCircle, X } from '@lucide/vue'
import { ref, watch } from 'vue'

import { workspaceAdapter } from '../../services/workspace-adapter'
import type { Account, ChatMessage, Conversation, MessageSegment } from '../../types/workspace'
import MessageBubble from './MessageBubble.vue'

const props = defineProps<{ open: boolean; conversation?: Conversation; account?: Account; forwardId: string }>()
const emit = defineEmits<{
  close: []
  refreshMedia: [message: ChatMessage]
  loadFile: [message: ChatMessage, fileId: string]
}>()
const messages = ref<ChatMessage[]>([])
const loading = ref(false)
const error = ref('')
const stack = ref<Array<{ forwardId: string; messages: ChatMessage[] }>>([])
let version = 0

async function load(forwardId: string, mode: 'replace' | 'push' = 'replace'): Promise<void> {
  if (!props.conversation || !forwardId) return
  const requestVersion = ++version
  loading.value = true
  error.value = ''
  try {
    const bundle = await workspaceAdapter.loadForwarded(props.conversation, forwardId)
    if (requestVersion !== version) return
    messages.value = bundle.messages
    const level = { forwardId, messages: bundle.messages }
    if (mode === 'push') stack.value.push(level)
    else stack.value = [level]
  } catch (cause) {
    if (requestVersion === version) error.value = cause instanceof Error ? cause.message : '无法加载合并转发消息'
  } finally {
    if (requestVersion === version) loading.value = false
  }
}

function nested(segment: Extract<MessageSegment, { type: 'forward' }>): void {
  if (segment.messages) {
    messages.value = segment.messages
    stack.value.push({ forwardId: segment.forwardId, messages: segment.messages })
    return
  }
  void load(segment.forwardId, 'push')
}

function loadFile(message: ChatMessage, fileId: string): void {
  emit('loadFile', message, fileId)
}

function back(): void {
  if (stack.value.length <= 1) return
  stack.value.pop()
  messages.value = stack.value.at(-1)?.messages ?? []
}

watch(
  () => [props.open, props.conversation?.id, props.forwardId] as const,
  ([open]) => {
    version += 1
    if (open) void load(props.forwardId)
    else {
      messages.value = []
      stack.value = []
    }
  },
  { immediate: true },
)
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="dialog-backdrop" @mousedown.self="emit('close')">
      <section class="forward-dialog" role="dialog" aria-modal="true" aria-label="合并转发消息">
        <header>
          <button v-if="stack.length > 1" type="button" title="返回上一层" @click="back"><ArrowLeft :size="18" /></button>
          <div><strong>合并转发消息</strong><small>{{ messages.length }} 条</small></div>
          <button type="button" title="关闭" @click="emit('close')"><X :size="18" /></button>
        </header>
        <div class="forward-content">
          <div v-if="loading" class="state"><LoaderCircle class="spin" :size="22" />正在加载</div>
          <div v-else-if="error" class="state error">{{ error }}</div>
          <MessageBubble
            v-for="message in messages"
            v-else-if="conversation"
            :key="message.id"
            :message="message"
            :conversation="conversation"
            :account="account"
            readonly
            @open-forward="nested"
            @refresh-media="emit('refreshMedia', $event)"
            @load-file="loadFile"
          />
          <div v-if="!loading && !error && !messages.length" class="state">转发内容为空</div>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop { position: fixed; z-index: 200; inset: 0; display: grid; place-items: center; background: #0007; padding: 16px; }
.forward-dialog { display: flex; width: min(560px, 100%); max-height: min(760px, calc(100dvh - 32px)); flex-direction: column; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); box-shadow: var(--floating-shadow); }
header { display: flex; min-height: 55px; align-items: center; gap: 9px; border-bottom: 1px solid var(--border); padding: 9px 12px; }
header div { min-width: 0; flex: 1; } header strong, header small { display: block; } header strong { color: var(--text); font-size: 13px; } header small { color: var(--text-muted); font-size: 9px; }
header button { display: grid; width: 32px; height: 32px; cursor: pointer; place-items: center; border: 0; color: var(--text-muted); background: transparent; }
.forward-content { min-height: 220px; overflow-y: auto; padding: 10px 14px; }
.forward-content :deep(.message-row) { border-bottom: 1px solid var(--border); padding: 10px 2px; }
.state { display: flex; min-height: 210px; align-items: center; justify-content: center; gap: 7px; color: var(--text-muted); font-size: 11px; }.state.error { color: var(--danger); }
.spin { animation: spin 800ms linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
</style>
