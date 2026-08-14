<script setup lang="ts">
import {
  Check,
  ChevronRight,
  CircleAlert,
  Clock3,
  Pencil,
  SendHorizontal,
  Sparkles,
  Trash2,
  Wrench,
  X,
} from '@lucide/vue'
import { computed, ref, watch } from 'vue'

import type { Account, AgentPart, PermissionPart, ReplyDraftPart, ToolPart } from '../types/workspace'
import AppAvatar from './AppAvatar.vue'

const props = defineProps<{
  part: AgentPart
  accounts: Account[]
}>()

const emit = defineEmits<{
  approveDraft: [part: ReplyDraftPart]
  discardDraft: [part: ReplyDraftPart]
  updateDraft: [part: ReplyDraftPart, content: string]
  respondPermission: [part: PermissionPart, allow: boolean]
}>()

const tool = computed<ToolPart | undefined>(() => (props.part.type === 'tool' ? props.part : undefined))
const permission = computed<PermissionPart | undefined>(() =>
  props.part.type === 'permission' ? props.part : undefined,
)
const draft = computed<ReplyDraftPart | undefined>(() =>
  props.part.type === 'reply_draft' ? props.part : undefined,
)
const draftAccount = computed(() => props.accounts.find((item) => item.id === draft.value?.accountId))
const editing = ref(false)
const editContent = ref('')

function startEditing(): void {
  if (!draft.value) return
  editContent.value = draft.value.content
  editing.value = true
}

function saveDraft(): void {
  if (!draft.value || !editContent.value.trim()) return
  emit('updateDraft', draft.value, editContent.value)
  editing.value = false
}

watch(
  () => draft.value?.content,
  (content) => {
    if (!editing.value) editContent.value = content ?? ''
  },
  { immediate: true },
)
</script>

<template>
  <p v-if="part.type === 'text'" class="agent-text">{{ part.text }}</p>

  <div v-else-if="part.type === 'status'" class="status-part" :class="`status-part--${part.tone}`">
    <Check v-if="part.tone === 'success'" :size="13" />
    <Clock3 v-else :size="13" />
    <span>{{ part.label }}</span>
  </div>

  <details v-else-if="tool" class="tool-part">
    <summary>
      <span class="tool-icon" :class="`tool-icon--${tool.status}`">
        <Wrench :size="14" />
      </span>
      <span class="tool-summary">
        <strong>{{ tool.title }}</strong>
        <small>{{ tool.name }}</small>
      </span>
      <span class="tool-state" :class="`tool-state--${tool.status}`">
        <Check v-if="tool.status === 'completed'" :size="12" />
        <CircleAlert v-else-if="tool.status === 'error'" :size="12" />
        <span v-else class="pulse-dot" />
        {{ tool.duration || (tool.status === 'running' ? '运行中' : '失败') }}
      </span>
      <ChevronRight class="disclosure-icon" :size="15" />
    </summary>
    <div class="tool-detail">
      <label>INPUT</label>
      <pre>{{ tool.input }}</pre>
      <template v-if="tool.output">
        <label>OUTPUT</label>
        <p>{{ tool.output }}</p>
      </template>
    </div>
  </details>

  <div v-else-if="permission" class="permission-part" :class="`permission-part--${permission.state}`">
    <div class="permission-heading">
      <span class="permission-icon"><CircleAlert :size="16" /></span>
      <span><strong>{{ permission.title }}</strong><small>{{ permission.detail }}</small></span>
    </div>
    <div v-if="permission.state === 'pending'" class="permission-actions">
      <button type="button" class="button-secondary" disabled title="Agent 权限命令不可用" @click="emit('respondPermission', permission, false)">拒绝</button>
      <button type="button" class="button-primary" disabled title="Agent 权限命令不可用" @click="emit('respondPermission', permission, true)">允许一次</button>
    </div>
    <span v-else class="permission-result">
      <Check v-if="permission.state === 'allowed'" :size="13" />
      <X v-else :size="13" />
      {{ permission.state === 'allowed' ? '已允许' : '已拒绝' }}
    </span>
  </div>

  <section v-else-if="draft" class="reply-draft" :class="`reply-draft--${draft.status}`">
    <header>
      <span class="draft-title"><Sparkles :size="14" />QQ 回复草稿</span>
      <span v-if="draft.status !== 'draft'" class="draft-state">
        <Check v-if="draft.status === 'sent'" :size="12" />
        <Trash2 v-else :size="12" />
        {{ draft.status === 'sent' ? '已发送' : '已丢弃' }}
      </span>
    </header>
    <div class="draft-target">
      <AppAvatar
        v-if="draftAccount"
        :src="draftAccount.avatar"
        :name="draftAccount.name"
        size="xs"
        :status="draftAccount.status"
      />
      <span>{{ draftAccount?.name ?? '未知账号' }}</span>
      <span class="target-arrow">→</span>
      <span>当前会话</span>
    </div>
    <textarea v-if="editing" v-model="editContent" rows="7" aria-label="编辑回复草稿" />
    <p v-else class="draft-content">{{ draft.content }}</p>
    <footer v-if="draft.status === 'draft'">
      <button v-if="editing" class="button-ghost" type="button" @click="editing = false">取消</button>
      <button v-if="editing" class="button-secondary" type="button" @click="saveDraft">保存草稿</button>
      <template v-else>
        <button class="button-ghost icon-text" type="button" @click="startEditing"><Pencil :size="13" />编辑</button>
        <button class="button-ghost icon-text danger" type="button" @click="emit('discardDraft', draft)">
          <Trash2 :size="13" />丢弃
        </button>
        <button class="button-primary icon-text send-draft" type="button" disabled title="Agent 草稿发送命令不可用" @click="emit('approveDraft', draft)">
          <SendHorizontal :size="14" />发送不可用
        </button>
      </template>
    </footer>
  </section>
