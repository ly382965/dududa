import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import AccountRail from '../components/AccountRail.vue'
import {
  HttpApiKeyPoolsAdapter,
} from '../services/api-key-pools'
import type {
  ApiKeyEntry,
  ApiKeyMutationResponse,
  ApiKeyPool,
  ApiKeyPoolTestResult,
  ApiKeyPoolUpdateRequest,
  ApiKeyPoolsAdapter,
  ApiKeyTier,
  ApiKeyCreateRequest,
  ApiKeyUpdateRequest,
} from '../types/api-key-pools'
import {
  API_KEY_TIERS,
  emptyApiKeyPool,
} from '../types/api-key-pools'
import type { Account } from '../types/workspace'
import ApiKeyPoolsView from './ApiKeyPoolsView.vue'

function key(id: string, overrides: Partial<ApiKeyEntry> = {}): ApiKeyEntry {
  return {
    id,
    name: id,
    secretRef: `provider/${id}`,
    masked: 'sk-••••1234',
    priority: 10,
    weight: 1,
    enabled: true,
    status: 'active',
    ...overrides,
  }
}

function pool(tier: ApiKeyTier, overrides: Partial<ApiKeyPool> = {}): ApiKeyPool {
  return {
    ...emptyApiKeyPool(tier),
    provider: 'Test Provider',
    baseUrl: 'https://provider.example/v1',
    model: `gpt-${tier}`,
    enabled: true,
    keys: [key(`${tier}-primary`)],
    ...overrides,
  }
}

function response(pools: ApiKeyPool[] = API_KEY_TIERS.map((tier) => pool(tier))) {
  return { schemaVersion: 1 as const, revision: 1, pools }
}

class FakeAdapter implements ApiKeyPoolsAdapter {
  readonly pools = API_KEY_TIERS.map((tier) => pool(tier))
  readonly creates: Array<{ tier: ApiKeyTier; request: ApiKeyCreateRequest }> = []
  readonly updates: Array<{ tier: ApiKeyTier; keyId: string; request: ApiKeyUpdateRequest }> = []
  readonly poolUpdates: Array<{ tier: ApiKeyTier; request: ApiKeyPoolUpdateRequest }> = []
  readonly removals: Array<{ tier: ApiKeyTier; keyId: string }> = []
  readonly tests: ApiKeyTier[] = []

  async list() {
    return response(this.pools)
  }

  async updatePool(tier: ApiKeyTier, request: ApiKeyPoolUpdateRequest): Promise<ApiKeyMutationResponse> {
    this.poolUpdates.push({ tier, request })
    const current = this.pools.find((item) => item.tier === tier)!
    const next = { ...current, ...request, revision: typeof current.revision === 'number' ? current.revision + 1 : current.revision }
    this.pools.splice(this.pools.indexOf(current), 1, next)
    return { pool: next, writeReceipt: { status: 'committed' } }
  }

  async createKey(tier: ApiKeyTier, request: ApiKeyCreateRequest): Promise<ApiKeyMutationResponse> {
    this.creates.push({ tier, request })
    const current = this.pools.find((item) => item.tier === tier)!
    const created = key(`${tier}-created`, { name: request.name, secretRef: request.secretRef || '', priority: request.priority ?? 0, weight: request.weight ?? 1, enabled: request.enabled ?? true })
    const next = { ...current, keys: [created, ...current.keys] }
    this.pools.splice(this.pools.indexOf(current), 1, next)
    return { pool: next, key: created, writeReceipt: { status: 'committed' } }
  }

  async updateKey(tier: ApiKeyTier, keyId: string, request: ApiKeyUpdateRequest): Promise<ApiKeyMutationResponse> {
    this.updates.push({ tier, keyId, request })
    const current = this.pools.find((item) => item.tier === tier)!
    const previous = current.keys.find((item) => item.id === keyId)!
    const nextKey = { ...previous, ...request, ...(request.secret ? { masked: 'sk-••••rotated' } : {}) }
    const next = { ...current, keys: current.keys.map((item) => item.id === keyId ? nextKey : item) }
    this.pools.splice(this.pools.indexOf(current), 1, next)
    return { pool: next, key: nextKey, writeReceipt: { status: 'committed' } }
  }

