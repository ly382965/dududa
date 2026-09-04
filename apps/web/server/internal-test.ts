import { randomUUID } from 'node:crypto'
import { appendFile, mkdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname, isAbsolute, resolve } from 'node:path'

import dududaPersona from '../../../configs/personas/registry-v1/dududa.json'
import {
  DududaRuntimePreviewClientError,
  type DududaRuntimePreviewClient,
  type DududaRuntimePreviewResult,
} from './dududa-runtime'

export const INTERNAL_TEST_EVIDENCE_MODE = 'private_silver_shadow' as const

const DEFAULT_TIER_MODELS = {
  haiku: 'gpt-5.6-luna',
  sonnet: 'gpt-5.6-terra',
  opus: 'gpt-5.6-sol',
} as const satisfies Record<ModelTier, string>
const PROFILE_TOKEN_LIMITS = {
  short: 220,
  medium: 600,
  long: 1_200,
} as const
const SELECTION_MODES = ['adaptive', 'preferred', 'locked'] as const
const REASONING_LEVELS = ['low', 'medium', 'high'] as const
const PLUGIN_MODES = ['off', 'auto', 'on', 'locked'] as const
const REPLY_INTENSITIES = ['quiet', 'normal', 'active'] as const
const CONTEXT_LENGTHS = ['compact', 'standard', 'extended'] as const
const GROUP_CHAT_STYLES = ['restrained', 'natural', 'lively', 'technical'] as const
const CONTEXT_BUDGETS = {
  compact: { messageLimit: 12, characterLimit: 6_000 },
  standard: { messageLimit: 30, characterLimit: 18_000 },
  extended: { messageLimit: 100, characterLimit: 36_000 },
} as const satisfies Record<ContextLength, { messageLimit: number; characterLimit: number }>
const PROACTIVE_TALK_LIMITS = {
  probabilityPercent: { minimum: 0, maximum: 100, step: 1 },
  cooldownSeconds: { minimum: 5, maximum: 1_800, step: 5 },
  maximumPerHour: { minimum: 1, maximum: 500, step: 1 },
} as const

export type ModelTier = 'haiku' | 'sonnet' | 'opus'
export type AnswerProfile = keyof typeof PROFILE_TOKEN_LIMITS
export type SelectionMode = typeof SELECTION_MODES[number]
export type ReasoningLevel = typeof REASONING_LEVELS[number]
export type PluginMode = typeof PLUGIN_MODES[number]
export type ReplyIntensity = typeof REPLY_INTENSITIES[number]
export type ContextLength = typeof CONTEXT_LENGTHS[number]
export type GroupChatStyle = typeof GROUP_CHAT_STYLES[number]
type ConversationType = 'group' | 'private'
type FeedbackVerdict = 'accepted' | 'rejected' | 'needs_review'

export interface AdaptiveSetting<T extends string> {
  mode: SelectionMode
  preferred: T
  allowed: T[]
}

export interface InternalTestAgentScope {
  accountId: string
  conversationId: string
}

export interface ProactiveTalkSettings {
  probabilityPercent: number
  cooldownSeconds: number
  maximumPerHour: number
}

export interface InternalTestAgentPolicyDefaults {
  enabled: boolean
  modelTier: AdaptiveSetting<ModelTier>
  reasoning: AdaptiveSetting<ReasoningLevel>
  answerProfile: AdaptiveSetting<AnswerProfile>
  replyIntensity: AdaptiveSetting<ReplyIntensity>
  contextLength: AdaptiveSetting<ContextLength>
  groupChatStyle: AdaptiveSetting<GroupChatStyle>
  proactiveTalk: ProactiveTalkSettings
  plugins: Record<string, PluginMode>
}

export interface InternalTestAgentPolicy extends InternalTestAgentPolicyDefaults {
  schemaVersion: 1
  scope: InternalTestAgentScope
  updatedAt?: string
}

export interface InternalTestCatalogModel {
  id: string
  tier: ModelTier
  displayName: string
  available: boolean
  modalities: Array<'text'>
  reasoningLevels: ReasoningLevel[]
  unavailableReason?: string
}

export interface InternalTestCatalogPlugin {
  id: string
  displayName: string
  kind: 'mcp' | 'image_generation' | 'readonly_query' | 'social_automation'
  installed: boolean
  available: boolean
  builtIn?: boolean
  policyManaged: boolean
  requiredRole?: 'super_admin' | 'admin'
  executionRole?: 'admin'
  runtimeTarget: 'web_agent' | 'astrbot'
  runtimeReadiness: 'online' | 'configured' | 'unavailable'
  executionKind: 'agent_capability' | 'command_auto_reply' | 'passive_behavior'
  description: string
  unavailableReason?: string
  model?: string
}

export interface InternalTestAgentCatalog {
  agent: {
    id: 'dududa'
    displayName: string
    consoleRole?: 'super_admin'
    executionRole?: 'admin'
  }
  selectionModes: SelectionMode[]
  pluginModes: PluginMode[]
  models: InternalTestCatalogModel[]
  reasoningLevels: ReasoningLevel[]
  answerProfiles: AnswerProfile[]
  replyIntensities: ReplyIntensity[]
  contextLengths: Array<{
    id: ContextLength
    messageLimit: number
    characterLimit: number
  }>
  groupChatStyles: GroupChatStyle[]
  proactiveTalkLimits: typeof PROACTIVE_TALK_LIMITS
  proactiveFrequencies?: Array<{
    id: 'low' | 'normal' | 'high'
    probability: number
    cooldownSeconds: number
    maximumPerHour: number
  }>
  replyIntensityNotice: string
  plugins: InternalTestCatalogPlugin[]
  policyDefaults: InternalTestAgentPolicyDefaults
}

export interface InternalTestEffectivePlugin {
  mode: PluginMode
  available: boolean
  eligible: boolean
  selectedForRun: boolean
  applicable: boolean
  triggerMatched: boolean
  runtimeTarget: InternalTestCatalogPlugin['runtimeTarget']
  runtimeReadiness: InternalTestCatalogPlugin['runtimeReadiness']
  selectionReason: 'unavailable' | 'off' | 'not_applicable' | 'trigger_matched'
}

export interface InternalTestEffectiveSelection {
  scope: InternalTestAgentScope
  policySource: 'default' | 'saved'
  modelTier: ModelTier
  model: string
  reasoning: ReasoningLevel
  answerProfile: AnswerProfile
  replyIntensity: ReplyIntensity
  contextLength: ContextLength
  groupChatStyle: GroupChatStyle
  contextUsage: InternalTestContextUsage
  plugins: Record<string, InternalTestEffectivePlugin>
}

export interface InternalTestContextUsage {
  messageLimit: number
  characterLimit: number
  messagesRead: number
  charactersRead: number
}

export interface InternalTestStatus {
  available: boolean
  evidenceMode: typeof INTERNAL_TEST_EVIDENCE_MODE
  outputEnabled: false
  providerConfigured: boolean
  sampleCount: number
  modelMapping: Record<ModelTier, string>
  generatedAt?: string
  warnings: string[]
}

export interface InternalTestSamplesQuery {
  q?: string
  bucket?: string
  complexity?: string
  profile?: string
  tools?: string
  offset?: string
  limit?: string
}

export interface InternalTestSamplesPage {
  items: Record<string, unknown>[]
  total: number
  offset: number
  limit: number
}

export interface InternalTestProgress {
  total: number
  evaluated: number
  pending: number
  accepted: number
  rejected: number
  needsReview: number
}

export interface InternalTestCandidate {
  runId: string
  windowId: string
  candidate: string
  tier: ModelTier
  model: string
  answerProfile: AnswerProfile
  latencyMs: number
  generatedAt: string
  evidenceMode: typeof INTERNAL_TEST_EVIDENCE_MODE
  providerCalls: 1
  outputCalls: 0
  memoryWrites: 0
  toolCalls: 0
}

export interface InternalTestAgentStatus {
  readinessReason?: string
  checkedAt?: string
  available: boolean
  providerConfigured: boolean
  outputEnabled: false
  modelMapping: Record<ModelTier, string>
  runtimeControls: {
    passiveAutoReply: {
      actualEnabled: boolean
      state: 'enabled' | 'disabled'
      rolloutMode: 'off' | 'shadow' | 'canary'
      deliveryEnabled: boolean
      killSwitch: boolean
      summary: string
    }
    proactiveGroupParticipation: {
      actualEnabled: boolean
      state: 'enabled' | 'disabled'
      stage: 'proactive_canary' | 'probe_shadow'
      deliveryEnabled: boolean
      summary: string
    }
  }
  warnings: string[]
}

export interface InternalTestAgentResponse {
  runId: string
  candidate: string
  tier: ModelTier
  model: string
  reasoning: ReasoningLevel
  answerProfile: AnswerProfile
  replyIntensity: ReplyIntensity
  contextLength: ContextLength
  groupChatStyle: GroupChatStyle
  contextUsage: InternalTestContextUsage
  effectiveSelection: InternalTestEffectiveSelection
  reasonCodes: string[]
  latencyMs: number
  generatedAt: string
  outputCalls: 0
  memoryWrites: 0
  toolCalls: number
  runtimePath: 'dududa_2_preview' | 'candidate_fallback'
}

export interface InternalTestFeedbackResult {
  ok: true
  feedbackId: string
  progress: InternalTestProgress
}

export interface InternalTestGateway {
  status(): Promise<InternalTestStatus>
  samples(query: InternalTestSamplesQuery): Promise<InternalTestSamplesPage>
  progress(): Promise<InternalTestProgress>
  generate(body: Record<string, unknown>): Promise<InternalTestCandidate>
  agentStatus(): Promise<InternalTestAgentStatus>
  agentCatalog(): Promise<InternalTestAgentCatalog>
  agentConfig(query: Record<string, unknown>): Promise<InternalTestAgentPolicy>
  saveAgentConfig(body: Record<string, unknown>): Promise<InternalTestAgentPolicy>
  respond(body: Record<string, unknown>): Promise<InternalTestAgentResponse>
  feedback(body: Record<string, unknown>): Promise<InternalTestFeedbackResult>
}

export class InternalTestError extends Error {
  constructor(message: string, readonly status = 400) {
    super(message)
  }
}

interface DemoProjection {
  generated_at?: string
  warnings?: unknown
  windows?: unknown
}

