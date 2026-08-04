import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import { extname, normalize, resolve, sep } from 'node:path'
import { Readable, Transform } from 'node:stream'
import { pipeline } from 'node:stream/promises'

import type { WorkspaceEvent } from '../src/types/workspace'
import { OneBotHub } from './onebot-hub'

export interface DududaServerOptions {
  hub: OneBotHub
  publicDir: string
  maxRequestBytes?: number
}

const contentTypes: Record<string, string> = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
}

function securityHeaders(response: ServerResponse): void {
  response.setHeader('X-Content-Type-Options', 'nosniff')
  response.setHeader('X-Frame-Options', 'DENY')
  response.setHeader('Referrer-Policy', 'no-referrer')
  response.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
}

function json(response: ServerResponse, status: number, payload: unknown): void {
  securityHeaders(response)
  response.statusCode = status
  response.setHeader('Content-Type', 'application/json; charset=utf-8')
  response.setHeader('Cache-Control', 'no-store')
  response.end(JSON.stringify(payload))
}

function routeError(response: ServerResponse, error: unknown): void {
  const message = error instanceof Error ? error.message : '请求失败'
  const status = /未连接|连接已断开/.test(message) ? 503 : /不存在|not found/i.test(message) ? 404 : 502
  json(response, status, { error: message })
}

function sameOrigin(request: IncomingMessage): boolean {
  const origin = request.headers.origin
  if (!origin) return true
  try {
    return new URL(origin).host === request.headers.host
  } catch {
    return false
  }
}

async function readJson(request: IncomingMessage, limit: number): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = []
  let size = 0
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
    size += buffer.length
    if (size > limit) throw new Error('请求正文过大')
    chunks.push(buffer)
  }
  if (!chunks.length) return {}
  const parsed = JSON.parse(Buffer.concat(chunks).toString('utf8')) as unknown
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('请求正文必须是 JSON object')
  return parsed as Record<string, unknown>
}

function avatarRemoteUrl(kind: string, id: string): string | undefined {
  if (!/^\d{5,20}$/.test(id)) return undefined
  if (kind === 'user') return `https://q.qlogo.cn/headimg_dl?dst_uin=${id}&spec=100&img_type=jpg`
  if (kind === 'group') return `https://p.qlogo.cn/gh/${id}/${id}/100/`
  return undefined
}

function remoteHostAllowed(hostname: string): boolean {
  const host = hostname.toLowerCase()
  return ['qq.com', 'qq.com.cn', 'qpic.cn', 'gtimg.cn', 'qlogo.cn'].some(
    (suffix) => host === suffix || host.endsWith(`.${suffix}`),
  )
}

async function fetchAllowedRemote(source: string): Promise<Response> {
  let url = new URL(source)
  for (let redirect = 0; redirect < 4; redirect += 1) {
    if (!['https:', 'http:'].includes(url.protocol) || !remoteHostAllowed(url.hostname)) throw new Error('媒体地址不在允许范围内')
    const response = await fetch(url, {
      redirect: 'manual',
      headers: { 'User-Agent': 'Dududa-QQ-Workspace/1.0' },
      signal: AbortSignal.timeout(15_000),
    })
    if (response.status >= 300 && response.status < 400) {
      const location = response.headers.get('location')
      if (!location) throw new Error('媒体重定向缺少地址')
      url = new URL(location, url)
      continue
    }
    if (!response.ok || !response.body) throw new Error(`媒体请求失败: ${response.status}`)
    return response
  }
  throw new Error('媒体重定向次数过多')
}

async function proxyImage(response: ServerResponse, source: string, cacheControl: string): Promise<void> {
  const upstream = await fetchAllowedRemote(source)
  const contentType = upstream.headers.get('content-type')?.split(';', 1)[0] ?? ''
  if (!contentType.startsWith('image/')) throw new Error('上游内容不是图片')
  const declaredSize = Number(upstream.headers.get('content-length') ?? 0)
  const maxBytes = 25 * 1024 * 1024
  if (declaredSize > maxBytes) throw new Error('图片超过大小限制')
  let received = 0
  const limiter = new Transform({
    transform(chunk: Buffer, _encoding, callback) {
      received += chunk.length
      if (received > maxBytes) callback(new Error('图片超过大小限制'))
      else callback(null, chunk)
    },
  })
  securityHeaders(response)
  response.statusCode = 200
  response.setHeader('Content-Type', contentType)
  response.setHeader('Cache-Control', cacheControl)
  await pipeline(Readable.fromWeb(upstream.body as never), limiter, response)
}

async function serveStatic(response: ServerResponse, pathname: string, publicDir: string): Promise<void> {
  const requested = pathname === '/' ? '/index.html' : pathname
  const decoded = decodeURIComponent(requested)
  const candidate = normalize(resolve(publicDir, `.${decoded}`))
  const root = resolve(publicDir)
  const path = candidate === root || candidate.startsWith(`${root}${sep}`) ? candidate : resolve(publicDir, 'index.html')
  let target = path
  try {
    const info = await stat(target)
    if (!info.isFile()) target = resolve(publicDir, 'index.html')
  } catch {
    target = resolve(publicDir, 'index.html')
  }
  try {
    const info = await stat(target)
    if (!info.isFile()) throw new Error('not a file')
  } catch {
    json(response, 404, { error: '前端构建产物不存在' })
    return
  }
  securityHeaders(response)
  response.statusCode = 200
  response.setHeader('Content-Type', contentTypes[extname(target).toLowerCase()] ?? 'application/octet-stream')
  response.setHeader('Cache-Control', target.endsWith('index.html') ? 'no-cache' : 'public, max-age=31536000, immutable')
  createReadStream(target).pipe(response)
}

