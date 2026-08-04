import type { AddressInfo } from 'node:net'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { WebSocket } from 'ws'

import { createDududaServer } from './app'
import { OneBotHub, type HubOptions } from './onebot-hub'

const token = 'test-only-onebot-token-32-characters'
const selfId = '123456789'

interface ActionRequest {
  action: string
  params: Record<string, unknown>
  echo: string
}

function realGroupMessage(content = '来自真实 NapCat 的消息', overrides: Record<string, unknown> = {}) {
  return {
    self_id: Number(selfId),
    time: 1_785_742_400,
    message_id: 101,
    message_seq: 101,
    real_id: 101,
    user_id: 234567890,
    group_id: 345678901,
    group_name: '真实测试群',
    message_type: 'group',
    post_type: 'message',
    sender: { user_id: 234567890, nickname: '群成员', card: '测试成员', role: 'member' },
    message: [{ type: 'text', data: { text: content } }],
    message_format: 'array',
    raw_message: content,
    font: 0,
    ...overrides,
  }
}

async function startTestServer(options: Omit<HubOptions, 'token'> = {}) {
  const hub = new OneBotHub({ token, actionTimeoutMs: 2_000, ...options })
  const server = createDududaServer({ hub, publicDir: '/tmp/dududa-web-does-not-exist' })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const port = (server.address() as AddressInfo).port
  const baseUrl = `http://127.0.0.1:${port}`
  return { hub, server, port, baseUrl }
}

async function closeServer(server: ReturnType<typeof createDududaServer>): Promise<void> {
  await new Promise<void>((resolve) => server.close(() => resolve()))
}

async function waitFor(predicate: () => Promise<boolean>, timeoutMs = 2_000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await predicate()) return
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
  throw new Error('condition timed out')
}

interface FakeNapCatOptions {
  loginSelfId?: string
  reportSentEvent?: boolean
}

interface FakeNapCatState {
  loginSelfId: string
  groups: unknown[]
  friends: unknown[]
  recent: unknown[]
  failedActions: Set<string>
  reportSentEvent: boolean
}

