"""Explicit, durable greeting consent and last-moment guarded delivery.

Authorization is the dispatch boundary: pending/claimed work can be cancelled;
network sends already authorized cannot be recalled and are never retried.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ..base import Command, Ctx, Job, JobCtx, Registry, Reply, Toolkit

ZONE = ZoneInfo("Asia/Shanghai")
KINDS = {"早安": "morning", "晚安": "evening", "生日": "birthday", "纪念日": "anniversary"}
LABELS = {value: key for key, value in KINDS.items()}
SPECIAL = {"birthday", "anniversary"}
WINDOW = 15 * 60


def initialize(store) -> None:
    with store.connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS affinity_greetings (
              user_id TEXT NOT NULL, kind TEXT NOT NULL, account_id TEXT NOT NULL,
              conversation_id TEXT NOT NULL, clock TEXT NOT NULL, annual_date TEXT,
              enabled INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1,
              enabled_at REAL NOT NULL, reason TEXT NOT NULL DEFAULT '',
              PRIMARY KEY(user_id,kind));
            CREATE TABLE IF NOT EXISTS affinity_greeting_pending (
              user_id TEXT NOT NULL, kind TEXT NOT NULL, scope TEXT NOT NULL,
              clock TEXT NOT NULL, annual_date TEXT, expires_at REAL NOT NULL,
              PRIMARY KEY(user_id,kind));
            CREATE TABLE IF NOT EXISTS affinity_greeting_groups (
              group_id TEXT PRIMARY KEY, disabled INTEGER NOT NULL, updated_by TEXT NOT NULL,
              updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS affinity_greeting_events (
              id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL,
              event TEXT NOT NULL, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS affinity_greeting_deliveries (
              user_id TEXT NOT NULL, kind TEXT NOT NULL, local_date TEXT NOT NULL,
              outbox_id INTEGER NOT NULL UNIQUE, PRIMARY KEY(user_id,kind,local_date));
        """)


def _audit(db, user: str, kind: str, event: str) -> None:
    db.execute("INSERT INTO affinity_greeting_events(user_id,kind,event,at) VALUES (?,?,?,?)",
               (user, kind, event, time.time()))


def _cancel(db, user: str, kind: str) -> None:
    db.execute("UPDATE outbox SET state='cancelled',updated_at=? WHERE guard_user=? AND guard_kind=? "
               "AND state IN ('pending','claimed')", (time.time(), user, kind))


def _pause(db, user: str, kind: str, reason: str) -> None:
    changed = db.execute("UPDATE affinity_greetings SET enabled=0,revision=revision+1,reason=? "
                         "WHERE user_id=? AND kind=? AND enabled=1", (reason, user, kind)).rowcount
    db.execute("DELETE FROM affinity_greeting_pending WHERE user_id=? AND kind=?", (user, kind))
    _cancel(db, user, kind)
    if changed:
        _audit(db, user, kind, reason)


def _eligible(db, user: str, kind: str, score: float) -> bool:
    from .social import established
    relation = established(db, user)
    return score >= 50 and not (relation and score <= 50) and (kind not in SPECIAL or (relation and score >= 80))


def score_changed(db, user_id: str, score: float) -> None:
    for kind in LABELS:
        if not _eligible(db, user_id, kind, score):
            _pause(db, user_id, kind, "score_ineligible")


def disable_user(db, user_id: str) -> None:
    for kind in LABELS:
        _pause(db, user_id, kind, "relationship_ended")


def disable_all(db) -> None:
    users = db.execute("SELECT user_id,kind FROM affinity_greetings WHERE enabled=1 "
                       "UNION SELECT user_id,kind FROM affinity_greeting_pending").fetchall()
    for row in users:
        _pause(db, row["user_id"], row["kind"], "affinity_disabled")
    db.execute("UPDATE outbox SET state='cancelled',updated_at=? WHERE guard_user IS NOT NULL "
               "AND state IN ('pending','claimed')", (time.time(),))


def _enabled(db, runtime) -> bool:
    row = db.execute("SELECT enabled FROM switches WHERE task='affinity'").fetchone()
    definition = runtime.registry.tasks.get("affinity")
    return bool(row[0]) if row else definition.default if definition else True


def _score(db, runtime, user: str) -> float:
    if user == str(runtime.settings.feature("affinity").get("super_admin") or ""):
        return 120.0
    row = db.execute("SELECT score FROM affinity WHERE user_id=?", (user,)).fetchone()
    return float(row[0]) if row else 0.0