  async deleteKey(tier: ApiKeyTier, keyId: string): Promise<ApiKeyMutationResponse> {
    this.removals.push({ tier, keyId })
    const current = this.pools.find((item) => item.tier === tier)!
    const next = { ...current, keys: current.keys.filter((item) => item.id !== keyId) }
    this.pools.splice(this.pools.indexOf(current), 1, next)
    return { pool: next, writeReceipt: { status: 'committed' } }
  }

  async testPool(tier: ApiKeyTier): Promise<ApiKeyPoolTestResult> {
    this.tests.push(tier)
    const current = this.pools.find((item) => item.tier === tier)!
    const revision = typeof current.revision === 'number' ? current.revision + 1 : current.revision
    const checkedAt = '2026-09-03T16:00:00.000Z'
    const keys = current.keys.map((item, index) => index === 0
      ? { ...item, status: 'active', lastSuccessAt: checkedAt }
      : item)
    this.pools.splice(this.pools.indexOf(current), 1, { ...current, keys, revision })
    return { status: 'ok', message: 'Provider 探测成功', latencyMs: 42, model: pool(tier).model, checkedAt, revision }
  }
}

function mountView(adapter = new FakeAdapter()) {
  const wrapper = mount(ApiKeyPoolsView, { props: { adapter } })
  return { wrapper, adapter }
}

afterEach(() => {
  vi.restoreAllMocks()
  window.localStorage.clear()
})

