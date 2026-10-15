import { mkdirSync } from 'node:fs'
import { dirname } from 'node:path'
import { DatabaseSync } from 'node:sqlite'

export interface RecallMediaScope {
  accountId: string
  conversationId: string
  messageId: string
  slot: string
}

interface MediaSettings {
  enabled: boolean
  retentionDays: number
}

interface CaptureJob {
  scope: RecallMediaScope
  sourceUrl: string
  expiresAt: number
  stillAllowed: () => boolean
  resolve: (saved: boolean) => void
  key: string
}

const DAY_MS = 86_400_000
const DOWNLOAD_TIMEOUT_MS = 15_000
const MAX_CONCURRENT = 4
const MAX_PENDING = 64
const QQ_HOSTS = ['qq.com', 'qq.com.cn', 'qpic.cn', 'gtimg.cn', 'qlogo.cn']

function allowedUrl(source: string): URL | undefined {
  try {
    const url = new URL(source)
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return undefined
    if (!QQ_HOSTS.some((host) => url.hostname === host || url.hostname.endsWith(`.${host}`))) return undefined
    return url
  } catch {
    return undefined
  }
}

function scopeArgs(scope: RecallMediaScope): [string, string, string, string] {
  return [scope.accountId, scope.conversationId, scope.messageId, scope.slot]
}

function conversationKey(accountId: string, conversationId: string): string {
  return JSON.stringify([accountId, conversationId])
}

function untilAborted<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(new Error('Media download stopped'))
    if (signal.aborted) {
      promise.catch(() => {})
      abort()
      return
    }
    signal.addEventListener('abort', abort, { once: true })
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort))
  })
}

/** Best-effort media retention; message text is stored independently. */
export class RecallMediaStore {
  private readonly db: DatabaseSync
  private readonly now: () => number
  private readonly fetchRemote: typeof fetch
  private readonly maxBytes: number
  private readonly settings = new Map<string, MediaSettings>()
  private readonly pending = new Set<string>()
  private readonly queue: CaptureJob[] = []
  private readonly active = new Map<CaptureJob, AbortController>()
  private closed = false

  constructor(options: { path: string; now?: () => number; fetch?: typeof fetch; maxBytes?: number }) {
    this.now = options.now ?? Date.now
    this.fetchRemote = options.fetch ?? globalThis.fetch
    this.maxBytes = options.maxBytes ?? 25 * 1024 * 1024
    if (options.path !== ':memory:') mkdirSync(dirname(options.path), { recursive: true })
    this.db = new DatabaseSync(options.path)
    this.db.exec(`
      PRAGMA journal_mode = WAL;
      PRAGMA busy_timeout = 5000;
      CREATE TABLE IF NOT EXISTS recall_media (
        account_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        message_id TEXT NOT NULL,
        slot TEXT NOT NULL,
        body BLOB NOT NULL,
        mime TEXT NOT NULL,
        saved_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        PRIMARY KEY (account_id, conversation_id, message_id, slot)
      );
      CREATE INDEX IF NOT EXISTS recall_media_expiry ON recall_media(expires_at);
    `)
    this.prune()
  }

  has(scope: RecallMediaScope): boolean {
    if (this.closed) return false
    return Boolean(this.db.prepare(`
      SELECT 1 FROM recall_media
      WHERE account_id = ? AND conversation_id = ? AND message_id = ? AND slot = ? AND expires_at > ?
    `).get(...scopeArgs(scope), this.now()))
  }

  get(scope: RecallMediaScope): { body: Buffer; mime: string } | undefined {
    if (this.closed) return undefined
    const row = this.db.prepare(`
      SELECT body, mime FROM recall_media
      WHERE account_id = ? AND conversation_id = ? AND message_id = ? AND slot = ? AND expires_at > ?
    `).get(...scopeArgs(scope), this.now()) as { body: Uint8Array; mime: string } | undefined
    return row ? { body: Buffer.from(row.body), mime: row.mime } : undefined
  }

  capture(scope: RecallMediaScope, sourceUrl: string, expiresAt: number, stillAllowed: () => boolean): Promise<boolean> {
    if (this.closed || !Number.isFinite(expiresAt) || expiresAt <= this.now()) return Promise.resolve(false)
    try {
      if (!stillAllowed() || this.settings.get(conversationKey(scope.accountId, scope.conversationId))?.enabled === false) {
        return Promise.resolve(false)
      }
      if (this.has(scope)) return Promise.resolve(true)
    } catch {
      return Promise.resolve(false)
    }
    if (!allowedUrl(sourceUrl)) return Promise.resolve(false)
    const key = JSON.stringify(scopeArgs(scope))
    if (this.pending.has(key) || this.pending.size >= MAX_PENDING) return Promise.resolve(false)
    this.pending.add(key)
    return new Promise<boolean>((resolve) => {
      this.queue.push({ scope: { ...scope }, sourceUrl, expiresAt, stillAllowed, resolve, key })
      this.drain()
    })
  }

