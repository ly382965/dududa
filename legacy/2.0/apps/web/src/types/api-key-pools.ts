/**
 * The browser projection of a Dududa provider credential pool.
 *
 * A raw credential is deliberately absent from every interface in this file.
 * `secret` exists only on explicit write request DTOs and must never be copied
 * into a response, store, or component state that survives the request.
 */

export type ApiKeyTier = 'haiku' | 'sonnet' | 'opus'
export type ApiKeyProtocol = string
export type ApiKeyReasoningEffort = 'off' | 'low' | 'medium' | 'high' | string
export type ApiKeySchedulingMode = 'round_robin' | 'priority' | 'health_first' | string
export type ApiKeyStatus = 'active' | 'disabled' | 'cooldown' | 'unavailable' | string

export interface ApiKeyCustomHeader {
  name: string
  value: string
}

export interface ApiKeyEntry {
  id: string
  name: string
  /** Deployment SecretRef identifier, never the secret value. */
  secretRef: string
  /** Server-provided masked value or suffix; may be empty when unavailable. */
  masked: string
  priority: number
  weight: number
  enabled: boolean
  status: ApiKeyStatus
  lastSuccessAt?: string
  lastFailureAt?: string
  cooldownUntil?: string
  createdAt?: string
  updatedAt?: string
}

export interface ApiKeyPool {
  tier: ApiKeyTier
  displayName: string
  provider: string
  providerType?: string
  providerId?: string
  sourceId?: string
  baseUrl: string
  model: string
  protocol: ApiKeyProtocol
  reasoningEffort: ApiKeyReasoningEffort
  timeoutMs: number
  maxOutputTokens: number
  enabled: boolean
  schedulingMode: ApiKeySchedulingMode
  customHeaders: ApiKeyCustomHeader[]
  revision: number | string
  updatedAt?: string
  runtimeSync?: {
    status: 'synced' | 'pending' | 'error' | string
    message?: string
    updatedAt?: string
  }
  keys: ApiKeyEntry[]
}

export interface ApiKeyPoolsResponse {
  schemaVersion: 1
  /** Monotonic collection revision used for optimistic concurrency. */
  revision: number | string
  pools: ApiKeyPool[]
}

export interface ApiKeyWriteReceipt {
  id?: string
  status?: string
  committedAt?: string
  message?: string
}

export interface ApiKeyMutationResponse {
  schemaVersion?: 1
  revision?: number | string
  pool?: ApiKeyPool
  key?: ApiKeyEntry
  writeReceipt?: ApiKeyWriteReceipt
  receipt?: ApiKeyWriteReceipt
}

export interface ApiKeyPoolUpdateRequest {
  displayName: string
  provider: string
  providerType?: string
  providerId?: string
  sourceId?: string
  baseUrl: string
  model: string
  protocol: ApiKeyProtocol
  reasoningEffort: ApiKeyReasoningEffort
  timeoutMs: number
  maxOutputTokens: number
  enabled: boolean
  schedulingMode: ApiKeySchedulingMode
  customHeaders: ApiKeyCustomHeader[]
  revision: number | string
}

export interface ApiKeyCreateRequest {
  name: string
  secret: string
  secretRef?: string
  priority?: number
  weight?: number
  enabled?: boolean
}

export interface ApiKeyUpdateRequest {
  name?: string
  secret?: string
  secretRef?: string
  priority?: number
  weight?: number
  enabled?: boolean
  revision?: number | string
}

export interface ApiKeyPoolTestResult {
  status: 'ok' | 'error' | 'unavailable' | string
  message: string
  latencyMs?: number
  model?: string
  checkedAt?: string
  /** Latest pool revision after the server records health metadata. */
  revision?: number | string
}

export interface ApiKeyPoolsAdapter {
  runtimeStatus?(): Promise<RuntimeConfigStatus>
  applyRuntime?(revision: number | string): Promise<RuntimeConfigStatus>
  list(): Promise<ApiKeyPoolsResponse>
  updatePool(tier: ApiKeyTier, request: ApiKeyPoolUpdateRequest): Promise<ApiKeyMutationResponse>
  createKey(tier: ApiKeyTier, request: ApiKeyCreateRequest): Promise<ApiKeyMutationResponse>
  updateKey(tier: ApiKeyTier, keyId: string, request: ApiKeyUpdateRequest): Promise<ApiKeyMutationResponse>
  deleteKey(tier: ApiKeyTier, keyId: string): Promise<ApiKeyMutationResponse>
  testPool(tier: ApiKeyTier): Promise<ApiKeyPoolTestResult>
}

export interface RuntimeConfigStatus {
  cleanupPending?: boolean
  status: 'applied' | 'pending' | 'applying' | 'unavailable'
  savedRevision: number | string | null
  ready: boolean
  message: string
  checkedAt: string
  scope: 'dududa_only'
}

export const API_KEY_TIERS: readonly ApiKeyTier[] = ['haiku', 'sonnet', 'opus']

export const API_KEY_TIER_LABELS: Record<ApiKeyTier, string> = {
  haiku: 'Luna · 轻量推理',
  sonnet: 'Terra · 标准推理',
  opus: 'Sol · 深度推理',
}

export const API_KEY_TIER_DESCRIPTIONS: Record<ApiKeyTier, string> = {
  haiku: '感知与普通直接对话',
  sonnet: '工具查询与中等复杂任务',
  opus: '高复杂度或长上下文任务',
}

export const API_KEY_TIER_PROVIDER_IDS: Record<ApiKeyTier, string> = {
  haiku: 'astrbot-luna',
  sonnet: 'astrbot-terra',
  opus: 'astrbot-sol',
}

export function emptyApiKeyPool(tier: ApiKeyTier): ApiKeyPool {
  return {
    tier,
    displayName: API_KEY_TIER_LABELS[tier],
    provider: '',
    providerId: API_KEY_TIER_PROVIDER_IDS[tier],
    sourceId: `dududa-${tier}-source`,
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
    keys: [],
  }
}
