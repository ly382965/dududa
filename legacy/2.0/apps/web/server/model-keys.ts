import { randomUUID } from 'node:crypto'
import { homedir } from 'node:os'
import { chmod, lstat, mkdir, open, readFile, rename, unlink } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'

/**
 * The three logical model tiers are intentionally kept independent from the
 * Runtime's tier policy.  This module only owns provider credentials and the
 * metadata needed to operate a credential pool.
 */
export const API_KEY_TIERS = ['haiku', 'sonnet', 'opus'] as const
export type ApiKeyTier = (typeof API_KEY_TIERS)[number]

const RUNTIME_BINDING_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$/
const API_KEY_STORE_MAX_BYTES = 4 * 1024 * 1024

export const API_KEY_TIER_LABELS: Record<ApiKeyTier, string> = {
  haiku: 'Luna · 轻量推理',
  sonnet: 'Terra · 标准推理',
  opus: 'Sol · 深度推理',
}

export type ApiKeyStatus = 'active' | 'disabled' | 'cooldown' | 'unavailable' | 'error' | 'pending' | string

export interface ApiKeyCustomHeader {
  name: string
  value: string
}

/** Public key projection.  It deliberately has no `secret` property. */
export interface ApiKeyEntry {
  id: string
  name: string
  secretRef: string
  masked: string
  priority: number
  weight: number
  enabled: boolean
  status: ApiKeyStatus
  lastSuccessAt?: string
  lastFailureAt?: string
  cooldownUntil?: string
  lastCheckedAt?: string
  createdAt?: string
  updatedAt?: string
}

export interface ApiKeyPool {
  tier: ApiKeyTier
  displayName: string
  provider: string
  providerType?: string
  providerId?: string
  /** AstrBot Provider Source identifier used by the controlled reload adapter. */
  sourceId?: string
  baseUrl: string
  model: string
  protocol: string
  reasoningEffort: string
  timeoutMs: number
  maxOutputTokens: number
  enabled: boolean
  schedulingMode: string
  customHeaders: ApiKeyCustomHeader[]
  revision: number
  updatedAt?: string
  keys: ApiKeyEntry[]
}

export interface ApiKeyPoolsSnapshot {
  schemaVersion: 1
  revision: number
  pools: ApiKeyPool[]
}

export interface ApiKeyWriteReceipt {
  id: string
  status: 'committed'
  committedAt: string
}

export interface ApiKeyMutationResponse {
  pool?: ApiKeyPool
  key?: ApiKeyEntry
  writeReceipt?: ApiKeyWriteReceipt
}

export interface ApiKeyPoolUpdateInput {
  displayName?: unknown
  provider?: unknown
  providerType?: unknown
  providerId?: unknown
  sourceId?: unknown
  baseUrl?: unknown
  model?: unknown
  modelId?: unknown
  protocol?: unknown
  reasoningEffort?: unknown
  reasoning?: unknown
  timeoutMs?: unknown
  timeout?: unknown
  maxOutputTokens?: unknown
  outputBudget?: unknown
  enabled?: unknown
  schedulingMode?: unknown
  scheduling?: unknown
  customHeaders?: unknown
  headers?: unknown
  revision?: unknown
}

export interface ApiKeyCreateInput {
  name?: unknown
  displayName?: unknown
  secret?: unknown
  secretRef?: unknown
  priority?: unknown
  weight?: unknown
  enabled?: unknown
}

export interface ApiKeyUpdateInput extends ApiKeyCreateInput {
  revision?: unknown
}

export interface ApiKeyProbeContext {
  tier: ApiKeyTier
  pool: ApiKeyPool
  key: ApiKeyEntry
  /** Raw secret is available only inside the server-side probe callback. */
  secret: string
  signal: AbortSignal
}

export interface ApiKeyProbeResult {
  status?: unknown
  ok?: unknown
  message?: unknown
  latencyMs?: unknown
  model?: unknown
}

export type ApiKeyProbe = (context: ApiKeyProbeContext) => Promise<ApiKeyProbeResult> | ApiKeyProbeResult

export interface ApiKeyPoolTestResult {
  status: 'ok' | 'error' | 'unavailable'
  message: string
  latencyMs?: number
  model?: string
  checkedAt?: string
  /** Pool revision after health metadata is recorded. */
  revision: number
}

export interface ApiKeyPoolClient {
  list(): Promise<ApiKeyPoolsSnapshot>
  updatePool(tier: ApiKeyTier, input: ApiKeyPoolUpdateInput): Promise<ApiKeyMutationResponse>
  createKey(tier: ApiKeyTier, input: ApiKeyCreateInput): Promise<ApiKeyMutationResponse>
  updateKey(tier: ApiKeyTier, keyId: string, input: ApiKeyUpdateInput): Promise<ApiKeyMutationResponse>
  deleteKey(tier: ApiKeyTier, keyId: string, mode?: 'remove' | 'disable'): Promise<ApiKeyMutationResponse>
  testPool(tier: ApiKeyTier, keyId?: string): Promise<ApiKeyPoolTestResult>
}

/** Alias used by callers that refer to the adapter as a model-key client. */
export type ModelKeyPoolClient = ApiKeyPoolClient

export class ApiKeyPoolError extends Error {
  constructor(message: string, readonly status = 400) {
    super(message)
    this.name = 'ApiKeyPoolError'
  }
}

export class ModelKeyPoolClientError extends ApiKeyPoolError {
  constructor(message: string, status = 400) {
    super(message, status)
    this.name = 'ModelKeyPoolClientError'
  }
}

class ProbeTimeoutError extends Error {
  constructor() {
    super('provider probe timeout')
    this.name = 'ProbeTimeoutError'
  }
}

interface StoredKey {
  id: string
  name: string
  secret: string
  secretRef: string
  priority: number
  weight: number
  enabled: boolean
  status: ApiKeyStatus
  lastSuccessAt?: string
  lastFailureAt?: string
  cooldownUntil?: string
  lastCheckedAt?: string
  createdAt: string
  updatedAt: string
}

interface StoredPool {
  tier: ApiKeyTier
  displayName: string
  provider: string
  providerType?: string
  providerId?: string
  sourceId?: string
  baseUrl: string
  model: string
  protocol: string
  reasoningEffort: string
  timeoutMs: number
  maxOutputTokens: number
  enabled: boolean
  schedulingMode: string
  customHeaders: ApiKeyCustomHeader[]
  revision: number
  updatedAt: string
  keys: StoredKey[]
}

interface StoredState {
  schemaVersion: 1
  revision: number
  pools: Record<ApiKeyTier, StoredPool>
}

export interface FileApiKeyPoolStoreOptions {
  /** Absolute or relative path to the external credential file. */
  path?: string
  /** Clock and ID hooks make persistence tests deterministic. */
  now?: () => Date
  idFactory?: () => string
  probe?: ApiKeyProbe
  maxProbeMs?: number
  /** Test hook; production can only use the shared 4 MiB ceiling or lower. */
  maxStoreBytes?: number
}

/**
 * A small file-backed credential store for the Web control plane.
 *
 * Raw secrets are kept only in this class and in the external JSON file.  All
 * values leaving the class pass through `publicPool`/`publicKey`, which have no
 * raw-secret field.  Writes use a temporary 0600 file followed by rename so a
 * process never observes a partially-written credential document.
 */
