import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { createDududaServer } from './app'
import { HttpControlPlaneClient, UnavailableControlPlaneClient } from './control-plane'
import { HttpDududaRuntimePreviewClient } from './dududa-runtime'
import { OneBotHub } from './onebot-hub'
import { HttpMcpConsoleClient, UnavailableMcpConsoleClient } from './mcp-console'
import { HttpAstrBotPluginManagerClient } from './plugin-manager'
import { FileApiKeyPoolStore } from './model-keys'
import { createHttpApiKeyProbe } from './provider-probe'
import { HttpRuntimeConfigClient } from './runtime-config'
import { RecallForwarder, recallForwardOptionsFromEnv } from './recall-forwarder'
import { RecallStore } from './recall-store'
import { RecallMediaStore } from './recall-media'
import { HttpRuntimeV3Client, RuntimeV3QqBridge, runtimeV3Scopes } from './runtime-v3'

function readToken(environmentName: string, fileEnvironmentName: string, defaultFile: string): string {
  const environmentToken = process.env[environmentName]?.trim()
  if (environmentToken) return environmentToken
  const tokenFile = process.env[fileEnvironmentName] || defaultFile
  try {
    return readFileSync(tokenFile, 'utf8').trim()
  } catch {
    return ''
  }
}

const publicDir = process.env.DUDUDA_WEB_PUBLIC_DIR || resolve(process.cwd(), 'dist')
const publicOrigin = process.env.DUDUDA_WEB_PUBLIC_ORIGIN?.trim()
const host = process.env.DUDUDA_WEB_BIND || '127.0.0.1'
const port = Number(process.env.DUDUDA_WEB_INTERNAL_PORT || 8000)
const oneBotToken = readToken('DUDUDA_ONEBOT_TOKEN', 'DUDUDA_ONEBOT_TOKEN_FILE', '/run/secrets/onebot_access_token')
const controlPlaneUrl = process.env.DUDUDA_CONTROL_PLANE_URL?.trim()
const mcpConsoleUrl = process.env.DUDUDA_MCP_CONSOLE_URL?.trim()
const astrBotPluginApiUrl = process.env.DUDUDA_ASTRBOT_PLUGIN_API_URL?.trim() || 'http://astrbot:6185/api/v1'
const astrBotPluginApiKey = () => readToken(
  'DUDUDA_ASTRBOT_PLUGIN_API_KEY',
  'DUDUDA_ASTRBOT_PLUGIN_API_KEY_FILE',
  '/run/secrets/astrbot_plugin_api_key',
)
const recallPath = process.env.DUDUDA_RECALL_STORE_PATH || resolve(process.cwd(), '../../runtime/web/recall/messages.sqlite')
const recallStore = new RecallStore({ path: recallPath })
const recallMediaStore = new RecallMediaStore({ path: recallPath })
const recallForwarder = new RecallForwarder(recallPath, recallForwardOptionsFromEnv())
const hub = new OneBotHub({ token: oneBotToken, recallStore, recallMediaStore, recallForwarder })
const controlPlane = controlPlaneUrl
  ? new HttpControlPlaneClient(controlPlaneUrl)
  : new UnavailableControlPlaneClient()
const mcpConsole = mcpConsoleUrl
  ? new HttpMcpConsoleClient(mcpConsoleUrl)
  : new UnavailableMcpConsoleClient()
const pluginManager = new HttpAstrBotPluginManagerClient(astrBotPluginApiUrl, astrBotPluginApiKey)
const runtimeVersion = process.env.DUDUDA_RUNTIME_VERSION?.trim() || '3'
if (!['2', '3'].includes(runtimeVersion)) throw new Error('DUDUDA_RUNTIME_VERSION 必须是 2 或 3')
const runtimeV3 = runtimeVersion === '3'
  ? new HttpRuntimeV3Client(
      process.env.DUDUDA_V3_URL?.trim() || 'http://127.0.0.1:8783',
      () => readToken('DUDUDA_V3_TOKEN', 'DUDUDA_V3_TOKEN_FILE', resolve(process.cwd(), '../../runtime/v3/token')),
    )
  : undefined
const runtimePreview = runtimeV3 ?? new HttpDududaRuntimePreviewClient(astrBotPluginApiUrl, astrBotPluginApiKey)
const runtimeBridge = runtimeV3
  ? new RuntimeV3QqBridge(hub, runtimeV3, runtimeV3Scopes(process.env.DUDUDA_V3_QQ_SCOPES), undefined, undefined,
      runtimeV3Scopes(process.env.DUDUDA_V3_QQ_NOTIFY_SCOPES))
  : undefined
// The Web gateway owns the write-only credential file.  Provider probes are
// explicit operator actions. These legacy pool settings are not Codex configuration.
const apiKeyPool = new FileApiKeyPoolStore({ probe: createHttpApiKeyProbe() })
const server = createDududaServer({
  hub,
  publicDir,
  publicOrigin,
  controlPlane,
  mcpConsole,
  pluginManager,
  runtimePreview,
  runtimeConfig: new HttpRuntimeConfigClient(astrBotPluginApiUrl, astrBotPluginApiKey),
  apiKeyPool,
})

server.listen(port, host, () => {
  const tokenState = hub.configured ? 'configured' : 'missing'
  console.log(`Dududa web listening on http://${host}:${port}; Runtime ${runtimeVersion}.0; OneBot token ${tokenState}`)
})

function shutdown(): void {
  runtimeBridge?.close()
  hub.close()
  server.close(() => process.exit(0))
  server.closeAllConnections()
  setTimeout(() => process.exit(1), 5_000).unref()
}

process.once('SIGINT', shutdown)
process.once('SIGTERM', shutdown)
