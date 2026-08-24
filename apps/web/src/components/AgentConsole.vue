<script setup lang="ts">
import {
  Activity,
  ArrowLeft,
  Bot,
  Check,
  ChevronDown,
  CircleStop,
  Clock3,
  Database,
  ExternalLink,
  Gauge,
  Hash,
  MessageSquareText,
  Plus,
  Play,
  RefreshCw,
  Save,
  SendHorizontal,
  Settings2,
  ShieldCheck,
  Sparkles,
  Wrench,
  Unplug,
  X,
} from '@lucide/vue'
import { computed, nextTick, ref, watch } from 'vue'

import { internalTestAdapter } from '../services/internal-test'
import type {
  InternalTestAdaptiveSetting,
  InternalTestAgentCatalog,
  InternalTestAgentPolicy,
  InternalTestAgentStatus,
  InternalTestAnswerProfile,
  InternalTestCatalogPlugin,
  InternalTestContextLength,
  InternalTestEffectiveSelection,
  InternalTestGroupChatStyle,
  InternalTestPluginMode,
  InternalTestReasoningLevel,
  InternalTestReplyIntensity,
  InternalTestSelectionMode,
  InternalTestTier,
  McpConsoleCatalog,
  McpConsoleInvocation,
} from '../types/internal-test'
import type {
  Account,
  AgentMessage,
  AgentPart,
  AgentRun,
  AgentSession,
  AgentTab,
  Conversation,
  PermissionPart,
  ReplyDraftPart,
} from '../types/workspace'
import AgentPartView from './AgentPartView.vue'
import AppAvatar from './AppAvatar.vue'

type AdaptiveAxis =
  | 'modelTier'
  | 'reasoning'
  | 'answerProfile'
  | 'replyIntensity'
  | 'contextLength'
  | 'groupChatStyle'

type AgentRunWithSelection = AgentRun & {
  modelTier?: InternalTestTier
  reasoning?: InternalTestReasoningLevel
  answerProfile?: InternalTestAnswerProfile
  plugins?: string[]
  reasonCodes?: string[]
  effectiveSelection?: InternalTestEffectiveSelection
}

const props = defineProps<{
  conversation?: Conversation
  account?: Account
  accounts: Account[]
  sessions: AgentSession[]
  selectedSession?: AgentSession
  messages: AgentMessage[]
  run?: AgentRunWithSelection
  catalog?: InternalTestAgentCatalog
  policy?: InternalTestAgentPolicy
  policyLoading: boolean
  policySaving: boolean
  policyError: string
  contextMessages: number
  answerProfileHint?: InternalTestAnswerProfile
  tab: AgentTab
  available: boolean
  runtimeLoading: boolean
  runtimeError: string
  runtimeWarning: string
  runtimeControls?: InternalTestAgentStatus['runtimeControls']
}>()

const emit = defineEmits<{
  setTab: [tab: AgentTab]
  selectSession: [id: string]
  newSession: []
  sendPrompt: [content: string]
  setAnswerProfile: [profile: InternalTestAnswerProfile | undefined]
  updatePolicy: [policy: InternalTestAgentPolicy]
  approveDraft: [part: ReplyDraftPart]
  discardDraft: [part: ReplyDraftPart]
  updateDraft: [part: ReplyDraftPart, content: string]
  respondPermission: [part: PermissionPart, allow: boolean]
  saveSettings: []
  back: []
  collapse: []
  reconnect: []
  notify: [message: string]
}>()

const prompt = ref('')
const sessionMenuOpen = ref(false)
const stream = ref<HTMLElement>()
const runtimeLabel = computed(() => props.available ? '内测已连接' : props.runtimeLoading ? '正在连接' : '未连接')
const runtimeDetail = computed(() => props.runtimeError || props.runtimeWarning || 'QQ 消息与历史仍由 NapCat 实时提供')
const policyEditable = computed(() => Boolean(props.policy) && !props.policyLoading && !props.policySaving)
const mcpCatalog = ref<McpConsoleCatalog>()
const mcpCatalogLoading = ref(false)
const mcpCatalogError = ref('')
const selectedMcpCapabilityId = ref('')
const mcpArguments = ref<Record<string, unknown>>({})
const mcpJsonArguments = ref<Record<string, string>>({})
const mcpInvoking = ref(false)
const mcpInvocationError = ref('')
const mcpInvocation = ref<McpConsoleInvocation>()

const selectionModeLabels: Record<InternalTestSelectionMode, string> = {
  adaptive: '自适应',
  preferred: '优先',
  locked: '锁定',
}

const pluginModeLabels: Record<InternalTestPluginMode, string> = {
  off: '关闭',
  auto: '自动',
  on: '偏好启用',
  locked: '锁定可用',
}

const pluginExecutionLabels: Record<InternalTestCatalogPlugin['executionKind'], string> = {
  agent_capability: 'Agent 能力',
  command_auto_reply: '命令自动回复',
  passive_behavior: '被动行为',
}

const pluginRoleLabels: Record<NonNullable<InternalTestCatalogPlugin['requiredRole']>, string> = {
  super_admin: 'WebUI 超级管理员可配置',
  admin: 'WebUI 管理员可配置',
}

const pluginRuntimeLabels: Record<InternalTestCatalogPlugin['runtimeTarget'], string> = {
  web_agent: 'Web Agent',
  astrbot: 'AstrBot',
}

const pluginReadinessLabels: Record<InternalTestCatalogPlugin['runtimeReadiness'], string> = {
  configured: '已装配 · 待 Runtime 接管',
  unavailable: '执行器未接通',
}

const tierLabels: Record<InternalTestTier, string> = {
  haiku: '轻量 / Haiku',
  sonnet: '中等 / Sonnet',
  opus: '专业 / Opus',
}

const reasoningLabels: Record<InternalTestReasoningLevel, string> = {
  low: '低',
  medium: '中',
  high: '高',
}

const answerProfileLabels: Record<InternalTestAnswerProfile, string> = {
  short: '短回答',
  medium: '中回答',
  long: '长回答',
}

const replyIntensityLabels: Record<InternalTestReplyIntensity, string> = {
  quiet: '克制',
  normal: '正常',
  active: '积极',
}

const contextLengthLabels: Record<InternalTestContextLength, string> = {
  compact: '紧凑',
  standard: '标准',
  extended: '扩展',
}

const groupChatStyleLabels: Record<InternalTestGroupChatStyle, string> = {
  restrained: '克制',
  natural: '自然',
  lively: '活跃',
  technical: '技术型',
}

const tabs = [
  { id: 'conversation', label: '对话', icon: MessageSquareText },
  { id: 'run', label: '运行', icon: Activity },
  { id: 'settings', label: '配置', icon: Settings2 },
] as const

const answerProfiles: Array<{ id: InternalTestAnswerProfile | undefined; label: string }> = [
  { id: undefined, label: '自动' },
  { id: 'short', label: '短' },
  { id: 'medium', label: '中' },
  { id: 'long', label: '长' },
]

const tierOptions = computed(() => {
  const grouped = new Map<InternalTestTier, { id: InternalTestTier; label: string; available: boolean; reason?: string }>()
  for (const model of props.catalog?.models ?? []) {
    const current = grouped.get(model.tier)
    const modelLabel = model.displayName || model.id
    if (!current) {
      grouped.set(model.tier, {
        id: model.tier,
        label: `${tierLabels[model.tier]} · ${modelLabel}`,
        available: model.available,
        reason: model.unavailableReason,
      })
      continue
    }
    current.label += ` / ${modelLabel}`
    current.available ||= model.available
    if (model.available) current.reason = undefined
  }
  return [...grouped.values()]
})

const modelOptions = computed(() => props.catalog?.models ?? [])
const selectedTopModelId = computed(() => {
  const preferredTier = props.policy?.modelTier.preferred
  return modelOptions.value.find(model => model.tier === preferredTier && model.available)?.id
    ?? modelOptions.value.find(model => model.tier === preferredTier)?.id
    ?? ''
})

const reasoningOptions = computed(() => (props.catalog?.reasoningLevels ?? []).map(id => ({
  id,
  label: reasoningLabels[id],
  available: true,
  reason: undefined as string | undefined,
})))

const profileOptions = computed(() => (props.catalog?.answerProfiles ?? []).map(id => ({
  id,
  label: answerProfileLabels[id],
  available: true,
  reason: undefined as string | undefined,
})))

const replyIntensityOptions = computed(() => (props.catalog?.replyIntensities ?? []).map(id => ({
  id,
  label: replyIntensityLabels[id],
  available: true,
  reason: undefined as string | undefined,
})))

const contextLengthOptions = computed(() => (props.catalog?.contextLengths ?? []).map(item => ({
  id: item.id,
  label: `${contextLengthLabels[item.id]} · ${item.messageLimit} 条 / ${item.characterLimit.toLocaleString('zh-CN')} 字符`,
  available: true,
  reason: undefined as string | undefined,
})))

const groupChatStyleOptions = computed(() => (props.catalog?.groupChatStyles ?? []).map(id => ({
  id,
  label: groupChatStyleLabels[id],
  available: true,
  reason: undefined as string | undefined,
})))

