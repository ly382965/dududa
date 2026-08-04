import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { createDududaServer } from './app'
import { OneBotHub } from './onebot-hub'

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
const hub = new OneBotHub({ token: oneBotToken })
const server = createDududaServer({ hub, publicDir })

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