describe('ApiKeyPoolsView', () => {
  it('shows shared connection settings from the Key dialog and clears an abandoned secret', async () => {
    const { wrapper, adapter } = mountView()
    await flushPromises()
    await wrapper.get('[data-tier="haiku"] .add-key').trigger('click')
    expect(wrapper.get('.key-editor').text()).toContain('https://provider.example/v1')
    await wrapper.get('.key-editor input[type="password"]').setValue('abandoned-secret-sentinel')
    await wrapper.get('.key-editor .connection-help button').trigger('click')
    await flushPromises()
    expect(wrapper.find('.key-editor').exists()).toBe(false)
    expect((wrapper.get('input[type="url"]').element as HTMLInputElement).value).toBe('https://provider.example/v1')
    expect(wrapper.html()).not.toContain('abandoned-secret-sentinel')
    expect(adapter.creates).toHaveLength(0)
  })
  it('renders three independent tier pools and never exposes a raw key from metadata', async () => {
    const { wrapper } = mountView()
    await flushPromises()

    expect(wrapper.findAll('.pool-card')).toHaveLength(3)
    expect(wrapper.find('[data-tier="haiku"]')?.text()).toContain('Luna')
    expect(wrapper.find('[data-tier="sonnet"]')?.text()).toContain('Terra')
    expect(wrapper.find('[data-tier="opus"]')?.text()).toContain('Sol')
    expect(wrapper.text()).not.toContain('unit-test-private-value')
    expect(window.localStorage.length).toBe(0)
  })

  it('submits a new secret only on explicit create and clears it from the component immediately', async () => {
    const { wrapper, adapter } = mountView()
    await flushPromises()
    await wrapper.get('[data-tier="haiku"] .add-key').trigger('click')
    const form = wrapper.get('.key-editor form')
    await form.get('input[placeholder="例如主 Key"]').setValue('备用 Luna')
    await form.get('input[type="password"]').setValue('unit-test-private-value')
    await form.get('input[placeholder="provider/luna-primary"]').setValue('provider/luna-secondary')
    await form.trigger('submit')
    await flushPromises()

    expect(adapter.creates).toHaveLength(1)
    expect(adapter.creates[0]?.request.secret).toBe('unit-test-private-value')
    expect(wrapper.find('.key-editor').exists()).toBe(false)
    expect(wrapper.text()).toContain('备用 Luna')
    expect(wrapper.text()).not.toContain('unit-test-private-value')
    expect(wrapper.html()).not.toContain('unit-test-private-value')
    expect(window.localStorage.length).toBe(0)
  })

  it('rotates an existing key without requiring or rendering the previous value', async () => {
    const { wrapper, adapter } = mountView()
    await flushPromises()
    await wrapper.get('[data-tier="sonnet"] .key-row button[aria-label="编辑 sonnet-primary"]').trigger('click')
    const form = wrapper.get('.key-editor form')
    const boundaryRef = `provider/${'a'.repeat(151)}`
    expect(form.get('input[type="password"]').attributes('placeholder')).toContain('留空保持现有密钥')
    await form.get('input[type="password"]').setValue('unit-test-rotated-value')
    await form.get('input[placeholder="provider/luna-primary"]').setValue(boundaryRef)
    await form.trigger('submit')
    await flushPromises()

    expect(adapter.updates[0]?.request.secret).toBe('unit-test-rotated-value')
    expect(adapter.updates[0]?.request.secretRef).toBe(boundaryRef)
    expect(adapter.updates[0]?.request.revision).toBe(1)
    expect(wrapper.find('.key-editor').exists()).toBe(false)
    expect(wrapper.html()).not.toContain('unit-test-rotated-value')
  })

  it('edits pool metadata, probes a pool, toggles a key, and removes it', async () => {
    const { wrapper, adapter } = mountView()
    await flushPromises()
    const card = wrapper.get('[data-tier="opus"]')
    await card.get('button').trigger('click')
    await flushPromises()
    expect(adapter.tests).toEqual(['opus'])
    expect(wrapper.text()).toContain('Provider 探测成功')
    expect(card.get('.status-chip').text()).toBe('可用')

    await card.get('button[aria-label="编辑 Sol · 深度推理 池"]').trigger('click')
    const poolForm = wrapper.get('.pool-editor form')
    await poolForm.get('input[placeholder="例如 OpenAI-compatible"]').setValue('New Provider')
    await poolForm.trigger('submit')
    await flushPromises()
    expect(adapter.poolUpdates[0]?.request.provider).toBe('New Provider')
    expect(adapter.poolUpdates[0]?.request.revision).toBe(2)
    expect(card.find('.test-result').exists()).toBe(false)

    const keyRow = wrapper.get('[data-tier="opus"] .key-row')
    await keyRow.get('button[aria-label="停用 opus-primary"]').trigger('click')
    await flushPromises()
    expect(adapter.updates.some((item) => item.keyId === 'opus-primary' && item.request.enabled === false && item.request.revision === 3)).toBe(true)
    await keyRow.get('button[aria-label="移除 opus-primary"]').trigger('click')
    expect(keyRow.get('button[aria-label="确认移除 opus-primary"]').text()).toContain('再次确认')
    expect(adapter.removals).toHaveLength(0)
    await keyRow.get('button[aria-label="确认移除 opus-primary"]').trigger('click')
    await flushPromises()
    expect(adapter.removals).toEqual([{ tier: 'opus', keyId: 'opus-primary' }])
  })

  it('contains modal focus, closes on Escape, and restores the trigger', async () => {
    const adapter = new FakeAdapter()
    const wrapper = mount(ApiKeyPoolsView, { props: { adapter }, attachTo: document.body })
    await flushPromises()
    const trigger = wrapper.get('[data-tier="haiku"] .add-key')
    ;(trigger.element as HTMLElement).focus()
    await trigger.trigger('click')
    await flushPromises()

    const dialog = wrapper.get('.key-editor')
    expect(dialog.element.contains(document.activeElement)).toBe(true)
    const buttons = dialog.findAll('button')
    const last = buttons[buttons.length - 1]!
    ;(last.element as HTMLElement).focus()
    await last.trigger('keydown', { key: 'Tab' })
    expect(dialog.element.contains(document.activeElement)).toBe(true)
    await dialog.trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(wrapper.find('.key-editor').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
    wrapper.unmount()
  })

  it('rejects an invalid runtime binding before saving pool metadata', async () => {
    const { wrapper, adapter } = mountView()
    await flushPromises()
    await wrapper.get('[data-tier="haiku"] button[aria-label="编辑 Luna · 轻量推理 池"]').trigger('click')
    const form = wrapper.get('.pool-editor form')
    await form.get('input[placeholder="dududa-haiku-source"]').setValue('invalid source id')
    await form.trigger('submit')

    expect(wrapper.get('.form-error').text()).toContain('Source ID 格式无效')
    expect(adapter.poolUpdates).toHaveLength(0)
  })

  it('preserves a supported 900 second timeout during an unrelated edit', async () => {
    const adapter = new FakeAdapter()
    const current = adapter.pools.find((item) => item.tier === 'sonnet')!
    adapter.pools.splice(adapter.pools.indexOf(current), 1, { ...current, timeoutMs: 900_000 })
    const { wrapper } = mountView(adapter)
    await flushPromises()
    await wrapper.get('[data-tier="sonnet"] button[aria-label="编辑 Terra · 标准推理 池"]').trigger('click')
    const form = wrapper.get('.pool-editor form')
    await form.get('input[placeholder="例如 OpenAI-compatible"]').setValue('Renamed Provider')
    await form.trigger('submit')
    await flushPromises()

    expect(adapter.poolUpdates[0]?.request.timeoutMs).toBe(900_000)
  })

  it('uses failure metadata instead of labeling an errored key as successful', async () => {
    const adapter = new FakeAdapter()
    const current = adapter.pools.find((item) => item.tier === 'haiku')!
    const failed = { ...current.keys[0]!, status: 'error', lastSuccessAt: '2026-09-01T00:00:00Z', lastFailureAt: '2026-09-03T00:00:00Z' }
    adapter.pools.splice(adapter.pools.indexOf(current), 1, { ...current, keys: [failed] })
    const { wrapper } = mountView(adapter)
    await flushPromises()

    const health = wrapper.get('[data-tier="haiku"] .key-row__health')
    expect(health.text()).toContain('失败')
    expect(health.text()).not.toContain('成功')
  })

  it('gates pool actions until the initial snapshot has loaded', async () => {
    const adapter = new FakeAdapter()
    let release!: () => void
    const pending = new Promise<ReturnType<typeof response>>((resolve) => {
      release = () => resolve(response(adapter.pools))
    })
    vi.spyOn(adapter, 'list').mockReturnValue(pending)
    const wrapper = mount(ApiKeyPoolsView, { props: { adapter } })
    await wrapper.vm.$nextTick()

    const add = wrapper.get('[data-tier="haiku"] .add-key')
    expect(add.attributes('disabled')).toBeDefined()
    await add.trigger('click')
    expect(wrapper.find('.key-editor').exists()).toBe(false)
    release()
    await flushPromises()
    expect(add.attributes('disabled')).toBeUndefined()
  })
})

describe('ApiKeyPoolsAdapter', () => {
  it('calls fetch without using the adapter as its receiver', async () => {
    const fetchLike = function (this: unknown) {
      if (this !== undefined) throw new TypeError('Illegal invocation')
      return Promise.resolve(new Response(JSON.stringify({ schemaVersion: 1, revision: 1, pools: [] }), { status: 200 }))
    } as typeof fetch
    const result = await new HttpApiKeyPoolsAdapter('', fetchLike).list()

    expect(result.pools).toHaveLength(3)
  })

  it('normalizes canonical GET and drops raw/sensitive credential fields', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      schemaVersion: 1,
      revision: 7,
      pools: [{
        tier: 'haiku',
        name: 'Luna',
        provider: '',
        providerId: 'astrbot-luna',
        baseUrl: 'https://provider.example/v1',
        model: 'gpt-luna',
        enabled: true,
        keys: [{
          id: 'key-1',
          name: 'primary',
          secretRef: 'provider/luna',
          masked: 'sk-••••1234',
          key: 'unit-test-private-value',
          secret: 'unit-test-private-value',
          priority: 1,
          weight: 2,
          enabled: true,
          status: 'active',
        }],
        headers: { Authorization: 'Bearer raw-secret', 'X-Client': 'dududa' },
      }],
    }), { status: 200 }))
    const adapter = new HttpApiKeyPoolsAdapter('', fetchMock)
    const result = await adapter.list()
    const serialized = JSON.stringify(result)

    expect(result.schemaVersion).toBe(1)
    expect(result.revision).toBe(7)
    expect(result.pools).toHaveLength(3)
    expect(result.pools.find((item) => item.tier === 'haiku')?.keys[0]?.masked).toBe('sk-••••1234')
    expect(serialized).not.toContain('unit-test-private-value')
    expect(serialized).not.toContain('Bearer raw-secret')
    expect(result.pools.find((item) => item.tier === 'haiku')?.customHeaders).toEqual([{ name: 'X-Client', value: 'dududa' }])
    expect(result.pools.find((item) => item.tier === 'haiku')?.provider).toBe('')
    expect(fetchMock).toHaveBeenCalledWith('/api/api-keys', expect.objectContaining({ credentials: 'same-origin' }))
  })
})