const selectionModes = computed<InternalTestSelectionMode[]>(() => props.catalog?.selectionModes ?? ['adaptive', 'preferred', 'locked'])
const pluginModes = computed<InternalTestPluginMode[]>(() => props.catalog?.pluginModes ?? ['off', 'auto', 'on', 'locked'])
const adaptiveAxes = computed(() => [
  {
    key: 'modelTier' as const,
    title: '模型档位',
    detail: '先按合法档位选路由，再由 Runtime 选择具体模型',
    setting: props.policy?.modelTier,
    options: tierOptions.value,
  },
  {
    key: 'reasoning' as const,
    title: '推理强度',
    detail: '与模型档位、回答长度独立判断',
    setting: props.policy?.reasoning,
    options: reasoningOptions.value,
  },
  {
    key: 'answerProfile' as const,
    title: '回答长度',
    detail: '短、中、长只是表达计划，不绑定模型',
    setting: props.policy?.answerProfile,
    options: profileOptions.value,
  },
  {
    key: 'replyIntensity' as const,
    title: '回复强度',
    detail: props.catalog?.replyIntensityNotice ?? '候选决策初值；当前真实发送链未开启。',
    setting: props.policy?.replyIntensity,
    options: replyIntensityOptions.value,
  },
  {
    key: 'contextLength' as const,
    title: '上下文长度（运行预算）',
    detail: '这是 Dududa 本轮读取历史的运行预算，不是模型厂商声明的最大 Context Window',
    setting: props.policy?.contextLength,
    options: contextLengthOptions.value,
  },
  {
    key: 'groupChatStyle' as const,
    title: '群聊风格',
    detail: '作为本轮表达初值自然融入回答，不机械复述风格标签',
    setting: props.policy?.groupChatStyle,
    options: groupChatStyleOptions.value,
  },
])

const selectedMcpCapability = computed(() =>
  mcpCatalog.value?.capabilities.find(item => item.id === selectedMcpCapabilityId.value),
)
const mcpInputProperties = computed<Array<[string, Record<string, unknown>]>>(() => {
  const properties = selectedMcpCapability.value?.inputSchema.properties
  if (!properties || typeof properties !== 'object' || Array.isArray(properties)) return []
  return Object.entries(properties as Record<string, unknown>)
    .filter((item): item is [string, Record<string, unknown>] => Boolean(item[1]) && typeof item[1] === 'object' && !Array.isArray(item[1]))
})
const mcpRequired = computed(() => new Set(
  Array.isArray(selectedMcpCapability.value?.inputSchema.required)
    ? selectedMcpCapability.value?.inputSchema.required.filter((item): item is string => typeof item === 'string')
    : [],
))

const runTier = computed(() => props.run?.effectiveSelection?.modelTier ?? props.run?.modelTier)
const runReasoning = computed(() => props.run?.effectiveSelection?.reasoning ?? props.run?.reasoning)
const runAnswerProfile = computed(() => props.run?.effectiveSelection?.answerProfile ?? props.run?.answerProfile)
const runReplyIntensity = computed(() => props.run?.effectiveSelection?.replyIntensity)
const runContextLength = computed(() => props.run?.effectiveSelection?.contextLength)
const runGroupChatStyle = computed(() => props.run?.effectiveSelection?.groupChatStyle)
const runContextUsage = computed(() => props.run?.effectiveSelection?.contextUsage)
const runPlugins = computed(() => {
  if (props.run?.plugins?.length) return props.run.plugins
  const plugins = props.run?.effectiveSelection?.plugins
  if (!plugins) return []
  return Object.entries(plugins).filter(([, value]) => value.selectedForRun).map(([id]) => id)
})
const runReasonCodes = computed(() => props.run?.reasonCodes ?? [])

function emitPolicy(patch: Partial<InternalTestAgentPolicy>): void {
  if (!props.policy) return
  emit('updatePolicy', {
    ...props.policy,
    ...patch,
    plugins: patch.plugins ?? { ...props.policy.plugins },
  })
}

function updateAdaptiveMode(axis: AdaptiveAxis, mode: InternalTestSelectionMode): void {
  const setting = props.policy?.[axis]
  if (!setting) return
  emitPolicy({ [axis]: { ...setting, allowed: [...setting.allowed], mode } } as Partial<InternalTestAgentPolicy>)
}

function updateAdaptivePreferred(axis: AdaptiveAxis, preferred: string): void {
  const setting = props.policy?.[axis] as InternalTestAdaptiveSetting<string> | undefined
  if (!setting) return
  const allowed = setting.allowed.includes(preferred) ? [...setting.allowed] : [...setting.allowed, preferred]
  emitPolicy({ [axis]: { ...setting, preferred, allowed } } as Partial<InternalTestAgentPolicy>)
}

function toggleAdaptiveAllowed(axis: AdaptiveAxis, value: string): void {
  const setting = props.policy?.[axis] as InternalTestAdaptiveSetting<string> | undefined
  if (!setting) return
  const selected = setting.allowed.includes(value)
  if (selected && setting.allowed.length === 1) return
  const allowed = selected ? setting.allowed.filter(item => item !== value) : [...setting.allowed, value]
  const preferred = allowed.includes(setting.preferred) ? setting.preferred : allowed[0]
  emitPolicy({ [axis]: { ...setting, preferred, allowed } } as Partial<InternalTestAgentPolicy>)
}

function isAdaptiveAllowed(setting: { allowed: readonly string[] } | undefined, value: string): boolean {
  return setting?.allowed.includes(value) ?? false
}

function selectTopModel(modelId: string): void {
  const model = modelOptions.value.find(item => item.id === modelId)
  if (model) updateAdaptivePreferred('modelTier', model.tier)
}

function updatePluginMode(pluginId: string, mode: InternalTestPluginMode): void {
  if (!props.policy) return
  emitPolicy({ plugins: { ...props.policy.plugins, [pluginId]: mode } })
}

function pluginModeOptions(plugin: InternalTestCatalogPlugin): InternalTestPluginMode[] {
  return plugin.available ? pluginModes.value : ['off']
}

function schemaKind(schema: Record<string, unknown>): string {
  if (typeof schema.type === 'string') return schema.type
  if (Array.isArray(schema.type)) return schema.type.find(item => item !== 'null') as string ?? 'string'
  if (Array.isArray(schema.anyOf)) {
    for (const candidate of schema.anyOf) {
      if (candidate && typeof candidate === 'object' && !Array.isArray(candidate)) {
        const kind = schemaKind(candidate as Record<string, unknown>)
        if (kind !== 'null') return kind
      }
    }
  }
  return 'string'
}

function schemaLabel(name: string, schema: Record<string, unknown>): string {
  return typeof schema.title === 'string' ? schema.title : name
}

function selectMcpCapability(capabilityId: string): void {
  selectedMcpCapabilityId.value = capabilityId
  mcpArguments.value = {}
  mcpJsonArguments.value = {}
  mcpInvocation.value = undefined
  mcpInvocationError.value = ''
  const capability = mcpCatalog.value?.capabilities.find(item => item.id === capabilityId)
  const properties = capability?.inputSchema.properties
  if (!properties || typeof properties !== 'object' || Array.isArray(properties)) return
  for (const [name, rawSchema] of Object.entries(properties)) {
    if (!rawSchema || typeof rawSchema !== 'object' || Array.isArray(rawSchema)) continue
    const schema = rawSchema as Record<string, unknown>
    const initial = schema.const ?? schema.default
    if (initial === undefined) continue
    if (['array', 'object'].includes(schemaKind(schema))) {
      mcpJsonArguments.value[name] = JSON.stringify(initial, null, 2)
    } else {
      mcpArguments.value[name] = initial
    }
  }
}

function updateMcpScalar(name: string, schema: Record<string, unknown>, event: Event): void {
  const target = event.target as HTMLInputElement | HTMLSelectElement
  const kind = schemaKind(schema)
  if (kind === 'boolean') {
    mcpArguments.value[name] = (target as HTMLInputElement).checked
    return
  }
  if (!target.value && !mcpRequired.value.has(name)) {
    delete mcpArguments.value[name]
    return
  }
  mcpArguments.value[name] = ['integer', 'number'].includes(kind)
    ? Number(target.value)
    : target.value
}

async function loadMcpCatalog(force = false): Promise<void> {
  if ((mcpCatalog.value && !force) || mcpCatalogLoading.value) return
  mcpCatalogLoading.value = true
  mcpCatalogError.value = ''
  try {
    mcpCatalog.value = await internalTestAdapter.mcpCatalog()
    const selected = mcpCatalog.value.capabilities.find(item => item.id === selectedMcpCapabilityId.value)
      ?? mcpCatalog.value.capabilities.find(item => item.available)
      ?? mcpCatalog.value.capabilities[0]
    if (selected) selectMcpCapability(selected.id)
  } catch (error) {
    mcpCatalogError.value = error instanceof Error ? error.message : 'MCP Catalog 加载失败'
  } finally {
    mcpCatalogLoading.value = false
  }
}

