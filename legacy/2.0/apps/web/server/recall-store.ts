import { chmodSync, closeSync, mkdirSync, openSync } from 'node:fs'
import { dirname } from 'node:path'
import { DatabaseSync } from 'node:sqlite'

import type { ChatMessage, MessageSegment, RecallArchivePage, RecallSettings } from '../src/types/workspace'

const dayMs = 86_400_000

export function* archivedSegments(message: ChatMessage, prefix = ''): Generator<{ segment: MessageSegment; path: string }> {
  for (const [index, segment] of message.segments.entries()) {
    const path = `${prefix}${index}`
    yield { segment, path }
    if (segment.type === 'forward') {
      for (const [childIndex, child] of (segment.messages ?? []).entries()) {
        yield* archivedSegments(child, `${path}.${childIndex}.`)
      }
    }
  }
}

interface MessageRow {
  message_id: string
  message_json: string | null
  recorded_at: number
  expires_at: number
  recalled_at: number | null
  operator_id: string | null
}

interface RecallCursor {
  accountId: string
  conversationId: string
  recalledAt: number
  messageId: string
}

export interface RecallStoreOptions {
  path: string
  defaultEnabled?: boolean
  retentionDays?: number
  now?: () => number
}

/** Stores messages before a recall arrives, independently of connected browsers. */
export class RecallStore {
  private readonly database: DatabaseSync
  private readonly defaults: RecallSettings
  private readonly now: () => number
  private closed = false

  constructor(options: RecallStoreOptions) {
    this.defaults = this.validateSettings({
      enabled: options.defaultEnabled ?? true,
      retentionDays: options.retentionDays ?? 7,
    })
    this.now = options.now ?? Date.now
    if (options.path !== ':memory:') {
      const directory = dirname(options.path)
      mkdirSync(directory, { recursive: true, mode: 0o700 })
      chmodSync(directory, 0o700)
      closeSync(openSync(options.path, 'a', 0o600))
      chmodSync(options.path, 0o600)
    }
    this.database = new DatabaseSync(options.path)
    this.database.exec(`
      PRAGMA secure_delete = ON;
      CREATE TABLE IF NOT EXISTS recall_settings (
        account_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        retention_days INTEGER NOT NULL,
        PRIMARY KEY (account_id, conversation_id)
      );
      CREATE TABLE IF NOT EXISTS recall_messages (
        account_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        message_id TEXT NOT NULL,
        message_json TEXT,
        recorded_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        recalled_at INTEGER,
        operator_id TEXT,
        PRIMARY KEY (account_id, conversation_id, message_id)
      );
      CREATE INDEX IF NOT EXISTS recall_messages_expiry ON recall_messages (expires_at);
      CREATE INDEX IF NOT EXISTS recall_messages_archive
        ON recall_messages (account_id, conversation_id, recalled_at DESC, message_id DESC);
    `)
    this.prune()
  }

  getSettings(accountId: string, conversationId: string): RecallSettings {
    this.assertScope(accountId, conversationId)
    const row = this.database.prepare(
      'SELECT enabled, retention_days FROM recall_settings WHERE account_id = ? AND conversation_id = ?',
    ).get(accountId, conversationId)
    return row
      ? { enabled: Boolean(row.enabled), retentionDays: Number(row.retention_days) }
      : { ...this.defaults }
  }

  setSettings(accountId: string, conversationId: string, input: RecallSettings): RecallSettings {
    this.assertScope(accountId, conversationId)
    const settings = this.validateSettings(input)
    this.database.exec('BEGIN')
    try {
      this.database.prepare(`
        INSERT INTO recall_settings (account_id, conversation_id, enabled, retention_days) VALUES (?, ?, ?, ?)
        ON CONFLICT (account_id, conversation_id)
        DO UPDATE SET enabled = excluded.enabled, retention_days = excluded.retention_days
      `).run(accountId, conversationId, Number(settings.enabled), settings.retentionDays)
      if (!settings.enabled) {
        this.database.prepare('DELETE FROM recall_messages WHERE account_id = ? AND conversation_id = ?')
          .run(accountId, conversationId)
      } else {
        // Increasing retention applies to future messages; existing records never gain extra time.
        this.database.prepare(`
          UPDATE recall_messages SET expires_at = MIN(expires_at, recorded_at + ?)
          WHERE account_id = ? AND conversation_id = ?
        `).run(settings.retentionDays * dayMs, accountId, conversationId)
      }
      this.prune()
      this.database.exec('COMMIT')
    } catch (error) {
      this.database.exec('ROLLBACK')
      throw error
    }
    return settings
  }