function connectFakeNapCat(port: number, options: FakeNapCatOptions = {}) {
  const actions: ActionRequest[] = []
  let lastSentText = ''
  const state: FakeNapCatState = {
    loginSelfId: options.loginSelfId ?? selfId,
    groups: [{ group_id: 345678901, group_name: '真实测试群', group_remark: '', member_count: 42 }],
    friends: [{ user_id: 456789012, nickname: '真实好友', remark: '好友备注' }],
    recent: [
      {
        lastestMsg: realGroupMessage(),
        peerUin: '345678901',
        remark: '',
        msgTime: '1785742400',
        chatType: 2,
        msgId: '101',
        sendNickName: '群成员',
        sendMemberName: '测试成员',
        peerName: '真实测试群',
      },
    ],
    failedActions: new Set(),
    reportSentEvent: options.reportSentEvent ?? false,
  }
  const socket = new WebSocket(`ws://127.0.0.1:${port}/onebot/v11/ws`, {
    headers: {
      'X-Self-ID': selfId,
      Authorization: `Bearer ${token}`,
      'X-Client-Role': 'Universal',
    },
  })
  clients.add(socket)
  const ready = new Promise<void>((resolve, reject) => {
    socket.once('open', resolve)
    socket.once('error', reject)
  })
  const closed = new Promise<{ code: number; reason: string }>((resolve) => {
    socket.once('close', (code, reason) => resolve({ code, reason: reason.toString() }))
  })
  socket.once('close', () => clients.delete(socket))
  socket.on('message', (payload) => {
    const request = JSON.parse(payload.toString()) as ActionRequest
    actions.push(request)
    if (state.failedActions.has(request.action)) {
      socket.send(JSON.stringify({ status: 'failed', retcode: 1200, data: null, message: 'fixture failure', echo: request.echo }))
      return
    }
    let data: unknown
    switch (request.action) {
      case 'get_login_info':
        data = { user_id: Number(state.loginSelfId), nickname: '真实机器人' }
        break
      case 'get_status':
        data = { online: true, good: true, stat: {} }
        break
      case 'get_version_info':
        data = { app_name: 'NapCat.Onebot', protocol_version: 'v11', app_version: '4.18.13' }
        break
      case 'get_group_list':
        data = state.groups
        break
      case 'get_friend_list':
        data = state.friends
        break
      case 'get_recent_contact':
        data = state.recent
        break
      case 'get_group_msg_history':
        data = { messages: [realGroupMessage()] }
        break
      case 'get_friend_msg_history':
        data = {
          messages: [
            {
              self_id: Number(selfId),
              time: 1_785_742_400,
              message_id: 201,
              message_seq: 201,
              user_id: 456789012,
              message_type: 'private',
              post_type: 'message_sent',
              sender: { user_id: Number(selfId), nickname: '真实机器人' },
              message: [{ type: 'text', data: { text: '本账号发出的私聊历史' } }],
              raw_message: '本账号发出的私聊历史',
            },
          ],
        }
        break
      case 'send_group_msg':
        lastSentText = String((request.params.message as Array<{ data?: { text?: string } }>)[0]?.data?.text ?? '')
        data = { message_id: 102 }
        if (state.reportSentEvent) {
          socket.send(
            JSON.stringify(
              realGroupMessage(lastSentText, {
                post_type: 'message_sent',
                message_id: 102,
                message_seq: 102,
                user_id: Number(selfId),
                sender: { user_id: Number(selfId), nickname: '真实机器人' },
              }),
            ),
          )
        }
        break
      case 'get_msg':
        data = {
          ...realGroupMessage(lastSentText),
          message_id: 102,
          message_seq: 102,
          user_id: Number(selfId),
          sender: { user_id: Number(selfId), nickname: '真实机器人' },
        }
        break
      case 'mark_group_msg_as_read':
        data = null
        break
      default:
        socket.send(JSON.stringify({ status: 'failed', retcode: 1404, data: null, message: 'unsupported', echo: request.echo }))
        return
    }
    socket.send(JSON.stringify({ status: 'ok', retcode: 0, data, message: '', echo: request.echo }))
  })
  return { socket, actions, state, ready, closed }
}

const clients = new Set<WebSocket>()
const servers: Array<ReturnType<typeof createDududaServer>> = []

afterEach(async () => {
  for (const socket of clients) socket.terminate()
  clients.clear()
  await Promise.allSettled(servers.splice(0).map((server) => closeServer(server)))
})

