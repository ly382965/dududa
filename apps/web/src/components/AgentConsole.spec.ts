import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { internalTestAdapter } from '../services/internal-test'
import { mcpManagementAdapter } from '../services/mcp-management'
import type { InternalTestAgentPolicy, InternalTestPluginMode } from '../types/internal-test'
import AgentConsole from './AgentConsole.vue'

type Props = InstanceType<typeof AgentConsole>['$props']
const scope = { accountId: 'qq-100001', conversationId: 'qq-100001:group:200001' }
function policy(mode: InternalTestPluginMode = 'off'): InternalTestAgentPolicy {
  return {
    schemaVersion: 1, scope, enabled: true,
    modelTier: { mode: 'adaptive', preferred: 'haiku', allowed: ['haiku'] },
    reasoning: { mode: 'adaptive', preferred: 'low', allowed: ['low'] },
    answerProfile: { mode: 'adaptive', preferred: 'short', allowed: ['short'] },
    replyIntensity: { mode: 'adaptive', preferred: 'normal', allowed: ['normal'] },
    contextLength: { mode: 'adaptive', preferred: 'standard', allowed: ['standard'] },
    groupChatStyle: { mode: 'adaptive', preferred: 'natural', allowed: ['natural'] },
    proactiveTalk: { probabilityPercent: 8, cooldownSeconds: 600, maximumPerHour: 3 },
    plugins: { 'social.proactive_talk': mode, 'icourse.read': 'on' },
  }
}
const conversation: NonNullable<Props['conversation']> = {
  id: scope.conversationId, accountId: scope.accountId, type: 'group', peerId: '200001',
  name: '测试群', avatar: '', lastMessage: '', lastMessageAt: '', unread: 0,
  pinned: false, muted: false, updatedAt: 0,
}
const runtimeControls: NonNullable<Props['runtimeControls']> = {
  passiveAutoReply: {
    actualEnabled: true, state: 'enabled', rolloutMode: 'canary',
    deliveryEnabled: true, killSwitch: false, summary: 'Runtime online',
  },
  proactiveGroupParticipation: {
    actualEnabled: true, state: 'enabled', stage: 'proactive_canary',
    deliveryEnabled: true, summary: 'Only explicitly enabled groups participate',
  },
}

const wrappers: Array<ReturnType<typeof shallowMount<typeof AgentConsole>>> = []
function render(overrides: Partial<Props> = {}) {
  const wrapper = shallowMount(AgentConsole, {
    props: {
      conversation, accounts: [], sessions: [], messages: [], policy: policy(),
      policyLoading: false, policySaving: false, policyError: '', contextMessages: 0,
      tab: 'settings', available: true, runtimeLoading: false, runtimeError: '',
      runtimeWarning: '', runtimeControls, ...overrides,
    },
  })
  wrappers.push(wrapper)
  return wrapper
}
const selector = 'input[role="switch"][aria-label="在本群启用自动搭话"]'

const emoji = { id: 'emoji.kitchen', displayName: 'Emoji Kitchen 表情合成', kind: 'image_generation',
  installed: true, available: true, policyManaged: true, executionKind: 'command_auto_reply',
  runtimeTarget: 'astrbot', runtimeReadiness: 'online', description: '群级表情合成' } as const
const pluginCatalog = { plugins: [emoji], pluginModes: ['off', 'auto', 'on', 'locked'], proactiveTalkLimits: {
  probabilityPercent: { minimum: 0, maximum: 100, step: 1 },
  cooldownSeconds: { minimum: 5, maximum: 1800, step: 5 },
  maximumPerHour: { minimum: 1, maximum: 500, step: 1 },
} } as unknown as NonNullable<Props['catalog']>
const emojiSwitch = 'input[role="switch"][aria-label="在本群启用Emoji Kitchen 表情合成"]'