export class FileApiKeyPoolStore implements ApiKeyPoolClient {
  readonly path: string

  private readonly now: () => Date
  private readonly idFactory: () => string
  private readonly probe?: ApiKeyProbe
  private readonly maxProbeMs: number
  private readonly maxStoreBytes: number
  private state?: StoredState
  private loadPromise?: Promise<void>
  private mutationQueue: Promise<unknown> = Promise.resolve()

  constructor(pathOrOptions: string | FileApiKeyPoolStoreOptions = {}) {
    const options = typeof pathOrOptions === 'string' ? { path: pathOrOptions } : pathOrOptions
    this.path = resolve(options.path || defaultApiKeyStorePath())
    this.now = options.now ?? (() => new Date())
    this.idFactory = options.idFactory ?? randomUUID
    this.probe = options.probe
    this.maxProbeMs = clampInteger(options.maxProbeMs, 100, 60_000, 10_000)
    this.maxStoreBytes = clampInteger(options.maxStoreBytes, 1, API_KEY_STORE_MAX_BYTES, API_KEY_STORE_MAX_BYTES)
  }

  async list(): Promise<ApiKeyPoolsSnapshot> {
    await this.mutationQueue
    await this.ensureLoaded()
    return this.snapshot()
  }

  async catalog(): Promise<ApiKeyPoolsSnapshot> {
    return this.list()
  }

  async getPool(tier: ApiKeyTier): Promise<ApiKeyPool> {
    await this.mutationQueue
    await this.ensureLoaded()
    return publicPool(this.requirePool(tier))
  }

  async updatePool(tier: ApiKeyTier, input: ApiKeyPoolUpdateInput): Promise<ApiKeyMutationResponse> {
    return this.mutate(async () => {
      const pool = this.requirePool(tier)
      checkRevision(input.revision, pool.revision)
      const next = applyPoolInput(pool, input)
      assertUniqueRuntimeBindings(this.state!.pools, tier, next)
      const timestamp = this.timestamp()
      next.revision = this.bumpRevision()
      next.updatedAt = timestamp
      this.state!.pools[tier] = next
      await this.persist()
      return this.mutationResponse(publicPool(next), undefined, timestamp)
    })
  }

  async createKey(tier: ApiKeyTier, input: ApiKeyCreateInput): Promise<ApiKeyMutationResponse> {
    return this.mutate(async () => {
      const pool = this.requirePool(tier)
      const secret = requiredSecret(input.secret)
      const name = keyName(input.name ?? input.displayName, pool.keys.length)
      const id = this.newKeyId(tier)
      const timestamp = this.timestamp()
      const key: StoredKey = {
        id,
        name,
        secret,
        secretRef: secretRef(tier, id, input.secretRef),
        priority: priorityValue(input.priority, 0),
        weight: weightValue(input.weight, 1),
        enabled: booleanValue(input.enabled, true),
        status: booleanValue(input.enabled, true) ? 'active' : 'disabled',
        createdAt: timestamp,
        updatedAt: timestamp,
      }
      pool.keys.unshift(key)
      pool.revision = this.bumpRevision()
      pool.updatedAt = timestamp
      await this.persist()
      return this.mutationResponse(publicPool(pool), publicKey(key), timestamp)
    })
  }

  async updateKey(tier: ApiKeyTier, keyId: string, input: ApiKeyUpdateInput): Promise<ApiKeyMutationResponse> {
    return this.mutate(async () => {
      const pool = this.requirePool(tier)
      const key = this.requireKey(pool, keyId)
      checkRevision(input.revision, pool.revision)
      if (input.name !== undefined || input.displayName !== undefined) {
        key.name = keyName(input.name ?? input.displayName, pool.keys.indexOf(key))
      }
      if (input.secret !== undefined) {
        if (typeof input.secret !== 'string') throw new ApiKeyPoolError('密钥格式无效', 400)
        // An omitted or blank replacement deliberately keeps the existing
        // credential.  This lets metadata-only edits avoid re-submitting it.
        if (input.secret.trim()) {
          key.secret = optionalSecret(input.secret)
          key.status = booleanValue(input.enabled, key.enabled) ? 'active' : 'disabled'
          key.lastCheckedAt = undefined
        }
      }
      if (input.secretRef !== undefined) key.secretRef = secretRef(tier, key.id, input.secretRef)
      if (input.priority !== undefined) key.priority = priorityValue(input.priority, key.priority)
      if (input.weight !== undefined) key.weight = weightValue(input.weight, key.weight)
      if (input.enabled !== undefined) {
        key.enabled = booleanValue(input.enabled, key.enabled)
        if (!key.enabled) key.status = 'disabled'
        else if (key.status === 'disabled') key.status = 'active'
      }
      const timestamp = this.timestamp()
      key.updatedAt = timestamp
      pool.revision = this.bumpRevision()
      pool.updatedAt = timestamp
      await this.persist()
      return this.mutationResponse(publicPool(pool), publicKey(key), timestamp)
    })
  }

  async deleteKey(tier: ApiKeyTier, keyId: string, mode: 'remove' | 'disable' = 'remove'): Promise<ApiKeyMutationResponse> {
    return this.mutate(async () => {
      const pool = this.requirePool(tier)
      const key = this.requireKey(pool, keyId)
      const timestamp = this.timestamp()
      if (mode === 'disable') {
        key.enabled = false
        key.status = 'disabled'
        key.updatedAt = timestamp
      } else {
        const index = pool.keys.indexOf(key)
        pool.keys.splice(index, 1)
      }
      pool.revision = this.bumpRevision()
      pool.updatedAt = timestamp
      await this.persist()
      return this.mutationResponse(publicPool(pool), mode === 'disable' ? publicKey(key) : undefined, timestamp)
    })
  }