async function invokeMcp(): Promise<void> {
  const capability = selectedMcpCapability.value
  if (!capability || !capability.available || mcpInvoking.value) return
  mcpInvoking.value = true
  mcpInvocation.value = undefined
  mcpInvocationError.value = ''
  try {
    const argumentsValue = { ...mcpArguments.value }
    for (const [name, value] of Object.entries(mcpJsonArguments.value)) {
      if (!value.trim()) continue
      argumentsValue[name] = JSON.parse(value) as unknown
    }
    mcpInvocation.value = await internalTestAdapter.invokeMcp(capability.id, argumentsValue)
  } catch (error) {
    mcpInvocationError.value = error instanceof Error ? error.message : 'MCP 调用失败'
  } finally {
    mcpInvoking.value = false
  }
}

function invocationText(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

function send(): void {
  const value = prompt.value.trim()
  if (!value) return
  emit('sendPrompt', value)
  prompt.value = ''
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  send()
}

function chooseSession(id: string): void {
  emit('selectSession', id)
  sessionMenuOpen.value = false
}

function selectQuickPrompt(value: string): void {
  prompt.value = value
  void nextTick(() => document.querySelector<HTMLTextAreaElement>('.agent-composer textarea')?.focus())
}

function partKey(message: AgentMessage, part: AgentPart, index: number): string {
  if ('id' in part) return `${message.id}-${part.id}`
  return `${message.id}-${part.type}-${index}`
}

watch(
  () => props.messages.length,
  () => {
    void nextTick(() => {
      if (stream.value) stream.value.scrollTop = stream.value.scrollHeight
    })
  },
)

watch(
  () => props.tab,
  (tab) => {
    if (tab === 'settings') void loadMcpCatalog()
  },
  { immediate: true },
)
</script>

<template>
  <aside class="agent-console" aria-label="Agent Console">
    <header class="agent-header">
      <button class="icon-button mobile-back" type="button" title="返回聊天" aria-label="返回聊天" @click="emit('back')">
        <ArrowLeft :size="20" />
      </button>
      <span class="agent-logo"><Sparkles :size="17" /></span>
      <div class="agent-heading">
        <div><strong>Dududa Agent</strong><span class="runtime-dot" :class="{ online: available }" /> <small>{{ runtimeLabel }}</small></div>
        <p>{{ available ? `内测 Runtime · 不会发送 · ${conversation?.name ?? '未选择会话'}` : (conversation?.name ?? '未选择会话') }}</p>
      </div>
      <button class="icon-button desktop-collapse" type="button" title="收起 Agent Console" aria-label="收起 Agent Console" @click="emit('collapse')">
        <X :size="17" />
      </button>
    </header>

    <div class="agent-context-bar">
      <div class="session-picker">
        <button type="button" :disabled="!available" :aria-expanded="sessionMenuOpen" @click="sessionMenuOpen = !sessionMenuOpen">
          <span class="session-status" :class="`session-status--${selectedSession?.status ?? 'idle'}`" />
          <span>{{ selectedSession?.title ?? '新对话' }}</span>
          <ChevronDown :size="14" />
        </button>
        <div v-if="sessionMenuOpen" class="session-menu">
          <button
            v-for="session in sessions"
            :key="session.id"
            type="button"
            :class="{ active: session.id === selectedSession?.id }"
            @click="chooseSession(session.id)"
          >
            <span><strong>{{ session.title }}</strong><small>{{ session.model }} · {{ session.updatedAt }}</small></span>
            <Check v-if="session.id === selectedSession?.id" :size="14" />
          </button>
          <button class="new-session-row" type="button" @click="emit('newSession'); sessionMenuOpen = false">
            <Plus :size="14" />新建对话
          </button>
        </div>
      </div>
      <label class="model-picker">
        <span>MODEL</span>
        <select
          :value="selectedTopModelId"
          aria-label="选择首选模型"
          :disabled="!policyEditable || !modelOptions.length"
          @change="selectTopModel(($event.target as HTMLSelectElement).value)"
        >
          <option v-if="!modelOptions.length" value="">暂无模型</option>
          <option
            v-for="model in modelOptions"
            :key="model.id"
            :value="model.id"
            :disabled="!model.available"
          >
            {{ model.displayName }} · {{ tierLabels[model.tier] }}{{ model.available ? '' : '（不可用）' }}
          </option>
        </select>
      </label>
      <button class="icon-button" type="button" title="新建 Agent 对话" aria-label="新建 Agent 对话" :disabled="!available" @click="emit('newSession')">
        <Plus :size="17" />
      </button>
    </div>

    <nav class="agent-tabs" aria-label="Agent Console 视图">
      <button v-for="item in tabs" :key="item.id" :class="{ active: tab === item.id }" type="button" :disabled="!available && item.id === 'run'" @click="emit('setTab', item.id)">
        <component :is="item.icon" :size="14" />
        <span>{{ item.label }}</span>
        <b v-if="item.id === 'run' && run?.status === 'waiting_approval'">1</b>
      </button>
    </nav>

    <template v-if="tab === 'conversation'">
      <section ref="stream" class="agent-stream" aria-label="Agent 对话消息">
        <div class="scope-line">
          <span><Hash :size="12" />{{ conversation?.name }}</span>
          <span>最多提交 {{ contextMessages }} 条历史 · Runtime 按本轮上下文长度截取</span>
        </div>

        <div v-if="available" class="runtime-mode-note">
          <ShieldCheck :size="13" />
          <span><strong>内测 Runtime</strong>只生成候选，不会发送 QQ 消息、写入 Memory 或调用工具</span>
        </div>

        <div v-if="!available" class="runtime-unavailable">
          <span><Unplug :size="18" /></span>
          <div><strong>{{ runtimeLoading ? '正在连接 Agent Runtime' : 'Agent Runtime 未连接' }}</strong><small>{{ runtimeDetail }}</small></div>
          <button type="button" :disabled="runtimeLoading" @click="emit('reconnect')">
            <RefreshCw :size="13" :class="{ spinning: runtimeLoading }" />
            {{ runtimeLoading ? '连接中' : '重新连接' }}
          </button>
        </div>

        <article v-for="message in messages" :key="message.id" class="agent-message" :class="`agent-message--${message.role}`">
          <header>
            <span v-if="message.role === 'assistant'" class="assistant-avatar"><Sparkles :size="13" /></span>
            <AppAvatar
              v-else-if="message.role === 'operator' && account"
              :src="account.avatar"
              name="你"
              size="xs"
            />
            <span v-else class="system-avatar"><Bot :size="12" /></span>
            <strong>{{ message.author }}</strong>
            <time>{{ message.timestamp }}</time>
          </header>
          <div class="agent-parts">
            <AgentPartView
              v-for="(part, index) in message.parts"
              :key="partKey(message, part, index)"
              :part="part"
              :accounts="accounts"
              @approve-draft="emit('approveDraft', $event)"
              @discard-draft="emit('discardDraft', $event)"
              @update-draft="(part, content) => emit('updateDraft', part, content)"
              @respond-permission="(part, allow) => emit('respondPermission', part, allow)"
            />
          </div>
        </article>

        <div v-if="selectedSession?.status === 'running'" class="agent-thinking">
          <span class="assistant-avatar"><Sparkles :size="13" /></span>
          <span><i /><i /><i /></span>
          <small>Agent 正在处理</small>
        </div>

        <div v-if="!messages.length && selectedSession?.status !== 'running'" class="agent-empty">
          <Sparkles :size="27" />
          <strong>{{ selectedSession?.title ?? '新对话' }}</strong>
          <div class="quick-prompts">
            <button type="button" :disabled="!available" @click="selectQuickPrompt('总结这个群今天的讨论')">生成今日摘要</button>
            <button type="button" :disabled="!available" @click="selectQuickPrompt('检查 Bot 上一条回复是否准确')">检查上一条回复</button>
          </div>
        </div>
      </section>

      <footer class="agent-composer">
        <div class="context-chip"><Hash :size="12" />{{ conversation?.name }}<span>最多提交 {{ contextMessages }} 条历史 · Runtime 按本轮预算截取</span></div>
        <textarea
          v-model="prompt"
          rows="3"
          placeholder="给 Agent 分配任务"
          aria-label="Agent 指令输入"
          :disabled="!available"
          @keydown="handleKeydown"
        />
        <div class="agent-composer-footer">
          <div>
            <div class="answer-profile-picker" role="group" aria-label="回答长度">
              <button
                v-for="profile in answerProfiles"
                :key="profile.id ?? 'auto'"
                type="button"
                :class="{ active: answerProfileHint === profile.id }"
                :title="profile.id ? `${profile.label}回答（仅本轮提示）` : '由 Agent 自动判断本轮回答长度'"
                :aria-pressed="answerProfileHint === profile.id"
                :disabled="!available || selectedSession?.status === 'running'"
                @click="emit('setAnswerProfile', profile.id)"
              >
                {{ profile.label }}
              </button>
            </div>
          </div>
          <button
            v-if="selectedSession?.status === 'running'"
            class="stop-button"
            type="button"
            title="中止运行"
            aria-label="中止运行"
            @click="emit('notify', '已请求中止当前运行')"
          >
            <CircleStop :size="17" />
          </button>
          <button v-else class="prompt-send" type="button" title="发送给 Agent" aria-label="发送给 Agent" :disabled="!available || !prompt.trim()" @click="send">
            <SendHorizontal :size="17" />
          </button>
        </div>
      </footer>
    </template>

    <section v-else-if="tab === 'run'" class="run-view">
      <template v-if="run">
        <header class="run-heading">
          <div>
            <span>AGENT RUN</span>
            <h3>{{ run.id }}</h3>
          </div>
          <span class="run-status" :class="`run-status--${run.status}`">
            <span />{{ run.status === 'waiting_approval' ? '等待审核' : run.status === 'running' ? '运行中' : '已完成' }}
          </span>
        </header>

        <div class="run-metrics">
          <div><Clock3 :size="14" /><span><small>耗时</small><strong>{{ run.duration }}</strong></span></div>
          <div><Gauge :size="14" /><span><small>Tokens</small><strong>{{ run.tokens }}</strong></span></div>
          <div>
            <MessageSquareText :size="14" />
            <span>
              <small>实际上下文</small>
              <strong>
                {{ runContextUsage
                  ? `${runContextUsage.messagesRead} 条 / ${runContextUsage.charactersRead.toLocaleString('zh-CN')} 字符`
                  : `${run.contextMessages} 条` }}
              </strong>
            </span>
          </div>
          <div><Activity :size="14" /><span><small>费用</small><strong>{{ run.cost }}</strong></span></div>
        </div>

        <section class="run-section">
          <div class="section-label">触发消息</div>
          <div class="trigger-message">
            <AppAvatar :src="run.triggerAvatar" :name="run.triggerSender" size="sm" />
            <div><strong>{{ run.triggerSender }}</strong><p>{{ run.triggerContent }}</p></div>
          </div>
        </section>

        <section class="run-section run-details">
          <div class="section-label">运行信息</div>
          <dl>
            <div><dt>模型</dt><dd>{{ run.model }}</dd></div>
            <div><dt>模型档位</dt><dd>{{ runTier ? tierLabels[runTier] : '未记录' }}</dd></div>
            <div><dt>推理强度</dt><dd>{{ runReasoning ? reasoningLabels[runReasoning] : '未记录' }}</dd></div>
            <div><dt>回答长度</dt><dd>{{ runAnswerProfile ? answerProfileLabels[runAnswerProfile] : '未记录' }}</dd></div>
            <div><dt>回复强度</dt><dd>{{ runReplyIntensity ? replyIntensityLabels[runReplyIntensity] : '未记录' }}</dd></div>
            <div>
              <dt>上下文长度</dt>
              <dd>
                {{ runContextLength && runContextUsage
                  ? `${contextLengthLabels[runContextLength]} · 上限 ${runContextUsage.messageLimit} 条 / ${runContextUsage.characterLimit.toLocaleString('zh-CN')} 字符`
                  : '未记录' }}
              </dd>
            </div>
            <div>
              <dt>本轮实际读取</dt>
              <dd>
                {{ runContextUsage
                  ? `${runContextUsage.messagesRead} 条 / ${runContextUsage.charactersRead.toLocaleString('zh-CN')} 字符`
                  : '未记录' }}
              </dd>
            </div>
            <div><dt>群聊风格</dt><dd>{{ runGroupChatStyle ? groupChatStyleLabels[runGroupChatStyle] : '未记录' }}</dd></div>
            <div><dt>实际插件</dt><dd>{{ runPlugins.length ? runPlugins.join('、') : '本轮未调用' }}</dd></div>
            <div><dt>开始于</dt><dd>{{ run.startedAt }}</dd></div>
            <div><dt>回复账号</dt><dd>{{ account?.name }}</dd></div>
            <div><dt>发送权限</dt><dd>禁止发送（内测）</dd></div>
          </dl>
          <div v-if="runReasonCodes.length" class="selection-reasons">
            <span>选择原因</span>
            <code v-for="reason in runReasonCodes" :key="reason">{{ reason }}</code>
          </div>
        </section>

        <section class="run-section">
          <div class="section-label">执行过程</div>
          <ol class="run-timeline">
            <li v-for="step in run.steps" :key="step.id" :class="`step--${step.status}`">
              <span class="step-marker"><Check v-if="step.status === 'completed'" :size="11" /><span v-else /></span>
              <div><strong>{{ step.label }}</strong><p>{{ step.detail }}</p></div>
              <time v-if="step.duration">{{ step.duration }}</time>
            </li>
          </ol>
        </section>
      </template>
      <div v-else class="run-empty"><Activity :size="28" /><strong>当前对话还没有运行</strong></div>
    </section>

    <section v-else class="settings-view">
      <div class="settings-intro">
        <div><span>管理员期望值</span><h3>{{ conversation?.name }}</h3></div>
        <label class="switch-control">
          <input
            :checked="policy?.enabled ?? false"
            type="checkbox"
            :disabled="!policyEditable"
            @change="emitPolicy({ enabled: ($event.target as HTMLInputElement).checked })"
          />
          <span />
        </label>
      </div>

      <section class="settings-section runtime-controls-section">
        <div class="section-heading"><Activity :size="15" /><span><strong>运行行为</strong><small>DESIRED POLICY VS ACTUAL RUNTIME</small></span></div>
        <p class="settings-help">顶部开关只表达管理员对本会话的期望，不等于已经获得真实 QQ 发送授权；以下状态以 Runtime 实际回传为准。</p>
        <div v-if="runtimeControls" class="runtime-control-list">
          <article class="runtime-control-card">
            <header>
              <span><strong>被动自动回复</strong><small>PASSIVE AUTO REPLY</small></span>
              <b :class="{ enabled: runtimeControls.passiveAutoReply.actualEnabled }">
                {{ runtimeControls.passiveAutoReply.actualEnabled ? '实际开启' : '实际关闭' }}
              </b>
            </header>
            <dl>
              <div><dt>管理员期望</dt><dd>{{ policy ? (policy.enabled ? '启用会话 Agent（非发送授权）' : '停用会话 Agent') : '尚未读取' }}</dd></div>
              <div><dt>Rollout</dt><dd>{{ runtimeControls.passiveAutoReply.rolloutMode.toUpperCase() }}</dd></div>
              <div><dt>消息交付</dt><dd>{{ runtimeControls.passiveAutoReply.deliveryEnabled ? '已开启' : '关闭 / NO SEND' }}</dd></div>
              <div><dt>Kill switch</dt><dd>{{ runtimeControls.passiveAutoReply.killSwitch ? '开启' : '关闭' }}</dd></div>
            </dl>
            <p>{{ runtimeControls.passiveAutoReply.summary }}</p>
          </article>

          <article class="runtime-control-card">
            <header>
              <span><strong>主动加入群聊</strong><small>PROACTIVE GROUP PARTICIPATION</small></span>
              <b :class="{ enabled: runtimeControls.proactiveGroupParticipation.actualEnabled }">
                {{ runtimeControls.proactiveGroupParticipation.actualEnabled ? '实际开启' : 'Shadow' }}
              </b>
            </header>
            <dl>
              <div><dt>管理员期望</dt><dd>{{ policy ? (policy.enabled ? '启用会话 Agent（非发送授权）' : '停用会话 Agent') : '尚未读取' }}</dd></div>
              <div><dt>当前阶段</dt><dd>{{ runtimeControls.proactiveGroupParticipation.stage === 'probe_shadow' ? 'Probe Shadow' : runtimeControls.proactiveGroupParticipation.stage }}</dd></div>
              <div><dt>消息交付</dt><dd>{{ runtimeControls.proactiveGroupParticipation.deliveryEnabled ? '已开启' : '关闭 / NO SEND' }}</dd></div>
              <div><dt>真实主动发言</dt><dd>{{ runtimeControls.proactiveGroupParticipation.actualEnabled ? '已接通' : '未接通' }}</dd></div>
            </dl>
            <p>{{ runtimeControls.proactiveGroupParticipation.summary }}</p>
          </article>
        </div>
        <div v-else class="settings-state"><RefreshCw v-if="runtimeLoading" :size="15" class="spinning" />运行状态尚未回传</div>
      </section>

      <div v-if="policyLoading" class="settings-state"><RefreshCw :size="16" class="spinning" />正在读取会话策略</div>
      <div v-else-if="!policy" class="settings-state settings-state--error">
        <Unplug :size="16" />{{ policyError || '当前账号与会话还没有可编辑策略' }}
      </div>

      <template v-else>
        <div v-if="policyError" class="settings-error">{{ policyError }}</div>

        <section class="settings-section">
          <div class="section-heading"><Bot :size="15" /><span><strong>自适应选择</strong><small>INITIAL VALUE + ALLOWED RANGE</small></span></div>
          <p class="settings-help">普通设置提供初值和合法范围，Agent 可以根据本轮任务改选；只有“锁定”不可覆盖。</p>

          <article v-for="axis in adaptiveAxes" :key="axis.key" class="adaptive-setting">
            <header><span><strong>{{ axis.title }}</strong><small>{{ axis.detail }}</small></span></header>
            <div class="adaptive-controls">
              <label>
                <span>模式</span>
                <select
                  :value="axis.setting?.mode"
                  :disabled="!policyEditable"
                  @change="updateAdaptiveMode(axis.key, ($event.target as HTMLSelectElement).value as InternalTestSelectionMode)"
                >
                  <option v-for="mode in selectionModes" :key="mode" :value="mode">{{ selectionModeLabels[mode] }}</option>
                </select>
              </label>
              <label>
                <span>初值</span>
                <select
                  :value="axis.setting?.preferred"
                  :disabled="!policyEditable || !axis.options.length"
                  @change="updateAdaptivePreferred(axis.key, ($event.target as HTMLSelectElement).value)"
                >
                  <option
                    v-for="option in axis.options"
                    :key="option.id"
                    :value="option.id"
                    :disabled="!option.available"
                  >
                    {{ option.label }}{{ option.available ? '' : '（不可用）' }}
                  </option>
                </select>
              </label>
            </div>
            <div class="allowed-options">
              <span>Agent 可选范围</span>
              <label v-for="option in axis.options" :key="option.id" :title="option.reason">
                <input
                  type="checkbox"
                  :checked="isAdaptiveAllowed(axis.setting, option.id)"
                  :disabled="!policyEditable || !option.available"
                  @change="toggleAdaptiveAllowed(axis.key, option.id)"
                />
                <span>{{ option.label }}</span>
              </label>
            </div>
          </article>
        </section>

        <section class="settings-section">
          <div class="section-heading"><Wrench :size="15" /><span><strong>插件与能力</strong><small>DYNAMIC CATALOG</small></span></div>
          <p class="settings-help">“偏好启用”不要求每轮调用；“锁定可用”只保证能力留在合法候选中。</p>
          <p v-if="catalog" class="settings-help">
            控制台身份：超级管理员；Bot 执行身份：普通管理员。这里设置每个群的初值，Agent 仍可在允许范围内自适应。
          </p>
          <p v-if="catalog" class="settings-help">
            “已装配”表示源码和 Compose 已就绪，不代表执行器当前在线或本轮已经调用；实际调用结果单独显示。
          </p>
          <div v-if="catalog?.plugins.length" class="plugin-list">
            <article v-for="plugin in catalog.plugins" :key="plugin.id" class="plugin-row" :class="{ unavailable: !plugin.available }">
              <div>
                <span class="plugin-title">
                  <strong>{{ plugin.displayName }}</strong>
                </span>
                <span class="plugin-badges">
                  <small :class="plugin.installed ? 'available' : 'unavailable'">{{ plugin.installed ? '已安装' : '未安装' }}</small>
                  <small :class="plugin.available ? 'available' : 'unavailable'">{{ plugin.available ? '本页可配置' : '当前不可配置' }}</small>
                  <small>{{ pluginExecutionLabels[plugin.executionKind] }}</small>
                  <small>{{ pluginRuntimeLabels[plugin.runtimeTarget] }}</small>
                  <small :class="plugin.runtimeReadiness === 'configured' ? 'available' : 'unavailable'">
                    {{ pluginReadinessLabels[plugin.runtimeReadiness] }}
                  </small>
                  <small v-if="plugin.builtIn">系统内建</small>
                  <small v-if="plugin.requiredRole">{{ pluginRoleLabels[plugin.requiredRole] }}</small>
                  <small v-if="plugin.executionRole === 'admin'">Bot 普通管理员执行</small>
                </span>
                <p>{{ plugin.description }}</p>
                <em v-if="!plugin.available">{{ plugin.unavailableReason || '当前 Runtime 未接通该能力' }}</em>
              </div>
              <select
                v-if="plugin.policyManaged"
                :value="plugin.available ? (policy.plugins[plugin.id] ?? 'off') : 'off'"
                :disabled="!policyEditable || !plugin.available"
                :aria-label="`${plugin.displayName} 使用模式`"
                @change="updatePluginMode(plugin.id, ($event.target as HTMLSelectElement).value as InternalTestPluginMode)"
              >
                <option
                  v-for="mode in pluginModeOptions(plugin)"
                  :key="mode"
                  :value="mode"
                >
                  {{ pluginModeLabels[mode] }}
                </option>
              </select>
              <span v-else class="plugin-policy-note">只读状态，不可从本页修改</span>
            </article>
          </div>
          <div v-else class="empty-catalog">当前 Catalog 没有已登记插件</div>
        </section>

        <section class="settings-section mcp-workbench">
          <div class="section-heading">
            <Database :size="15" />
            <span><strong>MCP 工作台</strong><small>SUPER ADMIN · READ ONLY</small></span>
            <button type="button" class="section-action" title="刷新 MCP 状态" :disabled="mcpCatalogLoading" @click="loadMcpCatalog(true)">
              <RefreshCw :size="13" :class="{ spinning: mcpCatalogLoading }" />
            </button>
          </div>

          <div v-if="mcpCatalogLoading && !mcpCatalog" class="settings-state"><RefreshCw :size="15" class="spinning" />正在读取 MCP Catalog</div>
          <div v-else-if="mcpCatalogError" class="settings-state settings-state--error"><Unplug :size="15" />{{ mcpCatalogError }}</div>
          <template v-else-if="mcpCatalog">
            <div class="mcp-server-grid">
              <article v-for="server in mcpCatalog.servers" :key="server.id" :class="{ unavailable: !server.available }">
                <header><strong>{{ server.displayName }}</strong><small>{{ server.id }}</small></header>
                <span :class="server.available ? 'available' : 'unavailable'">
                  {{ server.available ? '可调用' : server.reason || '不可用' }}
                </span>
                <p>{{ server.capabilityCount }} 项能力 · {{ server.health }}</p>
              </article>
            </div>

            <div v-if="mcpCatalog.capabilities.length" class="mcp-invocation-panel">
              <label class="mcp-capability-picker">
                <span>Capability</span>
                <select :value="selectedMcpCapabilityId" @change="selectMcpCapability(($event.target as HTMLSelectElement).value)">
                  <option v-for="capability in mcpCatalog.capabilities" :key="capability.id" :value="capability.id" :disabled="!capability.available">
                    {{ capability.name }}{{ capability.available ? '' : `（${capability.unavailableReason || '不可用'}）` }}
                  </option>
                </select>
              </label>

              <header v-if="selectedMcpCapability" class="mcp-capability-heading">
                <div><strong>{{ selectedMcpCapability.name }}</strong><small>{{ selectedMcpCapability.serverId }} / {{ selectedMcpCapability.toolName }}</small></div>
                <span>{{ selectedMcpCapability.privacy }}</span>
              </header>
              <p v-if="selectedMcpCapability" class="mcp-description">{{ selectedMcpCapability.description }}</p>

              <div v-if="mcpInputProperties.length" class="mcp-fields">
                <label v-for="[name, schema] in mcpInputProperties" :key="name">
                  <span>{{ schemaLabel(name, schema) }}<b v-if="mcpRequired.has(name)">*</b><small>{{ name }}</small></span>
                  <select
                    v-if="Array.isArray(schema.enum)"
                    :value="mcpArguments[name] ?? schema.default ?? ''"
                    @change="updateMcpScalar(name, schema, $event)"
                  >
                    <option v-if="!mcpRequired.has(name)" value="">未设置</option>
                    <option v-for="option in schema.enum" :key="String(option)" :value="String(option)">{{ option }}</option>
                  </select>
                  <input
                    v-else-if="schemaKind(schema) === 'boolean'"
                    type="checkbox"
                    :checked="Boolean(mcpArguments[name] ?? schema.default ?? false)"
                    @change="updateMcpScalar(name, schema, $event)"
                  />
                  <textarea
                    v-else-if="['array', 'object'].includes(schemaKind(schema))"
                    :value="mcpJsonArguments[name] ?? ''"
                    rows="3"
                    :placeholder="schemaKind(schema) === 'array' ? '[]' : '{}'"
                    @input="mcpJsonArguments[name] = ($event.target as HTMLTextAreaElement).value"
                  />
                  <input
                    v-else
                    :type="['integer', 'number'].includes(schemaKind(schema)) ? 'number' : 'text'"
                    :value="mcpArguments[name] ?? schema.default ?? ''"
                    :min="typeof schema.minimum === 'number' ? schema.minimum : undefined"
                    :max="typeof schema.maximum === 'number' ? schema.maximum : undefined"
                    @input="updateMcpScalar(name, schema, $event)"
                  />
                </label>
              </div>

              <button
                type="button"
                class="mcp-invoke-button"
                :disabled="!selectedMcpCapability?.available || mcpInvoking"
                @click="invokeMcp"
              >
                <RefreshCw v-if="mcpInvoking" :size="14" class="spinning" />
                <Play v-else :size="14" />
                {{ mcpInvoking ? '调用中' : '调用' }}
              </button>

              <div v-if="mcpInvocationError" class="mcp-result mcp-result--error">{{ mcpInvocationError }}</div>
              <div v-else-if="mcpInvocation" class="mcp-result">
                <header>
                  <span>{{ mcpInvocation.ok ? '调用成功' : '上游返回错误' }} · generation {{ mcpInvocation.generation }}</span>
                  <a v-if="mcpInvocation.sourceUrl" :href="mcpInvocation.sourceUrl" target="_blank" rel="noreferrer" title="打开来源"><ExternalLink :size="13" /></a>
                </header>
                <small v-if="mcpInvocation.fetchedAt">{{ mcpInvocation.fetchedAt }}</small>
                <pre>{{ invocationText(mcpInvocation.data ?? mcpInvocation.content) }}</pre>
              </div>
            </div>
            <div v-else class="empty-catalog">当前没有可调用的 MCP Capability</div>
          </template>
        </section>
      </template>

      <footer class="settings-footer">
        <span><ShieldCheck :size="13" />按账号 + 会话保存；普通偏好可由 Agent 本轮改选</span>
        <button
          type="button"
          class="save-button"
          :disabled="policyLoading || policySaving || !policy"
          @click="emit('saveSettings')"
        >
          <RefreshCw v-if="policySaving" :size="14" class="spinning" />
          <Save v-else :size="14" />
          {{ policySaving ? '保存中' : '保存配置' }}
        </button>
      </footer>
    </section>
  </aside>
</template>

<style scoped>
.agent-console {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  border-left: 1px solid var(--border-strong);
  background: var(--agent-background);
}

.agent-header {
  display: flex;
  height: 64px;
  min-width: 0;
  flex: 0 0 auto;
  align-items: center;
  gap: 9px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  padding: 0 12px;
}

.mobile-back {
  display: none;
}

.agent-logo,
.assistant-avatar,
.system-avatar {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 6px;
  color: #ffffff;
  background: var(--brand);
}

.agent-logo {
  width: 32px;
  height: 32px;
}

.agent-heading {
  min-width: 0;
  flex: 1;
}

.agent-heading > div {
  display: flex;
  align-items: center;
  gap: 5px;
}

.agent-heading strong {
  color: var(--text);
  font-size: 12px;
  font-weight: 720;
}

.agent-heading small,
.agent-heading p {
  color: var(--text-muted);
  font-size: 8px;
}

.agent-heading p {
  overflow: hidden;
  margin: 3px 0 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-dot {
  width: 6px;
  height: 6px;
  margin-left: 2px;
  border-radius: 50%;
  background: var(--warning);
}

.runtime-dot.online {
  background: var(--success);
}

.agent-context-bar {
  display: grid;
  height: 46px;
  flex: 0 0 auto;
  grid-template-columns: minmax(0, 1fr) auto 30px;
  align-items: center;
  gap: 7px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-subtle);
  padding: 0 9px;
}

.session-picker {
  position: relative;
  min-width: 0;
}

.session-picker > button {
  display: grid;
  width: 100%;
  height: 30px;
  cursor: pointer;
  grid-template-columns: 7px minmax(0, 1fr) 14px;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  background: var(--surface);
  padding: 0 7px;
  font: inherit;
  font-size: 9px;
  text-align: left;
}

.session-picker > button span:nth-child(2) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-status {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-muted);
}

