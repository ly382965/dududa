import type { AddressInfo } from 'node:net'
import { request as httpRequest } from 'node:http'

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

async function rawHttpRequest(
  port: number,
  path: string,
  options: { method?: string; host: string; origin?: string; body?: string },
): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const request = httpRequest({
      hostname: '127.0.0.1',
      port,
      path,
      method: options.method ?? 'GET',
      headers: {
        Host: options.host,
        ...(options.origin ? { Origin: options.origin } : {}),
        ...(options.body ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(options.body) } : {}),
      },
    }, (response) => {
      const chunks: Buffer[] = []
      response.on('data', (chunk) => chunks.push(Buffer.from(chunk)))
      response.on('end', () => resolve({
        status: response.statusCode ?? 0,
        body: Buffer.concat(chunks).toString('utf8'),
      }))
    })
    request.once('error', reject)
    if (options.body) request.write(options.body)
    request.end()
  })
}

async function waitFor(predicate: () => Promise<boolean>, timeoutMs = 2_000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await predicate()) return
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
  throw new Error('condition timed out')
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => (resolve = done))
  return { promise, resolve }
}

interface FakeNapCatOptions {
  selfId?: string
  loginSelfId?: string
  reportSentEvent?: boolean
  sendMessageDelayMs?: number
  appVersion?: string
  selfRole?: string
  atAllAllowed?: boolean
  packetAvailable?: boolean
  selfMemberGroupId?: string
  groupFileCount?: number
  customFaceUrls?: string[]
}

interface FakeNapCatState {
  loginSelfId: string
  groups: unknown[]
  friends: unknown[]
  recent: unknown[]
  failedActions: Set<string>
  silentActions: Set<string>
  reportSentEvent: boolean
  categories: unknown[]
  failureMessage: string
  failureWording: string
  groupRequestChecked: boolean
  memberListGate?: Promise<void>
}