  async testPool(tier: ApiKeyTier, keyId?: string): Promise<ApiKeyPoolTestResult> {
    return this.mutate(async () => {
      const pool = this.requirePool(tier)
      const key = keyId ? this.requireKey(pool, keyId) : selectProbeKey(pool)
      const checkedAt = this.timestamp()
      if (!pool.enabled || !pool.baseUrl || !pool.model || !key || !key.enabled || !key.secret) return {
        status: 'unavailable',
        message: '此 Provider 池没有可用的已启用 Key',
        latencyMs: 0,
        model: pool.model,
        checkedAt,
        revision: pool.revision,
      }
      if (!this.probe) return {
        status: 'unavailable',
        message: 'Provider 探针未配置；已保存池配置，可由 Runtime 侧执行探测',
        latencyMs: 0,
        model: pool.model,
        checkedAt,
        revision: pool.revision,
      }

      const started = Date.now()
      const controller = new AbortController()
      const probeTimeoutMs = Math.min(this.maxProbeMs, pool.timeoutMs)
      let timeoutHandle: ReturnType<typeof setTimeout> | undefined
      let result: ApiKeyProbeResult
      try {
        const probePromise = Promise.resolve(this.probe({
            tier,
            pool: publicPool(pool),
            key: publicKey(key),
            secret: key.secret,
            signal: controller.signal,
          }))
        const timeoutPromise = new Promise<never>((_resolve, reject) => {
          timeoutHandle = setTimeout(() => {
            controller.abort()
            reject(new ProbeTimeoutError())
          }, probeTimeoutMs)
          timeoutHandle.unref?.()
        })
        result = await Promise.race([probePromise, timeoutPromise])
      } catch (error) {
        const timestamp = this.timestamp()
        key.status = controller.signal.aborted ? 'unavailable' : 'error'
        key.lastFailureAt = timestamp
        key.lastCheckedAt = timestamp
        key.updatedAt = timestamp
        pool.revision = this.bumpRevision()
        pool.updatedAt = timestamp
        await this.persist()
        return {
          status: 'error',
          message: controller.signal.aborted ? 'Provider 探测超时' : 'Provider 探测失败',
          latencyMs: elapsed(started),
          model: pool.model,
          checkedAt: timestamp,
          revision: pool.revision,
        }
      } finally {
        if (timeoutHandle) clearTimeout(timeoutHandle)
      }
      const probeResult = result && typeof result === 'object' ? result : {}
      const timestamp = this.timestamp()
      const ok = probeResult.ok === true || probeResult.status === 'ok' || probeResult.status === 'success'
      key.status = ok ? 'active' : 'error'
      key.lastCheckedAt = timestamp
      if (ok) key.lastSuccessAt = timestamp
      else key.lastFailureAt = timestamp
      key.updatedAt = timestamp
      pool.revision = this.bumpRevision()
      pool.updatedAt = timestamp
      await this.persist()
      return {
        status: ok ? 'ok' : 'error',
        message: safeProbeMessage(probeResult.message, ok, key.secret),
        latencyMs: nonnegativeInteger(probeResult.latencyMs, elapsed(started)),
        model: safeText(probeResult.model) || pool.model,
        checkedAt: timestamp,
        revision: pool.revision,
      }
    })
  }

  /** Test-friendly alias. */
  async test(tier: ApiKeyTier, keyId?: string): Promise<ApiKeyPoolTestResult> {
    return this.testPool(tier, keyId)
  }

  private async mutate<T>(operation: () => Promise<T>): Promise<T> {
    const run = this.mutationQueue.then(async () => {
      await this.ensureLoaded()
      const previous = structuredClone(this.state!)
      try {
        return await operation()
      } catch (error) {
        // Mutations update the in-memory graph before the atomic rename. If
        // persistence fails, restore the complete graph so GET/retry cannot
        // observe or later commit a write that the caller saw fail.
        this.state = previous
        throw error
      }
    })
    this.mutationQueue = run.then(() => undefined, () => undefined)
    return run
  }

  private async ensureLoaded(): Promise<void> {
    if (!this.loadPromise) this.loadPromise = this.load()
    await this.loadPromise
  }

  private async load(): Promise<void> {
    let text: string
    try {
      const info = await lstat(this.path)
      if (info.isSymbolicLink() || !info.isFile()) throw new ApiKeyPoolError('API Key 存储路径必须是普通文件', 500)
      if ((info.mode & 0o077) !== 0) throw new ApiKeyPoolError('API Key 存储文件权限不安全', 500)
      if (info.size > this.maxStoreBytes) throw new ApiKeyPoolError('API Key 存储文件超过大小限制', 500)
      text = await readFile(this.path, 'utf8')
    } catch (error) {
      if (isMissingFile(error)) {
        this.state = createDefaultState(this.timestamp())
        return
      }
      if (error instanceof ApiKeyPoolError) throw error
      throw new ApiKeyPoolError('API Key 存储文件无法读取', 500)
    }
    if (!text.trim()) {
      this.state = createDefaultState(this.timestamp())
      return
    }
    try {
      this.state = normalizeState(JSON.parse(text) as unknown, this.timestamp(), this.idFactory)
    } catch {
      throw new ApiKeyPoolError('API Key 存储文件格式无效', 500)
    }
  }

  private snapshot(): ApiKeyPoolsSnapshot {
    const state = this.state!
    return {
      schemaVersion: 1,
      revision: state.revision,
      pools: API_KEY_TIERS.map((tier) => publicPool(state.pools[tier])),
    }
  }

  private requirePool(tier: ApiKeyTier): StoredPool {
    if (!isTier(tier)) throw new ApiKeyPoolError('API Key tier 无效', 400)
    const pool = this.state!.pools[tier]
    if (!pool) throw new ApiKeyPoolError('API Key 池不存在', 404)
    return pool
  }

  private requireKey(pool: StoredPool, keyId: string): StoredKey {
    if (typeof keyId !== 'string' || !keyId.trim() || keyId.length > 160) {
      throw new ApiKeyPoolError('API Key 标识无效', 400)
    }
    const key = pool.keys.find((item) => item.id === keyId)
    if (!key) throw new ApiKeyPoolError('API Key 不存在', 404)
    return key
  }

  private bumpRevision(): number {
    this.state!.revision += 1
    return this.state!.revision
  }

  private timestamp(): string {
    const value = this.now()
    return Number.isNaN(value.getTime()) ? new Date().toISOString() : value.toISOString()
  }

  private newKeyId(tier: ApiKeyTier): string {
    const existing = this.state!.pools[tier].keys
    let id = `${tier}-${this.idFactory()}`
    let suffix = 2
    while (existing.some((key) => key.id === id)) {
      id = `${tier}-${this.idFactory()}-${suffix}`
      suffix += 1
    }
    return id
  }

  private mutationResponse(pool: ApiKeyPool, key: ApiKeyEntry | undefined, timestamp: string): ApiKeyMutationResponse {
    return {
      pool,
      ...(key ? { key } : {}),
      writeReceipt: { id: this.idFactory(), status: 'committed', committedAt: timestamp },
    }
  }

  private async persist(): Promise<void> {
    const state = this.state!
    const directory = dirname(this.path)
    const serialized = `${JSON.stringify(state, null, 2)}\n`
    if (Buffer.byteLength(serialized, 'utf8') > this.maxStoreBytes) {
      throw new ApiKeyPoolError('API Key 存储容量已达上限', 413)
    }
    await mkdir(directory, { recursive: true, mode: 0o700 })
    const temporary = `${this.path}.${process.pid}.${this.idFactory()}.tmp`
    try {
      const handle = await open(temporary, 'wx', 0o600)
      try {
        await handle.writeFile(serialized, 'utf8')
        await handle.sync()
      } finally {
        await handle.close()
      }
      await chmod(temporary, 0o600)
      await rename(temporary, this.path)
    } catch (error) {
      await unlink(temporary).catch(() => undefined)
      throw new ApiKeyPoolError('API Key 存储文件无法写入', 500)
    }
  }
}

export class UnavailableApiKeyPoolClient implements ApiKeyPoolClient {
  constructor(private readonly reason = 'API Key 池后端未配置') {}

  async list(): Promise<ApiKeyPoolsSnapshot> {
    const timestamp = new Date().toISOString()
    return {
      schemaVersion: 1,
      revision: 1,
      pools: API_KEY_TIERS.map((tier) => publicPool(defaultPool(tier, timestamp))),
    }
  }

  async updatePool(): Promise<ApiKeyMutationResponse> {
    throw new ApiKeyPoolError(this.reason, 503)
  }

  async createKey(): Promise<ApiKeyMutationResponse> {
    throw new ApiKeyPoolError(this.reason, 503)
  }