.session-status--running {
  background: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}

.session-status--waiting_approval {
  background: var(--warning);
  box-shadow: 0 0 0 3px var(--warning-soft);
}

.session-menu {
  position: absolute;
  z-index: 50;
  top: 35px;
  left: 0;
  width: min(250px, 78vw);
  border: 1px solid var(--border-strong);
  border-radius: 7px;
  background: var(--surface);
  box-shadow: var(--floating-shadow);
  padding: 4px;
}

.session-menu button {
  display: flex;
  width: 100%;
  min-height: 43px;
  cursor: pointer;
  align-items: center;
  justify-content: space-between;
  gap: 7px;
  border: 0;
  border-radius: 5px;
  color: var(--text-secondary);
  background: transparent;
  padding: 6px 8px;
  text-align: left;
}

.session-menu button:hover,
.session-menu button.active {
  color: var(--brand-strong);
  background: var(--brand-soft);
}

.session-menu strong,
.session-menu small {
  display: block;
}

.session-menu strong {
  font-size: 10px;
}

.session-menu small {
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 8px;
}

.session-menu .new-session-row {
  min-height: 32px;
  justify-content: flex-start;
  border-top: 1px solid var(--border);
  border-radius: 0 0 5px 5px;
  margin-top: 3px;
}

.model-picker {
  display: flex;
  height: 30px;
  align-items: center;
  gap: 5px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  padding: 0 6px;
}

