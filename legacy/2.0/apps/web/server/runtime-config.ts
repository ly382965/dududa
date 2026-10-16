import type { RuntimeConfigStatus } from '../src/types/api-key-pools'

const reasons: Record<string, string> = {
  pool_revision_changed: '配置已被修改，请刷新后重新应用',
  runtime_apply_in_progress: '另一项 Runtime 应用正在执行，请稍后刷新',
  runtime_shutting_down: 'Runtime 正在停止，请重连后再应用',
  runtime_requests_active: 'Runtime 正在处理请求，请结束后重新应用',
  host_configuration_changed: '服务端配置已变化，请刷新后重试',
  bounded_host_adapter_required: '当前 AstrBot 缺少已验证的请求适配器，不能应用',
  current_host_evidence_required: '当前宿主缺少 Provider 验证证据，不能应用',
  provider_policy_evidence_required: 'Provider 留存策略尚未验证，不能应用',
  candidate_provider_probe_failed: '新 Provider 模型或输出验证失败，旧配置已保留',
  candidate_provider_health_failed: '新 Provider 健康检查失败，旧配置已保留',
  configuration_rollback_failed: '配置回滚失败，需要管理员检查；请勿继续应用',
  runtime_apply_failed: '应用失败，旧 Runtime 保留；请检查三档是否均为已验证的官方 DeepSeek 配置',
  runtime_configuration_current: '已应用到当前 Dududa Runtime',
  runtime_configuration_pending: '已保存，尚未应用到当前 Runtime',
}

export class RuntimeConfigClientError extends Error {
  constructor(message: string, readonly status: number) { super(message) }
}

export interface RuntimeConfigClient {
  status(): Promise<RuntimeConfigStatus>
  apply(revision: number | string): Promise<RuntimeConfigStatus>
}

export class HttpRuntimeConfigClient implements RuntimeConfigClient {
  private readonly baseUrl: string
  constructor(baseUrl: string, private readonly apiKey: string | (() => string),
    private readonly fetchImpl: typeof fetch = fetch) {
    const parsed = new URL(baseUrl)
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('Runtime API 协议无效')
    this.baseUrl = parsed.toString().replace(/\/$/, '')
  }

  status() { return this.request() }
  apply(revision: number | string) { return this.request(revision) }

  private async request(revision?: number | string): Promise<RuntimeConfigStatus> {
    const token = (typeof this.apiKey === 'function' ? this.apiKey() : this.apiKey).trim()
    if (!token) throw new RuntimeConfigClientError('Runtime 服务端认证未配置', 503)
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), revision === undefined ? 5000 : 330_000)
    timer.unref?.()
    try {
      const response = await this.fetchImpl(`${this.baseUrl}/plugins/extensions/astrbot_plugin_dududa_core/runtime/configuration${revision === undefined ? '' : '/apply'}`, {
        method: revision === undefined ? 'GET' : 'POST',
        headers: { 'X-API-Key': token, 'Content-Type': 'application/json', Accept: 'application/json' },
        ...(revision === undefined ? {} : { body: JSON.stringify({ revision }) }), signal: controller.signal,
      })
      const envelope = await response.json().catch(() => ({})) as Record<string, unknown>
      if (!response.ok || envelope.status !== 'ok') {
        throw new RuntimeConfigClientError(response.status === 401 || response.status === 403
          ? 'Runtime 服务端认证失败' : reasons[String(envelope.message)] || 'Runtime 配置应用请求失败，请刷新状态确认',
        response.ok ? 502 : response.status)
      }
      return projectRuntimeConfigStatus(envelope.data)
    } catch (error) {
      if (error instanceof RuntimeConfigClientError) throw error
      throw new RuntimeConfigClientError('Runtime 配置接口不可用或超时，请刷新确认实际状态', 503)
    } finally { clearTimeout(timer) }
  }
}

export function projectRuntimeConfigStatus(value: unknown): RuntimeConfigStatus {
  const item = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  if (!['applied', 'pending', 'applying', 'unavailable'].includes(String(item.status))) {
    throw new RuntimeConfigClientError('Runtime 配置状态格式无效', 502)
  }
  return {
    status: item.status as RuntimeConfigStatus['status'],
    savedRevision: typeof item.savedRevision === 'string' || typeof item.savedRevision === 'number' ? item.savedRevision : null,
    ready: item.ready === true,
    message: item.status === 'applied' && item.cleanupPending === true
      ? '新配置已应用；旧连接清理待重试，不影响新 Runtime'
      : reasons[String(item.reason)] || '请刷新 Runtime 配置状态',
    cleanupPending: item.cleanupPending === true,
    checkedAt: typeof item.checkedAt === 'string' && !Number.isNaN(Date.parse(item.checkedAt)) ? item.checkedAt : '',
    scope: 'dududa_only',
  }
}
