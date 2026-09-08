import type {
  ApiKeyCreateRequest,
  ApiKeyCustomHeader,
  ApiKeyEntry,
  ApiKeyMutationResponse,
  ApiKeyPool,
  ApiKeyPoolTestResult,
  ApiKeyPoolUpdateRequest,
  ApiKeyPoolsAdapter,
  ApiKeyPoolsResponse,
  ApiKeyTier,
  ApiKeyUpdateRequest,
  ApiKeyWriteReceipt,
  RuntimeConfigStatus,
} from '../types/api-key-pools'
import { API_KEY_TIERS, emptyApiKeyPool } from '../types/api-key-pools'

type JsonRecord = Record<string, unknown>

export class ApiKeyPoolsClientError extends Error {
  constructor(message: string, readonly status = 0) {
    super(message)
    this.name = 'ApiKeyPoolsClientError'
  }
}

function record(value: unknown): JsonRecord | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonRecord
    : undefined
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function firstText(item: JsonRecord, ...keys: string[]): string {
  for (const key of keys) {
    const value = text(item[key])
    if (value) return value
  }
  return ''
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function positiveNumber(value: unknown, fallback: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return fallback
  return Math.round(value)
}

function nonnegativeNumber(value: unknown, fallback: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return fallback
  return Math.round(value)
}

function revision(value: unknown): number | string {
  if (typeof value === 'number' && Number.isSafeInteger(value) && value > 0) return value
  const stringValue = text(value)
  return stringValue || 1
}

function tierValue(value: unknown): ApiKeyTier | undefined {
  const candidate = text(value).toLowerCase()
  return API_KEY_TIERS.includes(candidate as ApiKeyTier) ? candidate as ApiKeyTier : undefined
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function sensitiveHeader(name: string): boolean {
  return /authorization|api[-_]?key|token|secret|password|cookie|credential/i.test(name)
}

function parseHeaders(value: unknown): ApiKeyCustomHeader[] {
  const result: ApiKeyCustomHeader[] = []
  if (Array.isArray(value)) {
    for (const candidate of value) {
      const item = record(candidate)
      if (!item) continue
      const name = firstText(item, 'name', 'headerName', 'header_name')
      const headerValue = firstText(item, 'value', 'headerValue', 'header_value')
      if (name && headerValue && !sensitiveHeader(name)) result.push({ name, value: headerValue })
    }
  } else {
    const objectValue = record(value)
    if (!objectValue) return result
    for (const [name, rawValue] of Object.entries(objectValue)) {
      const headerValue = text(rawValue)
      if (name.trim() && headerValue && !sensitiveHeader(name)) result.push({ name: name.trim(), value: headerValue })
    }
  }
  return result.slice(0, 32)
}

function parseKey(value: unknown, index: number): ApiKeyEntry | undefined {
  const item = record(value)
  if (!item) return undefined
  const id = firstText(item, 'id', 'keyId', 'key_id')
  if (!id) return undefined
  const status = firstText(item, 'status', 'state') || (booleanValue(item.enabled, true) ? 'active' : 'disabled')
  return {
    id,
    name: firstText(item, 'name', 'displayName', 'display_name') || `Key ${index + 1}`,
    secretRef: firstText(item, 'secretRef', 'secret_ref', 'secretId', 'secret_id'),
    masked: firstText(item, 'masked', 'maskedKey', 'masked_key', 'suffix')
      // Never use `key`, `secret`, or `value` as a fallback: those fields can
      // contain the raw credential on a misconfigured upstream response.
      .replace(/\s+/g, ' '),
    priority: nonnegativeNumber(item.priority, 0),
    weight: positiveNumber(item.weight, 1),
    enabled: booleanValue(item.enabled, status !== 'disabled'),
    status,
    ...(firstText(item, 'lastSuccessAt', 'last_success_at') ? { lastSuccessAt: firstText(item, 'lastSuccessAt', 'last_success_at') } : {}),
    ...(firstText(item, 'lastFailureAt', 'last_failure_at') ? { lastFailureAt: firstText(item, 'lastFailureAt', 'last_failure_at') } : {}),
    ...(firstText(item, 'cooldownUntil', 'cooldown_until') ? { cooldownUntil: firstText(item, 'cooldownUntil', 'cooldown_until') } : {}),
    ...(firstText(item, 'createdAt', 'created_at') ? { createdAt: firstText(item, 'createdAt', 'created_at') } : {}),
    ...(firstText(item, 'updatedAt', 'updated_at') ? { updatedAt: firstText(item, 'updatedAt', 'updated_at') } : {}),
  }
}

export function parseApiKeyPool(value: unknown): ApiKeyPool {
  const item = record(value)
  const tier = tierValue(item?.tier)
  if (!item || !tier) throw new ApiKeyPoolsClientError('API Key 池响应缺少有效 tier')
  const fallback = emptyApiKeyPool(tier)
  const rawKeys = array(item.keys ?? item.entries ?? item.keyEntries ?? item.key_entries)
  return {
    ...fallback,
    displayName: firstText(item, 'displayName', 'display_name', 'name') || fallback.displayName,
    provider: firstText(item, 'provider', 'providerName', 'provider_name'),
    ...(firstText(item, 'providerType', 'provider_type') ? { providerType: firstText(item, 'providerType', 'provider_type') } : {}),
    ...(firstText(item, 'providerId', 'provider_id') ? { providerId: firstText(item, 'providerId', 'provider_id') } : {}),
    ...(firstText(item, 'sourceId', 'source_id') ? { sourceId: firstText(item, 'sourceId', 'source_id') } : {}),
    baseUrl: firstText(item, 'baseUrl', 'base_url', 'apiBase', 'api_base'),
    model: firstText(item, 'model', 'modelId', 'model_id'),
    protocol: firstText(item, 'protocol', 'protocolMode', 'protocol_mode') || fallback.protocol,
    reasoningEffort: firstText(item, 'reasoningEffort', 'reasoning_effort', 'reasoning') || fallback.reasoningEffort,
    timeoutMs: positiveNumber(item.timeoutMs ?? item.timeout_ms, fallback.timeoutMs),
    maxOutputTokens: positiveNumber(item.maxOutputTokens ?? item.max_output_tokens, fallback.maxOutputTokens),
    enabled: booleanValue(item.enabled, fallback.enabled),
    schedulingMode: firstText(item, 'schedulingMode', 'scheduling_mode', 'scheduler') || fallback.schedulingMode,
    customHeaders: parseHeaders(item.customHeaders ?? item.custom_headers ?? item.headers),
    revision: revision(item.revision ?? item.configRevision ?? item.config_revision),
    ...(firstText(item, 'updatedAt', 'updated_at') ? { updatedAt: firstText(item, 'updatedAt', 'updated_at') } : {}),
    ...(record(item.runtimeSync ?? item.runtime_sync)
      ? { runtimeSync: parseRuntimeSync(item.runtimeSync ?? item.runtime_sync) }
      : {}),
    keys: rawKeys.map(parseKey).filter((entry): entry is ApiKeyEntry => Boolean(entry)),
  }
}

function parseRuntimeSync(value: unknown): ApiKeyPool['runtimeSync'] {
  const item = record(value)
  if (!item) return undefined
  const status = firstText(item, 'status', 'state') || 'pending'
  return {
    status,
    ...(firstText(item, 'message', 'detail') ? { message: redactSensitiveText(firstText(item, 'message', 'detail')) } : {}),
    ...(firstText(item, 'updatedAt', 'updated_at') ? { updatedAt: firstText(item, 'updatedAt', 'updated_at') } : {}),
  }
}

function parseReceipt(value: unknown): ApiKeyWriteReceipt | undefined {
  const item = record(value)
  if (!item) return undefined
  const parsed: ApiKeyWriteReceipt = {}
  const id = firstText(item, 'id', 'receiptId', 'receipt_id')
  const status = firstText(item, 'status', 'state')
  const committedAt = firstText(item, 'committedAt', 'committed_at', 'updatedAt', 'updated_at')
  const message = firstText(item, 'message', 'detail')
  if (id) parsed.id = id
  if (status) parsed.status = status
  if (committedAt) parsed.committedAt = committedAt
  if (message) parsed.message = redactSensitiveText(message)
  return parsed
}

function parseMutation(value: unknown): ApiKeyMutationResponse {
  const item = record(value)
  if (!item) return {}
  const poolValue = item.pool ?? (tierValue(item.tier) ? item : undefined)
  const keyValue = item.key ?? item.entry
  return {
    ...(poolValue ? { pool: parseApiKeyPool(poolValue) } : {}),
    ...(keyValue ? (() => {
      const parsed = parseKey(keyValue, 0)
      return parsed ? { key: parsed } : {}
    })() : {}),
    ...(item.writeReceipt ? { writeReceipt: parseReceipt(item.writeReceipt) } : {}),
    ...(item.receipt ? { receipt: parseReceipt(item.receipt) } : {}),
  }
}

function parseTest(value: unknown): ApiKeyPoolTestResult {
  const item = record(value)
  if (!item) return { status: 'error', message: 'Provider 探测返回格式无效' }
  const status = firstText(item, 'status', 'state') || 'error'
  return {
    status,
    message: redactSensitiveText(firstText(item, 'message', 'detail', 'error') || 'Provider 探测完成'),
    ...(typeof item.latencyMs === 'number' && Number.isFinite(item.latencyMs) && item.latencyMs >= 0 ? { latencyMs: Math.round(item.latencyMs) } : {}),
    ...(firstText(item, 'model', 'modelId', 'model_id') ? { model: firstText(item, 'model', 'modelId', 'model_id') } : {}),
    ...(firstText(item, 'checkedAt', 'checked_at') ? { checkedAt: firstText(item, 'checkedAt', 'checked_at') } : {}),
    ...(item.revision !== undefined ? { revision: revision(item.revision) } : {}),
  }
}

function redactSensitiveText(value: string): string {
  return value
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]{8,}/gi, 'Bearer [已隐藏]')
    .replace(/(?:sk|rk|xai|AIza|key)[-_]?[A-Za-z0-9_-]{12,}/gi, '[已隐藏凭据]')
}

