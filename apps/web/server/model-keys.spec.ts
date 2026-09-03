import { mkdtemp, readFile, rm, stat } from 'node:fs/promises'
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
    await expect(store.updatePool('haiku', { revision: 999, displayName: 'stale' })).rejects.toMatchObject({ status: 409 })
    await expect(store.createKey('opus', { secret: `ok-${randomUUID()}`, weight: 0 })).rejects.toMatchObject({ status: 400 })
    await expect(store.getPool('bad' as never)).rejects.toBeInstanceOf(ApiKeyPoolError)
  })

  it('bounds provider probes, records health metadata and sanitizes probe messages', async () => {
    const secret = `probe-${randomUUID()}`
    const { store } = await temporaryStore({
      maxProbeMs: 30,
      probe: ({ secret: received }) => ({ ok: true, status: 'ok', message: `ok ${received}`, latencyMs: 7 }),
    })
    const created = await store.createKey('opus', { secret })
    const result = await store.testPool('opus', created.key!.id)
    expect(result).toMatchObject({ status: 'ok', latencyMs: 7 })
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
    await timeoutStore.createKey('haiku', { secret: `timeout-${randomUUID()}` })
    const started = Date.now()
    const timeout = await timeoutStore.testPool('haiku')
    expect(timeout.status).toBe('error')
    expect(Date.now() - started).toBeLessThan(500)
  })
})
