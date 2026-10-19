import { EventEmitter } from 'node:events'
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import type { AddressInfo } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  HttpRuntimeV3Client, RuntimeV3QqBridge, runtimeV3Scopes,
  type RuntimeV3OutboxItem, type RuntimeV3Request, type RuntimeV3Run,
} from './runtime-v3'
import { createAgentGateway, FileInternalTestGateway } from './internal-test'
import type { ChatMessage, GroupMemberDirectory, WorkspaceEvent } from '../src/types/workspace'
import { summaryForwardParts } from './summary-delivery'

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
  it('shows the configured Luna MAX result rather than a hardcoded low effort', async () => {
    const url = await serve((request, response) => {
      if (request.url === '/v3/health') return json(response, { codex_available: true,
        model: 'gpt-5.6-luna', reasoning_effort: 'max' })
      if (request.method === 'POST') return json(response, { run_id: 'run-v3', status: 'queued' })
      json(response, { ...completed, route: 'agent', model: 'gpt-5.6-luna', reasoning_effort: 'max' })
    })
    const client = new HttpRuntimeV3Client(url, 'test', fetch, 1_000, 1)
    expect(await client.status()).toMatchObject({ controls: { model: 'gpt-5.6-luna', reasoning_effort: 'max' } })
    expect(await client.preview({ ...scope, prompt: 'hello' })).toMatchObject({
      model: 'gpt-5.6-luna', reasoning: 'max', generationObserved: true,
    })
  })

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

const MEDIA_KEY = 'a'.repeat(32)
const QUOTED_KEY = 'b'.repeat(32)
const cdn = (key: string) => `https://multimedia.nt.qq.com.cn/download?appid=1407&fileid=${key}`

function bridgeFixture(scopes = runtimeV3Scopes(`${scope.accountId}/${scope.conversationId}`)) {
  const hub = Object.assign(new EventEmitter(), {
    sendRuntimeMessage: vi.fn(async (..._args: unknown[]) => ({ messageId: 'sent-1' })),
    sendRuntimeForward: vi.fn(async (..._args: unknown[]) => ({ messageId: 'rforward-1' })),
    sendMergedForward: vi.fn(async (..._args: unknown[]) => ({ messageId: 'forward-1' })),
    setMessageReaction: vi.fn(async (..._args: unknown[]) => undefined),
    sendFile: vi.fn(async (..._args: unknown[]) => ({ kind: 'file' as const, fileId: 'file-1', name: 'x', size: 1 })),
    resolveMediaSource: vi.fn((path: string | undefined) => {
      const key = /^\/api\/media\/message\/([0-9a-f]{32})$/.exec(path ?? '')?.[1]
      return key ? cdn(key) : undefined
    }),
    refreshMessage: vi.fn(async (..._args: unknown[]): Promise<ChatMessage> => { throw new Error('not cached') }),
    memberDirectory: vi.fn(async (..._args: unknown[]): Promise<GroupMemberDirectory> => { throw new Error('no directory') }),
  })
  const claims = new Set<string>()
  const runtime = {
    run: vi.fn(async (_request: RuntimeV3Request) => completed),
    delivery: vi.fn(async (id: string, state: string, _messageId?: string) => {
      if (state !== 'sending' || claims.has(id)) return false
      claims.add(id)
      return true
    }),
  }
  return { hub, runtime, bridge: new RuntimeV3QqBridge(hub, runtime, scopes, () => undefined) }
}

