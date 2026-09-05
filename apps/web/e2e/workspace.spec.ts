import { expect, test } from '@playwright/test'
import { WebSocket } from 'ws'

const selfId = '123456789'
const token = 'playwright-only-onebot-token-32-chars'
let napcat: WebSocket | undefined
const extraNapcats: WebSocket[] = []
let syntheticSendActions = 0

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
        syntheticSendActions += 1
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
  syntheticSendActions = 0
  napcat = await openFakeNapCat()
})

test.afterEach(() => {
  napcat?.close()
  napcat = undefined
  extraNapcats.splice(0).forEach((socket) => socket.close())
})

for (const width of [1280, 390]) {
  test(`preview explains empty outcomes and zero probability without sending at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const scope = { accountId: `qq-${selfId}`, conversationId: `qq-${selfId}:group:345678901` }
    const policy = {
      schemaVersion: 1, scope, enabled: true,
      modelTier: { mode: 'adaptive', preferred: 'haiku', allowed: ['haiku'] },
      reasoning: { mode: 'adaptive', preferred: 'low', allowed: ['low'] },
      answerProfile: { mode: 'adaptive', preferred: 'short', allowed: ['short'] },
      replyIntensity: { mode: 'adaptive', preferred: 'normal', allowed: ['normal'] },
      contextLength: { mode: 'adaptive', preferred: 'standard', allowed: ['standard'] },
      groupChatStyle: { mode: 'adaptive', preferred: 'natural', allowed: ['natural'] },
      proactiveTalk: { probabilityPercent: 0, cooldownSeconds: 5, maximumPerHour: 500 },
      plugins: { 'social.proactive_talk': 'on' },
    }
    await page.route('**/api/agent/status', route => route.fulfill({ json: {
      available: true, outputEnabled: false, providerConfigured: true, modelMapping: { haiku: 'synthetic-model' }, warnings: [],
      runtimeControls: {
        passiveAutoReply: { actualEnabled: true, state: 'enabled', rolloutMode: 'canary', deliveryEnabled: true, killSwitch: false, summary: 'Synthetic' },
        proactiveGroupParticipation: { actualEnabled: true, state: 'enabled', stage: 'proactive_canary', deliveryEnabled: true, summary: 'Synthetic' },
      },
    } }))
    await page.route('**/api/agent/config**', route => route.fulfill({ json: policy }))
    await page.route('**/api/agent/catalog', route => route.fulfill({ json: {
      agent: { id: 'dududa', displayName: 'Dududa' }, selectionModes: ['adaptive'], pluginModes: ['off', 'on', 'auto'],
      models: [{ id: 'synthetic-model', tier: 'haiku', displayName: 'Synthetic light', available: true, modalities: ['text'], reasoningLevels: ['low'] }, { id: 'synthetic-model', tier: 'sonnet', displayName: 'Synthetic medium', available: true, modalities: ['text'], reasoningLevels: ['low'] }],
      reasoningLevels: ['low'], answerProfiles: ['short'], replyIntensities: ['normal'], groupChatStyles: ['natural'],
      contextLengths: [{ id: 'standard', messageLimit: 30, characterLimit: 18000 }],
      proactiveTalkLimits: { probabilityPercent: { minimum: 0, maximum: 100, step: 1 }, cooldownSeconds: { minimum: 5, maximum: 1800, step: 5 }, maximumPerHour: { minimum: 1, maximum: 500, step: 1 } },
      replyIntensityNotice: '', plugins: [], policyDefaults: policy,
    } }))
    await page.route('**/api/internal-test/mcp/catalog', route => route.fulfill({ json: { schemaVersion: 1, available: false, servers: [], capabilities: [] } }))
    const coverage = { source: 'synthetic', partial: true, truncated: true, historyMessagesRead: 2, oldestAt: '2026-09-04T08:00:00Z', newestAt: '2026-09-04T08:01:00Z' }
    const usage = { messageLimit: 31, characterLimit: 18000, messagesRead: 3, charactersRead: 80, coverage }
    await page.route('**/api/agent/respond', async route => {
      expect(route.request().postDataJSON().messages).toEqual([])
      await route.fulfill({ json: {
        runId: 'synthetic-empty', candidate: '', outcome: 'deferred', runtimeState: 'deferred', generationObserved: false,
        tier: 'haiku', model: 'synthetic-model', reasoning: 'low', answerProfile: 'short', replyIntensity: 'normal', contextLength: 'standard', groupChatStyle: 'natural',
        contextUsage: usage, effectiveSelection: { scope, policySource: 'saved', modelTier: 'haiku', model: 'synthetic-model', reasoning: 'low', answerProfile: 'short', replyIntensity: 'normal', contextLength: 'standard', groupChatStyle: 'natural', contextUsage: usage, plugins: {} },
        reasonCodes: ['conflicting_evidence_without_clarification', 'runtime.preview.no_send'], latencyMs: 1,
        generatedAt: '2026-09-04T09:00:00Z', outputCalls: 0, memoryWrites: 0, toolCalls: 0, runtimePath: 'dududa_2_preview',
      } })
    })
    await page.goto('/')
    await page.locator('.conversation-item').first().click()
    await page.getByRole('button', { name: width > 860 ? '打开 Agent Console' : 'Agent', exact: true }).click()
    const panel = page.getByRole('complementary', { name: 'Agent Console' })
    await panel.getByLabel('Agent 指令输入').fill('总结这段合成讨论')
    await panel.getByRole('button', { name: '发送给 Agent', exact: true }).click()
    await expect(panel.locator('.agent-message--assistant')).toContainText('本次暂缓回复')
    await expect(panel.locator('.agent-message--assistant')).toContainText('conflicting_evidence_without_clarification')
    await expect(panel.locator('.agent-message--assistant .status-part--success')).toHaveCount(0)
    await expect(panel.locator('.agent-message--assistant')).toContainText('仅最近 2 条历史（非全天，已截断）')
    await page.screenshot({ path: testInfo.outputPath('preview-deferred.png') })
    await panel.getByRole('button', { name: '配置', exact: true }).click()
    await expect(panel.getByText('触发概率为 0，不会自动搭话；服务连接与其他回复功能不受影响。')).toBeVisible()
    const probability = panel.locator('input[type=range]').filter({ visible: true }).first()
    await probability.fill('1')
    await probability.fill('0')
    await expect(panel.getByText('未保存草稿：触发概率为 0，保存后不会自动搭话；当前生效值仍以已保存配置为准。')).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('zero-probability-draft.png') })
    await panel.getByLabel('选择首选模型').selectOption('sonnet')
    await panel.getByRole('button', { name: '配置', exact: true }).click()
    await expect(panel.getByLabel('模型档位初值')).toHaveValue('sonnet')
    await panel.getByRole('button', { name: '对话', exact: true }).click()
    let failedRequests = 0
    await page.route('**/api/agent/respond', async route => {
      failedRequests += 1
      await route.fulfill({ status: 503, json: { error: '读取 QQ 历史失败：请检查账号后重试' } })
    })
    await panel.getByRole('button', { name: '对话', exact: true }).click()
    await panel.getByLabel('Agent 指令输入').fill('重试历史读取')
    await panel.getByRole('button', { name: '发送给 Agent', exact: true }).click()
    await expect(panel.locator('.preview-failure')).toContainText('读取 QQ 历史失败')
    await panel.getByRole('button', { name: '重试本次预览', exact: true }).click()
    await expect.poll(() => failedRequests).toBe(2)
    await panel.getByRole('button', { name: '运行', exact: true }).click()
    await expect(panel.getByText('未确认', { exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('actionable-preview-error.png') })
    expect(syntheticSendActions).toBe(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
  })
}

for (const width of [1280, 390]) {
  test(`group plugin switches persist scoped policy without sending at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const scope = { accountId: `qq-${selfId}`, conversationId: `qq-${selfId}:group:345678901` }
    let saved = {
      schemaVersion: 1, scope, enabled: true,
      modelTier: { mode: 'adaptive', preferred: 'haiku', allowed: ['haiku'] },
      reasoning: { mode: 'adaptive', preferred: 'low', allowed: ['low'] },
      answerProfile: { mode: 'adaptive', preferred: 'short', allowed: ['short'] },
      replyIntensity: { mode: 'adaptive', preferred: 'normal', allowed: ['normal'] },
      contextLength: { mode: 'adaptive', preferred: 'standard', allowed: ['standard'] },
      groupChatStyle: { mode: 'adaptive', preferred: 'natural', allowed: ['natural'] },
      proactiveTalk: { probabilityPercent: 0, cooldownSeconds: 5, maximumPerHour: 500 },
      plugins: { 'emoji.kitchen': 'off', 'arc.compat': 'off', 'social.reread.auto': 'off' },
    }
    const writes: Array<{ scope: typeof scope; policy: typeof saved }> = []
    await page.route('**/api/agent/status', route => route.fulfill({ json: { available: true, providerConfigured: true, outputEnabled: false, modelMapping: {}, warnings: [] } }))
    await page.route('**/api/agent/config**', async route => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON()
        writes.push(body)
        saved = body.policy
      }
      await route.fulfill({ json: saved })
    })
    await page.route('**/api/agent/catalog', route => route.fulfill({ json: {
      models: [], reasoningLevels: [], answerProfiles: [], replyIntensities: [], contextLengths: [], groupChatStyles: [],
      selectionModes: ['adaptive'], pluginModes: ['off', 'auto', 'on', 'locked'],
      proactiveTalkLimits: { probabilityPercent: { minimum: 0, maximum: 100, step: 1 }, cooldownSeconds: { minimum: 5, maximum: 1800, step: 5 }, maximumPerHour: { minimum: 1, maximum: 500, step: 1 } },
      policyDefaults: saved,
      plugins: [['emoji.kitchen', 'Emoji Kitchen 表情合成'], ['arc.compat', 'Arc 曲目与谱面'], ['social.reread.auto', '自动复读']].map(([id, displayName]) => ({
        id, displayName, kind: 'readonly_query', installed: true, available: true, policyManaged: true,
        runtimeTarget: 'astrbot', runtimeReadiness: 'online', executionKind: id === 'social.reread.auto' ? 'passive_behavior' : 'command_auto_reply', description: '仅本账号本群的显式开启权限',
      })),
    } }))
    await page.goto('/')
    await page.locator('.conversation-item').first().click()
    await page.getByRole('button', { name: width > 860 ? '打开 Agent Console' : 'Agent', exact: true }).click()
    const panel = page.getByRole('complementary', { name: 'Agent Console' })
    await panel.getByRole('button', { name: '配置', exact: true }).click()
    const control = panel.getByRole('switch', { name: '在本群启用Emoji Kitchen 表情合成', exact: true })
    await control.check()
    expect(writes).toHaveLength(0)
    await panel.getByRole('button', { name: '保存配置', exact: true }).click()
    await expect.poll(() => writes.length).toBe(1)
    expect(writes[0]!.scope).toEqual(scope)
    expect(saved.plugins).toEqual({ 'emoji.kitchen': 'on', 'arc.compat': 'off', 'social.reread.auto': 'off' })
    await panel.locator('.plugin-list').scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath('group-plugin-controls.png') })
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
    await control.uncheck()
    await panel.getByRole('button', { name: '保存配置', exact: true }).click()
    await expect.poll(() => writes.length).toBe(2)
    expect(saved.plugins['emoji.kitchen']).toBe('off')
    expect(syntheticSendActions).toBe(0)
  })
}