  async updateKey(): Promise<ApiKeyMutationResponse> {
    throw new ApiKeyPoolError(this.reason, 503)
  }

  async deleteKey(): Promise<ApiKeyMutationResponse> {
    throw new ApiKeyPoolError(this.reason, 503)
  }

  async testPool(): Promise<ApiKeyPoolTestResult> {
    return {
      status: 'unavailable',
      message: this.reason,
      latencyMs: 0,
      model: '',
      checkedAt: new Date().toISOString(),
      revision: 1,
    }
  }
}

export function defaultApiKeyStorePath(): string {
  const configured = process.env.DUDUDA_API_KEY_STORE_PATH?.trim()
    || process.env.DUDUDA_API_KEYS_FILE?.trim()
  if (configured) return resolve(configured)
  const stateHome = process.env.XDG_STATE_HOME?.trim() || resolve(homedir(), '.local', 'state')
  return resolve(stateHome, 'dududa', 'api-keys.json')
}

export function isApiKeyTier(value: unknown): value is ApiKeyTier {
  return isTier(value)
}

export function maskApiKey(secret: string): string {
  if (!secret) return ''
  if (secret.length <= 8) return '••••••••'
  return `${secret.slice(0, 4)}${'•'.repeat(Math.min(12, Math.max(4, secret.length - 8)))}${secret.slice(-4)}`
}

/**
 * Re-project an adapter value through the public allow-list.  This is useful
 * at the HTTP boundary because TypeScript interfaces cannot prevent a faulty
 * AstrBot adapter (or a future implementation) from returning `secret` at
 * runtime.  Unknown fields, including `secret`, `apiKey`, `token` and
 * `credentials`, are intentionally discarded.
 */
export function sanitizeApiKeySnapshot(value: unknown): ApiKeyPoolsSnapshot {
  const item = value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
  const rawPools = item.pools
  const candidates: unknown[] = Array.isArray(rawPools)
    ? rawPools
    : rawPools && typeof rawPools === 'object'
      ? Object.entries(rawPools as Record<string, unknown>).map(([tier, pool]) => ({
        ...(pool && typeof pool === 'object' && !Array.isArray(pool) ? pool as Record<string, unknown> : {}),
        tier,
      }))
      : []
  const byTier = new Map<ApiKeyTier, ApiKeyPool>()
  for (const candidate of candidates) {
    const pool = sanitizeApiKeyPool(candidate)
    if (!byTier.has(pool.tier)) byTier.set(pool.tier, pool)
  }
  const revision = positiveInteger(item.revision, 1)
  const timestamp = new Date().toISOString()
  return {
    schemaVersion: 1,
    revision,
    pools: API_KEY_TIERS.map((tier) => byTier.get(tier) ?? publicPool(defaultPool(tier, timestamp))),
  }
}

export function sanitizeApiKeyPool(value: unknown): ApiKeyPool {
  const item = value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
  const tier = safeText(item.tier)
  if (!isTier(tier)) throw new ApiKeyPoolError('API Key 池响应格式无效', 502)
  const fallback = publicPool(defaultPool(tier, new Date().toISOString()))
  const rawHeaders = item.customHeaders ?? item.custom_headers ?? item.headers
  const customHeaders = sanitizeHeaders(rawHeaders)
  const rawKeys = Array.isArray(item.keys)
    ? item.keys
    : Array.isArray(item.entries)
      ? item.entries
      : []
  return {
    tier,
    displayName: boundedSafe(item.displayName ?? item.display_name, fallback.displayName, 120),
    provider: boundedSafe(item.provider ?? item.providerName ?? item.provider_name, '', 160),
    ...(boundedSafe(item.providerType ?? item.provider_type, '', 120) ? { providerType: boundedSafe(item.providerType ?? item.provider_type, '', 120) } : {}),
    ...(boundedSafe(item.providerId ?? item.provider_id, '', 160) ? { providerId: boundedSafe(item.providerId ?? item.provider_id, '', 160) } : {}),
    ...(boundedSafe(item.sourceId ?? item.source_id, '', 160) ? { sourceId: boundedSafe(item.sourceId ?? item.source_id, '', 160) } : {}),
    baseUrl: safePublicBaseUrl(item.baseUrl ?? item.base_url, ''),
    model: boundedSafe(item.model ?? item.modelId ?? item.model_id, '', 256),
    protocol: boundedSafe(item.protocol ?? item.protocolMode ?? item.protocol_mode, fallback.protocol, 64),
    reasoningEffort: boundedSafe(item.reasoningEffort ?? item.reasoning_effort ?? item.reasoning, fallback.reasoningEffort, 32),
    timeoutMs: boundedOrDefault(item.timeoutMs ?? item.timeout_ms, fallback.timeoutMs, 1_000, 900_000),
    maxOutputTokens: boundedOrDefault(item.maxOutputTokens ?? item.max_output_tokens ?? item.outputBudget, fallback.maxOutputTokens, 1, 1_000_000),
    enabled: typeof item.enabled === 'boolean' ? item.enabled : fallback.enabled,
    schedulingMode: boundedSafe(item.schedulingMode ?? item.scheduling_mode ?? item.scheduler, fallback.schedulingMode, 64),
    customHeaders,
    revision: positiveInteger(item.revision, fallback.revision),
    updatedAt: boundedSafe(item.updatedAt ?? item.updated_at, fallback.updatedAt ?? new Date().toISOString(), 64),
    keys: rawKeys.map(sanitizeApiKeyEntry).filter((key): key is ApiKeyEntry => Boolean(key)),
  }
}

export function sanitizeApiKeyEntry(value: unknown): ApiKeyEntry | undefined {
  const item = value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
  const id = boundedSafe(item.id ?? item.keyId ?? item.key_id, '', 160)
  if (!id) return undefined
  const enabled = typeof item.enabled === 'boolean' ? item.enabled : item.status !== 'disabled'
  const status = boundedSafe(item.status ?? item.state, enabled ? 'active' : 'disabled', 64)
  // Never use `key`, `value`, `token` or `apiKey` as a masking fallback.  A
  // raw secret from a faulty adapter may be present under one of those names.
  const suppliedMasked = boundedSafe(item.masked ?? item.maskedKey ?? item.masked_key ?? item.suffix, '', 128)
  const rawSecret = typeof item.secret === 'string' ? item.secret : ''
  return {
    id,
    name: boundedSafe(item.name ?? item.displayName ?? item.display_name, 'Key', 120),
    secretRef: boundedSafe(item.secretRef ?? item.secret_ref ?? item.secretId ?? item.secret_id, '', 160),
    masked: rawSecret ? maskApiKey(rawSecret) : sanitizeMasked(suppliedMasked),
    priority: boundedOrDefault(item.priority, 0, 0, 1_000_000),
    weight: boundedOrDefault(item.weight, 1, 1, 1_000),
    enabled,
    status: enabled ? status : 'disabled',
    ...(boundedSafe(item.lastSuccessAt ?? item.last_success_at, '', 64) ? { lastSuccessAt: boundedSafe(item.lastSuccessAt ?? item.last_success_at, '', 64) } : {}),
    ...(boundedSafe(item.lastFailureAt ?? item.last_failure_at, '', 64) ? { lastFailureAt: boundedSafe(item.lastFailureAt ?? item.last_failure_at, '', 64) } : {}),
    ...(boundedSafe(item.cooldownUntil ?? item.cooldown_until, '', 64) ? { cooldownUntil: boundedSafe(item.cooldownUntil ?? item.cooldown_until, '', 64) } : {}),
    ...(boundedSafe(item.lastCheckedAt ?? item.last_checked_at, '', 64) ? { lastCheckedAt: boundedSafe(item.lastCheckedAt ?? item.last_checked_at, '', 64) } : {}),
    createdAt: boundedSafe(item.createdAt ?? item.created_at, new Date().toISOString(), 64),
    updatedAt: boundedSafe(item.updatedAt ?? item.updated_at, new Date().toISOString(), 64),
  }
}

