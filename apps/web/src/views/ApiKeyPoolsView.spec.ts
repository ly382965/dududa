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
    return { status: 'ok', message: 'Provider 探测成功', latencyMs: 42, model: pool(tier).model }
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
  it('renders three independent tier pools and never exposes a raw key from metadata', async () => {
    const { wrapper } = mountView()
    await flushPromises()

    expect(wrapper.findAll('.pool-card')).toHaveLength(3)
    expect(wrapper.find('[data-tier="haiku"]')?.text()).toContain('Luna')
    expect(wrapper.find('[data-tier="sonnet"]')?.text()).toContain('Terra')
    expect(wrapper.find('[data-tier="opus"]')?.text()).toContain('Sol')
    expect(wrapper.text()).not.toContain('sk-real-secret-value')
    expect(window.localStorage.length).toBe(0)
  })

  it('submits a new secret only on explicit create and clears it from the component immediately', async () => {
    const { wrapper, adapter } = mountView()
    await flushPromises()
    await wrapper.get('[data-tier="haiku"] .add-key').trigger('click')
    const form = wrapper.get('.key-editor form')
    await form.get('input[placeholder="例如主 Key"]').setValue('备用 Luna')
    await form.get('input[type="password"]').setValue('sk-real-secret-value')
    await form.get('input[placeholder="provider/luna-primary"]').setValue('provider/luna-secondary')
    await form.trigger('submit')
    await flushPromises()

    expect(adapter.creates).toHaveLength(1)
    expect(adapter.creates[0]?.request.secret).toBe('sk-real-secret-value')
    expect(wrapper.find('.key-editor').exists()).toBe(false)
    expect(wrapper.text()).toContain('备用 Luna')
    expect(wrapper.text()).not.toContain('sk-real-secret-value')
    expect(wrapper.html()).not.toContain('sk-real-secret-value')
    expect(window.localStorage.length).toBe(0)
  })

  it('rotates an existing key without requiring or rendering the previous value', async () => {
    const { wrapper, adapter } = mountView()
    await flushPromises()
    await wrapper.get('[data-tier="sonnet"] .key-row button[aria-label="编辑 sonnet-primary"]').trigger('click')
    const form = wrapper.get('.key-editor form')
    expect(form.get('input[type="password"]').attributes('placeholder')).toContain('留空保持现有密钥')
    await form.get('input[type="password"]').setValue('sk-rotated-secret-value')
    await form.trigger('submit')
    await flushPromises()

    expect(adapter.updates[0]?.request.secret).toBe('sk-rotated-secret-value')
    expect(wrapper.find('.key-editor').exists()).toBe(false)
    expect(wrapper.html()).not.toContain('sk-rotated-secret-value')
  })

  it('edits pool metadata, probes a pool, toggles a key, and removes it', async () => {
    const { wrapper, adapter } = mountView()
    await flushPromises()
    const card = wrapper.get('[data-tier="opus"]')
    await card.get('button').trigger('click')
    await flushPromises()
    expect(adapter.tests).toEqual(['opus'])
    expect(wrapper.text()).toContain('Provider 探测成功')

    await card.get('button[aria-label="编辑 Sol · 深度推理 池"]').trigger('click')
    const poolForm = wrapper.get('.pool-editor form')
    await poolForm.get('input[placeholder="例如 OpenAI-compatible"]').setValue('New Provider')
    await poolForm.trigger('submit')
    await flushPromises()
    expect(adapter.poolUpdates[0]?.request.provider).toBe('New Provider')

    const keyRow = wrapper.get('[data-tier="opus"] .key-row')
    await keyRow.get('button[aria-label="停用 opus-primary"]').trigger('click')
    await flushPromises()
    expect(adapter.updates.some((item) => item.keyId === 'opus-primary' && item.request.enabled === false)).toBe(true)
    await keyRow.get('button[aria-label="移除 opus-primary"]').trigger('click')
    await keyRow.get('button[aria-label="移除 opus-primary"]').trigger('click')
    await flushPromises()
    expect(adapter.removals).toEqual([{ tier: 'opus', keyId: 'opus-primary' }])
  })
})

describe('ApiKeyPoolsAdapter', () => {
  it('normalizes canonical GET and drops raw/sensitive credential fields', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      schemaVersion: 1,
      revision: 7,
      pools: [{
        tier: 'haiku',
        name: 'Luna',
        provider: 'Provider A',
        baseUrl: 'https://provider.example/v1',
        model: 'gpt-luna',
        enabled: true,
        keys: [{
          id: 'key-1',
          name: 'primary',
          secretRef: 'provider/luna',
          masked: 'sk-••••1234',
          key: 'sk-real-secret-value',
          secret: 'sk-real-secret-value',
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
    expect(serialized).not.toContain('sk-real-secret-value')
    expect(serialized).not.toContain('Bearer raw-secret')
    expect(result.pools.find((item) => item.tier === 'haiku')?.customHeaders).toEqual([{ name: 'X-Client', value: 'dududa' }])
    expect(fetchMock).toHaveBeenCalledWith('/api/api-keys', expect.objectContaining({ credentials: 'same-origin' }))
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
    await desktop.trigger('click')
    expect(wrapper.findAll('.mobile-nav button').some((button) => button.text().includes('Key 池'))).toBe(true)
    expect(wrapper.emitted('navigate')?.[0]).toEqual(['api-keys'])
    expect(wrapper.find('.mobile-nav button').exists()).toBe(true)
  })
})