  remember(message: ChatMessage): ChatMessage | undefined {
    const { accountId, conversationId, id } = message
    const settings = this.getSettings(accountId, conversationId)
    if (!settings.enabled) return undefined
    this.prune()
    const existing = this.row(accountId, conversationId, id)
    let original = message
    if (existing?.message_json && existing.recalled_at !== null) {
      const stored = JSON.parse(existing.message_json) as ChatMessage
      // A later replay cannot replace the original text. Media URLs may be refreshed separately.
      original = message.content === stored.content
        ? { ...stored, segments: message.segments, attachments: message.attachments ?? stored.attachments }
        : stored
    }
    // A UI placeholder is not the original message and must not become archived evidence.
    if (original.status === 'recalled' && !original.recall?.retained) {
      return existing ? this.message(existing) : undefined
    }
    const { recall: _recall, ...payload } = original
    // A replay contains the card again, not necessarily the details we already fetched.
    if (existing?.message_json) {
      const previous = JSON.parse(existing.message_json) as ChatMessage
      payload.segments = payload.segments.map((segment, index) => {
        const saved = previous.segments[index]
        return segment.type === 'forward' && !segment.messages && saved?.type === 'forward'
          && saved.forwardId === segment.forwardId && saved.messages
          ? { ...segment, messages: saved.messages, count: saved.count }
          : segment
      })
    }
    const recordedAt = existing?.recorded_at ?? this.now()
    this.database.prepare(`
      INSERT INTO recall_messages
        (account_id, conversation_id, message_id, message_json, recorded_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
      ON CONFLICT (account_id, conversation_id, message_id) DO UPDATE SET message_json = excluded.message_json
    `).run(accountId, conversationId, id, JSON.stringify(payload), recordedAt, recordedAt + settings.retentionDays * dayMs)
    return this.message(this.row(accountId, conversationId, id)!)
  }

  recall(
    accountId: string,
    conversationId: string,
    messageId: string,
    info: { recalledAt: number; operatorId?: string },
  ): ChatMessage | undefined {
    const settings = this.getSettings(accountId, conversationId)
    if (!settings.enabled) return undefined
    if (!Number.isFinite(info.recalledAt) || info.recalledAt < 0) throw new Error('撤回时间无效')
    this.prune()
    const now = this.now()
    this.database.prepare(`
      INSERT INTO recall_messages
        (account_id, conversation_id, message_id, recorded_at, expires_at, recalled_at, operator_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT (account_id, conversation_id, message_id) DO UPDATE SET
        recalled_at = COALESCE(recall_messages.recalled_at, excluded.recalled_at),
        operator_id = COALESCE(recall_messages.operator_id, excluded.operator_id)
    `).run(accountId, conversationId, messageId, now, now + settings.retentionDays * dayMs, info.recalledAt, info.operatorId ?? null)
    return this.message(this.row(accountId, conversationId, messageId)!)
  }

  get(accountId: string, conversationId: string, messageId: string): ChatMessage | undefined {
    if (!this.getSettings(accountId, conversationId).enabled) return undefined
    this.prune()
    const row = this.row(accountId, conversationId, messageId)
    return row ? this.message(row) : undefined
  }

  expiresAt(accountId: string, conversationId: string, messageId: string): number | undefined {
    return this.retention(accountId, conversationId, messageId)?.expiresAt
  }

  retention(accountId: string, conversationId: string, messageId: string): { recordedAt: number; expiresAt: number } | undefined {
    if (!this.getSettings(accountId, conversationId).enabled) return undefined
    this.prune()
    const row = this.row(accountId, conversationId, messageId)
    return row ? { recordedAt: row.recorded_at, expiresAt: row.expires_at } : undefined
  }

