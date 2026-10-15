import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { RecallMediaStore, type RecallMediaScope } from './recall-media'

const DAY = 86_400_000
const SOURCE = 'https://gchat.qpic.cn/message-image?token=private'
const scope: RecallMediaScope = { accountId: 'bot-1', conversationId: 'group-1', messageId: 'group-1:42', slot: '0.url' }

function media(body = 'saved image', mime = 'image/png'): Response {
  return new Response(body, { headers: { 'content-type': mime } })
}

describe('persistent recall media', () => {
  const stores: RecallMediaStore[] = []
  const directories: string[] = []

  function open(options: Partial<ConstructorParameters<typeof RecallMediaStore>[0]> = {}): RecallMediaStore {
    const store = new RecallMediaStore({ path: ':memory:', ...options })
    stores.push(store)
    return store
  }

  function diskPath(): string {
    const directory = mkdtempSync(join(tmpdir(), 'dududa-recall-media-'))
    directories.push(directory)
    return join(directory, 'recall.sqlite')
  }

  afterEach(() => {
    for (const store of stores.splice(0)) store.close()
    for (const directory of directories.splice(0)) rmSync(directory, { recursive: true, force: true })
    vi.useRealTimers()
  })

  it('retains bytes across reopen and isolates account, conversation, message and slot', async () => {
    const path = diskPath()
    const fetchRemote = vi.fn<typeof fetch>().mockImplementation(async () => media())
    const store = open({ path, fetch: fetchRemote, now: () => 100 })
    expect(await store.capture(scope, SOURCE, 100 + 7 * DAY, () => true)).toBe(true)
    expect(await store.capture(scope, 'https://invalid.example', 100 + 7 * DAY, () => true)).toBe(true)
    expect(fetchRemote).toHaveBeenCalledTimes(1)
    store.close()

    const reopened = open({ path, now: () => 101 })
    expect(reopened.has(scope)).toBe(true)
    expect(reopened.get(scope)).toEqual({ body: Buffer.from('saved image'), mime: 'image/png' })
    for (const field of ['accountId', 'conversationId', 'messageId', 'slot']) {
      expect(reopened.get({ ...scope, [field]: 'other' })).toBeUndefined()
      expect(reopened.has({ ...scope, [field]: 'other' })).toBe(false)
    }
  })

  it('rejects non-QQ, credential-bearing and private URLs before fetching', async () => {
    const fetchRemote = vi.fn<typeof fetch>().mockImplementation(async () => media())
    const store = open({ fetch: fetchRemote })
    for (const source of [
      'file:///tmp/image', 'ftp://qq.com/image', 'https://qq.com.evil.example/image',
      'https://user:secret@qq.com/image', 'http://127.0.0.1/image', 'http://10.1.2.3/image',
      'http://[::1]/image', 'http://localhost/image', 'not a URL',
    ]) {
      expect(await store.capture(scope, source, Date.now() + DAY, () => true)).toBe(false)
    }
    expect(fetchRemote).not.toHaveBeenCalled()
  })

  it('follows allowed relative redirects and checks every redirect target', async () => {
    const fetchRemote = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(null, { status: 302, headers: { location: '/next' } }))
      .mockResolvedValueOnce(media())
    const store = open({ fetch: fetchRemote })
    expect(await store.capture(scope, SOURCE, Date.now() + DAY, () => true)).toBe(true)
    expect(String(fetchRemote.mock.calls[1]![0])).toBe('https://gchat.qpic.cn/next')
    expect(fetchRemote.mock.calls.every(([, init]) => init?.redirect === 'manual')).toBe(true)

    for (const location of ['http://192.168.0.1/private', 'https://evil.example/image', 'https://user:secret@qq.com/image']) {
      fetchRemote.mockReset().mockResolvedValue(new Response(null, { status: 302, headers: { location } }))
      const other = { ...scope, messageId: location }
      expect(await store.capture(other, SOURCE, Date.now() + DAY, () => true)).toBe(false)
      expect(fetchRemote).toHaveBeenCalledTimes(1)
    }
  })

  it('bounds redirects to four hops', async () => {
    const fetchRemote = vi.fn<typeof fetch>().mockImplementation(async () => new Response(null, {
      status: 302, headers: { location: '/again' },
    }))
    const store = open({ fetch: fetchRemote })
    expect(await store.capture(scope, SOURCE, Date.now() + DAY, () => true)).toBe(false)
    expect(fetchRemote).toHaveBeenCalledTimes(5)
  })

  it('accepts image, audio, video and generic binary but rejects active document MIME types', async () => {
    const fetchRemote = vi.fn<typeof fetch>()
    const store = open({ fetch: fetchRemote })
    for (const mime of ['image/jpeg', 'audio/ogg', 'video/mp4', 'application/octet-stream']) {
      fetchRemote.mockResolvedValueOnce(media('bytes', mime))
      expect(await store.capture({ ...scope, slot: mime }, SOURCE, Date.now() + DAY, () => true)).toBe(true)
    }
    for (const mime of ['image/svg+xml', 'text/html', 'application/xhtml+xml', 'application/json', '']) {
      fetchRemote.mockResolvedValueOnce(media('document', mime))
      expect(await store.capture({ ...scope, slot: mime }, SOURCE, Date.now() + DAY, () => true)).toBe(false)
    }
  })

  it('enforces the byte limit from both headers and streamed data', async () => {
    const fetchRemote = vi.fn<typeof fetch>()
    const store = open({ fetch: fetchRemote, maxBytes: 4 })
    fetchRemote.mockResolvedValueOnce(new Response('small', { headers: { 'content-type': 'image/png', 'content-length': '100' } }))
    expect(await store.capture(scope, SOURCE, Date.now() + DAY, () => true)).toBe(false)

    fetchRemote.mockResolvedValueOnce(new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array([1, 2, 3]))
        controller.enqueue(new Uint8Array([4, 5]))
        controller.close()
      },
    }), { headers: { 'content-type': 'audio/ogg' } }))
    expect(await store.capture(scope, SOURCE, Date.now() + DAY, () => true)).toBe(false)
    expect(store.has(scope)).toBe(false)

    fetchRemote.mockResolvedValueOnce(media('1234'))
    expect(await store.capture(scope, SOURCE, Date.now() + DAY, () => true)).toBe(true)
  })

  it('keeps the timeout active while a response body is stalled', async () => {
    vi.useFakeTimers()
    const cancel = vi.fn()
    const fetchRemote = vi.fn<typeof fetch>().mockResolvedValue(new Response(new ReadableStream({ cancel }), {
      headers: { 'content-type': 'video/mp4' },
    }))
    const store = open({ fetch: fetchRemote })
    const capture = store.capture(scope, SOURCE, Date.now() + DAY, () => true)
    await vi.advanceTimersByTimeAsync(15_001)
    expect(await capture).toBe(false)
    expect(cancel).toHaveBeenCalled()
    expect(store.has(scope)).toBe(false)
  })

  it('also times out while waiting for response headers', async () => {
    vi.useFakeTimers()
    const fetchRemote = vi.fn<typeof fetch>().mockImplementation(() => new Promise(() => {}))
    const store = open({ fetch: fetchRemote })
    const capture = store.capture(scope, SOURCE, Date.now() + DAY, () => true)
    await vi.advanceTimersByTimeAsync(15_001)
    expect(await capture).toBe(false)
    expect(store.has(scope)).toBe(false)
  })

  it('does not write back after close, disabling, expiration or revoked eligibility', async () => {
    for (const reason of ['close', 'disabled', 'expired', 'ineligible']) {
      const path = diskPath()
      let now = 100
      let allowed = true
      let finish!: (response: Response) => void
      const fetchRemote = vi.fn<typeof fetch>().mockImplementation(() => new Promise((resolve) => { finish = resolve }))
      const store = open({ path, now: () => now, fetch: fetchRemote })
      const capture = store.capture(scope, SOURCE, 200, () => allowed)
      if (reason === 'close') store.close()
      if (reason === 'disabled') {
        store.setSettings(scope.accountId, scope.conversationId, { enabled: false, retentionDays: 7 })
        store.setSettings(scope.accountId, scope.conversationId, { enabled: true, retentionDays: 7 })
      }
      if (reason === 'expired') now = 200
      if (reason === 'ineligible') allowed = false
      finish(media())
      expect(await capture).toBe(false)
      const reopened = open({ path, now: () => 100 })
      expect(reopened.has(scope)).toBe(false)
    }
  })

  it('expires and deletes bytes, and shortens retention from original save time', async () => {
    const path = diskPath()
    let now = 100
    const fetchRemote = vi.fn<typeof fetch>().mockImplementation(async () => media())
    const store = open({ path, now: () => now, fetch: fetchRemote })
    expect(await store.capture(scope, SOURCE, 100 + 7 * DAY, () => true)).toBe(true)
    now += DAY
    store.setSettings(scope.accountId, scope.conversationId, { enabled: true, retentionDays: 2 })
    store.setSettings(scope.accountId, scope.conversationId, { enabled: true, retentionDays: 30 })
    expect(store.has(scope)).toBe(true)
    now = 100 + 2 * DAY
    expect(store.get(scope)).toBeUndefined()
    expect(store.has(scope)).toBe(false)
    store.prune()
    const db = new DatabaseSync(path)
    expect(db.prepare('SELECT COUNT(*) AS total FROM recall_media').get()?.total).toBe(0)
    db.close()
  })

  it('disables only the matching account and conversation and rejects future captures', async () => {
    const fetchRemote = vi.fn<typeof fetch>().mockImplementation(async () => media())
    const store = open({ fetch: fetchRemote })
    const otherAccount = { ...scope, accountId: 'bot-2' }
    const otherConversation = { ...scope, conversationId: 'group-2' }
    for (const target of [scope, otherAccount, otherConversation]) {
      expect(await store.capture(target, SOURCE, Date.now() + DAY, () => true)).toBe(true)
    }
    store.setSettings(scope.accountId, scope.conversationId, { enabled: false, retentionDays: 7 })
    expect(store.has(scope)).toBe(false)
    expect(store.has(otherAccount)).toBe(true)
    expect(store.has(otherConversation)).toBe(true)
    expect(await store.capture(scope, SOURCE, Date.now() + DAY, () => true)).toBe(false)
  })

  it('bounds concurrent downloads and the queue, and clears queued work on close', async () => {
    const fetchRemote = vi.fn<typeof fetch>().mockImplementation(() => new Promise(() => {}))
    const store = open({ fetch: fetchRemote })
    const captures = Array.from({ length: 64 }, (_, index) => store.capture(
      { ...scope, messageId: String(index) }, SOURCE, Date.now() + DAY, () => true,
    ))
    expect(fetchRemote).toHaveBeenCalledTimes(4)
    expect(await store.capture({ ...scope, messageId: 'overflow' }, SOURCE, Date.now() + DAY, () => true)).toBe(false)
    expect(await store.capture({ ...scope, messageId: '0' }, SOURCE, Date.now() + DAY, () => true)).toBe(false)
    store.close()
    expect(await Promise.all(captures)).toEqual(Array(64).fill(false))
  })
})
