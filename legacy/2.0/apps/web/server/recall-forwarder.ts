import { DatabaseSync } from 'node:sqlite'
import type { OneBotMessage, OneBotSegment } from './mapper'

export const recallForwardDefaultGroups = ['419256533', '481757927', '530719678'] as const
export const recallSuperAdmin = '1778159807'
const retentionMs = 7 * 86_400_000
export type RecallSend = (groupId: string, message: OneBotSegment[]) => Promise<unknown>

/** Only literal text plus one real mention of this account is a command. */
export function recallCommand(raw: OneBotMessage, selfId: string): boolean | undefined {
  if (raw.message_type !== 'group' || !Array.isArray(raw.message)) return undefined
  const mentions = raw.message.filter((s) => s.type === 'at')
  if (mentions.length !== 1 || String(mentions[0]?.data?.qq) !== selfId) return undefined
  if (raw.message.some((s) => s.type !== 'text' && s.type !== 'at')) return undefined
  const text = raw.message.filter((s) => s.type === 'text').map((s) => String(s.data?.text ?? '')).join('').trim()
  if (text === '/开启防撤回') return true
  if (text === '/关闭防撤回') return false
  return undefined
}

function displaySegments(raw: OneBotMessage): OneBotSegment[] {
  const result: OneBotSegment[] = []
  const text = (value: string) => result.push({ type: 'text', data: { text: value } })
  if (!Array.isArray(raw.message)) {
    text(typeof raw.message === 'string' ? raw.message : raw.raw_message || '[无法读取消息内容]')
    return result
  }
  for (const segment of raw.message) {
    const data = segment.data ?? {}
    if (segment.type === 'text') text(String(data.text ?? ''))
    else if (segment.type === 'at') text(data.qq === 'all' ? '@全体成员' : `@${String(data.qq ?? '')}`)
    else if (segment.type === 'face' && /^\d+$/.test(String(data.id))) result.push({ type: 'face', data: { id: String(data.id) } })
    else if (['image', 'record', 'video'].includes(segment.type)) {
      // Never pass local paths, CQ commands, or arbitrary segment data to OneBot.
      const source = String(data.url ?? data.file ?? '')
      let allowed = false
      try {
        const url = new URL(source)
        allowed = ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password &&
          ['qq.com', 'qq.com.cn', 'qpic.cn', 'gtimg.cn', 'qlogo.cn'].some((host) => url.hostname === host || url.hostname.endsWith(`.${host}`))
      } catch { /* Missing or expired resources still have a readable marker. */ }
      if (allowed && segment.type === 'image') result.push({ type: 'image', data: { file: source } })
      else text(segment.type === 'image' ? '[图片]' : segment.type === 'record' ? '[语音]' : '[视频]')
    } else if (segment.type === 'reply') continue
    else if (segment.type === 'file') text(`[文件] ${String(data.name ?? data.file ?? '').split(/[\\/]/).at(-1)}`)
    else if (segment.type === 'forward') text('[合并转发消息]')
    else if (segment.type === 'json' || segment.type === 'xml') text('[卡片消息]')
    else text(`[${segment.type}消息]`)
  }
  return result.length ? result : [{ type: 'text', data: { text: '[无可显示内容]' } }]
}