export function sanitizeApiKeyMutation(value: unknown): ApiKeyMutationResponse {
  const item = value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
  const poolValue = item.pool ?? (isTier(item.tier) ? item : undefined)
  const keyValue = item.key ?? item.entry
  const receiptValue = item.writeReceipt ?? item.receipt
  const receipt = sanitizeReceipt(receiptValue)
  const pool = poolValue === undefined ? undefined : sanitizeApiKeyPool(poolValue)
  const key = keyValue === undefined ? undefined : sanitizeApiKeyEntry(keyValue)
  return {
    ...(pool ? { pool } : {}),
    ...(key ? { key } : {}),
    writeReceipt: receipt,
  }
}

export function sanitizeApiKeyTestResult(value: unknown): ApiKeyPoolTestResult {
  const item = value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
  const status = safeText(item.status ?? item.state)
  const normalizedStatus: ApiKeyPoolTestResult['status'] = status === 'ok' || status === 'success'
    ? 'ok'
    : status === 'unavailable' || status === 'pending'
      ? 'unavailable'
      : 'error'
  return {
    status: normalizedStatus,
    message: safeProbeMessage(item.message ?? item.detail ?? item.error, normalizedStatus === 'ok'),
    latencyMs: nonnegativeInteger(item.latencyMs, 0),
    model: boundedSafe(item.model ?? item.modelId ?? item.model_id, '', 256),
    checkedAt: boundedSafe(item.checkedAt ?? item.checked_at, new Date().toISOString(), 64),
    revision: positiveInteger(item.revision, 1),
  }
}

function createDefaultState(timestamp: string): StoredState {
  return {
    schemaVersion: 1,
    revision: 1,
    pools: {
      haiku: defaultPool('haiku', timestamp),
      sonnet: defaultPool('sonnet', timestamp),
      opus: defaultPool('opus', timestamp),
    },
  }
}

function defaultPool(tier: ApiKeyTier, timestamp: string): StoredPool {
  return {
    tier,
    displayName: API_KEY_TIER_LABELS[tier],
    provider: '',
    providerId: defaultProviderId(tier),
    sourceId: defaultSourceId(tier),
    baseUrl: '',
    model: '',
    protocol: 'openai_chat_completions',
    reasoningEffort: 'low',
    timeoutMs: 120_000,
    maxOutputTokens: 2_048,
    enabled: false,
    schedulingMode: 'round_robin',
    customHeaders: [],
    revision: 1,
    updatedAt: timestamp,
    keys: [],
  }
}

function publicPool(pool: StoredPool): ApiKeyPool {
  return {
    tier: pool.tier,
    displayName: pool.displayName,
    provider: pool.provider,
    ...(pool.providerType ? { providerType: pool.providerType } : {}),
    ...(pool.providerId ? { providerId: pool.providerId } : {}),
    ...(pool.sourceId ? { sourceId: pool.sourceId } : {}),
    baseUrl: pool.baseUrl,
    model: pool.model,
    protocol: pool.protocol,
    reasoningEffort: pool.reasoningEffort,
    timeoutMs: pool.timeoutMs,
    maxOutputTokens: pool.maxOutputTokens,
    enabled: pool.enabled,
    schedulingMode: pool.schedulingMode,
    customHeaders: pool.customHeaders.map((header) => ({ ...header })),
    revision: pool.revision,
    updatedAt: pool.updatedAt,
    keys: pool.keys.map(publicKey),
  }
}

function publicKey(key: StoredKey): ApiKeyEntry {
  return {
    id: key.id,
    name: key.name,
    secretRef: key.secretRef,
    masked: maskApiKey(key.secret),
    priority: key.priority,
    weight: key.weight,
    enabled: key.enabled,
    status: key.enabled ? key.status : 'disabled',
    ...(key.lastSuccessAt ? { lastSuccessAt: key.lastSuccessAt } : {}),
    ...(key.lastFailureAt ? { lastFailureAt: key.lastFailureAt } : {}),
    ...(key.cooldownUntil ? { cooldownUntil: key.cooldownUntil } : {}),
    ...(key.lastCheckedAt ? { lastCheckedAt: key.lastCheckedAt } : {}),
    createdAt: key.createdAt,
    updatedAt: key.updatedAt,
  }
}

function applyPoolInput(pool: StoredPool, input: ApiKeyPoolUpdateInput): StoredPool {
  const next: StoredPool = {
    ...pool,
    customHeaders: pool.customHeaders.map((header) => ({ ...header })),
    keys: pool.keys,
  }
  if (input.displayName !== undefined) next.displayName = requiredText(input.displayName, '显示名称', 120)
  if (input.provider !== undefined) next.provider = requiredText(input.provider, 'Provider', 160)
  // PUT replaces pool metadata. The UI omits optional fields when an
  // operator clears them, so absence intentionally clears the prior value.
  next.providerType = input.providerType === undefined
    ? undefined
    : optionalText(input.providerType, 'Provider 类型', 120)
  // Provider/Source IDs are runtime binding identities, not presentation
  // metadata. Preserve an existing binding when an older client omits these
  // fields, and fall back to deterministic tier IDs when a client sends an
  // empty value. This keeps the in-memory response identical to normalized
  // state after a restart and prevents silent rebinding on reload.
  const defaultBinding = defaultPool(pool.tier, pool.updatedAt)
  next.providerId = input.providerId === undefined
    ? (pool.providerId || defaultBinding.providerId)
    : runtimeBindingId(input.providerId, 'Provider ID', defaultBinding.providerId!)
  next.sourceId = input.sourceId === undefined
    ? (pool.sourceId || defaultBinding.sourceId)
    : runtimeBindingId(input.sourceId, 'Source ID', defaultBinding.sourceId!)
  if (input.baseUrl !== undefined) next.baseUrl = providerUrl(input.baseUrl)
  if (input.model !== undefined || input.modelId !== undefined) next.model = requiredText(input.model ?? input.modelId, '模型 ID', 256)
  if (input.protocol !== undefined) next.protocol = runtimeProtocol(input.protocol)
  if (input.reasoningEffort !== undefined || input.reasoning !== undefined) {
    next.reasoningEffort = requiredText(input.reasoningEffort ?? input.reasoning, '推理强度', 32)
  }
  if (input.timeoutMs !== undefined || input.timeout !== undefined) next.timeoutMs = boundedInteger(input.timeoutMs ?? input.timeout, '超时', 1_000, 900_000)
  if (input.maxOutputTokens !== undefined || input.outputBudget !== undefined) {
    next.maxOutputTokens = boundedInteger(input.maxOutputTokens ?? input.outputBudget, '输出预算', 1, 1_000_000)
  }
  if (input.enabled !== undefined) next.enabled = requiredBoolean(input.enabled, '池启用状态')
  if (input.schedulingMode !== undefined || input.scheduling !== undefined) {
    next.schedulingMode = normalizeScheduling(input.schedulingMode ?? input.scheduling)
  }
  if (input.customHeaders !== undefined || input.headers !== undefined) {
    next.customHeaders = parseHeaders(input.customHeaders ?? input.headers)
  }
  return next
}