  setSettings(accountId: string, conversationId: string, settings: MediaSettings): void {
    if (this.closed) return
    const retentionDays = Number.isFinite(settings.retentionDays) ? Math.max(0, settings.retentionDays) : 0
    this.settings.set(conversationKey(accountId, conversationId), { enabled: settings.enabled, retentionDays })
    if (!settings.enabled) {
      this.db.prepare('DELETE FROM recall_media WHERE account_id = ? AND conversation_id = ?').run(accountId, conversationId)
      for (const [job, controller] of this.active) {
        if (job.scope.accountId === accountId && job.scope.conversationId === conversationId) controller.abort()
      }
      for (let index = this.queue.length - 1; index >= 0; index -= 1) {
        const job = this.queue[index]!
        if (job.scope.accountId !== accountId || job.scope.conversationId !== conversationId) continue
        this.queue.splice(index, 1)
        this.pending.delete(job.key)
        job.resolve(false)
      }
    } else {
      this.db.prepare(`
        UPDATE recall_media SET expires_at = MIN(expires_at, saved_at + ?)
        WHERE account_id = ? AND conversation_id = ?
      `).run(retentionDays * DAY_MS, accountId, conversationId)
    }
    this.prune()
  }

  prune(): void {
    if (!this.closed) this.db.prepare('DELETE FROM recall_media WHERE expires_at <= ?').run(this.now())
  }

  close(): void {
    if (this.closed) return
    this.closed = true
    for (const controller of this.active.values()) controller.abort()
    for (const job of this.queue.splice(0)) {
      this.pending.delete(job.key)
      job.resolve(false)
    }
    this.db.close()
  }

  private drain(): void {
    while (!this.closed && this.active.size < MAX_CONCURRENT && this.queue.length) {
      const job = this.queue.shift()!
      const controller = new AbortController()
      this.active.set(job, controller)
      void this.run(job, controller).then((saved) => {
        this.active.delete(job)
        this.pending.delete(job.key)
        job.resolve(saved)
        this.drain()
      })
    }
  }

  private jobAllowed(job: CaptureJob): boolean {
    return !this.closed && job.expiresAt > this.now()
      && this.settings.get(conversationKey(job.scope.accountId, job.scope.conversationId))?.enabled !== false
      && job.stillAllowed()
  }

  private async run(job: CaptureJob, controller: AbortController): Promise<boolean> {
    const timer = setTimeout(() => controller.abort(), DOWNLOAD_TIMEOUT_MS)
    timer.unref?.()
    try {
      if (!this.jobAllowed(job)) return false
      const media = await this.download(job.sourceUrl, controller.signal)
      if (!media || controller.signal.aborted || !this.jobAllowed(job)) return false
      const savedAt = this.now()
      const settings = this.settings.get(conversationKey(job.scope.accountId, job.scope.conversationId))
      const expiresAt = settings ? Math.min(job.expiresAt, savedAt + settings.retentionDays * DAY_MS) : job.expiresAt
      if (expiresAt <= savedAt) return false
      this.db.prepare(`
        INSERT OR REPLACE INTO recall_media (account_id, conversation_id, message_id, slot, body, mime, saved_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      `).run(...scopeArgs(job.scope), media.body, media.mime, savedAt, expiresAt)
      return true
    } catch {
      // Remote URLs can carry QQ credentials; neither errors nor logs expose them.
      return false
    } finally {
      clearTimeout(timer)
    }
  }

  private async download(source: string, signal: AbortSignal): Promise<{ body: Buffer; mime: string } | undefined> {
    let url = allowedUrl(source)
    for (let redirects = 0; url && redirects <= 4; redirects += 1) {
      const response = await untilAborted(this.fetchRemote(url, {
        redirect: 'manual',
        headers: { 'User-Agent': 'Dududa-QQ-Workspace/1.0' },
        signal,
      }), signal)
      if (response.status >= 300 && response.status < 400) {
        void response.body?.cancel().catch(() => {})
        const location = response.headers.get('location')
        url = location ? allowedUrl(new URL(location, url).href) : undefined
        continue
      }
      const mime = response.headers.get('content-type')?.split(';')[0]?.trim().toLowerCase() ?? ''
      const allowedMime = /^(?:image|audio|video)\/[a-z0-9.+-]+$/.test(mime) || mime === 'application/octet-stream'
      const length = Number(response.headers.get('content-length') ?? 0)
      if (!response.ok || !allowedMime || /svg|html|xml/.test(mime) || length > this.maxBytes || !response.body) {
        void response.body?.cancel().catch(() => {})
        return undefined
      }
      const reader = response.body.getReader()
      const chunks: Buffer[] = []
      let size = 0
      try {
        while (true) {
          const { done, value } = await untilAborted(reader.read(), signal)
          if (done) break
          size += value.byteLength
          if (size > this.maxBytes) return undefined
          chunks.push(Buffer.from(value))
        }
        return size ? { body: Buffer.concat(chunks, size), mime } : undefined
      } finally {
        void reader.cancel().catch(() => {})
      }
    }
    return undefined
  }
}