interface LoadedProjection {
  generatedAt?: string
  warnings: string[]
  windows: Record<string, unknown>[]
}

interface PrivateProviderConfig {
  baseUrl: string
  apiKey: string
}

export interface FileInternalTestGatewayOptions {
  dataRoot?: string
  /** Formal Agent APIs share policy/preview logic, never corpus or personal credentials. */
  runtimeOnly?: boolean
  feedbackPath?: string
  policyPath?: string
  codexConfigPath?: string
  authPath?: string
  runtimeConfigPath?: string
  runtimeStatusPath?: string
  providerName?: string
  providerBaseUrl?: string
  providerApiKey?: string
  providerTimeoutMs?: number
  models?: Partial<Record<ModelTier, string>>
  fetchImpl?: typeof fetch
  now?: () => Date
  runtimePreview?: DududaRuntimePreviewClient
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function objectValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function boundedInteger(value: string | undefined, fallback: number, minimum: number, maximum: number): number {
  const parsed = Number(value)
  return Number.isInteger(parsed) ? Math.min(maximum, Math.max(minimum, parsed)) : fallback
}

function labelFrom(sample: Record<string, unknown>, key: string): unknown {
  const silver = objectValue(sample.silver)
  if (silver && key in silver) return silver[key]
  return objectValue(objectValue(sample.student)?.[key])?.label
}

function sampleAnswerProfile(sample: Record<string, unknown>): AnswerProfile {
  const raw = stringValue(labelFrom(sample, 'answer_profile'))?.toLowerCase()
  return raw === 'short' || raw === 'medium' || raw === 'long' ? raw : 'medium'
}

function sampleTier(sample: Record<string, unknown>): ModelTier {
  const tier = stringValue(objectValue(sample.tier_preview)?.selected_tier)?.toLowerCase()
  if (tier === 'haiku' || tier === 'sonnet' || tier === 'opus') return tier
  const complexity = stringValue(labelFrom(sample, 'semantic_complexity'))?.toLowerCase()
  if (complexity === 'low') return 'haiku'
  if (complexity === 'high') return 'opus'
  return 'sonnet'
}

function sampleMatches(sample: Record<string, unknown>, query: InternalTestSamplesQuery): boolean {
  const bucket = query.bucket?.trim()
  if (bucket && bucket !== 'all') {
    const buckets = arrayValue(sample.buckets).map(String)
    if (stringValue(sample.primary_bucket) !== bucket && !buckets.includes(bucket)) return false
  }
  const complexity = query.complexity?.trim()
  if (complexity && complexity !== 'all' && String(labelFrom(sample, 'semantic_complexity')) !== complexity) return false
  const profile = query.profile?.trim()
  if (profile && profile !== 'all' && String(labelFrom(sample, 'answer_profile')) !== profile) return false
  const tools = query.tools?.trim()
  if (tools && tools !== 'all') {
    const expected = tools === 'true' || tools === 'yes' || tools === '1'
    if (Boolean(labelFrom(sample, 'need_tools')) !== expected) return false
  }
  const needle = query.q?.trim().toLowerCase()
  return !needle || JSON.stringify(sample).toLowerCase().includes(needle)
}

function unquoteToml(value: string): string | undefined {
  const match = /^\s*["'](.*)["']\s*$/.exec(value)
  return match?.[1]?.trim() || undefined
}

function parseCodexProvider(config: string, requestedName?: string): { name: string; baseUrl: string } | undefined {
  let selected = requestedName
  let section = ''
  const values = new Map<string, Map<string, string>>()
  for (const rawLine of config.split(/\r?\n/)) {
    const line = rawLine.replace(/\s+#.*$/, '').trim()
    if (!line) continue
    const sectionMatch = /^\[([^\]]+)]$/.exec(line)
    if (sectionMatch) {
      section = sectionMatch[1]!
      continue
    }
    const assignment = /^([A-Za-z0-9_]+)\s*=\s*(.+)$/.exec(line)
    if (!assignment) continue
    const value = unquoteToml(assignment[2]!)
    if (!value) continue
    if (!section && assignment[1] === 'model_provider' && !selected) selected = value
    if (!values.has(section)) values.set(section, new Map())
    values.get(section)!.set(assignment[1]!, value)
  }
  if (!selected) return undefined
  const baseUrl = values.get(`model_providers.${selected}`)?.get('base_url')
  return baseUrl ? { name: selected, baseUrl } : undefined
}

function providerEndpoint(baseUrl: string): string {
  const base = baseUrl.replace(/\/+$/, '')
  return base.endsWith('/v1') ? `${base}/responses` : `${base}/v1/responses`
}

function outputText(payload: unknown): string | undefined {
  const body = objectValue(payload)
  const direct = stringValue(body?.output_text)
  if (direct) return direct
  for (const output of arrayValue(body?.output)) {
    for (const item of arrayValue(objectValue(output)?.content)) {
      const content = objectValue(item)
      if (content?.type === 'output_text') {
        const text = stringValue(content.text)
        if (text) return text
      }
    }
  }
  return undefined
}

function contextFor(sample: Record<string, unknown>): string {
  const lines = arrayValue(sample.messages)
    .map(objectValue)
    .filter((message): message is Record<string, unknown> => Boolean(message))
    .map((message) => `${stringValue(message.sender_ref) ?? 'anonymous'}：${stringValue(message.text) ?? ''}`)
  return lines.join('\n').slice(-18_000)
}

function generationInstructions(
  profile: AnswerProfile,
  conversationType: ConversationType,
  groupChatStyle: GroupChatStyle = 'natural',
): string {
  const style = profile === 'short'
    ? '使用简短自然的日常回复，通常一到三句。'
    : profile === 'long'
      ? '可以完整解释观点和推理，但保持群聊可读性，不写空泛套话。'
      : '给出信息充分但不过度展开的中等长度回复。'
  const channelRule = dududaPersona.channel_rules[conversationType]
  const emojiBudget = Math.min(dududaPersona.voice.emoji_budget, channelRule.emoji_budget)
  const channelBehavior = conversationType === 'group'
    ? '像群成员一样自然接住当前话题：默认简洁，不抢话，不逐条复述已有聊天；只有问题确实需要时才展开。'
    : '专注回应对方当前的问题和情绪，保持自然、耐心，不把简单交流写成正式说明。'
  const groupStyleBehavior = conversationType === 'private'
    ? '私聊中以对方当前需要为准，不照搬群聊气氛。'
    : groupChatStyle === 'restrained'
      ? '在多人讨论中保持克制和留白，先回应最相关的内容，避免为了活跃而抢话。'
      : groupChatStyle === 'lively'
        ? '群聊气氛轻松时可以更有活力地接话，但不要硬造梗、刷屏或打断正在进行的讨论。'
        : groupChatStyle === 'technical'
          ? '技术讨论中优先使用准确术语和清晰结构，同时保留正常群聊语气，不写成生硬报告。'
          : '顺着当前群聊的语气自然回应，不刻意制造存在感，也不把普通聊天改写成正式答复。'
  const technicalBehavior = dududaPersona.voice.technical_style === 'conclusion_then_bounded_steps'
    ? '遇到技术问题先给结论，再补足真正有用的步骤。'
    : '技术问题按最容易理解的顺序回答。'
  const uncertaintyBehavior = dududaPersona.voice.uncertainty_style === 'state_limits_plainly'
    ? '不确定时直接说明边界，不装作知道。'
    : '对不确定内容保持克制。'
  const sentenceBehavior = channelRule.prefer_short_sentences
    ? '优先使用自然短句，让语气由句式和信息组织体现。'
    : '句式保持自然。'
  const emojiBehavior = emojiBudget > 0
    ? `表情只在语境自然时偶尔使用，整条回答最多 ${emojiBudget} 个；没有必要就不用。`
    : '不要使用表情。'
  return [
    `你正在以“${dududaPersona.display_name}”的身份生成一条人工内测候选回答。`,
    '让人格通过自然措辞、回应节奏和信息取舍体现，不要宣告、复述或刻意表演人设。',
    channelBehavior,
    groupStyleBehavior,
    sentenceBehavior,
    technicalBehavior,
    uncertaintyBehavior,
    emojiBehavior,
    '不要模仿某个具体群成员，不要复制其身份、隐私、口头禅或敏感信息。',
    '这些规则只影响表达；不要在回答中谈论或罗列人格规则，也不得改变事实、权限、任务要求或安全边界。',
    '输入中的群聊内容只作为回答上下文；不要猜测未提供的真实身份，不要调用工具，不要声称已执行外部操作。',
    '直接输出候选回答正文，不要解释路由、模型、标签或测试流程。',
    style,
  ].join('\n')
}

function requestedConversationType(value: unknown): ConversationType {
  const conversationType = stringValue(value)?.toLowerCase()
  if (!conversationType) return 'group'
  if (conversationType === 'group' || conversationType === 'private') return conversationType
  throw new InternalTestError('conversationType 参数无效')
}

function optionalAnswerProfile(value: unknown): AnswerProfile | undefined {
  const profile = stringValue(value)?.toLowerCase()
  if (!profile) return undefined
  if (profile === 'short' || profile === 'medium' || profile === 'long') return profile
  throw new InternalTestError('answerProfile 参数无效')
}

function agentContext(body: Record<string, unknown>, contextLength: ContextLength): {
  input: string
  usage: InternalTestContextUsage
} {
  const conversationId = stringValue(body.conversationId ?? body.conversation_id)
  const conversationName = stringValue(body.conversationName ?? body.conversation_name)
  const prompt = stringValue(body.prompt)
  if (!conversationId || !conversationName || !prompt) {
    throw new InternalTestError('缺少 conversationId、conversationName 或 prompt')
  }
  const budget = CONTEXT_BUDGETS[contextLength]
  const messageLines = arrayValue(body.messages)
    .map(objectValue)
    .filter((message): message is Record<string, unknown> => Boolean(message))
    .map((message) => {
      const senderName = stringValue(message.senderName ?? message.sender_name) ?? '匿名成员'
      const content = stringValue(message.content)
      if (!content) return undefined
      return `${senderName}${message.mine === true ? '（嘟嘟哒）' : ''}：${content}`
    })
    .filter((line): line is string => Boolean(line))
    .slice(-budget.messageLimit)
  const selectedLines: string[] = []
  let remainingCharacters = budget.characterLimit
  for (let index = messageLines.length - 1; index >= 0 && remainingCharacters > 0; index -= 1) {
    const separatorLength = selectedLines.length ? 1 : 0
    const available = remainingCharacters - separatorLength
    if (available <= 0) break
    const line = messageLines[index]!
    const selected = line.length > available ? line.slice(-available) : line
    selectedLines.unshift(selected)
    remainingCharacters -= selected.length + separatorLength
    if (selected.length < line.length) break
  }
  const messages = selectedLines.join('\n')
  return {
    input: [
      `当前会话：${conversationName}`,
      messages ? `最近消息：\n${messages}` : '最近消息：（无）',
      `操作员指令：\n${prompt}`,
    ].join('\n\n'),
    usage: {
      messageLimit: budget.messageLimit,
      characterLimit: budget.characterLimit,
      messagesRead: selectedLines.length,
      charactersRead: messages.length,
    },
  }
}

function agentScope(value: Record<string, unknown>, requireAccount = true): InternalTestAgentScope {
  const nested = objectValue(value.scope)
  const accountId = stringValue(nested?.accountId ?? nested?.account_id ?? value.accountId ?? value.account_id)
  const conversationId = stringValue(
    nested?.conversationId ?? nested?.conversation_id ?? value.conversationId ?? value.conversation_id,
  )
  if ((!accountId && requireAccount) || !conversationId) {
    throw new InternalTestError('缺少 accountId 或 conversationId')
  }
  if ((accountId?.length ?? 0) > 256 || conversationId.length > 256) {
    throw new InternalTestError('accountId 或 conversationId 过长')
  }
  return { accountId: accountId ?? 'default', conversationId }
}

function policyKey(scope: InternalTestAgentScope): string {
  return `${encodeURIComponent(scope.accountId)}::${encodeURIComponent(scope.conversationId)}`
}

function defaultPolicyDefaults(): InternalTestAgentPolicyDefaults {
  return {
    enabled: true,
    modelTier: {
      mode: 'adaptive',
      preferred: 'sonnet',
      allowed: ['haiku', 'sonnet', 'opus'],
    },
    reasoning: {
      mode: 'adaptive',
      preferred: 'medium',
      allowed: ['low', 'medium', 'high'],
    },
    answerProfile: {
      mode: 'adaptive',
      preferred: 'medium',
      allowed: ['short', 'medium', 'long'],
    },
    replyIntensity: {
      mode: 'adaptive',
      preferred: 'normal',
      allowed: ['quiet', 'normal', 'active'],
    },
    contextLength: {
      mode: 'adaptive',
      preferred: 'standard',
      allowed: ['compact', 'standard', 'extended'],
    },
    groupChatStyle: {
      mode: 'adaptive',
      preferred: 'natural',
      allowed: ['restrained', 'natural', 'lively', 'technical'],
    },
    proactiveTalk: {
      probabilityPercent: 2,
      cooldownSeconds: 1_800,
      maximumPerHour: 1,
    },
    plugins: {
      'icourse.read': 'off',
      'notifai.read': 'off',
      'ustc.young.read': 'off',
      'ustc.curriculum.read': 'off',
      'ustc.academic.read': 'off',
      'ustc.shuttle.read': 'off',
      'image.generate.gpt-image-2': 'off',
      'social.proactive_talk': 'off',
      'social.reread.auto': 'off',
      'sub2api.auto_query': 'off',
    },
  }
}

function catalogPlugins(runtimeReady = false): InternalTestCatalogPlugin[] {
  return [
    {
      id: 'icourse.read',
      displayName: 'iCourse 评课社区',
      kind: 'mcp',
      installed: true,
      available: true,
      builtIn: true,
      policyManaged: true,
      requiredRole: 'super_admin',
      executionRole: 'admin',
      runtimeTarget: 'astrbot',
      runtimeReadiness: runtimeReady ? 'online' : 'configured',
      executionKind: 'agent_capability',
      description: '复用现有匿名 iCourse 服务查询课程与公开评价；超级管理员可在 MCP 工作台直接调用。',
    },
    {
      id: 'notifai.read',
      displayName: 'USTC 校园通知',
      kind: 'mcp',
      installed: true,
      available: true,
      builtIn: true,
      policyManaged: true,
      requiredRole: 'super_admin',
      executionRole: 'admin',
      runtimeTarget: 'astrbot',
      runtimeReadiness: runtimeReady ? 'online' : 'configured',
      executionKind: 'agent_capability',
      description: '通过 NotifAI 查询公开校园通知、截止提醒、通知日历、来源分类和统计；只读，不保存通知正文。',
    },
    {
      id: 'ustc.young.read',
      displayName: 'USTC 二课',
      kind: 'mcp',
      installed: true,
      available: true,
      builtIn: true,
      policyManaged: true,
      requiredRole: 'super_admin',
      executionRole: 'admin',
      runtimeTarget: 'astrbot',
      runtimeReadiness: runtimeReady ? 'online' : 'configured',
      executionKind: 'agent_capability',
      description: '2.0 Runtime 通过固定版本 pyustc 查询二课公共活动；不提供用户登录或个人活动能力，上游连接使用仓库外 CAS SecretRef。',
    },
    {
      id: 'ustc.curriculum.read',
      displayName: 'USTC 培养方案研究',
      kind: 'mcp',
      installed: true,
      available: true,
      builtIn: true,
      policyManaged: true,
      requiredRole: 'super_admin',
      executionRole: 'admin',
      runtimeTarget: 'astrbot',
      runtimeReadiness: runtimeReady ? 'online' : 'configured',
      executionKind: 'agent_capability',
      description: '查询 docs.mmdustc.top/curriculum 的公开研究快照；不是实时教务数据，不能直接用于毕业审核。',
    },
    {
      id: 'ustc.academic.read',
      displayName: 'USTC 教务处',
      kind: 'mcp',
      installed: true,
      available: true,
      builtIn: true,
      policyManaged: true,
      requiredRole: 'super_admin',
      executionRole: 'admin',
      runtimeTarget: 'astrbot',
      runtimeReadiness: runtimeReady ? 'online' : 'configured',
      executionKind: 'agent_capability',
      description: '查询学期、开课、考试和教学日历；支持 2.0 自然语言调用和超级管理员直接调用。',
    },
    {
      id: 'ustc.shuttle.read',
      displayName: 'USTC 校车',
      kind: 'readonly_query',
      installed: true,
      available: true,
      builtIn: true,
      policyManaged: true,
      requiredRole: 'super_admin',
      executionRole: 'admin',
      runtimeTarget: 'astrbot',
      runtimeReadiness: runtimeReady ? 'online' : 'configured',
      executionKind: 'agent_capability',
      description: '本地版本化时刻表插件；查询校园、高新校区和太湖路园区班次，不在运行时抓取网页。',
    },
    {
      id: 'image.generate.gpt-image-2',
      displayName: 'GPT Image 2 图片生成',
      kind: 'image_generation',
      installed: true,
      available: false,
      builtIn: true,
      policyManaged: true,
      runtimeTarget: 'web_agent',
      runtimeReadiness: 'unavailable',
      executionKind: 'agent_capability',
      description: '独立的图片生成与编辑能力，不用于图片理解。',
      unavailableReason: 'gpt-image-2 图片生成执行链尚未接入当前 Runtime。',
      model: 'gpt-image-2',
    },
    {
      id: 'social.proactive_talk',
      displayName: 'Dududa 2.0 自动搭话',
      kind: 'social_automation',
      installed: true,
      available: true,
      builtIn: true,
      policyManaged: true,
      requiredRole: 'super_admin',
      executionRole: 'admin',
      runtimeTarget: 'astrbot',
      runtimeReadiness: runtimeReady ? 'online' : 'configured',
      executionKind: 'passive_behavior',
      description: '读取有界群聊历史并通过 2.0 Runtime 生成 SHORT 群级接话；频率、冷却和每小时上限由独立主动频率控制。',
    },
    {
      id: 'social.reread.auto',
      displayName: '自动复读',
      kind: 'social_automation',
      installed: true,
      available: true,
      policyManaged: true,
      requiredRole: 'super_admin',
      executionRole: 'admin',
      runtimeTarget: 'astrbot',
      runtimeReadiness: 'configured',
      executionKind: 'passive_behavior',
      description: '复用 Dududa 1.0 的确定性群消息复读；WebUI 设置 Scope 初值，Bot 以普通管理员身份执行。',
    },
    {
      id: 'sub2api.auto_query',
      displayName: '/sub2api 自动查询',
      kind: 'readonly_query',
      installed: true,
      available: true,
      builtIn: true,
      policyManaged: true,
      requiredRole: 'super_admin',
      executionRole: 'admin',
      runtimeTarget: 'astrbot',
      runtimeReadiness: 'configured',
      executionKind: 'command_auto_reply',
      description: '复用 Dududa 1.0 的确定性 /sub2api 只读查询；WebUI 设置 Scope 初值，Bot 以普通管理员身份执行。',
    },
  ]
}

function currentAgentRuntimeControls(
  config: Record<string, unknown> = {},
  runtimeReady?: boolean,
): InternalTestAgentStatus['runtimeControls'] {
  const requestedMode = stringValue(config.rollout_mode)?.toLowerCase()
  const rolloutMode = requestedMode === 'shadow' || requestedMode === 'canary' ? requestedMode : 'off'
  const deliveryEnabled = config.rollout_delivery_enabled === true
  const killSwitch = config.rollout_kill_switch !== false
  const runtimeEnabled = config.runtime_enabled === true
  const configuredEnabled = runtimeEnabled && rolloutMode === 'canary' && deliveryEnabled && !killSwitch
  const actualEnabled = configuredEnabled && runtimeReady !== false
  const proactiveEnabled = actualEnabled && config.proactive_talk_enabled === true
  const configuredGroups = Array.isArray(config.rollout_allowlisted_groups)
    ? config.rollout_allowlisted_groups
    : []
  const allGroups = config.all_groups === true || configuredGroups.includes('*')
  return {
    passiveAutoReply: {
      actualEnabled,
      state: actualEnabled ? 'enabled' : 'disabled',
      rolloutMode,
      deliveryEnabled,
      killSwitch,
      summary: actualEnabled
        ? allGroups
          ? 'Dududa 2.0 已接管所有群内明确 @Bot 的受支持文本；旧 AstrBot Agent 不再回退接管。'
          : 'Dududa 2.0 已接管白名单群内明确 @Bot 的受支持文本；旧 AstrBot Agent 不再回退接管。'
        : configuredEnabled && runtimeReady === false
          ? 'Dududa 2.0 配置已开启，但 Runtime Assembly 尚未就绪。'
          : `Dududa 2.0 当前未交付：rollout=${rolloutMode}，delivery=${deliveryEnabled}，kill_switch=${killSwitch}。`,
    },
    proactiveGroupParticipation: {
      actualEnabled: proactiveEnabled,
      state: proactiveEnabled ? 'enabled' : 'disabled',
      stage: proactiveEnabled ? 'proactive_canary' : 'probe_shadow',
      deliveryEnabled: proactiveEnabled,
      summary: proactiveEnabled
        ? 'Dududa 2.0 主动搭话执行器在线；仅对 Scope Policy 明确启用的群生效，自动回复固定为 SHORT。'
        : '主动参与当前只有 S15E Probe Shadow，只生成机会与候选，不发送消息。',
    },
  }
}

function buildAgentCatalog(
  models: Record<ModelTier, string>,
  providerConfigured: boolean,
  runtimeReady = false,
): InternalTestAgentCatalog {
  const modelDetails: Array<{ tier: ModelTier; label: string }> = [
    { tier: 'haiku', label: '轻量' },
    { tier: 'sonnet', label: '中等' },
    { tier: 'opus', label: '专业' },
  ]
  return {
    agent: {
      id: 'dududa',
      displayName: dududaPersona.display_name,
      consoleRole: 'super_admin',
      executionRole: 'admin',
    },
    selectionModes: [...SELECTION_MODES],
    pluginModes: [...PLUGIN_MODES],
    models: modelDetails.map(({ tier, label }) => ({
      id: models[tier],
      tier,
      displayName: `${label} · ${models[tier]}`,
      available: providerConfigured,
      modalities: ['text'],
      reasoningLevels: [...REASONING_LEVELS],
      ...(!providerConfigured ? { unavailableReason: 'Provider 尚未配置。' } : {}),
    })),
    reasoningLevels: [...REASONING_LEVELS],
    answerProfiles: ['short', 'medium', 'long'],
    replyIntensities: [...REPLY_INTENSITIES],
    contextLengths: CONTEXT_LENGTHS.map((id) => ({ id, ...CONTEXT_BUDGETS[id] })),
    groupChatStyles: [...GROUP_CHAT_STYLES],
    proactiveTalkLimits: PROACTIVE_TALK_LIMITS,
    // Keep tabs loaded before the numeric-control rollout usable until refresh.
    proactiveFrequencies: [
      { id: 'low', probability: 0.02, cooldownSeconds: 1_800, maximumPerHour: 1 },
      { id: 'normal', probability: 0.08, cooldownSeconds: 600, maximumPerHour: 3 },
      { id: 'high', probability: 0.20, cooldownSeconds: 180, maximumPerHour: 8 },
    ],
    replyIntensityNotice: '本轮参与倾向；不会替代独立的主动搭话频率、冷却和每小时上限。',
    plugins: catalogPlugins(runtimeReady),
    policyDefaults: defaultPolicyDefaults(),
  }
}

function selectionMode(value: unknown, fallback: SelectionMode): SelectionMode {
  const mode = stringValue(value)?.toLowerCase()
  if (!mode) return fallback
  if (SELECTION_MODES.includes(mode as SelectionMode)) return mode as SelectionMode
  throw new InternalTestError('SelectionMode 参数无效')
}

function adaptiveSetting<T extends string>(
  value: unknown,
  fallback: AdaptiveSetting<T>,
  domain: readonly T[],
  label: string,
): AdaptiveSetting<T> {
  if (value === undefined) return { ...fallback, allowed: [...fallback.allowed] }
  const object = objectValue(value)
  if (!object) throw new InternalTestError(`${label} 必须包含 mode、preferred 和 allowed`)
  const preferred = stringValue(object.preferred) as T | undefined
  const allowed = arrayValue(object.allowed)
    .map(stringValue)
    .filter((item): item is string => Boolean(item)) as T[]
  if (!preferred || !domain.includes(preferred)) throw new InternalTestError(`${label}.preferred 参数无效`)
  if (!allowed.length || allowed.some((item) => !domain.includes(item))) {
    throw new InternalTestError(`${label}.allowed 参数无效`)
  }
  const uniqueAllowed = [...new Set(allowed)]
  if (!uniqueAllowed.includes(preferred)) throw new InternalTestError(`${label}.allowed 必须包含 preferred`)
  return {
    mode: selectionMode(object.mode, fallback.mode),
    preferred,
    allowed: uniqueAllowed,
  }
}

function pluginMode(value: unknown): PluginMode {
  const mode = stringValue(value)?.toLowerCase()
  if (mode && PLUGIN_MODES.includes(mode as PluginMode)) return mode as PluginMode
  throw new InternalTestError('插件 mode 参数无效')
}

function isSub2ApiCommand(value: unknown): boolean {
  const command = stringValue(value)
  return Boolean(command && /^\/(?:sub2api|sub2|用量)(?:\s|$)/iu.test(command))
}

function hasConsecutiveGroupRepeat(body: Record<string, unknown>): boolean {
  const messages = arrayValue(body.messages)
    .map(objectValue)
    .filter((message): message is Record<string, unknown> => Boolean(message))
    .filter((message) => message.mine !== true && message.selfAuthored !== true && message.self_authored !== true)
    .map((message) => stringValue(message.content ?? message.text))
    .filter((content): content is string => Boolean(content))
  if (messages.length < 2) return false
  return messages.at(-1) === messages.at(-2)
}

function pluginRunSelection(
  plugin: InternalTestCatalogPlugin,
  mode: PluginMode,
  body: Record<string, unknown>,
  conversationType: ConversationType,
): Pick<
  InternalTestEffectivePlugin,
  'eligible' | 'selectedForRun' | 'applicable' | 'triggerMatched' | 'selectionReason'
> & { reasonCode: string } {
  if (!plugin.available) {
    return {
      eligible: false,
      selectedForRun: false,
      applicable: false,
      triggerMatched: false,
      selectionReason: 'unavailable',
      reasonCode: `plugin.${plugin.id}.unavailable`,
    }
  }
  if (mode === 'off') {
    return {
      eligible: false,
      selectedForRun: false,
      applicable: false,
      triggerMatched: false,
      selectionReason: 'off',
      reasonCode: `plugin.${plugin.id}.off_by_admin`,
    }
  }
  if (plugin.executionKind === 'command_auto_reply') {
    const matched = isSub2ApiCommand(body.prompt ?? body.command)
    return {
      eligible: true,
      selectedForRun: false,
      applicable: matched,
      triggerMatched: matched,
      selectionReason: matched ? 'trigger_matched' : 'not_applicable',
      reasonCode: matched
        ? `plugin.${plugin.id}.exact_command_trigger_matched_not_executed`
        : `plugin.${plugin.id}.waiting_for_exact_command`,
    }
  }
  if (plugin.executionKind === 'passive_behavior') {
    const matched = conversationType === 'group' && hasConsecutiveGroupRepeat(body)
    return {
      eligible: true,
      selectedForRun: false,
      applicable: matched,
      triggerMatched: matched,
      selectionReason: matched ? 'trigger_matched' : 'not_applicable',
      reasonCode: matched
        ? `plugin.${plugin.id}.group_repeat_trigger_matched_not_executed`
        : `plugin.${plugin.id}.waiting_for_group_repeat`,
    }
  }
  return {
    eligible: true,
    selectedForRun: false,
    applicable: false,
    triggerMatched: false,
    selectionReason: 'not_applicable',
    reasonCode: `plugin.${plugin.id}.eligible_${mode}`,
  }
}

interface TaskChoice<T extends string> {
  value: T
  strong: boolean
  reasonCode: string
}

interface TaskSignals {
  modelTier: TaskChoice<ModelTier>
  reasoning: TaskChoice<ReasoningLevel>
  answerProfile: TaskChoice<AnswerProfile>
  replyIntensity: TaskChoice<ReplyIntensity>
  contextLength: TaskChoice<ContextLength>
  groupChatStyle: TaskChoice<GroupChatStyle>
}

function taskSignals(body: Record<string, unknown>): TaskSignals {
  const prompt = stringValue(body.prompt) ?? ''
  const recent = arrayValue(body.messages)
    .slice(-12)
    .map(objectValue)
    .filter((message): message is Record<string, unknown> => Boolean(message))
    .map((message) => stringValue(message.content) ?? '')
    .join('\n')
  const text = `${recent}\n${prompt}`.trim()
  const complex = /```|架构|设计|调试|排查|代码|实现|证明|推导|论文|研究|评估|权衡|迁移|重构|方案|深入分析|详细分析|完整分析/i.test(text)
    || text.length > 420
    || (text.match(/[？?]/g)?.length ?? 0) >= 3
  const casual = text.length <= 80
    && /^(?:你好|嗨|哈喽|在吗|谢谢|收到|好的|好呀|晚安|早安|哈哈|嘿|嗯+|哦+|行|可以)[呀啊哦呢嘛吗！!。.～~\s]*$/u.test(text)
  const explicitProfile = optionalAnswerProfile(body.answerProfile ?? body.answer_profile)
  const longRequested = /详细|完整|深入|展开|长回答|多讲|逐步|系统地/u.test(prompt)
  const shortRequested = /简短|一句话|短回答|简单说/u.test(prompt)
  const lively = casual && /哈哈|笑死|好耶|太棒|冲[！!]|[！!]{2,}/u.test(text)

  const answerProfile: TaskChoice<AnswerProfile> = explicitProfile
    ? { value: explicitProfile, strong: true, reasonCode: 'answer_profile.request_hint' }
    : longRequested
      ? { value: 'long', strong: true, reasonCode: 'answer_profile.explicit_long_request' }
      : shortRequested || casual
        ? { value: 'short', strong: true, reasonCode: shortRequested ? 'answer_profile.explicit_short_request' : 'answer_profile.casual_exchange' }
        : { value: 'medium', strong: false, reasonCode: 'answer_profile.ordinary_task' }

  if (complex) {
    return {
      modelTier: { value: 'opus', strong: true, reasonCode: 'model.task_complexity_high' },
      reasoning: { value: 'high', strong: true, reasonCode: 'reasoning.task_complexity_high' },
      answerProfile,
      replyIntensity: { value: 'active', strong: true, reasonCode: 'reply_intensity.deep_task' },
      contextLength: { value: 'extended', strong: true, reasonCode: 'context_length.deep_task' },
      groupChatStyle: { value: 'technical', strong: true, reasonCode: 'group_chat_style.technical_task' },
    }
  }
  if (casual) {
    return {
      modelTier: { value: 'haiku', strong: true, reasonCode: 'model.casual_exchange' },
      reasoning: { value: 'low', strong: true, reasonCode: 'reasoning.casual_exchange' },
      answerProfile,
      replyIntensity: { value: 'quiet', strong: true, reasonCode: 'reply_intensity.casual_exchange' },
      contextLength: { value: 'compact', strong: true, reasonCode: 'context_length.casual_exchange' },
      groupChatStyle: lively
        ? { value: 'lively', strong: true, reasonCode: 'group_chat_style.lively_exchange' }
        : { value: 'natural', strong: false, reasonCode: 'group_chat_style.casual_exchange' },
    }
  }
  return {
    modelTier: { value: 'sonnet', strong: false, reasonCode: 'model.ordinary_task' },
    reasoning: { value: 'medium', strong: false, reasonCode: 'reasoning.ordinary_task' },
    answerProfile,
    replyIntensity: { value: 'normal', strong: false, reasonCode: 'reply_intensity.ordinary_task' },
    contextLength: { value: 'standard', strong: false, reasonCode: 'context_length.ordinary_task' },
    groupChatStyle: { value: 'natural', strong: false, reasonCode: 'group_chat_style.ordinary_task' },
  }
}

function effectiveValue<T extends string>(
  axis: string,
  setting: AdaptiveSetting<T>,
  inferred: TaskChoice<T>,
): { value: T; reasonCodes: string[] } {
  if (setting.mode === 'locked') {
    return { value: setting.preferred, reasonCodes: [`${axis}.locked_by_admin`] }
  }
  const canUseInferred = setting.allowed.includes(inferred.value)
  if (setting.mode === 'adaptive' && canUseInferred) {
    return { value: inferred.value, reasonCodes: [`${axis}.adaptive`, inferred.reasonCode] }
  }
  if (setting.mode === 'preferred' && inferred.strong && canUseInferred) {
    return { value: inferred.value, reasonCodes: [`${axis}.preferred_overridden`, inferred.reasonCode] }
  }
  if (!canUseInferred) {
    return {
      value: setting.preferred,
      reasonCodes: [`${axis}.inferred_not_allowed`, `${axis}.preferred_fallback`],
    }
  }
  return { value: setting.preferred, reasonCodes: [`${axis}.preferred_initial`] }
}

function normalizeAgentPolicy(
  value: unknown,
  current: InternalTestAgentPolicy,
  scope: InternalTestAgentScope,
  updatedAt?: string,
): InternalTestAgentPolicy {
  const policy = objectValue(value) ?? {}
  const knownPlugins = new Map(catalogPlugins().map((plugin) => [plugin.id, plugin]))
  const plugins = { ...current.plugins }
  const requestedPlugins = objectValue(policy.plugins)
  if (requestedPlugins) {
    for (const [id, mode] of Object.entries(requestedPlugins)) {
      const plugin = knownPlugins.get(id)
      if (!plugin) throw new InternalTestError(`未知插件: ${id}`)
      const requestedMode = pluginMode(mode)
      if (requestedMode !== 'off' && !plugin.policyManaged) {
        throw new InternalTestError(`插件 ${id} 不允许通过普通 Scope Policy 启用`)
      }
      if (requestedMode !== 'off' && !plugin.available) {
        throw new InternalTestError(`插件 ${id} 当前不可用，不能启用`)
      }
      plugins[id] = requestedMode
    }
  }
  return {
    schemaVersion: 1,
    scope,
    enabled: typeof policy.enabled === 'boolean' ? policy.enabled : current.enabled,
    modelTier: adaptiveSetting(
      policy.modelTier ?? policy.model_tier ?? policy.tier,
      current.modelTier,
      ['haiku', 'sonnet', 'opus'],
      'modelTier',
    ),
    reasoning: adaptiveSetting(policy.reasoning, current.reasoning, REASONING_LEVELS, 'reasoning'),
    answerProfile: adaptiveSetting(
      policy.answerProfile ?? policy.answer_profile,
      current.answerProfile,
      ['short', 'medium', 'long'],
      'answerProfile',
    ),
    replyIntensity: adaptiveSetting(
      policy.replyIntensity ?? policy.reply_intensity,
      current.replyIntensity,
      REPLY_INTENSITIES,
      'replyIntensity',
    ),
    contextLength: adaptiveSetting(
      policy.contextLength ?? policy.context_length,
      current.contextLength,
      CONTEXT_LENGTHS,
      'contextLength',
    ),
    groupChatStyle: adaptiveSetting(
      policy.groupChatStyle ?? policy.group_chat_style,
      current.groupChatStyle,
      GROUP_CHAT_STYLES,
      'groupChatStyle',
    ),
    proactiveTalk: proactiveTalkSettings(
      policy.proactiveTalk ?? policy.proactive_talk,
      current.proactiveTalk,
    ),
    plugins,
    ...(updatedAt ? { updatedAt } : {}),
  }
}

function proactiveTalkSettings(
  value: unknown,
  fallback: ProactiveTalkSettings,
): ProactiveTalkSettings {
  const proactive = objectValue(value)
  if (!proactive) return fallback
  const legacy = legacyProactiveTalkSettings(proactive.frequency)
  return {
    probabilityPercent: proactiveInteger(
      proactive.probabilityPercent,
      legacy?.probabilityPercent ?? fallback.probabilityPercent,
      PROACTIVE_TALK_LIMITS.probabilityPercent,
      'probabilityPercent',
    ),
    cooldownSeconds: proactiveInteger(
      proactive.cooldownSeconds,
      legacy?.cooldownSeconds ?? fallback.cooldownSeconds,
      PROACTIVE_TALK_LIMITS.cooldownSeconds,
      'cooldownSeconds',
    ),
    maximumPerHour: proactiveInteger(
      proactive.maximumPerHour,
      legacy?.maximumPerHour ?? fallback.maximumPerHour,
      PROACTIVE_TALK_LIMITS.maximumPerHour,
      'maximumPerHour',
    ),
  }
}

function legacyProactiveTalkSettings(value: unknown): ProactiveTalkSettings | undefined {
  const frequency = stringValue(value)?.toLowerCase()
  if (frequency === 'low') return { probabilityPercent: 2, cooldownSeconds: 1_800, maximumPerHour: 1 }
  if (frequency === 'normal') return { probabilityPercent: 8, cooldownSeconds: 600, maximumPerHour: 3 }
  if (frequency === 'high') return { probabilityPercent: 20, cooldownSeconds: 180, maximumPerHour: 8 }
  return undefined
}

function proactiveInteger(
  value: unknown,
  fallback: number,
  limits: { minimum: number; maximum: number; step: number },
  label: string,
): number {
  if (value === undefined || value === null) return fallback
  if (
    typeof value !== 'number'
    || !Number.isInteger(value)
    || value < limits.minimum
    || value > limits.maximum
    || (value - limits.minimum) % limits.step !== 0
  ) {
    throw new InternalTestError(`proactiveTalk.${label} 参数无效`)
  }
  return value
}

function feedbackVerdict(value: unknown): FeedbackVerdict {
  const verdict = stringValue(value)?.toLowerCase()
  if (verdict === 'accepted' || verdict === 'accept') return 'accepted'
  if (verdict === 'rejected' || verdict === 'reject') return 'rejected'
  if (verdict === 'needs_review' || verdict === 'needs-review' || verdict === 'review') return 'needs_review'
  throw new InternalTestError('请选择人工评价结果')
}

function rating(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 1 || value > 5) {
    throw new InternalTestError(`${label} 必须是 1 到 5 的整数`)
  }
  return value
}

function feedbackEvaluation(value: unknown): Record<string, unknown> {
  const evaluation = objectValue(value)
  if (!evaluation) throw new InternalTestError('缺少完整的人工评价字段')
  const shouldReply = stringValue(evaluation.shouldReply ?? evaluation.should_reply)?.toLowerCase()
  if (shouldReply !== 'yes' && shouldReply !== 'no' && shouldReply !== 'uncertain') {
    throw new InternalTestError('shouldReply 参数无效')
  }
  return {
    should_reply: shouldReply,
    routing_reasonable: rating(evaluation.routingReasonable ?? evaluation.routing_reasonable, 'routingReasonable'),
    correctness: rating(evaluation.correctness, 'correctness'),
    naturalness: rating(evaluation.naturalness, 'naturalness'),
    group_fit: rating(evaluation.groupFit ?? evaluation.group_fit, 'groupFit'),
    length_fit: rating(evaluation.lengthFit ?? evaluation.length_fit, 'lengthFit'),
  }
}

function feedbackCorrections(value: unknown): Record<string, string> | undefined {
  const corrections = objectValue(value)
  if (!corrections) return undefined
  const semanticComplexity = stringValue(
    corrections.semanticComplexity ?? corrections.semantic_complexity,
  )?.toLowerCase()
  const answerProfile = stringValue(
    corrections.answerProfile ?? corrections.answer_profile,
  )?.toLowerCase()
  const result: Record<string, string> = {}
  if (semanticComplexity === 'low' || semanticComplexity === 'medium' || semanticComplexity === 'high') {
    result.semanticComplexity = semanticComplexity
  }
  if (answerProfile === 'short' || answerProfile === 'medium' || answerProfile === 'long') {
    result.answerProfile = answerProfile
  }
  return Object.keys(result).length ? result : undefined
}

export class FileInternalTestGateway implements InternalTestGateway {
  private readonly demoPath?: string
  private readonly feedbackPath?: string
  private readonly policyPath: string
  private readonly codexConfigPath: string
  private readonly authPath: string
  private readonly runtimeConfigPath?: string
  private readonly runtimeStatusPath?: string
  private readonly fetchImpl: typeof fetch
  private readonly now: () => Date
  private readonly models: Record<ModelTier, string>
  private cache?: { mtimeMs: number; projection: LoadedProjection }
  private policyWrite: Promise<unknown> = Promise.resolve()

  constructor(private readonly options: FileInternalTestGatewayOptions) {
    const dataRoot = stringValue(options.dataRoot)
    if ((!dataRoot && !options.runtimeOnly) || (dataRoot && !isAbsolute(dataRoot))) {
      throw new InternalTestError('DUDUDA_INTERNAL_TEST_DATA_ROOT 必须是私有绝对路径', 503)
    }
    const feedbackPath = stringValue(options.feedbackPath) ?? (dataRoot ? resolve(dataRoot, 'internal-test/feedback.jsonl') : undefined)
    if (feedbackPath && !isAbsolute(feedbackPath)) {
      throw new InternalTestError('DUDUDA_INTERNAL_TEST_FEEDBACK_PATH 必须是绝对路径', 503)
    }
    const policyPath = stringValue(options.policyPath) ?? (dataRoot ? resolve(dataRoot, 'internal-test/agent-policies.json') : undefined)
    if (!policyPath || !isAbsolute(policyPath)) {
      throw new InternalTestError('DUDUDA_INTERNAL_TEST_POLICY_PATH 必须是绝对路径', 503)
    }
    this.demoPath = dataRoot ? resolve(dataRoot, 'demo/index.html') : undefined
    this.feedbackPath = feedbackPath
    this.policyPath = policyPath
    this.codexConfigPath = resolve(options.codexConfigPath ?? resolve(homedir(), '.codex/config.toml'))
    this.authPath = resolve(options.authPath ?? resolve(homedir(), '.codex/auth.json'))
    this.runtimeConfigPath = stringValue(options.runtimeConfigPath)
    this.runtimeStatusPath = stringValue(options.runtimeStatusPath)
    this.fetchImpl = options.fetchImpl ?? fetch
    this.now = options.now ?? (() => new Date())
    this.models = {
      haiku: stringValue(options.models?.haiku) ?? DEFAULT_TIER_MODELS.haiku,
      sonnet: stringValue(options.models?.sonnet) ?? DEFAULT_TIER_MODELS.sonnet,
      opus: stringValue(options.models?.opus) ?? DEFAULT_TIER_MODELS.opus,
    }
  }

  private defaultPolicy(scope: InternalTestAgentScope): InternalTestAgentPolicy {
    return { schemaVersion: 1, scope, ...defaultPolicyDefaults() }
  }

  private async policyRecords(): Promise<Record<string, unknown>> {
    try {
      const parsed = JSON.parse(await readFile(this.policyPath, 'utf8')) as unknown
      const root = objectValue(parsed)
      return objectValue(root?.policies) ?? {}
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return {}
      throw new InternalTestError('Agent 配置文件无法读取', 503)
    }
  }

  private async resolvedPolicy(
    scope: InternalTestAgentScope,
  ): Promise<{ policy: InternalTestAgentPolicy; source: 'default' | 'saved' }> {
    const stored = (await this.policyRecords())[policyKey(scope)]
    if (!stored) return { policy: this.defaultPolicy(scope), source: 'default' }
    const updatedAt = stringValue(objectValue(stored)?.updatedAt)
    return {
      policy: normalizeAgentPolicy(stored, this.defaultPolicy(scope), scope, updatedAt),
      source: 'saved',
    }
  }

  private async projection(): Promise<LoadedProjection> {
    if (!this.demoPath) throw new InternalTestError('历史内测入口未配置', 503)
    let info
    try {
      info = await stat(this.demoPath)
    } catch {
      throw new InternalTestError('内测语料 Demo 尚未生成', 503)
    }
    if (this.cache?.mtimeMs === info.mtimeMs) return this.cache.projection
    const html = await readFile(this.demoPath, 'utf8')
    const match = /<script\s+id=["']demo-data["']\s+type=["']application\/json["']>([\s\S]*?)<\/script>/.exec(html)
    if (!match) throw new InternalTestError('内测语料 Demo 投影无效', 503)
    let parsed: DemoProjection
    try {
      parsed = JSON.parse(match[1]!) as DemoProjection
    } catch {
      throw new InternalTestError('内测语料 Demo 投影无法读取', 503)
    }
    const windows = arrayValue(parsed.windows).map(objectValue).filter(
      (item): item is Record<string, unknown> => Boolean(item && stringValue(item.window_id)),
    )
    const projection = {
      generatedAt: stringValue(parsed.generated_at),
      warnings: arrayValue(parsed.warnings).map(String),
      windows,
    }
    this.cache = { mtimeMs: info.mtimeMs, projection }
    return projection
  }

  private async runtimeStatus(): Promise<Record<string, unknown> | undefined> {
    if (!this.runtimeStatusPath) return undefined
    try {
      const statusText = await readFile(this.runtimeStatusPath, 'utf8')
      return objectValue(JSON.parse(statusText.replace(/^\uFEFF/, '')))
    } catch {
      return undefined
    }
  }

  private async runtimeReady(): Promise<boolean | undefined> {
    const status = await this.runtimeStatus()
    if (!status) return this.runtimeStatusPath ? false : undefined
    return status.ready === true
  }

  private async providerConfig(): Promise<PrivateProviderConfig> {
    if (this.options.runtimeOnly) throw new InternalTestError('正式 Agent 只调用 AstrBot Runtime', 503)
    const explicitBaseUrl = stringValue(this.options.providerBaseUrl)
    const explicitApiKey = stringValue(this.options.providerApiKey)
    if (explicitBaseUrl && explicitApiKey) return { baseUrl: explicitBaseUrl, apiKey: explicitApiKey }
    try {
      const [configText, authText] = await Promise.all([
        readFile(this.codexConfigPath, 'utf8'),
        readFile(this.authPath, 'utf8'),
      ])
      const provider = parseCodexProvider(configText, stringValue(this.options.providerName))
      const auth = JSON.parse(authText) as Record<string, unknown>
      const apiKey = stringValue(auth.OPENAI_API_KEY)
      if (!provider?.baseUrl || !apiKey) throw new Error('missing provider config')
      return { baseUrl: provider.baseUrl, apiKey }
    } catch {
      throw new InternalTestError('Provider 尚未配置', 503)
    }
  }

  private async requestCandidate(
    input: string,
    answerProfile: AnswerProfile,
    tier: ModelTier,
    reasoning: ReasoningLevel,
    conversationType: ConversationType = 'group',
    groupChatStyle: GroupChatStyle = 'natural',
  ): Promise<{ candidate: string; model: string; latencyMs: number }> {
    const model = this.models[tier]
    const provider = await this.providerConfig()
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), this.options.providerTimeoutMs ?? 90_000)
    timeout.unref?.()
    const started = performance.now()
    let response: Response
    try {
      response = await this.fetchImpl(providerEndpoint(provider.baseUrl), {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${provider.apiKey}`,
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({
          model,
          instructions: generationInstructions(answerProfile, conversationType, groupChatStyle),
          input,
          max_output_tokens: PROFILE_TOKEN_LIMITS[answerProfile],
          reasoning: { effort: reasoning },
          store: false,
        }),
        signal: controller.signal,
      })
    } catch {
      throw new InternalTestError('Provider 请求失败', 502)
    } finally {
      clearTimeout(timeout)
    }
    if (!response.ok) {
      await response.body?.cancel()
      throw new InternalTestError(`Provider 请求失败（HTTP ${response.status}）`, 502)
    }
    let payload: unknown
    try {
      payload = await response.json()
    } catch {
      throw new InternalTestError('Provider 返回了无法解析的结果', 502)
    }
    const candidate = outputText(payload)
    if (!candidate) throw new InternalTestError('Provider 未返回候选回答', 502)
    return {
      candidate,
      model,
      latencyMs: Math.max(0, Math.round(performance.now() - started)),
    }
  }

  async status(): Promise<InternalTestStatus> {
    let providerConfigured = true
    try {
      await this.providerConfig()
    } catch {
      providerConfigured = false
    }
    try {
      const projection = await this.projection()
      return {
        available: true,
        evidenceMode: INTERNAL_TEST_EVIDENCE_MODE,
        outputEnabled: false,
        providerConfigured,
        sampleCount: projection.windows.length,
        modelMapping: { ...this.models },
        generatedAt: projection.generatedAt,
        warnings: projection.warnings,
      }
    } catch {
      return {
        available: false,
        evidenceMode: INTERNAL_TEST_EVIDENCE_MODE,
        outputEnabled: false,
        providerConfigured,
        sampleCount: 0,
        modelMapping: { ...this.models },
        warnings: ['PRIVATE DEVELOPMENT DATA', 'NO SEND', '内测语料 Demo 尚未生成'],
      }
    }
  }

  async samples(query: InternalTestSamplesQuery): Promise<InternalTestSamplesPage> {
    const projection = await this.projection()
    const offset = boundedInteger(query.offset, 0, 0, projection.windows.length)
    const limit = boundedInteger(query.limit, 24, 1, 100)
    const matches = projection.windows.filter((sample) => sampleMatches(sample, query))
    return { items: matches.slice(offset, offset + limit), total: matches.length, offset, limit }
  }

  async progress(): Promise<InternalTestProgress> {
    if (!this.feedbackPath) throw new InternalTestError('历史内测入口未配置', 503)
    const projection = await this.projection()
    const windowIds = new Set(projection.windows.map((window) => String(window.window_id)))
    const latestVerdict = new Map<string, FeedbackVerdict>()
    let text: string
    try {
      text = await readFile(this.feedbackPath, 'utf8')
    } catch {
      return {
        total: windowIds.size,
        evaluated: 0,
        pending: windowIds.size,
        accepted: 0,
        rejected: 0,
        needsReview: 0,
      }
    }
    for (const line of text.split(/\r?\n/)) {
      if (!line.trim()) continue
      try {
        const record = JSON.parse(line) as Record<string, unknown>
        const windowId = stringValue(record.window_id ?? record.windowId)
        if (!windowId || !windowIds.has(windowId)) continue
        const verdict = feedbackVerdict(record.verdict)
        latestVerdict.set(windowId, verdict)
      } catch {
        // A malformed historical line is ignored so the remaining human work stays visible.
      }
    }
    const counts: InternalTestProgress = {
      total: windowIds.size,
      evaluated: latestVerdict.size,
      pending: Math.max(0, windowIds.size - latestVerdict.size),
      accepted: 0,
      rejected: 0,
      needsReview: 0,
    }
    for (const verdict of latestVerdict.values()) {
      if (verdict === 'accepted') counts.accepted += 1
      else if (verdict === 'rejected') counts.rejected += 1
      else counts.needsReview += 1
    }
    return counts
  }

  async generate(body: Record<string, unknown>): Promise<InternalTestCandidate> {
    const windowId = stringValue(body.windowId ?? body.window_id)
    if (!windowId) throw new InternalTestError('缺少 windowId')
    const projection = await this.projection()
    const sample = projection.windows.find((item) => item.window_id === windowId)
    if (!sample) throw new InternalTestError('内测样本不存在', 404)
    const tier = sampleTier(sample)
    const answerProfile = sampleAnswerProfile(sample)
    const reasoning: ReasoningLevel = tier === 'opus' ? 'high' : tier === 'haiku' ? 'low' : 'medium'
    const generated = await this.requestCandidate(contextFor(sample), answerProfile, tier, reasoning)
    return {
      runId: randomUUID(),
      windowId,
      candidate: generated.candidate,
      tier,
      model: generated.model,
      answerProfile,
      latencyMs: generated.latencyMs,
      generatedAt: this.now().toISOString(),
      evidenceMode: INTERNAL_TEST_EVIDENCE_MODE,
      providerCalls: 1,
      outputCalls: 0,
      memoryWrites: 0,
      toolCalls: 0,
    }
  }

  async agentStatus(): Promise<InternalTestAgentStatus> {
    if (this.options.runtimeOnly) {
      try {
        if (!this.options.runtimePreview?.status) throw new Error('missing runtime client')
        const live = await this.options.runtimePreview.status()
        const providerConfigured = Object.keys(live.modelMapping).length > 0
        return {
          available: live.ready,
          providerConfigured,
          outputEnabled: false,
          modelMapping: { haiku: '', sonnet: '', opus: '', ...live.modelMapping },
          runtimeControls: currentAgentRuntimeControls(live.controls, live.ready),
          readinessReason: live.ready
            ? 'Runtime 已连接；群聊预览不发送 QQ。模型调用健康以实际运行结果为准。'
            : 'AstrBot 已连接，但 Dududa Runtime 尚未装配就绪，请检查模型绑定与运行配置。',
          checkedAt: live.checkedAt,
          warnings: ['CONTROL-PLANE PREVIEW NO SEND', 'NO MEMORY WRITE', 'NO BANDIT'],
        }
      } catch (error) {
        return {
          available: false,
          providerConfigured: false,
          outputEnabled: false,
          modelMapping: { haiku: '', sonnet: '', opus: '' },
          runtimeControls: currentAgentRuntimeControls({}, false),
          readinessReason: error instanceof DududaRuntimePreviewClientError
            ? error.message : 'AstrBot Runtime 状态接口未连接，请检查服务端连接配置。',
          warnings: ['CONTROL-PLANE PREVIEW NO SEND', 'NO MEMORY WRITE', 'NO BANDIT'],
        }
      }
    }
    let providerConfigured = true
    try {
      await this.providerConfig()
    } catch {
      providerConfigured = false
    }
    const runtimeStatus = await this.runtimeStatus()
    const runtimeReady = runtimeStatus ? runtimeStatus.ready === true : this.runtimeStatusPath ? false : undefined
    let runtimeControls = currentAgentRuntimeControls(runtimeStatus ?? {}, runtimeReady)
    if (this.runtimeConfigPath) {
      try {
        const text = await readFile(this.runtimeConfigPath, 'utf8')
        runtimeControls = currentAgentRuntimeControls(
          objectValue(JSON.parse(text.replace(/^\uFEFF/, ''))) ?? {},
          runtimeReady,
        )
      } catch {
        runtimeControls = currentAgentRuntimeControls(runtimeStatus ?? {}, runtimeReady)
      }
    }
    return {
      available: providerConfigured,
      providerConfigured,
      outputEnabled: false,
      modelMapping: { ...this.models },
      runtimeControls,
      warnings: [
        'INTERNAL TEST RUNTIME',
        runtimeControls.passiveAutoReply.actualEnabled
          ? 'DUDUDA 2.0 PASSIVE RUNTIME ACTIVE'
          : 'NO PASSIVE RUNTIME DELIVERY',
        'CONTROL-PLANE CANDIDATE NO SEND',
        'NO MEMORY WRITE',
        this.options.runtimePreview
          ? '2.0 RUNTIME PREVIEW NO SEND'
          : 'NO TOOL CALL',
        'NO BANDIT',
        ...(!providerConfigured ? ['Provider 尚未配置'] : []),
      ],
    }
  }

  async agentCatalog(): Promise<InternalTestAgentCatalog> {
    if (this.options.runtimeOnly) {
      const status = await this.agentStatus()
      const catalog = buildAgentCatalog(status.modelMapping, status.providerConfigured, status.available)
      catalog.models = catalog.models.filter(model => Boolean(model.id))
      return catalog
    }
    let providerConfigured = true
    try {
      await this.providerConfig()
    } catch {
      providerConfigured = false
    }
    return buildAgentCatalog(
      this.models,
      providerConfigured,
      (await this.runtimeReady()) === true,
    )
  }

  async agentConfig(query: Record<string, unknown>): Promise<InternalTestAgentPolicy> {
    return (await this.resolvedPolicy(agentScope(query))).policy
  }

  async saveAgentConfig(body: Record<string, unknown>): Promise<InternalTestAgentPolicy> {
    const operation = this.policyWrite.then(() => this.writeAgentConfig(body))
    this.policyWrite = operation.catch(() => undefined)
    return operation
  }

  private async writeAgentConfig(body: Record<string, unknown>): Promise<InternalTestAgentPolicy> {
    const scope = agentScope(body)
    const records = await this.policyRecords()
    const current = await this.resolvedPolicy(scope)
    const updatedAt = this.now().toISOString()
    const policy = normalizeAgentPolicy(objectValue(body.policy) ?? body, current.policy, scope, updatedAt)
    records[policyKey(scope)] = policy
    await mkdir(dirname(this.policyPath), { recursive: true, mode: 0o700 })
    const temporaryPath = `${this.policyPath}.${randomUUID()}.tmp`
    try {
      await writeFile(temporaryPath, `${JSON.stringify({ schemaVersion: 1, policies: records }, null, 2)}\n`, {
        encoding: 'utf8', mode: 0o600, flag: 'wx',
      })
      await rename(temporaryPath, this.policyPath)
    } finally {
      await rm(temporaryPath, { force: true })
    }
    return policy
  }

  async respond(body: Record<string, unknown>): Promise<InternalTestAgentResponse> {
    const scope = agentScope(body, this.options.runtimeOnly === true)
    if (this.options.runtimeOnly && !this.options.runtimePreview) {
      throw new InternalTestError('AstrBot Runtime 预览接口未配置', 503)
    }
    if (this.options.runtimeOnly && !scope.conversationId.includes(':group:')) {
      throw new InternalTestError('当前 Runtime 预览仅支持已连接账号的群聊，不支持私聊。', 400)
    }
    const resolved = await this.resolvedPolicy(scope)
    if (!resolved.policy.enabled) throw new InternalTestError('当前会话的 Agent 已关闭', 409)
    const conversationType = requestedConversationType(body.conversationType ?? body.conversation_type)
    const signals = taskSignals(body)
    const modelTier = effectiveValue('model', resolved.policy.modelTier, signals.modelTier)
    const reasoning = effectiveValue('reasoning', resolved.policy.reasoning, signals.reasoning)
    const answerProfile = effectiveValue('answer_profile', resolved.policy.answerProfile, signals.answerProfile)
    const replyIntensity = effectiveValue(
      'reply_intensity',
      resolved.policy.replyIntensity,
      signals.replyIntensity,
    )
    const contextLength = effectiveValue('context_length', resolved.policy.contextLength, signals.contextLength)
    const groupChatStyle = effectiveValue(
      'group_chat_style',
      resolved.policy.groupChatStyle,
      signals.groupChatStyle,
    )
    const catalog = await this.agentCatalog()
    const plugins: Record<string, InternalTestEffectivePlugin> = {}
    const pluginReasonCodes: string[] = []
    for (const plugin of catalog.plugins) {
      const mode = resolved.policy.plugins[plugin.id] ?? 'off'
      const selection = pluginRunSelection(plugin, mode, body, conversationType)
      plugins[plugin.id] = {
        mode,
        available: plugin.available,
        eligible: selection.eligible,
        selectedForRun: selection.selectedForRun,
        applicable: selection.applicable,
        triggerMatched: selection.triggerMatched,
        runtimeTarget: plugin.runtimeTarget,
        runtimeReadiness: plugin.runtimeReadiness,
        selectionReason: selection.selectionReason,
      }
      pluginReasonCodes.push(selection.reasonCode)
    }
    const context = agentContext(body, contextLength.value)
    if (this.options.runtimePreview) {
      let runtime: DududaRuntimePreviewResult
      try {
        runtime = await this.options.runtimePreview.preview({
          accountId: scope.accountId,
          conversationId: scope.conversationId,
          prompt: stringValue(body.prompt) ?? '',
        })
      } catch (error) {
        if (error instanceof DududaRuntimePreviewClientError) {
          throw new InternalTestError(error.message, error.status)
        }
        throw new InternalTestError('Dududa 2.0 Runtime 预览失败', 503)
      }
      const selectedPluginIds = new Set<string>(runtime.capabilityIds.map((capabilityId) => {
        if (capabilityId.startsWith('icourse.')) return 'icourse.read'
        if (capabilityId.startsWith('notifai.')) return 'notifai.read'
        if (capabilityId.startsWith('ustc.young.')) return 'ustc.young.read'
        if (capabilityId.startsWith('ustc.curriculum.')) return 'ustc.curriculum.read'
        if (capabilityId.startsWith('ustc.academic.')) return 'ustc.academic.read'
        if (capabilityId.startsWith('ustc.shuttle.')) return 'ustc.shuttle.read'
        return ''
      }).filter(Boolean))
      const selectedPlugins = Object.fromEntries(
        Object.entries(plugins).map(([id, plugin]) => [
          id,
          selectedPluginIds.has(id)
            ? {
                ...plugin,
                selectedForRun: true,
                applicable: true,
                triggerMatched: true,
                selectionReason: 'trigger_matched' as const,
              }
            : plugin,
        ]),
      )
      const runtimeContextUsage = {
        ...context.usage,
        messagesRead: runtime.messagesRead,
        charactersRead: runtime.charactersRead,
      }
      const effectiveSelection: InternalTestEffectiveSelection = {
        scope,
        policySource: resolved.source,
        modelTier: runtime.tier,
        model: runtime.model,
        reasoning: runtime.reasoning,
        answerProfile: runtime.answerProfile,
        replyIntensity: replyIntensity.value,
        contextLength: contextLength.value,
        groupChatStyle: groupChatStyle.value,
        contextUsage: runtimeContextUsage,
        plugins: selectedPlugins,
      }
      return {
        runId: runtime.runId,
        candidate: runtime.candidate,
        tier: runtime.tier,
        model: runtime.model,
        reasoning: runtime.reasoning,
        answerProfile: runtime.answerProfile,
        replyIntensity: replyIntensity.value,
        contextLength: contextLength.value,
        groupChatStyle: groupChatStyle.value,
        contextUsage: runtimeContextUsage,
        effectiveSelection,
        reasonCodes: [
          `policy.${resolved.source}`,
          ...runtime.reasonCodes,
          ...pluginReasonCodes,
        ],
        latencyMs: runtime.latencyMs,
        generatedAt: runtime.generatedAt,
        outputCalls: 0,
        memoryWrites: 0,
        toolCalls: runtime.toolCalls,
        runtimePath: 'dududa_2_preview',
      }
    }
    const generated = await this.requestCandidate(
      context.input,
      answerProfile.value,
      modelTier.value,
      reasoning.value,
      conversationType,
      groupChatStyle.value,
    )
    const reasonCodes = [
      `policy.${resolved.source}`,
      ...modelTier.reasonCodes,
      ...reasoning.reasonCodes,
      ...answerProfile.reasonCodes,
      ...replyIntensity.reasonCodes,
      ...contextLength.reasonCodes,
      ...groupChatStyle.reasonCodes,
      ...pluginReasonCodes,
      'tools.none_called_by_candidate_runtime',
    ]
    const effectiveSelection: InternalTestEffectiveSelection = {
      scope,
      policySource: resolved.source,
      modelTier: modelTier.value,
      model: generated.model,
      reasoning: reasoning.value,
      answerProfile: answerProfile.value,
      replyIntensity: replyIntensity.value,
      contextLength: contextLength.value,
      groupChatStyle: groupChatStyle.value,
      contextUsage: context.usage,
      plugins,
    }
    return {
      runId: randomUUID(),
      candidate: generated.candidate,
      tier: modelTier.value,
      model: generated.model,
      reasoning: reasoning.value,
      answerProfile: answerProfile.value,
      replyIntensity: replyIntensity.value,
      contextLength: contextLength.value,
      groupChatStyle: groupChatStyle.value,
      contextUsage: context.usage,
      effectiveSelection,
      reasonCodes,
      latencyMs: generated.latencyMs,
      generatedAt: this.now().toISOString(),
      outputCalls: 0,
      memoryWrites: 0,
      toolCalls: 0,
      runtimePath: 'candidate_fallback',
    }
  }

  async feedback(body: Record<string, unknown>): Promise<InternalTestFeedbackResult> {
    if (!this.feedbackPath) throw new InternalTestError('历史内测入口未配置', 503)
    const windowId = stringValue(body.windowId ?? body.window_id)
    const runId = stringValue(body.runId ?? body.run_id)
    if (!windowId || !runId) throw new InternalTestError('缺少 windowId 或 runId')
    const projection = await this.projection()
    if (!projection.windows.some((item) => item.window_id === windowId)) {
      throw new InternalTestError('内测样本不存在', 404)
    }
    const verdict = feedbackVerdict(body.verdict)
    const evaluation = feedbackEvaluation(body.evaluation)
    const feedbackId = randomUUID()
    const note = stringValue(body.note ?? body.notes)?.slice(0, 2_000)
    const corrected = feedbackCorrections(body.corrected ?? body.corrections)
    const record = {
      schema_version: 1,
      feedback_id: feedbackId,
      window_id: windowId,
      run_id: runId,
      verdict,
      evaluation,
      ...(note ? { note } : {}),
      ...(corrected ? { corrected } : {}),
      created_at: this.now().toISOString(),
      evidence_mode: INTERNAL_TEST_EVIDENCE_MODE,
    }
    await mkdir(dirname(this.feedbackPath), { recursive: true })
    await appendFile(this.feedbackPath, `${JSON.stringify(record)}\n`, { encoding: 'utf8', mode: 0o600 })
    return { ok: true, feedbackId, progress: await this.progress() }
  }
}

