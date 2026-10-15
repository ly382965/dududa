import { expect, test, type Page } from '@playwright/test'

import type { Account, ChatMessage, Conversation, RecallSettings, WorkspaceSnapshot } from '../src/types/workspace'

const accountId = 'qq-123450001'
const DAY = 86_400_000
const groupOriginal = '这是合成群聊中撤回前的原文：周五下午三点一起讨论课程安排。'
const privateOriginal = '这是合成私聊中撤回前的原文：请保留这条测试记录。'

async function mockRecallWorkspace(page: Page) {
  const now = Date.now()
  const account: Account = {
    id: accountId, botId: '123450001', name: '合成测试机器人', shortName: '测试 Bot',
    avatar: '', status: 'online', unread: 0, role: 'bot', accent: 'cyan',
  }
  const conversations: Conversation[] = [
    { id: `${accountId}:group:234560001`, accountId, type: 'group', peerId: '234560001',
      name: '合成防撤回测试群', avatar: '', lastMessage: '群聊合成消息', lastMessageAt: '15:00',
      unread: 0, pinned: false, muted: false, members: 12, updatedAt: now },
    { id: `${accountId}:private:345670001`, accountId, type: 'private', peerId: '345670001',
      name: '合成测试好友', avatar: '', lastMessage: '私聊合成消息', lastMessageAt: '14:59',
      unread: 0, pinned: false, muted: false, updatedAt: now - 1000 },
  ]
  const snapshot: WorkspaceSnapshot = {
    runtime: { status: 'connected', message: '合成测试环境', reverseWebSocketPath: '/onebot/v11/ws' },
    accounts: [account], conversations, messages: {}, sessions: [], agentMessages: {}, runs: [], configs: {},
  }
  const settings = new Map(conversations.map((conversation) => [conversation.id, { enabled: true, retentionDays: 7 }]))
  const messages = new Map(conversations.map((conversation) => {
    const content = conversation.type === 'group' ? groupOriginal : privateOriginal
    const message: ChatMessage = {
      id: `${conversation.id}:42`, accountId, conversationId: conversation.id, messageId: '42',
      senderId: '345670001', senderName: '合成测试成员', senderAvatar: '', timestamp: '15:00',
      timestampMs: now - 1000, content, segments: [{ type: 'text', text: content }], mine: false,
      status: 'recalled', recall: { recalledAt: now, retained: true, expiresAt: now + 7 * DAY },
    }
    return [conversation.id, [message]]
  }))
  const saved: Array<{ conversationId: string; settings: RecallSettings }> = []
  const recallLoads: string[] = []

  // Every API response is synthetic. No QQ connection or production API is used.
  await page.route('**/*', (route) => {
    const url = new URL(route.request().url())
    return url.origin === 'http://127.0.0.1:4174' ? route.continue() : route.abort()
  })
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const respond = (json: unknown, status = 200) => route.fulfill({ status, json })
    if (path === '/api/workspace') return respond(snapshot)
    if (path === '/api/events') return route.fulfill({ contentType: 'text/event-stream', body: ': synthetic events only\n\n' })
    if (path === '/api/agent/status') return respond({
      available: false, providerConfigured: false, outputEnabled: false, modelMapping: {}, warnings: [],
    })
    if (path.endsWith('/directory')) return respond({ accountId, friends: [], groups: [], refreshedAt: now })
    if (path.endsWith('/notifications')) return respond({ accountId, notifications: [], refreshedAt: now })
    for (const conversation of conversations) {
      const prefix = `/api/accounts/${accountId}/conversations/${conversation.type}/${conversation.peerId}`
      if (path === `${prefix}/recalls`) {
        recallLoads.push(conversation.id)
        return respond({ settings: settings.get(conversation.id), messages: messages.get(conversation.id), hasMore: false })
      }
      if (path === `${prefix}/recall-settings`) {
        expect(route.request().method()).toBe('PUT')
        const value = route.request().postDataJSON() as RecallSettings
        expect(Number.isInteger(value.retentionDays) && value.retentionDays >= 1 && value.retentionDays <= 30).toBe(true)
        settings.set(conversation.id, value)
        saved.push({ conversationId: conversation.id, settings: value })
        if (!value.enabled) messages.set(conversation.id, [])
        return respond(value)
      }
      if (path === `${prefix}/messages`) return respond({ messages: [], hasMoreBefore: false, hasMoreAfter: false })
      if (path === `${prefix}/read`) return respond({ ok: true })
    }
    return respond({ error: '合成验收未启用此接口' }, 503)
  })
  return { conversations, saved, recallLoads, messages }
}

test('opens saved forward contents and nested nodes from the recall archive', async ({ page }) => {
  const mock = await mockRecallWorkspace(page)
  const group = mock.conversations[0]!
  const original = mock.messages.get(group.id)![0]!
  const inner: ChatMessage = { ...original, id: 'inner', messageId: '2', status: 'sent', recall: undefined,
    content: '嵌套转发的保留原文', segments: [{ type: 'text', text: '嵌套转发的保留原文' }] }
  const child: ChatMessage = { ...inner, id: 'child', messageId: '1', content: '转发中的保留原文', segments: [
    { type: 'text', text: '转发中的保留原文' }, { type: 'forward', forwardId: 'nested', messages: [inner] },
  ] }
  mock.messages.set(group.id, [{ ...original, content: '[转发消息]',
    segments: [{ type: 'forward', forwardId: 'archived-bundle', messages: [child] }] }])
  let loads = 0
  await page.route('**/forwards/archived-bundle?*', (route) => {
    expect(new URL(route.request().url()).searchParams.get('messageId')).toBe('42')
    loads += 1
    return route.fulfill({ json: { forwardId: 'archived-bundle', messages: [child],
      retention: { recordedAt: Date.now(), expiresAt: Date.now() + DAY } } })
  })
  await page.goto('/')
  await page.locator('.conversation-item').filter({ hasText: group.name }).click()
  await page.getByRole('button', { name: '撤回记录与防撤回设置', exact: true }).click()
  const archive = page.getByRole('dialog', { name: '撤回记录', exact: true })
  await archive.locator('.forward-segment').click()
  const viewer = page.getByRole('dialog', { name: '合并转发消息', exact: true })
  await expect(viewer.getByText('转发中的保留原文', { exact: true })).toBeVisible()
  await viewer.locator('.forward-segment').click()
  await expect(viewer.getByText('嵌套转发的保留原文', { exact: true })).toBeVisible()
  await viewer.getByRole('button', { name: '返回上一层', exact: true }).click()
  await expect(viewer.getByText('转发中的保留原文', { exact: true })).toBeVisible()
  expect(loads).toBe(1)
  await viewer.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(archive).toBeVisible()
})

