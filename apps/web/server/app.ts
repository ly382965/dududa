import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import { extname, normalize, resolve, sep } from 'node:path'
import { Readable, Transform } from 'node:stream'
import { pipeline } from 'node:stream/promises'

import type { WorkspaceEvent } from '../src/types/workspace'
import type { McpServerInstallRequest } from '../src/types/mcp-management'
import {
  groupServiceCommandSchema,
  previewGroupServiceSchema,
} from '../src/schemas/control-plane'
import {
  createGroupFolderSchema,
  directoryQuerySchema,
  groupFileMutationSchema,
  groupFilesQuerySchema,
  groupMembersQuerySchema,
  forwardRequestSchema,
  historyQuerySchema,
  nudgeRequestSchema,
  renameGroupSchema,
  resolveNotificationSchema,
  sendMessageRequestSchema,
  setGroupAdminSchema,
  setGroupCardSchema,
  setGroupMuteAllSchema,
} from '../src/schemas/workspace'
import { OneBotHub } from './onebot-hub'
import {
  ControlPlaneClientError,
  UnavailableControlPlaneClient,
  type ControlPlaneClient,
} from './control-plane'
import {
  createInternalTestGateway,
  createAgentGateway,
  InternalTestError,
  type InternalTestGateway,
  type AgentGateway,
} from './internal-test'
import type { DududaRuntimePreviewClient } from './dududa-runtime'
import {
  McpConsoleClientError,
  UnavailableMcpConsoleClient,
  type McpConsoleClient,
} from './mcp-console'
import {
  PluginManagerClientError,
  UnavailablePluginManagerClient,
  type PluginManagerClient,
} from './plugin-manager'
import {
  ApiKeyPoolError,
  FileApiKeyPoolStore,
  isApiKeyTier,
  sanitizeApiKeyMutation,
  sanitizeApiKeySnapshot,
  sanitizeApiKeyTestResult,
  type ApiKeyPoolClient,
} from './model-keys'
import { readBrowserUpload } from './uploads'

export interface DududaServerOptions {
  hub: OneBotHub
  publicDir: string
  publicOrigin?: string
  controlPlane?: ControlPlaneClient
  internalTest?: InternalTestGateway
  agent?: AgentGateway
  mcpConsole?: McpConsoleClient
  pluginManager?: PluginManagerClient
  runtimePreview?: DududaRuntimePreviewClient
  /** Server-side provider credential pool.  `modelKeys` is a compatibility alias. */
  apiKeyPool?: ApiKeyPoolClient
  modelKeys?: ApiKeyPoolClient
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
  '.md': 'text/markdown; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
}

const workspaceEventReplayLimit = 4_096

interface ReplayableWorkspaceEvent {
  id: number
  event: WorkspaceEvent
}

function workspaceEventFrame(event: WorkspaceEvent, id?: number): string {
  return `${id === undefined ? '' : `id: ${id}\n`}event: workspace\ndata: ${JSON.stringify(event)}\n\n`
}

function lastWorkspaceEventId(request: IncomingMessage): number | undefined {
  const header = request.headers['last-event-id']
  const value = Array.isArray(header) ? header[0] : header
  if (!value || !/^\d+$/.test(value)) return undefined
  const id = Number(value)
  return Number.isSafeInteger(id) ? id : undefined
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
  if (error instanceof ControlPlaneClientError) {
    json(response, error.status, { error: error.message })
    return
  }
  if (error instanceof InternalTestError) {
    json(response, error.status, { error: error.message })
    return
  }
  if (error instanceof McpConsoleClientError) {
    json(response, error.status, { error: error.message })
    return
  }
  if (error instanceof PluginManagerClientError) {
    json(response, error.status, { error: error.message })
    return
  }
  if (error instanceof ApiKeyPoolError) {
    json(response, error.status, { error: error.message })
    return
  }
  const message = error instanceof Error ? error.message : '请求失败'
  const status = /未连接|连接已断开/.test(message)
    ? 503
    : /无权|只允许|只有.+可以|无法确认当前 QQ 的群|@全体成员/.test(message)
      ? 403
      : /已经处理|正在处理|正在上传|结果未知|避免重复上传/.test(message)
        ? 409
    : /不存在|not found/i.test(message)
      ? 404
      : /游标|before|after|Range|参数无效|JSON|请求正文|消息内容|上传|消息标识|标识无效|标识与|QQ 号|转发|文件类型|表情|不匹配/.test(
            message,
          )
        ? 400
        : 502
  json(response, status, { error: message })
}

async function apiKeyCall<T>(operation: () => Promise<T>): Promise<T> {
  try {
    return await operation()
  } catch (error) {
    if (error instanceof ApiKeyPoolError) throw error
    // Third-party adapters must not be able to put an upstream exception (and
    // possibly a credential) into the browser-facing error body.
    throw new ApiKeyPoolError('API Key 操作失败', 502)
  }
}

function operatorSession(request: IncomingMessage): string {
  const value = request.headers['x-dududa-operator-session']
  if (typeof value !== 'string' || !value.trim() || value.length > 2_048) {
    throw new ControlPlaneClientError('管理员会话缺失', 401)
  }
  return value
}

function trustedLoopbackHost(value: string | undefined): boolean {
  if (!value) return false
  try {
    const hostname = new URL(`http://${value}`).hostname.toLowerCase()
    return hostname === 'localhost' || hostname === 'localhost.' || hostname === '127.0.0.1' || hostname === '[::1]'
  } catch {
    return false
  }
}

function configuredPublicOrigin(value: string | undefined): URL | undefined {
  if (!value?.trim()) return undefined
  const parsed = new URL(value)
  if (
    parsed.protocol !== 'https:' ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== '/' ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error('DUDUDA_WEB_PUBLIC_ORIGIN 必须是无路径的 HTTPS Origin')
  }
  return parsed
}

function trustedRequestHost(value: string | undefined, publicOrigin: URL | undefined): boolean {
  if (trustedLoopbackHost(value)) return true
  if (!value || !publicOrigin) return false
  try {
    return new URL(`http://${value}`).host === publicOrigin.host
  } catch {
    return false
  }
}