describe('group proactive participation switch', () => {
  beforeEach(() => {
    vi.spyOn(internalTestAdapter, 'mcpCatalog').mockResolvedValue({
      schemaVersion: 1, available: false, servers: [], capabilities: [],
    })
  })
  afterEach(() => {
    wrappers.splice(0).forEach(wrapper => wrapper.unmount())
    vi.restoreAllMocks()
  })

  it('distinguishes tiers that share the same underlying model', async () => {
    const original = policy()
    original.modelTier = { mode: 'preferred', preferred: 'sonnet', allowed: ['haiku', 'sonnet'] }
    const wrapper = render({ policy: original, catalog: {
      ...pluginCatalog,
      models: [
        { id: 'shared-model', tier: 'haiku', displayName: '轻量', available: true, modalities: ['text'], reasoningLevels: ['low'] },
        { id: 'shared-model', tier: 'sonnet', displayName: '中等', available: true, modalities: ['text'], reasoningLevels: ['low'] },
      ],
    } })
    const select = wrapper.get<HTMLSelectElement>('[aria-label="选择首选模型"]')
    expect(select.element.value).toBe('sonnet')
    await select.setValue('haiku')
    await select.setValue('sonnet')
    const updates = wrapper.emitted('updatePolicy')!
    expect((updates.at(-1)![0] as InternalTestAgentPolicy).modelTier.preferred).toBe('sonnet')
    expect(wrapper.emitted('saveSettings')).toBeUndefined()
  })

  it('toggles a group plugin without saving/sending and preserves other modes and scope', async () => {
    const original = { ...policy(), plugins: { ...policy().plugins, 'emoji.kitchen': 'off' as const } }
    const wrapper = render({ policy: original, catalog: pluginCatalog })
    await wrapper.get(emojiSwitch).setValue(true)
    const updated = wrapper.emitted('updatePolicy')![0]![0] as InternalTestAgentPolicy
    expect(updated).toEqual({ ...original, plugins: { ...original.plugins, 'emoji.kitchen': 'on' } })
    expect(wrapper.emitted('saveSettings')).toBeUndefined()
    expect(wrapper.emitted('sendPrompt')).toBeUndefined()
    await wrapper.setProps({ policy: updated })
    await wrapper.get(emojiSwitch).setValue(false)
    expect((wrapper.emitted('updatePolicy')![1]![0] as InternalTestAgentPolicy).plugins['emoji.kitchen']).toBe('off')
    const other = { ...original, scope: { ...scope, conversationId: 'qq-100001:group:other' } }
    await wrapper.setProps({ policy: other, conversation: { ...conversation, id: other.scope.conversationId, peerId: 'other' } })
    expect(wrapper.get<HTMLInputElement>(emojiSwitch).element.checked).toBe(false)
  })

  it.each([
    { policyLoading: true }, { policySaving: true }, { conversation: { ...conversation, type: 'private' as const } },
  ])('disables group plugin switch for unavailable editing state %s', overrides => {
    const wrapper = render({ ...overrides, catalog: pluginCatalog })
    if ('policyLoading' in overrides) expect(wrapper.find(emojiSwitch).exists()).toBe(false)
    else expect(wrapper.get<HTMLInputElement>(emojiSwitch).element.disabled).toBe(true)
  })

  it('does not hide a saved mode when the conversation master is off', () => {
    const wrapper = render({ catalog: pluginCatalog, policy: { ...policy(), enabled: false, plugins: { 'emoji.kitchen': 'locked' } } })
    expect(wrapper.get<HTMLInputElement>(emojiSwitch).element.checked).toBe(true)
    expect(wrapper.text()).toContain('会话总开关已关闭，当前不生效')
  })

  it('edits only the proactive plugin and uses the existing explicit save action', async () => {
    const original = policy()
    const wrapper = render({ policy: original })
    expect(wrapper.get<HTMLInputElement>(selector).element.checked).toBe(false)
    await wrapper.get(selector).setValue(true)
    const updated = wrapper.emitted('updatePolicy')![0]![0] as InternalTestAgentPolicy
    expect(updated).toEqual({ ...original, plugins: { ...original.plugins, 'social.proactive_talk': 'auto' } })
    expect(original.plugins['social.proactive_talk']).toBe('off')
    expect(wrapper.emitted('saveSettings')).toBeUndefined()
    expect(wrapper.text()).toContain('修改后点击底部「保存配置」生效')
    await wrapper.setProps({ policy: updated })
    expect(wrapper.get<HTMLInputElement>(selector).element.checked).toBe(true)
    await wrapper.findAll('button').find(button => button.text() === '保存配置')!.trigger('click')
    expect(wrapper.emitted('saveSettings')).toHaveLength(1)
    expect(wrapper.emitted('sendPrompt')).toBeUndefined()
  })

  it.each(['auto', 'on', 'locked'] as const)('can disable existing %s mode', async mode => {
    const original = policy(mode)
    const wrapper = render({ policy: original })
    expect(wrapper.get<HTMLInputElement>(selector).element.checked).toBe(true)
    await wrapper.get(selector).setValue(false)
    expect(wrapper.emitted('updatePolicy')![0]![0]).toEqual({
      ...original, plugins: { ...original.plugins, 'social.proactive_talk': 'off' },
    })
  })

  it.each([
    ['missing policy', { policy: undefined }],
    ['loading', { policyLoading: true }],
    ['saving', { policySaving: true }],
    ['private chat', { conversation: { ...conversation, type: 'private' } }],
  ] as Array<[string, Partial<Props>]>)('disables the switch for %s', (_name, props) => {
    expect(render(props).get<HTMLInputElement>(selector).element.disabled).toBe(true)
  })

  it('does not claim actual participation while the conversation Agent is disabled', () => {
    const wrapper = render({ policy: { ...policy('auto'), enabled: false } })
    expect(wrapper.text()).not.toContain('本群已开启')
    expect(wrapper.text()).toContain('本群未开启')
  })

  it('explains saved and draft zero-probability policies without changing them', async () => {
    const zero = { ...policy('on'), proactiveTalk: { probabilityPercent: 0, cooldownSeconds: 5, maximumPerHour: 500 } }
    const wrapper = render({ policy: zero })
    expect(wrapper.text()).toContain('触发概率为 0，不会自动搭话')
    expect(wrapper.text()).not.toContain('未保存草稿：')
    expect(wrapper.emitted('updatePolicy')).toBeUndefined()
    await wrapper.setProps({ policyDirty: true })
    expect(wrapper.text()).toContain('未保存草稿：触发概率为 0，保存后不会自动搭话')
    expect(wrapper.get<HTMLInputElement>(selector).element.checked).toBe(true)
    expect(zero.proactiveTalk.probabilityPercent).toBe(0)
  })

  it('checks a registered MCP and preserves empty-query results through catalog refresh', async () => {
    const server = { id: 'library', displayName: '图书馆', enabled: true, available: true,
      authentication: 'not_required' as const, health: 'initializing' as const,
      readiness: 'unverified' as const, reason: '尚未检测连接', capabilityCount: 1 }
    vi.mocked(internalTestAdapter.mcpCatalog).mockResolvedValue({
      schemaVersion: 1, available: true, servers: [server], capabilities: [{
        id: 'console.library.query.v1', serverId: 'library', toolName: 'library_hours_public_query',
        name: '图书馆查询', description: '留空浏览', category: 'console.library', privacy: 'conversation',
        allowedContexts: ['private'], authentication: 'not_required', available: true,
        inputSchema: { type: 'object', properties: { query: { type: 'string', default: '' } }, required: ['query'] },
      }],
    })
    const check = vi.spyOn(mcpManagementAdapter, 'check').mockResolvedValue({ ok: true,
      server: { ...server, health: 'healthy', readiness: 'healthy', reason: '连接正常（不代表数据时效）' } })
    const invoke = vi.spyOn(internalTestAdapter, 'invokeMcp').mockResolvedValue({
      ok: true, capabilityId: 'console.library.query.v1', serverId: 'library', toolName: 'library_hours_public_query',
      data: { source: 'official-cache', freshness_note: '日常时间，非假期公告', items: [] }, content: [], generation: 1,
      fetchedAt: '2026-09-04T11:00:00Z',
    })
    const wrapper = render()
    await flushPromises()
    expect(wrapper.get('.mcp-server-grid').text()).toContain('尚未检测连接')
    expect(wrapper.find('.mcp-server-grid span.available').exists()).toBe(false)
    await wrapper.get('.mcp-check-button').trigger('click')
    await flushPromises()
    expect(check).toHaveBeenCalledExactlyOnceWith('library')
    await wrapper.get('.mcp-invoke-button').trigger('click')
    await flushPromises()
    expect(invoke).toHaveBeenCalledExactlyOnceWith('console.library.query.v1', { query: '' })
    expect(wrapper.get('.mcp-result').text()).toContain('official-cache')
    expect(wrapper.get('.mcp-result').text()).toContain('缓存更新时间')
    expect(wrapper.get('.mcp-result').text()).toContain('日常时间，非假期公告')
  })
})