function parseHeaders(value: unknown): ApiKeyCustomHeader[] {
  const values: ApiKeyCustomHeader[] = []
  if (Array.isArray(value)) {
    for (const candidate of value) {
      if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) throw new ApiKeyPoolError('自定义 Header 参数无效', 400)
      const item = candidate as Record<string, unknown>
      const name = requiredText(item.name ?? item.headerName ?? item.header_name, 'Header 名称', 128)
      const headerValue = requiredText(item.value ?? item.headerValue ?? item.header_value, 'Header 值', 512)
      validateHeaderName(name)
      validateHeaderValue(headerValue)
      values.push({ name, value: headerValue })
    }
  } else if (value && typeof value === 'object') {
    for (const [name, rawValue] of Object.entries(value as Record<string, unknown>)) {
      const normalizedName = requiredText(name, 'Header 名称', 128)
      const headerValue = requiredText(rawValue, 'Header 值', 512)
      validateHeaderName(normalizedName)
      validateHeaderValue(headerValue)
      values.push({ name: normalizedName, value: headerValue })
    }
  } else {
    throw new ApiKeyPoolError('自定义 Header 参数无效', 400)
  }
  if (values.length > 32) throw new ApiKeyPoolError('自定义 Header 数量过多', 400)
  return values
}

function validateHeaderName(name: string): void {
  if (!/^[A-Za-z0-9][A-Za-z0-9-]{0,127}$/.test(name)) throw new ApiKeyPoolError('Header 名称无效', 400)
  if (/authorization|api[-_]?key|token|secret|password|cookie|credential/i.test(name)) {
    throw new ApiKeyPoolError('认证 Header 必须通过 SecretRef 注入', 400)
  }
}

function validateHeaderValue(value: string): void {
  if (/[\u0000-\u001f\u007f]/.test(value)) throw new ApiKeyPoolError('Header 值包含非法控制字符', 400)
}

function normalizeState(value: unknown, timestamp: string, idFactory: () => string): StoredState {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new ApiKeyPoolError('API Key 存储文件格式无效', 500)
  const item = value as Record<string, unknown>
  if (item.schemaVersion !== undefined && item.schemaVersion !== 1) {
    throw new ApiKeyPoolError('API Key 存储文件 schema 版本不受支持', 500)
  }
  const revision = persistedInteger(item, ['revision'], 1, 1, Number.MAX_SAFE_INTEGER)
  const poolsValue = item.pools
  const poolMap: Partial<Record<ApiKeyTier, unknown>> = {}
  if (poolsValue === undefined) {
    // A missing pools field is the only legacy empty-store form we accept.
  } else if (Array.isArray(poolsValue)) {
    const seen = new Set<ApiKeyTier>()
    for (const candidate of poolsValue) {
      if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) throw persistedFormatError()
      const tier = safeText((candidate as Record<string, unknown>).tier)
      if (!isTier(tier) || seen.has(tier)) throw persistedFormatError()
      seen.add(tier)
      poolMap[tier] = candidate
    }
  } else if (poolsValue && typeof poolsValue === 'object') {
    for (const [tier, candidate] of Object.entries(poolsValue as Record<string, unknown>)) {
      if (!isTier(tier) || !candidate || typeof candidate !== 'object' || Array.isArray(candidate)) throw persistedFormatError()
      const candidateItem = candidate as Record<string, unknown>
      if (Object.prototype.hasOwnProperty.call(candidateItem, 'tier')) {
        const declaredTier = persistedText(candidateItem, ['tier'], '', 16)
        if (!declaredTier || declaredTier !== tier) throw persistedFormatError()
      }
      poolMap[tier] = candidate
    }
  } else {
    throw persistedFormatError()
  }
  const pools = {} as Record<ApiKeyTier, StoredPool>
  for (const tier of API_KEY_TIERS) pools[tier] = normalizePool(tier, poolMap[tier], timestamp, idFactory)
  assertUniqueRuntimeBindings(pools, undefined, undefined, 500)
  return { schemaVersion: 1, revision, pools }
}

function normalizePool(tier: ApiKeyTier, value: unknown, timestamp: string, idFactory: () => string): StoredPool {
  const fallback = defaultPool(tier, timestamp)
  if (value === undefined) return fallback
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw persistedFormatError()
  const item = value as Record<string, unknown>
  const pool: StoredPool = { ...fallback }
  pool.displayName = persistedText(item, ['displayName', 'display_name'], fallback.displayName, 120)
  pool.provider = persistedText(item, ['provider', 'providerName', 'provider_name'], '', 160)
  pool.providerType = persistedOptionalText(item, ['providerType', 'provider_type'], 120)
  pool.providerId = runtimeBindingId(persistedField(item, ['providerId', 'provider_id']), 'Provider ID', fallback.providerId!, 500)
  pool.sourceId = runtimeBindingId(persistedField(item, ['sourceId', 'source_id']), 'Source ID', fallback.sourceId!, 500)
  pool.baseUrl = persistedBaseUrl(persistedField(item, ['baseUrl', 'base_url']))
  pool.model = persistedText(item, ['model', 'modelId', 'model_id'], '', 256)
  pool.protocol = runtimeProtocol(persistedField(item, ['protocol', 'protocolMode', 'protocol_mode']) ?? fallback.protocol, 500)
  pool.reasoningEffort = persistedText(item, ['reasoningEffort', 'reasoning_effort', 'reasoning'], fallback.reasoningEffort, 32)
  pool.timeoutMs = persistedInteger(item, ['timeoutMs', 'timeout_ms'], fallback.timeoutMs, 1_000, 900_000)
  pool.maxOutputTokens = persistedInteger(item, ['maxOutputTokens', 'max_output_tokens', 'outputBudget'], fallback.maxOutputTokens, 1, 1_000_000)
  pool.enabled = persistedBoolean(item, ['enabled'], fallback.enabled)
  const scheduling = persistedText(item, ['schedulingMode', 'scheduling_mode', 'scheduler'], fallback.schedulingMode, 64)
  pool.schedulingMode = normalizeScheduling(scheduling)
  pool.customHeaders = normalizePersistedHeaders(persistedField(item, ['customHeaders', 'custom_headers', 'headers']))
  pool.revision = persistedInteger(item, ['revision'], fallback.revision, 1, Number.MAX_SAFE_INTEGER)
  pool.updatedAt = persistedText(item, ['updatedAt', 'updated_at'], timestamp, 64)
  if (Object.prototype.hasOwnProperty.call(item, 'keys') && !Array.isArray(item.keys)) throw persistedFormatError()
  if (Object.prototype.hasOwnProperty.call(item, 'entries') && !Array.isArray(item.entries)) throw persistedFormatError()
  const rawKeys = Array.isArray(item.keys) ? item.keys : Array.isArray(item.entries) ? item.entries : []
  pool.keys = rawKeys.map((candidate, index) => normalizeKey(tier, candidate, index, timestamp, idFactory))
  return pool
}