describe('Dududa 3.0 QQ bridge (synthetic delivery only)', () => {
  it.each(['/a help', '/help', '/help /a', '/ping'])('ignores %s addressed only to another user', async (text) => {
    const { bridge, runtime, hub } = bridgeFixture()
    const event = messageEvent()
    event.message.segments = [
      { type: 'mention', userId: '300002', label: '@Yurisaki', all: false },
      { type: 'text', text: ` ${text}` },
    ]
    await bridge.handle(event)
    expect(runtime.run).not.toHaveBeenCalled()
    expect(hub.sendRuntimeMessage).not.toHaveBeenCalled()
    expect(hub.sendMergedForward).not.toHaveBeenCalled()
    event.message.segments.unshift({ type: 'mention', userId: '100001', label: '@嘟嘟哒', all: false })
    await bridge.handle(event)
    expect(runtime.run).toHaveBeenCalledWith(expect.objectContaining({ mentioned: true, text: `@Yurisaki ${text}` }))
    bridge.close()
  })

  it('sends sender, quoted reply, mentions, absolute image URLs and normalized segments', async () => {
    const { bridge, runtime, hub } = bridgeFixture()
    hub.memberDirectory.mockResolvedValue({ members: [{ userId: '300002', card: '小红', nickname: '红' }] } as GroupMemberDirectory)
    hub.refreshMessage.mockResolvedValue({ ...messageEvent().message, messageId: '77', senderId: '300003', senderName: '老王',
      content: '原话[图片]', segments: [{ type: 'text', text: '原话' },
        { type: 'image', url: `/api/media/message/${QUOTED_KEY}`, sticker: false }] })
    const event = messageEvent()
    Object.assign(event.message, { senderName: '群名片', senderCard: '群名片', senderNickname: '昵称', role: 'admin',
      timestampMs: 1_790_000_000_000 })
    event.message.segments = [
      { type: 'reply', messageId: '77' },
      { type: 'mention', userId: '100001', label: '嘟嘟哒', all: false },
      { type: 'text', text: ' 看看 ' },
      { type: 'mention', userId: '300002', label: '300002', all: false },
      { type: 'image', url: `/api/media/message/${MEDIA_KEY}`, sticker: true, summary: '[动画表情]', width: 100, height: 80 },
      { type: 'face', faceId: '14', name: '微笑', market: false },
      { type: 'light_app', title: '小程序', url: 'https://b23.tv/x', description: '视频' },
      { type: 'forward', forwardId: 'f', preview: '聊天记录' },
      { type: 'audio' },
    ]
    await bridge.handle(event)
    const request = runtime.run.mock.calls[0]![0]
    const stickerImage = { url: cdn(MEDIA_KEY), sticker: true, summary: '[动画表情]', width: 100, height: 80 }
    expect(request).toEqual({
      account_id: 'qq-100001', conversation_id: 'qq-100001:group:200001', user_id: '300001', message_id: '1',
      text: '看看 @小红', mentioned: true, source: 'qq', preview: false,
      sender: { name: '群名片', card: '群名片', nickname: '昵称', role: 'admin' },
      reply: { message_id: '77', sender_id: '300003', sender_name: '老王', text: '原话',
        images: [{ url: cdn(QUOTED_KEY), sticker: false }] },
      mentions: [{ id: '300002', name: '小红' }],
      images: [stickerImage],
      segments: [
        { type: 'reply', message_id: '77' },
        { type: 'mention', id: '100001', name: '嘟嘟哒' },
        { type: 'text', text: ' 看看 ' },
        { type: 'mention', id: '300002', name: '小红' },
        { type: 'image', ...stickerImage },
        { type: 'face', id: '14', name: '微笑' },
        { type: 'light_app', title: '小程序', url: 'https://b23.tv/x', description: '视频' },
        { type: 'forward', preview: '聊天记录' },
        { type: 'unknown', summary: '[语音]' },
      ],
      timestamp: 1_790_000_000,
    })
    expect(hub.refreshMessage).toHaveBeenCalledWith('qq-100001', 'group', '200001', '77')
    bridge.close()
  })

  it('allows empty text for image-only messages and keeps the body under 200 KiB', async () => {
    const { bridge, runtime } = bridgeFixture()
    const event = messageEvent()
    event.message.segments = [{ type: 'image', url: `/api/media/message/${MEDIA_KEY}`, sticker: false }]
    await bridge.handle(event)
    expect(runtime.run.mock.calls[0]![0]).toMatchObject({ text: '', images: [{ url: cdn(MEDIA_KEY) }] })
    event.message.segments = Array.from({ length: 200 }, () => ({ type: 'text' as const, text: '长'.repeat(3000) }))
    await bridge.handle(event)
    const body = runtime.run.mock.calls[1]![0]
    expect(Buffer.byteLength(JSON.stringify(body))).toBeLessThan(200 * 1024)
    bridge.close()
  })

  it('groups consecutive content actions and sends forward, reaction and file actions standalone in order', async () => {
    const { bridge, runtime, hub } = bridgeFixture()
    const order: string[] = []
    hub.sendRuntimeMessage.mockImplementation(async () => { order.push('message'); return { messageId: `m${order.length}` } })
    hub.sendRuntimeForward.mockImplementation(async () => { order.push('forward'); return { messageId: 'fw' } })
    hub.setMessageReaction.mockImplementation(async () => { order.push('reaction') })
    hub.sendFile.mockImplementation(async () => { order.push('file'); return { kind: 'file', fileId: 'f', name: 'x', size: 1 } })
    runtime.run.mockResolvedValue({ ...completed, text: '天气', actions: [
      { type: 'text', text: '合肥 晴' },
      { type: 'image', data: 'aGVsbG8=', mime: 'image/png' },
      { type: 'face', id: 14 },
      { type: 'forward', nodes: [{ name: '嘟嘟哒', actions: [{ type: 'text', text: '节点' }, { type: 'image', url: 'https://example.com/a.png' }] }] },
      { type: 'reaction', message_id: '1', emoji_id: '66' },
      { type: 'file', name: 'H3_v2.pdf', data: Buffer.from('%PDF').toString('base64'), mime: 'application/pdf' },
      { type: 'image', url: 'https://example.com/b.png' },
    ] })
    await bridge.handle(messageEvent())
    expect(order).toEqual(['message', 'forward', 'reaction', 'file', 'message'])
    expect(hub.sendRuntimeMessage).toHaveBeenNthCalledWith(1, 'qq-100001', 'group', '200001', [
      { type: 'text', text: '合肥 晴' }, { type: 'image', file: 'base64://aGVsbG8=' }, { type: 'face', id: '14' },
    ])
    expect(hub.sendRuntimeForward).toHaveBeenCalledWith('qq-100001', 'group', '200001', [
      { name: '嘟嘟哒', parts: [{ type: 'text', text: '节点' }, { type: 'image', file: 'https://example.com/a.png' }] },
    ])
    expect(hub.setMessageReaction).toHaveBeenCalledWith('qq-100001', '1', '66')
    expect(hub.sendFile).toHaveBeenCalledWith('qq-100001', 'group', '200001',
      { buffer: Buffer.from('%PDF'), fileName: 'H3_v2.pdf', size: 4 })
    expect(hub.sendRuntimeMessage).toHaveBeenLastCalledWith('qq-100001', 'group', '200001', [
      { type: 'image', file: 'https://example.com/b.png' },
    ])
    expect(runtime.delivery).toHaveBeenCalledWith('run-v3', 'sent', 'm1')
    bridge.close()
  })

  it('claims reaction-only results once and reports them sent', async () => {
    const { bridge, runtime, hub } = bridgeFixture()
    runtime.run.mockResolvedValue({ ...completed, route: 'observer', text: '', actions: [{ type: 'reaction', message_id: '1', emoji_id: '66' }] })
    await Promise.all([bridge.handle(messageEvent()), bridge.handle(messageEvent())])
    expect(hub.setMessageReaction).toHaveBeenCalledTimes(1)
    expect(runtime.delivery).toHaveBeenCalledWith('run-v3', 'sending')
    expect(runtime.delivery).toHaveBeenCalledWith('run-v3', 'sent', undefined)
    expect(hub.sendRuntimeMessage).not.toHaveBeenCalled()
    bridge.close()
  })

  it('sends a long summary once as merged forward, preserving all text and Unicode', async () => {
    const { bridge, runtime, hub } = bridgeFixture()
    const text = '14:20 小明在东区提出方案。😀\n\n'.repeat(150)
    runtime.run.mockResolvedValue({ ...completed, route: 'agent', response_kind: 'conversation_summary', text,
      actions: [{ type: 'text', text }] })
    await Promise.all([bridge.handle(messageEvent()), bridge.handle(messageEvent())])
    expect(hub.sendRuntimeMessage).not.toHaveBeenCalled()
    expect(hub.sendMergedForward).toHaveBeenCalledTimes(1)
    const args = hub.sendMergedForward.mock.calls[0] as unknown as [string, string, string, string[]]
    expect(args.slice(0, 3)).toEqual(['qq-100001', 'group', '200001'])
    expect(args[3].join('')).toBe(text)
    expect(args[3].every(part => Array.from(part).length <= 1200)).toBe(true)
    expect(runtime.delivery).toHaveBeenCalledWith('run-v3', 'sent', 'forward-1')
    bridge.close()
  })

  it('keeps a short summary as text and never retries an uncertain forward', async () => {
    const { bridge, runtime, hub } = bridgeFixture()
    runtime.run.mockResolvedValue({ ...completed, response_kind: 'conversation_summary', text: '短总结' })
    await bridge.handle(messageEvent())
    expect(hub.sendRuntimeMessage).toHaveBeenCalledTimes(1)
    runtime.run.mockResolvedValue({ ...completed, run_id: 'long-run', response_kind: 'conversation_summary', text: '长'.repeat(1201) })
    hub.sendMergedForward.mockRejectedValue(new Error('forward timeout'))
    await expect(bridge.handle(messageEvent())).rejects.toThrow('forward timeout')
    await bridge.handle(messageEvent())
    expect(hub.sendMergedForward).toHaveBeenCalledTimes(1)
    expect(hub.sendRuntimeMessage).toHaveBeenCalledTimes(1)
    expect(runtime.delivery).toHaveBeenCalledWith('long-run', 'unknown')
    expect(summaryForwardParts('😀'.repeat(2401)).join('')).toBe('😀'.repeat(2401))
    bridge.close()
  })

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
    expect(hub.sendRuntimeMessage).not.toHaveBeenCalled()
    bridge.close()
  })

  it('claims a durable delivery once even when duplicate events arrive concurrently', async () => {
    const { bridge, runtime, hub } = bridgeFixture()
    await Promise.all([bridge.handle(messageEvent()), bridge.handle(messageEvent())])
    expect(hub.sendRuntimeMessage).toHaveBeenCalledTimes(1)
    expect(hub.sendRuntimeMessage).toHaveBeenCalledWith('qq-100001', 'group', '200001', [{ type: 'text', text: 'pong' }])
    expect(runtime.delivery).toHaveBeenCalledWith('run-v3', 'sent', 'sent-1')
    bridge.close()
    expect(hub.listenerCount('workspace-event')).toBe(0)
  })

  it('records uncertain send results and does not resend on a repeated event', async () => {
    const { bridge, runtime, hub } = bridgeFixture()
    hub.sendRuntimeMessage.mockRejectedValue(new Error('OneBot timeout'))
    await expect(bridge.handle(messageEvent())).rejects.toThrow('OneBot timeout')
    expect(runtime.delivery).toHaveBeenCalledWith('run-v3', 'unknown')
    await bridge.handle(messageEvent())
    expect(hub.sendRuntimeMessage).toHaveBeenCalledTimes(1)
    bridge.close()
  })
})

