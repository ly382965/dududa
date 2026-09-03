import { chmod, mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { randomUUID } from 'node:crypto'

import { afterEach, describe, expect, it } from 'vitest'

import {
  API_KEY_TIERS,
  FileApiKeyPoolStore,
  ApiKeyPoolError,
  maskApiKey,
} from './model-keys'

const roots: string[] = []

async function temporaryStore(options: ConstructorParameters<typeof FileApiKeyPoolStore>[0] = {}) {
  const root = await mkdtemp(join(tmpdir(), 'dududa-api-keys-'))
  roots.push(root)
  const path = join(root, 'credentials.json')
  const store = new FileApiKeyPoolStore(typeof options === 'string' ? options : { path, ...options })
  return { root, path, store }
}

afterEach(async () => {
  while (roots.length) await rm(roots.pop()!, { recursive: true, force: true })
})

describe('FileApiKeyPoolStore', () => {
  it('projects all three independent pools without a credential field', async () => {
    const { store } = await temporaryStore()
    const snapshot = await store.list()
    expect(snapshot.schemaVersion).toBe(1)
    expect(snapshot.pools.map((pool) => pool.tier)).toEqual([...API_KEY_TIERS])
    expect(snapshot.pools.map((pool) => pool.providerId)).toEqual(['astrbot-luna', 'astrbot-terra', 'astrbot-sol'])
    for (const pool of snapshot.pools) {
      expect(pool.keys).toEqual([])
      expect(Object.prototype.hasOwnProperty.call(pool, 'secret')).toBe(false)
      expect(Object.prototype.hasOwnProperty.call(pool, 'apiKey')).toBe(false)
    }
  })

  it('persists a key atomically with mode 0600 and masks every public projection', async () => {
    const { store, path } = await temporaryStore()
    const secret = `runtime-${randomUUID()}`
    const created = await store.createKey('haiku', { name: 'primary', secret })
    expect(created.key).toBeDefined()
    expect(JSON.stringify(created)).not.toContain(secret)
    expect(created.key?.masked).toBe(maskApiKey(secret))
    expect(created.key?.secretRef).toContain('haiku')

    const mode = (await stat(path)).mode & 0o777
    expect(mode).toBe(0o600)
    const persisted = await readFile(path, 'utf8')
    expect(persisted).toContain(secret)
    expect(JSON.stringify(await store.list())).not.toContain(secret)

    const reloaded = new FileApiKeyPoolStore(path)
    const snapshot = await reloaded.list()
    expect(snapshot.pools.find((pool) => pool.tier === 'haiku')?.keys[0]?.masked).toBe(maskApiKey(secret))
    expect(snapshot.pools.find((pool) => pool.tier === 'sonnet')?.keys).toEqual([])
  })

  it('keeps an existing secret for omitted and blank rotations', async () => {
    const { store } = await temporaryStore()
    const secret = `rotate-${randomUUID()}`
    const created = await store.createKey('sonnet', { name: 'terra', secret })
    const keyId = created.key!.id
    const revision = created.pool!.revision

    const omitted = await store.updateKey('sonnet', keyId, { name: 'renamed', revision })
    expect(omitted.key?.masked).toBe(maskApiKey(secret))
    const blank = await store.updateKey('sonnet', keyId, { secret: '   ' })
    expect(blank.key?.masked).toBe(maskApiKey(secret))
    await expect(store.createKey('sonnet', { name: 'invalid', secret: '' })).rejects.toMatchObject({ status: 400 })
  })

  it('retains SecretRef-only entries when reloading a deployment snapshot', async () => {
    const { path } = await temporaryStore()
    await writeFile(path, JSON.stringify({
      schemaVersion: 1,
      revision: 4,
      pools: {
        haiku: {
          tier: 'haiku',
          keys: [{ id: 'haiku-env', name: 'environment', secretRef: 'provider/luna', enabled: true, status: 'active' }],
        },
      },
    }), { mode: 0o600 })
    const store = new FileApiKeyPoolStore(path)
    const key = (await store.list()).pools.find((pool) => pool.tier === 'haiku')?.keys[0]
    expect(key).toMatchObject({ id: 'haiku-env', secretRef: 'provider/luna', masked: '', enabled: true })
  })

  it('isolates tier CRUD and supports disable versus remove', async () => {
    const { store } = await temporaryStore()
    const haiku = await store.createKey('haiku', { secret: `h-${randomUUID()}` })
    const sonnet = await store.createKey('sonnet', { secret: `s-${randomUUID()}` })
    await store.deleteKey('haiku', haiku.key!.id, 'disable')
    const afterDisable = await store.list()
    expect(afterDisable.pools.find((pool) => pool.tier === 'haiku')?.keys[0]).toMatchObject({
      id: haiku.key!.id,
      enabled: false,
      status: 'disabled',
    })
    expect(afterDisable.pools.find((pool) => pool.tier === 'sonnet')?.keys[0]?.id).toBe(sonnet.key!.id)
    await store.deleteKey('sonnet', sonnet.key!.id)
    expect((await store.list()).pools.find((pool) => pool.tier === 'sonnet')?.keys).toEqual([])
  })

  it('rejects stale revisions and invalid metadata without leaking input values', async () => {
    const { store } = await temporaryStore()
    await expect(store.updatePool('haiku', { baseUrl: 'not-a-url' })).rejects.toMatchObject({ status: 400 })
    await expect(store.updatePool('haiku', { baseUrl: 'https:provider.example/v1' })).rejects.toMatchObject({ status: 400 })
    await expect(store.updatePool('haiku', { baseUrl: 'https:///provider.example/v1' })).rejects.toMatchObject({ status: 400 })
    await expect(store.updatePool('haiku', { revision: 999, displayName: 'stale' })).rejects.toMatchObject({ status: 409 })
    await expect(store.createKey('opus', { secret: `ok-${randomUUID()}`, weight: 0 })).rejects.toMatchObject({ status: 400 })
    await expect(store.updatePool('opus', { timeoutMs: 900_001 })).rejects.toMatchObject({ status: 400 })
    await expect(store.updatePool('haiku', { providerId: 'invalid provider id' })).rejects.toMatchObject({ status: 400 })
    await expect(store.updatePool('haiku', { protocol: 'openai_responses' })).rejects.toMatchObject({ status: 400 })
    await expect(store.updatePool('haiku', { providerId: 'astrbot-terra' })).rejects.toMatchObject({ status: 400 })
    await expect(store.getPool('bad' as never)).rejects.toBeInstanceOf(ApiKeyPoolError)
  })

  it('rejects a future persisted schema instead of rewriting it as version one', async () => {
    const { path } = await temporaryStore()
    await writeFile(path, JSON.stringify({ schemaVersion: 2, revision: 1, pools: {} }), { mode: 0o600 })

    await expect(new FileApiKeyPoolStore(path).list()).rejects.toMatchObject({ status: 500 })
  })

  it('rejects a persisted store with group or other permissions before reading it', async () => {
    const { path } = await temporaryStore()
    await writeFile(path, JSON.stringify({ schemaVersion: 1, revision: 1, pools: {} }), { mode: 0o600 })
    await chmod(path, 0o640)

    await expect(new FileApiKeyPoolStore(path).list()).rejects.toMatchObject({ status: 500 })
  })

  it.each([
    ['pools', { schemaVersion: 1, revision: 1, pools: 'invalid' }],
    ['pool', { schemaVersion: 1, revision: 1, pools: { haiku: [] } }],
    ['keys', { schemaVersion: 1, revision: 1, pools: { haiku: { keys: { retained: true } } } }],
    ['key entry', { schemaVersion: 1, revision: 1, pools: { haiku: { keys: ['invalid'] } } }],
    ['Base URL', { schemaVersion: 1, revision: 1, pools: { haiku: { baseUrl: 'https://provider.example/v1?private=value' } } }],
    ['noncanonical Base URL', { schemaVersion: 1, revision: 1, pools: { haiku: { baseUrl: 'https:provider.example/v1' } } }],
    ['empty-authority Base URL', { schemaVersion: 1, revision: 1, pools: { haiku: { baseUrl: 'https:///provider.example/v1' } } }],
    ['numeric field', { schemaVersion: 1, revision: 1, pools: { haiku: { timeoutMs: '120000' } } }],
    ['headers', { schemaVersion: 1, revision: 1, pools: { haiku: { customHeaders: 'invalid' } } }],
    ['root revision', { schemaVersion: 1, revision: 'invalid', pools: {} }],
    ['declared tier', { schemaVersion: 1, revision: 1, pools: { haiku: { tier: 42 } } }],
  ])('rejects malformed persisted %s data without rewriting the file', async (_label, document) => {
    const { path } = await temporaryStore()
    const serialized = JSON.stringify(document)
    await writeFile(path, serialized, { mode: 0o600 })

    await expect(new FileApiKeyPoolStore(path).list()).rejects.toMatchObject({ status: 500 })
    expect(await readFile(path, 'utf8')).toBe(serialized)
  })

  it('enforces the shared store-size ceiling before reads and writes', async () => {
    const oversized = await temporaryStore({ maxStoreBytes: 1_024 })
    await writeFile(oversized.path, ' '.repeat(1_025), { mode: 0o600 })
    await expect(oversized.store.list()).rejects.toMatchObject({ status: 500 })

    const writable = await temporaryStore({ maxStoreBytes: 4_096 })
    const before = await writable.store.list()
    await expect(writable.store.createKey('haiku', {
      name: 'too large',
      secret: 'x'.repeat(4_096),
    })).rejects.toMatchObject({ status: 413 })
    expect(await writable.store.list()).toEqual(before)
    await expect(stat(writable.path)).rejects.toMatchObject({ code: 'ENOENT' })
  })

  it('rolls back memory and revision when an atomic persistence attempt fails', async () => {
    const { path, store } = await temporaryStore()
    await store.updatePool('haiku', { provider: 'before-failure' })
    const before = await store.list()
    const internals = store as unknown as { persist: () => Promise<void> }
    internals.persist = async () => {
      throw new ApiKeyPoolError('synthetic persistence failure', 500)
    }

    await expect(store.updatePool('haiku', { provider: 'must-not-stick' })).rejects.toMatchObject({ status: 500 })
    expect(await store.list()).toEqual(before)
    expect(await new FileApiKeyPoolStore(path).list()).toEqual(before)
  })

  it('keeps deterministic Provider and Source bindings across partial updates', async () => {
    const { store } = await temporaryStore()
    const initial = (await store.list()).pools.find((pool) => pool.tier === 'haiku')!
    const omitted = await store.updatePool('haiku', { displayName: 'Luna renamed' })
    expect(omitted.pool).toMatchObject({ providerId: initial.providerId, sourceId: initial.sourceId })
    const cleared = await store.updatePool('haiku', { providerId: '', sourceId: '' })
    expect(cleared.pool).toMatchObject({ providerId: 'astrbot-luna', sourceId: 'dududa-haiku-source' })
  })

  it('rejects control characters in custom header values', async () => {
    const { store } = await temporaryStore()
    await expect(store.updatePool('haiku', {
      customHeaders: [{ name: 'X-Client-Name', value: 'dududa\r\nX-Injected: true' }],
    })).rejects.toMatchObject({ status: 400 })
  })

  it('rejects credential-shaped custom header names', async () => {
    const { store } = await temporaryStore()
    await expect(store.updatePool('haiku', {
      customHeaders: [{ name: 'X-Provider-Credential', value: 'not-a-secret' }],
    })).rejects.toMatchObject({ status: 400 })
  })

  it('bounds provider probes, records health metadata and sanitizes probe messages', async () => {
    const secret = `probe-${randomUUID()}`
    const { store } = await temporaryStore({
      maxProbeMs: 30,
      probe: ({ secret: received }) => ({ ok: true, status: 'ok', message: `ok ${received}`, latencyMs: 7 }),
    })
    const created = await store.createKey('opus', { secret })
    await store.updatePool('opus', {
      enabled: true,
      baseUrl: 'https://provider.example/v1',
      model: 'probe-model',
      revision: created.pool!.revision,
    })
    const result = await store.testPool('opus', created.key!.id)
    expect(result).toMatchObject({ status: 'ok', latencyMs: 7 })
    expect(result.revision).toBeGreaterThan(created.pool!.revision)
    expect(result.message).not.toContain(secret)
    expect((await store.list()).pools.find((pool) => pool.tier === 'opus')?.keys[0]).toMatchObject({
      status: 'active',
      lastCheckedAt: result.checkedAt,
      lastSuccessAt: result.checkedAt,
    })

    const timeoutStore = await temporaryStore({
      maxProbeMs: 20,
      probe: async () => new Promise(() => undefined),
    }).then(({ store: value }) => value)
    const timeoutKey = await timeoutStore.createKey('haiku', { secret: `timeout-${randomUUID()}` })
    await timeoutStore.updatePool('haiku', {
      enabled: true,
      baseUrl: 'https://provider.example/v1',
      model: 'timeout-model',
      revision: timeoutKey.pool!.revision,
    })
    const started = Date.now()
    const timeout = await timeoutStore.testPool('haiku')
    expect(timeout.status).toBe('error')
    expect(Date.now() - started).toBeLessThan(500)
  })
})