.model-picker span {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 7px;
}

.model-picker select {
  max-width: 88px;
  border: 0;
  color: var(--text-secondary);
  background: transparent;
  font: inherit;
  font-size: 8px;
  outline: 0;
}

.agent-tabs {
  display: grid;
  height: 40px;
  flex: 0 0 auto;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  padding: 0 8px;
}

.agent-tabs button {
  position: relative;
  display: flex;
  cursor: pointer;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border: 0;
  color: var(--text-muted);
  background: transparent;
  font: inherit;
  font-size: 10px;
}

.agent-tabs button::after {
  position: absolute;
  right: 12px;
  bottom: -1px;
  left: 12px;
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: transparent;
  content: '';
}

.agent-tabs button.active {
  color: var(--brand-strong);
  font-weight: 650;
}

.agent-tabs button.active::after {
  background: var(--brand);
}

.agent-tabs b {
  display: grid;
  width: 14px;
  height: 14px;
  place-items: center;
  border-radius: 7px;
  color: #ffffff;
  background: var(--warning);
  font-size: 8px;
}

.agent-stream {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 0 13px 22px;
}

.scope-line {
  display: flex;
  height: 35px;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 8px;
}

.scope-line span {
  display: flex;
  align-items: center;
  gap: 3px;
}

.runtime-mode-note {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 10px 0 2px;
  border: 1px solid var(--success-border);
  border-radius: 7px;
  color: var(--success-strong);
  background: var(--success-soft);
  padding: 7px 9px;
  font-size: 8px;
  line-height: 1.45;
}