export class UnavailableInternalTestGateway implements InternalTestGateway {
  constructor(
    private readonly warnings: string[] = ['PRIVATE DEVELOPMENT DATA', 'NO SEND', '内测入口未配置'],
    private readonly models: Record<ModelTier, string> = { ...DEFAULT_TIER_MODELS },
  ) {}

  async status(): Promise<InternalTestStatus> {
    return {
      available: false,
      evidenceMode: INTERNAL_TEST_EVIDENCE_MODE,
      outputEnabled: false,
      providerConfigured: false,
      sampleCount: 0,
      modelMapping: { ...this.models },
      warnings: [...this.warnings],
    }
  }

  async samples(): Promise<InternalTestSamplesPage> {
    throw new InternalTestError('内测入口未配置', 503)
  }

  async progress(): Promise<InternalTestProgress> {
    return { total: 0, evaluated: 0, pending: 0, accepted: 0, rejected: 0, needsReview: 0 }
  }

  async generate(): Promise<InternalTestCandidate> {
    throw new InternalTestError('内测入口未配置', 503)
  }

  async agentStatus(): Promise<InternalTestAgentStatus> {
    return {
      available: false,
      providerConfigured: false,
      outputEnabled: false,
      modelMapping: { ...this.models },
      runtimeControls: currentAgentRuntimeControls(),
      warnings: [...this.warnings, 'NO MEMORY WRITE', 'NO TOOL CALL', 'NO BANDIT'],
    }
  }

