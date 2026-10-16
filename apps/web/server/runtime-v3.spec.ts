import { EventEmitter } from 'node:events'
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import type { AddressInfo } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { HttpRuntimeV3Client, RuntimeV3QqBridge, runtimeV3Scopes, type RuntimeV3Run } from './runtime-v3'
import { createAgentGateway, FileInternalTestGateway } from './internal-test'
import type { ChatMessage, WorkspaceEvent } from '../src/types/workspace'

const servers: Server[] = []
afterEach(async () => {
  await Promise.all(servers.splice(0).map(server => new Promise<void>((resolve, reject) => {
    server.closeAllConnections()
    server.close(error => error ? reject(error) : resolve())
  })))
})

async function serve(handler: (request: IncomingMessage, response: ServerResponse) => void): Promise<string> {
  const server = createServer(handler)
  servers.push(server)
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}`
}

function json(response: ServerResponse, body: Record<string, unknown>, status = 200): void {
  response.writeHead(status, { 'Content-Type': 'application/json' })
  response.end(JSON.stringify({ runtime: 'dududa-3.0', ...body }))
}

const completed: RuntimeV3Run = {
  runtime: 'dududa-3.0', run_id: 'run-v3', status: 'completed', route: 'rule',
  text: 'pong', tool_calls: 0, events: [], created_at: '2026-10-15T01:00:00Z', latency_ms: 2,
}
const scope = { accountId: 'qq-100001', conversationId: 'qq-100001:group:200001' }

describe('Dududa 3.0 HTTP adapter', () => {
  it('authenticates against v3, polls the run, and identifies deterministic output without claiming LLM generation', async () => {
    const requests: Array<{ path: string; method: string; body: string }> = []
    let reads = 0
    const url = await serve((request, response) => {
      expect(request.headers.authorization).toBe('Bearer v3-secret')
      let body = ''
      request.on('data', chunk => { body += chunk })
      request.on('end', () => {
        requests.push({ path: request.url!, method: request.method!, body })
        if (request.url === '/v3/health') json(response, { version: '3.0.0', codex_available: false })
        else if (request.url === '/v3/runs') json(response, { run_id: 'run-v3', status: 'queued' }, 202)
        else json(response, reads++ === 0 ? { ...completed, status: 'running' } : completed)
      })
    })
    const client = new HttpRuntimeV3Client(url, 'v3-secret', fetch, 1_000, 1)
    const status = await client.status()
    expect(status).toMatchObject({ ready: true, modelMapping: {}, controls: { runtime: 'dududa-3.0', codex_available: false } })
    const result = await client.preview({ ...scope, prompt: '/ping' })
    expect(result).toMatchObject({ candidate: 'pong', tier: 'rules', model: '', generationObserved: false,
      outputCalls: 0, memoryWrites: 0, toolCalls: 0, runtimeState: 'dududa-3.0:completed' })
    expect(result.reasonCodes).toContain('runtime_v3')
    expect(JSON.parse(requests.find(request => request.path === '/v3/runs')!.body)).toMatchObject({
      account_id: scope.accountId, conversation_id: scope.conversationId, source: 'web', preview: true,
      text: '/ping', mentioned: true, user_id: 'web-preview',
    })
    expect(requests.map(request => request.path)).toEqual(['/v3/health', '/v3/runs', '/v3/runs/run-v3', '/v3/runs/run-v3'])
  })

  it('uses v3 through the existing Web Agent gateway and carries server history without inventing legacy model tiers', async () => {
    let input: Record<string, unknown> = {}
    const url = await serve((request, response) => {
      if (request.url === '/v3/health') return json(response, { codex_available: true })
      if (request.method === 'POST') {
        let body = ''
        request.on('data', chunk => { body += chunk })
        request.on('end', () => { input = JSON.parse(body); json(response, { run_id: 'run-v3', status: 'queued' }) })
      } else json(response, { ...completed, route: 'agent', model: 'local-codex-model', text: '模型回答', tool_calls: 2,
        context_messages: 1, context_characters: 4, context_truncated: true })
    })
    const gateway = createAgentGateway({}, new HttpRuntimeV3Client(url, 'v3-secret'), async () => ({
      messages: [{ ...messageEvent().message, content: '服务器历史' }], hasMoreBefore: false, hasMoreAfter: false,
    }))
    expect((await gateway.agentStatus()).readinessReason).toContain('Dududa 3.0')
    const result = await gateway.respond({ ...scope, conversationName: '测试群', conversationType: 'group', prompt: '帮我总结' })
    expect(result).toMatchObject({ runtimePath: 'dududa_3_preview', tier: 'codex', model: 'local-codex-model', generationObserved: true, toolCalls: 2 })
    expect(result.contextUsage).toMatchObject({ messagesRead: 1, charactersRead: 4,
      coverage: { truncated: true, historyMessagesRead: 0, oldestAt: null, newestAt: null } })
    expect(input.history).toMatchObject({ source: 'server_recent', messages: [expect.objectContaining({ content: '服务器历史' })] })
  })

  it('cancels a timed-out v3 run without retrying through the old runtime', async () => {
    const paths: string[] = []
    const url = await serve((request, response) => {
      paths.push(request.url!)
      if (request.url?.endsWith('/cancel')) return json(response, { run_id: 'run-v3', status: 'cancelled' })
      json(response, { ...completed, status: 'running' })
    })
    const client = new HttpRuntimeV3Client(url, 'v3-secret', fetch, 40, 5)
    await expect(client.preview({ ...scope, prompt: 'slow' })).rejects.toMatchObject({ status: 504 })
    expect(paths.at(-1)).toBe('/v3/runs/run-v3/cancel')
    expect(paths.every(path => path.startsWith('/v3/'))).toBe(true)
  })

  it('routes historical sample generation through v3 instead of the archived candidate provider', async () => {
    const root = await mkdtemp(join(tmpdir(), 'dududa-v3-sample-'))
    try {
      await mkdir(join(root, 'demo'))
      await writeFile(join(root, 'demo/index.html'), `<script id="demo-data" type="application/json">${JSON.stringify({
        windows: [{ window_id: 'v3-sample', messages: [{ sender_ref: 'user', text: '合成样本' }] }],
      })}</script>`)
      const url = await serve((request, response) => {
        if (request.method === 'POST') return json(response, { run_id: 'run-v3', status: 'queued' })
        json(response, { ...completed, route: 'agent', model: 'local-codex-model', tool_calls: 2 })
      })
      const gateway = new FileInternalTestGateway({ dataRoot: root, runtimePreview: new HttpRuntimeV3Client(url, 'v3-secret') })
      await expect(gateway.generate({ windowId: 'v3-sample' })).resolves.toMatchObject({
        runtimePath: 'dududa_3_preview', tier: 'codex', generationObserved: true, providerCalls: null,
        toolCalls: 2, outputCalls: 0, memoryWrites: 0,
      })
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })

  it('rejects another runtime even if HTTP is successful and never exposes upstream auth details', async () => {
    const wrongRuntime = new HttpRuntimeV3Client('http://unit.invalid', 'v3-secret', vi.fn(async () =>
      new Response(JSON.stringify({ runtime: 'dududa-2.0', ready: true }))) as typeof fetch)
    await expect(wrongRuntime.status()).rejects.toThrow('已拒绝回退')
    const forbidden = new HttpRuntimeV3Client('http://unit.invalid', 'v3-secret', vi.fn(async () =>
      new Response('secret-sentinel', { status: 403 })) as typeof fetch)
    await expect(forbidden.preview({ ...scope, prompt: '/ping' })).rejects.toMatchObject({ status: 403, message: expect.stringContaining('认证失败') })
  })
})

function messageEvent(): Extract<WorkspaceEvent, { type: 'message.created' }> {
  return {
    type: 'message.created',
    conversation: { id: scope.conversationId, accountId: scope.accountId, type: 'group', peerId: '200001',
      name: '测试群', avatar: '', lastMessage: '', lastMessageAt: '', unread: 0, pinned: false, muted: false },
    message: { ...scope, id: `${scope.conversationId}:1`, messageId: '1', senderId: '300001',
      senderName: '用户', senderAvatar: '', timestamp: '', content: '/ping', segments: [{ type: 'text', text: '/ping' }], mine: false },
  }
}

function bridgeFixture(scopes = runtimeV3Scopes(`${scope.accountId}/${scope.conversationId}`)) {
  const hub = Object.assign(new EventEmitter(), {
    sendSegments: vi.fn(async () => ({ ...messageEvent().message, messageId: 'sent-1', mine: true }) as ChatMessage),
  })
  const claims = new Set<string>()
  const runtime = {
    run: vi.fn(async () => completed),
    delivery: vi.fn(async (id: string, state: string, _messageId?: string) => {
      if (state !== 'sending' || claims.has(id)) return false
      claims.add(id)
      return true
    }),
  }
  return { hub, runtime, bridge: new RuntimeV3QqBridge(hub, runtime, scopes) }
}

describe('Dududa 3.0 QQ bridge (synthetic delivery only)', () => {
  it('ignores self messages and scopes not explicitly enabled', async () => {
    const { bridge, runtime } = bridgeFixture()
    const own = messageEvent()
    own.message.mine = true
    await bridge.handle(own)
    own.message.mine = false
    own.message.senderId = '100001'
    await bridge.handle(own)
    const empty = bridgeFixture(runtimeV3Scopes())
    await empty.bridge.handle(messageEvent())
    expect(runtime.run).not.toHaveBeenCalled()
    expect(empty.runtime.run).not.toHaveBeenCalled()
    bridge.close()
    empty.bridge.close()
  })

  it('passes ordinary group messages to Host participation rules, including correct mention state', async () => {
    const { bridge, runtime, hub } = bridgeFixture()
    runtime.run.mockResolvedValue({ ...completed, status: 'ignored', route: 'ignore', text: '' })
    const event = messageEvent()
    event.message.segments = [{ type: 'text', text: '普通群聊' }]
    await bridge.handle(event)
    expect(runtime.run).toHaveBeenCalledWith(expect.objectContaining({ mentioned: false, text: '普通群聊', preview: false, source: 'qq' }))
    event.message.segments.unshift({ type: 'mention', userId: '100001', label: '@机器人', all: false })
    await bridge.handle(event)
    expect(runtime.run).toHaveBeenLastCalledWith(expect.objectContaining({ mentioned: true, text: '普通群聊' }))
    expect(hub.sendSegments).not.toHaveBeenCalled()
    bridge.close()
  })

  it('claims a durable delivery once even when duplicate events arrive concurrently', async () => {
    const { bridge, runtime, hub } = bridgeFixture()
    await Promise.all([bridge.handle(messageEvent()), bridge.handle(messageEvent())])
    expect(hub.sendSegments).toHaveBeenCalledTimes(1)
    expect(hub.sendSegments).toHaveBeenCalledWith('qq-100001', 'group', '200001', [{ type: 'text', text: 'pong' }])
    expect(runtime.delivery).toHaveBeenCalledWith('run-v3', 'sent', 'sent-1')
    bridge.close()
    expect(hub.listenerCount('workspace-event')).toBe(0)
  })

  it('records uncertain send results and does not resend on a repeated event', async () => {
    const { bridge, runtime, hub } = bridgeFixture()
    hub.sendSegments.mockRejectedValue(new Error('OneBot timeout'))
    await expect(bridge.handle(messageEvent())).rejects.toThrow('OneBot timeout')
    expect(runtime.delivery).toHaveBeenCalledWith('run-v3', 'unknown')
    await bridge.handle(messageEvent())
    expect(hub.sendSegments).toHaveBeenCalledTimes(1)
    bridge.close()
  })
})
