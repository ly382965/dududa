<script setup lang="ts">
import {
  Activity,
  Check,
  CircleAlert,
  CircleCheck,
  Clock3,
  KeyRound,
  LoaderCircle,
  Pencil,
  Plus,
  Power,
  RefreshCw,
  Save,
  ShieldCheck,
  Trash2,
  X,
} from '@lucide/vue'
import { computed, nextTick, onMounted, ref } from 'vue'

import { apiKeyPoolsAdapter } from '../services/api-key-pools'
import type {
  ApiKeyCreateRequest,
  ApiKeyCustomHeader,
  ApiKeyEntry,
  ApiKeyMutationResponse,
  ApiKeyPool,
  ApiKeyPoolTestResult,
  ApiKeyPoolUpdateRequest,
  ApiKeyPoolsAdapter,
  ApiKeyStatus,
  ApiKeyTier,
  ApiKeyUpdateRequest,
  RuntimeConfigStatus,
} from '../types/api-key-pools'
import {
  API_KEY_TIERS,
  API_KEY_TIER_DESCRIPTIONS,
  API_KEY_TIER_LABELS,
  emptyApiKeyPool,
} from '../types/api-key-pools'

const props = withDefaults(defineProps<{ adapter?: ApiKeyPoolsAdapter }>(), {
  adapter: () => apiKeyPoolsAdapter,
})

const emit = defineEmits<{ notify: [message: string] }>()

interface PoolForm {
  displayName: string
  provider: string
  providerType: string
  providerId: string
  sourceId: string
  baseUrl: string
  model: string
  protocol: string
  reasoningEffort: string
  timeoutMs: number
  maxOutputTokens: number
  enabled: boolean
  schedulingMode: string
  customHeadersText: string
  revision: number | string
}

interface KeyForm {
  name: string
  secret: string
  secretRef: string
  priority: number
  weight: number
  enabled: boolean
}

const pools = ref<ApiKeyPool[]>(API_KEY_TIERS.map(emptyApiKeyPool))
const loading = ref(false)
const error = ref('')
const notice = ref('')
const collectionRevision = ref<number | string>(1)
const runtimeState = ref<RuntimeConfigStatus>()
const runtimeError = ref('')
const applyingRuntime = ref(false)
let runtimeStatusGeneration = 0

async function refreshRuntime(): Promise<void> {
  if (!props.adapter.runtimeStatus) return
  const generation = ++runtimeStatusGeneration
  try {
    const state = await props.adapter.runtimeStatus()
    if (generation !== runtimeStatusGeneration) return
    runtimeState.value = state
    runtimeError.value = ''
  } catch (cause) {
    if (generation !== runtimeStatusGeneration) return
    runtimeState.value = undefined
    runtimeError.value = cause instanceof Error ? cause.message : 'Runtime 配置状态读取失败'
  }
}

async function applyRuntime(): Promise<void> {
  if (!props.adapter.applyRuntime || applyingRuntime.value) return
  applyingRuntime.value = true
  const generation = ++runtimeStatusGeneration
  runtimeError.value = ''
  try {
    const state = await props.adapter.applyRuntime(collectionRevision.value)
    if (generation !== runtimeStatusGeneration) return
    runtimeState.value = state
    if (runtimeState.value.status !== 'applied' || !runtimeState.value.ready) {
      runtimeError.value = '服务端尚未确认新配置可用，请刷新实际状态'
    } else setNotice('已应用到 Dududa Runtime；其他 AstrBot 插件保持原配置直到冷重启')
  } catch (cause) {
    runtimeError.value = cause instanceof Error ? cause.message : 'Runtime 配置应用失败'
  } finally {
    applyingRuntime.value = false
  }
}

function captureMutation(response: ApiKeyMutationResponse): void {
  if (response.revision !== undefined) collectionRevision.value = response.revision
  if (runtimeState.value) runtimeState.value = { ...runtimeState.value, status: 'pending', message: '保存内容已变化，请应用到 Runtime' }
  void refreshRuntime()
}
const poolEditorTier = ref<ApiKeyTier>()
const poolDraft = ref<PoolForm>()
const poolFormError = ref('')
const poolSaving = ref(false)
const keyEditor = ref<{ tier: ApiKeyTier; keyId?: string; revision: number | string }>()
const keyDraft = ref<KeyForm>()
const keyFormError = ref('')
const keySaving = ref(false)
const pendingRemove = ref<{ tier: ApiKeyTier; keyId: string }>()
const testingTier = ref<ApiKeyTier>()
const testResults = ref<Partial<Record<ApiKeyTier, ApiKeyPoolTestResult>>>({})
const poolDialog = ref<HTMLElement>()
const keyDialog = ref<HTMLElement>()
let loadGeneration = 0
let dialogReturnFocus: HTMLElement | undefined

const DIALOG_FOCUSABLE = 'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

const editingKey = computed(() => {
  const editor = keyEditor.value
  if (!editor) return undefined
  return pools.value.find((pool) => pool.tier === editor.tier)?.keys.find((key) => key.id === editor.keyId)
})
const keyDialogTitle = computed(() => editingKey.value ? '编辑 Provider Key' : '添加 Provider Key')

const statusLabels: Record<string, string> = {
  active: '可用',
  configured: '已配置',
  disabled: '已停用',
  cooldown: '冷却中',
  unavailable: '不可用',
  pending: '待同步',
  error: '异常',
}

const statusClasses: Record<string, string> = {
  active: 'status--ok',
  configured: 'status--ok',
  disabled: 'status--disabled',
  cooldown: 'status--warning',
  unavailable: 'status--danger',
  pending: 'status--warning',
  error: 'status--danger',
}

const reasoningOptions: Array<{ value: string; label: string }> = [
  { value: 'off', label: '关闭' },
  { value: 'low', label: '低（low）' },
  { value: 'medium', label: '中（medium）' },
  { value: 'high', label: '高（high）' },
  { value: 'max', label: '最高（max，DeepSeek）' },
]

const schedulingOptions: Array<{ value: string; label: string }> = [
  { value: 'round_robin', label: '轮询' },
  { value: 'priority', label: '优先级' },
  { value: 'health_first', label: '健康优先' },
]

function poolFor(tier: ApiKeyTier): ApiKeyPool {
  return pools.value.find((pool) => pool.tier === tier) ?? emptyApiKeyPool(tier)
}

