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
      case 'nc_get_packet_status':
        data = null
        break
      case 'get_group_list':
        data = [{ group_id: 345678901, group_name: groupName, group_remark: '', member_count: 42 }]
        break
      case 'get_friend_list':
        data = [{ user_id: 456789012, nickname: '真实好友', remark: '' }]
        break
      case 'get_friends_with_category':
        data = [{ categoryId: 1, categoryName: '真实联系人', buddyList: [{ user_id: 456789012, nickname: '真实好友', remark: '' }] }]
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
      case 'get_group_member_list':
        data = [
          { group_id: 345678901, user_id: Number(ownerId), nickname: botName, card: '机器人群名片', role: 'owner', level: '12', join_time: 1_700_000_000, last_sent_time: Math.floor(Date.now() / 1000) },
          { group_id: 345678901, user_id: 234567890, nickname: '群成员', card: '真实成员', role: 'member', level: '8', join_time: 1_710_000_000, last_sent_time: Math.floor(Date.now() / 1000) },
        ]
        break
      case 'get_group_at_all_remain':
        data = { can_at_all: true, remain_at_all_count_for_group: 1, remain_at_all_count_for_self: 1 }
        break
      case 'get_group_system_msg':
        data = {
          invited_requests: [],
          join_requests: [{
            request_id: 9001,
            invitor_uin: 567890123,
            invitor_nick: '真实申请者',
            group_id: 345678901,
            group_name: groupName,
            message: '真实入群申请',
            checked: false,
          }],
        }
        break
      case 'get_essence_msg_list':
        data = [{
          msg_seq: 101,
          sender_id: 234567890,
          sender_nick: '真实成员',
          operator_id: Number(ownerId),
          operator_nick: botName,
          message_id: 101,
          operator_time: Math.floor(Date.now() / 1000),
          content: [{ type: 'text', data: { text: '来自 NapCat 的真实精华消息' } }],
        }]
        break
      case '_get_group_notice':
        data = [{ notice_id: 'notice-1', sender_id: Number(ownerId), publish_time: Math.floor(Date.now() / 1000), message: { text: '来自 NapCat 的真实群公告', images: [] }, read_num: 12 }]
        break
      case 'get_group_root_files':
        data = {
          files: [{ file_id: '/file-1', file_name: '真实群文件.txt', file_size: 2048, download_times: 3, uploader: Number(ownerId) }],
          folders: [{ folder_id: '/folder-1', folder_name: '真实资料', total_file_count: 1 }],
        }
        break
      case 'get_group_files_by_folder':
        data = { files: [], folders: [] }
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
  await expect(page.getByLabel('聊天消息').getByText('真实发送链路测试', { exact: true })).toBeVisible()

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
  if (process.env.DUDUDA_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '/tmp/dududa-chat-desktop.png' })
})

test('API Key workbench loads all three pools through the default browser adapter', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.stack || error.message))
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')

  const listed = page.waitForResponse((response) => response.url().endsWith('/api/api-keys'))
  await page.getByRole('button', { name: 'API Key 池' }).click()
  expect((await listed).ok()).toBe(true)
  await expect(page.getByRole('heading', { name: 'API Key 池' })).toBeVisible()
  await expect(page.locator('.pool-card')).toHaveCount(3)
  await expect(page.getByText('API Key 管理接口不可用')).toHaveCount(0)
  expect(pageErrors).toEqual([])
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
  if (process.env.DUDUDA_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '/tmp/dududa-api-key-pools.png', fullPage: true })
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

