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
  selfId?: string
  loginSelfId?: string
  reportSentEvent?: boolean
  sendMessageDelayMs?: number
  appVersion?: string
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
    reportSentEvent: options.reportSentEvent ?? false,
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
        data = { app_name: 'NapCat.Onebot', protocol_version: 'v11', app_version: options.appVersion ?? '4.18.13' }
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
        data = { messages: [realGroupMessage('来自真实 NapCat 的消息', { self_id: Number(connectionSelfId) })] }
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
    if (options.sendMessageDelayMs && ['send_group_msg', 'send_private_msg'].includes(request.action)) {
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
})
