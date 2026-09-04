import type { McpConsoleServer } from './internal-test'

export interface McpServerCheckResult {
  ok: boolean
  server: McpConsoleServer
}

export type McpTransport = 'stdio' | 'streamable_http'
export type McpProtocolMode = 'auto' | 'legacy'

export interface McpSecretRefInput {
  secretId: string
  target: 'env' | 'header'
  targetName: string
}

export interface McpStdioEndpointInput {
  command: string
  args: string[]
  cwd: string
  envAllowlist: string[]
}

export interface McpHttpEndpointInput {
  url: string
  allowedHosts: string[]
}

export interface McpServerInstallRequest {
  serverId: string
  displayName?: string
  enabled: boolean
  transport: McpTransport
  protocolMode: McpProtocolMode
  endpoint: McpStdioEndpointInput | McpHttpEndpointInput
  secretRefs: McpSecretRefInput[]
  allowedTools: string[]
  deniedTools: string[]
  timeoutsSeconds: {
    connect: number
    discovery: number
    call: number
    maximumCall: number
    close: number
  }
  retry: {
    maximumAttempts: number
    baseDelayMs: number
  }
  circuit: {
    failureThreshold: number
    failureWindowSeconds: number
    openDurationSeconds: number
  }
  maximumConcurrency: number
  schemaTtlSeconds: number
  configRevision: string
}

export interface McpServerInstallResult {
  schemaVersion: 1
  status: 'ok' | 'warning'
  server: {
    id: string
    displayName: string
  }
  discovery: {
    status: 'ok' | 'unavailable'
    tools: Array<{ name: string; description?: string }>
    error?: string
  }
  capabilityGranted: false
  message: string
}
