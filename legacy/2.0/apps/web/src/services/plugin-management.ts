import type {
  GithubPluginInstallRequest,
  PluginInstallResult,
  RuntimePluginCatalog,
} from '../types/plugin-management'

export interface PluginManagementAdapter {
  runtimePlugins(): Promise<RuntimePluginCatalog>
  installGithub(request: GithubPluginInstallRequest): Promise<PluginInstallResult>
  installUpload(file: File, ignoreVersionCheck?: boolean): Promise<PluginInstallResult>
}

export class HttpPluginManagementAdapter implements PluginManagementAdapter {
  constructor(private readonly baseUrl = '') {}

  runtimePlugins(): Promise<RuntimePluginCatalog> {
    return this.request('/api/plugins/runtime')
  }

  installGithub(request: GithubPluginInstallRequest): Promise<PluginInstallResult> {
    return this.request('/api/plugins/install/github', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
  }

  installUpload(file: File, ignoreVersionCheck = false): Promise<PluginInstallResult> {
    const form = new FormData()
    form.append('file', file)
    return this.request(
      `/api/plugins/install/upload?ignoreVersionCheck=${ignoreVersionCheck ? 'true' : 'false'}`,
      { method: 'POST', body: form },
    )
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...init?.headers,
      },
    })
    const body = await response.json().catch(() => ({})) as { error?: string }
    if (!response.ok) throw new Error(body.error || `插件管理请求失败: ${response.status}`)
    return body as T
  }
}

export const pluginManagementAdapter = new HttpPluginManagementAdapter()
