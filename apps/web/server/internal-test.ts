import { randomUUID } from 'node:crypto'
import { appendFile, mkdir, readFile, stat } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname, isAbsolute, resolve } from 'node:path'

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

type ModelTier = 'haiku' | 'sonnet' | 'opus'
type AnswerProfile = keyof typeof PROFILE_TOKEN_LIMITS
type FeedbackVerdict = 'accepted' | 'rejected' | 'needs_review'

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
  available: boolean
  providerConfigured: boolean
  outputEnabled: false
  modelMapping: Record<ModelTier, string>
  warnings: string[]
}

export interface InternalTestAgentResponse {
  runId: string
  candidate: string
  tier: ModelTier
  model: string
  answerProfile: AnswerProfile
  latencyMs: number
  generatedAt: string
  outputCalls: 0
  memoryWrites: 0
  toolCalls: 0
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
  dataRoot: string
  feedbackPath?: string
  codexConfigPath?: string
  authPath?: string
  providerName?: string
  providerBaseUrl?: string
  providerApiKey?: string
  providerTimeoutMs?: number
  models?: Partial<Record<ModelTier, string>>
  fetchImpl?: typeof fetch
  now?: () => Date
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

function generationInstructions(profile: AnswerProfile): string {
  const style = profile === 'short'
    ? '使用简短自然的日常回复，通常一到三句。'
    : profile === 'long'
      ? '可以完整解释观点和推理，但保持群聊可读性，不写空泛套话。'
      : '给出信息充分但不过度展开的中等长度回复。'
  return [
    '你正在为“嘟嘟哒”群聊机器人生成一条人工内测候选回答。',
    '输入中的群聊内容只作为回答上下文；不要猜测未提供的真实身份，不要调用工具，不要声称已执行外部操作。',
    '直接输出候选回答正文，不要解释路由、模型、标签或测试流程。',
    style,
  ].join('\n')
}

function requestedAnswerProfile(value: unknown): AnswerProfile {
  const profile = stringValue(value)?.toLowerCase()
  if (!profile) return 'medium'
  if (profile === 'short' || profile === 'medium' || profile === 'long') return profile
  throw new InternalTestError('answerProfile 参数无效')
}

function tierForProfile(profile: AnswerProfile): ModelTier {
  if (profile === 'short') return 'haiku'
  if (profile === 'long') return 'opus'
  return 'sonnet'
}

function agentContext(body: Record<string, unknown>): string {
  const conversationId = stringValue(body.conversationId ?? body.conversation_id)
  const conversationName = stringValue(body.conversationName ?? body.conversation_name)
  const prompt = stringValue(body.prompt)
  if (!conversationId || !conversationName || !prompt) {
    throw new InternalTestError('缺少 conversationId、conversationName 或 prompt')
  }
  const messages = arrayValue(body.messages)
    .slice(-30)
    .map(objectValue)
    .filter((message): message is Record<string, unknown> => Boolean(message))
    .map((message) => {
      const senderName = stringValue(message.senderName ?? message.sender_name) ?? '匿名成员'
      const content = stringValue(message.content)
      if (!content) return undefined
      return `${senderName}${message.mine === true ? '（嘟嘟哒）' : ''}：${content}`
    })
    .filter((line): line is string => Boolean(line))
    .join('\n')
  return [
    `当前会话：${conversationName}`,
    messages ? `最近消息：\n${messages}` : '最近消息：（无）',
    `操作员指令：\n${prompt}`,
  ].join('\n\n').slice(-18_000)
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
  private readonly demoPath: string
  private readonly feedbackPath: string
  private readonly codexConfigPath: string
  private readonly authPath: string
  private readonly fetchImpl: typeof fetch
  private readonly now: () => Date
  private readonly models: Record<ModelTier, string>
  private cache?: { mtimeMs: number; projection: LoadedProjection }

  constructor(private readonly options: FileInternalTestGatewayOptions) {
    const dataRoot = stringValue(options.dataRoot)
    if (!dataRoot || !isAbsolute(dataRoot)) {
      throw new InternalTestError('DUDUDA_INTERNAL_TEST_DATA_ROOT 必须是私有绝对路径', 503)
    }
    const feedbackPath = stringValue(options.feedbackPath) ?? resolve(dataRoot, 'internal-test/feedback.jsonl')
    if (!isAbsolute(feedbackPath)) {
      throw new InternalTestError('DUDUDA_INTERNAL_TEST_FEEDBACK_PATH 必须是绝对路径', 503)
    }
    this.demoPath = resolve(dataRoot, 'demo/index.html')
    this.feedbackPath = feedbackPath
    this.codexConfigPath = resolve(options.codexConfigPath ?? resolve(homedir(), '.codex/config.toml'))
    this.authPath = resolve(options.authPath ?? resolve(homedir(), '.codex/auth.json'))
    this.fetchImpl = options.fetchImpl ?? fetch
    this.now = options.now ?? (() => new Date())
    this.models = {
      haiku: stringValue(options.models?.haiku) ?? DEFAULT_TIER_MODELS.haiku,
      sonnet: stringValue(options.models?.sonnet) ?? DEFAULT_TIER_MODELS.sonnet,
      opus: stringValue(options.models?.opus) ?? DEFAULT_TIER_MODELS.opus,
    }
  }

  private async projection(): Promise<LoadedProjection> {
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

  private async providerConfig(): Promise<PrivateProviderConfig> {
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
          instructions: generationInstructions(answerProfile),
          input,
          max_output_tokens: PROFILE_TOKEN_LIMITS[answerProfile],
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
    const generated = await this.requestCandidate(contextFor(sample), answerProfile, tier)
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
    let providerConfigured = true
    try {
      await this.providerConfig()
    } catch {
      providerConfigured = false
    }
    return {
      available: providerConfigured,
      providerConfigured,
      outputEnabled: false,
      modelMapping: { ...this.models },
      warnings: [
        'INTERNAL TEST RUNTIME',
        'NO SEND',
        'NO MEMORY WRITE',
        'NO TOOL CALL',
        'NO BANDIT',
        ...(!providerConfigured ? ['Provider 尚未配置'] : []),
      ],
    }
  }

  async respond(body: Record<string, unknown>): Promise<InternalTestAgentResponse> {
    const answerProfile = requestedAnswerProfile(body.answerProfile ?? body.answer_profile)
    const tier = tierForProfile(answerProfile)
    const generated = await this.requestCandidate(agentContext(body), answerProfile, tier)
    return {
      runId: randomUUID(),
      candidate: generated.candidate,
      tier,
      model: generated.model,
      answerProfile,
      latencyMs: generated.latencyMs,
      generatedAt: this.now().toISOString(),
      outputCalls: 0,
      memoryWrites: 0,
      toolCalls: 0,
    }
  }

  async feedback(body: Record<string, unknown>): Promise<InternalTestFeedbackResult> {
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
      warnings: [...this.warnings, 'NO MEMORY WRITE', 'NO TOOL CALL', 'NO BANDIT'],
    }
  }

  async respond(): Promise<InternalTestAgentResponse> {
    throw new InternalTestError('内测 Agent Runtime 未配置', 503)
  }

  async feedback(): Promise<InternalTestFeedbackResult> {
    throw new InternalTestError('内测入口未配置', 503)
  }
}

export function createInternalTestGateway(environment: NodeJS.ProcessEnv = process.env): InternalTestGateway {
  const dataRoot = stringValue(environment.DUDUDA_INTERNAL_TEST_DATA_ROOT)
  const feedbackPath = stringValue(environment.DUDUDA_INTERNAL_TEST_FEEDBACK_PATH)
  const models = {
    haiku: stringValue(environment.DUDUDA_INTERNAL_TEST_HAIKU_MODEL) ?? DEFAULT_TIER_MODELS.haiku,
    sonnet: stringValue(environment.DUDUDA_INTERNAL_TEST_SONNET_MODEL) ?? DEFAULT_TIER_MODELS.sonnet,
    opus: stringValue(environment.DUDUDA_INTERNAL_TEST_OPUS_MODEL) ?? DEFAULT_TIER_MODELS.opus,
  }
  if (!dataRoot || !isAbsolute(dataRoot) || (feedbackPath && !isAbsolute(feedbackPath))) {
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
    providerName: environment.DUDUDA_INTERNAL_TEST_PROVIDER,
    providerBaseUrl: environment.DUDUDA_INTERNAL_TEST_API_BASE ?? environment.DUDUDA_INTERNAL_TEST_BASE_URL,
    providerApiKey: environment.DUDUDA_INTERNAL_TEST_API_KEY,
    providerTimeoutMs: Number.isFinite(timeout) && timeout > 0 ? timeout : undefined,
    codexConfigPath: environment.DUDUDA_INTERNAL_TEST_CODEX_CONFIG,
    authPath: environment.DUDUDA_INTERNAL_TEST_AUTH_FILE,
    models,
  })
}