export class RecallForwarder {
  private readonly db: DatabaseSync
  private closed = false
  constructor(path: string, private readonly now: () => number = Date.now) {
    this.db = new DatabaseSync(path)
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS recall_forward_settings (
        account TEXT NOT NULL, group_id TEXT NOT NULL, enabled INTEGER NOT NULL,
        PRIMARY KEY(account, group_id));
      CREATE TABLE IF NOT EXISTS recall_forward_messages (
        account TEXT NOT NULL, group_id TEXT NOT NULL, message_id TEXT NOT NULL,
        payload TEXT, recalled INTEGER NOT NULL DEFAULT 0, claimed INTEGER NOT NULL DEFAULT 0,
        expires_at INTEGER NOT NULL, PRIMARY KEY(account, group_id, message_id));
      CREATE INDEX IF NOT EXISTS recall_forward_expiry ON recall_forward_messages(expires_at);
      CREATE TABLE IF NOT EXISTS recall_forward_commands (
        account TEXT NOT NULL, group_id TEXT NOT NULL, message_id TEXT NOT NULL,
        expires_at INTEGER NOT NULL, PRIMARY KEY(account, group_id, message_id));
    `)
    this.prune()
  }

  enabled(account: string, groupId: string): boolean {
    const row = this.db.prepare('SELECT enabled FROM recall_forward_settings WHERE account=? AND group_id=?').get(account, groupId)
    return row ? Boolean(row.enabled) : (recallForwardDefaultGroups as readonly string[]).includes(groupId)
  }

  private setEnabled(account: string, groupId: string, enabled: boolean): void {
    this.db.prepare(`INSERT INTO recall_forward_settings VALUES(?,?,?)
      ON CONFLICT(account,group_id) DO UPDATE SET enabled=excluded.enabled`).run(account, groupId, Number(enabled))
    if (!enabled) this.db.prepare('UPDATE recall_forward_messages SET payload=NULL, claimed=1 WHERE account=? AND group_id=?').run(account, groupId)
  }

  async message(account: string, selfId: string, raw: OneBotMessage, send: RecallSend): Promise<void> {
    if (this.closed || raw.message_type !== 'group' || String(raw.user_id) === selfId) return
    const groupId = String(raw.group_id ?? '')
    const id = String(raw.message_id ?? '')
    if (!/^\d+$/.test(groupId) || !/^-?\d+$/.test(id)) return
    this.prune()
    const command = recallCommand(raw, selfId)
    if (command !== undefined) {
      // The configured super administrator can operate even as an ordinary member.
      // No global AstrBot privileges or other users' permissions are changed.
      if (String(raw.user_id) !== recallSuperAdmin) return
      const claimed = this.db.prepare('INSERT OR IGNORE INTO recall_forward_commands VALUES(?,?,?,?)')
        .run(account, groupId, id, this.now() + retentionMs)
      if (!claimed.changes) return
      this.setEnabled(account, groupId, command)
      await send(groupId, [{ type: 'text', data: { text: command ? '本群防撤回已开启。' : '本群防撤回已关闭。' } }])
      return
    }
    if (!this.enabled(account, groupId)) return
    this.db.prepare(`INSERT INTO recall_forward_messages(account,group_id,message_id,payload,expires_at) VALUES(?,?,?,?,?)
      ON CONFLICT(account,group_id,message_id) DO UPDATE SET payload=COALESCE(recall_forward_messages.payload,excluded.payload)`)
      .run(account, groupId, id, JSON.stringify(raw), this.now() + retentionMs)
    await this.deliver(account, groupId, id, send)
  }

  async recall(account: string, selfId: string, event: Record<string, unknown>, send: RecallSend): Promise<void> {
    if (!this.closed && event.notice_type === 'group_increase' && String(event.user_id) === selfId) {
      const joinedGroup = String(event.group_id ?? '')
      if (/^\d+$/.test(joinedGroup) && !(recallForwardDefaultGroups as readonly string[]).includes(joinedGroup)) {
        this.setEnabled(account, joinedGroup, false)
      }
      return
    }
    if (this.closed || event.notice_type !== 'group_recall' || String(event.user_id) === selfId) return
    const groupId = String(event.group_id ?? '')
    const id = String(event.message_id ?? '')
    if (!/^\d+$/.test(groupId) || !/^-?\d+$/.test(id) || !this.enabled(account, groupId)) return
    this.prune()
    this.db.prepare(`INSERT INTO recall_forward_messages(account,group_id,message_id,recalled,expires_at) VALUES(?,?,?,1,?)
      ON CONFLICT(account,group_id,message_id) DO UPDATE SET recalled=1`)
      .run(account, groupId, id, this.now() + retentionMs)
    await this.deliver(account, groupId, id, send)
  }

  private async deliver(account: string, groupId: string, id: string, send: RecallSend): Promise<void> {
    if (!this.enabled(account, groupId)) return
    // Claim before sending: duplicate notices and uncertain network responses must
    // not publish somebody's message twice, including after a service restart.
    const row = this.db.prepare(`UPDATE recall_forward_messages SET claimed=1
      WHERE account=? AND group_id=? AND message_id=? AND recalled=1 AND claimed=0 AND payload IS NOT NULL
      RETURNING payload`).get(account, groupId, id)
    if (!row) return
    const raw = JSON.parse(String(row.payload)) as OneBotMessage
    const senderId = String(raw.user_id)
    const name = String(raw.sender?.card || raw.sender?.nickname || senderId)
    await send(groupId, [
      { type: 'text', data: { text: `【防撤回】\n发送人：${name}（${senderId}）\n内容：\n` } },
      ...displaySegments(raw),
    ])
  }

  prune(): void {
    if (this.closed) return
    this.db.prepare('DELETE FROM recall_forward_messages WHERE expires_at<=?').run(this.now())
    this.db.prepare('DELETE FROM recall_forward_commands WHERE expires_at<=?').run(this.now())
  }
  close(): void { if (!this.closed) { this.closed = true; this.db.close() } }
}