function connectFakeNapCat(port: number, options: FakeNapCatOptions = {}) {
  const connectionSelfId = options.selfId ?? selfId
  const actions: ActionRequest[] = []
  let lastSentText = ''
  let lastSentMessage: Array<{ type: string; data?: Record<string, unknown> }> = []
  const state: FakeNapCatState = {
    loginSelfId: options.loginSelfId ?? connectionSelfId,
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
    silentActions: new Set(),
    reportSentEvent: options.reportSentEvent ?? false,
    categories: [
      {
        categoryId: 1,
        categoryName: '我的好友',
        buddyList: [{ user_id: 456789012, nickname: '真实好友', remark: '好友备注' }],
      },
    ],
    failureMessage: 'fixture failure',
    failureWording: 'fixture wording',
    groupRequestChecked: false,
  }
  const socket = new WebSocket(`ws://127.0.0.1:${port}/onebot/v11/ws`, {
    headers: {
      'X-Self-ID': connectionSelfId,
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
    if (state.silentActions.has(request.action)) return
    if (state.failedActions.has(request.action)) {
      socket.send(JSON.stringify({
        status: 'failed',
        retcode: 1200,
        data: null,
        message: state.failureMessage,
        wording: state.failureWording,
        echo: request.echo,
      }))
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
        data = { app_name: 'NapCat.Onebot', protocol_version: 'v11', app_version: options.appVersion ?? '4.18.13' }
        break
      case 'nc_get_packet_status':
        if (options.packetAvailable === false) {
          socket.send(JSON.stringify({ status: 'failed', retcode: 1200, data: null, message: 'packet unavailable', echo: request.echo }))
          return
        }
        data = null
        break
      case 'get_group_list':
        data = state.groups
        break
      case 'get_friend_list':
        data = state.friends
        break
      case 'get_friends_with_category':
        data = state.categories
        break
      case 'get_recent_contact':
        data = state.recent
        break
      case 'fetch_custom_face':
        data = options.customFaceUrls ?? ['https://gchat.qpic.cn/gchatpic_new/0/0-0-FAVORITE/0']
        break
      case 'get_group_msg_history':
        data = { messages: [realGroupMessage('来自真实 NapCat 的消息', { self_id: Number(connectionSelfId) })] }
        break
      case 'get_group_member_list':
        data = [
          {
            group_id: options.selfMemberGroupId ?? String(request.params.group_id ?? 345678901),
            user_id: Number(connectionSelfId),
            nickname: '真实机器人',
            card: '机器人群名片',
            role: options.selfRole ?? 'owner',
            level: '12',
            join_time: 1_700_000_000,
            last_sent_time: 1_785_742_400,
          },
          {
            group_id: String(request.params.group_id ?? 345678901),
            user_id: 234567890,
            nickname: '群成员',
            card: '测试成员',
            role: 'member',
            level: '8',
            join_time: 1_710_000_000,
            last_sent_time: 1_785_742_300,
          },
        ]
        break
      case 'get_group_at_all_remain':
        data = {
          can_at_all: options.atAllAllowed ?? true,
          remain_at_all_count_for_group: options.atAllAllowed === false ? 0 : 1,
          remain_at_all_count_for_self: options.atAllAllowed === false ? 0 : 1,
        }
        break
      case 'get_group_system_msg':
        data = {
          invited_requests: [],
          join_requests: [
            {
              request_id: 9001,
              invitor_uin: 567890123,
              invitor_nick: '真实申请者',
              actor: 0,
              group_id: 345678901,
              group_name: '真实测试群',
              message: '申请理由',
              checked: state.groupRequestChecked,
            },
          ],
        }
        break
      case 'get_essence_msg_list':
        data = [
          {
            msg_seq: 101,
            sender_id: 234567890,
            sender_nick: '测试成员',
            operator_id: Number(connectionSelfId),
            operator_nick: '真实机器人',
            message_id: 101,
            operator_time: 1_785_742_400,
            content: [{ type: 'text', data: { text: '真实精华消息' } }],
          },
        ]
        break
      case '_get_group_notice':
        data = [
          {
            notice_id: 'notice-real-1',
            sender_id: Number(connectionSelfId),
            publish_time: 1_785_742_400,
            message: { text: '真实群公告', images: [] },
            read_num: 12,
          },
        ]
        break
      case 'get_group_root_files':
        data = {
          files: options.groupFileCount === undefined
            ? [
                {
                  file_id: '/real-file-id',
                  file_name: '真实文件.txt',
                  file_size: 1024,
                  download_times: 0,
                  uploader: Number(connectionSelfId),
                },
              ]
            : Array.from({ length: options.groupFileCount }, (_, index) => ({
                file_id: `/real-file-${index}`,
                file_name: `真实文件-${index}.txt`,
                file_size: index + 1,
                download_times: 0,
                uploader: Number(connectionSelfId),
              })),
          folders: options.groupFileCount === undefined
            ? [{ folder_id: '/real-folder-id', folder_name: '真实文件夹', total_file_count: 1 }]
            : [],
        }
        break
      case 'get_group_files_by_folder':
        data = { files: [], folders: [] }
        break
      case 'get_friend_msg_history':
        data = {
          messages: [
            {
              self_id: Number(connectionSelfId),
              time: 1_785_742_400,
              message_id: 201,
              message_seq: 201,
              user_id: 456789012,
              message_type: 'private',
              post_type: 'message_sent',
              sender: { user_id: Number(connectionSelfId), nickname: '真实机器人' },
              message: [{ type: 'text', data: { text: '本账号发出的私聊历史' } }],
              raw_message: '本账号发出的私聊历史',
            },
          ],
        }
        break
      case 'send_group_msg':
        lastSentMessage = request.params.message as Array<{ type: string; data?: Record<string, unknown> }>
        lastSentText = lastSentMessage
          .filter((segment) => segment.type === 'text')
          .map((segment) => String(segment.data?.text ?? ''))
          .join('')
        data = { message_id: 102 }
        if (state.reportSentEvent) {
          socket.send(
            JSON.stringify(
              realGroupMessage(lastSentText, {
                self_id: Number(connectionSelfId),
                post_type: 'message_sent',
                message_id: 102,
                message_seq: 102,
                user_id: Number(connectionSelfId),
                sender: { user_id: Number(connectionSelfId), nickname: '真实机器人' },
                message: lastSentMessage,
              }),
            ),
          )
        }
        break
      case 'upload_group_file':
      case 'upload_private_file':
        data = { file_id: 'uploaded-file-1' }
        break
      case 'get_group_file_url':
      case 'get_private_file_url':
        data = { url: 'https://gchat.qpic.cn/download/real-file' }
        break
      case 'delete_msg':
      case 'group_poke':
      case 'friend_poke':
      case 'set_friend_add_request':
      case 'set_group_add_request':
      case 'set_group_admin':
      case 'set_group_kick':
      case 'set_group_card':
      case 'set_group_name':
      case 'set_group_whole_ban':
      case 'set_group_leave':
      case '_del_group_notice':
      case 'move_group_file':
      case 'rename_group_file':
      case 'delete_group_file':
      case 'create_group_file_folder':
      case 'delete_group_folder':
        data = null
        break
      case 'forward_group_single_msg':
      case 'forward_friend_single_msg':
        data = null
        break
      case 'get_forward_msg':
        data = {
          messages: [
            {
              type: 'node',
              data: {
                time: 1_785_742_400,
                user_id: 234567890,
                nickname: '转发成员',
                message: [
                  { type: 'text', data: { text: '转发中的真实消息' } },
                  {
                    type: 'node',
                    data: {
                      message: [
                        {
                          type: 'node',
                          data: {
                            user_id: 345678901,
                            nickname: '内层成员',
                            message: [{ type: 'text', data: { text: '内层真实消息' } }],
                          },
                        },
                      ],
                    },
                  },
                ],
              },
            },
          ],
        }
        break
      case 'get_msg':
        if (String(request.params.message_id) === '101') {
          data = realGroupMessage('来自真实 NapCat 的消息', { self_id: Number(connectionSelfId) })
        } else if (String(request.params.message_id) === '201') {
          data = {
            self_id: Number(connectionSelfId),
            time: 1_785_742_400,
            message_id: 201,
            message_seq: 201,
            user_id: Number(connectionSelfId),
            message_type: 'private',
            post_type: 'message_sent',
            sender: { user_id: Number(connectionSelfId), nickname: '真实机器人' },
            message: [{ type: 'text', data: { text: '本账号发出的私聊历史' } }],
          }
        } else {
          data = {
            ...realGroupMessage(lastSentText),
            self_id: Number(connectionSelfId),
            message_id: Number(request.params.message_id),
            message_seq: Number(request.params.message_id),
            user_id: Number(connectionSelfId),
            sender: { user_id: Number(connectionSelfId), nickname: '真实机器人' },
            message: lastSentMessage,
          }
        }
        break
      case 'mark_group_msg_as_read':
        data = null
        break
      default:
        socket.send(JSON.stringify({ status: 'failed', retcode: 1404, data: null, message: 'unsupported', echo: request.echo }))
        return
    }
    const response = JSON.stringify({ status: 'ok', retcode: 0, data, message: '', echo: request.echo })
    if (state.memberListGate && request.action === 'get_group_member_list') {
      const gate = state.memberListGate
      void gate.then(() => {
        if (socket.readyState === WebSocket.OPEN) socket.send(response)
      })
    } else if (options.sendMessageDelayMs && ['send_group_msg', 'send_private_msg'].includes(request.action)) {
      setTimeout(() => socket.send(response), options.sendMessageDelayMs)
    } else {
      socket.send(response)
    }
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

  it('rejects DNS-rebinding hosts and browser writes without a same-origin header', async () => {
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const rebound = await rawHttpRequest(port, '/api/workspace', {
      host: 'attacker.example',
      origin: 'http://attacker.example',
    })
    expect(rebound.status).toBe(421)

    const account = `qq-${selfId}`
    const noOrigin = await fetch(
      `${baseUrl}/api/accounts/${account}/conversations/group/345678901/messages`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: '不应发送' }),
      },
    )
    expect(noOrigin.status).toBe(403)

    const napcat = connectFakeNapCat(port)
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const hostileOrigin = await rawHttpRequest(
      port,
      `/api/accounts/${account}/conversations/group/345678901/messages`,
      {
        method: 'POST',
        host: `127.0.0.1:${port}`,
        origin: 'http://attacker.example',
        body: JSON.stringify({ content: '不应发送的跨站消息' }),
      },
    )
    expect(hostileOrigin.status).toBe(403)
    expect(napcat.actions.some((item) => item.action === 'send_group_msg')).toBe(false)
    napcat.socket.close()
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

  it('publishes explicit capabilities, signed history cursors, and typed rich sends', async () => {
    const { server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await napcat.ready
    const account = `qq-${selfId}`
    await waitFor(async () => {
      const response = await fetch(`${baseUrl}/api/accounts/${account}/capabilities`)
      if (!response.ok) return false
      const body = (await response.json()) as { actions?: Record<string, { status?: string }> }
      return body.actions?.['history.cursor']?.status === 'supported'
    })

    const capabilities = (await (
      await fetch(`${baseUrl}/api/accounts/${account}/capabilities`)
    ).json()) as {
      implementation: { name: string; version: string }
      actions: Record<string, { status: string; reason?: string }>
    }
    expect(capabilities.implementation).toEqual({
      name: 'NapCat.Onebot',
      version: '4.18.13',
      protocol: 'onebot-v11',
    })
    expect(capabilities.actions['history.cursor']).toEqual({ status: 'supported' })
    expect(capabilities.actions['directory.peer_pin']).toMatchObject({
      status: 'unsupported',
      reason: expect.stringContaining('NapCat'),
    })
    expect(capabilities.actions['message.send.image']).toEqual({ status: 'supported' })
    expect(capabilities.actions['message.custom_faces']).toEqual({ status: 'supported' })

    const messageUrl = `${baseUrl}/api/accounts/${account}/conversations/group/345678901/messages`
    const first = (await (await fetch(`${messageUrl}?limit=1`)).json()) as {
      messages: Array<{ messageSeq: string; segments: unknown[] }>
      beforeCursor: string
      afterCursor: string
      hasMoreBefore: boolean
      hasMoreAfter: boolean
    }
    expect(first.messages[0]).toMatchObject({ messageSeq: '101', segments: [{ type: 'text' }] })
    expect(first.beforeCursor).toBeTruthy()
    expect(first.afterCursor).toBeTruthy()
    expect(first.hasMoreBefore).toBe(true)
    expect(first.hasMoreAfter).toBe(false)

    const older = await fetch(`${messageUrl}?limit=1&before=${encodeURIComponent(first.beforeCursor)}`)
    expect(older.status).toBe(200)
    expect(napcat.actions.filter((action) => action.action === 'get_group_msg_history').at(-1)?.params).toMatchObject({
      group_id: '345678901',
      count: 2,
      message_seq: '101',
      reverse_order: false,
    })

    const sent = await fetch(messageUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({
        segments: [
          { type: 'reply', messageId: '91' },
          { type: 'text', text: '真实富消息' },
          { type: 'mention', userId: '234567890', label: '成员', all: false },
          { type: 'face', faceId: '14', name: '微笑', market: false },
        ],
      }),
    })
    expect(sent.status).toBe(201)
    const action = napcat.actions.filter((item) => item.action === 'send_group_msg').at(-1)
    expect(action?.params.message).toEqual([
      { type: 'reply', data: { id: '91' } },
      { type: 'text', data: { text: '真实富消息' } },
      { type: 'at', data: { qq: '234567890' } },
      { type: 'face', data: { id: '14' } },
    ])

    const rejected = await fetch(messageUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ segments: [{ type: 'image', file: '/tmp/private.png' }] }),
    })
    expect(rejected.status).toBe(400)
    expect(napcat.actions.filter((item) => item.action === 'send_group_msg')).toHaveLength(1)

    const malformed = await fetch(messageUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: '{',
    })
    expect(malformed.status).toBe(400)
    expect(napcat.actions.filter((item) => item.action === 'send_group_msg')).toHaveLength(1)
    napcat.socket.close()
  })

  it('uses account-bound expiring handles for NapCat custom faces without exposing remote URLs', async () => {
    const secondSelfId = '987654321'
    const remoteFaceUrl = 'https://gchat.qpic.cn/gchatpic_new/0/0-0-FAVORITE/0'
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const firstNapcat = connectFakeNapCat(port, {
      customFaceUrls: [remoteFaceUrl, remoteFaceUrl, 'https://attacker.example/not-a-qq-face'],
    })
    const secondNapcat = connectFakeNapCat(port, { selfId: secondSelfId })
    await Promise.all([firstNapcat.ready, secondNapcat.ready])
    const firstAccount = `qq-${selfId}`
    const secondAccount = `qq-${secondSelfId}`
    await waitFor(() => Promise.resolve(hub.workspaceSnapshot().accounts.length === 2))

    const catalogResponse = await fetch(
      `${baseUrl}/api/accounts/${firstAccount}/conversations/group/345678901/custom-faces`,
    )
    expect(catalogResponse.status).toBe(200)
    const catalog = (await catalogResponse.json()) as {
      accountId: string
      conversationId: string
      items: Array<{ handle: string; previewUrl: string; expiresAt: number }>
    }
    expect(catalog).toMatchObject({
      accountId: firstAccount,
      conversationId: `${firstAccount}:group:345678901`,
    })
    expect(catalog.items).toHaveLength(1)
    expect(catalog.items[0]).toMatchObject({
      handle: expect.stringMatching(/^[a-f0-9]{32}$/),
      previewUrl: expect.stringMatching(/^\/api\/accounts\/qq-\d+\/conversations\/group\/345678901\/custom-faces\/[a-f0-9]{32}\/preview$/),
      expiresAt: expect.any(Number),
    })
    expect(JSON.stringify(catalog)).not.toContain(remoteFaceUrl)
    expect(JSON.stringify(catalog)).not.toContain('attacker.example')
    expect(firstNapcat.actions.filter((item) => item.action === 'fetch_custom_face').at(-1)?.params).toEqual({ count: 48 })

    const handle = catalog.items[0]!.handle
    const secondCatalog = (await (
      await fetch(`${baseUrl}/api/accounts/${secondAccount}/conversations/group/345678901/custom-faces`)
    ).json()) as { items: Array<{ handle: string }> }
    expect(secondCatalog.items[0]!.handle).not.toBe(handle)
    const crossAccountPreview = catalog.items[0]!.previewUrl.replace(`/accounts/${firstAccount}/`, `/accounts/${secondAccount}/`)
    expect((await fetch(`${baseUrl}${crossAccountPreview}`)).status).toBe(404)
    const crossConversationPreview = catalog.items[0]!.previewUrl.replace(
      '/conversations/group/345678901/',
      '/conversations/private/456789012/',
    )
    expect((await fetch(`${baseUrl}${crossConversationPreview}`)).status).toBe(404)

    const firstMessages = `${baseUrl}/api/accounts/${firstAccount}/conversations/group/345678901/messages`
    const secondMessages = `${baseUrl}/api/accounts/${secondAccount}/conversations/group/345678901/messages`
    const withoutOrigin = await fetch(firstMessages, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ segments: [{ type: 'custom_face', handle }] }),
    })
    expect(withoutOrigin.status).toBe(403)

    const crossAccountSend = await fetch(secondMessages, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ segments: [{ type: 'custom_face', handle }] }),
    })
    expect(crossAccountSend.status).toBe(400)
    expect(secondNapcat.actions.some((item) => item.action === 'send_group_msg')).toBe(false)
    const crossConversationSend = await fetch(
      `${baseUrl}/api/accounts/${firstAccount}/conversations/private/456789012/messages`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Origin: baseUrl },
        body: JSON.stringify({ segments: [{ type: 'custom_face', handle }] }),
      },
    )
    expect(crossConversationSend.status).toBe(400)
    expect(firstNapcat.actions.some((item) => item.action === 'send_private_msg')).toBe(false)

    const arbitraryUrl = await fetch(firstMessages, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ segments: [{ type: 'custom_face', handle, url: 'https://gchat.qpic.cn/other' }] }),
    })
    expect(arbitraryUrl.status).toBe(400)
    const unknownHandle = await fetch(firstMessages, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ segments: [{ type: 'custom_face', handle: '0'.repeat(32) }] }),
    })
    expect(unknownHandle.status).toBe(400)

    const sent = await fetch(firstMessages, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ segments: [{ type: 'custom_face', handle }] }),
    })
    expect(sent.status).toBe(201)
    expect(firstNapcat.actions.filter((item) => item.action === 'send_group_msg').at(-1)?.params.message).toEqual([
      { type: 'image', data: { file: remoteFaceUrl, sub_type: 1, summary: '[表情]' } },
    ])
    const sentBody = (await sent.json()) as { message: { content: string; segments: Array<Record<string, unknown>> } }
    expect(sentBody.message).toMatchObject({ content: '[表情]', segments: [{ type: 'image', sticker: true }] })
    firstNapcat.socket.close()
    secondNapcat.socket.close()
  })

  it('rejects a custom-face handle after its server-side TTL expires', async () => {
    const { hub, server, port, baseUrl } = await startTestServer({ customFaceTtlMs: 5 })
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await napcat.ready
    await waitFor(() => Promise.resolve(hub.workspaceSnapshot().accounts[0]?.status === 'online'))
    const account = `qq-${selfId}`
    const catalog = (await (
      await fetch(`${baseUrl}/api/accounts/${account}/conversations/group/345678901/custom-faces`)
    ).json()) as { items: Array<{ handle: string }> }
    await new Promise((resolve) => setTimeout(resolve, 15))

    const sent = await fetch(`${baseUrl}/api/accounts/${account}/conversations/group/345678901/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ segments: [{ type: 'custom_face', handle: catalog.items[0]!.handle }] }),
    })
    expect(sent.status).toBe(400)
    expect(napcat.actions.some((item) => item.action === 'send_group_msg')).toBe(false)
    napcat.socket.close()
  })

  it('disables version-gated actions for an older NapCat implementation', async () => {
    const { server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port, { appVersion: '4.7.0' })
    await napcat.ready
    const account = `qq-${selfId}`
    await waitFor(async () => {
      const response = await fetch(`${baseUrl}/api/accounts/${account}/capabilities`)
      if (!response.ok) return false
      const body = (await response.json()) as { implementation?: { version?: string } }
      return body.implementation?.version === '4.7.0'
    })
    const capabilities = (await (
      await fetch(`${baseUrl}/api/accounts/${account}/capabilities`)
    ).json()) as { actions: Record<string, { status: string; reason?: string }> }
    expect(capabilities.actions['message.forward']).toMatchObject({
      status: 'unsupported',
      reason: expect.stringContaining('4.8.0'),
    })
    expect(capabilities.actions['message.download.file']).toMatchObject({ status: 'unsupported' })
    expect(capabilities.actions['message.custom_faces']).toMatchObject({ status: 'unsupported' })
    expect(capabilities.actions['message.send.text']).toEqual({ status: 'supported' })
    napcat.socket.close()
  })

  it('isolates signed cursors, actions, and live events across concurrent accounts', async () => {
    const secondSelfId = '987654321'
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const firstNapcat = connectFakeNapCat(port)
    const secondNapcat = connectFakeNapCat(port, { selfId: secondSelfId })
    await Promise.all([firstNapcat.ready, secondNapcat.ready])
    const firstAccount = `qq-${selfId}`
    const secondAccount = `qq-${secondSelfId}`
    await waitFor(
      async () =>
        hub.workspaceSnapshot().conversations.filter((item) => item.peerId === '345678901').length === 2,
    )
    const snapshot = hub.workspaceSnapshot()
    expect(snapshot.conversations.filter((item) => item.peerId === '345678901').map((item) => item.accountId).sort()).toEqual([
      firstAccount,
      secondAccount,
    ])

    const firstUrl = `${baseUrl}/api/accounts/${firstAccount}/conversations/group/345678901/messages`
    const secondUrl = `${baseUrl}/api/accounts/${secondAccount}/conversations/group/345678901/messages`
    const firstPage = (await (await fetch(`${firstUrl}?limit=1`)).json()) as { beforeCursor: string }
    const secondHistoryBefore = secondNapcat.actions.filter((item) => item.action === 'get_group_msg_history').length
    const crossAccount = await fetch(`${secondUrl}?limit=1&before=${encodeURIComponent(firstPage.beforeCursor)}`)
    expect(crossAccount.status).toBe(400)
    expect(secondNapcat.actions.filter((item) => item.action === 'get_group_msg_history')).toHaveLength(
      secondHistoryBefore,
    )

    const sent = await fetch(secondUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ content: '只由二号账号发送' }),
    })
    expect(sent.status).toBe(201)
    expect(secondNapcat.actions.some((item) => item.action === 'send_group_msg')).toBe(true)
    expect(firstNapcat.actions.some((item) => item.action === 'send_group_msg')).toBe(false)

    const firstUploadForm = new FormData()
    firstUploadForm.append('file', new Blob([Buffer.from('account-one-image')], { type: 'image/png' }), '一号图片.png')
    const firstUpload = (await (
      await fetch(`${firstUrl.replace(/\/messages$/, '')}/uploads?purpose=media`, {
        method: 'POST',
        headers: { Origin: baseUrl },
        body: firstUploadForm,
      })
    ).json()) as { uploadId: string }
    const secondActionCount = secondNapcat.actions.filter((item) => item.action === 'send_group_msg').length
    const crossUpload = await fetch(secondUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ segments: [{ type: 'image', uploadId: firstUpload.uploadId }] }),
    })
    expect(crossUpload.status).toBe(400)
    expect(secondNapcat.actions.filter((item) => item.action === 'send_group_msg')).toHaveLength(secondActionCount)

    const eventPromise = new Promise<{ conversation: { accountId: string }; message: { accountId: string } }>((resolve) => {
      const listener = (event: unknown) => {
        if ((event as { type?: string }).type !== 'message.created') return
        const created = event as { conversation: { accountId: string }; message: { accountId: string } }
        if (created.message.accountId !== secondAccount) return
        hub.off('workspace-event', listener)
        resolve(created)
      }
      hub.on('workspace-event', listener)
    })
    secondNapcat.socket.send(
      JSON.stringify(
        realGroupMessage('二号实时事件', {
          self_id: Number(secondSelfId),
          message_id: 302,
          message_seq: 302,
        }),
      ),
    )
    await expect(eventPromise).resolves.toMatchObject({
      conversation: { accountId: secondAccount },
      message: { accountId: secondAccount },
    })

    firstNapcat.socket.close()
    secondNapcat.socket.close()
  })

  it('stages browser media and executes file, recall, forward, nudge, and forwarded-message actions', async () => {
    const { server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port, { sendMessageDelayMs: 30 })
    await napcat.ready
    const account = `qq-${selfId}`
    await waitFor(async () => {
      const workspace = (await (await fetch(`${baseUrl}/api/workspace`)).json()) as { conversations: unknown[] }
      return workspace.conversations.length === 2
    })
    const groupBase = `${baseUrl}/api/accounts/${account}/conversations/group/345678901`

    const invalidPurpose = await fetch(`${groupBase}/uploads?purpose=other`, {
      method: 'POST',
      headers: { Origin: baseUrl },
    })
    expect(invalidPurpose.status).toBe(400)

    const mediaForm = new FormData()
    mediaForm.append('file', new Blob([Buffer.from('real-image-bytes')], { type: 'image/png' }), '真实图片.png')
    const stagedResponse = await fetch(`${groupBase}/uploads?purpose=media`, {
      method: 'POST',
      headers: { Origin: baseUrl },
      body: mediaForm,
    })
    expect(stagedResponse.status).toBe(201)
    const staged = (await stagedResponse.json()) as { uploadId: string; kind: string; name: string }
    expect(staged).toMatchObject({ kind: 'image', name: '真实图片.png' })

    const mediaSend = await fetch(`${groupBase}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ segments: [{ type: 'image', uploadId: staged.uploadId, name: staged.name }] }),
    })
    expect(mediaSend.status).toBe(201)
    const sentAction = napcat.actions.filter((item) => item.action === 'send_group_msg').at(-1)!
    expect(sentAction.params.message).toEqual([
      {
        type: 'image',
        data: { file: `base64://${Buffer.from('real-image-bytes').toString('base64')}`, summary: '真实图片.png' },
      },
    ])

    const replay = await fetch(`${groupBase}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ segments: [{ type: 'image', uploadId: staged.uploadId, name: staged.name }] }),
    })
    expect(replay.status).toBe(400)

    const concurrentForm = new FormData()
    concurrentForm.append('file', new Blob([Buffer.from('concurrent-image')], { type: 'image/png' }), '并发图片.png')
    const concurrentStaged = (await (
      await fetch(`${groupBase}/uploads?purpose=media`, {
        method: 'POST',
        headers: { Origin: baseUrl },
        body: concurrentForm,
      })
    ).json()) as { uploadId: string }
    const concurrentBody = JSON.stringify({
      segments: [{ type: 'image', uploadId: concurrentStaged.uploadId, name: '并发图片.png' }],
    })
    const concurrentResponses = await Promise.all([
      fetch(`${groupBase}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Origin: baseUrl },
        body: concurrentBody,
      }),
      fetch(`${groupBase}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Origin: baseUrl },
        body: concurrentBody,
      }),
    ])
    expect(concurrentResponses.map((response) => response.status).sort()).toEqual([201, 400])

    const fileForm = new FormData()
    fileForm.append('file', new Blob([Buffer.from('real-file')], { type: 'text/plain' }), '../报告.txt')
    const fileResponse = await fetch(`${groupBase}/uploads?purpose=file`, {
      method: 'POST',
      headers: { Origin: baseUrl },
      body: fileForm,
    })
    expect(fileResponse.status).toBe(201)
    expect(await fileResponse.json()).toMatchObject({ kind: 'file', fileId: 'uploaded-file-1', name: '报告.txt' })
    expect(napcat.actions.filter((item) => item.action === 'upload_group_file').at(-1)?.params).toMatchObject({
      group_id: '345678901',
      name: '报告.txt',
      file: `base64://${Buffer.from('real-file').toString('base64')}`,
    })

    const fileUrlResponse = await fetch(`${groupBase}/files/real-file-token/url?name=${encodeURIComponent('报告.pdf')}`)
    expect(fileUrlResponse.status).toBe(200)
    const fileUrl = (await fileUrlResponse.json()) as { url: string }
    expect(fileUrl).toMatchObject({ url: expect.stringMatching(/^\/api\/media\/file\//) })
    expect(napcat.actions.filter((item) => item.action === 'get_group_file_url').at(-1)?.params).toEqual({
      group_id: '345678901',
      file_id: 'real-file-token',
    })

    const realFetch = globalThis.fetch
    const fileFetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((async (input, init) => {
      if (String(input) === 'https://gchat.qpic.cn/download/real-file') {
        return new Response(Buffer.from('%PDF-real-file'), {
          status: 200,
          headers: { 'Content-Type': 'application/pdf', 'Content-Length': '14' },
        })
      }
      return realFetch(input, init)
    }) as typeof fetch)
    try {
      const downloaded = await realFetch(`${baseUrl}${fileUrl.url}`)
      expect(downloaded.status).toBe(200)
      expect(downloaded.headers.get('content-type')).toBe('application/pdf')
      expect(downloaded.headers.get('content-disposition')).toContain("filename*=UTF-8''%E6%8A%A5%E5%91%8A.pdf")
      expect(Buffer.from(await downloaded.arrayBuffer()).toString()).toBe('%PDF-real-file')
    } finally {
      fileFetchSpy.mockRestore()
    }

    const refreshedMessage = await fetch(`${groupBase}/messages/101`)
    expect(refreshedMessage.status).toBe(200)
    expect(await refreshedMessage.json()).toMatchObject({ message: { messageId: '101', conversationId: `${account}:group:345678901` } })

    const receivedRecall = await fetch(`${groupBase}/messages/101`, { method: 'DELETE', headers: { Origin: baseUrl } })
    expect(receivedRecall.status).toBe(400)
    expect(napcat.actions.some((item) => item.action === 'delete_msg')).toBe(false)

    const recalled = await fetch(`${groupBase}/messages/102`, { method: 'DELETE', headers: { Origin: baseUrl } })
    expect(recalled.status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === 'delete_msg').at(-1)?.params).toEqual({ message_id: '102' })

    const nudged = await fetch(`${groupBase}/nudge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ userId: '234567890' }),
    })
    expect(nudged.status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === 'group_poke').at(-1)?.params).toEqual({
      group_id: '345678901',
      user_id: '234567890',
    })

    const privateBase = `${baseUrl}/api/accounts/${account}/conversations/private/456789012`
    const wrongPrivateNudge = await fetch(`${privateBase}/nudge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ userId: '234567890' }),
    })
    expect(wrongPrivateNudge.status).toBe(400)
    expect(napcat.actions.some((item) => item.action === 'friend_poke')).toBe(false)
    const privateNudge = await fetch(`${privateBase}/nudge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ userId: '456789012' }),
    })
    expect(privateNudge.status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === 'friend_poke').at(-1)?.params).toEqual({
      user_id: '456789012',
    })

    const wrongSourceForward = await fetch(`${groupBase}/messages/201/forward`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ target: { accountId: account, type: 'private', peerId: '456789012' } }),
    })
    expect(wrongSourceForward.status).toBe(400)
    expect(napcat.actions.some((item) => item.action === 'forward_group_single_msg')).toBe(false)

    const forwarded = await fetch(`${groupBase}/messages/101/forward`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ target: { accountId: account, type: 'private', peerId: '456789012' } }),
    })
    expect(forwarded.status).toBe(201)
    expect(napcat.actions.filter((item) => item.action === 'forward_group_single_msg').at(-1)?.params).toEqual({
      user_id: '456789012',
      message_id: '101',
    })

    const bundle = await fetch(`${groupBase}/forwards/forward-1`)
    expect(bundle.status).toBe(200)
    expect(await bundle.json()).toMatchObject({
      forwardId: 'forward-1',
      messages: [
        {
          senderName: '转发成员',
          content: '转发中的真实消息[转发消息]',
          segments: [
            { type: 'text', text: '转发中的真实消息' },
            {
              type: 'forward',
              count: 1,
              messages: [{ senderName: '内层成员', content: '内层真实消息' }],
            },
          ],
        },
      ],
    })
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

  it('proxies valid media ranges and preserves an upstream 416 response', async () => {
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.name === '真实机器人')
    let route = ''
    hub.on('workspace-event', (event) => {
      const candidate = event as { type?: string; message?: { attachments?: Array<{ url?: string }> } }
      if (candidate.type === 'message.created') route = candidate.message?.attachments?.[0]?.url ?? ''
    })
    napcat.socket.send(
      JSON.stringify(
        realGroupMessage('Range 媒体', {
          message_id: 390,
          message_seq: 390,
          message: [{ type: 'video', data: { url: 'https://gchat.qpic.cn/range-video.mp4' } }],
        }),
      ),
    )
    await waitFor(async () => Boolean(route))

    const realFetch = globalThis.fetch
    const remoteRanges: string[] = []
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((async (input, init) => {
      if (String(input).startsWith('https://gchat.qpic.cn/')) {
        const range = new Headers(init?.headers).get('range') ?? ''
        remoteRanges.push(range)
        if (range === 'bytes=99-100') {
          return new Response(null, {
            status: 416,
            headers: { 'Content-Range': 'bytes */10', 'Accept-Ranges': 'bytes' },
          })
        }
        return new Response(Buffer.from('bcd'), {
          status: 206,
          headers: {
            'Content-Type': 'video/mp4',
            'Content-Length': '3',
            'Content-Range': 'bytes 1-3/10',
            'Accept-Ranges': 'bytes',
          },
        })
      }
      return realFetch(input, init)
    }) as typeof fetch)
    try {
      const partial = await realFetch(`${baseUrl}${route}`, { headers: { Range: 'bytes=1-3' } })
      expect(partial.status).toBe(206)
      expect(partial.headers.get('content-range')).toBe('bytes 1-3/10')
      expect(Buffer.from(await partial.arrayBuffer()).toString()).toBe('bcd')

      const unsatisfied = await realFetch(`${baseUrl}${route}`, { headers: { Range: 'bytes=99-100' } })
      expect(unsatisfied.status).toBe(416)
      expect(unsatisfied.headers.get('content-range')).toBe('bytes */10')
      expect(remoteRanges).toEqual(['bytes=1-3', 'bytes=99-100'])

      const malformed = await realFetch(`${baseUrl}${route}`, { headers: { Range: 'bytes=1-2,4-5' } })
      expect(malformed.status).toBe(400)
      expect(remoteRanges).toEqual(['bytes=1-3', 'bytes=99-100'])
    } finally {
      fetchSpy.mockRestore()
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

  it('serves real account-scoped contacts, group requests, and authoritative member permissions', async () => {
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const account = `qq-${selfId}`

    const directory = (await (
      await fetch(`${baseUrl}/api/accounts/${account}/directory?refresh=1`)
    ).json()) as {
      accountId: string
      friends: Array<{ userId: string; categoryName?: string }>
      groups: Array<{ groupId: string }>
    }
    expect(directory).toMatchObject({ accountId: account })
    expect(directory.friends).toContainEqual(expect.objectContaining({ userId: '456789012', categoryName: '我的好友' }))
    expect(directory.groups).toContainEqual(expect.objectContaining({ groupId: '345678901' }))

    const members = (await (
      await fetch(`${baseUrl}/api/accounts/${account}/groups/345678901/members?refresh=1`)
    ).json()) as {
      selfUserId: string
      selfRole: string
      members: Array<{ userId: string; role: string }>
      permissions: Record<string, { allowed: boolean }>
    }
    expect(members).toMatchObject({ selfUserId: selfId, selfRole: 'owner' })
    expect(members.members).toContainEqual(expect.objectContaining({ userId: '234567890', role: 'member' }))
    expect(members.permissions.mentionAll).toEqual({ allowed: true })
    expect(napcat.actions.some((item) => item.action === 'get_group_at_all_remain')).toBe(true)

    const capabilities = (await (
      await fetch(`${baseUrl}/api/accounts/${account}/capabilities`)
    ).json()) as { actions: Record<string, { status: string }> }
    expect(capabilities.actions['request.friend.history']?.status).toBe('unsupported')
    expect(capabilities.actions['request.friend.resolve']).toEqual({ status: 'supported' })
    expect(capabilities.actions['request.group.resolve']).toEqual({ status: 'supported' })

    const inbox = (await (
      await fetch(`${baseUrl}/api/accounts/${account}/notifications?refresh=1`)
    ).json()) as { items: Array<{ id: string; kind: string; userId: string; state: string }> }
    const request = inbox.items.find((item) => item.kind === 'group-request')!
    expect(request).toMatchObject({ userId: '567890123', state: 'pending' })
    expect(JSON.stringify(request)).not.toContain('9001')

    const resolved = await fetch(
      `${baseUrl}/api/accounts/${account}/notifications/${encodeURIComponent(request.id)}/resolve`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Origin: baseUrl },
        body: JSON.stringify({ action: 'reject' }),
      },
    )
    expect(resolved.status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === 'set_group_add_request').at(-1)?.params).toEqual({
      flag: '9001',
      approve: false,
      reason: '',
    })
    const afterRefresh = (await (
      await fetch(`${baseUrl}/api/accounts/${account}/notifications?refresh=1`)
    ).json()) as { items: Array<{ id: string; state: string; actionable: boolean }> }
    expect(afterRefresh.items.find((item) => item.id === request.id)).toMatchObject({
      state: 'rejected',
      actionable: false,
    })
    napcat.socket.close()
  })

  it('refuses group-request resolution when the connected QQ is only a group member', async () => {
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port, { selfRole: 'member' })
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const account = `qq-${selfId}`
    const inbox = (await (
      await fetch(`${baseUrl}/api/accounts/${account}/notifications?refresh=1`)
    ).json()) as {
      items: Array<{ id: string; kind: string; actionable: boolean; actionReason?: string }>
    }
    const request = inbox.items.find((item) => item.kind === 'group-request')!
    expect(request).toMatchObject({
      actionable: false,
      actionReason: expect.stringContaining('群主或管理员'),
    })

    const denied = await fetch(
      `${baseUrl}/api/accounts/${account}/notifications/${encodeURIComponent(request.id)}/resolve`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Origin: baseUrl },
        body: JSON.stringify({ action: 'accept' }),
      },
    )
    expect(denied.status).toBe(403)
    expect(napcat.actions.some((item) => item.action === 'set_group_add_request')).toBe(false)
    napcat.socket.close()
  })

  it('does not resolve a group request that a concurrent refresh already marked handled', async () => {
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const account = `qq-${selfId}`
    const notificationUrl = `${baseUrl}/api/accounts/${account}/notifications`
    const inbox = (await (await fetch(`${notificationUrl}?refresh=1`)).json()) as {
      items: Array<{ id: string; kind: string }>
    }
    const request = inbox.items.find((item) => item.kind === 'group-request')!
    const memberGate = deferred<void>()
    napcat.state.memberListGate = memberGate.promise
    const memberLookups = napcat.actions.filter((item) => item.action === 'get_group_member_list').length
    const resolving = fetch(`${notificationUrl}/${encodeURIComponent(request.id)}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ action: 'accept' }),
    })
    await waitFor(async () =>
      napcat.actions.filter((item) => item.action === 'get_group_member_list').length > memberLookups,
    )

    napcat.state.groupRequestChecked = true
    const refreshed = await fetch(`${notificationUrl}?refresh=1`)
    expect(refreshed.status).toBe(200)
    expect((await refreshed.json()) as { items: Array<{ state: string }> }).toMatchObject({
      items: expect.arrayContaining([expect.objectContaining({ state: 'handled' })]),
    })
    napcat.state.memberListGate = undefined
    memberGate.resolve()
    expect((await resolving).status).toBe(409)
    expect(napcat.actions.some((item) => item.action === 'set_group_add_request')).toBe(false)
    napcat.socket.close()
  })

  it('keeps a request retryable when role preflight is interrupted before the mutation starts', async () => {
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const account = `qq-${selfId}`
    const notificationUrl = `${baseUrl}/api/accounts/${account}/notifications`
    const inbox = (await (await fetch(`${notificationUrl}?refresh=1`)).json()) as {
      items: Array<{ id: string; kind: string }>
    }
    const request = inbox.items.find((item) => item.kind === 'group-request')!
    napcat.state.silentActions.add('get_group_member_list')
    const memberLookups = napcat.actions.filter((item) => item.action === 'get_group_member_list').length
    const resolving = fetch(`${notificationUrl}/${encodeURIComponent(request.id)}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ action: 'accept' }),
    })
    await waitFor(async () =>
      napcat.actions.filter((item) => item.action === 'get_group_member_list').length > memberLookups,
    )

    const replacement = connectFakeNapCat(port)
    await replacement.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')
    expect((await resolving).status).toBe(503)
    const after = (await (await fetch(notificationUrl)).json()) as {
      items: Array<{ id: string; state: string; actionable: boolean }>
    }
    expect(after.items.find((item) => item.id === request.id)).toMatchObject({ state: 'pending' })
    expect(napcat.actions.some((item) => item.action === 'set_group_add_request')).toBe(false)
    expect(replacement.actions.some((item) => item.action === 'set_group_add_request')).toBe(false)
    replacement.socket.close()
  })

  it('does not grant group-request authority from a member row belonging to another group', async () => {
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port, { selfMemberGroupId: '456789013' })
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const account = `qq-${selfId}`
    const notificationUrl = `${baseUrl}/api/accounts/${account}/notifications`
    const inbox = (await (await fetch(`${notificationUrl}?refresh=1`)).json()) as {
      items: Array<{ id: string; kind: string; actionable: boolean }>
    }
    const request = inbox.items.find((item) => item.kind === 'group-request')!
    expect(request.actionable).toBe(false)

    const denied = await fetch(`${notificationUrl}/${encodeURIComponent(request.id)}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ action: 'accept' }),
    })
    expect(denied.status).toBe(403)
    const renameDenied = await fetch(`${baseUrl}/api/accounts/${account}/groups/345678901`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ name: '不应授权的群名' }),
    })
    expect(renameDenied.status).toBe(403)
    expect(napcat.actions.some((item) => item.action === 'set_group_add_request')).toBe(false)
    expect(napcat.actions.some((item) => item.action === 'set_group_name')).toBe(false)
    napcat.socket.close()
  })

  it('does not treat an unknown NapCat group role as an ordinary member or manager', async () => {
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port, { selfRole: 'future-owner' })
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const account = `qq-${selfId}`
    const groupBase = `${baseUrl}/api/accounts/${account}/groups/345678901`
    const members = (await (await fetch(`${groupBase}/members?refresh=1`)).json()) as {
      selfRole?: string
      members: Array<{ userId: string }>
    }
    expect(members.selfRole).toBeUndefined()
    expect(members.members.some((item) => item.userId === selfId)).toBe(false)

    const denied = await fetch(groupBase, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ name: '不应授权的群名' }),
    })
    expect(denied.status).toBe(403)
    expect(napcat.actions.some((item) => item.action === 'set_group_name')).toBe(false)
    napcat.socket.close()
  })

  it('maps every group management route to the exact allowlisted NapCat action and normalized event', async () => {
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const account = `qq-${selfId}`
    const groupBase = `${baseUrl}/api/accounts/${account}/groups/345678901`
    const events: unknown[] = []
    hub.on('workspace-event', (event) => events.push(event))

    expect((await fetch(`${groupBase}/members/234567890/admin`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ enabled: true }),
    })).status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === 'set_group_admin').at(-1)?.params).toEqual({
      group_id: '345678901', user_id: '234567890', enable: true,
    })

    expect((await fetch(`${groupBase}/members/${selfId}/card`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ card: '新的真实群名片' }),
    })).status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === 'set_group_card').at(-1)?.params).toEqual({
      group_id: '345678901', user_id: selfId, card: '新的真实群名片',
    })

    expect((await fetch(groupBase, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ name: '新的真实群名' }),
    })).status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === 'set_group_name').at(-1)?.params).toEqual({
      group_id: '345678901', group_name: '新的真实群名',
    })

    expect((await fetch(`${groupBase}/mute-all`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ enabled: true }),
    })).status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === 'set_group_whole_ban').at(-1)?.params).toEqual({
      group_id: '345678901', enable: true,
    })

    expect((await fetch(`${groupBase}/members/234567890`, {
      method: 'DELETE', headers: { Origin: baseUrl },
    })).status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === 'set_group_kick').at(-1)?.params).toEqual({
      group_id: '345678901', user_id: '234567890', reject_add_request: false,
    })
    expect(events).toContainEqual({ type: 'group.members.changed', accountId: account, groupId: '345678901' })
    expect(events).toContainEqual({ type: 'directory.changed', accountId: account })

    expect((await fetch(groupBase, { method: 'DELETE', headers: { Origin: baseUrl } })).status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === 'set_group_leave').at(-1)?.params).toEqual({
      group_id: '345678901', is_dismiss: false,
    })
    napcat.socket.close()
  })

  it('binds file and announcement IDs to their account and group while using exact NapCat file fields', async () => {
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    napcat.state.groups.push({
      group_id: 456789013,
      group_name: '另一个真实测试群',
      group_remark: '',
      member_count: 3,
    })
    const secondSelfId = '223456789'
    const secondNapcat = connectFakeNapCat(port, { selfId: secondSelfId })
    await napcat.ready
    await secondNapcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts.filter((item) => item.status === 'online').length === 2)
    const account = `qq-${selfId}`
    const groupBase = `${baseUrl}/api/accounts/${account}/groups/345678901`

    const files = (await (await fetch(`${groupBase}/files?parentId=%2F`)).json()) as {
      files: Array<{ id: string; name: string; downloadCount: number }>
      folders: Array<{ id: string; name: string }>
      permissions: Record<string, { allowed: boolean }>
    }
    const file = files.files[0]!
    const folder = files.folders[0]!
    expect(file).toMatchObject({ name: '真实文件.txt', downloadCount: 0 })
    expect(file.id).not.toContain('/real-file-id')
    expect(folder.id).not.toContain('/real-folder-id')
    expect(files.permissions.packetFiles).toEqual({ allowed: true })

    const download = await fetch(`${groupBase}/files/${encodeURIComponent(file.id)}/url?name=真实文件.txt`)
    expect(download.status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === 'get_group_file_url').at(-1)?.params).toEqual({
      group_id: '345678901',
      file_id: '/real-file-id',
    })

    const moved = await fetch(`${groupBase}/files/${encodeURIComponent(file.id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ operation: 'move', currentParentId: '/', targetParentId: folder.id }),
    })
    expect(moved.status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === 'move_group_file').at(-1)?.params).toEqual({
      group_id: '345678901',
      file_id: '/real-file-id',
      current_parent_directory: '/',
      target_parent_directory: '/real-folder-id',
    })

    const renamed = await fetch(`${groupBase}/files/${encodeURIComponent(file.id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ operation: 'rename', currentParentId: '/', name: '重命名文件.txt' }),
    })
    expect(renamed.status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === 'rename_group_file').at(-1)?.params).toEqual({
      group_id: '345678901',
      file_id: '/real-file-id',
      current_parent_directory: '/',
      new_name: '重命名文件.txt',
    })

    const uploadForm = new FormData()
    uploadForm.append('file', new Blob([Buffer.from('group-resource')], { type: 'text/plain' }), '群资源.txt')
    const uploaded = await fetch(`${groupBase}/files/uploads?parentId=${encodeURIComponent(folder.id)}`, {
      method: 'POST', headers: { Origin: baseUrl }, body: uploadForm,
    })
    expect(uploaded.status).toBe(201)
    expect(napcat.actions.filter((item) => item.action === 'upload_group_file').at(-1)?.params).toEqual({
      group_id: '345678901',
      file: `base64://${Buffer.from('group-resource').toString('base64')}`,
      name: '群资源.txt',
      folder: '/real-folder-id',
    })

    expect((await fetch(`${groupBase}/folders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ name: '新建真实文件夹' }),
    })).status).toBe(201)
    expect(napcat.actions.filter((item) => item.action === 'create_group_file_folder').at(-1)?.params).toEqual({
      group_id: '345678901', folder_name: '新建真实文件夹',
    })

    expect((await fetch(`${groupBase}/files/${encodeURIComponent(file.id)}`, {
      method: 'DELETE', headers: { Origin: baseUrl },
    })).status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === 'delete_group_file').at(-1)?.params).toEqual({
      group_id: '345678901', file_id: '/real-file-id',
    })

    expect((await fetch(`${groupBase}/folders/${encodeURIComponent(folder.id)}`, {
      method: 'DELETE', headers: { Origin: baseUrl },
    })).status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === 'delete_group_folder').at(-1)?.params).toEqual({
      group_id: '345678901', folder_id: '/real-folder-id',
    })

    const tampered = `${file.id.slice(0, -1)}x`
    expect((await fetch(`${groupBase}/files/${encodeURIComponent(tampered)}/url`)).status).toBe(400)

    const crossGroupActions = napcat.actions.filter((item) => item.action === 'get_group_file_url').length
    const crossGroup = await fetch(
      `${baseUrl}/api/accounts/${account}/groups/456789013/files/${encodeURIComponent(file.id)}/url`,
    )
    expect(crossGroup.status).toBe(400)
    expect(napcat.actions.filter((item) => item.action === 'get_group_file_url')).toHaveLength(crossGroupActions)

    const crossGroupFolderActions = napcat.actions.filter((item) => item.action === 'delete_group_folder').length
    const crossGroupFolder = await fetch(
      `${baseUrl}/api/accounts/${account}/groups/456789013/folders/${encodeURIComponent(folder.id)}`,
      { method: 'DELETE', headers: { Origin: baseUrl } },
    )
    expect(crossGroupFolder.status).toBe(400)
    expect(napcat.actions.filter((item) => item.action === 'delete_group_folder')).toHaveLength(crossGroupFolderActions)

    const secondAccount = `qq-${secondSelfId}`
    const crossAccountActions = secondNapcat.actions.filter((item) => item.action === 'get_group_file_url').length
    const crossAccount = await fetch(
      `${baseUrl}/api/accounts/${secondAccount}/groups/345678901/files/${encodeURIComponent(file.id)}/url`,
    )
    expect(crossAccount.status).toBe(400)
    expect(secondNapcat.actions.filter((item) => item.action === 'get_group_file_url')).toHaveLength(crossAccountActions)

    const announcements = (await (await fetch(`${groupBase}/announcements`)).json()) as Array<{
      id: string
      content: string
    }>
    expect(announcements[0]?.content).toBe('真实群公告')
    expect(announcements[0]?.id).not.toContain('notice-real-1')
    const crossAccountNoticeActions = secondNapcat.actions.filter((item) => item.action === '_del_group_notice').length
    const crossAccountNotice = await fetch(
      `${baseUrl}/api/accounts/${secondAccount}/groups/345678901/announcements/${encodeURIComponent(announcements[0]!.id)}`,
      { method: 'DELETE', headers: { Origin: baseUrl } },
    )
    expect(crossAccountNotice.status).toBe(400)
    expect(secondNapcat.actions.filter((item) => item.action === '_del_group_notice')).toHaveLength(crossAccountNoticeActions)
    const deleted = await fetch(`${groupBase}/announcements/${encodeURIComponent(announcements[0]!.id)}`, {
      method: 'DELETE',
      headers: { Origin: baseUrl },
    })
    expect(deleted.status).toBe(200)
    expect(napcat.actions.filter((item) => item.action === '_del_group_notice').at(-1)?.params).toEqual({
      group_id: '345678901',
      notice_id: 'notice-real-1',
    })

    const essence = (await (await fetch(`${groupBase}/essence`)).json()) as {
      items: Array<{ content: string }>
      hasMore: boolean
    }
    expect(essence).toMatchObject({ items: [{ content: '真实精华消息' }], hasMore: false })
    napcat.socket.close()
    secondNapcat.socket.close()
  })

  it('returns more than 100 group files and marks the 500-item NapCat boundary as truncated', async () => {
    const first = await startTestServer()
    servers.push(first.server)
    const firstNapcat = connectFakeNapCat(first.port, { groupFileCount: 101 })
    await firstNapcat.ready
    await waitFor(async () => first.hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const account = `qq-${selfId}`
    const firstPage = (await (
      await fetch(`${first.baseUrl}/api/accounts/${account}/groups/345678901/files`)
    ).json()) as { files: unknown[]; truncated: boolean }
    expect(firstPage.files).toHaveLength(101)
    expect(firstPage.truncated).toBe(false)
    expect(firstNapcat.actions.filter((item) => item.action === 'get_group_root_files').at(-1)?.params).toMatchObject({
      file_count: 500,
    })

    const bounded = await startTestServer()
    servers.push(bounded.server)
    const boundedNapcat = connectFakeNapCat(bounded.port, { groupFileCount: 500 })
    await boundedNapcat.ready
    await waitFor(async () => bounded.hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const boundedPage = (await (
      await fetch(`${bounded.baseUrl}/api/accounts/${account}/groups/345678901/files`)
    ).json()) as { files: unknown[]; truncated: boolean }
    expect(boundedPage.files).toHaveLength(500)
    expect(boundedPage.truncated).toBe(true)
    firstNapcat.socket.close()
    boundedNapcat.socket.close()
  })

  it('guards an unknown group-file upload outcome against duplicate manual replay', async () => {
    const { hub, server, port, baseUrl } = await startTestServer({
      actionTimeoutMs: 30,
      groupFileUploadTimeoutMs: 30,
    })
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')
    napcat.state.silentActions.add('upload_group_file')
    const account = `qq-${selfId}`
    const uploadUrl = `${baseUrl}/api/accounts/${account}/groups/345678901/files/uploads?parentId=%2F`
    const upload = () => {
      const form = new FormData()
      form.append('file', new Blob([Buffer.from('uncertain-upload')], { type: 'text/plain' }), '结果未知.txt')
      return fetch(uploadUrl, { method: 'POST', headers: { Origin: baseUrl }, body: form })
    }

    const [first, second] = await Promise.all([upload(), upload()])
    expect([first.status, second.status]).toEqual([409, 409])
    const errors = await Promise.all([first.json(), second.json()]) as Array<{ error: string }>
    expect(errors.some((item) => item.error.includes('结果未知'))).toBe(true)
    expect(napcat.actions.filter((item) => item.action === 'upload_group_file')).toHaveLength(1)
    napcat.socket.close()
  })

  it('guards concurrent chat-file uploads with the same group file uncertainty lock', async () => {
    const { hub, server, port, baseUrl } = await startTestServer({
      actionTimeoutMs: 30,
      groupFileUploadTimeoutMs: 30,
    })
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')
    napcat.state.silentActions.add('upload_group_file')
    const account = `qq-${selfId}`
    const uploadUrl = `${baseUrl}/api/accounts/${account}/conversations/group/345678901/uploads?purpose=file`
    const upload = () => {
      const form = new FormData()
      form.append('file', new Blob([Buffer.from('same-chat-file')], { type: 'text/plain' }), '聊天文件.txt')
      return fetch(uploadUrl, { method: 'POST', headers: { Origin: baseUrl }, body: form })
    }

    const [first, second] = await Promise.all([upload(), upload()])
    expect([first.status, second.status]).toEqual([409, 409])
    expect(napcat.actions.filter((item) => item.action === 'upload_group_file')).toHaveLength(1)
    expect((await upload()).status).toBe(409)
    expect(napcat.actions.filter((item) => item.action === 'upload_group_file')).toHaveLength(1)
    napcat.socket.close()
  })

  it('blocks management writes for ordinary members before any dangerous NapCat action', async () => {
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port, { selfRole: 'member' })
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const account = `qq-${selfId}`
    const groupBase = `${baseUrl}/api/accounts/${account}/groups/345678901`
    const files = (await (await fetch(`${groupBase}/files`)).json()) as {
      files: Array<{ id: string }>
      folders: Array<{ id: string }>
    }
    const announcements = (await (await fetch(`${groupBase}/announcements`)).json()) as Array<{ id: string }>
    const jsonHeaders = { 'Content-Type': 'application/json', Origin: baseUrl }
    const attempts = await Promise.all([
      fetch(`${groupBase}/members/234567890/admin`, {
        method: 'PUT', headers: jsonHeaders, body: JSON.stringify({ enabled: true }),
      }),
      fetch(`${groupBase}/members/234567890/card`, {
        method: 'PUT', headers: jsonHeaders, body: JSON.stringify({ card: '不应修改他人群名片' }),
      }),
      fetch(`${groupBase}/members/234567890`, { method: 'DELETE', headers: { Origin: baseUrl } }),
      fetch(groupBase, {
        method: 'PATCH', headers: jsonHeaders, body: JSON.stringify({ name: '不应生效的群名' }),
      }),
      fetch(`${groupBase}/mute-all`, {
        method: 'PUT', headers: jsonHeaders, body: JSON.stringify({ enabled: true }),
      }),
      fetch(`${groupBase}/announcements/${encodeURIComponent(announcements[0]!.id)}`, {
        method: 'DELETE', headers: { Origin: baseUrl },
      }),
      fetch(`${groupBase}/files/${encodeURIComponent(files.files[0]!.id)}`, {
        method: 'PATCH',
        headers: jsonHeaders,
        body: JSON.stringify({ operation: 'rename', currentParentId: '/', name: '不应生效.txt' }),
      }),
      fetch(`${groupBase}/files/${encodeURIComponent(files.files[0]!.id)}`, {
        method: 'DELETE', headers: { Origin: baseUrl },
      }),
      fetch(`${groupBase}/folders`, {
        method: 'POST', headers: jsonHeaders, body: JSON.stringify({ name: '不应创建' }),
      }),
      fetch(`${groupBase}/folders/${encodeURIComponent(files.folders[0]!.id)}`, {
        method: 'DELETE', headers: { Origin: baseUrl },
      }),
    ])
    expect(attempts.map((response) => response.status)).toEqual(Array(attempts.length).fill(403))
    const dangerousActions = new Set([
      'set_group_admin',
      'set_group_card',
      'set_group_kick',
      'set_group_name',
      'set_group_whole_ban',
      '_del_group_notice',
      'rename_group_file',
      'delete_group_file',
      'create_group_file_folder',
      'delete_group_folder',
    ])
    expect(napcat.actions.filter((item) => dangerousActions.has(item.action))).toHaveLength(0)
    napcat.socket.close()
  })

  it('sanitizes rejected NapCat action errors before returning them to the browser', async () => {
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')
    napcat.state.failureMessage = '/srv/private/napcat/secrets/account.json: raw upstream failure'
    napcat.state.failureWording = 'wording contains /home/qq/private-token.txt'
    napcat.state.failedActions.add('set_group_name')
    const account = `qq-${selfId}`

    const response = await fetch(`${baseUrl}/api/accounts/${account}/groups/345678901`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ name: '不会生效' }),
    })
    const body = await response.text()
    expect(response.status).toBe(502)
    expect(body).toContain('set_group_name')
    expect(body).toContain('1200')
    expect(body).not.toContain('/srv/private')
    expect(body).not.toContain('raw upstream failure')
    expect(body).not.toContain('/home/qq/private-token.txt')
    expect(body).not.toContain('wording contains')
    napcat.socket.close()
  })

  it('enforces authoritative role and remaining-count checks for @all on the send endpoint', async () => {
    const memberServer = await startTestServer()
    servers.push(memberServer.server)
    const memberNapcat = connectFakeNapCat(memberServer.port, { selfRole: 'member' })
    await memberNapcat.ready
    await waitFor(async () => memberServer.hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const account = `qq-${selfId}`
    const sendUrl = `${memberServer.baseUrl}/api/accounts/${account}/conversations/group/345678901/messages`
    const deniedByRole = await fetch(sendUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: memberServer.baseUrl },
      body: JSON.stringify({ segments: [{ type: 'mention', label: '全体成员', all: true }] }),
    })
    expect(deniedByRole.status).toBe(403)
    expect(memberNapcat.actions.some((item) => item.action === 'send_group_msg')).toBe(false)

    const countServer = await startTestServer()
    servers.push(countServer.server)
    const countNapcat = connectFakeNapCat(countServer.port, { atAllAllowed: false })
    await countNapcat.ready
    await waitFor(async () => countServer.hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const deniedByCount = await fetch(
      `${countServer.baseUrl}/api/accounts/${account}/conversations/group/345678901/messages`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Origin: countServer.baseUrl },
        body: JSON.stringify({ segments: [{ type: 'mention', label: '全体成员', all: true }] }),
      },
    )
    expect(deniedByCount.status).toBe(403)
    expect(countNapcat.actions.some((item) => item.action === 'get_group_at_all_remain')).toBe(true)
    expect(countNapcat.actions.some((item) => item.action === 'send_group_msg')).toBe(false)
  })

  it('keeps group file reads available when member metadata fails and gates Packet-only actions separately', async () => {
    const { hub, server, port, baseUrl } = await startTestServer()
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    napcat.state.failedActions.add('get_group_member_list')
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const account = `qq-${selfId}`
    const filesResponse = await fetch(`${baseUrl}/api/accounts/${account}/groups/345678901/files`)
    expect(filesResponse.status).toBe(200)
    const files = (await filesResponse.json()) as { files: unknown[]; permissions: Record<string, { allowed: boolean }> }
    expect(files.files).toHaveLength(1)
    expect(files.permissions.readFiles).toEqual({ allowed: true })
    expect(files.permissions.uploadFiles.allowed).toBe(false)

    const packetServer = await startTestServer()
    servers.push(packetServer.server)
    const packetNapcat = connectFakeNapCat(packetServer.port, { packetAvailable: false })
    await packetNapcat.ready
    await waitFor(async () => packetServer.hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const packetFiles = (await (
      await fetch(`${packetServer.baseUrl}/api/accounts/${account}/groups/345678901/files`)
    ).json()) as { files: Array<{ id: string }>; permissions: Record<string, { allowed: boolean }> }
    expect(packetFiles.permissions.packetFiles.allowed).toBe(false)
    expect(
      (
        await fetch(
          `${packetServer.baseUrl}/api/accounts/${account}/groups/345678901/files/${encodeURIComponent(packetFiles.files[0]!.id)}/url`,
        )
      ).status,
    ).toBe(502)
    expect(packetNapcat.actions.some((item) => item.action === 'get_group_file_url')).toBe(false)
    napcat.socket.close()
    packetNapcat.socket.close()
  })

  it('marks an observed request non-retryable when the NapCat mutation outcome is unknown', async () => {
    const { hub, server, port, baseUrl } = await startTestServer({ actionTimeoutMs: 30 })
    servers.push(server)
    const napcat = connectFakeNapCat(port)
    await napcat.ready
    await waitFor(async () => hub.workspaceSnapshot().accounts[0]?.status === 'online')
    const account = `qq-${selfId}`
    napcat.socket.send(
      JSON.stringify({
        time: 1_785_742_500,
        self_id: Number(selfId),
        post_type: 'request',
        request_type: 'friend',
        user_id: 678901234,
        comment: '好友申请',
        flag: 'friend-flag-1',
      }),
    )
    await waitFor(async () => {
      const inbox = (await (
        await fetch(`${baseUrl}/api/accounts/${account}/notifications`)
      ).json()) as { items: unknown[] }
      return inbox.items.length === 1
    })
    const inbox = (await (
      await fetch(`${baseUrl}/api/accounts/${account}/notifications`)
    ).json()) as { items: Array<{ id: string }> }
    napcat.state.silentActions.add('set_friend_add_request')
    const resolveUrl = `${baseUrl}/api/accounts/${account}/notifications/${encodeURIComponent(inbox.items[0]!.id)}/resolve`
    const [first, second] = await Promise.all([
      fetch(resolveUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Origin: baseUrl },
        body: JSON.stringify({ action: 'accept' }),
      }),
      fetch(resolveUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Origin: baseUrl },
        body: JSON.stringify({ action: 'reject' }),
      }),
    ])
    expect([first.status, second.status].sort()).toEqual([409, 502])
    expect(napcat.actions.filter((item) => item.action === 'set_friend_add_request')).toHaveLength(1)
    const after = (await (
      await fetch(`${baseUrl}/api/accounts/${account}/notifications`)
    ).json()) as { items: Array<{ state: string; actionable: boolean; comment: string }> }
    expect(after.items[0]).toMatchObject({ state: 'handled', actionable: false })
    expect(after.items[0]?.comment).toContain('结果待')
    napcat.socket.close()
  })
})