test('directory, notifications, group resources, and settings stay usable at the compact desktop breakpoint', async ({ page }) => {
  await page.setViewportSize({ width: 980, height: 760 })
  await page.goto('/')

  await page.locator('.route-nav button[title="联系人"]').click()
  await expect(page.getByRole('heading', { name: '联系人' })).toBeVisible()
  await expect(page.getByText('真实好友', { exact: true })).toBeVisible()
  const managementBox = await page.locator('.management-panel').boundingBox()
  expect(managementBox?.width ?? 0).toBeGreaterThan(850)

  await page.getByRole('tablist', { name: '联系人类型' }).getByRole('button', { name: /群聊/ }).click()
  await expect(page.getByText('NapCat 实时测试群', { exact: true })).toBeVisible()
  expect((await page.locator('.contact-item .avatar').first().boundingBox())?.width ?? 0).toBeLessThanOrEqual(50)
  await page.getByTitle('群聊管理').click()
  await expect(page.getByRole('dialog', { name: '群聊管理' })).toBeVisible()
  expect((await page.getByRole('dialog', { name: '群聊管理' }).locator('.avatar').first().boundingBox())?.width ?? 0).toBeLessThanOrEqual(50)
  await page.getByRole('button', { name: '资源' }).click()
  await expect(page.getByText('来自 NapCat 的真实精华消息', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '文件' }).click()
  await expect(page.getByText('真实群文件.txt', { exact: true })).toBeVisible()
  await expect(page.getByText(/群文件夹重命名/)).toBeVisible()
  if (process.env.DUDUDA_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '/tmp/dududa-directory-desktop.png' })
  await page.getByTitle('关闭群聊管理').click()

  await page.locator('.route-nav button[title="通知"]').click()
  await page.getByRole('tablist', { name: '通知类型' }).getByRole('button', { name: /群通知/ }).click()
  await expect(page.getByText(/真实入群申请/)).toBeVisible()
  if (process.env.DUDUDA_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '/tmp/dududa-notifications-desktop.png' })

  await page.locator('.route-nav button[title="设置"]').click()
  await expect(page.getByRole('heading', { name: '设置' })).toBeVisible()
  await expect(page.getByRole('button', { name: '跟随系统' })).toBeVisible()
  await expect(page.getByText('NapCat.Onebot', { exact: true })).toBeVisible()
  if (process.env.DUDUDA_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '/tmp/dududa-settings-desktop.png' })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('mobile management routes remain usable in portrait and short landscape viewports', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')

  await page.getByRole('button', { name: '联系人', exact: true }).click()
  await expect(page.getByRole('heading', { name: '联系人' })).toBeVisible()
  await expect(page.getByText('真实好友', { exact: true })).toBeVisible()
  await page.getByRole('tablist', { name: '联系人类型' }).getByRole('button', { name: /群聊/ }).click()
  await page.getByTitle('群聊管理').click()
  await expect(page.getByRole('dialog', { name: '群聊管理' })).toBeVisible()
  await page.getByRole('button', { name: '资源', exact: true }).click()
  await expect(page.getByText('来自 NapCat 的真实精华消息', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '文件', exact: true }).click()
  await expect(page.getByText('真实群文件.txt', { exact: true })).toBeVisible()
  await page.getByTitle('关闭群聊管理').click()

  await page.getByRole('button', { name: /^通知/ }).click()
  await expect(page.getByRole('heading', { name: '通知' })).toBeVisible()
  await page.getByRole('tablist', { name: '通知类型' }).getByRole('button', { name: /群通知/ }).click()
  await expect(page.getByText(/真实入群申请/)).toBeVisible()

  await page.getByRole('button', { name: 'Key 池', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'API Key 池' })).toBeVisible()
  await expect(page.locator('.pool-card')).toHaveCount(3)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)

  await page.getByRole('button', { name: '设置', exact: true }).click()
  await expect(page.getByRole('heading', { name: '设置' })).toBeVisible()
  await expect(page.getByRole('button', { name: '跟随系统' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
  if (process.env.DUDUDA_CAPTURE_SCREENSHOTS === '1') {
    await page.screenshot({ path: '/tmp/dududa-management-mobile.png' })
  }

  await page.setViewportSize({ width: 844, height: 390 })
  const cleanup = page.getByText('缓存清理', { exact: true })
  await cleanup.scrollIntoViewIfNeeded()
  await expect(cleanup).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
  if (process.env.DUDUDA_CAPTURE_SCREENSHOTS === '1') {
    await page.screenshot({ path: '/tmp/dududa-management-landscape.png' })
  }
})
