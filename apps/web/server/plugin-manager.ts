import type {
  PluginInstallResult,
  RuntimePlugin,
  RuntimePluginCatalog,
} from '../src/types/plugin-management'
import type { BrowserUpload } from './uploads'

interface AstrBotEnvelope {
  status?: string
  message?: string | null
  data?: unknown
}

export interface PluginManagerClient {
  catalog(): Promise<RuntimePluginCatalog>
  installGithub(repository: string, ignoreVersionCheck?: boolean): Promise<PluginInstallResult>
  installUpload(upload: BrowserUpload, ignoreVersionCheck?: boolean): Promise<PluginInstallResult>
}

export class PluginManagerClientError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'PluginManagerClientError'
  }
}

export class UnavailablePluginManagerClient implements PluginManagerClient {
  constructor(private readonly reason = 'AstrBot 插件管理凭据未配置') {}

  async catalog(): Promise<RuntimePluginCatalog> {
    return { available: false, plugins: [], reason: this.reason }
  }

  async installGithub(): Promise<PluginInstallResult> {
    throw new PluginManagerClientError(this.reason, 503)
  }

  async installUpload(): Promise<PluginInstallResult> {
    throw new PluginManagerClientError(this.reason, 503)
  }
}

type ApiKeyProvider = string | (() => string)

export class HttpAstrBotPluginManagerClient implements PluginManagerClient {
  private readonly baseUrl: string

  constructor(
    baseUrl: string,
    private readonly apiKey: ApiKeyProvider,
    private readonly timeoutMs = 120_000,
  ) {
    const parsed = new URL(baseUrl)
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('AstrBot 插件 API URL 协议无效')
    this.baseUrl = parsed.toString().replace(/\/$/, '')
  }

  async catalog(): Promise<RuntimePluginCatalog> {
    if (!this.readApiKey()) {
      return { available: false, plugins: [], reason: 'AstrBot plugin scope API Key 未配置' }
    }
    const envelope = await this.request('/plugins')
    const values = Array.isArray(envelope.data) ? envelope.data : []
    return {
      available: true,
      plugins: values.map(runtimePlugin).filter((item): item is RuntimePlugin => item !== undefined),
    }
  }

  async installGithub(repository: string, ignoreVersionCheck = false): Promise<PluginInstallResult> {
    const normalized = normalizeGithubRepository(repository)
    const failedBefore = ignoreVersionCheck ? undefined : await this.failedPluginIds()
    const envelope = await this.request('/plugins/install/github', {
      repository: normalized,
      ignore_version_check: ignoreVersionCheck,
    })
    return this.finalizeInstall(envelope, failedBefore)
  }

  async installUpload(upload: BrowserUpload, ignoreVersionCheck = false): Promise<PluginInstallResult> {
    if (!upload.fileName.toLowerCase().endsWith('.zip') || !isZip(upload.buffer)) {
      throw new PluginManagerClientError('插件文件必须是有效 ZIP', 400)
    }
    const failedBefore = ignoreVersionCheck ? undefined : await this.failedPluginIds()
    const form = new FormData()
    form.append('file', new Blob([new Uint8Array(upload.buffer)], { type: 'application/zip' }), upload.fileName)
    form.append('ignore_version_check', String(ignoreVersionCheck))
    return this.finalizeInstall(await this.request('/plugins/install/upload', form), failedBefore)
  }

  private async failedPluginIds(): Promise<Set<string>> {
    const envelope = await this.request('/plugins/failed')
    const failures = record(envelope.data)
    return new Set(failures ? Object.keys(failures) : [])
  }

  private async finalizeInstall(
    envelope: AstrBotEnvelope,
    failedBefore?: Set<string>,
  ): Promise<PluginInstallResult> {
    const result = installResult(envelope)
    if (result.status !== 'warning' || !result.canIgnoreVersionCheck || !failedBefore) return result

    const failedAfter = await this.failedPluginIds()
    const introduced = [...failedAfter].filter((pluginId) => !failedBefore.has(pluginId))
    if (introduced.length !== 1) {
      return {
        ...result,
        canIgnoreVersionCheck: false,
        message: `${result.message}；无法唯一确定本次失败目录，请在 AstrBot 插件页处理`,
      }
    }

    try {
      await this.request(
        `/plugins/failed/${encodeURIComponent(introduced[0]!)}`,
        { delete_config: false, delete_data: false },
        'DELETE',
      )
      return result
    } catch {
      return {
        ...result,
        canIgnoreVersionCheck: false,
        message: `${result.message}；本次失败目录未能回滚，请在 AstrBot 插件页处理`,
      }
    }
  }