  saveForward(accountId: string, conversationId: string, messageId: string, forwardId: string, messages: ChatMessage[]): ChatMessage | undefined {
    // A fetch completing after disable/expiry must not recreate the deleted original.
    const original = this.get(accountId, conversationId, messageId)
    if (!original || !messages.length) return undefined
    const match = [...archivedSegments(original)].find(({ segment }) => segment.type === 'forward' && segment.forwardId === forwardId)
    if (match?.segment.type !== 'forward') return undefined
    match.segment.messages = messages
    match.segment.count = messages.length
    return this.remember(original)
  }

  listRecalled(
    accountId: string,
    conversationId: string,
    query: { limit?: number; before?: string } = {},
  ): RecallArchivePage {
    const settings = this.getSettings(accountId, conversationId)
    this.prune()
    if (!settings.enabled) return { settings, messages: [], hasMore: false }
    const requestedLimit = Number.isFinite(query.limit) ? Math.floor(query.limit!) : 50
    const limit = Math.min(Math.max(requestedLimit, 1), 100)
    const cursor = query.before ? this.cursor(query.before, accountId, conversationId) : undefined
    const rows = this.database.prepare(`
      SELECT * FROM recall_messages
      WHERE account_id = ? AND conversation_id = ? AND recalled_at IS NOT NULL AND message_json IS NOT NULL
      ${cursor ? 'AND (recalled_at < ? OR (recalled_at = ? AND message_id < ?))' : ''}
      ORDER BY recalled_at DESC, message_id DESC LIMIT ?
    `).all(accountId, conversationId,
      ...(cursor ? [cursor.recalledAt, cursor.recalledAt, cursor.messageId] : []), limit + 1) as unknown as MessageRow[]
    const page = rows.slice(0, limit)
    const hasMore = rows.length > limit
    const last = page.at(-1)
    return {
      settings,
      messages: page.map((row) => this.message(row)!),
      hasMore,
      ...(hasMore && last ? {
        nextCursor: Buffer.from(JSON.stringify({
          accountId, conversationId, recalledAt: last.recalled_at, messageId: last.message_id,
        })).toString('base64url'),
      } : {}),
    }
  }

  prune(): void {
    this.database.prepare('DELETE FROM recall_messages WHERE expires_at <= ?').run(this.now())
  }

  close(): void {
    if (this.closed) return
    this.database.close()
    this.closed = true
  }

  private row(accountId: string, conversationId: string, messageId: string): MessageRow | undefined {
    return this.database.prepare(
      'SELECT * FROM recall_messages WHERE account_id = ? AND conversation_id = ? AND message_id = ?',
    ).get(accountId, conversationId, messageId) as unknown as MessageRow | undefined
  }

  private message(row: MessageRow): ChatMessage | undefined {
    if (!row.message_json) return undefined
    const message = JSON.parse(row.message_json) as ChatMessage
    if (row.recalled_at === null) return message
    return {
      ...message,
      status: 'recalled',
      recall: {
        recalledAt: row.recalled_at,
        recordedAt: row.recorded_at,
        ...(row.operator_id ? { operatorId: row.operator_id } : {}),
        retained: true,
        expiresAt: row.expires_at,
      },
    }
  }

  private assertScope(accountId: string, conversationId: string): void {
    if (!accountId || !conversationId.startsWith(`${accountId}:`)) throw new Error('防撤回会话不属于当前账号')
  }

  private validateSettings(settings: RecallSettings): RecallSettings {
    if (typeof settings.enabled !== 'boolean') throw new Error('防撤回开关无效')
    if (!Number.isInteger(settings.retentionDays) || settings.retentionDays < 1 || settings.retentionDays > 30) {
      throw new Error('防撤回保留时间必须为 1 至 30 天')
    }
    return { enabled: settings.enabled, retentionDays: settings.retentionDays }
  }

  private cursor(value: string, accountId: string, conversationId: string): RecallCursor {
    let cursor: RecallCursor
    try {
      cursor = JSON.parse(Buffer.from(value, 'base64url').toString()) as RecallCursor
    } catch {
      throw new Error('防撤回分页游标无效')
    }
    if (!cursor || cursor.accountId !== accountId || cursor.conversationId !== conversationId
      || !Number.isFinite(cursor.recalledAt) || typeof cursor.messageId !== 'string') {
      throw new Error('防撤回分页游标与当前会话不匹配')
    }
    return cursor
  }
}