test('desktop operator reads and sends through the NapCat action channel', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')

  await expect(page.getByRole('heading', { name: '消息工作台' })).toBeVisible()
  await expect(page.getByText('NapCat 实时测试群', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('这条消息来自 OneBot 通道', { exact: true })).toBeVisible()
  await expect(page.getByText('QQ 在线', { exact: true })).toBeVisible()

  const composer = page.getByLabel('QQ 消息输入')
  await composer.fill('真实发送链路测试')
  await composer.press('Enter')
  await expect(page.getByLabel('聊天消息').getByText('真实发送链路测试', { exact: true })).toBeVisible()

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
  if (process.env.DUDUDA_CAPTURE_SCREENSHOTS === '1') await page.screenshot({ path: '/tmp/dududa-chat-desktop.png' })
})

test('offline status and search errors remain actionable without sending', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await expect(page.getByText('这条消息来自 OneBot 通道', { exact: true })).toBeVisible()
  const trigger = page.getByTitle('搜索聊天记录', { exact: true }).first()
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: '搜索消息' })
  await dialog.getByLabel('消息关键词').fill('没有匹配的关键词_xyz')
  await dialog.getByRole('button', { name: '搜索', exact: true }).click()
  await expect(dialog.getByText('未找到匹配消息，请调整关键词或日期范围')).toBeVisible()
  await dialog.getByTitle('关闭', { exact: true }).focus()
  await page.keyboard.press('Shift+Tab')
  expect(await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]')))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(trigger).toBeFocused()

  napcat!.send(JSON.stringify({ self_id: Number(selfId), post_type: 'meta_event', meta_event_type: 'heartbeat', status: { online: false, good: false } }))
  await expect(page.locator('.connection-notice')).toContainText('QQ 已离线')
  await expect(page.locator('.sidebar-footer')).toContainText('0 在线 / 1 个账号')
  await expect(page.getByTitle('发送消息', { exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '重新检测', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('offline-recovery.png') })
  await page.getByRole('button', { name: '联系人', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('联系人暂时无法读取')
  await expect(page.getByText('当前账号暂无联系人', { exact: true })).not.toBeVisible()
  await expect(page.getByRole('button', { name: '重试读取联系人', exact: true })).toBeVisible()
  expect(syntheticSendActions).toBe(0)
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

for (const width of [1280, 390, 320]) {
  test(`MCP workbench keeps styled controls and readable cards at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const names = ['校园公告', '学院通知', '评课社区', '图书馆开放时间', '校园生活参考', '校园通知', '本科专业设置', '教务处', '培养方案', '二课']
    const servers = names.map((displayName, index) => ({
      id: `public-server-${index}`, displayName, enabled: index !== 9, available: index !== 9,
      authentication: 'not_required', health: 'initializing', readiness: 'unverified',
      reason: index === 9 ? '服务未启用' : index === 1
        ? '连接检测已过期，请重新检测。此状态不代表源数据已失效；检测只验证协议与工具发现。'
        : '连接检测已过期，请重新检测',
      capabilityCount: index + 1, checkedAt: '2026-09-04T12:58:58Z',
    }))
    await page.route('**/api/internal-test/mcp/catalog', route => route.fulfill({
      json: { schemaVersion: 1, available: true, servers, capabilities: [] },
    }))
    let releaseCheck!: () => void
    const checkGate = new Promise<void>(resolve => { releaseCheck = resolve })
    let checkCalls = 0
    await page.route('**/api/mcp/check', async route => {
      checkCalls += 1
      await checkGate
      await route.fulfill({ json: { ok: true, server: {
        ...servers[0], readiness: 'healthy', health: 'healthy', reason: '连接正常（不代表数据时效）',
      } } })
    })
    await page.goto('/')
    await page.locator('.conversation-item').first().click()
    await page.getByRole('button', { name: width > 860 ? '打开 Agent Console' : 'Agent', exact: true }).click()
    const consolePanel = page.getByRole('complementary', { name: 'Agent Console' })
    await consolePanel.getByRole('button', { name: '配置', exact: true }).click()
    const workbench = consolePanel.locator('.mcp-workbench')
    await workbench.locator('summary').click()
    const cards = workbench.locator('.mcp-server-grid > article')
    await expect(cards).toHaveCount(10)
    await workbench.locator('.section-heading').scrollIntoViewIfNeeded()
    const checkButton = workbench.getByRole('button', { name: '检测 校园公告 连接' })
    await expect(checkButton).toHaveCSS('font-size', '9px')
    await expect(checkButton).toHaveCSS('border-radius', '5px')
    await expect(cards.first().locator('time')).toHaveAttribute('datetime', servers[0]!.checkedAt)
    await expect(workbench.getByRole('button', { name: '检测 二课 连接' })).toBeDisabled()
    expect(checkCalls).toBe(0)
    try {
      await checkButton.click()
      await expect(checkButton).toBeDisabled()
      await expect(checkButton).toHaveAttribute('aria-busy', 'true')
      await expect(checkButton).toContainText('检测中')
    } finally {
      releaseCheck()
    }
    await expect(checkButton).toBeEnabled()
    await expect(cards.first().locator('.mcp-server-status')).toContainText('连接正常')
    expect(checkCalls).toBe(1)
    await consolePanel.locator('.settings-view').evaluate(element => {
      const heading = element.querySelector('.mcp-workbench .section-heading')!
      element.scrollTop += heading.getBoundingClientRect().top - element.getBoundingClientRect().top + 25
    })
    const layout = await consolePanel.evaluate(element => {
      const scroller = element.querySelector('.settings-view')!
      const heading = element.querySelector('.mcp-workbench .section-heading')!
      const grid = element.querySelector('.mcp-server-grid')!
      return {
        pageOverflow: document.documentElement.scrollWidth - window.innerWidth,
        panelOverflow: scroller.scrollWidth - scroller.clientWidth,
        headingOffset: heading.getBoundingClientRect().top - scroller.getBoundingClientRect().top,
        tabsOverlap: element.querySelector('.agent-tabs')!.getBoundingClientRect().bottom - heading.getBoundingClientRect().top,
        columns: getComputedStyle(grid).gridTemplateColumns.split(' ').length,
        clippedCards: [...grid.querySelectorAll('article, .mcp-server-status, .mcp-server-meta')]
          .filter(item => item.scrollWidth > item.clientWidth + 1).length,
      }
    })
    expect(layout.pageOverflow).toBeLessThanOrEqual(0)
    expect(layout.panelOverflow).toBeLessThanOrEqual(0)
    expect(Math.abs(layout.headingOffset)).toBeLessThanOrEqual(1)
    expect(layout.tabsOverlap).toBeLessThanOrEqual(1)
    expect(layout.columns).toBe(width === 320 ? 1 : 2)
    expect(layout.clippedCards).toBe(0)
    await page.screenshot({ path: testInfo.outputPath('mcp-workbench.png') })
  })
}

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

  await page.locator('.mobile-more summary').click()
  await page.locator('.mobile-more').getByRole('button', { name: 'API Key 池', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'API Key 池' })).toBeVisible()
  await expect(page.locator('.pool-card')).toHaveCount(3)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)

  await page.locator('.mobile-more summary').click()
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
