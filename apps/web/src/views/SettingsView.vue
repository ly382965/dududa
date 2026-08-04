<script setup lang="ts">
import {
  CalendarDays,
  Database,
  HardDrive,
  LoaderCircle,
  Monitor,
  Moon,
  RefreshCw,
  Square,
  Sun,
  Trash2,
} from '@lucide/vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { workspaceCache, type CacheStatistics } from '../services/database'
import { backfillHistory, type HistoryBackfillProgress } from '../services/history-backfill'
import { workspaceAdapter } from '../services/workspace-adapter'
import { useQqDirectoryStore } from '../stores/qq-directory'
import type { Account, Conversation, ThemeMode } from '../types/workspace'

const props = defineProps<{
  account?: Account
  conversations: Conversation[]
  theme: ThemeMode
}>()
const emit = defineEmits<{ toggleTheme: []; setTheme: [theme: ThemeMode]; notify: [message: string] }>()
const directoryStore = useQqDirectoryStore()

interface CleanupTarget {
  mode: 'before' | 'account' | 'all'
  accountId?: string
  accountName?: string
  conversationId?: string
  cutoff?: number
  cutoffLabel?: string
}

const stats = ref<CacheStatistics>({
  conversationCount: 0,
  messageCount: 0,
  eventCount: 0,
  notificationCount: 0,
  draftCount: 0,
  estimatedUsage: 0,
  estimatedQuota: 0,
})
const selectedConversationId = ref('all')
const historyStart = ref(dateValue(-30))
const historyEnd = ref(dateValue())
const cleanupBefore = ref(dateValue(-90))
const loadingStats = ref(false)
const cleanupTarget = ref<CleanupTarget>()
const cleaning = ref(false)
const backfillState = ref<'idle' | 'running' | 'cancelling' | 'complete' | 'cancelled' | 'error'>('idle')
const backfillProgress = ref<HistoryBackfillProgress>({
  completedConversations: 0,
  totalConversations: 0,
  fetchedMessages: 0,
  coveredMessages: 0,
  failedConversations: 0,
  truncatedConversations: 0,
  truncations: [],
  cancelled: false,
})
let controller: AbortController | undefined
let statsVersion = 0
let backfillRun = 0

const accountConversations = computed(() =>
  props.conversations.filter((conversation) => conversation.accountId === props.account?.id),
)
const scopedConversations = computed(() =>
  selectedConversationId.value === 'all'
    ? accountConversations.value
    : accountConversations.value.filter((conversation) => conversation.id === selectedConversationId.value),
)
const progressPercent = computed(() =>
  backfillProgress.value.totalConversations
    ? Math.round(
        ((backfillProgress.value.completedConversations +
          backfillProgress.value.failedConversations +
          backfillProgress.value.truncatedConversations) /
          backfillProgress.value.totalConversations) *
          100,
      )
    : 0,
)
const operationBusy = computed(
  () => cleaning.value || backfillState.value === 'running' || backfillState.value === 'cancelling',
)
const themeLabel = computed(() => props.theme === 'system' ? '跟随系统' : props.theme === 'dark' ? '深色' : '浅色')
const supportedCapabilities = computed(() =>
  Object.values(props.account?.capabilities ?? {}).filter((capability) => capability.status === 'supported').length,
)