test('group recall archive shows originals and saves 1–30 day settings, then clears on disable', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  const mock = await mockRecallWorkspace(page)
  await page.goto('/')
  await page.locator('.conversation-item').filter({ hasText: '合成防撤回测试群' }).click()
  await page.getByRole('button', { name: '撤回记录与防撤回设置', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '撤回记录', exact: true })
  await expect(dialog.getByText(groupOriginal, { exact: true })).toBeVisible()
  await expect(dialog.getByText('已撤回 · 原文已保留', { exact: true })).toBeVisible()
  await expect(dialog.getByText(/撤回于/)).toBeVisible()
  await expect(dialog.getByLabel('保留此会话的撤回消息')).toBeChecked()
  await page.screenshot({ path: '/tmp/dududa-recall-preview.png' })

  const days = dialog.getByRole('spinbutton', { name: '撤回消息保存天数' })
  await expect(days).toHaveValue('7')
  for (const invalid of ['0', '31']) {
    await days.fill(invalid)
    await dialog.getByRole('button', { name: '保存设置', exact: true }).click()
    expect(await days.evaluate((input: HTMLInputElement) => input.checkValidity())).toBe(false)
    expect(mock.saved).toHaveLength(0)
  }
  for (const retentionDays of [1, 30]) {
    await days.fill(String(retentionDays))
    await dialog.getByRole('button', { name: '保存设置', exact: true }).click()
    await expect.poll(() => mock.saved.at(-1)?.settings).toEqual({ enabled: true, retentionDays })
    await expect(dialog.getByRole('status').filter({ hasText: '已保存' })).toBeVisible()
    await expect(dialog.getByText(groupOriginal, { exact: true })).toBeVisible()
  }

  await dialog.getByLabel('保留此会话的撤回消息').uncheck()
  await dialog.getByRole('button', { name: '保存设置', exact: true }).click()
  await expect.poll(() => mock.saved.at(-1)?.settings).toEqual({ enabled: false, retentionDays: 30 })
  await expect(dialog.getByText('此会话已关闭防撤回', { exact: true })).toBeVisible()
  await expect(dialog.getByText(groupOriginal, { exact: true })).toHaveCount(0)
  await dialog.getByRole('button', { name: '关闭撤回记录', exact: true }).click()
  await page.getByRole('button', { name: '撤回记录与防撤回设置', exact: true }).click()
  await expect(dialog.getByText('此会话已关闭防撤回', { exact: true })).toBeVisible()
  await expect(dialog.getByLabel('保留此会话的撤回消息')).not.toBeChecked()
  await expect(days).toHaveValue('30')
  expect(mock.saved.every((entry) => entry.conversationId === mock.conversations[0]!.id)).toBe(true)
})

test('private recall archive remains usable without horizontal overflow on a 390px screen', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const mock = await mockRecallWorkspace(page)
  await page.goto('/')
  await page.locator('.conversation-item').filter({ hasText: '合成测试好友' }).click()
  await page.getByRole('button', { name: '撤回记录与防撤回设置', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '撤回记录', exact: true })
  await expect(dialog.getByText('合成测试好友', { exact: true })).toBeVisible()
  await expect(dialog.getByText(privateOriginal, { exact: true })).toBeVisible()
  await expect(dialog.getByText('已撤回 · 原文已保留', { exact: true })).toBeVisible()
  expect(mock.recallLoads).toContain(mock.conversations[1]!.id)
  expect(mock.recallLoads).not.toContain(mock.conversations[0]!.id)

  const dimensions = await page.evaluate(() => {
    const panel = document.querySelector<HTMLElement>('.recall-dialog')!
    const messages = panel.querySelector<HTMLElement>('.archive-messages')!
    const bounds = panel.getBoundingClientRect()
    return {
      pageWidth: document.documentElement.scrollWidth,
      viewport: window.innerWidth,
      left: bounds.left,
      right: bounds.right,
      panelOverflow: panel.scrollWidth - panel.clientWidth,
      messagesOverflow: messages.scrollWidth - messages.clientWidth,
    }
  })
  expect(dimensions.pageWidth).toBeLessThanOrEqual(dimensions.viewport)
  expect(dimensions.left).toBeGreaterThanOrEqual(0)
  expect(dimensions.right).toBeLessThanOrEqual(dimensions.viewport)
  expect(dimensions.panelOverflow).toBeLessThanOrEqual(1)
  expect(dimensions.messagesOverflow).toBeLessThanOrEqual(1)
  await page.screenshot({ path: testInfo.outputPath('recall-private-mobile.png') })
  await dialog.getByRole('button', { name: '关闭撤回记录', exact: true }).click()
  await expect(dialog).toHaveCount(0)
})