function editConnectionFromKey(): void {
  const tier = keyEditor.value?.tier
  if (!tier || keySaving.value) return
  closeKeyEditor()
  openPoolEditor(tier)
}

function displayStatus(status: ApiKeyStatus): string {
  return statusLabels[status] ?? status
}

function statusClass(status: ApiKeyStatus): string {
  return statusClasses[status] ?? 'status--disabled'
}

function formatTime(value?: string): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function formatCooldown(key: ApiKeyEntry): string {
  if (!key.cooldownUntil) return ''
  const date = new Date(key.cooldownUntil)
  if (Number.isNaN(date.getTime())) return '冷却时间未知'
  return `冷却至 ${date.toLocaleTimeString('zh-CN', { hour12: false })}`
}

function keyHealthText(key: ApiKeyEntry): string {
  const cooldown = formatCooldown(key)
  if (cooldown) return cooldown
  if (key.status === 'error' || key.status === 'unavailable') {
    return `失败 ${formatTime(key.lastFailureAt ?? key.updatedAt)}`
  }
  if (!key.enabled || key.status === 'disabled') return `更新 ${formatTime(key.updatedAt)}`
  return `成功 ${formatTime(key.lastSuccessAt)}`
}

function poolForm(pool: ApiKeyPool): PoolForm {
  return {
    displayName: pool.displayName,
    provider: pool.provider,
    providerType: pool.providerType ?? '',
    providerId: pool.providerId ?? '',
    sourceId: pool.sourceId ?? '',
    baseUrl: pool.baseUrl,
    model: pool.model,
    protocol: pool.protocol,
    reasoningEffort: pool.reasoningEffort,
    timeoutMs: pool.timeoutMs,
    maxOutputTokens: pool.maxOutputTokens,
    enabled: pool.enabled,
    schedulingMode: pool.schedulingMode,
    customHeadersText: pool.customHeaders.map((header) => `${header.name}=${header.value}`).join('\n'),
    revision: pool.revision,
  }
}

function keyForm(key?: ApiKeyEntry): KeyForm {
  return {
    name: key?.name ?? '',
    secret: '',
    secretRef: key?.secretRef ?? '',
    priority: key?.priority ?? 0,
    weight: key?.weight ?? 1,
    enabled: key?.enabled ?? true,
  }
}

function setNotice(message: string): void {
  notice.value = message
  error.value = ''
}

function invalidatePendingLoad(): void {
  loadGeneration += 1
  loading.value = false
}

function clearTestResult(tier: ApiKeyTier): void {
  if (!testResults.value[tier]) return
  const next = { ...testResults.value }
  delete next[tier]
  testResults.value = next
}

function applyPool(pool: ApiKeyPool): void {
  const index = pools.value.findIndex((item) => item.tier === pool.tier)
  if (index < 0) pools.value = [...pools.value, pool]
  else pools.value.splice(index, 1, pool)
}

function mergeMutationPool(response: ApiKeyMutationResponse, fallback: ApiKeyPool): void {
  captureMutation(response)
  if (response.pool) {
    applyPool(response.pool)
    return
  }
  applyPool(fallback)
}

function parseHeaders(value: string): { headers?: ApiKeyCustomHeader[]; error?: string } {
  const headers: ApiKeyCustomHeader[] = []
  for (const [index, line] of value.split('\n').map((item) => item.trim()).filter(Boolean).entries()) {
    const separator = line.indexOf('=')
    if (separator < 1 || separator === line.length - 1) {
      return { error: `自定义 Header 第 ${index + 1} 行应为 Header-Name=value` }
    }
    const name = line.slice(0, separator).trim()
    const headerValue = line.slice(separator + 1).trim()
    if (!/^[A-Za-z0-9][A-Za-z0-9-]{0,127}$/.test(name)) {
      return { error: `自定义 Header 名称无效：${name}` }
    }
    if (/authorization|api[-_]?key|token|secret|password|cookie|credential/i.test(name)) {
      return { error: '认证 Header 必须通过 SecretRef 注入，不能在此填写' }
    }
    headers.push({ name, value: headerValue })
  }
  return { headers }
}

function validHttpUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password && !url.search && !url.hash
  } catch {
    return false
  }
}