export function createDududaServer(options: DududaServerOptions) {
  const maxRequestBytes = options.maxRequestBytes ?? 64 * 1024
  const eventClients = new Set<ServerResponse>()
  const onWorkspaceEvent = (event: WorkspaceEvent) => {
    const frame = `event: workspace\ndata: ${JSON.stringify(event)}\n\n`
    for (const client of eventClients) client.write(frame)
  }
  options.hub.on('workspace-event', onWorkspaceEvent)

  const heartbeat = setInterval(() => {
    for (const client of eventClients) client.write(': keepalive\n\n')
  }, 20_000)
  heartbeat.unref()

  const server = createServer(async (request, response) => {
    const method = request.method ?? 'GET'
    const url = new URL(request.url ?? '/', 'http://localhost')
    try {
      if (method === 'GET' && url.pathname === '/api/health') {
        json(response, 200, options.hub.runtimeStatus())
        return
      }
      if (method === 'GET' && url.pathname === '/api/workspace') {
        await options.hub.refreshAll(url.searchParams.get('refresh') === '1')
        json(response, 200, options.hub.workspaceSnapshot())
        return
      }
      if (method === 'GET' && url.pathname === '/api/events') {
        securityHeaders(response)
        response.statusCode = 200
        response.setHeader('Content-Type', 'text/event-stream; charset=utf-8')
        response.setHeader('Cache-Control', 'no-cache, no-transform')
        response.setHeader('Connection', 'keep-alive')
        response.flushHeaders()
        eventClients.add(response)
        response.write(`event: workspace\ndata: ${JSON.stringify({ type: 'runtime.status', status: options.hub.runtimeStatus() })}\n\n`)
        response.write(`event: workspace\ndata: ${JSON.stringify({ type: 'workspace.refresh' })}\n\n`)
        request.once('close', () => eventClients.delete(response))
        return
      }
      const messagesRoute = /^\/api\/accounts\/([^/]+)\/conversations\/(group|private)\/([^/]+)\/messages$/.exec(url.pathname)
      if (messagesRoute) {
        const account = decodeURIComponent(messagesRoute[1]!)
        const type = messagesRoute[2] as 'group' | 'private'
        const peerId = decodeURIComponent(messagesRoute[3]!)
        if (method === 'GET') {
          const messages = await options.hub.history(account, type, peerId, Number(url.searchParams.get('limit') ?? 50))
          json(response, 200, { messages })
          return
        }
        if (method === 'POST') {
          if (!sameOrigin(request)) {
            json(response, 403, { error: '跨站写请求已拒绝' })
            return
          }
          const body = await readJson(request, maxRequestBytes)
          const content = typeof body.content === 'string' ? body.content.trim() : ''
          if (!content || content.length > 4000) {
            json(response, 400, { error: '消息长度必须在 1 到 4000 字符之间' })
            return
          }
          const message = await options.hub.sendText(account, type, peerId, content)
          json(response, 201, { message })
          return
        }
      }
      const readRoute = /^\/api\/accounts\/([^/]+)\/conversations\/(group|private)\/([^/]+)\/read$/.exec(url.pathname)
      if (method === 'POST' && readRoute) {
        if (!sameOrigin(request)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        await options.hub.markRead(
          decodeURIComponent(readRoute[1]!),
          readRoute[2] as 'group' | 'private',
          decodeURIComponent(readRoute[3]!),
        )
        json(response, 200, { ok: true })
        return
      }
      const avatarRoute = /^\/api\/media\/avatar\/(user|group)\/(\d{5,20})$/.exec(url.pathname)
      if (method === 'GET' && avatarRoute) {
        const source = avatarRemoteUrl(avatarRoute[1]!, avatarRoute[2]!)
        if (!source) {
          json(response, 404, { error: '头像不存在' })
          return
        }
        await proxyImage(response, source, 'public, max-age=3600, stale-while-revalidate=86400')
        return
      }
      const mediaRoute = /^\/api\/media\/message\/([a-f0-9]{32})$/.exec(url.pathname)
      if (method === 'GET' && mediaRoute) {
        const source = options.hub.mediaUrl(mediaRoute[1]!)
        if (!source) {
          json(response, 404, { error: '媒体地址已过期' })
          return
        }
        await proxyImage(response, source, 'private, max-age=300')
        return
      }
      if (url.pathname.startsWith('/api/')) {
        json(response, 404, { error: 'API 不存在' })
        return
      }
      if (method !== 'GET' && method !== 'HEAD') {
        json(response, 405, { error: 'Method Not Allowed' })
        return
      }
      await serveStatic(response, url.pathname, options.publicDir)
    } catch (error) {
      if (!response.headersSent) routeError(response, error)
      else response.destroy(error instanceof Error ? error : undefined)
    }
  })

  server.on('upgrade', (request, socket, head) => {
    if (!options.hub.handleUpgrade(request, socket, head)) socket.destroy()
  })

  server.once('close', () => {
    clearInterval(heartbeat)
    options.hub.off('workspace-event', onWorkspaceEvent)
    for (const client of eventClients) client.end()
    eventClients.clear()
    options.hub.close()
  })

  return server
}