function safeErrorMessage(value: unknown, status: number): string {
  const item = record(value)
  const candidate = item ? firstText(item, 'error', 'message', 'detail') : ''
  const safe = redactSensitiveText(candidate)
  if (!safe || /secret|password|cookie|authorization/i.test(safe) && /value|raw|plain|token/i.test(safe)) {
    return `API Key 管理请求失败（${status}）`
  }
  return safe
}

export class HttpApiKeyPoolsAdapter implements ApiKeyPoolsAdapter {
  constructor(private readonly baseUrl = '', private readonly fetchImpl: typeof fetch = fetch) {}

  async runtimeStatus(): Promise<RuntimeConfigStatus> {
    return this.runtimeResult(await this.request('/api/api-keys/runtime'))
  }

  async applyRuntime(revision: number | string): Promise<RuntimeConfigStatus> {
    return this.runtimeResult(await this.request('/api/api-keys/runtime/apply', {
      method: 'POST', body: JSON.stringify({ revision }),
    }))
  }

  private runtimeResult(value: unknown): RuntimeConfigStatus {
    const item = record(value)
    if (!item || !['applied', 'pending', 'applying', 'unavailable'].includes(text(item.status))) {
      throw new ApiKeyPoolsClientError('Runtime 配置状态格式无效')
    }
    return { status: item.status as RuntimeConfigStatus['status'], savedRevision: item.savedRevision === null ? null : revision(item.savedRevision),
      ready: item.ready === true, message: redactSensitiveText(text(item.message)), checkedAt: text(item.checkedAt), scope: 'dududa_only', cleanupPending: item.cleanupPending === true }
  }