function normalizeKey(tier: ApiKeyTier, value: unknown, index: number, timestamp: string, _idFactory: () => string): StoredKey {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw persistedFormatError()
  const item = value as Record<string, unknown>
  const secretValue = persistedField(item, ['secret'])
  if (secretValue !== undefined && typeof secretValue !== 'string') throw persistedFormatError()
  const secret = typeof secretValue === 'string' ? secretValue.trim() : ''
  if (secret.length > 16_384) throw persistedFormatError()
  const id = runtimeBindingId(persistedField(item, ['id', 'keyId', 'key_id']), 'Key ID', '', 500)
  const configuredSecretRef = persistedText(item, ['secretRef', 'secret_ref'], '', 512)
  const status = persistedText(item, ['status', 'state'], 'active', 64)
  const enabled = persistedBoolean(item, ['enabled'], status !== 'disabled')
  return {
    id,
    name: persistedText(item, ['name', 'displayName', 'display_name'], `Key ${index + 1}`, 120),
    secret,
    // SecretRef-only entries are valid for deployments where the concrete
    // value is injected by AstrBot/environment rather than held by Node.
    secretRef: configuredSecretRef || `dududa/api-keys/${tier}/${id}`,
    priority: persistedInteger(item, ['priority'], 0, 0, 1_000_000),
    weight: persistedInteger(item, ['weight'], 1, 1, 1_000),
    enabled,
    status: enabled ? status : 'disabled',
    lastSuccessAt: persistedOptionalText(item, ['lastSuccessAt', 'last_success_at'], 64),
    lastFailureAt: persistedOptionalText(item, ['lastFailureAt', 'last_failure_at'], 64),
    cooldownUntil: persistedOptionalText(item, ['cooldownUntil', 'cooldown_until'], 64),
    lastCheckedAt: persistedOptionalText(item, ['lastCheckedAt', 'last_checked_at'], 64),
    createdAt: persistedText(item, ['createdAt', 'created_at'], timestamp, 64),
    updatedAt: persistedText(item, ['updatedAt', 'updated_at'], timestamp, 64),
  }
}

function normalizePersistedHeaders(value: unknown): ApiKeyCustomHeader[] {
  if (value === undefined) return []
  try {
    return parseHeaders(value)
  } catch {
    throw persistedFormatError()
  }
}

function checkRevision(value: unknown, current: number): void {
  if (value === undefined || value === null || value === '') return
  const requested = typeof value === 'number' ? value : Number(value)
  if (!Number.isSafeInteger(requested) || requested !== current) throw new ApiKeyPoolError('API Key 池版本已变化，请刷新后重试', 409)
}

function requiredSecret(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) throw new ApiKeyPoolError('新 Key 必须提供密钥', 400)
  return optionalSecret(value)
}

function optionalSecret(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) throw new ApiKeyPoolError('密钥格式无效', 400)
  const normalized = value.trim()
  if (normalized.length > 16_384) throw new ApiKeyPoolError('密钥长度超过限制', 400)
  return normalized
}

function secretRef(tier: ApiKeyTier, id: string, value: unknown): string {
  if (value === undefined || value === null || value === '') return `dududa/api-keys/${tier}/${id}`
  const normalized = requiredText(value, 'SecretRef', 160)
  if (!/^[A-Za-z0-9][A-Za-z0-9._/-]{1,159}$/.test(normalized)) throw new ApiKeyPoolError('SecretRef 格式无效', 400)
  return normalized
}

function keyName(value: unknown, index: number): string {
  return value === undefined || value === null || value === ''
    ? `Key ${index + 1}`
    : requiredText(value, 'Key 名称', 120)
}

function providerUrl(value: unknown): string {
  const normalized = requiredText(value, 'Base URL', 512)
  if (!hasExplicitHttpAuthority(normalized)) {
    throw new ApiKeyPoolError('Base URL 必须是 HTTP(S) 地址', 400)
  }
  let parsed: URL
  try {
    parsed = new URL(normalized)
  } catch {
    throw new ApiKeyPoolError('Base URL 必须是 HTTP(S) 地址', 400)
  }
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new ApiKeyPoolError('Base URL 必须是无凭据、无查询参数的 HTTP(S) 地址', 400)
  }
  return parsed.toString().replace(/\/$/, '')
}

/** Return only a safe, credential-free URL from an untrusted stored snapshot. */
function safePublicBaseUrl(value: unknown, fallback: string): string {
  const normalized = boundedSafe(value, fallback, 2_048)
  if (!normalized) return fallback
  if (!hasExplicitHttpAuthority(normalized)) return fallback
  try {
    const parsed = new URL(normalized)
    if (
      !['http:', 'https:'].includes(parsed.protocol)
      || parsed.username
      || parsed.password
      || parsed.search
      || parsed.hash
    ) return fallback
    return parsed.toString().replace(/\/$/, '')
  } catch {
    return fallback
  }
}

