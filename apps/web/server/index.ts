import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { createDududaServer } from './app'
import { HttpControlPlaneClient, UnavailableControlPlaneClient } from './control-plane'
import { HttpDududaRuntimePreviewClient } from './dududa-runtime'
import { OneBotHub } from './onebot-hub'
import { HttpMcpConsoleClient, UnavailableMcpConsoleClient } from './mcp-console'
import { HttpAstrBotPluginManagerClient } from './plugin-manager'

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
const hub = new OneBotHub({ token: oneBotToken })
const controlPlane = controlPlaneUrl
  ? new HttpControlPlaneClient(controlPlaneUrl)
  : new UnavailableControlPlaneClient()
const mcpConsole = mcpConsoleUrl
  ? new HttpMcpConsoleClient(mcpConsoleUrl)
  : new UnavailableMcpConsoleClient()
const pluginManager = new HttpAstrBotPluginManagerClient(astrBotPluginApiUrl, astrBotPluginApiKey)
const runtimePreview = new HttpDududaRuntimePreviewClient(astrBotPluginApiUrl, astrBotPluginApiKey)
const server = createDududaServer({ hub, publicDir, controlPlane, mcpConsole, pluginManager, runtimePreview })

server.listen(port, host, () => {
  const tokenState = hub.configured ? 'configured' : 'missing'
  console.log(`Dududa web listening on http://${host}:${port}; OneBot token ${tokenState}`)
})

function shutdown(): void {
  hub.close()
  server.close(() => process.exit(0))
  server.closeAllConnections()
  setTimeout(() => process.exit(1), 5_000).unref()
}

process.once('SIGINT', shutdown)
process.once('SIGTERM', shutdown)