  async agentCatalog(): Promise<InternalTestAgentCatalog> {
    return buildAgentCatalog(this.models, false)
  }

  async agentConfig(): Promise<InternalTestAgentPolicy> {
    throw new InternalTestError('内测 Agent Runtime 未配置', 503)
  }

  async saveAgentConfig(): Promise<InternalTestAgentPolicy> {
    throw new InternalTestError('内测 Agent Runtime 未配置', 503)
  }

  async respond(): Promise<InternalTestAgentResponse> {
    throw new InternalTestError('内测 Agent Runtime 未配置', 503)
  }

  async feedback(): Promise<InternalTestFeedbackResult> {
    throw new InternalTestError('内测入口未配置', 503)
  }
}

export type AgentGateway = Pick<InternalTestGateway, 'agentStatus' | 'agentCatalog' | 'agentConfig' | 'saveAgentConfig' | 'respond'>

export function createAgentGateway(
  environment: NodeJS.ProcessEnv = process.env,
  runtimePreview?: DududaRuntimePreviewClient,
): AgentGateway {
  return new FileInternalTestGateway({
    runtimeOnly: true,
    policyPath: environment.DUDUDA_AGENT_POLICY_PATH || '/var/lib/dududa/agent/agent-policies.json',
    runtimePreview,
  })
}