function dateValue(offset = 0): string {
  const date = new Date()
  date.setHours(0, 0, 0, 0)
  date.setDate(date.getDate() + offset)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function boundary(value: string, end = false): number | undefined {
  const parts = value.split('-').map(Number)
  if (parts.length !== 3 || parts.some((part) => !Number.isInteger(part))) return undefined
  const [year, month, day] = parts as [number, number, number]
  const date = new Date(year, month - 1, day + Number(end))
  if (!end && (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day)) return undefined
  return date.getTime() - Number(end)
}

function bytes(value: number): string {
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / 1024 ** index).toFixed(index >= 2 ? 1 : 0)} ${units[index]}`
}

async function refreshStats(): Promise<void> {
  const accountId = props.account?.id
  if (!accountId) return
  const version = ++statsVersion
  loadingStats.value = true
  try {
    const result = await workspaceCache.statistics(
      accountId,
      selectedConversationId.value === 'all' ? undefined : selectedConversationId.value,
    )
    if (version === statsVersion) stats.value = result
  } finally {
    if (version === statsVersion) loadingStats.value = false
  }
}

async function startBackfill(): Promise<void> {
  const start = boundary(historyStart.value)
  const end = boundary(historyEnd.value, true)
  if (
    start === undefined ||
    end === undefined ||
    start > end ||
    !scopedConversations.value.length ||
    operationBusy.value
  ) return
  controller?.abort()
  const run = ++backfillRun
  const runController = new AbortController()
  controller = runController
  backfillState.value = 'running'
  try {
    const result = await backfillHistory(
      [...scopedConversations.value],
      start,
      end,
      runController.signal,
      (progress) => {
        if (run === backfillRun) backfillProgress.value = progress
      },
      workspaceAdapter,
    )
    if (run !== backfillRun) return
    backfillProgress.value = result
    backfillState.value = result.cancelled
      ? 'cancelled'
      : result.failedConversations > 0 || result.truncatedConversations > 0
        ? 'error'
        : 'complete'
    await refreshStats()
  } catch (cause) {
    if (run !== backfillRun) return
    backfillState.value = runController.signal.aborted ? 'cancelled' : 'error'
    if (!runController.signal.aborted) emit('notify', cause instanceof Error ? cause.message : '历史补齐失败')
  } finally {
    if (run === backfillRun && controller === runController) controller = undefined
  }
}

function cancelBackfill(): void {
  if (!controller) return
  backfillState.value = 'cancelling'
  controller.abort()
}

function requestCleanup(mode: CleanupTarget['mode']): void {
  if (operationBusy.value) return
  if (mode === 'all') {
    cleanupTarget.value = { mode }
    return
  }
  const accountId = props.account?.id
  if (!accountId) return
  if (mode === 'account') {
    cleanupTarget.value = { mode, accountId, accountName: props.account?.name || accountId }
    return
  }
  const cutoff = boundary(cleanupBefore.value)
  if (cutoff === undefined) {
    emit('notify', '缓存清理日期无效')
    return
  }
  cleanupTarget.value = {
    mode,
    accountId,
    accountName: props.account?.name || accountId,
    conversationId: selectedConversationId.value === 'all' ? undefined : selectedConversationId.value,
    cutoff,
    cutoffLabel: cleanupBefore.value,
  }
}

async function confirmCleanup(): Promise<void> {
  const target = cleanupTarget.value
  if (!target || operationBusy.value) return
  cleaning.value = true
  try {
    if (target.mode === 'all') {
      await workspaceCache.clearAll()
      directoryStore.clearAllState()
    } else if (target.mode === 'account' && target.accountId) {
      await workspaceCache.clearAccount(target.accountId)
      directoryStore.clearAccountState(target.accountId)
    } else {
      if (!target.accountId || target.cutoff === undefined) throw new Error('缓存清理范围无效')
      await workspaceCache.clearBefore(
        target.accountId,
        target.cutoff,
        target.conversationId,
      )
      directoryStore.clearBeforeState(target.accountId, target.cutoff, target.conversationId)
    }
    cleanupTarget.value = undefined
    await refreshStats()
    emit('notify', '本地 QQ 缓存已清理')
  } catch (cause) {
    emit('notify', cause instanceof Error ? cause.message : '缓存清理失败')
  } finally {
    cleaning.value = false
  }
}

watch(
  () => props.account?.id,
  () => {
    backfillRun += 1
    controller?.abort()
    controller = undefined
    cleanupTarget.value = undefined
    selectedConversationId.value = 'all'
    backfillState.value = 'idle'
    void refreshStats()
  },
  { immediate: true },
)
watch(selectedConversationId, () => {
  cleanupTarget.value = undefined
  void refreshStats()
})
onBeforeUnmount(() => {
  backfillRun += 1
  controller?.abort()
})
</script>

<template>
  <main class="settings-view">
    <header class="view-header">
      <div><small>CLIENT & STORAGE</small><h1>设置</h1></div>
      <button class="icon-button" type="button" title="刷新缓存统计" :disabled="loadingStats" @click="refreshStats">
        <RefreshCw :class="{ spin: loadingStats }" :size="17" />
      </button>
    </header>

    <section class="setting-section">
      <div class="section-heading"><Sun :size="18" /><span><strong>外观</strong><small>当前主题：{{ themeLabel }}</small></span></div>
      <div class="theme-control" role="group" aria-label="主题">
        <button :class="{ active: theme === 'light' }" type="button" @click="emit('setTheme', 'light')"><Sun :size="15" />浅色</button>
        <button :class="{ active: theme === 'dark' }" type="button" @click="emit('setTheme', 'dark')"><Moon :size="15" />深色</button>
        <button :class="{ active: theme === 'system' }" type="button" @click="emit('setTheme', 'system')"><Monitor :size="15" />跟随系统</button>
      </div>
    </section>

    <section class="setting-section implementation-section">
      <div class="section-heading"><HardDrive :size="18" /><span><strong>NapCat 实现</strong><small>{{ account?.botId || '-' }}</small></span></div>
      <dl>
        <div><dt>实现</dt><dd>{{ account?.implementation?.name || '未知' }}</dd></div>
        <div><dt>版本</dt><dd>{{ account?.implementation?.version || '未知' }}</dd></div>
        <div><dt>协议</dt><dd>{{ account?.implementation?.protocol || 'onebot-v11' }}</dd></div>
        <div><dt>已启用能力</dt><dd>{{ supportedCapabilities }}</dd></div>
      </dl>
    </section>

    <section class="setting-section data-section">
      <div class="section-heading"><Database :size="18" /><span><strong>本地 QQ 数据</strong><small>{{ bytes(stats.estimatedUsage) }} / {{ bytes(stats.estimatedQuota) }}</small></span></div>
      <label class="scope-select">范围
        <select v-model="selectedConversationId" aria-label="缓存与历史范围">
          <option value="all">当前账号全部会话</option>
          <option v-for="conversation in accountConversations" :key="conversation.id" :value="conversation.id">{{ conversation.name }}</option>
        </select>
      </label>
      <dl class="stats-grid">
        <div><dt>会话</dt><dd>{{ stats.conversationCount }}</dd></div>
        <div><dt>消息</dt><dd>{{ stats.messageCount.toLocaleString() }}</dd></div>
        <div><dt>事件</dt><dd>{{ stats.eventCount.toLocaleString() }}</dd></div>
        <div><dt>通知</dt><dd>{{ stats.notificationCount.toLocaleString() }}</dd></div>
        <div><dt>草稿</dt><dd>{{ stats.draftCount }}</dd></div>
      </dl>
    </section>

    <section class="setting-section history-section">
      <div class="section-heading"><CalendarDays :size="18" /><span><strong>历史补齐</strong><small>通过 NapCat 逐页读取并写入本地缓存</small></span></div>
      <div class="date-row">
        <label>开始<input v-model="historyStart" type="date" :max="historyEnd" /></label>
        <label>结束<input v-model="historyEnd" type="date" :min="historyStart" /></label>
        <button v-if="backfillState === 'running' || backfillState === 'cancelling'" type="button" :disabled="backfillState === 'cancelling'" @click="cancelBackfill"><Square :size="14" />{{ backfillState === 'cancelling' ? '正在中止' : '中止' }}</button>
        <button v-else class="primary" type="button" :disabled="!scopedConversations.length || operationBusy" @click="startBackfill">开始补齐</button>
      </div>
      <div v-if="backfillState !== 'idle'" class="progress-block" aria-live="polite">
        <span><i :style="{ width: `${progressPercent}%` }" /></span>
        <p>{{ backfillProgress.completedConversations + backfillProgress.failedConversations + backfillProgress.truncatedConversations }} / {{ backfillProgress.totalConversations }} 个会话 · {{ backfillProgress.fetchedMessages }} 条已缓存 · {{ backfillProgress.coveredMessages }} 条位于日期范围</p>
        <p v-if="backfillProgress.failedConversations" class="progress-warning">{{ backfillProgress.failedConversations }} 个会话读取失败，当前缓存并不完整。</p>
        <p v-if="backfillProgress.truncatedConversations" class="progress-warning">{{ backfillProgress.truncatedConversations }} 个会话达到本地补齐上限，未声明为完整覆盖。</p>
      </div>
    </section>

    <section class="setting-section cleanup-section">
      <div class="section-heading"><Trash2 :size="18" /><span><strong>缓存清理</strong><small>不会删除或撤回 QQ 服务器数据</small></span></div>
      <div class="cleanup-row">
        <input v-model="cleanupBefore" type="date" aria-label="清理此日期前缓存" />
        <button type="button" :disabled="operationBusy" @click="requestCleanup('before')">清理日期前记录</button>
        <button class="danger" type="button" :disabled="operationBusy" @click="requestCleanup('account')">清理当前账号</button>
        <button class="danger" type="button" :disabled="operationBusy" @click="requestCleanup('all')">清理全部账号</button>
      </div>
      <div v-if="cleanupTarget" class="confirm-strip" role="alertdialog" aria-label="确认清理缓存">
        <span v-if="cleanupTarget.mode === 'all'">删除所有 QQ 账号的浏览器缓存？QQ 服务器数据不会改变。</span>
        <span v-else-if="cleanupTarget.mode === 'account'">删除 {{ cleanupTarget.accountName }} 的全部浏览器缓存？</span>
        <span v-else>删除 {{ cleanupTarget.accountName }} 在 {{ cleanupTarget.cutoffLabel }} 前的{{ cleanupTarget.conversationId ? '所选会话' : '全部会话' }}缓存？</span>
        <button type="button" :disabled="cleaning" @click="cleanupTarget = undefined">取消</button>
        <button class="danger" type="button" :disabled="cleaning" @click="confirmCleanup"><LoaderCircle v-if="cleaning" class="spin" :size="14" />确认清理</button>
      </div>
    </section>
  </main>
</template>

<style scoped>
.settings-view { min-height: 0; overflow-y: auto; background: var(--app-background); padding: 24px clamp(16px, 3vw, 38px) 42px; }
.view-header { display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); padding-bottom: 17px; }
.view-header small { color: var(--brand-strong); font-size: 9px; font-weight: 800; }
h1 { margin: 4px 0 0; color: var(--text); font-size: 22px; letter-spacing: 0; }
.setting-section { display: grid; grid-template-columns: minmax(210px, .7fr) minmax(340px, 1.3fr); align-items: start; gap: 28px; border-bottom: 1px solid var(--border); padding: 20px 0; }
.section-heading { display: flex; align-items: flex-start; gap: 10px; color: var(--brand-strong); }
.section-heading span { display: grid; gap: 4px; }
.section-heading strong { color: var(--text); font-size: 12px; }
.section-heading small { color: var(--text-muted); font-size: 9px; line-height: 1.4; }
.theme-control { display: grid; width: min(390px, 100%); grid-template-columns: repeat(3, minmax(0, 1fr)); border-radius: 6px; background: var(--surface-muted); padding: 3px; }
.theme-control button { display: flex; height: 34px; cursor: pointer; align-items: center; justify-content: center; gap: 6px; border: 0; border-radius: 4px; color: var(--text-muted); background: transparent; font-size: 10px; }
.theme-control button.active { color: var(--text); background: var(--surface); box-shadow: 0 1px 4px rgb(19 37 41 / 8%); }
dl { display: grid; margin: 0; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; background: var(--border); }
dl div { display: grid; gap: 3px; background: var(--surface); padding: 10px 12px; }
dt { color: var(--text-muted); font-size: 9px; }
dd { margin: 0; color: var(--text); font-size: 11px; font-weight: 650; }
.data-section, .history-section, .cleanup-section { grid-template-columns: minmax(210px, .7fr) minmax(340px, 1.3fr); }
.data-section > :not(.section-heading), .history-section > :not(.section-heading), .cleanup-section > :not(.section-heading) { grid-column: 2; }
.scope-select, .date-row label { display: flex; align-items: center; gap: 8px; color: var(--text-muted); font-size: 10px; }
select, input[type='date'] { min-width: 0; height: 34px; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--surface); padding: 0 9px; font: inherit; font-size: 10px; }
.scope-select select { flex: 1; }
.stats-grid { margin-top: 9px; grid-template-columns: repeat(5, minmax(0, 1fr)); }
.date-row, .cleanup-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.date-row button, .cleanup-row button, .confirm-strip button { display: flex; height: 34px; cursor: pointer; align-items: center; justify-content: center; gap: 5px; border: 1px solid var(--border); border-radius: 5px; color: var(--text-secondary); background: var(--surface); padding: 0 11px; font-size: 10px; }
button.primary { border-color: var(--brand); color: #fff; background: var(--brand); }
button.danger { border-color: var(--danger); color: var(--danger); }
button:disabled { cursor: not-allowed; opacity: .5; }
.progress-block { margin-top: 10px; }
.progress-block > span { display: block; height: 5px; overflow: hidden; border-radius: 3px; background: var(--surface-muted); }
.progress-block i { display: block; height: 100%; background: var(--brand); transition: width 180ms ease; }
.progress-block p { margin: 6px 0 0; color: var(--text-muted); font-size: 9px; }
.progress-block .progress-warning { color: var(--warning); }
.confirm-strip { display: flex; align-items: center; gap: 7px; margin-top: 9px; border-left: 3px solid var(--danger); background: var(--danger-soft); padding: 8px 10px; }
.confirm-strip span { min-width: 0; flex: 1; color: var(--text-secondary); font-size: 10px; }
.spin { animation: spin 850ms linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 720px) {
  .settings-view { padding: 18px 13px 30px; }
  .setting-section, .data-section, .history-section, .cleanup-section { grid-template-columns: minmax(0, 1fr); gap: 13px; }
  .data-section > :not(.section-heading), .history-section > :not(.section-heading), .cleanup-section > :not(.section-heading) { grid-column: 1; }
  .stats-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