async function load(): Promise<void> {
  const generation = ++loadGeneration
  ++runtimeStatusGeneration
  loading.value = true
  error.value = ''
  try {
    const response = await props.adapter.list()
    if (generation !== loadGeneration) return
    collectionRevision.value = response.revision
    const byTier = new Map(response.pools.map((pool) => [pool.tier, pool]))
    const nextPools = API_KEY_TIERS.map((tier) => byTier.get(tier) ?? emptyApiKeyPool(tier))
    const nextResults = { ...testResults.value }
    for (const tier of API_KEY_TIERS) {
      const result = nextResults[tier]
      const nextPool = nextPools.find((pool) => pool.tier === tier)
      if (result && (result.revision === undefined || result.revision !== nextPool?.revision)) delete nextResults[tier]
    }
    pools.value = nextPools
    testResults.value = nextResults
    void refreshRuntime()
  } catch (cause) {
    if (generation !== loadGeneration) return
    error.value = cause instanceof Error ? cause.message : 'API Key 池读取失败'
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

function openPoolEditor(tier: ApiKeyTier): void {
  if (loading.value) return
  rememberDialogTrigger()
  poolEditorTier.value = tier
  poolDraft.value = poolForm(poolFor(tier))
  poolFormError.value = ''
  notice.value = ''
  focusDialog(poolDialog)
}

function closePoolEditor(force = false): void {
  if (poolSaving.value && !force) return
  poolEditorTier.value = undefined
  poolDraft.value = undefined
  poolFormError.value = ''
  restoreDialogFocus()
}

async function savePool(): Promise<void> {
  const tier = poolEditorTier.value
  const draft = poolDraft.value
  const current = tier ? poolFor(tier) : undefined
  if (!tier || !draft || !current || poolSaving.value) return
  const displayName = draft.displayName.trim()
  const provider = draft.provider.trim()
  const providerId = draft.providerId.trim()
  const sourceId = draft.sourceId.trim()
  const baseUrl = draft.baseUrl.trim()
  const model = draft.model.trim()
  if (!displayName || !provider || !baseUrl || !model) {
    poolFormError.value = '显示名称、Provider、Base URL 和模型 ID 不能为空'
    return
  }
  const runtimeIdPattern = /^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$/
  if (providerId && !runtimeIdPattern.test(providerId)) {
    poolFormError.value = 'Provider ID 格式无效；仅允许字母、数字及 _ . : / -'
    return
  }
  if (sourceId && !runtimeIdPattern.test(sourceId)) {
    poolFormError.value = 'Source ID 格式无效；仅允许字母、数字及 _ . : / -'
    return
  }
  if (!validHttpUrl(baseUrl)) {
    poolFormError.value = 'Base URL 必须是无凭据、无查询参数的 HTTP(S) 地址'
    return
  }
  if (!Number.isInteger(draft.timeoutMs) || draft.timeoutMs < 1_000 || draft.timeoutMs > 900_000) {
    poolFormError.value = '超时必须在 1,000–900,000 ms 之间'
    return
  }
  if (!Number.isInteger(draft.maxOutputTokens) || draft.maxOutputTokens < 1 || draft.maxOutputTokens > 1_000_000) {
    poolFormError.value = '输出预算必须是 1–1,000,000 的整数'
    return
  }
  const parsedHeaders = parseHeaders(draft.customHeadersText)
  if (parsedHeaders.error || !parsedHeaders.headers) {
    poolFormError.value = parsedHeaders.error || '自定义 Header 无效'
    return
  }
  poolSaving.value = true
  poolFormError.value = ''
  invalidatePendingLoad()
  const request: ApiKeyPoolUpdateRequest = {
    displayName,
    provider,
    ...(draft.providerType.trim() ? { providerType: draft.providerType.trim() } : {}),
    providerId,
    sourceId,
    baseUrl,
    model,
    protocol: draft.protocol.trim() || 'openai_chat_completions',
    reasoningEffort: draft.reasoningEffort.trim() || 'low',
    timeoutMs: draft.timeoutMs,
    maxOutputTokens: draft.maxOutputTokens,
    enabled: draft.enabled,
    schedulingMode: draft.schedulingMode.trim() || 'round_robin',
    customHeaders: parsedHeaders.headers,
    revision: draft.revision,
  }
  try {
    const response = await props.adapter.updatePool(tier, request)
    const fallback: ApiKeyPool = {
      ...current,
      ...request,
      customHeaders: [...request.customHeaders],
      revision: typeof current.revision === 'number' ? current.revision + 1 : current.revision,
    }
    mergeMutationPool(response, fallback)
    clearTestResult(tier)
    closePoolEditor(true)
    setNotice(`${API_KEY_TIER_LABELS[tier]} 配置已保存；请点击“应用到 Runtime”使其生效`)
  } catch (cause) {
    poolFormError.value = cause instanceof Error ? cause.message : 'Provider 池保存失败'
  } finally {
    poolSaving.value = false
  }
}

function openKeyEditor(tier: ApiKeyTier, key?: ApiKeyEntry): void {
  if (loading.value) return
  rememberDialogTrigger()
  keyEditor.value = { tier, ...(key ? { keyId: key.id } : {}), revision: poolFor(tier).revision }
  keyDraft.value = keyForm(key)
  keyFormError.value = ''
  pendingRemove.value = undefined
  notice.value = ''
  focusDialog(keyDialog)
}

function closeKeyEditor(force = false): void {
  if (keySaving.value && !force) return
  if (keyDraft.value) keyDraft.value.secret = ''
  keyEditor.value = undefined
  keyDraft.value = undefined
  keyFormError.value = ''
  restoreDialogFocus()
}

function rememberDialogTrigger(): void {
  dialogReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : undefined
}

function focusDialog(dialog: typeof poolDialog): void {
  void nextTick(() => {
    const element = dialog.value
    const target = element?.querySelector<HTMLElement>(DIALOG_FOCUSABLE) ?? element
    target?.focus()
  })
}

function restoreDialogFocus(): void {
  const target = dialogReturnFocus
  dialogReturnFocus = undefined
  void nextTick(() => {
    if (target?.isConnected) target.focus()
  })
}

function handleDialogKeydown(event: KeyboardEvent, close: () => void): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }
  if (event.key !== 'Tab') return
  const dialog = event.currentTarget instanceof HTMLElement ? event.currentTarget : undefined
  const focusable = dialog
    ? [...dialog.querySelectorAll<HTMLElement>(DIALOG_FOCUSABLE)].filter((item) => !item.hidden)
    : []
  if (!focusable.length) {
    event.preventDefault()
    dialog?.focus()
    return
  }
  const first = focusable[0]!
  const last = focusable[focusable.length - 1]!
  if (event.shiftKey && (document.activeElement === first || !dialog?.contains(document.activeElement))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

async function saveKey(): Promise<void> {
  const editor = keyEditor.value
  const draft = keyDraft.value
  if (!editor || !draft || keySaving.value) return
  const name = draft.name.trim()
  const secret = draft.secret.trim()
  const secretRef = draft.secretRef.trim()
  if (!name) {
    keyFormError.value = 'Key 显示名称不能为空'
    return
  }
  if (!editor.keyId && !secret) {
    keyFormError.value = '新 Key 必须填写密钥；已有 Key 留空表示保持不变'
    return
  }
  if (secretRef && !/^[A-Za-z0-9][A-Za-z0-9._/-]{1,159}$/.test(secretRef)) {
    keyFormError.value = 'SecretRef ID 格式无效'
    return
  }
  if (!Number.isInteger(draft.priority) || draft.priority < 0 || draft.priority > 1_000_000) {
    keyFormError.value = '优先级必须是 0–1,000,000 的整数'
    return
  }
  if (!Number.isInteger(draft.weight) || draft.weight < 1 || draft.weight > 1_000) {
    keyFormError.value = '权重必须是 1–1,000 的整数'
    return
  }
  keySaving.value = true
  keyFormError.value = ''
  invalidatePendingLoad()
  // Construct the request before clearing the input. The adapter serializes it
  // immediately; the component retains no secret while the network is pending.
  const request: ApiKeyCreateRequest | ApiKeyUpdateRequest = {
    name,
    ...(secret ? { secret } : {}),
    ...(editor.keyId ? { secretRef } : secretRef ? { secretRef } : {}),
    priority: draft.priority,
    weight: draft.weight,
    enabled: draft.enabled,
    ...(editor.keyId ? { revision: editor.revision } : {}),
  }
  draft.secret = ''
  try {
    const response = editor.keyId
      ? await props.adapter.updateKey(editor.tier, editor.keyId, request as ApiKeyUpdateRequest)
      : await props.adapter.createKey(editor.tier, request as ApiKeyCreateRequest)
    captureMutation(response)
    const current = poolFor(editor.tier)
    if (response.pool) {
      applyPool(response.pool)
    } else if (editor.keyId) {
      const nextKey = response.key ?? current.keys.find((key) => key.id === editor.keyId)
      if (nextKey) applyPool({ ...current, keys: current.keys.map((key) => key.id === editor.keyId ? nextKey : key) })
    } else if (response.key) {
      applyPool({ ...current, keys: [response.key, ...current.keys] })
    } else {
      await load()
    }
    clearTestResult(editor.tier)
    closeKeyEditor(true)
    setNotice(editor.keyId ? 'Provider Key 已保存；请应用到 Runtime' : 'Provider Key 已登记；密钥不会再次显示，请应用到 Runtime')
  } catch (cause) {
    keyFormError.value = cause instanceof Error ? cause.message : 'Provider Key 保存失败；请重新输入密钥'
  } finally {
    // Also clear a stale reference if an adapter throws synchronously.
    draft.secret = ''
    keySaving.value = false
  }
}

function requestRemove(tier: ApiKeyTier, keyId: string): void {
  if (pendingRemove.value?.tier === tier && pendingRemove.value.keyId === keyId) {
    void removeKey(tier, keyId)
    return
  }
  pendingRemove.value = { tier, keyId }
}

async function removeKey(tier: ApiKeyTier, keyId: string): Promise<void> {
  if (loading.value) return
  pendingRemove.value = undefined
  invalidatePendingLoad()
  try {
    const response = await props.adapter.deleteKey(tier, keyId)
    captureMutation(response)
    const current = poolFor(tier)
    if (response.pool) applyPool(response.pool)
    else applyPool({ ...current, keys: current.keys.filter((key) => key.id !== keyId) })
    clearTestResult(tier)
    setNotice('Provider Key 已停用并从当前池移除')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Provider Key 移除失败'
  }
}

async function toggleKey(tier: ApiKeyTier, key: ApiKeyEntry): Promise<void> {
  if (loading.value) return
  invalidatePendingLoad()
  try {
    const current = poolFor(tier)
    const response = await props.adapter.updateKey(tier, key.id, { enabled: !key.enabled, revision: current.revision })
    captureMutation(response)
    if (response.pool) applyPool(response.pool)
    else if (response.key) applyPool({ ...current, keys: current.keys.map((item) => item.id === key.id ? response.key! : item) })
    else applyPool({ ...current, keys: current.keys.map((item) => item.id === key.id ? { ...item, enabled: !key.enabled, status: !key.enabled ? 'active' : 'disabled' } : item) })
    clearTestResult(tier)
    setNotice(key.enabled ? 'Provider Key 已停用' : 'Provider Key 已启用')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Provider Key 状态更新失败'
  }
}

async function testPool(tier: ApiKeyTier): Promise<void> {
  if (testingTier.value || loading.value) return
  invalidatePendingLoad()
  testingTier.value = tier
  try {
    const result = await props.adapter.testPool(tier)
    testResults.value = { ...testResults.value, [tier]: result }
    // A probe records health timestamps server-side and therefore advances
    // the pool revision. Keep the local editor's CAS token current so an
    // immediate metadata edit does not fail with a stale-revision response.
    if (result.revision !== undefined) {
      const current = poolFor(tier)
      applyPool({ ...current, revision: result.revision })
    }
    // The probe response is intentionally small and secret-free. Reload the
    // public snapshot so the row reflects the health metadata just persisted.
    await load()
    emit('notify', result.message)
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : 'Provider 探测失败'
    testResults.value = { ...testResults.value, [tier]: { status: 'error', message } }
    error.value = message
  } finally {
    testingTier.value = undefined
  }
}

function testResultClass(result?: ApiKeyPoolTestResult): string {
  if (!result) return ''
  return result.status === 'ok' ? 'test-result--ok' : 'test-result--error'
}

onMounted(() => void load())
</script>

<template>
  <main class="api-key-pools-view">
    <header class="view-header">
      <div>
        <small>PROVIDER CREDENTIALS</small>
        <h1>API Key 池</h1>
        <p>按 Dududa 2.0 三档模型管理 Provider 连接与密钥轮换。</p>
      </div>
      <button class="icon-button" type="button" title="刷新 API Key 池" aria-label="刷新 API Key 池" :disabled="loading" @click="load">
        <RefreshCw :class="{ spin: loading }" :size="17" />
      </button>
    </header>

    <div class="security-note" role="note">
      <ShieldCheck :size="17" />
      <span><strong>密钥边界：</strong>密钥只在添加或轮换时提交，读取仅返回脱敏信息。保存后点击“应用到 Runtime”，服务端会验证三档 Provider 后切换 Dududa；其他 AstrBot 插件保持原配置直到冷重启。应用会进行少量模型连接验证。</span>
    </div>

    <section class="runtime-apply" aria-label="Runtime 配置应用">
      <div><strong>Runtime 配置</strong><p role="status">{{ applyingRuntime ? '正在验证并应用三档配置…' : runtimeState?.message || runtimeError || '尚未确认应用状态' }}</p></div>
      <button type="button" :disabled="!adapter.applyRuntime || loading || applyingRuntime || poolSaving || keySaving || !!testingTier" :aria-busy="applyingRuntime" @click="applyRuntime">
        <LoaderCircle v-if="applyingRuntime" class="spin" :size="15" /><Save v-else :size="15" />应用到 Runtime
      </button>
    </section>
    <p v-if="runtimeError" class="inline-error" role="alert">{{ runtimeError }}</p>

    <p v-if="error" class="inline-error" role="alert"><CircleAlert :size="15" />{{ error }}</p>
    <p v-if="notice" class="inline-notice" role="status"><CircleCheck :size="15" />{{ notice }}</p>

    <section class="pool-grid" aria-label="三档 Provider Key 池">
      <article v-for="tier in API_KEY_TIERS" :key="tier" class="pool-card" :class="`pool-card--${tier}`" :data-tier="tier">
        <header class="pool-card__header">
          <div class="tier-mark"><KeyRound :size="18" /></div>
          <div class="pool-card__title">
            <small>{{ tier.toUpperCase() }} TIER</small>
            <h2>{{ API_KEY_TIER_LABELS[tier] }}</h2>
            <p>{{ API_KEY_TIER_DESCRIPTIONS[tier] }}</p>
          </div>
          <span class="pool-enabled" :class="{ 'pool-enabled--off': !poolFor(tier).enabled }">
            <Power :size="12" />{{ poolFor(tier).enabled ? '启用' : '停用' }}
          </span>
        </header>

        <dl class="pool-facts">
          <div><dt>Provider</dt><dd>{{ poolFor(tier).provider || '未配置' }}</dd></div>
          <div><dt>模型</dt><dd>{{ poolFor(tier).model || '未配置' }}</dd></div>
          <div><dt>Base URL</dt><dd :title="poolFor(tier).baseUrl">{{ poolFor(tier).baseUrl || '未配置' }}</dd></div>
          <div><dt>协议 / 推理</dt><dd>{{ poolFor(tier).protocol }} · {{ poolFor(tier).reasoningEffort }}</dd></div>
          <div><dt>调度</dt><dd>{{ schedulingOptions.find((item) => item.value === poolFor(tier).schedulingMode)?.label ?? poolFor(tier).schedulingMode }}</dd></div>
          <div><dt>预算 / 超时</dt><dd>{{ poolFor(tier).maxOutputTokens.toLocaleString() }} tokens · {{ poolFor(tier).timeoutMs }} ms</dd></div>
        </dl>

        <div v-if="poolFor(tier).runtimeSync" class="runtime-sync" :class="`runtime-sync--${poolFor(tier).runtimeSync?.status}`">
          <Activity :size="13" /><span>Runtime 同步：{{ poolFor(tier).runtimeSync?.message || poolFor(tier).runtimeSync?.status }}</span>
        </div>

        <div class="pool-actions">
          <button type="button" :aria-label="`探测 ${API_KEY_TIER_LABELS[tier]} Provider`" :disabled="Boolean(testingTier) || loading" @click="testPool(tier)">
            <LoaderCircle v-if="testingTier === tier" class="spin" :size="14" /><Activity v-else :size="14" />探测 Provider
          </button>
          <button type="button" :aria-label="`编辑 ${API_KEY_TIER_LABELS[tier]} 池`" :disabled="loading" @click="openPoolEditor(tier)"><Pencil :size="14" />配置 Base URL / 模型</button>
        </div>
        <div v-if="testResults[tier]" class="test-result" :class="testResultClass(testResults[tier])" role="status">
          <Check v-if="testResults[tier]?.status === 'ok'" :size="13" /><CircleAlert v-else :size="13" />
          <span>{{ testResults[tier]?.message }}<small v-if="testResults[tier]?.latencyMs !== undefined"> · {{ testResults[tier]?.latencyMs }} ms</small></span>
        </div>

        <div class="keys-heading">
          <div><h3>Key 列表</h3><span>{{ poolFor(tier).keys.length }} 个凭据 · 仅显示元数据</span></div>
          <button class="add-key" type="button" :disabled="loading" @click="openKeyEditor(tier)"><Plus :size="14" />添加 Key</button>
        </div>
        <div v-if="!poolFor(tier).keys.length" class="keys-empty"><KeyRound :size="22" /><span>此池还没有 Key</span><small>添加后由服务端保存，列表不会返回明文。</small></div>
        <ul v-else class="key-list" :aria-label="`${API_KEY_TIER_LABELS[tier]} Key 列表`">
          <li v-for="key in poolFor(tier).keys" :key="key.id" class="key-row">
            <div class="key-row__main">
              <span class="key-icon"><KeyRound :size="14" /></span>
              <div><strong>{{ key.name }}</strong><code>{{ key.masked || '••••••••' }}</code></div>
            </div>
            <div class="key-row__ref"><small>SecretRef</small><code>{{ key.secretRef || '未绑定' }}</code></div>
            <div class="key-row__priority"><small>优先级 / 权重</small><span>{{ key.priority }} / {{ key.weight }}</span></div>
            <div class="key-row__health">
              <span class="status-chip" :class="statusClass(key.status)">{{ displayStatus(key.status) }}</span>
              <small>{{ keyHealthText(key) }}</small>
            </div>
            <div class="key-row__actions">
              <button type="button" :title="key.enabled ? '停用此 Key' : '启用此 Key'" :aria-label="`${key.enabled ? '停用' : '启用'} ${key.name}`" :disabled="loading" @click="toggleKey(tier, key)"><Power :size="14" />{{ key.enabled ? '停用' : '启用' }}</button>
              <button type="button" :aria-label="`编辑 ${key.name}`" :disabled="loading" @click="openKeyEditor(tier, key)"><Pencil :size="14" />编辑</button>
              <button class="danger" type="button" :aria-label="pendingRemove?.tier === tier && pendingRemove.keyId === key.id ? `确认移除 ${key.name}` : `移除 ${key.name}`" :disabled="loading" @click="requestRemove(tier, key.id)"><Trash2 :size="14" />{{ pendingRemove?.tier === tier && pendingRemove.keyId === key.id ? '再次确认' : '移除' }}</button>
            </div>
          </li>
        </ul>
      </article>
    </section>

    <p class="page-footnote"><Clock3 :size="14" /> Key 的健康状态来自服务端探针。本版的推理强度、输出预算、调度模式和权重是暂存元数据；运行中 Dududa 仍以既有 runtime_models_json 与 conformance evidence 为准，本页不改变 Capability、TierPolicy 或 Delivery 权限。</p>

    <div v-if="poolEditorTier && poolDraft" class="modal-backdrop" role="presentation" @click.self="closePoolEditor()">
      <section ref="poolDialog" class="modal-card pool-editor" role="dialog" aria-modal="true" aria-labelledby="pool-editor-title" tabindex="-1" @keydown="handleDialogKeydown($event, closePoolEditor)">
        <header class="modal-card__header">
          <div><small>POOL CONFIGURATION</small><h2 id="pool-editor-title">编辑 {{ API_KEY_TIER_LABELS[poolEditorTier] }}</h2></div>
          <button class="icon-button" type="button" title="关闭" aria-label="关闭池配置" :disabled="poolSaving" @click="closePoolEditor()"><X :size="17" /></button>
        </header>
        <form class="editor-form" @submit.prevent="savePool">
          <p class="connection-help">同一档的所有 Key 共用此连接。DeepSeek：Provider 填 DeepSeek，Base URL 填 https://api.deepseek.com，协议选 OpenAI Chat Completions；模型 ID 按 DeepSeek 控制台填写。保存后再添加 Key。模型变更需要运行时绑定验证，探测通过不代表已应用到 Bot。</p>
          <div class="form-grid form-grid--two">
            <label>显示名称<input v-model="poolDraft.displayName" autocomplete="off" /></label>
            <label>Provider<input v-model="poolDraft.provider" autocomplete="off" placeholder="例如 OpenAI-compatible" /></label>
            <label>Provider 类型（暂存元数据）<input v-model="poolDraft.providerType" autocomplete="off" placeholder="chat_completion" /></label>
            <label>Provider ID（固定 Runtime 绑定）<input v-model="poolDraft.providerId" readonly autocomplete="off" placeholder="部署侧绑定 ID" /></label>
            <label>Source ID（可选）<input v-model="poolDraft.sourceId" autocomplete="off" placeholder="dududa-haiku-source" /></label>
            <label class="form-grid__wide">Base URL<input v-model="poolDraft.baseUrl" type="url" maxlength="512" autocomplete="off" placeholder="https://provider.example/v1" /></label>
            <label>模型 ID（重载前需校验）<input v-model="poolDraft.model" autocomplete="off" placeholder="gpt-5.6-luna" /></label>
            <label>协议<select v-model="poolDraft.protocol"><option value="openai_chat_completions">OpenAI Chat Completions</option><option value="anthropic_messages">Anthropic Messages</option></select></label>
            <label>推理强度（暂存元数据）<select v-model="poolDraft.reasoningEffort"><option v-for="option in reasoningOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
            <label>超时（ms）<input v-model.number="poolDraft.timeoutMs" type="number" min="1000" max="900000" step="1000" /></label>
            <label>输出预算（暂存 tokens）<input v-model.number="poolDraft.maxOutputTokens" type="number" min="1" max="1000000" step="1" /></label>
            <label>调度模式（暂存元数据）<select v-model="poolDraft.schedulingMode"><option v-for="option in schedulingOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
            <label class="toggle-field"><input v-model="poolDraft.enabled" type="checkbox" /><span><strong>启用此池</strong><small>不影响 TierPolicy，只控制凭据池是否可用。</small></span></label>
            <label class="form-grid__wide">自定义 Header（非认证）<textarea v-model="poolDraft.customHeadersText" rows="3" placeholder="例如 X-Client-Name=dududa\n认证 Header 请改用 SecretRef" /></label>
          </div>
          <p v-if="poolFormError" class="form-error" role="alert">{{ poolFormError }}</p>
          <footer class="modal-card__footer"><button type="button" :disabled="poolSaving" @click="closePoolEditor()">取消</button><button class="primary" type="submit" :disabled="poolSaving"><LoaderCircle v-if="poolSaving" class="spin" :size="14" /><Save v-else :size="14" />保存池配置</button></footer>
        </form>
      </section>
    </div>

    <div v-if="keyEditor && keyDraft" class="modal-backdrop" role="presentation" @click.self="closeKeyEditor()">
      <section ref="keyDialog" class="modal-card key-editor" role="dialog" aria-modal="true" aria-labelledby="key-editor-title" tabindex="-1" @keydown="handleDialogKeydown($event, closeKeyEditor)">
        <header class="modal-card__header">
          <div><small>WRITE-ONLY CREDENTIAL</small><h2 id="key-editor-title">{{ keyDialogTitle }}</h2><p>{{ API_KEY_TIER_LABELS[keyEditor.tier] }}</p></div>
          <button class="icon-button" type="button" title="关闭" aria-label="关闭 Key 编辑" :disabled="keySaving" @click="closeKeyEditor()"><X :size="17" /></button>
        </header>
        <form class="editor-form" @submit.prevent="saveKey">
          <div class="secret-boundary"><ShieldCheck :size="15" /><span>密钥只会随本次明确提交发送。提交后输入立即清空，服务端和 GET 列表只返回遮罩与 SecretRef。</span></div>
          <div class="connection-help" role="note">
            <strong>此 Key 使用的连接（同档共享）</strong>
            <div>Base URL：{{ poolFor(keyEditor.tier).baseUrl || '尚未配置' }}</div>
            <div>模型：{{ poolFor(keyEditor.tier).model || '尚未配置' }}</div>
            <button type="button" :disabled="keySaving" @click="editConnectionFromKey">配置 Base URL / 模型</button>
            <small>DeepSeek Key 填在下方 API Key；SecretRef ID 可留空。切换到连接设置会清空未提交的密钥。</small>
          </div>
          <div class="form-grid form-grid--two">
            <label>显示名称<input v-model="keyDraft.name" autocomplete="off" placeholder="例如主 Key" /></label>
            <label>SecretRef ID（可选）<input v-model="keyDraft.secretRef" maxlength="160" autocomplete="off" placeholder="provider/luna-primary" /></label>
            <label class="form-grid__wide">API Key <input v-model="keyDraft.secret" type="password" autocomplete="new-password" :placeholder="editingKey ? '留空保持现有密钥；填写则轮换' : '仅本次写入，不会再次显示'" /></label>
            <label>优先级<input v-model.number="keyDraft.priority" type="number" min="0" max="1000000" step="1" /></label>
            <label>权重（同优先级排序）<input v-model.number="keyDraft.weight" type="number" min="1" max="1000" step="1" /></label>
            <label class="toggle-field"><input v-model="keyDraft.enabled" type="checkbox" /><span><strong>启用此 Key</strong><small>停用后不会参与池内调度。</small></span></label>
          </div>
          <p v-if="keyFormError" class="form-error" role="alert">{{ keyFormError }}</p>
          <footer class="modal-card__footer"><button type="button" :disabled="keySaving" @click="closeKeyEditor()">取消</button><button class="primary" type="submit" :disabled="keySaving"><LoaderCircle v-if="keySaving" class="spin" :size="14" /><Save v-else :size="14" />{{ editingKey ? '保存元数据' : '写入 Key' }}</button></footer>
        </form>
      </section>
    </div>
  </main>
</template>

<style scoped>
.runtime-apply { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-top: 16px; padding: 12px; border: 1px solid var(--border); border-radius: 8px; color: var(--text); background: var(--surface); }
.runtime-apply strong { font-size: 12px; }
.runtime-apply p { margin: 5px 0 0; color: var(--text-secondary); font-size: 11px; }
.runtime-apply button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 0; border-radius: 6px; padding: 10px 12px; color: white; background: var(--brand-strong); font: inherit; font-size: 12px; cursor: pointer; }
.runtime-apply button:disabled { opacity: .55; cursor: wait; }
.runtime-apply button:focus-visible { outline: 2px solid var(--brand-strong); outline-offset: 3px; }
.connection-help { padding: 12px; border: 1px solid var(--border); border-radius: 6px; color: var(--text-secondary); font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.connection-help small { display: block; color: var(--text-muted); }
.api-key-pools-view { min-height: 0; overflow-y: auto; background: var(--app-background); padding: 24px clamp(16px, 3vw, 38px) 40px; }
.view-header { display: flex; align-items: center; justify-content: space-between; gap: 18px; border-bottom: 1px solid var(--border); padding-bottom: 17px; }
.view-header small { color: var(--brand-strong); font-size: 9px; font-weight: 800; }
.view-header h1 { margin: 4px 0 2px; color: var(--text); font-size: 22px; }
.view-header p { margin: 0; color: var(--text-muted); font-size: 10px; }
.security-note, .inline-error, .inline-notice { display: flex; align-items: flex-start; gap: 8px; margin: 16px 0 0; border-left: 3px solid var(--brand); color: var(--text-secondary); background: var(--brand-soft); padding: 9px 11px; font-size: 10px; line-height: 1.5; }
.security-note svg { flex: 0 0 auto; color: var(--brand-strong); }
.security-note strong { color: var(--brand-strong); }
.inline-error { border-left-color: var(--danger); color: var(--danger); background: var(--danger-soft); }
.inline-notice { border-left-color: var(--success); color: var(--success-strong); background: var(--success-soft); }
.pool-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: 12px; margin-top: 16px; }
.pool-card { display: flex; min-width: 0; flex-direction: column; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); box-shadow: 0 5px 16px rgb(25 43 47 / 4%); }
.pool-card--haiku { --tier-color: var(--brand); --tier-soft: var(--brand-soft); }
.pool-card--sonnet { --tier-color: #8b6db1; --tier-soft: #f3eef9; }
.pool-card--opus { --tier-color: var(--accent); --tier-soft: var(--accent-soft); }
:root[data-theme='dark'] .pool-card--sonnet { --tier-soft: #30273a; }
.pool-card__header { display: flex; min-height: 78px; align-items: center; gap: 10px; border-bottom: 1px solid var(--border-soft); padding: 13px; }
.tier-mark { display: grid; width: 34px; height: 34px; flex: 0 0 auto; place-items: center; border-radius: 8px; color: var(--tier-color); background: var(--tier-soft); }
.pool-card__title { min-width: 0; flex: 1; }
.pool-card__title small { color: var(--tier-color); font-size: 8px; font-weight: 800; letter-spacing: .06em; }
.pool-card__title h2 { overflow: hidden; margin: 3px 0 2px; color: var(--text); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.pool-card__title p { margin: 0; overflow: hidden; color: var(--text-muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.pool-enabled { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 4px; border-radius: 999px; color: var(--success-strong); background: var(--success-soft); padding: 5px 7px; font-size: 8px; font-weight: 700; }
.pool-enabled--off { color: var(--text-muted); background: var(--surface-muted); }
.pool-facts { display: grid; margin: 0; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; background: var(--border-soft); }
.pool-facts div { min-width: 0; background: var(--surface); padding: 8px 10px; }
.pool-facts dt, .key-row small { color: var(--text-muted); font-size: 8px; }
.pool-facts dd { overflow: hidden; margin: 4px 0 0; color: var(--text-secondary); font-size: 9px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.runtime-sync { display: flex; align-items: center; gap: 5px; margin: 9px 10px 0; border-radius: 4px; color: var(--text-secondary); background: var(--surface-muted); padding: 6px 7px; font-size: 9px; }
.runtime-sync--synced { color: var(--success-strong); background: var(--success-soft); }
.runtime-sync--error { color: var(--danger); background: var(--danger-soft); }
.pool-actions { display: flex; gap: 6px; padding: 10px 10px 0; }
.pool-actions button, .add-key, .key-row__actions button, .modal-card__footer button { display: inline-flex; height: 31px; cursor: pointer; align-items: center; justify-content: center; gap: 5px; border: 1px solid var(--border); border-radius: 5px; color: var(--text-secondary); background: var(--surface); padding: 0 9px; font-size: 9px; }
.pool-actions button { flex: 1; }
.pool-actions button:hover, .add-key:hover, .key-row__actions button:hover, .modal-card__footer button:hover { border-color: var(--border-strong); background: var(--surface-hover); }
.pool-actions button:disabled, .add-key:disabled, .key-row__actions button:disabled, .modal-card__footer button:disabled { cursor: wait; opacity: .55; }
.test-result { display: flex; align-items: flex-start; gap: 5px; margin: 8px 10px 0; border-radius: 4px; padding: 6px 7px; font-size: 9px; line-height: 1.4; }
.test-result--ok { color: var(--success-strong); background: var(--success-soft); }
.test-result--error { color: var(--danger); background: var(--danger-soft); }
.test-result span { min-width: 0; }
.test-result small { color: inherit; opacity: .75; }
.keys-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 11px; border-top: 1px solid var(--border-soft); padding: 11px 10px 8px; }
.keys-heading h3 { margin: 0 0 2px; color: var(--text); font-size: 10px; }
.keys-heading span { color: var(--text-muted); font-size: 8px; }
.add-key { flex: 0 0 auto; border-style: dashed; border-color: var(--brand-border); color: var(--brand-strong); }
.keys-empty { display: grid; min-height: 125px; place-content: center; place-items: center; gap: 5px; border-top: 1px dashed var(--border); color: var(--text-muted); padding: 12px; text-align: center; }
.keys-empty span { color: var(--text-secondary); font-size: 10px; }
.keys-empty small { font-size: 8px; }
.key-list { display: grid; gap: 6px; margin: 0; padding: 0 10px 11px; list-style: none; }
.key-row { display: grid; grid-template-columns: minmax(125px, 1.25fr) minmax(100px, 1fr) minmax(80px, .7fr) auto; align-items: center; gap: 8px; border: 1px solid var(--border); border-radius: 5px; background: var(--surface-subtle); padding: 8px; }
.key-row__main, .key-row__ref, .key-row__priority, .key-row__health { display: flex; min-width: 0; align-items: center; gap: 6px; }
.key-row__main { gap: 7px; }
.key-icon { display: grid; width: 25px; height: 25px; flex: 0 0 auto; place-items: center; border-radius: 6px; color: var(--tier-color); background: var(--tier-soft); }
.key-row__main > div, .key-row__ref, .key-row__priority, .key-row__health { min-width: 0; }
.key-row__main > div { display: grid; gap: 3px; }
.key-row strong { overflow: hidden; color: var(--text); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.key-row code { overflow: hidden; color: var(--text-secondary); font-family: var(--font-mono); font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.key-row__ref, .key-row__priority, .key-row__health { display: grid; align-items: start; gap: 3px; }
.key-row__priority span { color: var(--text-secondary); font-size: 9px; }
.key-row__health { justify-items: start; }
.status-chip { display: inline-flex; border-radius: 999px; padding: 4px 6px; font-size: 8px; font-weight: 700; line-height: 1; }
.status--ok { color: var(--success-strong); background: var(--success-soft); }
.status--warning { color: var(--warning-strong); background: var(--warning-soft); }
.status--danger { color: var(--danger); background: var(--danger-soft); }
.status--disabled { color: var(--text-muted); background: var(--surface-muted); }
.key-row__health small { white-space: nowrap; }
.key-row__actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px; }
.key-row__actions button { height: 27px; padding: 0 7px; font-size: 8px; white-space: nowrap; }
.key-row__actions button.danger { border-color: var(--danger); color: var(--danger); }
.page-footnote { display: flex; align-items: flex-start; gap: 6px; margin: 15px 0 0; color: var(--text-muted); font-size: 9px; line-height: 1.5; }
.page-footnote svg { flex: 0 0 auto; margin-top: 1px; }
.modal-backdrop { position: fixed; z-index: 80; inset: 0; display: grid; overflow-y: auto; place-items: center; background: rgb(18 30 32 / 45%); padding: 20px; }
.modal-card { width: min(680px, 100%); max-height: min(800px, calc(100dvh - 40px)); overflow-y: auto; border: 1px solid var(--border-strong); border-radius: 9px; background: var(--surface); box-shadow: var(--floating-shadow); }
.modal-card__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--border); padding: 15px 17px; }
.modal-card__header small { color: var(--brand-strong); font-size: 8px; font-weight: 800; }
.modal-card__header h2 { margin: 4px 0 2px; color: var(--text); font-size: 16px; }
.modal-card__header p { margin: 0; color: var(--text-muted); font-size: 9px; }
.editor-form { padding: 15px 17px 17px; }
.form-grid { display: grid; gap: 10px; }
.form-grid--two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.form-grid__wide { grid-column: 1 / -1; }
.editor-form label { display: grid; gap: 5px; color: var(--text-secondary); font-size: 9px; }
.editor-form input, .editor-form select, .editor-form textarea { width: 100%; min-width: 0; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--surface); padding: 0 9px; font: inherit; font-size: 10px; }
.editor-form input, .editor-form select { height: 34px; }
.editor-form textarea { min-height: 72px; resize: vertical; padding-top: 8px; padding-bottom: 8px; }
.editor-form input::placeholder, .editor-form textarea::placeholder { color: var(--text-muted); }
.toggle-field { display: flex !important; min-height: 34px; align-items: center; grid-template-columns: auto 1fr; gap: 8px !important; }
.toggle-field > input { width: 16px; height: 16px; accent-color: var(--brand); }
.toggle-field span { display: grid; gap: 3px; }
.toggle-field strong { color: var(--text); font-size: 10px; }
.toggle-field small { color: var(--text-muted); font-size: 8px; }
.secret-boundary { display: flex; align-items: flex-start; gap: 7px; margin-bottom: 12px; border-left: 3px solid var(--warning); color: var(--text-secondary); background: var(--warning-soft); padding: 8px 10px; font-size: 9px; line-height: 1.45; }
.secret-boundary svg { flex: 0 0 auto; color: var(--warning-strong); }
.form-error { margin: 11px 0 0; color: var(--danger); font-size: 9px; }
.modal-card__footer { display: flex; justify-content: flex-end; gap: 7px; margin-top: 15px; border-top: 1px solid var(--border-soft); padding-top: 12px; }
.modal-card__footer .primary { border-color: var(--brand); color: #fff; background: var(--brand); }
.modal-card__footer .primary:hover { border-color: var(--brand-strong); background: var(--brand-strong); }
.spin { animation: spin 850ms linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1180px) {
  .pool-grid { grid-template-columns: 1fr; }
  .pool-card { min-width: 0; }
  .key-row { grid-template-columns: minmax(150px, 1.2fr) minmax(120px, 1fr) minmax(90px, .7fr) auto; }
}
@media (max-width: 720px) {
  .api-key-pools-view { padding: 18px 13px 28px; }
  .view-header { align-items: flex-start; }
  .pool-card__header { min-height: 70px; }
  .key-row { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
  .key-row__actions { grid-column: 1 / -1; justify-content: flex-start; }
  .key-row__health { justify-items: end; }
  .form-grid--two { grid-template-columns: minmax(0, 1fr); }
  .form-grid__wide { grid-column: auto; }
  .modal-backdrop { place-items: end center; padding: 8px; }
  .modal-card { max-height: calc(100dvh - 16px); border-radius: 9px 9px 0 0; }
}
</style>