.runtime-mode-note strong {
  margin-right: 5px;
}

.runtime-unavailable {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 12px 0 4px;
  border: 1px solid var(--warning-border);
  border-radius: 7px;
  background: var(--warning-soft);
  padding: 9px;
}

.runtime-unavailable > div {
  min-width: 0;
  flex: 1;
}

.runtime-unavailable > button {
  display: inline-flex;
  height: 27px;
  flex: 0 0 auto;
  cursor: pointer;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--warning-border);
  border-radius: 6px;
  color: var(--warning-strong);
  background: var(--surface);
  padding: 0 7px;
  font: inherit;
  font-size: 8px;
}

.runtime-unavailable > button:disabled {
  cursor: wait;
}

.spinning {
  animation: runtime-spin 0.9s linear infinite;
}

@keyframes runtime-spin {
  to { transform: rotate(360deg); }
}

.runtime-unavailable > span {
  display: grid;
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 6px;
  color: var(--warning-strong);
  background: var(--surface);
}

.runtime-unavailable strong,
.runtime-unavailable small {
  display: block;
}

.runtime-unavailable strong {
  color: var(--text);
  font-size: 10px;
}

.runtime-unavailable small {
  margin-top: 3px;
  color: var(--text-secondary);
  font-size: 8px;
}

button:disabled,
select:disabled,
textarea:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.agent-message {
  border-bottom: 1px solid var(--border-soft);
  padding: 13px 0 11px;
}

.agent-message > header {
  display: flex;
  height: 24px;
  align-items: center;
  gap: 6px;
}

.assistant-avatar,
.system-avatar {
  width: 24px;
  height: 24px;
}

.system-avatar {
  color: var(--text-secondary);
  background: var(--surface-muted);
}

.agent-message > header strong {
  color: var(--text-secondary);
  font-size: 10px;
}

.agent-message > header time {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 8px;
}

.agent-message--operator .agent-parts {
  margin-left: 30px;
  border-left: 2px solid var(--brand-border);
  padding-left: 9px;
}

.agent-parts {
  margin-top: 4px;
}

.agent-thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 13px 0;
  color: var(--text-muted);
}

.agent-thinking > span:nth-child(2) {
  display: flex;
  gap: 3px;
}

.agent-thinking i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--brand);
  animation: thinking 1.1s ease-in-out infinite;
}

.agent-thinking i:nth-child(2) {
  animation-delay: 120ms;
}

.agent-thinking i:nth-child(3) {
  animation-delay: 240ms;
}

.agent-thinking small {
  font-size: 9px;
}

.agent-empty,
.run-empty {
  display: flex;
  min-height: 240px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-muted);
}

.agent-empty strong,
.run-empty strong {
  color: var(--text-secondary);
  font-size: 11px;
}

.quick-prompts {
  display: flex;
  gap: 6px;
}

.quick-prompts button {
  cursor: pointer;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  background: var(--surface);
  padding: 6px 8px;
  font-size: 9px;
}

.agent-composer {
  min-height: 120px;
  flex: 0 0 auto;
  border-top: 1px solid var(--border-strong);
  background: var(--surface);
  padding: 7px 10px 8px;
}

.context-chip {
  display: flex;
  width: fit-content;
  max-width: 100%;
  height: 20px;
  align-items: center;
  gap: 4px;
  border-radius: 4px;
  color: var(--brand-strong);
  background: var(--brand-soft);
  padding: 0 6px;
  font-size: 8px;
}

.context-chip span {
  margin-left: 3px;
  color: var(--text-muted);
}

.agent-composer textarea {
  display: block;
  width: 100%;
  height: 57px;
  resize: none;
  border: 0;
  color: var(--text);
  background: transparent;
  padding: 8px 3px 4px;
  font: inherit;
  font-size: 11px;
  line-height: 1.5;
  outline: 0;
}

.agent-composer textarea::placeholder {
  color: var(--text-muted);
}