function sameOrigin(request: IncomingMessage, publicOrigin: URL | undefined): boolean {
  const origin = request.headers.origin
  if (!origin || !trustedRequestHost(request.headers.host, publicOrigin)) return false
  try {
    const parsed = new URL(origin)
    if (trustedLoopbackHost(request.headers.host)) {
      return ['http:', 'https:'].includes(parsed.protocol) && parsed.host === request.headers.host
    }
    return parsed.origin === publicOrigin?.origin && request.headers.host === publicOrigin.host
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
  let parsed: unknown
  try {
    parsed = JSON.parse(Buffer.concat(chunks).toString('utf8')) as unknown
  } catch {
    // Native JSON parser errors can include a fragment of the request body.
    // Keep the browser-facing diagnostic deterministic and credential-free.
    throw new Error('请求正文 JSON 无效')
  }
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

async function fetchAllowedRemote(source: string, range?: string): Promise<Response> {
  let url = new URL(source)
  for (let redirect = 0; redirect < 4; redirect += 1) {
    if (!['https:', 'http:'].includes(url.protocol) || !remoteHostAllowed(url.hostname)) throw new Error('媒体地址不在允许范围内')
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 15_000)
    timer.unref?.()
    let response: Response
    try {
      response = await fetch(url, {
        redirect: 'manual',
        headers: {
          'User-Agent': 'Dududa-QQ-Workspace/1.0',
          ...(range && /^bytes=\d*-\d*$/.test(range) ? { Range: range } : {}),
        },
        signal: controller.signal,
      })
    } finally {
      clearTimeout(timer)
    }
    if (response.status >= 300 && response.status < 400) {
      const location = response.headers.get('location')
      if (!location) throw new Error('媒体重定向缺少地址')
      url = new URL(location, url)
      continue
    }
    if (!response.ok && response.status !== 416) throw new Error(`媒体请求失败: ${response.status}`)
    return response
  }
  throw new Error('媒体重定向次数过多')
}

function validatedRange(value: string | undefined): string | undefined {
  if (!value) return undefined
  const match = /^bytes=(?:(\d+)-(\d*)|-(\d+))$/.exec(value)
  if (!match) throw new Error('Range 请求格式无效')
  if (match[1] && match[2] && Number(match[1]) > Number(match[2])) throw new Error('Range 请求格式无效')
  return value
}

async function proxyImage(response: ServerResponse, source: string, cacheControl: string): Promise<void> {
  const upstream = await fetchAllowedRemote(source)
  if (!upstream.body) throw new Error('图片响应内容为空')
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

async function proxyMessageMedia(
  request: IncomingMessage,
  response: ServerResponse,
  source: string,
  cacheControl: string,
): Promise<void> {
  const upstream = await fetchAllowedRemote(source, validatedRange(request.headers.range))
  if (upstream.status === 416) {
    securityHeaders(response)
    response.statusCode = 416
    response.setHeader('Cache-Control', 'no-store')
    const contentRange = upstream.headers.get('content-range')
    const acceptRanges = upstream.headers.get('accept-ranges')
    if (contentRange) response.setHeader('Content-Range', contentRange)
    if (acceptRanges) response.setHeader('Accept-Ranges', acceptRanges)
    await upstream.body?.cancel()
    response.end()
    return
  }
  if (!upstream.body) throw new Error('消息媒体响应内容为空')
  const contentType = upstream.headers.get('content-type')?.split(';', 1)[0] ?? 'application/octet-stream'
  if (!/^(?:image|audio|video)\//.test(contentType) && contentType !== 'application/octet-stream') {
    throw new Error('上游内容不是受支持的消息媒体')
  }
  const declaredSize = Number(upstream.headers.get('content-length') ?? 0)
  const maxBytes = 100 * 1024 * 1024
  if (declaredSize > maxBytes) throw new Error('消息媒体超过大小限制')
  let received = 0
  const limiter = new Transform({
    transform(chunk: Buffer, _encoding, callback) {
      received += chunk.length
      if (received > maxBytes) callback(new Error('消息媒体超过大小限制'))
      else callback(null, chunk)
    },
  })
  securityHeaders(response)
  response.statusCode = upstream.status === 206 ? 206 : 200
  response.setHeader('Content-Type', contentType)
  response.setHeader('Cache-Control', cacheControl)
  const contentRange = upstream.headers.get('content-range')
  const acceptRanges = upstream.headers.get('accept-ranges')
  if (contentRange) response.setHeader('Content-Range', contentRange)
  if (acceptRanges) response.setHeader('Accept-Ranges', acceptRanges)
  if (declaredSize > 0) response.setHeader('Content-Length', declaredSize)
  await pipeline(Readable.fromWeb(upstream.body as never), limiter, response)
}

function attachmentHeader(fileName: string): string {
  const safe = fileName.replace(/[\\/\u0000-\u001f\u007f"]/g, '_').trim().slice(0, 255) || 'QQ-file'
  const ascii = safe.replace(/[^\x20-\x7e]/g, '_')
  return `attachment; filename="${ascii}"; filename*=UTF-8''${encodeURIComponent(safe)}`
}

async function proxyMessageFile(
  request: IncomingMessage,
  response: ServerResponse,
  source: string,
  fileName: string,
): Promise<void> {
  const upstream = await fetchAllowedRemote(source, validatedRange(request.headers.range))
  if (upstream.status === 416) {
    securityHeaders(response)
    response.statusCode = 416
    response.setHeader('Cache-Control', 'no-store')
    const contentRange = upstream.headers.get('content-range')
    if (contentRange) response.setHeader('Content-Range', contentRange)
    response.end()
    await upstream.body?.cancel()
    return
  }
  if (!upstream.body) throw new Error('文件响应内容为空')
  const declaredSize = Number(upstream.headers.get('content-length') ?? 0)
  const maxBytes = 512 * 1024 * 1024
  if (declaredSize > maxBytes) throw new Error('文件超过下载大小限制')
  let received = 0
  const limiter = new Transform({
    transform(chunk: Buffer, _encoding, callback) {
      received += chunk.length
      if (received > maxBytes) callback(new Error('文件超过下载大小限制'))
      else callback(null, chunk)
    },
  })
  securityHeaders(response)
  response.statusCode = upstream.status === 206 ? 206 : 200
  response.setHeader('Content-Type', upstream.headers.get('content-type')?.split(';', 1)[0] || 'application/octet-stream')
  response.setHeader('Content-Disposition', attachmentHeader(fileName))
  response.setHeader('Cache-Control', 'private, max-age=60')
  const contentRange = upstream.headers.get('content-range')
  const acceptRanges = upstream.headers.get('accept-ranges')
  if (contentRange) response.setHeader('Content-Range', contentRange)
  if (acceptRanges) response.setHeader('Accept-Ranges', acceptRanges)
  if (declaredSize > 0) response.setHeader('Content-Length', declaredSize)
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
  response.setHeader(
    'Cache-Control',
    target.endsWith('index.html') || target.endsWith('.md') ? 'no-cache' : 'public, max-age=31536000, immutable',
  )
  createReadStream(target).pipe(response)
}

export function createDududaServer(options: DududaServerOptions) {
  const maxRequestBytes = options.maxRequestBytes ?? 64 * 1024
  const publicOrigin = configuredPublicOrigin(options.publicOrigin)
  const controlPlane = options.controlPlane ?? new UnavailableControlPlaneClient()
  const internalTest = options.internalTest ?? createInternalTestGateway(process.env, options.runtimePreview)
  const agent = options.agent ?? createAgentGateway(process.env, options.runtimePreview, async (scope, limit) => {
    const prefix = `${scope.accountId}:group:`
    if (!scope.conversationId.startsWith(prefix)) throw new InternalTestError('Runtime 历史仅支持当前账号群聊', 400)
    const groupId = scope.conversationId.slice(prefix.length)
    if (!/^\d+$/.test(groupId)) throw new InternalTestError('群聊标识无效', 400)
    return options.hub.historyPage(scope.accountId, 'group', groupId, { limit })
  })
  const mcpConsole = options.mcpConsole ?? new UnavailableMcpConsoleClient()
  const pluginManager = options.pluginManager ?? new UnavailablePluginManagerClient()
  const apiKeyPool = options.apiKeyPool
    ?? options.modelKeys
    ?? new FileApiKeyPoolStore()
  const eventClients = new Set<ServerResponse>()
  const eventReplay: ReplayableWorkspaceEvent[] = []
  let nextWorkspaceEventId = 1
  const onWorkspaceEvent = (event: WorkspaceEvent) => {
    const replayable = { id: nextWorkspaceEventId, event }
    nextWorkspaceEventId += 1
    eventReplay.push(replayable)
    if (eventReplay.length > workspaceEventReplayLimit) eventReplay.splice(0, eventReplay.length - workspaceEventReplayLimit)
    const frame = workspaceEventFrame(event, replayable.id)
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
      if (!trustedRequestHost(request.headers.host, publicOrigin)) {
        json(response, 421, { error: '请求 Host 不在服务允许范围内' })
        return
      }
      if (method === 'GET' && url.pathname === '/api/health') {
        json(response, 200, options.hub.runtimeStatus())
        return
      }
      if (method === 'GET' && url.pathname === '/api/api-keys') {
        json(response, 200, sanitizeApiKeySnapshot(await apiKeyCall(() => apiKeyPool.list())))
        return
      }
      const apiKeyPoolRoute = /^\/api\/api-keys\/pools\/([^/]+)$/.exec(url.pathname)
      if (method === 'PUT' && apiKeyPoolRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '只允许同源管理员页面修改 API Key 池' })
          return
        }
        const tier = decodeURIComponent(apiKeyPoolRoute[1]!)
        if (!isApiKeyTier(tier)) {
          json(response, 400, { error: 'API Key tier 无效' })
          return
        }
        const body = await readJson(request, maxRequestBytes)
        if (Object.prototype.hasOwnProperty.call(body, 'secret') || Object.prototype.hasOwnProperty.call(body, 'keys')) {
          json(response, 400, { error: '池配置请求不接受明文密钥或 Key 列表' })
          return
        }
        json(response, 200, sanitizeApiKeyMutation(await apiKeyCall(() => apiKeyPool.updatePool(tier, body))))
        return
      }
      const apiKeyCreateRoute = /^\/api\/api-keys\/pools\/([^/]+)\/keys$/.exec(url.pathname)
      if (method === 'POST' && apiKeyCreateRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '只允许同源管理员页面登记 API Key' })
          return
        }
        const tier = decodeURIComponent(apiKeyCreateRoute[1]!)
        if (!isApiKeyTier(tier)) {
          json(response, 400, { error: 'API Key tier 无效' })
          return
        }
        // Creation requires a raw secret; the key PUT route accepts one only
        // when the operator explicitly rotates an existing credential.
        const body = await readJson(request, maxRequestBytes)
        json(response, 201, sanitizeApiKeyMutation(await apiKeyCall(() => apiKeyPool.createKey(tier, body))))
        return
      }
      const apiKeyKeyRoute = /^\/api\/api-keys\/pools\/([^/]+)\/keys\/([^/]+)$/.exec(url.pathname)
      if ((method === 'PUT' || method === 'DELETE') && apiKeyKeyRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '只允许同源管理员页面修改 API Key' })
          return
        }
        const tier = decodeURIComponent(apiKeyKeyRoute[1]!)
        const keyId = decodeURIComponent(apiKeyKeyRoute[2]!)
        if (!isApiKeyTier(tier)) {
          json(response, 400, { error: 'API Key tier 无效' })
          return
        }
        if (method === 'PUT') {
          // A missing or empty secret means “keep the existing secret” for a
          // replacement.  The store owns that rule and never echoes it.
          const body = await readJson(request, maxRequestBytes)
          json(response, 200, sanitizeApiKeyMutation(await apiKeyCall(() => apiKeyPool.updateKey(tier, keyId, body))))
        } else {
          const body = await readJson(request, maxRequestBytes)
          const mode = body.disable === true || url.searchParams.get('mode') === 'disable' ? 'disable' : 'remove'
          json(response, 200, sanitizeApiKeyMutation(await apiKeyCall(() => apiKeyPool.deleteKey(tier, keyId, mode))))
        }
        return
      }
      const apiKeyTestRoute = /^\/api\/api-keys\/pools\/([^/]+)\/test$/.exec(url.pathname)
      if (method === 'POST' && apiKeyTestRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '只允许同源管理员页面探测 Provider' })
          return
        }
        const tier = decodeURIComponent(apiKeyTestRoute[1]!)
        if (!isApiKeyTier(tier)) {
          json(response, 400, { error: 'API Key tier 无效' })
          return
        }
        const body = await readJson(request, maxRequestBytes)
        if (Object.prototype.hasOwnProperty.call(body, 'secret')) {
          json(response, 400, { error: 'Provider 探测请求不接受明文密钥' })
          return
        }
        const keyId = body.keyId === undefined ? undefined : body.keyId
        if (keyId !== undefined && typeof keyId !== 'string') {
          json(response, 400, { error: 'Provider 探测 Key 标识无效' })
          return
        }
        json(response, 200, sanitizeApiKeyTestResult(await apiKeyCall(() => apiKeyPool.testPool(tier, keyId as string | undefined))))
        return
      }
      if (method === 'GET' && url.pathname === '/api/internal-test/status') {
        json(response, 200, await internalTest.status())
        return
      }
      if (method === 'GET' && url.pathname === '/api/internal-test/samples') {
        json(response, 200, await internalTest.samples(Object.fromEntries(url.searchParams.entries())))
        return
      }
      if (method === 'GET' && url.pathname === '/api/internal-test/progress') {
        json(response, 200, await internalTest.progress())
        return
      }
      if (method === 'GET' && url.pathname === '/api/internal-test/agent/status') {
        json(response, 200, await internalTest.agentStatus())
        return
      }
      if (method === 'GET' && url.pathname === '/api/agent/status') {
        json(response, 200, await agent.agentStatus())
        return
      }
      if (method === 'GET' && url.pathname === '/api/agent/catalog') {
        json(response, 200, await agent.agentCatalog())
        return
      }
      if (method === 'GET' && url.pathname === '/api/agent/config') {
        json(response, 200, await agent.agentConfig(Object.fromEntries(url.searchParams.entries())))
        return
      }
      if ((method === 'PUT' && url.pathname === '/api/agent/config')
        || (method === 'POST' && url.pathname === '/api/agent/respond')) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '只允许同源管理员页面操作 Agent' })
          return
        }
        const body = await readJson(request, maxRequestBytes)
        json(response, 200, method === 'PUT' ? await agent.saveAgentConfig(body) : await agent.respond(body))
        return
      }
      if (method === 'GET' && url.pathname === '/api/internal-test/agent/catalog') {
        json(response, 200, await internalTest.agentCatalog())
        return
      }
      if (method === 'GET' && url.pathname === '/api/internal-test/mcp/catalog') {
        json(response, 200, await mcpConsole.catalog())
        return
      }
      if (method === 'POST' && url.pathname === '/api/internal-test/mcp/invoke') {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '只允许同源超级管理员页面调用 MCP Capability' })
          return
        }
        const body = await readJson(request, maxRequestBytes)
        if (typeof body.capabilityId !== 'string' || !body.arguments || typeof body.arguments !== 'object' || Array.isArray(body.arguments)) {
          json(response, 400, { error: 'MCP Capability 调用参数无效' })
          return
        }
        json(response, 200, await mcpConsole.invoke(body.capabilityId, body.arguments as Record<string, unknown>))
        return
      }
      if (method === 'POST' && url.pathname === '/api/mcp/check') {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '只允许同源超级管理员页面检测 MCP' })
          return
        }
        const body = await readJson(request, maxRequestBytes)
        if (Object.keys(body).length !== 1 || typeof body.serverId !== 'string' || !body.serverId.trim()) {
          json(response, 400, { error: 'MCP 检测只接受已登记的 Server ID' })
          return
        }
        json(response, 200, await mcpConsole.checkServer(body.serverId))
        return
      }
      if (method === 'POST' && url.pathname === '/api/mcp/install') {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '只允许同源超级管理员页面接入 MCP Server' })
          return
        }
        const body = await readJson(request, maxRequestBytes)
        if (typeof body.serverId !== 'string' || !body.serverId.trim()) {
          json(response, 400, { error: '缺少 MCP Server ID' })
          return
        }
        json(response, 200, await mcpConsole.installServer(body as unknown as McpServerInstallRequest))
        return
      }
      if (method === 'GET' && url.pathname === '/api/plugins/runtime') {
        json(response, 200, await pluginManager.catalog())
        return
      }
      if (method === 'POST' && url.pathname === '/api/plugins/install/github') {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '只允许同源超级管理员页面安装插件' })
          return
        }
        const body = await readJson(request, maxRequestBytes)
        if (typeof body.repository !== 'string' || !body.repository.trim()) {
          json(response, 400, { error: '缺少 GitHub 仓库地址' })
          return
        }
        json(
          response,
          200,
          await pluginManager.installGithub(body.repository, body.ignoreVersionCheck === true),
        )
        return
      }
      if (method === 'POST' && url.pathname === '/api/plugins/install/upload') {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '只允许同源超级管理员页面安装插件' })
          return
        }
        const upload = await readBrowserUpload(request, 16 * 1024 * 1024)
        const ignoreVersionCheck = url.searchParams.get('ignoreVersionCheck') === 'true'
        json(response, 200, await pluginManager.installUpload(upload, ignoreVersionCheck))
        return
      }
      if (method === 'GET' && url.pathname === '/api/internal-test/agent/config') {
        json(response, 200, await internalTest.agentConfig(Object.fromEntries(url.searchParams.entries())))
        return
      }
      if (method === 'PUT' && url.pathname === '/api/internal-test/agent/config') {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '只允许同源管理员页面修改 Agent 配置' })
          return
        }
        json(response, 200, await internalTest.saveAgentConfig(await readJson(request, maxRequestBytes)))
        return
      }
      if (method === 'POST' && url.pathname === '/api/internal-test/agent/respond') {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '只允许同源内测页面生成 Agent 候选回答' })
          return
        }
        json(response, 200, await internalTest.respond(await readJson(request, maxRequestBytes)))
        return
      }
      if (method === 'POST' && url.pathname === '/api/internal-test/generate') {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '只允许同源内测页面生成候选回答' })
          return
        }
        json(response, 200, await internalTest.generate(await readJson(request, maxRequestBytes)))
        return
      }
      if (method === 'POST' && url.pathname === '/api/internal-test/feedback') {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '只允许同源内测页面提交反馈' })
          return
        }
        json(response, 200, await internalTest.feedback(await readJson(request, maxRequestBytes)))
        return
      }
      if (method === 'GET' && url.pathname === '/api/control-plane/status') {
        json(response, 200, controlPlane.status())
        return
      }
      const operationsRoute = /^\/api\/control-plane\/accounts\/([^/]+)\/operations$/.exec(url.pathname)
      if (method === 'GET' && operationsRoute) {
        const accountId = decodeURIComponent(operationsRoute[1]!)
        json(
          response,
          200,
          await controlPlane.operations(operatorSession(request), 'qq', options.hub.botId(accountId)),
        )
        return
      }
      const pendingGroupsRoute = /^\/api\/control-plane\/accounts\/([^/]+)\/pending$/.exec(url.pathname)
      if (method === 'GET' && pendingGroupsRoute) {
        const accountId = decodeURIComponent(pendingGroupsRoute[1]!)
        json(
          response,
          200,
          await controlPlane.pendingInbox(operatorSession(request), 'qq', options.hub.botId(accountId)),
        )
        return
      }
      const managedGroupsRoute = /^\/api\/control-plane\/accounts\/([^/]+)\/managed$/.exec(url.pathname)
      if (method === 'GET' && managedGroupsRoute) {
        const accountId = decodeURIComponent(managedGroupsRoute[1]!)
        json(
          response,
          200,
          await controlPlane.managedGroups(operatorSession(request), 'qq', options.hub.botId(accountId)),
        )
        return
      }
      const profileCatalogRoute = /^\/api\/control-plane\/accounts\/([^/]+)\/profiles$/.exec(url.pathname)
      if (method === 'GET' && profileCatalogRoute) {
        const accountId = decodeURIComponent(profileCatalogRoute[1]!)
        json(
          response,
          200,
          await controlPlane.profileCatalog(operatorSession(request), 'qq', options.hub.botId(accountId)),
        )
        return
      }
      const controlPlaneGroupRoute = /^\/api\/control-plane\/accounts\/([^/]+)\/groups\/([^/]+)\/(preview|commands)$/.exec(
        url.pathname,
      )
      if (method === 'POST' && controlPlaneGroupRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '只允许同源控制后台提交命令' })
          return
        }
        const accountId = decodeURIComponent(controlPlaneGroupRoute[1]!)
        const groupId = decodeURIComponent(controlPlaneGroupRoute[2]!)
        const sessionRef = operatorSession(request)
        const botId = options.hub.botId(accountId)
        const body = await readJson(request, maxRequestBytes)
        if (controlPlaneGroupRoute[3] === 'preview') {
          const parsed = previewGroupServiceSchema.safeParse(body)
          if (!parsed.success) throw new Error('群服务 Preview 参数无效')
          json(response, 200, await controlPlane.preview(sessionRef, 'qq', botId, groupId, parsed.data))
        } else {
          const parsed = groupServiceCommandSchema.safeParse(body)
          if (!parsed.success) throw new Error('群服务命令参数无效')
          json(response, 200, await controlPlane.command(sessionRef, 'qq', botId, groupId, parsed.data))
        }
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
        response.setHeader('X-Accel-Buffering', 'no')
        response.flushHeaders()
        eventClients.add(response)
        response.write(workspaceEventFrame({ type: 'runtime.status', status: options.hub.runtimeStatus() }))
        const lastEventId = lastWorkspaceEventId(request)
        if (lastEventId === undefined) {
          response.write(workspaceEventFrame({ type: 'workspace.refresh' }))
        } else {
          const latestEventId = nextWorkspaceEventId - 1
          const oldestReplayableId = eventReplay[0]?.id ?? nextWorkspaceEventId
          if (lastEventId > latestEventId || lastEventId < oldestReplayableId - 1) {
            response.write(workspaceEventFrame({ type: 'workspace.refresh' }))
          } else {
            for (const replayable of eventReplay) {
              if (replayable.id > lastEventId) response.write(workspaceEventFrame(replayable.event, replayable.id))
            }
          }
        }
        request.once('close', () => eventClients.delete(response))
        return
      }
      const capabilitiesRoute = /^\/api\/accounts\/([^/]+)\/capabilities$/.exec(url.pathname)
      if (method === 'GET' && capabilitiesRoute) {
        json(response, 200, options.hub.capabilities(decodeURIComponent(capabilitiesRoute[1]!)))
        return
      }
      const directoryRoute = /^\/api\/accounts\/([^/]+)\/directory$/.exec(url.pathname)
      if (method === 'GET' && directoryRoute) {
        const parsed = directoryQuerySchema.safeParse(Object.fromEntries(url.searchParams.entries()))
        if (!parsed.success) {
          json(response, 400, { error: parsed.error.issues[0]?.message || '联系人请求参数无效' })
          return
        }
        json(
          response,
          200,
          await options.hub.directorySnapshot(decodeURIComponent(directoryRoute[1]!), parsed.data.refresh),
        )
        return
      }
      const notificationsRoute = /^\/api\/accounts\/([^/]+)\/notifications$/.exec(url.pathname)
      if (method === 'GET' && notificationsRoute) {
        const parsed = directoryQuerySchema.safeParse(Object.fromEntries(url.searchParams.entries()))
        if (!parsed.success) {
          json(response, 400, { error: parsed.error.issues[0]?.message || '通知请求参数无效' })
          return
        }
        json(
          response,
          200,
          await options.hub.notificationInbox(decodeURIComponent(notificationsRoute[1]!), parsed.data.refresh),
        )
        return
      }
      const notificationActionRoute = /^\/api\/accounts\/([^/]+)\/notifications\/([^/]+)\/resolve$/.exec(
        url.pathname,
      )
      if (method === 'POST' && notificationActionRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        const parsed = resolveNotificationSchema.safeParse(await readJson(request, maxRequestBytes))
        if (!parsed.success) {
          json(response, 400, { error: parsed.error.issues[0]?.message || '通知处理参数无效' })
          return
        }
        const notification = await options.hub.resolveNotification(
          decodeURIComponent(notificationActionRoute[1]!),
          decodeURIComponent(notificationActionRoute[2]!),
          parsed.data.action,
        )
        json(response, 200, { notification })
        return
      }
      const groupMembersRoute = /^\/api\/accounts\/([^/]+)\/groups\/([^/]+)\/members$/.exec(url.pathname)
      if (method === 'GET' && groupMembersRoute) {
        const parsed = groupMembersQuerySchema.safeParse(Object.fromEntries(url.searchParams.entries()))
        if (!parsed.success) {
          json(response, 400, { error: parsed.error.issues[0]?.message || '群成员请求参数无效' })
          return
        }
        json(
          response,
          200,
          await options.hub.memberDirectory(
            decodeURIComponent(groupMembersRoute[1]!),
            decodeURIComponent(groupMembersRoute[2]!),
            parsed.data.refresh,
          ),
        )
        return
      }
      const groupMemberAdminRoute =
        /^\/api\/accounts\/([^/]+)\/groups\/([^/]+)\/members\/([^/]+)\/admin$/.exec(url.pathname)
      if (method === 'PUT' && groupMemberAdminRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        const parsed = setGroupAdminSchema.safeParse(await readJson(request, maxRequestBytes))
        if (!parsed.success) {
          json(response, 400, { error: parsed.error.issues[0]?.message || '管理员设置参数无效' })
          return
        }
        await options.hub.setGroupAdmin(
          decodeURIComponent(groupMemberAdminRoute[1]!),
          decodeURIComponent(groupMemberAdminRoute[2]!),
          decodeURIComponent(groupMemberAdminRoute[3]!),
          parsed.data.enabled,
        )
        json(response, 200, { ok: true })
        return
      }
      const groupMemberCardRoute =
        /^\/api\/accounts\/([^/]+)\/groups\/([^/]+)\/members\/([^/]+)\/card$/.exec(url.pathname)
      if (method === 'PUT' && groupMemberCardRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        const parsed = setGroupCardSchema.safeParse(await readJson(request, maxRequestBytes))
        if (!parsed.success) {
          json(response, 400, { error: parsed.error.issues[0]?.message || '群名片参数无效' })
          return
        }
        await options.hub.setGroupCard(
          decodeURIComponent(groupMemberCardRoute[1]!),
          decodeURIComponent(groupMemberCardRoute[2]!),
          decodeURIComponent(groupMemberCardRoute[3]!),
          parsed.data.card,
        )
        json(response, 200, { ok: true })
        return
      }
      const groupMemberRoute = /^\/api\/accounts\/([^/]+)\/groups\/([^/]+)\/members\/([^/]+)$/.exec(url.pathname)
      if (method === 'DELETE' && groupMemberRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        await options.hub.kickGroupMember(
          decodeURIComponent(groupMemberRoute[1]!),
          decodeURIComponent(groupMemberRoute[2]!),
          decodeURIComponent(groupMemberRoute[3]!),
        )
        json(response, 200, { ok: true })
        return
      }
      const groupMuteRoute = /^\/api\/accounts\/([^/]+)\/groups\/([^/]+)\/mute-all$/.exec(url.pathname)
      if (method === 'PUT' && groupMuteRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        const parsed = setGroupMuteAllSchema.safeParse(await readJson(request, maxRequestBytes))
        if (!parsed.success) {
          json(response, 400, { error: parsed.error.issues[0]?.message || '全员禁言参数无效' })
          return
        }
        await options.hub.setGroupMuteAll(
          decodeURIComponent(groupMuteRoute[1]!),
          decodeURIComponent(groupMuteRoute[2]!),
          parsed.data.enabled,
        )
        json(response, 200, { ok: true })
        return
      }
      const groupRoute = /^\/api\/accounts\/([^/]+)\/groups\/([^/]+)$/.exec(url.pathname)
      if (method === 'PATCH' && groupRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        const parsed = renameGroupSchema.safeParse(await readJson(request, maxRequestBytes))
        if (!parsed.success) {
          json(response, 400, { error: parsed.error.issues[0]?.message || '群名称参数无效' })
          return
        }
        await options.hub.renameGroup(
          decodeURIComponent(groupRoute[1]!),
          decodeURIComponent(groupRoute[2]!),
          parsed.data.name,
        )
        json(response, 200, { ok: true })
        return
      }
      if (method === 'DELETE' && groupRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        await options.hub.quitGroup(
          decodeURIComponent(groupRoute[1]!),
          decodeURIComponent(groupRoute[2]!),
        )
        json(response, 200, { ok: true })
        return
      }
      const essenceRoute = /^\/api\/accounts\/([^/]+)\/groups\/([^/]+)\/essence$/.exec(url.pathname)
      if (method === 'GET' && essenceRoute) {
        json(
          response,
          200,
          await options.hub.essenceMessages(
            decodeURIComponent(essenceRoute[1]!),
            decodeURIComponent(essenceRoute[2]!),
          ),
        )
        return
      }
      const announcementsRoute = /^\/api\/accounts\/([^/]+)\/groups\/([^/]+)\/announcements$/.exec(url.pathname)
      if (method === 'GET' && announcementsRoute) {
        json(
          response,
          200,
          await options.hub.groupAnnouncements(
            decodeURIComponent(announcementsRoute[1]!),
            decodeURIComponent(announcementsRoute[2]!),
          ),
        )
        return
      }
      const announcementRoute =
        /^\/api\/accounts\/([^/]+)\/groups\/([^/]+)\/announcements\/([^/]+)$/.exec(url.pathname)
      if (method === 'DELETE' && announcementRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        await options.hub.deleteGroupAnnouncement(
          decodeURIComponent(announcementRoute[1]!),
          decodeURIComponent(announcementRoute[2]!),
          decodeURIComponent(announcementRoute[3]!),
        )
        json(response, 200, { ok: true })
        return
      }
      const groupFilesRoute = /^\/api\/accounts\/([^/]+)\/groups\/([^/]+)\/files$/.exec(url.pathname)
      if (method === 'GET' && groupFilesRoute) {
        const parsed = groupFilesQuerySchema.safeParse(Object.fromEntries(url.searchParams.entries()))
        if (!parsed.success) {
          json(response, 400, { error: parsed.error.issues[0]?.message || '群文件请求参数无效' })
          return
        }
        json(
          response,
          200,
          await options.hub.groupFiles(
            decodeURIComponent(groupFilesRoute[1]!),
            decodeURIComponent(groupFilesRoute[2]!),
            parsed.data.parentId,
            parsed.data.limit,
          ),
        )
        return
      }
      const groupFilesUploadRoute = /^\/api\/accounts\/([^/]+)\/groups\/([^/]+)\/files\/uploads$/.exec(url.pathname)
      if (method === 'POST' && groupFilesUploadRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        const parentId = url.searchParams.get('parentId') || '/'
        const upload = await readBrowserUpload(request)
        json(
          response,
          201,
          await options.hub.uploadGroupResource(
            decodeURIComponent(groupFilesUploadRoute[1]!),
            decodeURIComponent(groupFilesUploadRoute[2]!),
            parentId,
            upload,
          ),
        )
        return
      }
      const groupFileUrlRoute =
        /^\/api\/accounts\/([^/]+)\/groups\/([^/]+)\/files\/([^/]+)\/url$/.exec(url.pathname)
      if (method === 'GET' && groupFileUrlRoute) {
        json(
          response,
          200,
          await options.hub.groupFileDownloadUrl(
            decodeURIComponent(groupFileUrlRoute[1]!),
            decodeURIComponent(groupFileUrlRoute[2]!),
            decodeURIComponent(groupFileUrlRoute[3]!),
            url.searchParams.get('name') || '群文件',
          ),
        )
        return
      }
      const groupFileRoute = /^\/api\/accounts\/([^/]+)\/groups\/([^/]+)\/files\/([^/]+)$/.exec(url.pathname)
      if (method === 'PATCH' && groupFileRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        const parsed = groupFileMutationSchema.safeParse(await readJson(request, maxRequestBytes))
        if (!parsed.success) {
          json(response, 400, { error: parsed.error.issues[0]?.message || '群文件操作参数无效' })
          return
        }
        await options.hub.mutateGroupFile(
          decodeURIComponent(groupFileRoute[1]!),
          decodeURIComponent(groupFileRoute[2]!),
          decodeURIComponent(groupFileRoute[3]!),
          parsed.data,
        )
        json(response, 200, { ok: true })
        return
      }
      if (method === 'DELETE' && groupFileRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        await options.hub.deleteGroupFile(
          decodeURIComponent(groupFileRoute[1]!),
          decodeURIComponent(groupFileRoute[2]!),
          decodeURIComponent(groupFileRoute[3]!),
        )
        json(response, 200, { ok: true })
        return
      }
      const groupFoldersRoute = /^\/api\/accounts\/([^/]+)\/groups\/([^/]+)\/folders$/.exec(url.pathname)
      if (method === 'POST' && groupFoldersRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        const parsed = createGroupFolderSchema.safeParse(await readJson(request, maxRequestBytes))
        if (!parsed.success) {
          json(response, 400, { error: parsed.error.issues[0]?.message || '群文件夹参数无效' })
          return
        }
        await options.hub.createGroupFolder(
          decodeURIComponent(groupFoldersRoute[1]!),
          decodeURIComponent(groupFoldersRoute[2]!),
          parsed.data.name,
        )
        json(response, 201, { ok: true })
        return
      }
      const groupFolderRoute = /^\/api\/accounts\/([^/]+)\/groups\/([^/]+)\/folders\/([^/]+)$/.exec(url.pathname)
      if (method === 'DELETE' && groupFolderRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        await options.hub.deleteGroupFolder(
          decodeURIComponent(groupFolderRoute[1]!),
          decodeURIComponent(groupFolderRoute[2]!),
          decodeURIComponent(groupFolderRoute[3]!),
        )
        json(response, 200, { ok: true })
        return
      }
      const customFacesRoute =
        /^\/api\/accounts\/([^/]+)\/conversations\/(group|private)\/([^/]+)\/custom-faces$/.exec(url.pathname)
      if (method === 'GET' && customFacesRoute) {
        json(
          response,
          200,
          await options.hub.customFaceCatalog(
            decodeURIComponent(customFacesRoute[1]!),
            customFacesRoute[2] as 'group' | 'private',
            decodeURIComponent(customFacesRoute[3]!),
          ),
        )
        return
      }
      const customFacePreviewRoute =
        /^\/api\/accounts\/([^/]+)\/conversations\/(group|private)\/([^/]+)\/custom-faces\/([a-f0-9]{32})\/preview$/.exec(
          url.pathname,
        )
      if (method === 'GET' && customFacePreviewRoute) {
        const source = options.hub.customFaceUrl(
          decodeURIComponent(customFacePreviewRoute[1]!),
          customFacePreviewRoute[2] as 'group' | 'private',
          decodeURIComponent(customFacePreviewRoute[3]!),
          customFacePreviewRoute[4]!,
        )
        if (!source) {
          json(response, 404, { error: '收藏表情地址已过期' })
          return
        }
        await proxyImage(response, source, 'private, max-age=300')
        return
      }
      const messagesRoute = /^\/api\/accounts\/([^/]+)\/conversations\/(group|private)\/([^/]+)\/messages$/.exec(url.pathname)
      if (messagesRoute) {
        const account = decodeURIComponent(messagesRoute[1]!)
        const type = messagesRoute[2] as 'group' | 'private'
        const peerId = decodeURIComponent(messagesRoute[3]!)
        if (method === 'GET') {
          const parsed = historyQuerySchema.safeParse(Object.fromEntries(url.searchParams.entries()))
          if (!parsed.success) {
            json(response, 400, { error: parsed.error.issues[0]?.message || '历史请求参数无效' })
            return
          }
          const page = await options.hub.historyPage(account, type, peerId, parsed.data)
          json(response, 200, page)
          return
        }
        if (method === 'POST') {
          if (!sameOrigin(request, publicOrigin)) {
            json(response, 403, { error: '跨站写请求已拒绝' })
            return
          }
          const body = await readJson(request, maxRequestBytes)
          const parsed = sendMessageRequestSchema.safeParse(body)
          if (!parsed.success) {
            json(response, 400, { error: parsed.error.issues[0]?.message || '消息内容无效' })
            return
          }
          const message = await options.hub.sendSegments(account, type, peerId, parsed.data)
          json(response, 201, { message })
          return
        }
      }
      const uploadsRoute = /^\/api\/accounts\/([^/]+)\/conversations\/(group|private)\/([^/]+)\/uploads$/.exec(
        url.pathname,
      )
      if (method === 'POST' && uploadsRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        const account = decodeURIComponent(uploadsRoute[1]!)
        const type = uploadsRoute[2] as 'group' | 'private'
        const peerId = decodeURIComponent(uploadsRoute[3]!)
        options.hub.assertConversation(account, type, peerId)
        const purpose = url.searchParams.get('purpose')
        if (purpose !== 'media' && purpose !== 'file') {
          json(response, 400, { error: '上传 purpose 必须是 media 或 file' })
          return
        }
        const upload = await readBrowserUpload(request)
        if (purpose === 'file') {
          json(response, 201, await options.hub.sendFile(account, type, peerId, upload))
        } else {
          json(response, 201, options.hub.stageMediaUpload(account, type, peerId, upload))
        }
        return
      }
      const messageActionRoute =
        /^\/api\/accounts\/([^/]+)\/conversations\/(group|private)\/([^/]+)\/messages\/([^/]+)$/.exec(url.pathname)
      if (method === 'GET' && messageActionRoute) {
        const message = await options.hub.refreshMessage(
          decodeURIComponent(messageActionRoute[1]!),
          messageActionRoute[2] as 'group' | 'private',
          decodeURIComponent(messageActionRoute[3]!),
          decodeURIComponent(messageActionRoute[4]!),
        )
        json(response, 200, { message })
        return
      }
      if (method === 'DELETE' && messageActionRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        await options.hub.recallMessage(
          decodeURIComponent(messageActionRoute[1]!),
          messageActionRoute[2] as 'group' | 'private',
          decodeURIComponent(messageActionRoute[3]!),
          decodeURIComponent(messageActionRoute[4]!),
        )
        json(response, 200, { ok: true })
        return
      }
      const forwardActionRoute =
        /^\/api\/accounts\/([^/]+)\/conversations\/(group|private)\/([^/]+)\/messages\/([^/]+)\/forward$/.exec(
          url.pathname,
        )
      if (method === 'POST' && forwardActionRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        const parsed = forwardRequestSchema.safeParse(await readJson(request, maxRequestBytes))
        if (!parsed.success) {
          json(response, 400, { error: parsed.error.issues[0]?.message || '转发目标无效' })
          return
        }
        json(
          response,
          201,
          await options.hub.forwardMessage(
            decodeURIComponent(forwardActionRoute[1]!),
            forwardActionRoute[2] as 'group' | 'private',
            decodeURIComponent(forwardActionRoute[3]!),
            decodeURIComponent(forwardActionRoute[4]!),
            parsed.data.target,
          ),
        )
        return
      }
      const forwardedRoute =
        /^\/api\/accounts\/([^/]+)\/conversations\/(group|private)\/([^/]+)\/forwards\/([^/]+)$/.exec(url.pathname)
      if (method === 'GET' && forwardedRoute) {
        json(
          response,
          200,
          await options.hub.forwardedMessages(
            decodeURIComponent(forwardedRoute[1]!),
            forwardedRoute[2] as 'group' | 'private',
            decodeURIComponent(forwardedRoute[3]!),
            decodeURIComponent(forwardedRoute[4]!),
          ),
        )
        return
      }
      const nudgeRoute = /^\/api\/accounts\/([^/]+)\/conversations\/(group|private)\/([^/]+)\/nudge$/.exec(
        url.pathname,
      )
      if (method === 'POST' && nudgeRoute) {
        if (!sameOrigin(request, publicOrigin)) {
          json(response, 403, { error: '跨站写请求已拒绝' })
          return
        }
        const parsed = nudgeRequestSchema.safeParse(await readJson(request, maxRequestBytes))
        if (!parsed.success) {
          json(response, 400, { error: parsed.error.issues[0]?.message || 'QQ 号无效' })
          return
        }
        await options.hub.nudge(
          decodeURIComponent(nudgeRoute[1]!),
          nudgeRoute[2] as 'group' | 'private',
          decodeURIComponent(nudgeRoute[3]!),
          parsed.data.userId,
        )
        json(response, 200, { ok: true })
        return
      }
      const fileUrlRoute =
        /^\/api\/accounts\/([^/]+)\/conversations\/(group|private)\/([^/]+)\/files\/([^/]+)\/url$/.exec(
          url.pathname,
        )
      if (method === 'GET' && fileUrlRoute) {
        json(
          response,
          200,
          await options.hub.fileDownloadUrl(
            decodeURIComponent(fileUrlRoute[1]!),
            fileUrlRoute[2] as 'group' | 'private',
            decodeURIComponent(fileUrlRoute[3]!),
            decodeURIComponent(fileUrlRoute[4]!),
            url.searchParams.get('name') || 'QQ文件',
          ),
        )
        return
      }
      const readRoute = /^\/api\/accounts\/([^/]+)\/conversations\/(group|private)\/([^/]+)\/read$/.exec(url.pathname)
      if (method === 'POST' && readRoute) {
        if (!sameOrigin(request, publicOrigin)) {
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
        await proxyMessageMedia(request, response, source, 'private, max-age=300')
        return
      }
      const fileMediaRoute = /^\/api\/media\/file\/([a-f0-9]{32})$/.exec(url.pathname)
      if (method === 'GET' && fileMediaRoute) {
        const entry = options.hub.fileMedia(fileMediaRoute[1]!)
        if (!entry) {
          json(response, 404, { error: '文件地址已过期' })
          return
        }
        await proxyMessageFile(request, response, entry.url, entry.fileName)
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