function hasExplicitHttpAuthority(value: string): boolean {
  return /^https?:\/\/[^/\\?#\s]+(?:[/?#]|$)/i.test(value) && !value.includes('\\')
}

function normalizeScheduling(value: unknown): string {
  const normalized = requiredText(value, '调度模式', 64).toLowerCase().replace(/-/g, '_')
  if (!['round_robin', 'priority', 'health_first', 'weighted', 'random'].includes(normalized)) {
    throw new ApiKeyPoolError('调度模式无效', 400)
  }
  return normalized
}

function runtimeProtocol(value: unknown, status = 400): string {
  const normalized = typeof value === 'string' ? value.trim().toLowerCase().replace(/-/g, '_') : ''
  if (['openai', 'chat_completion', 'openai_chat_completion', 'openai_chat_completions'].includes(normalized)) {
    return 'openai_chat_completions'
  }
  if (['anthropic', 'anthropic_message', 'anthropic_messages'].includes(normalized)) {
    return 'anthropic_messages'
  }
  throw new ApiKeyPoolError('协议不受当前 AstrBot Runtime 支持', status)
}

function selectProbeKey(pool: StoredPool): StoredKey | undefined {
  return [...pool.keys]
    .filter((key) => key.enabled && key.secret)
    .sort((left, right) => {
      const priority = left.priority - right.priority
      if (priority) return priority
      const weight = right.weight - left.weight
      if (weight) return weight
      return left.id < right.id ? -1 : left.id > right.id ? 1 : 0
    })[0]
}

function safeProbeMessage(value: unknown, ok: boolean, secret?: string): string {
  const candidate = safeText(value).replace(secret ? escapeRegExp(secret) : /$^/, '[已隐藏凭据]')
  if (!candidate) return ok ? 'Provider 探测成功' : 'Provider 探测失败'
  // Provider error bodies frequently echo Authorization headers.  Return a
  // stable operator-facing message rather than forwarding an upstream body.
  if (/bearer\s+|(?:sk|rk|xai|key)[-_]?[A-Za-z0-9_-]{12,}|secret|password|authorization|token/i.test(candidate)) {
    return ok ? 'Provider 探测成功' : 'Provider 探测失败（上游返回敏感错误信息）'
  }
  return candidate.slice(0, 500)
}

function escapeRegExp(value: string): RegExp {
  return new RegExp(value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')
}

function sanitizeHeaders(value: unknown): ApiKeyCustomHeader[] {
  const result: ApiKeyCustomHeader[] = []
  const entries: Array<[unknown, unknown]> = Array.isArray(value)
    ? value.map((candidate) => {
      if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return [undefined, undefined]
      const item = candidate as Record<string, unknown>
      return [item.name ?? item.headerName ?? item.header_name, item.value ?? item.headerValue ?? item.header_value]
    })
    : value && typeof value === 'object'
      ? Object.entries(value as Record<string, unknown>)
      : []
  for (const [rawName, rawValue] of entries) {
    const name = safeText(rawName)
    const headerValue = safeText(rawValue)
    if (!name || !headerValue || !/^[A-Za-z0-9][A-Za-z0-9-]{0,127}$/.test(name)) continue
    if (/authorization|api[-_]?key|token|secret|password|cookie|credential/i.test(name)) continue
    result.push({ name, value: headerValue.slice(0, 2_048) })
    if (result.length >= 32) break
  }
  return result
}

function sanitizeReceipt(value: unknown): ApiKeyWriteReceipt {
  const item = value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
  // Receipt IDs are operationally opaque.  Generate a new one instead of
  // trusting an upstream value that could accidentally contain a credential.
  return {
    id: `receipt-${randomUUID()}`,
    status: 'committed',
    committedAt: boundedSafe(item.committedAt ?? item.committed_at ?? item.updatedAt ?? item.updated_at, new Date().toISOString(), 64),
  }
}

function boundedSafe(value: unknown, fallback: string, maxLength: number): string {
  const normalized = safeText(value)
  return normalized ? normalized.slice(0, maxLength) : fallback
}

function sanitizeMasked(value: string): string {
  if (!value) return ''
  // Only preserve the two shapes emitted by maskApiKey().  A stray masking
  // character in untrusted adapter text must not make that text public.
  if (/^•{8}$/.test(value) || /^.{4}•{4,12}.{4}$/u.test(value)) return value
  return '••••••••'
}

function persistedFormatError(): ApiKeyPoolError {
  return new ApiKeyPoolError('API Key 存储文件格式无效', 500)
}

function persistedField(item: Record<string, unknown>, names: string[]): unknown {
  for (const name of names) {
    if (Object.prototype.hasOwnProperty.call(item, name)) return item[name]
  }
  return undefined
}

function persistedText(
  item: Record<string, unknown>,
  names: string[],
  fallback: string,
  maxLength: number,
): string {
  const value = persistedField(item, names)
  if (value === undefined) return fallback
  if (typeof value !== 'string') throw persistedFormatError()
  const normalized = value.trim()
  if (normalized.length > maxLength) throw persistedFormatError()
  return normalized || fallback
}

function persistedOptionalText(item: Record<string, unknown>, names: string[], maxLength: number): string | undefined {
  const normalized = persistedText(item, names, '', maxLength)
  return normalized || undefined
}

function persistedInteger(
  item: Record<string, unknown>,
  names: string[],
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  const value = persistedField(item, names)
  if (value === undefined) return fallback
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw persistedFormatError()
  }
  return value
}

function persistedBoolean(item: Record<string, unknown>, names: string[], fallback: boolean): boolean {
  const value = persistedField(item, names)
  if (value === undefined) return fallback
  if (typeof value !== 'boolean') throw persistedFormatError()
  return value
}

function persistedBaseUrl(value: unknown): string {
  if (value === undefined || value === null || value === '') return ''
  if (typeof value === 'string' && !value.trim()) return ''
  try {
    return providerUrl(value)
  } catch {
    throw persistedFormatError()
  }
}

function isTier(value: unknown): value is ApiKeyTier {
  return typeof value === 'string' && (API_KEY_TIERS as readonly string[]).includes(value)
}

function requiredText(value: unknown, field: string, maxLength: number): string {
  if (typeof value !== 'string' || !value.trim()) throw new ApiKeyPoolError(`${field}不能为空`, 400)
  const normalized = value.trim()
  if (normalized.length > maxLength) throw new ApiKeyPoolError(`${field}长度超过限制`, 400)
  return normalized
}

function optionalText(value: unknown, field: string, maxLength: number): string | undefined {
  if (value === undefined || value === null || value === '') return undefined
  return requiredText(value, field, maxLength)
}

function defaultProviderId(tier: ApiKeyTier): string {
  return {
    haiku: 'astrbot-luna',
    sonnet: 'astrbot-terra',
    opus: 'astrbot-sol',
  }[tier]
}

function defaultSourceId(tier: ApiKeyTier): string {
  return `dududa-${tier}-source`
}

function runtimeBindingId(value: unknown, field: string, fallback: string, status = 400): string {
  const normalized = value === undefined || value === null || value === ''
    ? fallback
    : typeof value === 'string'
      ? value.trim()
      : ''
  if (!normalized || !RUNTIME_BINDING_ID_RE.test(normalized)) {
    throw new ApiKeyPoolError(`${field}格式无效`, status)
  }
  return normalized
}

function assertUniqueRuntimeBindings(
  pools: Record<ApiKeyTier, StoredPool>,
  replacementTier?: ApiKeyTier,
  replacement?: StoredPool,
  status = 400,
): void {
  const values = API_KEY_TIERS.map((tier) => replacementTier === tier && replacement ? replacement : pools[tier])
  const providerIds = values.map((pool) => pool.providerId)
  const sourceIds = values.map((pool) => pool.sourceId)
  if (new Set(providerIds).size !== providerIds.length || new Set(sourceIds).size !== sourceIds.length) {
    throw new ApiKeyPoolError('Provider ID 和 Source ID 必须在三档池中唯一', status)
  }
}

function safeText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function optionalSafeText(value: unknown): string | undefined {
  const normalized = safeText(value)
  return normalized || undefined
}

function requiredBoolean(value: unknown, field: string): boolean {
  if (typeof value !== 'boolean') throw new ApiKeyPoolError(`${field}参数无效`, 400)
  return value
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function boundedInteger(value: unknown, field: string, minimum: number, maximum: number): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new ApiKeyPoolError(`${field}参数无效`, 400)
  }
  return value
}

function boundedOrDefault(value: unknown, fallback: number, minimum: number, maximum: number): number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= minimum && value <= maximum ? value : fallback
}

function priorityValue(value: unknown, fallback: number): number {
  return value === undefined ? fallback : boundedInteger(value, '优先级', 0, 1_000_000)
}

function weightValue(value: unknown, fallback: number): number {
  return value === undefined ? fallback : boundedInteger(value, '权重', 1, 1_000)
}

function positiveInteger(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : fallback
}

function clampInteger(value: unknown, minimum: number, maximum: number, fallback: number): number {
  return typeof value === 'number' && Number.isSafeInteger(value) ? Math.min(maximum, Math.max(minimum, value)) : fallback
}

function nonnegativeInteger(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.round(value) : fallback
}

function elapsed(started: number): number {
  return Math.max(0, Date.now() - started)
}

function isMissingFile(error: unknown): boolean {
  return Boolean(error && typeof error === 'object' && (error as NodeJS.ErrnoException).code === 'ENOENT')
}
