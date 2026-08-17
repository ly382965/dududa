<script setup lang="ts">
import {
  Activity,
  ArrowLeft,
  Bot,
  Check,
  ChevronDown,
  CircleStop,
  Clock3,
  Gauge,
  Hash,
  MessageSquareText,
  Plus,
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

import type {
  InternalTestAdaptiveSetting,
  InternalTestAgentCatalog,
  InternalTestAgentPolicy,
  InternalTestAnswerProfile,
  InternalTestEffectiveSelection,
  InternalTestPluginMode,
  InternalTestReasoningLevel,
  InternalTestSelectionMode,
  InternalTestTier,
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

type AdaptiveAxis = 'modelTier' | 'reasoning' | 'answerProfile'

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
])

const runTier = computed(() => props.run?.effectiveSelection?.modelTier ?? props.run?.modelTier)
const runReasoning = computed(() => props.run?.effectiveSelection?.reasoning ?? props.run?.reasoning)
const runAnswerProfile = computed(() => props.run?.effectiveSelection?.answerProfile ?? props.run?.answerProfile)
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
          <span>{{ contextMessages }} 条上下文</span>
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
        <div class="context-chip"><Hash :size="12" />{{ conversation?.name }}<span>最近 {{ contextMessages }} 条</span></div>
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
          <div><MessageSquareText :size="14" /><span><small>上下文</small><strong>{{ run.contextMessages }} 条</strong></span></div>
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
        <div><span>会话配置</span><h3>{{ conversation?.name }}</h3></div>
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
          <div v-if="catalog?.plugins.length" class="plugin-list">
            <article v-for="plugin in catalog.plugins" :key="plugin.id" class="plugin-row" :class="{ unavailable: !plugin.available }">
              <div>
                <span class="plugin-title">
                  <strong>{{ plugin.displayName }}</strong>
                  <small :class="plugin.available ? 'available' : 'unavailable'">{{ plugin.available ? '可用' : '不可用' }}</small>
                </span>
                <p>{{ plugin.description }}</p>
                <em v-if="!plugin.available">{{ plugin.unavailableReason || '当前 Runtime 未接通该能力' }}</em>
              </div>
              <select
                :value="policy.plugins[plugin.id] ?? 'off'"
                :disabled="!policyEditable"
                :aria-label="`${plugin.displayName} 使用模式`"
                @change="updatePluginMode(plugin.id, ($event.target as HTMLSelectElement).value as InternalTestPluginMode)"
              >
                <option
                  v-for="mode in pluginModes"
                  :key="mode"
                  :value="mode"
                  :disabled="!plugin.available && mode !== 'off'"
                >
                  {{ pluginModeLabels[mode] }}
                </option>
              </select>
            </article>
          </div>
          <div v-else class="empty-catalog">当前 Catalog 没有已登记插件</div>
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
  grid-template-columns: minmax(0, 1fr) 92px;
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

.plugin-title small {
  flex: 0 0 auto;
  border-radius: 4px;
  padding: 2px 4px;
  font-size: 7px;
}

.plugin-title small.available {
  color: var(--success-strong);
  background: var(--success-soft);
}

.plugin-title small.unavailable {
  color: var(--warning-strong);
  background: var(--warning-soft);
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
}
</style>
