<script setup lang="ts">
import { Forward, Search, X } from '@lucide/vue'
import { computed, ref, watch } from 'vue'

import type { ChatMessage, Conversation } from '../../types/workspace'
import AppAvatar from '../AppAvatar.vue'

const props = defineProps<{
  open: boolean
  message?: ChatMessage
  source?: Conversation
  conversations: Conversation[]
  sending: boolean
}>()
const emit = defineEmits<{ close: []; submit: [target: Conversation] }>()
const query = ref('')
const selectedId = ref('')
const options = computed(() => {
  const value = query.value.trim().toLocaleLowerCase('zh-CN')
  return props.conversations
    .filter((item) => item.accountId === props.source?.accountId)
    .filter((item) => !value || `${item.name} ${item.peerId}`.toLocaleLowerCase('zh-CN').includes(value))
    .slice(0, 100)
})
const selected = computed(() => props.conversations.find((item) => item.id === selectedId.value))

watch(
  () => props.open,
  (open) => {
    if (open) {
      query.value = ''
      selectedId.value = ''
    }
  },
)
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="dialog-backdrop" @mousedown.self="emit('close')">
      <section class="forward-dialog" role="dialog" aria-modal="true" aria-label="转发消息">
        <header><div><strong>转发消息</strong><small>{{ message?.content }}</small></div><button type="button" title="关闭" @click="emit('close')"><X :size="18" /></button></header>
        <label class="search"><Search :size="15" /><input v-model="query" type="search" placeholder="搜索同一 QQ 账号的会话" /></label>
        <div class="targets">
          <button v-for="item in options" :key="item.id" type="button" :class="{ selected: item.id === selectedId }" @click="selectedId = item.id">
            <AppAvatar :src="item.avatar" :name="item.name" size="sm" />
            <span><strong>{{ item.name }}</strong><small>{{ item.type === 'group' ? '群聊' : '好友' }} · {{ item.peerId }}</small></span>
          </button>
          <p v-if="!options.length">没有匹配的同账号会话</p>
        </div>
        <footer><button type="button" @click="emit('close')">取消</button><button class="primary" type="button" :disabled="!selected || sending" @click="selected && emit('submit', selected)"><Forward :size="15" />{{ sending ? '转发中' : '转发' }}</button></footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop { position: fixed; z-index: 200; inset: 0; display: grid; place-items: center; background: #0007; padding: 16px; }
.forward-dialog { display: flex; width: min(480px, 100%); max-height: min(680px, calc(100dvh - 32px)); flex-direction: column; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); box-shadow: var(--floating-shadow); }
header { display: flex; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--border); padding: 12px 14px; } header div { min-width: 0; } header strong, header small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } header strong { color: var(--text); font-size: 13px; } header small { max-width: 390px; color: var(--text-muted); font-size: 9px; } header button { border: 0; color: var(--text-muted); background: transparent; }
.search { display: flex; align-items: center; gap: 7px; margin: 10px; border: 1px solid var(--border); border-radius: 5px; color: var(--text-muted); padding: 0 9px; }.search input { min-width: 0; height: 35px; flex: 1; border: 0; color: var(--text); background: transparent; outline: none; font-size: 11px; }
.targets { min-height: 180px; overflow-y: auto; padding: 0 8px 8px; }.targets > button { display: flex; width: 100%; cursor: pointer; align-items: center; gap: 9px; border: 0; border-radius: 5px; color: var(--text); background: transparent; padding: 8px; text-align: left; }.targets > button:hover, .targets > button.selected { background: var(--surface-hover); }.targets > button.selected { outline: 1px solid var(--brand-border); }.targets span { min-width: 0; }.targets strong, .targets small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.targets strong { font-size: 11px; }.targets small, .targets p { color: var(--text-muted); font-size: 9px; }.targets p { padding: 55px 10px; text-align: center; }
footer { display: flex; justify-content: flex-end; gap: 7px; border-top: 1px solid var(--border); padding: 10px 12px; }footer button { display: flex; height: 33px; cursor: pointer; align-items: center; gap: 5px; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--surface); padding: 0 12px; font-size: 11px; }footer .primary { border-color: var(--brand); color: #fff; background: var(--brand); }footer button:disabled { cursor: not-allowed; opacity: .45; }
</style>
