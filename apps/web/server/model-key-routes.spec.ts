import type { AddressInfo } from 'node:net'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { randomUUID } from 'node:crypto'

import { afterEach, describe, expect, it } from 'vitest'

import { createDududaServer } from './app'
import { FileApiKeyPoolStore, sanitizeApiKeySnapshot } from './model-keys'
import { OneBotHub } from './onebot-hub'

const token = `route-test-${randomUUID()}`
const resources: Array<{ server: ReturnType<typeof createDududaServer>; root: string }> = []

async function start() {
  const root = await mkdtemp(join(tmpdir(), 'dududa-api-key-route-'))
  const store = new FileApiKeyPoolStore(join(root, 'credentials.json'))
  const hub = new OneBotHub({ token, actionTimeoutMs: 500 })
  const server = createDududaServer({ hub, publicDir: root, apiKeyPool: store })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const port = (server.address() as AddressInfo).port
  const baseUrl = `http://127.0.0.1:${port}`
  resources.push({ server, root })
  return { server, root, baseUrl }
}

async function closeAll() {
  while (resources.length) {
    const resource = resources.pop()!
    await new Promise<void>((resolve) => resource.server.close(() => resolve()))
    await rm(resource.root, { recursive: true, force: true })
  }
}

afterEach(closeAll)

