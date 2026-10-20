from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__:
    from .notifications import QueryError
else:
    from notifications import QueryError

CHINA_TIME = timezone(timedelta(hours=8))
WEEKLY_PAGE = "https://tam.cmet.ustc.edu.cn/ustcta-pc/#/stu-week-report-student/index"
REASONS = {
    "weekly_report_missing": "学校当前列表中找不到这期汇报，请人工核对",
    "weekly_schedule_changed": "学校汇报日期已变化，将按最新日期重新安排",
    "weekly_permission_missing": "当前账号没有周汇报提交权限",
    "weekly_submission_closed": "学校提交前检查未通过，未强行提交",
    "weekly_report_not_empty": "本期已有学生学业信息，不按空汇报自动提交，请人工确认",
    "weekly_schedule_invalid": "学校未提供可识别的汇报日期，请人工确认",
}


def current_time():
    return datetime.now(CHINA_TIME)


def scheduled_date(item, policy="first"):
    dates = item["report_dates"]
    return (dates[0] if policy == "first" else dates[-1]) if dates else None


def is_due(item, hour=20, policy="first", *, now=None):
    now = (now or current_time()).astimezone(CHINA_TIME)
    return (
        item["open_week"]
        and item["status"] == "NOT_SUBMITTED"
        and scheduled_date(item, policy) == now.date().isoformat()
        and now.hour >= hour
    )