describe('Explicit Runtime application', () => {
  it('ignores an older status response after a newer refresh', async () => {
    const adapter = new FakeAdapter()
    let finishOld: (value: unknown) => void = () => {}
    const status = { status: 'pending', savedRevision: 1, ready: true, message: '新版等待应用', checkedAt: '', scope: 'dududa_only' }
    const runtimeStatus = vi.fn()
      .mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
      .mockResolvedValue(status)
    Object.assign(adapter, { runtimeStatus })
    const wrapper = mount(ApiKeyPoolsView, { props: { adapter } })
    await flushPromises()
    await wrapper.get('button[aria-label="刷新 API Key 池"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('新版等待应用')
    finishOld({ ...status, status: 'applied', message: '过期响应显示已应用' })
    await flushPromises()
    expect(wrapper.text()).toContain('新版等待应用')
    expect(wrapper.text()).not.toContain('过期响应显示已应用')
    wrapper.unmount()
  })

  it('sends only the saved revision and shows actual apply success', async () => {
    const adapter = new FakeAdapter()
    const status = { status: 'pending' as const, savedRevision: 1, ready: true, message: '已保存，尚未应用', checkedAt: '', scope: 'dududa_only' as const }
    const runtimeStatus = vi.fn(async () => status)
    const applyRuntime = vi.fn(async () => ({ ...status, status: 'applied' as const, message: '已应用到当前 Dududa Runtime' }))
    Object.assign(adapter, { runtimeStatus, applyRuntime })
    const wrapper = mount(ApiKeyPoolsView, { props: { adapter } })
    await flushPromises()
    expect(wrapper.text()).toContain('已保存，尚未应用')
    await wrapper.get('.runtime-apply button').trigger('click')
    await flushPromises()
    expect(applyRuntime).toHaveBeenCalledExactlyOnceWith(1)
    expect(wrapper.text()).toContain('已应用到当前 Dududa Runtime')
    expect(wrapper.text()).toContain('其他 AstrBot 插件保持原配置直到冷重启')
    wrapper.unmount()
  })

  it('prevents duplicate application while pending and displays failure without claiming success', async () => {
    const adapter = new FakeAdapter()
    let reject: (error: Error) => void = () => {}
    const applyRuntime = vi.fn(() => new Promise((_resolve, fail) => { reject = fail }))
    Object.assign(adapter, { applyRuntime })
    const wrapper = mount(ApiKeyPoolsView, { props: { adapter } })
    await flushPromises()
    await wrapper.get('.runtime-apply button').trigger('click')
    expect(wrapper.get('.runtime-apply button').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('正在验证并应用三档配置')
    reject(new Error('Runtime 正在处理请求，请稍后重试'))
    await flushPromises()
    expect(wrapper.text()).toContain('Runtime 正在处理请求，请稍后重试')
    expect(wrapper.text()).not.toContain('已应用到 Dududa Runtime；')
    wrapper.unmount()
  })
})

describe('AccountRail API Key route', () => {
  const account = {
    id: 'qq-123456789',
    botId: '123456789',
    name: '测试账号',
    shortName: '测试账号',
    avatar: '',
    status: 'online' as const,
    unread: 0,
    role: 'bot' as const,
    accent: 'cyan' as const,
  } satisfies Account

  it('provides an accessible desktop and mobile Key Pool navigation item', async () => {
    const wrapper = mount(AccountRail, {
      props: {
        accounts: [account],
        selectedAccountId: 'all',
        totalUnread: 0,
        mobilePanel: 'inbox',
        theme: 'light',
        agentActive: false,
        activeRoute: 'api-keys',
        notificationCount: 0,
      },
    })
    const desktop = wrapper.get('button[aria-label="API Key 池"]')
    expect(desktop.classes()).toContain('active')
    expect(desktop.attributes('aria-current')).toBe('page')
    await desktop.trigger('click')
    expect(wrapper.findAll('.mobile-nav button').some((button) => button.text().includes('Key 池'))).toBe(true)
    expect(wrapper.findAll('.mobile-nav button').find((button) => button.text().includes('Key 池'))?.attributes('aria-current')).toBe('page')
    expect(wrapper.emitted('navigate')?.[0]).toEqual(['api-keys'])
    expect(wrapper.find('.mobile-nav button').exists()).toBe(true)
  })
})