  private readApiKey(): string {
    return (typeof this.apiKey === 'function' ? this.apiKey() : this.apiKey).trim()
  }

  private async request(
    path: string,
    payload?: object | FormData,
    method?: 'GET' | 'POST' | 'DELETE',
  ): Promise<AstrBotEnvelope> {
    const apiKey = this.readApiKey()
    if (!apiKey) throw new PluginManagerClientError('AstrBot plugin scope API Key 未配置', 503)
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.timeoutMs)
    timer.unref?.()
    try {
      const isForm = payload instanceof FormData
      const response = await fetch(`${this.baseUrl}${path}`, {
        method: method ?? (payload ? 'POST' : 'GET'),
        headers: {
          Accept: 'application/json',
          'X-API-Key': apiKey,
          ...(!payload || isForm ? {} : { 'Content-Type': 'application/json' }),
        },
        body: !payload ? undefined : isForm ? payload : JSON.stringify(payload),
        signal: controller.signal,
      })
      const body = await response.json().catch(() => ({})) as AstrBotEnvelope
      if (!response.ok) {
        throw new PluginManagerClientError(publicError(body, `AstrBot 插件 API 请求失败: ${response.status}`), response.status)
      }
      if (body.status === 'error') throw new PluginManagerClientError(publicError(body, '插件操作失败'), 502)
      return body
    } catch (error) {
      if (error instanceof PluginManagerClientError) throw error
      throw new PluginManagerClientError(
        error instanceof Error && error.name === 'AbortError' ? '插件操作超时' : 'AstrBot 插件 API 不可用',
        503,
      )
    } finally {
      clearTimeout(timer)
    }
  }
}

export function normalizeGithubRepository(value: string): string {
  let parsed: URL
  try {
    parsed = new URL(value.trim())
  } catch {
    throw new PluginManagerClientError('请输入完整的 GitHub HTTPS 仓库地址', 400)
  }
  const parts = parsed.pathname.replace(/\/$/, '').split('/').filter(Boolean)
  if (
    parsed.protocol !== 'https:'
    || parsed.hostname.toLowerCase() !== 'github.com'
    || parsed.port
    || parsed.username
    || parsed.password
    || parsed.search
    || parsed.hash
    || parts.length !== 2
    || !parts.every((part) => /^[A-Za-z0-9_.-]+$/.test(part))
  ) {
    throw new PluginManagerClientError('仅支持 https://github.com/<owner>/<repo> 仓库地址', 400)
  }
  const repository = parts[1]!.replace(/\.git$/i, '')
  if (!repository || repository === '.' || repository === '..') {
    throw new PluginManagerClientError('GitHub 仓库名称无效', 400)
  }
  return `https://github.com/${parts[0]}/${repository}`
}

function isZip(buffer: Buffer): boolean {
  if (buffer.length < 4 || buffer[0] !== 0x50 || buffer[1] !== 0x4b) return false
  return (buffer[2] === 0x03 && buffer[3] === 0x04)
    || (buffer[2] === 0x05 && buffer[3] === 0x06)
    || (buffer[2] === 0x07 && buffer[3] === 0x08)
}

function publicError(envelope: AstrBotEnvelope, fallback: string): string {
  return typeof envelope.message === 'string' && envelope.message.trim() ? envelope.message.trim() : fallback
}

function installResult(envelope: AstrBotEnvelope): PluginInstallResult {
  const warning = envelope.status === 'warning'
  const data = record(envelope.data)
  return {
    status: warning ? 'warning' : 'ok',
    message: publicError(envelope, warning ? '插件兼容性需要确认' : '插件安装成功'),
    canIgnoreVersionCheck: warning && data?.can_ignore === true,
    plugin: data ? runtimePlugin(data) : undefined,
  }
}

function runtimePlugin(value: unknown): RuntimePlugin | undefined {
  const item = record(value)
  if (!item) return undefined
  const id = text(item.root_dir_name) || text(item.name)
  if (!id) return undefined
  return {
    id,
    name: text(item.name) || id,
    displayName: text(item.display_name) || text(item.name) || id,
    description: text(item.desc),
    version: text(item.version),
    author: text(item.author),
    repository: text(item.repo) || undefined,
    installedAt: text(item.installed_at) || undefined,
    activated: item.activated === true,
    reserved: item.reserved === true,
  }
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}