class WeeklyService:
    def __init__(self, root, owner, query, send, *, hour=20, policy="first",
                 submit_allowed=True, dry_run=False):
        if not 0 <= hour <= 23 or policy not in {"first", "last"}:
            raise ValueError("invalid_weekly_schedule")
        self.owner, self.query, self.send = owner, query, send
        self.hour, self.policy = hour, policy
        # ``submit_allowed`` mirrors the Host switch ``notify_auto_submit``; dry runs never write.
        self.submit_allowed, self.dry_run = submit_allowed, dry_run
        self.root = Path(root) / f"weekly-{owner}"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.root / "state.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                key TEXT PRIMARY KEY, semester TEXT NOT NULL, payload TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'waiting', attempted_at TEXT,
                notice TEXT NOT NULL DEFAULT '', notified INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    def set_meta(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, value))

    def get_meta(self, key):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_state(self, item, state, notice=""):
        with self.db:
            self.db.execute(
                "UPDATE jobs SET state=?,payload=?,notified=CASE WHEN notice=? THEN notified ELSE 0 END,notice=? WHERE key=?",
                (
                    state,
                    json.dumps(item, ensure_ascii=False),
                    notice,
                    notice,
                    item["key"],
                ),
            )

    def label(self, item):
        return f"{item['course']}，{item['week_start']} 至 {item['week_end']}"

    def verified_notice(self, item):
        return f"【周汇报已提交】\n- {self.label(item)}\n- 学校记录：{item['submitted_at']}\n- 已核对提交状态，未填写正文或上传附件。"

    def uncertain_notice(self, item):
        return f"【周汇报待核实】\n- {self.label(item)}\n- 提交结果暂未确认，会只读核对学校记录，不会重复提交。\n{WEEKLY_PAGE}"

    async def deliver_notices(self):
        for row in self.db.execute(
            "SELECT key,notice FROM jobs WHERE notice<>'' AND notified=0"
        ).fetchall():
            await self.send(row["notice"])
            with self.db:
                self.db.execute("UPDATE jobs SET notified=1 WHERE key=?", (row["key"],))

    async def poll(self):
        semesters = [
            row[0]
            for row in self.db.execute(
                "SELECT DISTINCT semester FROM jobs WHERE state IN ('submitting','uncertain')"
            )
        ]
        snapshot = await self.query(
            {"operation": "weekly_list", "semesters": semesters}
        )
        self.set_meta("checked_at", current_time().isoformat(timespec="seconds"))
        self.set_meta("semester", snapshot["semester_id"])
        self.set_meta("can_submit", str(snapshot["can_submit"]))
        failure = None
        with self.db:
            self.db.execute("UPDATE jobs SET active=0")
            for item in snapshot["reports"]:
                self.db.execute(
                    "INSERT INTO jobs(key,semester,payload) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,active=1",
                    (
                        item["key"],
                        item["semester_id"],
                        json.dumps(item, ensure_ascii=False),
                    ),
                )
        for item in snapshot["reports"]:
            state = self.db.execute(
                "SELECT state FROM jobs WHERE key=?", (item["key"],)
            ).fetchone()[0]
            if item["status"] == "SUBMITTED":
                if state in {"submitting", "uncertain"} and item["submitted_at"]:
                    self.set_state(item, "submitted", self.verified_notice(item))
                elif state in {"waiting", "blocked"}:
                    self.set_state(item, "existing")
                continue
            if state in {"submitting", "uncertain"}:
                self.set_state(item, "uncertain", self.uncertain_notice(item))
                continue
            if (
                state in {"waiting", "blocked"}
                and item["open_week"]
                and not item["report_dates"]
            ):
                self.set_state(
                    item,
                    "blocked",
                    f"【周汇报未提交】\n- {self.label(item)}\n- {REASONS['weekly_schedule_invalid']}\n{WEEKLY_PAGE}",
                )
                continue
            if state not in {"waiting", "blocked"} or not is_due(
                item, self.hour, self.policy
            ):
                continue
            if self.dry_run:
                continue
            if not self.submit_allowed:
                self.set_state(
                    item,
                    "blocked",
                    f"【周汇报未提交】\n- {self.label(item)}\n- 自动提交已关闭，请人工提交\n{WEEKLY_PAGE}",
                )
                continue
            with self.db:
                claimed = self.db.execute(
                    "UPDATE jobs SET state='submitting',attempted_at=? WHERE key=? AND state IN ('waiting','blocked')",
                    (current_time().isoformat(), item["key"]),
                ).rowcount
            if not claimed:
                continue
            try:
                result = await self.query(
                    {
                        "operation": "weekly_submit",
                        "expected": item,
                        "hour": self.hour,
                        "policy": self.policy,
                    }
                )
            except Exception:  # noqa: BLE001 - a lost worker response may follow a completed write
                result = {"outcome": "uncertain"}
            outcome = result.get("outcome")
            if outcome in {"submitted", "already_submitted"}:
                report = result.get("report", {})
                if (
                    report.get("key") != item["key"]
                    or report.get("status") != "SUBMITTED"
                    or not report.get("submitted_at")
                ):
                    self.set_state(item, "uncertain", self.uncertain_notice(item))
                    continue
                notice = (
                    self.verified_notice(report)
                    if outcome == "submitted"
                    else f"【周汇报已跳过】\n- {self.label(report)}\n- 学校已有提交记录，没有重复提交。"
                )
                self.set_state(
                    report,
                    "submitted" if outcome == "submitted" else "existing",
                    notice,
                )
            elif outcome == "not_due":
                self.set_state(item, "waiting")
            elif outcome == "not_sent":
                self.set_state(item, "waiting")
                failure = QueryError(result.get("reason", "weekly_prepare_failed"))
            elif outcome == "blocked":
                reason = REASONS.get(result.get("reason"), "学校检查未通过，请人工确认")
                self.set_state(
                    item,
                    "blocked",
                    f"【周汇报未提交】\n- {self.label(item)}\n- {reason}\n{WEEKLY_PAGE}",
                )
            else:
                self.set_state(item, "uncertain", self.uncertain_notice(item))
        for row in self.db.execute(
            "SELECT payload FROM jobs WHERE active=0 AND state='submitting'"
        ).fetchall():
            item = json.loads(row["payload"])
            self.set_state(item, "uncertain", self.uncertain_notice(item))
        await self.deliver_notices()
        if failure:
            raise failure
        policy = f"{self.policy}:{self.hour}"
        if self.get_meta("subscription") != policy:
            await self.send(self.status())
            self.set_meta("subscription", policy)

    def status(self):
        day = "首个" if self.policy == "first" else "最后一个"
        lines = [
            "【周汇报自动提交】",
            f"- 计划：系统{day}汇报日 {self.hour:02d}:00（北京时间）",
            "- 仅提交空汇报，不填写正文、不上传附件；已有学业信息时提醒人工确认。",
        ]
        checked = self.get_meta("checked_at")
        if not checked:
            return "\n".join([*lines, "- 等待首次读取学校数据。"])
        lines.append("- 最近同步：" + checked)
        today = current_time().date().isoformat()
        upcoming = []
        for row in self.db.execute(
            "SELECT payload,state FROM jobs WHERE semester=? AND (active=1 OR state IN ('submitting','uncertain'))",
            (self.get_meta("semester"),),
        ):
            item = json.loads(row["payload"])
            if row["state"] in {"submitting", "uncertain"}:
                lines.append(f"- 待核实：{self.label(item)}，不会重复提交。")
            if item["week_start"] <= today <= item["week_end"]:
                state = {
                    "SUBMITTED": "已提交",
                    "NOT_SUBMITTED": "未提交",
                    "CANCELLED": "已撤回，不自动重交",
                }[item["status"]]
                lines.append(
                    f"- 本期：{item['course']}，{state}"
                    + (f"（{item['submitted_at']}）" if item["submitted_at"] else "")
                )
            planned = scheduled_date(item, self.policy)
            if (
                item["open_week"]
                and item["status"] == "NOT_SUBMITTED"
                and planned
                and planned >= today
            ):
                upcoming.append((planned, item["course"]))
        if upcoming:
            planned, course = min(upcoming)
            lines.append(f"- 下次计划：{planned} {self.hour:02d}:00，{course}")
        else:
            lines.append("- 当前没有已公布且待提交的后续计划。")
        if self.get_meta("can_submit") == "False":
            lines.append("- 注意：当前账号没有周汇报提交权限。")
        return "\n".join(lines)