describe('Dududa NapCat gateway', () => {
  it('serves workspace data without browser authentication', async () => {
    const { server, baseUrl } = await startTestServer()
    servers.push(server)

    const response = await fetch(`${baseUrl}/api/workspace`)

    expect(response.status).toBe(200)
  })

  it('rejects reverse websocket clients with the wrong token', async () => {
    const { server, port } = await startTestServer()
    servers.push(server)

    const status = await new Promise<number>((resolve, reject) => {
      const socket = new WebSocket(`ws://127.0.0.1:${port}/onebot/v11/ws`, {
        headers: { 'X-Self-ID': selfId, Authorization: 'Bearer wrong-token-value' },
      })
      socket.once('unexpected-response', (_request, response) => resolve(response.statusCode ?? 0))
      socket.once('error', reject)
    })

    expect(status).toBe(401)
  })

  it('loads real accounts, conversations, history, and sends through the action channel', async () => {
    const { server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port)

    await waitFor(async () => {
      const response = await fetch(`${baseUrl}/api/workspace`)
      const body = (await response.json()) as { accounts: unknown[] }
      return body.accounts.length === 1
    })

    const workspace = (await (await fetch(`${baseUrl}/api/workspace`)).json()) as {
      runtime: { status: string }
      accounts: Array<{ botId: string; name: string }>
      conversations: Array<{ id: string; name: string; lastMessage: string }>
    }
    expect(workspace.runtime.status).toBe('connected')
    expect(workspace.accounts[0]).toMatchObject({ botId: selfId, name: '真实机器人' })
    expect(workspace.conversations.some((item) => item.name === '真实测试群')).toBe(true)

    const account = `qq-${selfId}`
    const messageUrl = `${baseUrl}/api/accounts/${account}/conversations/group/345678901/messages`
    const history = (await (await fetch(messageUrl)).json()) as { messages: Array<{ content: string }> }
    expect(history.messages[0]?.content).toBe('来自真实 NapCat 的消息')

    const privateHistory = (await (
      await fetch(`${baseUrl}/api/accounts/${account}/conversations/private/456789012/messages`)
    ).json()) as { messages: Array<{ id: string; mine: boolean; senderId: string }> }
    expect(privateHistory.messages[0]).toMatchObject({
      id: `${account}:private:456789012:201`,
      mine: true,
      senderId: selfId,
    })

    const unknownConversation = await fetch(
      `${baseUrl}/api/accounts/${account}/conversations/private/999999999/messages`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Origin: baseUrl },
        body: JSON.stringify({ content: '不应发送到未发现的会话' }),
      },
    )
    expect(unknownConversation.status).toBe(404)
    expect(napcat.actions.some((item) => item.action === 'send_private_msg')).toBe(false)

    const sent = await fetch(messageUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ content: '由真实动作通道发送' }),
    })
    expect(sent.status).toBe(201)
    const sentBody = (await sent.json()) as { message: { content: string; mine: boolean } }
    expect(sentBody.message).toMatchObject({ content: '由真实动作通道发送', mine: true })
    expect(napcat.actions.some((item) => item.action === 'send_group_msg')).toBe(true)
    napcat.socket.close()
  })

  it('normalizes live OneBot message events without exposing the raw event', async () => {
    const { hub, server, port } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await waitFor(async () => hub.workspaceSnapshot().accounts.length === 1)

    const eventPromise = new Promise<unknown>((resolve) => {
      const listener = (event: unknown) => {
        if ((event as { type?: string }).type === 'message.created') {
          hub.off('workspace-event', listener)
          resolve(event)
        }
      }
      hub.on('workspace-event', listener)
    })
    napcat.socket.send(JSON.stringify(realGroupMessage('实时事件消息')))
    const event = (await eventPromise) as { message: { content: string }; raw?: unknown }

    expect(event.message.content).toBe('实时事件消息')
    expect(event).not.toHaveProperty('raw')
    napcat.socket.close()
  })

  it('tracks heartbeat quality and bot-offline notices for the connected QQ account', async () => {
    const { hub, server, port } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.name === '真实机器人')

    napcat.socket.send(
      JSON.stringify({
        self_id: Number(selfId),
        post_type: 'meta_event',
        meta_event_type: 'heartbeat',
        status: { online: false, good: true },
        interval: 30_000,
      }),
    )
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'offline')
    expect(hub.runtimeStatus()).toMatchObject({ status: 'connected', message: '0/1 个 QQ 账号在线，NapCat 连接正常' })

    napcat.socket.send(
      JSON.stringify({
        self_id: Number(selfId),
        post_type: 'meta_event',
        meta_event_type: 'heartbeat',
        status: { online: true, good: false },
        interval: 30_000,
      }),
    )
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'degraded')

    napcat.socket.send(
      JSON.stringify({
        self_id: Number(selfId),
        post_type: 'meta_event',
        meta_event_type: 'heartbeat',
        status: { online: true, good: true },
        interval: 30_000,
      }),
    )
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')

    napcat.socket.send(
      JSON.stringify({ self_id: Number(selfId), post_type: 'notice', notice_type: 'bot_offline', user_id: Number(selfId) }),
    )
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'offline')
    napcat.socket.close()
  })

  it('preserves only failed contact categories and accepts an authoritative empty refresh', async () => {
    const { hub, server, port } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().conversations.length === 2)

    napcat.state.failedActions.add('get_group_list')
    napcat.state.friends = []
    napcat.state.recent = []
    await hub.refreshAll(true)
    expect(hub.workspaceSnapshot().conversations).toEqual([
      expect.objectContaining({ type: 'group', peerId: '345678901' }),
    ])

    napcat.state.failedActions.clear()
    napcat.state.groups = []
    await hub.refreshAll(true)
    expect(hub.workspaceSnapshot().conversations).toEqual([])
    napcat.socket.close()
  })

  it('closes a reverse connection whose login self-id differs from its handshake header', async () => {
    const { hub, server, port } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port, { loginSelfId: '987654321' })
    await napcat.ready

    const closed = await napcat.closed
    expect(closed).toEqual({ code: 1008, reason: 'OneBot self ID mismatch' })
    expect(hub.workspaceSnapshot().accounts).toEqual([])
    expect(hub.runtimeStatus().status).toBe('waiting')
  })

  it('closes a reverse connection before accepting an event with another self-id', async () => {
    const { hub, server, port } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.name === '真实机器人')
    const created: unknown[] = []
    hub.on('workspace-event', (event) => {
      if ((event as { type?: string }).type === 'message.created') created.push(event)
    })

    napcat.socket.send(JSON.stringify(realGroupMessage('错误账号事件', { self_id: 987654321 })))
    const closed = await napcat.closed

    expect(closed).toEqual({ code: 1008, reason: 'OneBot event self ID mismatch' })
    expect(created).toEqual([])
    expect(hub.workspaceSnapshot().accounts).toEqual([])
  })

  it('bounds and expires registered QQ media URLs', async () => {
    const { hub, server, port } = await startTestServer({ mediaMaxEntries: 2, mediaTtlMs: 60_000 })
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.name === '真实机器人')
    const sources = ['https://gchat.qpic.cn/one', 'https://gchat.qpic.cn/two', 'https://gchat.qpic.cn/three']
    const routes: string[] = []
    hub.on('workspace-event', (event) => {
      const candidate = event as { type?: string; message?: { attachments?: Array<{ url?: string }> } }
      const route = candidate.message?.attachments?.[0]?.url
      if (candidate.type === 'message.created' && route) routes.push(route)
    })

    sources.forEach((source, index) => {
      napcat.socket.send(
        JSON.stringify(
          realGroupMessage(`图片 ${index + 1}`, {
            message_id: 301 + index,
            message_seq: 301 + index,
            message: [{ type: 'image', data: { url: source, summary: `[图片 ${index + 1}]` } }],
          }),
        ),
      )
    })
    await waitFor(async () => routes.length === 3)
    const keys = routes.map((route) => route.split('/').at(-1)!)

    expect(hub.mediaUrl(keys[0]!)).toBeUndefined()
    expect(hub.mediaUrl(keys[1]!)).toBe(sources[1])
    expect(hub.mediaUrl(keys[2]!)).toBe(sources[2])

    const now = Date.now()
    const dateSpy = vi.spyOn(Date, 'now').mockReturnValue(now + 60_001)
    try {
      expect(hub.mediaUrl(keys[1]!)).toBeUndefined()
      expect(hub.mediaUrl(keys[2]!)).toBeUndefined()
    } finally {
      dateSpy.mockRestore()
    }
    napcat.socket.close()
  })

  it('broadcasts one message when sendText and reportSelfMessage describe the same send', async () => {
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port, { reportSentEvent: true })
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().conversations.length === 2)
    const created: Array<{ type?: string; message?: { id: string } }> = []
    hub.on('workspace-event', (event) => {
      if ((event as { type?: string }).type === 'message.created') created.push(event as (typeof created)[number])
    })

    const account = `qq-${selfId}`
    const response = await fetch(`${baseUrl}/api/accounts/${account}/conversations/group/345678901/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ content: '只广播一次' }),
    })

    expect(response.status).toBe(201)
    expect(created.filter((event) => event.message?.id === `${account}:group:345678901:102`)).toHaveLength(1)
    napcat.socket.close()
  })
})