.agent-composer-footer {
  display: flex;
  height: 27px;
  align-items: center;
  justify-content: space-between;
}

.agent-composer-footer > div {
  display: flex;
  align-items: center;
  gap: 2px;
}

.answer-profile-picker {
  display: flex;
  height: 24px;
  align-items: center;
  gap: 1px;
  margin-left: 4px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-subtle);
  padding: 2px;
}

.answer-profile-picker button {
  min-width: 25px;
  height: 18px;
  cursor: pointer;
  border: 0;
  border-radius: 4px;
  color: var(--text-muted);
  background: transparent;
  padding: 0 6px;
  font: inherit;
  font-size: 8px;
}

.answer-profile-picker button.active {
  color: var(--brand-strong);
  background: var(--brand-soft);
  font-weight: 700;
}

.answer-profile-picker button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.prompt-send,
.stop-button {
  display: grid;
  width: 34px;
  height: 28px;
  cursor: pointer;
  place-items: center;
  border: 0;
  border-radius: 6px;
}

.prompt-send {
  color: #ffffff;
  background: var(--brand);
}

.prompt-send:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.stop-button {
  color: var(--danger);
  background: var(--danger-soft);
}

.run-view,
.settings-view {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
}

.run-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
  padding: 17px 15px 13px;
}

.run-heading > div > span,
.settings-intro > div > span {
  color: var(--brand-strong);
  font-family: var(--font-mono);
  font-size: 8px;
  font-weight: 700;
}

.run-heading h3,
.settings-intro h3 {
  margin: 4px 0 0;
  color: var(--text);
  font-size: 17px;
  font-weight: 720;
}

.run-status {
  display: inline-flex;
  height: 23px;
  align-items: center;
  gap: 5px;
  border-radius: 5px;
  color: var(--warning-strong);
  background: var(--warning-soft);
  padding: 0 7px;
  font-size: 9px;
  font-weight: 650;
}

.run-status > span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--warning);
}

.run-status--completed {
  color: var(--success-strong);
  background: var(--success-soft);
}

.run-status--completed > span {
  background: var(--success);
}

.run-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.run-metrics > div {
  display: flex;
  min-width: 0;
  height: 58px;
  align-items: center;
  gap: 6px;
  border-right: 1px solid var(--border);
  color: var(--brand);
  padding: 0 8px;
}

.run-metrics > div:last-child {
  border-right: 0;
}

.run-metrics small,
.run-metrics strong {
  display: block;
  white-space: nowrap;
}

.run-metrics small {
  color: var(--text-muted);
  font-size: 7px;
}

.run-metrics strong {
  margin-top: 2px;
  color: var(--text);
  font-size: 10px;
}

.run-section,
.settings-section {
  border-bottom: 1px solid var(--border);
  padding: 14px 15px;
}

.section-label {
  margin-bottom: 10px;
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 720;
}

.trigger-message {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  border-left: 2px solid var(--brand);
  background: var(--surface-subtle);
  padding: 9px;
}

.trigger-message > div {
  min-width: 0;
}

.trigger-message strong {
  color: var(--text-secondary);
  font-size: 10px;
}

.trigger-message p {
  margin: 4px 0 0;
  color: var(--text);
  font-size: 10px;
  line-height: 1.55;
}

.run-details dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 16px;
  margin: 0;
}

.run-details dl div {
  min-width: 0;
}

.run-details dt {
  color: var(--text-muted);
  font-size: 8px;
}

.run-details dd {
  overflow: hidden;
  margin: 3px 0 0;
  color: var(--text-secondary);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selection-reasons {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  margin-top: 12px;
  border-top: 1px solid var(--border-soft);
  padding-top: 9px;
}

.selection-reasons > span {
  margin-right: 2px;
  color: var(--text-muted);
  font-size: 8px;
}

.selection-reasons code {
  border-radius: 4px;
  color: var(--brand-strong);
  background: var(--brand-soft);
  padding: 3px 5px;
  font-size: 7px;
}

.run-timeline {
  margin: 0;
  padding: 0;
  list-style: none;
}

.run-timeline li {
  position: relative;
  display: grid;
  min-height: 51px;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  gap: 7px;
}

.run-timeline li:not(:last-child)::before {
  position: absolute;
  top: 20px;
  bottom: -1px;
  left: 10px;
  width: 1px;
  background: var(--border-strong);
  content: '';
}

.step-marker {
  position: relative;
  z-index: 1;
  display: grid;
  width: 21px;
  height: 21px;
  place-items: center;
  border: 1px solid var(--success-border);
  border-radius: 50%;
  color: var(--success-strong);
  background: var(--success-soft);
}

.step-marker > span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--warning);
}

.step--waiting .step-marker {
  border-color: var(--warning-border);
  background: var(--warning-soft);
}

.run-timeline strong {
  display: block;
  color: var(--text);
  font-size: 10px;
}

.run-timeline p {
  margin: 3px 0 0;
  color: var(--text-muted);
  font-size: 8px;
}

.run-timeline time {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 8px;
}

.settings-intro {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
  padding: 16px 15px;
}

.switch-control input {
  position: absolute;
  opacity: 0;
}

.switch-control span {
  position: relative;
  display: block;
  width: 34px;
  height: 19px;
  cursor: pointer;
  border-radius: 10px;
  background: var(--border-strong);
  transition: background 150ms ease;
}

.switch-control span::after {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 1px 3px rgb(0 0 0 / 20%);
  content: '';
  transition: transform 150ms ease;
}

.switch-control input:checked + span {
  background: var(--brand);
}

.switch-control input:checked + span::after {
  transform: translateX(15px);
}

.section-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 11px;
  color: var(--brand);
}

.section-heading strong,
.section-heading small {
  display: block;
}

.section-heading strong {
  color: var(--text);
  font-size: 10px;
}

.section-heading small {
  margin-top: 2px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 7px;
}

.settings-state {
  display: flex;
  min-height: 150px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  color: var(--text-muted);
  font-size: 9px;
}

.settings-state--error {
  color: var(--warning-strong);
}

.settings-error {
  margin: 10px 15px 0;
  border: 1px solid var(--warning-border);
  border-radius: 6px;
  color: var(--warning-strong);
  background: var(--warning-soft);
  padding: 7px 9px;
  font-size: 8px;
}

.settings-help {
  margin: -2px 0 10px;
  color: var(--text-muted);
  font-size: 8px;
  line-height: 1.5;
}

.runtime-control-list {
  display: grid;
  gap: 7px;
}

.runtime-control-card {
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  padding: 9px;
}

.runtime-control-card > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.runtime-control-card > header strong,
.runtime-control-card > header small {
  display: block;
}

.runtime-control-card > header strong {
  color: var(--text);
  font-size: 9px;
}

.runtime-control-card > header small {
  margin-top: 2px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 7px;
}

.runtime-control-card > header b {
  flex: 0 0 auto;
  border-radius: 4px;
  color: var(--warning-strong);
  background: var(--warning-soft);
  padding: 3px 5px;
  font-size: 7px;
  font-weight: 700;
}

.runtime-control-card > header b.enabled {
  color: var(--success-strong);
  background: var(--success-soft);
}

.runtime-control-card dl {
  display: grid;
  gap: 4px;
  margin: 9px 0 0;
}

.runtime-control-card dl > div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  border-top: 1px solid var(--border-soft);
  padding-top: 4px;
  font-size: 7px;
}

.runtime-control-card dt {
  color: var(--text-muted);
}

.runtime-control-card dd {
  margin: 0;
  color: var(--text-secondary);
  text-align: right;
}

.runtime-control-card > p {
  margin: 8px 0 0;
  color: var(--text-muted);
  font-size: 7px;
  line-height: 1.45;
}

.runtime-controls-section .settings-state {
  min-height: 64px;
  border: 1px dashed var(--border-strong);
  border-radius: 6px;
}

.adaptive-setting {
  border-top: 1px solid var(--border-soft);
  padding: 10px 0 11px;
}

.adaptive-setting > header strong,
.adaptive-setting > header small {
  display: block;
}

.adaptive-setting > header strong {
  color: var(--text);
  font-size: 10px;
}

.adaptive-setting > header small {
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 8px;
}

.adaptive-controls {
  display: grid;
  grid-template-columns: minmax(90px, 0.8fr) minmax(130px, 1.2fr);
  gap: 7px;
  margin-top: 9px;
}

.adaptive-controls label > span,
.allowed-options > span {
  display: block;
  margin-bottom: 4px;
  color: var(--text-muted);
  font-size: 7px;
}

.adaptive-controls select,
.plugin-row select {
  width: 100%;
  height: 28px;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-secondary);
  background: var(--surface);
  padding: 0 6px;
  font: inherit;
  font-size: 8px;
}

.allowed-options {
  margin-top: 8px;
}

.allowed-options label {
  display: inline-flex;
  max-width: 100%;
  cursor: pointer;
  align-items: center;
  gap: 4px;
  margin: 0 5px 5px 0;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-secondary);
  background: var(--surface);
  padding: 4px 6px;
  font-size: 8px;
}

.allowed-options label:has(input:checked) {
  color: var(--brand-strong);
  border-color: var(--brand-border);
  background: var(--brand-soft);
}

