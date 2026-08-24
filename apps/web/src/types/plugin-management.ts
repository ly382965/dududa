export interface RuntimePlugin {
  id: string
  name: string
  displayName: string
  description: string
  version: string
  author: string
  repository?: string
  installedAt?: string
  activated: boolean
  reserved: boolean
}

export interface RuntimePluginCatalog {
  available: boolean
  plugins: RuntimePlugin[]
  reason?: string
}

export interface PluginInstallResult {
  status: 'ok' | 'warning'
  message: string
  canIgnoreVersionCheck?: boolean
  plugin?: RuntimePlugin
}

export interface GithubPluginInstallRequest {
  repository: string
  ignoreVersionCheck?: boolean
}