describe('Dududa 3.0 outbox poller', () => {
  function outboxFixture(items: RuntimeV3OutboxItem[]) {
    const { hub, runtime } = bridgeFixture()
    const outbox = {
      ...runtime,
      claimOutbox: vi.fn(async (_limit?: number) => items.splice(0)),
      outboxResult: vi.fn(async (_id: number | string, _state: 'sent' | 'unknown', _messageId?: string) => undefined),
    }
    const errors: unknown[] = []
    const bridge = new RuntimeV3QqBridge(hub, outbox, runtimeV3Scopes(`${scope.accountId}/${scope.conversationId}`),
      error => errors.push(error), 0)
    return { hub, outbox, bridge, errors }
  }

  it('claims, delivers to the parsed conversation, and reports results without retrying failures', async () => {
    const { hub, outbox, bridge, errors } = outboxFixture([
      { id: 1, account_id: scope.accountId, conversation_id: scope.conversationId,
        actions: [{ type: 'text', text: '预警' }, { type: 'image', url: 'https://example.com/r.png' }] },
      { id: 2, account_id: scope.accountId, conversation_id: 'qq-100001:group:999999', actions: [{ type: 'text', text: '不该发' }] },
      { id: 3, account_id: scope.accountId, conversation_id: scope.conversationId, actions: [{ type: 'text', text: '失败' }] },
    ])
    hub.sendRuntimeMessage.mockResolvedValueOnce({ messageId: 'out-1' }).mockRejectedValueOnce(new Error('OneBot timeout'))
    await bridge.pollOutbox()
    expect(outbox.claimOutbox).toHaveBeenCalledWith(10)
    expect(hub.sendRuntimeMessage).toHaveBeenCalledTimes(2)
    expect(hub.sendRuntimeMessage).toHaveBeenNthCalledWith(1, 'qq-100001', 'group', '200001', [
      { type: 'text', text: '预警' }, { type: 'image', file: 'https://example.com/r.png' },
    ])
    expect(outbox.outboxResult.mock.calls).toEqual([[1, 'sent', 'out-1'], [2, 'unknown'], [3, 'unknown']])
    expect(errors).toHaveLength(2)
    await bridge.pollOutbox()
    expect(hub.sendRuntimeMessage).toHaveBeenCalledTimes(2)
    bridge.close()
  })

  it('never overlaps ticks and swallows claim errors', async () => {
    const { outbox, bridge, errors } = outboxFixture([])
    let release!: () => void
    outbox.claimOutbox.mockImplementationOnce(() => new Promise(resolve => { release = () => resolve([]) }))
    const first = bridge.pollOutbox()
    await bridge.pollOutbox()
    expect(outbox.claimOutbox).toHaveBeenCalledTimes(1)
    release()
    await first
    outbox.claimOutbox.mockRejectedValueOnce(new Error('host down'))
    await bridge.pollOutbox()
    expect(errors).toHaveLength(1)
    bridge.close()
  })

  it('runs on a timer, private conversations included, and stops on close', async () => {
    vi.useFakeTimers()
    try {
      const { hub } = bridgeFixture()
      const privateScope = 'qq-100001:private:300001'
      const items: RuntimeV3OutboxItem[] = [{ id: 9, account_id: scope.accountId, conversation_id: privateScope,
        actions: [{ type: 'file', name: 'H3_v2.pdf', data: 'JVBERg==' }] }]
      const outbox = {
        run: vi.fn(), delivery: vi.fn(),
        claimOutbox: vi.fn(async () => items.splice(0)),
        outboxResult: vi.fn(async () => undefined),
      }
      const bridge = new RuntimeV3QqBridge(hub, outbox, runtimeV3Scopes(`${scope.accountId}/${privateScope}`), () => undefined)
      await vi.advanceTimersByTimeAsync(3_000)
      expect(hub.sendFile).toHaveBeenCalledWith('qq-100001', 'private', '300001',
        { buffer: Buffer.from('%PDF'), fileName: 'H3_v2.pdf', size: 4 })
      expect(outbox.outboxResult).toHaveBeenCalledWith(9, 'sent', 'file-1')
      bridge.close()
      await vi.advanceTimersByTimeAsync(10_000)
      expect(outbox.claimOutbox).toHaveBeenCalledTimes(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('uses the Host outbox endpoints', async () => {
    const requests: Array<{ url?: string; body: string }> = []
    const base = await serve((request, response) => {
      let body = ''
      request.on('data', chunk => { body += chunk })
      request.on('end', () => {
        requests.push({ url: request.url, body })
        json(response, request.url === '/v3/outbox/claim'
          ? { items: [{ id: 5, account_id: scope.accountId, conversation_id: scope.conversationId, actions: [] }] }
          : { updated: true })
      })
    })
    const client = new HttpRuntimeV3Client(base, 'token')
    await expect(client.claimOutbox()).resolves.toEqual([{ id: 5, account_id: scope.accountId, conversation_id: scope.conversationId, actions: [] }])
    await client.outboxResult(5, 'sent', 'm-1')
    expect(requests).toEqual([
      { url: '/v3/outbox/claim', body: '{"limit":10}' },
      { url: '/v3/outbox/5/result', body: '{"state":"sent","message_id":"m-1"}' },
    ])
  })
})