def _target_allowed(db, runtime, account: str, conversation: str, user: str) -> bool:
    match = re.fullmatch(r"(qq-\d+):(group|private):(\d+)", conversation)
    scope = f"{account}/{conversation}"
    if not match or match[1] != account or scope not in runtime.settings.allowed_scopes:
        return False
    if match[2] == "private":
        return match[3] == user
    if scope not in runtime.settings.proactive_scopes:
        return False
    row = db.execute("SELECT disabled FROM affinity_greeting_groups WHERE group_id=?", (match[3],)).fetchone()
    return not row or not row[0]


def _valid(db, runtime, row) -> bool:
    return (_enabled(db, runtime)
            and _eligible(db, row["user_id"], row["kind"], _score(db, runtime, row["user_id"]))
            and _target_allowed(db, runtime, row["account_id"], row["conversation_id"], row["user_id"]))


def reconcile(runtime) -> None:
    from . import ledger
    ledger(Toolkit(runtime))  # Initialize score tables without changing any existing score.
    with runtime.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if not _enabled(db, runtime):
            disable_all(db)
            return
        for row in db.execute("SELECT * FROM affinity_greetings WHERE enabled=1").fetchall():
            if not _valid(db, runtime, row):
                _pause(db, row["user_id"], row["kind"], "permission_revoked")
        db.execute("DELETE FROM affinity_greeting_pending WHERE expires_at<?", (time.time(),))
        db.execute("UPDATE outbox SET state='cancelled',updated_at=? WHERE guard_user IS NOT NULL "
                   "AND state IN ('pending','claimed') AND expires_at<?", (time.time(), time.time()))


def _reply(ctx: Ctx, text: str) -> Reply:
    reply = Reply()
    if ctx.inbound.is_group:
        reply.mention(ctx.inbound.sender.id)
    return reply.text(text)


def _schedule(parts: list[str], kind: str) -> tuple[str, str | None]:
    expected = 3 if kind in SPECIAL else 2
    if len(parts) != expected or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", parts[-1]):
        raise ValueError("早晚问候：/问候 早安 08:00 或 /问候 晚安 23:00；纪念日：/问候 生日 05-20 08:00 或 /问候 纪念日 2026-10-20 08:00。时区 Asia/Shanghai。")
    annual = None
    if kind in SPECIAL:
        annual = parts[1]
        if re.fullmatch(r"\d{2}-\d{2}", annual):
            date.fromisoformat("2000-" + annual)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", annual):
            date.fromisoformat(annual)
        else:
            raise ValueError("请提供真实有效日期，格式 MM-DD 或 YYYY-MM-DD；每年在该日期问候。")
    return parts[-1], annual


def _activate(db, user: str, kind: str, account: str, conversation: str, clock: str,
              annual: str | None, now: float) -> None:
    _cancel(db, user, kind)
    db.execute("INSERT INTO affinity_greetings(user_id,kind,account_id,conversation_id,clock,annual_date,enabled,enabled_at) "
               "VALUES (?,?,?,?,?,?,1,?) ON CONFLICT(user_id,kind) DO UPDATE SET account_id=excluded.account_id,"
               "conversation_id=excluded.conversation_id,clock=excluded.clock,annual_date=excluded.annual_date,"
               "enabled=1,revision=affinity_greetings.revision+1,enabled_at=excluded.enabled_at,reason=''",
               (user, kind, account, conversation, clock, annual, now))
    db.execute("DELETE FROM affinity_greeting_pending WHERE user_id=? AND kind=?", (user, kind))
    _audit(db, user, kind, "explicit_opt_in")