.allowed-options input {
  width: 12px;
  height: 12px;
  margin: 0;
  accent-color: var(--brand);
}

.plugin-list {
  display: grid;
  gap: 6px;
}

.plugin-row {
  display: grid;
  min-width: 0;
  grid-template-columns: minmax(0, 1fr) 108px;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  padding: 8px;
}

.plugin-row > div {
  min-width: 0;
}

.plugin-title {
  display: flex;
  align-items: center;
  gap: 5px;
}

.plugin-title strong {
  overflow: hidden;
  color: var(--text);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plugin-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 5px;
}

.plugin-badges small {
  flex: 0 0 auto;
  border-radius: 4px;
  color: var(--text-muted);
  background: var(--surface-subtle);
  padding: 2px 4px;
  font-size: 7px;
}

.plugin-badges small.available {
  color: var(--success-strong);
  background: var(--success-soft);
}

.plugin-badges small.unavailable {
  color: var(--warning-strong);
  background: var(--warning-soft);
}

.plugin-policy-note {
  color: var(--text-muted);
  font-size: 7px;
  line-height: 1.35;
  text-align: right;
}

.plugin-row p,
.plugin-row em {
  overflow: hidden;
  margin: 3px 0 0;
  color: var(--text-muted);
  font-size: 7px;
  font-style: normal;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plugin-row em {
  display: block;
  color: var(--warning-strong);
}

.plugin-row.unavailable {
  background: var(--surface-subtle);
}

.empty-catalog {
  border: 1px dashed var(--border-strong);
  border-radius: 6px;
  color: var(--text-muted);
  padding: 14px;
  font-size: 8px;
  text-align: center;
}

.form-row,
.range-row,
.toggle-row {
  display: flex;
  min-height: 38px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border-top: 1px solid var(--border-soft);
  color: var(--text-secondary);
  font-size: 9px;
}

.form-row select {
  max-width: 180px;
  height: 27px;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-secondary);
  background: var(--surface);
  padding: 0 6px;
  font: inherit;
  font-size: 9px;
}

.segmented-control {
  display: grid;
  width: 126px;
  height: 27px;
  grid-template-columns: repeat(3, 1fr);
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--surface-muted);
  padding: 2px;
}

.segmented-control button {
  cursor: pointer;
  border: 0;
  border-radius: 3px;
  color: var(--text-muted);
  background: transparent;
  font-size: 8px;
}

.segmented-control button.active {
  color: var(--brand-strong);
  background: var(--surface);
  box-shadow: 0 1px 3px rgb(24 48 53 / 10%);
}

.range-row {
  display: block;
  padding: 9px 0;
}

.range-row > span {
  display: flex;
  justify-content: space-between;
}

.range-row strong {
  color: var(--brand-strong);
  font-size: 9px;
}

.range-row input {
  width: 100%;
  margin-top: 8px;
  accent-color: var(--brand);
}

.toggle-row {
  cursor: pointer;
}

.toggle-row > span strong,
.toggle-row > span small {
  display: block;
}

.toggle-row > span strong {
  color: var(--text-secondary);
  font-size: 9px;
}

.toggle-row > span small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
}

.toggle-row input {
  width: 15px;
  height: 15px;
  accent-color: var(--brand);
}

.tool-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.tool-grid button {
  display: grid;
  min-width: 0;
  min-height: 45px;
  cursor: pointer;
  grid-template-columns: 18px minmax(0, 1fr) 13px;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-muted);
  background: var(--surface);
  padding: 6px 7px;
  text-align: left;
}

.tool-grid button.active {
  color: var(--brand-strong);
  border-color: var(--brand-border);
  background: var(--brand-soft);
}

.tool-grid strong,
.tool-grid small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-grid strong {
  color: var(--text-secondary);
  font-size: 9px;
}

.tool-grid small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 7px;
}

.settings-footer {
  display: flex;
  min-height: 48px;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--text-muted);
  padding: 0 15px;
  font-size: 8px;
}

.settings-footer > span,
.save-button {
  display: flex;
  align-items: center;
  gap: 5px;
}

.settings-footer > span {
  min-width: 0;
  line-height: 1.35;
}

.settings-footer > span svg {
  flex: 0 0 auto;
}

.save-button {
  height: 29px;
  flex: 0 0 auto;
  cursor: pointer;
  border: 0;
  border-radius: 5px;
  color: #ffffff;
  background: var(--brand);
  padding: 0 10px;
  font-size: 9px;
  font-weight: 650;
}

.mcp-workbench .section-heading {
  position: relative;
}

.section-action {
  display: grid;
  width: 27px;
  height: 27px;
  margin-left: auto;
  cursor: pointer;
  place-items: center;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-muted);
  background: var(--surface);
}

.mcp-server-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.mcp-server-grid article {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  padding: 8px;
}

.mcp-server-grid article.unavailable {
  opacity: 0.72;
}

.mcp-server-grid header,
.mcp-server-grid header strong,
.mcp-server-grid header small {
  display: block;
  min-width: 0;
}

.mcp-server-grid header strong {
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mcp-server-grid header small,
.mcp-server-grid p {
  overflow: hidden;
  margin: 2px 0 0;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 7px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mcp-server-grid > article > span {
  display: inline-flex;
  margin-top: 6px;
  border-radius: 3px;
  padding: 2px 5px;
  font-size: 7px;
}

.mcp-server-grid > article > span.available {
  color: var(--success);
  background: color-mix(in srgb, var(--success) 10%, transparent);
}

.mcp-server-grid > article > span.unavailable {
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 10%, transparent);
}

.mcp-invocation-panel {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
  border-top: 1px solid var(--border);
  padding-top: 10px;
}

.mcp-capability-picker,
.mcp-fields > label {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.mcp-capability-picker > span,
.mcp-fields > label > span {
  color: var(--text-muted);
  font-size: 8px;
}

.mcp-capability-picker select,
.mcp-fields input:not([type='checkbox']),
.mcp-fields select,
.mcp-fields textarea {
  width: 100%;
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-secondary);
  background: var(--surface);
  padding: 6px 7px;
  font: inherit;
  font-size: 8px;
  outline: 0;
}

.mcp-fields textarea {
  resize: vertical;
  font-family: var(--font-mono);
  line-height: 1.5;
}

.mcp-fields input[type='checkbox'] {
  width: 15px;
  height: 15px;
  accent-color: var(--brand);
}

.mcp-capability-heading {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.mcp-capability-heading div,
.mcp-capability-heading strong,
.mcp-capability-heading small {
  display: block;
  min-width: 0;
}

.mcp-capability-heading strong {
  color: var(--text-primary);
  font-size: 10px;
}

.mcp-capability-heading small {
  margin-top: 2px;
  overflow: hidden;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 7px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mcp-capability-heading > span {
  flex: 0 0 auto;
  border: 1px solid var(--border);
  border-radius: 3px;
  color: var(--text-muted);
  padding: 2px 5px;
  font-size: 7px;
}

.mcp-description {
  margin: 0;
  color: var(--text-muted);
  font-size: 8px;
  line-height: 1.5;
}

.mcp-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.mcp-fields > label > span b {
  color: var(--danger);
}

.mcp-fields > label > span small {
  display: block;
  margin-top: 1px;
  overflow: hidden;
  font-family: var(--font-mono);
  font-size: 7px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mcp-invoke-button {
  display: inline-flex;
  min-width: 76px;
  min-height: 30px;
  cursor: pointer;
  align-items: center;
  align-self: flex-end;
  justify-content: center;
  gap: 5px;
  border: 0;
  border-radius: 5px;
  color: #ffffff;
  background: var(--brand);
  padding: 0 11px;
  font-size: 9px;
  font-weight: 650;
}

.mcp-invoke-button:disabled,
.section-action:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.mcp-result {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-muted);
  padding: 8px;
}

.mcp-result--error {
  color: var(--danger);
  font-size: 8px;
}

.mcp-result header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--success);
  font-size: 8px;
}

.mcp-result header a {
  display: grid;
  width: 23px;
  height: 23px;
  place-items: center;
  color: var(--brand-strong);
}

.mcp-result > small {
  display: block;
  margin-top: 3px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 7px;
}

.mcp-result pre {
  max-height: 320px;
  margin: 7px 0 0;
  overflow: auto;
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 7px;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

@keyframes thinking {
  0%,
  100% {
    opacity: 0.35;
    transform: translateY(0);
  }
  50% {
    opacity: 1;
    transform: translateY(-2px);
  }
}

@media (max-width: 1280px) {
  .model-picker span {
    display: none;
  }

  .model-picker select {
    max-width: 76px;
  }
}

@media (max-width: 860px) {
  .agent-console {
    border-left: 0;
  }

  .agent-header {
    height: 60px;
    padding: 0 10px;
  }

  .mobile-back {
    display: grid;
  }

  .desktop-collapse {
    display: none;
  }

  .agent-context-bar {
    height: 48px;
  }

  .agent-tabs {
    height: 43px;
  }

  .agent-stream {
    padding-right: 12px;
    padding-left: 12px;
  }

  .agent-composer {
    min-height: 116px;
    padding-bottom: max(8px, env(safe-area-inset-bottom));
  }

  .settings-view,
  .run-view {
    padding-bottom: 10px;
  }

  .mcp-fields {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