</template>

<style scoped>
.agent-text {
  margin: 8px 0;
  color: var(--text);
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.status-part {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 7px 0;
  color: var(--text-secondary);
  font-size: 10px;
}

.status-part--success {
  color: var(--success-strong);
}

.status-part--warning {
  color: var(--warning-strong);
}

.tool-part {
  margin: 8px 0;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface);
}

.tool-part summary {
  display: grid;
  min-height: 50px;
  cursor: pointer;
  grid-template-columns: 30px minmax(0, 1fr) auto 16px;
  align-items: center;
  gap: 8px;
  padding: 6px 9px;
  list-style: none;
}

.tool-part summary::-webkit-details-marker {
  display: none;
}

.tool-icon {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 6px;
  color: var(--brand-strong);
  background: var(--brand-soft);
}

.tool-icon--error {
  color: var(--danger);
  background: var(--danger-soft);
}

.tool-summary {
  display: block;
  min-width: 0;
}

.tool-summary strong,
.tool-summary small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-summary strong {
  color: var(--text);
  font-size: 11px;
  font-weight: 650;
}

.tool-summary small {
  margin-top: 2px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 8px;
}

.tool-state {
  display: flex;
  align-items: center;
  gap: 3px;
  color: var(--text-muted);
  font-size: 8px;
  white-space: nowrap;
}

.tool-state--completed {
  color: var(--success-strong);
}

.tool-state--error {
  color: var(--danger);
}

.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--brand);
  animation: pulse 1s ease-in-out infinite;
}

.disclosure-icon {
  color: var(--text-muted);
  transition: transform 150ms ease;
}

.tool-part[open] .disclosure-icon {
  transform: rotate(90deg);
}

.tool-detail {
  border-top: 1px solid var(--border);
  background: var(--surface-subtle);
  padding: 10px;
}

.tool-detail label {
  display: block;
  margin: 0 0 4px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 8px;
  font-weight: 700;
}

.tool-detail label:not(:first-child) {
  margin-top: 10px;
}

.tool-detail pre,
.tool-detail p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 9px;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.tool-detail pre {
  font-family: var(--font-mono);
}

.permission-part {
  margin: 9px 0;
  border: 1px solid var(--warning-border);
  border-radius: 7px;
  background: var(--warning-soft);
  padding: 10px;
}

.permission-heading {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.permission-icon {
  display: grid;
  width: 28px;
  height: 28px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 6px;
  color: var(--warning-strong);
  background: var(--surface);
}

.permission-heading strong,
.permission-heading small {
  display: block;
}

.permission-heading strong {
  color: var(--text);
  font-size: 11px;
}

.permission-heading small {
  margin-top: 3px;
  color: var(--text-secondary);
  font-size: 9px;
  line-height: 1.5;
}

.permission-actions,
.reply-draft footer {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  margin-top: 10px;
}

.permission-result {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: 9px;
}

.reply-draft {
  overflow: hidden;
  margin: 10px 0;
  border: 1px solid var(--brand-border);
  border-radius: 7px;
  background: var(--surface);
  box-shadow: 0 7px 24px rgb(27 72 81 / 8%);
}

.reply-draft--sent {
  border-color: var(--success-border);
}

.reply-draft--discarded {
  opacity: 0.68;
}

.reply-draft header {
  display: flex;
  height: 35px;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
  background: var(--brand-soft);
  padding: 0 10px;
}

.draft-title,
.draft-state {
  display: flex;
  align-items: center;
  gap: 5px;
}

.draft-title {
  color: var(--brand-strong);
  font-size: 10px;
  font-weight: 700;
}

.draft-state {
  color: var(--success-strong);
  font-size: 9px;
}

.draft-target {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 9px 11px 0;
  color: var(--text-secondary);
  font-size: 9px;
}

.target-arrow {
  color: var(--text-muted);
}

.draft-content {
  margin: 9px 11px 11px;
  color: var(--text);
  font-size: 11px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.reply-draft textarea {
  display: block;
  width: calc(100% - 22px);
  margin: 9px 11px 0;
  resize: vertical;
  border: 1px solid var(--brand-border);
  border-radius: 6px;
  color: var(--text);
  background: var(--surface-subtle);
  padding: 8px;
  font: inherit;
  font-size: 11px;
  line-height: 1.6;
  outline: none;
}

.reply-draft footer {
  border-top: 1px solid var(--border);
  margin: 0;
  padding: 8px 10px;
}

.button-primary,
.button-secondary,
.button-ghost {
  display: inline-flex;
  height: 28px;
  cursor: pointer;
  align-items: center;
  justify-content: center;
  border-radius: 5px;
  padding: 0 9px;
  font: inherit;
  font-size: 9px;
  font-weight: 650;
}

.button-primary {
  border: 1px solid var(--brand);
  color: #ffffff;
  background: var(--brand);
}

.button-secondary {
  border: 1px solid var(--border-strong);
  color: var(--text-secondary);
  background: var(--surface);
}

.button-ghost {
  border: 1px solid transparent;
  color: var(--text-secondary);
  background: transparent;
}

.button-ghost:hover {
  background: var(--surface-hover);
}

.icon-text {
  gap: 4px;
}

.danger {
  color: var(--danger);
}

.send-draft {
  margin-left: auto;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.35;
    transform: scale(0.85);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}
</style>