async def greeting_command(ctx: Ctx) -> Reply:
    from . import ledger, score_for
    inbound = ctx.inbound
    if inbound.source != "qq" or inbound.preview:
        return _reply(ctx, "请在本人 QQ 会话中操作问候。")
    user, scope, now = inbound.sender.id, inbound.scope, time.time()
    parts = ctx.args.strip().split()
    action = parts[0] if parts else "状态"
    with ctx.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if action in {"关闭", *("关闭" + label for label in KINDS)} and len(parts) == 1:
            for kind in ([KINDS[action[2:]]] if action != "关闭" else LABELS):
                _pause(db, user, kind, "user_opt_out")
            return _reply(ctx, "已关闭所选问候，尚未派发的任务已取消。")
        if action in ("群关闭", "群开启") and len(parts) == 1:
            if not inbound.is_group or not (ctx.is_admin or ledger(ctx).is_super(user)
                                            or inbound.sender.role in ("owner", "admin")):
                return _reply(ctx, "仅当前群管理员或系统管理员可管理群问候。")
            disabled = action == "群关闭"
            db.execute("INSERT OR REPLACE INTO affinity_greeting_groups VALUES (?,?,?,?)",
                       (inbound.peer_id, int(disabled), user, now))
            if disabled:
                rows = db.execute("SELECT user_id,kind FROM affinity_greetings WHERE conversation_id LIKE ?",
                                  (f"%:group:{inbound.peer_id}",)).fetchall()
                for row in rows:
                    _pause(db, row["user_id"], row["kind"], "group_disabled")
                db.execute("DELETE FROM affinity_greeting_pending WHERE scope LIKE ?", (f"%:group:{inbound.peer_id}",))
            suffix = "；用户须逐项重新开启，仍须运维允许本群主动发送" if not disabled else "，不会改发私聊"
            return _reply(ctx, ("本群问候已关闭" if disabled else "本群问候限制已解除") + suffix + "。")
        if action == "状态" and len(parts or ["状态"]) == 1:
            rows = db.execute("SELECT * FROM affinity_greetings WHERE user_id=?", (user,)).fetchall()
            lines = ["问候默认关闭；时区 Asia/Shanghai。"]
            for kind, label in LABELS.items():
                row = next((item for item in rows if item["kind"] == kind), None)
                if not row or not row["enabled"]:
                    lines.append(f"{label}：关闭或暂停，恢复条件后须手动开启")
                elif f"{row['account_id']}/{row['conversation_id']}" != scope:
                    lines.append(f"{label}：在其他会话开启（不在此展示私人日期或目标）")
                else:
                    lines.append(f"{label}：本会话 {row['annual_date'] or '每天'} {row['clock']}")
            lines.append("开启：/问候 早安 08:00、/问候 晚安 23:00；生日/纪念日需分别提供日期和时间；关闭：/问候 关闭。")
            return _reply(ctx, "\n".join(lines))
        if not _enabled(db, ctx.runtime):
            return _reply(ctx, "亲密度系统已关闭；仍可关闭问候。")
        confirm = action == "确认" or action.startswith("确认")
        label = (parts[1] if action == "确认" and len(parts) == 2 else action[2:]) if confirm else action
        kind = KINDS.get(label)
        if not kind:
            return _reply(ctx, "使用 /问候 早安 08:00、晚安 23:00、生日 MM-DD HH:MM、纪念日 YYYY-MM-DD HH:MM、状态 或 关闭。")
        if not (_eligible(db, user, kind, score_for(ctx)) and _eligible(db, user, kind, _score(db, ctx.runtime, user))):
            return _reply(ctx, "暂时不能开启或修改此问候。早晚问候需至少 50；已有暂停关系不可开启；生日和纪念日需已建立关系且至少 80。")
        if not _target_allowed(db, ctx.runtime, inbound.account_id, inbound.conversation_id, user):
            return _reply(ctx, "本会话未获准主动问候或已被群管理员关闭；不会改发其他会话。")
        if confirm:
            if (action == "确认" and len(parts) != 2) or (action != "确认" and len(parts) != 1):
                return _reply(ctx, "请使用 /问候 确认 早安（或晚安、生日、纪念日）。")
            pending = db.execute("SELECT * FROM affinity_greeting_pending WHERE user_id=? AND kind=?", (user, kind)).fetchone()
            if not pending or pending["scope"] != scope or pending["expires_at"] < now:
                return _reply(ctx, "本会话没有有效的替换申请；请重新发送带时间（纪念日另带日期）的开启指令。")
            clock, annual = pending["clock"], pending["annual_date"]
        else:
            try:
                clock, annual = _schedule(parts, kind)
            except ValueError as exc:
                return _reply(ctx, str(exc))
            old = db.execute("SELECT * FROM affinity_greetings WHERE user_id=? AND kind=?", (user, kind)).fetchone()
            if old and f"{old['account_id']}/{old['conversation_id']}" != scope:
                _pause(db, user, kind, "replacement_requested")
                db.execute("INSERT OR REPLACE INTO affinity_greeting_pending VALUES (?,?,?,?,?,?)",
                           (user, kind, scope, clock, annual, now + 600))
                return _reply(ctx, f"该问候已有其他目标，旧目标已暂停。若同意仅在本会话接收{label}，请在 10 分钟内发送 /问候 确认 {label}。生日等日期仅使用你在本次明确提供的信息。")
        _activate(db, user, kind, inbound.account_id, inbound.conversation_id, clock, annual, now)
        return _reply(ctx, f"已明确开启{label}：{annual or '每天'} {clock}（Asia/Shanghai），仅发本会话" +
                      ("并 @ 你一次。" if inbound.is_group else "，不向群公开。") + "可随时 /问候 关闭" + label + "。")


