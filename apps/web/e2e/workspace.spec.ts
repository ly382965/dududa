import { expect, test } from '@playwright/test'
import { WebSocket } from 'ws'

const selfId = '123456789'
const token = 'playwright-only-onebot-token-32-chars'
let napcat: WebSocket | undefined
const extraNapcats: WebSocket[] = []

function message(content: string, overrides: Record<string, unknown> = {}, ownerId = selfId) {
  return {
    self_id: Number(ownerId),
    time: Math.floor(Date.now() / 1000),
    message_id: 101,
    message_seq: 101,
    real_id: 101,
    user_id: 234567890,
    group_id: 345678901,
    group_name: 'NapCat 实时测试群',
    message_type: 'group',
    post_type: 'message',
    sender: { user_id: 234567890, nickname: '群成员', card: '真实成员', role: 'member' },
    message: [{ type: 'text', data: { text: content } }],
    message_format: 'array',
    raw_message: content,
    font: 0,
    ...overrides,
  }
}

async function openFakeNapCat(ownerId = selfId, botName = '嘟嘟哒真实号', groupName = 'NapCat 实时测试群'): Promise<WebSocket> {
  const socket = new WebSocket('ws://127.0.0.1:8180/onebot/v11/ws', {
    headers: { 'X-Self-ID': ownerId, Authorization: `Bearer ${token}`, 'X-Client-Role': 'Universal' },
  })
  let lastSentText = ''
  socket.on('message', (payload) => {
    const request = JSON.parse(payload.toString()) as {
      action: string
      params: Record<string, unknown>
      echo: string
    }
    let data: unknown
    switch (request.action) {
      case 'get_login_info':
        data = { user_id: Number(ownerId), nickname: botName }
        break
      case 'get_status':
        data = { online: true, good: true, stat: {} }
        break
      case 'get_version_info':
        data = { app_name: 'NapCat.Onebot', protocol_version: 'v11', app_version: '4.18.13' }
        break
      case 'get_group_list':
        data = [{ group_id: 345678901, group_name: groupName, group_remark: '', member_count: 42 }]
        break
      case 'get_friend_list':
        data = [{ user_id: 456789012, nickname: '真实好友', remark: '' }]
        break
      case 'get_recent_contact':
        data = [
          {
            lastestMsg: message('这条消息来自 OneBot 通道', { group_name: groupName }, ownerId),
            peerUin: '345678901',
            remark: '',
            msgTime: String(Math.floor(Date.now() / 1000)),
            chatType: 2,
            msgId: '101',
            sendNickName: '群成员',
            sendMemberName: '真实成员',
            peerName: groupName,
          },
        ]
        break
      case 'get_group_msg_history':
        data = { messages: [message('这条消息来自 OneBot 通道', { group_name: groupName }, ownerId)] }
        break
      case 'send_group_msg':
        lastSentText = String((request.params.message as Array<{ data?: { text?: string } }>)[0]?.data?.text ?? '')
        data = { message_id: 102 }
        break
      case 'get_msg':
        data = message(lastSentText, {
          message_id: 102,
          message_seq: 102,
          user_id: Number(ownerId),
          sender: { user_id: Number(ownerId), nickname: botName },
          group_name: groupName,
        }, ownerId)
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
  await new Promise<void>((resolve, reject) => {
    socket.once('open', resolve)
    socket.once('error', reject)
  })
  return socket
}

test.beforeEach(async () => {
  napcat = await openFakeNapCat()
})

test.afterEach(() => {
  napcat?.close()
  napcat = undefined
  extraNapcats.splice(0).forEach((socket) => socket.close())
})

test('desktop operator reads and sends through the NapCat action channel', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')

  await expect(page.getByRole('heading', { name: '消息工作台' })).toBeVisible()
  await expect(page.getByText('NapCat 实时测试群', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('这条消息来自 OneBot 通道', { exact: true })).toBeVisible()
  await expect(page.getByText('NapCat 实时连接')).toBeVisible()

  const composer = page.getByLabel('QQ 消息输入')
  await composer.fill('真实发送链路测试')
  await composer.press('Enter')
  await expect(page.getByText('真实发送链路测试', { exact: true })).toBeVisible()

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
  if (process.env.DUDUDA_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '/tmp/dududa-chat-desktop.png' })
})

test('mobile navigation keeps real QQ chat separate from the unavailable Agent runtime', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')

  await expect(page.getByLabel('会话列表')).toBeVisible()
  await page.locator('.conversation-item').first().click()
  await expect(page.getByRole('main')).toBeVisible()
  await expect(page.getByText('这条消息来自 OneBot 通道', { exact: true })).toBeVisible()
  await page.locator('.message-row').first().dispatchEvent('contextmenu')
  await expect(page.getByRole('button', { name: '复制', exact: true })).toBeVisible()
  if (process.env.DUDUDA_CAPTURE_SCREENSHOTS === '1') {
    await page.screenshot({ path: '/tmp/dududa-chat-mobile-message.png' })
  }
  await page.getByRole('button', { name: '关闭消息操作' }).click()

  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await expect(page.getByRole('complementary', { name: 'Agent Console' })).toBeVisible()
  await expect(page.getByText('Agent Runtime 未连接')).toBeVisible()

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
  if (process.env.DUDUDA_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '/tmp/dududa-chat-mobile.png' })
})

test('two real account scopes keep unsent drafts isolated', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.stack || error.message))
  const second = await openFakeNapCat('987654321', '二号真实号', '二号 NapCat 群')
  extraNapcats.push(second)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await page.waitForTimeout(500)
  expect(pageErrors).toEqual([])

  await page.getByRole('button', { name: '嘟嘟哒真实号', exact: true }).click()
  await expect(page.getByText('NapCat 实时测试群', { exact: true }).first()).toBeVisible()
  const composer = page.getByLabel('QQ 消息输入')
  await composer.fill('账号一未发送草稿')
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '二号真实号', exact: true }).click()
  await expect(page.getByText('二号 NapCat 群', { exact: true }).first()).toBeVisible()
  await composer.fill('账号二未发送草稿')
  await page.waitForTimeout(300)

  await page.getByRole('button', { name: '嘟嘟哒真实号', exact: true }).click()
  await expect(composer).toHaveText('账号一未发送草稿')

  const fileInput = page.locator('input[type="file"]:not([accept])')
  await fileInput.setInputFiles({ name: '待确认.txt', mimeType: 'text/plain', buffer: Buffer.from('not sent') })
  await expect(page.getByRole('dialog', { name: '发送文件' })).toBeVisible()
  await page.getByRole('button', { name: '取消', exact: true }).last().click()
  await expect(page.getByRole('dialog', { name: '发送文件' })).toBeHidden()
})

test('short mobile viewport keeps the NapCat connection actions reachable', async ({ page }) => {
  const socket = napcat
  napcat = undefined
  if (socket && socket.readyState !== WebSocket.CLOSED) {
    await new Promise<void>((resolve) => {
      socket.once('close', resolve)
      socket.close()
    })
  }

  await page.setViewportSize({ width: 844, height: 390 })
  await page.goto('/')

  await expect(page.getByRole('heading', { name: '等待 QQ 账号接入' })).toBeVisible()
  const footer = page.locator('.connection-panel footer')
  await footer.scrollIntoViewIfNeeded()
  await expect(footer).toBeInViewport({ ratio: 1 })

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