export function createInternalTestGateway(
  environment: NodeJS.ProcessEnv = process.env,
  runtimePreview?: DududaRuntimePreviewClient,
): InternalTestGateway {
  const dataRoot = stringValue(environment.DUDUDA_INTERNAL_TEST_DATA_ROOT)
  const feedbackPath = stringValue(environment.DUDUDA_INTERNAL_TEST_FEEDBACK_PATH)
  const policyPath = stringValue(environment.DUDUDA_INTERNAL_TEST_POLICY_PATH)
  const models = {
    haiku: stringValue(environment.DUDUDA_INTERNAL_TEST_HAIKU_MODEL) ?? DEFAULT_TIER_MODELS.haiku,
    sonnet: stringValue(environment.DUDUDA_INTERNAL_TEST_SONNET_MODEL) ?? DEFAULT_TIER_MODELS.sonnet,
    opus: stringValue(environment.DUDUDA_INTERNAL_TEST_OPUS_MODEL) ?? DEFAULT_TIER_MODELS.opus,
  }
  if (!dataRoot || !isAbsolute(dataRoot) || (feedbackPath && !isAbsolute(feedbackPath)) || (policyPath && !isAbsolute(policyPath))) {
    return new UnavailableInternalTestGateway([
      'PRIVATE DEVELOPMENT DATA',
      'NO SEND',
      '内测数据与反馈路径必须是绝对路径',
    ], models)
  }
  const timeout = Number(environment.DUDUDA_INTERNAL_TEST_TIMEOUT_MS)
  return new FileInternalTestGateway({
    dataRoot,
    feedbackPath,
    policyPath,
    providerName: environment.DUDUDA_INTERNAL_TEST_PROVIDER,
    providerBaseUrl: environment.DUDUDA_INTERNAL_TEST_API_BASE ?? environment.DUDUDA_INTERNAL_TEST_BASE_URL,
    providerApiKey: environment.DUDUDA_INTERNAL_TEST_API_KEY,
    providerTimeoutMs: Number.isFinite(timeout) && timeout > 0 ? timeout : undefined,
    codexConfigPath: environment.DUDUDA_INTERNAL_TEST_CODEX_CONFIG,
    authPath: environment.DUDUDA_INTERNAL_TEST_AUTH_FILE,
    runtimeConfigPath: environment.DUDUDA_ASTRBOT_RUNTIME_CONFIG,
    runtimeStatusPath: environment.DUDUDA_ASTRBOT_RUNTIME_STATUS,
    runtimePreview,
    models,
  })
}