def _actions(db, runtime, row) -> list[dict]:
    from .social import approved_nickname
    scope = f"{row['account_id']}/{row['conversation_id']}"
    nickname = approved_nickname(db, row["user_id"], scope, _score(db, runtime, row["user_id"]))
    text = {"morning": "早安，愿今天顺利。", "evening": "晚安，愿你安稳休息。",
            "birthday": "生日快乐，愿新的一岁平安顺心。", "anniversary": "纪念日快乐，谢谢一路相伴。"}[row["kind"]]
    reply = Reply()
    if ":group:" in row["conversation_id"]:
        reply.mention(row["user_id"])
    return reply.text((nickname + "，" if nickname else "") + text).actions


def queue_due(ctx: JobCtx, now: float | None = None) -> int:
    from . import ledger
    ledger(ctx)
    now = time.time() if now is None else now
    local = datetime.fromtimestamp(now, ZONE)
    queued = 0
    with ctx.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if not _enabled(db, ctx.runtime):
            disable_all(db)
            return 0
        rows = db.execute("SELECT * FROM affinity_greetings WHERE enabled=1").fetchall()
        for row in rows:
            user, kind = row["user_id"], row["kind"]
            if not _valid(db, ctx.runtime, row):
                _pause(db, user, kind, "permission_revoked")
                continue
            annual = row["annual_date"]
            if annual and (annual[-5:] != local.strftime("%m-%d") or (len(annual) == 10 and annual[:4] > str(local.year))):
                continue
            hour, minute = map(int, row["clock"].split(":"))
            due = local.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()
            if due < row["enabled_at"] or not due <= now <= due + WINDOW:
                continue
            queued += bool(db.execute(
                "INSERT OR IGNORE INTO outbox(account_id,conversation_id,actions,state,dedupe,created_at,updated_at,"
                "guard_user,guard_kind,guard_revision,expires_at) VALUES (?,?,?,'pending',?,?,?,?,?,?,?)",
                (row["account_id"], row["conversation_id"], json.dumps(_actions(db, ctx.runtime, row), ensure_ascii=False),
                 f"affinity:{user}:{kind}:{local.date().isoformat()}", now, now, user, kind, row["revision"], due + WINDOW)).rowcount)
    return queued


async def greeting_job(ctx: JobCtx) -> None:
    queue_due(ctx)


def authorize(runtime, item_id: int, target_valid: bool, now: float | None = None) -> dict:
    """Called only after the bridge's fresh OneBot target check, immediately before send."""
    now = time.time() if now is None else now
    with runtime.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        item = db.execute("SELECT * FROM outbox WHERE id=?", (item_id,)).fetchone()
        if not item or not item["guard_user"] or item["state"] != "claimed":
            return {"authorized": False}
        row = db.execute("SELECT * FROM affinity_greetings WHERE user_id=? AND kind=?",
                         (item["guard_user"], item["guard_kind"])).fetchone()
        current = bool(row and row["enabled"] and row["revision"] == item["guard_revision"]
                       and row["account_id"] == item["account_id"] and row["conversation_id"] == item["conversation_id"])
        if not target_valid:
            if current:
                _pause(db, row["user_id"], row["kind"], "target_invalid")
            db.execute("UPDATE outbox SET state='unknown',updated_at=? WHERE id=?", (now, item_id))
            return {"authorized": False}
        valid = current and _valid(db, runtime, row)
        if current and not valid:
            _pause(db, row["user_id"], row["kind"], "permission_revoked")
        if not valid or item["expires_at"] < now:
            db.execute("UPDATE outbox SET state='cancelled',updated_at=? WHERE id=?", (now, item_id))
            return {"authorized": False}
        local_date = datetime.fromtimestamp(now, ZONE).date().isoformat()
        reserved = db.execute(
            "INSERT OR IGNORE INTO affinity_greeting_deliveries(user_id,kind,local_date,outbox_id) VALUES (?,?,?,?)",
            (row["user_id"], row["kind"], local_date, item_id)).rowcount
        if not reserved:
            db.execute("UPDATE outbox SET state='cancelled',updated_at=? WHERE id=?", (now, item_id))
            return {"authorized": False}
        actions = _actions(db, runtime, row)
        db.execute("UPDATE outbox SET state='sending',updated_at=?,actions=? WHERE id=?",
                   (now, json.dumps(actions, ensure_ascii=False), item_id))
        return {"authorized": True, "actions": actions}


def register(registry: Registry) -> None:
    registry.command(Command(("问候",), greeting_command, "", task=None))
    registry.job(Job("affinity", 30, greeting_job, initial_delay_seconds=20))
