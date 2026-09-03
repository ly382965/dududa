import { describe, expect, it, vi } from 'vitest'

import { createHttpApiKeyProbe } from './provider-probe'
import type { ApiKeyProbeContext } from './model-keys'

function context(overrides: Partial<ApiKeyProbeContext> = {}): ApiKeyProbeContext {
  return {
    tier: 'haiku',
    pool: {
      tier: 'haiku',
      displayName: 'Luna',
      provider: 'test',
      baseUrl: 'https://provider.example/v1',
      model: 'luna-test',
      protocol: 'openai_chat_completions',
      reasoningEffort: 'low',
      timeoutMs: 10_000,
      maxOutputTokens: 128,
      enabled: true,
      schedulingMode: 'round_robin',
      customHeaders: [{ name: 'X-Client-Name', value: 'dududa-test' }],
      revision: 1,
      updatedAt: new Date().toISOString(),
      keys: [],
    },
    key: {
      id: 'haiku-test',
      name: 'test',
      secretRef: 'provider/luna',
      masked: 'sk-••••1234',
      priority: 0,
      weight: 1,
      enabled: true,
      status: 'active',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    },
    secret: 'sk-test-secret-value',
    signal: new AbortController().signal,
    ...overrides,
  }
}

describe('HTTP API Key provider probe', () => {
  it('uses the configured OpenAI Chat Completions endpoint and never returns the key', async () => {
    const fetchImpl = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      expect(String(input)).toBe('https://provider.example/v1/chat/completions')
      const headers = new Headers(init?.headers)
      expect(headers.get('Authorization')).toBe('Bearer sk-test-secret-value')
      expect(headers.get('X-Client-Name')).toBe('dududa-test')
      expect(JSON.parse(String(init?.body))).toMatchObject({ model: 'luna-test', max_tokens: 8 })
      return new Response('{}', { status: 200 })
    })
    const result = await createHttpApiKeyProbe(fetchImpl as typeof fetch)(context())
    expect(result).toMatchObject({ ok: true, status: 'ok', model: 'luna-test' })
    expect(JSON.stringify(result)).not.toContain('sk-test-secret-value')
  })

  it('supports Responses and Anthropic protocol paths and reports only status on failure', async () => {
    const calls: Array<{ url: string; authorization?: string | null; apiKey?: string | null }> = []
    const fetchImpl = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const headers = new Headers(init?.headers)
      calls.push({ url: String(input), authorization: headers.get('Authorization'), apiKey: headers.get('x-api-key') })
      return new Response('upstream body contains sk-test-secret-value', { status: 401 })
    })
    const probe = createHttpApiKeyProbe(fetchImpl as typeof fetch)
    const responses = await probe(context({ pool: { ...context().pool, protocol: 'openai_responses' } }))
    const anthropic = await probe(context({ pool: { ...context().pool, protocol: 'anthropic_messages' } }))
    expect(responses).toMatchObject({ ok: false, status: 'error', message: 'Provider 返回 HTTP 401' })
    expect(anthropic).toMatchObject({ ok: false, status: 'error', message: 'Provider 返回 HTTP 401' })
    expect(calls.map((item) => item.url)).toEqual([
      'https://provider.example/v1/responses',
      'https://provider.example/v1/messages',
    ])
    expect(calls[0]?.authorization).toBe('Bearer sk-test-secret-value')
    expect(calls[1]?.apiKey).toBe('sk-test-secret-value')
    expect(JSON.stringify([responses, anthropic])).not.toContain('sk-test-secret-value')
  })

  it('does not follow redirects and rejects unsupported protocols without a request', async () => {
    const fetchImpl = vi.fn()
    const probe = createHttpApiKeyProbe(fetchImpl as typeof fetch)
    const unsupported = await probe(context({ pool: { ...context().pool, protocol: 'custom' } }))
    expect(unsupported).toMatchObject({ ok: false, status: 'error' })
    expect(fetchImpl).not.toHaveBeenCalled()
  })
})