  async list(): Promise<ApiKeyPoolsResponse> {
    const body = await this.request('/api/api-keys')
    const item = record(body)
    const rawPools = array(item?.pools)
    const parsed = rawPools.map(parseApiKeyPool)
    const byTier = new Map(parsed.map((pool) => [pool.tier, pool]))
    // The API always projects all three logical pools. Filling absent pools
    // keeps the UI deterministic while an empty deployment is being prepared.
    return {
      schemaVersion: 1,
      revision: revision(item?.revision),
      pools: API_KEY_TIERS.map((tier) => byTier.get(tier) ?? emptyApiKeyPool(tier)),
    }
  }

  async updatePool(tier: ApiKeyTier, request: ApiKeyPoolUpdateRequest): Promise<ApiKeyMutationResponse> {
    return parseMutation(await this.request(`/api/api-keys/pools/${encodeURIComponent(tier)}`, {
      method: 'PUT',
      body: JSON.stringify(request),
    }))
  }

  async createKey(tier: ApiKeyTier, request: ApiKeyCreateRequest): Promise<ApiKeyMutationResponse> {
    if (!request.secret.trim()) throw new ApiKeyPoolsClientError('新 Key 不能为空')
    return parseMutation(await this.request(`/api/api-keys/pools/${encodeURIComponent(tier)}/keys`, {
      method: 'POST',
      body: JSON.stringify(request),
    }))
  }

  async updateKey(tier: ApiKeyTier, keyId: string, request: ApiKeyUpdateRequest): Promise<ApiKeyMutationResponse> {
    const payload = { ...request }
    if (payload.secret !== undefined && !payload.secret.trim()) delete payload.secret
    return parseMutation(await this.request(
      `/api/api-keys/pools/${encodeURIComponent(tier)}/keys/${encodeURIComponent(keyId)}`,
      { method: 'PUT', body: JSON.stringify(payload) },
    ))
  }

  async deleteKey(tier: ApiKeyTier, keyId: string): Promise<ApiKeyMutationResponse> {
    return parseMutation(await this.request(
      `/api/api-keys/pools/${encodeURIComponent(tier)}/keys/${encodeURIComponent(keyId)}`,
      { method: 'DELETE' },
    ))
  }

  async testPool(tier: ApiKeyTier): Promise<ApiKeyPoolTestResult> {
    return parseTest(await this.request(`/api/api-keys/pools/${encodeURIComponent(tier)}/test`, {
      method: 'POST',
      body: JSON.stringify({}),
    }))
  }

  private async request(path: string, init: RequestInit = {}): Promise<unknown> {
    let response: Response
    try {
      // Native browser fetch rejects an arbitrary receiver. Copy it to a local
      // before calling so the default adapter does not invoke it as an object
      // method (`this.fetchImpl(...)`).
      const fetchImpl = this.fetchImpl
      response = await fetchImpl(`${this.baseUrl}${path}`, {
        ...init,
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          ...(init.body ? { 'Content-Type': 'application/json' } : {}),
          ...init.headers,
        },
      })
    } catch {
      throw new ApiKeyPoolsClientError('API Key 管理接口不可用')
    }
    const body = await response.json().catch(() => ({})) as unknown
    if (!response.ok) throw new ApiKeyPoolsClientError(safeErrorMessage(body, response.status), response.status)
    return body
  }
}

export const apiKeyPoolsAdapter = new HttpApiKeyPoolsAdapter()