describe('API Key pool HTTP boundary', () => {
  it('lists all tiers, enforces same-origin writes and never returns the raw secret', async () => {
    const { baseUrl } = await start()
    const listed = await fetch(`${baseUrl}/api/api-keys`)
    expect(listed.status).toBe(200)
    const initial = await listed.json() as { schemaVersion: number; revision: number; pools: Array<{ tier: string; keys: unknown[] }> }
    expect(initial.schemaVersion).toBe(1)
    expect(initial.pools.map((pool) => pool.tier)).toEqual(['haiku', 'sonnet', 'opus'])

    const secret = `route-${randomUUID()}`
    const payload = JSON.stringify({ name: 'route key', secret })
    const denied = await fetch(`${baseUrl}/api/api-keys/pools/haiku/keys`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: 'https://attacker.invalid' },
      body: payload,
    })
    expect(denied.status).toBe(403)
    expect(await denied.text()).not.toContain(secret)

    const createdResponse = await fetch(`${baseUrl}/api/api-keys/pools/haiku/keys`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: payload,
    })
    expect(createdResponse.status).toBe(201)
    const created = await createdResponse.json() as { key: { id: string; masked: string }; pool: { revision: number } }
    expect(created.key.masked).not.toContain(secret)
    expect(JSON.stringify(created)).not.toContain(secret)

    const after = await (await fetch(`${baseUrl}/api/api-keys`)).json() as { pools: Array<{ tier: string; keys: unknown[] }> }
    expect(after.pools.find((pool) => pool.tier === 'haiku')?.keys).toHaveLength(1)
    expect(JSON.stringify(after)).not.toContain(secret)
  })

  it('updates pool/key metadata, preserves blank rotations, and supports disable/remove', async () => {
    const { baseUrl } = await start()
    const originHeaders = { 'Content-Type': 'application/json', Origin: baseUrl }
    const secret = `metadata-${randomUUID()}`
    const created = await (await fetch(`${baseUrl}/api/api-keys/pools/sonnet/keys`, {
      method: 'POST', headers: originHeaders, body: JSON.stringify({ name: 'terra', secret }),
    })).json() as { key: { id: string; masked: string }; pool: { revision: number } }

    const poolUpdate = await fetch(`${baseUrl}/api/api-keys/pools/sonnet`, {
      method: 'PUT',
      headers: originHeaders,
      body: JSON.stringify({
        displayName: 'Terra custom', provider: 'test-provider', baseUrl: 'https://provider.example/v1',
        model: 'model-terra', protocol: 'openai_chat_completions', reasoningEffort: 'medium',
        timeoutMs: 20_000, maxOutputTokens: 4_096, enabled: true, schedulingMode: 'priority',
        customHeaders: [{ name: 'X-Client-Name', value: 'dududa-test' }], revision: created.pool.revision,
      }),
    })
    expect(poolUpdate.status).toBe(200)
    const updatedPool = await poolUpdate.json() as { pool: { revision: number; provider: string; keys: unknown[] } }
    expect(updatedPool.pool.provider).toBe('test-provider')
    expect(updatedPool.pool.keys).toHaveLength(1)

    const keyUpdate = await fetch(`${baseUrl}/api/api-keys/pools/sonnet/keys/${encodeURIComponent(created.key.id)}`, {
      method: 'PUT', headers: originHeaders, body: JSON.stringify({ name: 'terra renamed', secret: '' }),
    })
    expect(keyUpdate.status).toBe(200)
    const updatedKey = await keyUpdate.json() as { key: { name: string; masked: string } }
    expect(updatedKey.key.name).toBe('terra renamed')
    expect(updatedKey.key.masked).toBe(created.key.masked)
    expect(JSON.stringify(updatedKey)).not.toContain(secret)

    const disabled = await fetch(`${baseUrl}/api/api-keys/pools/sonnet/keys/${encodeURIComponent(created.key.id)}`, {
      method: 'DELETE', headers: originHeaders, body: JSON.stringify({ disable: true }),
    })
    expect(disabled.status).toBe(200)
    expect((await disabled.json() as { key: { enabled: boolean; status: string } }).key).toMatchObject({ enabled: false, status: 'disabled' })
    const removed = await fetch(`${baseUrl}/api/api-keys/pools/sonnet/keys/${encodeURIComponent(created.key.id)}`, {
      method: 'DELETE', headers: originHeaders,
    })
    expect(removed.status).toBe(200)
    expect((await (await fetch(`${baseUrl}/api/api-keys`)).json() as { pools: Array<{ tier: string; keys: unknown[] }> }).pools.find((pool) => pool.tier === 'sonnet')?.keys).toEqual([])
  })

  it('does not pass credential-shaped fields through the pool metadata route', async () => {
    const { baseUrl } = await start()
    const response = await fetch(`${baseUrl}/api/api-keys/pools/haiku`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ secret: `pool-secret-${randomUUID()}`, keys: [] }),
    })
    expect(response.status).toBe(400)
  })

  it('returns bounded, sanitized probe results and rejects invalid tiers', async () => {
    const { baseUrl } = await start()
    const origin = { 'Content-Type': 'application/json', Origin: baseUrl }
    const invalid = await fetch(`${baseUrl}/api/api-keys/pools/not-a-tier/keys`, {
      method: 'POST', headers: origin, body: JSON.stringify({ secret: `invalid-${randomUUID()}` }),
    })
    expect(invalid.status).toBe(400)
    expect((await invalid.json() as { error: string }).error).toContain('tier')

    const test = await fetch(`${baseUrl}/api/api-keys/pools/opus/test`, {
      method: 'POST', headers: origin, body: JSON.stringify({}),
    })
    expect(test.status).toBe(200)
    expect(await test.json()).toMatchObject({ status: 'unavailable' })

    const secretProbe = await fetch(`${baseUrl}/api/api-keys/pools/opus/test`, {
      method: 'POST', headers: origin, body: JSON.stringify({ secret: `should-not-${randomUUID()}` }),
    })
    expect(secretProbe.status).toBe(400)
  })

  it('does not expose credential-bearing Base URL query strings from an adapter', () => {
    const snapshot = sanitizeApiKeySnapshot({
      revision: 3,
      pools: [{
        tier: 'haiku',
        baseUrl: 'https://provider.example/v1?api_key=should-not-leak',
        keys: [],
      }],
    })
    const pool = snapshot.pools.find((item) => item.tier === 'haiku')!
    expect(pool.baseUrl).toBe('')
    expect(JSON.stringify(snapshot)).not.toContain('should-not-leak')
  })

  it('fully hides a noncanonical masked value returned by an adapter', () => {
    const marker = 'private-adapter-marker*'
    const snapshot = sanitizeApiKeySnapshot({
      pools: [{ tier: 'haiku', keys: [{ id: 'leaky-mask', masked: marker }] }],
    })
    const key = snapshot.pools.find((item) => item.tier === 'haiku')!.keys[0]
    expect(key.masked).toBe('••••••••')
    expect(JSON.stringify(snapshot)).not.toContain(marker)
  })

  it('does not echo malformed JSON fragments in an error response', async () => {
    const { baseUrl } = await start()
    const marker = `private-json-fragment-${randomUUID()}`
    const response = await fetch(`${baseUrl}/api/api-keys/pools/haiku/keys`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: marker,
    })
    const body = await response.text()
    expect(response.status).toBe(400)
    expect(body).not.toContain(marker)
    expect(body).toContain('请求正文 JSON 无效')
  })
})
