import type { AddressInfo } from 'node:net'
import { describe, expect, it, vi } from 'vitest'
import { HttpRuntimeConfigClient, projectRuntimeConfigStatus } from './runtime-config'
import { createDududaServer } from './app'
import { OneBotHub } from './onebot-hub'
import type { ApiKeyPoolClient } from './model-keys'

const rawStatus = { status: 'applied', savedRevision: 7, ready: true,
  reason: 'runtime_configuration_current', checkedAt: '2026-09-04T00:00:00Z' }

describe('Runtime configuration application', () => {
  it('uses the fixed plugin-scope host path and revision-only body; projects away secrets', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok', data: {
      ...rawStatus, secret: 'synthetic-private-key', command: '/arbitrary',
    } }), { status: 200 }))
    const client = new HttpRuntimeConfigClient('http://host.invalid/api/v1', () => 'synthetic-host-token', fetcher)
    const result = await client.apply(7)
    expect(result.status).toBe('applied')
    expect(JSON.stringify(result)).not.toContain('synthetic')
    expect(fetcher).toHaveBeenCalledWith('http://host.invalid/api/v1/plugins/extensions/astrbot_plugin_dududa_core/runtime/configuration/apply',
      expect.objectContaining({ method: 'POST', body: '{"revision":7}', headers: expect.objectContaining({ 'X-API-Key': 'synthetic-host-token' }) }))
  })

  it('does not echo upstream errors and reports authentication/busy failures', async () => {
    for (const [status, message, expected] of [[401, 'synthetic-secret', '认证失败'],
      [409, 'runtime_requests_active', '正在处理请求'], [500, 'synthetic-secret', '请求失败']] as const) {
      const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'error', message }), { status }))
      const client = new HttpRuntimeConfigClient('http://host.invalid', 'token', fetcher)
      await expect(client.apply(7)).rejects.toThrow(expected)
      await expect(new HttpRuntimeConfigClient('http://host.invalid', '', fetcher).status()).rejects.toThrow('认证未配置')
    }
  })

  it('only accepts same-origin revision intent and rejects stale or credential bodies', async () => {
    const hub = new OneBotHub({ token: 'test-only-token' })
    const runtimeConfig = { status: vi.fn(async () => projectRuntimeConfigStatus(rawStatus)),
      apply: vi.fn(async () => projectRuntimeConfigStatus(rawStatus)) }
    const server = createDududaServer({ hub, publicDir: '/tmp/dududa-test-no-static', runtimeConfig,
      apiKeyPool: { list: async () => ({ schemaVersion: 1, revision: 7, pools: [] }) } as unknown as ApiKeyPoolClient })
    await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
    const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
    try {
      const apply = (body: unknown, source = origin) => fetch(`${origin}/api/api-keys/runtime/apply`, {
        method: 'POST', headers: { Origin: source, 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
      expect((await apply({ revision: 7 }, 'https://evil.invalid')).status).toBe(403)
      expect((await apply({ revision: 7, secret: 'synthetic' })).status).toBe(400)
      expect((await apply({ revision: 6 })).status).toBe(409)
      expect(runtimeConfig.apply).not.toHaveBeenCalled()
      expect((await apply({ revision: 7 })).status).toBe(200)
      expect(runtimeConfig.apply).toHaveBeenCalledExactlyOnceWith(7)
      expect((await fetch(`${origin}/api/api-keys/runtime`)).status).toBe(200)
    } finally {
      hub.close()
      server.closeAllConnections()
      await new Promise<void>(resolve => server.close(() => resolve()))
    }
  })
})
