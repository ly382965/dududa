from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path

from .notifications import PORTAL_URL


class SeminarBookingService:
    """At most one possible submission per account/report, with a durable outbox.

    A committed claim is released only on an explicit no-write unavailable result,
    never after poll cancellation or response loss. Snapshots must be complete.
    The sender must deduplicate the supplied key: a crash after delivery but before
    its acknowledgement is recorded necessarily causes an at-least-once delivery.
    """

    def __init__(
        self,
        root: Path,
        book: Callable[[dict], Awaitable[dict]],
        send: Callable[[str, str], Awaitable[object]],
    ) -> None:
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.book, self.send = book, send
        self._lock = asyncio.Lock()
        self.db = sqlite3.connect(root / "seminar-bookings.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS bookings (
                account_key TEXT NOT NULL,
                report_id TEXT NOT NULL,
                report TEXT NOT NULL,
                state TEXT NOT NULL,
                attempted INTEGER NOT NULL DEFAULT 0,
                attempt INTEGER NOT NULL DEFAULT 0,
                ever_selected INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (account_key, report_id)
            );
            CREATE TABLE IF NOT EXISTS notices (
                account_key TEXT NOT NULL,
                report_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                text TEXT NOT NULL,
                delivered INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (account_key, report_id, outcome, attempt)
            );
        """)

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def _report(report: dict) -> dict:
        # Persist only presentation fields, never an authenticated worker payload.
        payload = {
            key: str(report.get(key) or "").replace("\r", " ").replace("\n", " ")[:300]
            for key in ("id", "title", "time", "location")
        }
        withdrawal = report.get("cancellable")
        payload["cancellable"] = withdrawal if isinstance(withdrawal, bool) else None
        return payload

    def _notice(self, account: str, report: dict, outcome: str) -> None:
        headings = {
            "booked": ("学术报告报名成功", "已读取学校已选列表，确认报名成功。"),
            "selected": ("学术报告已选中", "已核对学校已选列表，确认当前已选中；没有重复报名。"),
            "uncertain": ("学术报告报名待核实", "报名结果尚未确认，可能已经生效；将只读核对，不会重复报名。"),
            "rejected": ("学术报告报名未成功", "学校未接受本次报名，请在学校门户人工处理；不会自动重试。"),
            "unavailable": ("学术报告未报名", "复查时可报名条件、偏好或自动报名开关不满足；未发起报名，后续会重新检查。"),
            "withdrawn": ("学术报告不再选中", "此前已确认选中，但本次学校已选列表中已无此报告；不会自动重新报名。"),
        }
        heading, explanation = headings[outcome]
        if outcome in {"booked", "selected"}:
            withdrawal = report.get("cancellable")
            if withdrawal is True:
                explanation += "\n退选状态：核对时可退选；学校未提供退选截止时间，状态可能变化。"
            elif withdrawal is False:
                explanation += "\n退选状态：核对时不可退选，请在学校门户确认限制。"
            else:
                explanation += "\n退选状态：学校未返回，需在学校门户确认。"
        text = "\n".join([
            f"【{heading}】",
            report.get("title") or "报告标题暂不可用",
            f"时间：{report.get('time') or '请在学校门户查看'}",
            f"地点：{report.get('location') or '请在学校门户查看'}",
            f"报告编号：{report['id']}",
            explanation,
            "如需退选，请在学校门户手动操作，能否退选以学校规则为准；退选后不会自动重新报名。",
            PORTAL_URL,
        ])
        # A newer observation supersedes an unsent obsolete outcome. Retain sent
        # rows so that a later reconciliation never resets their dedupe history.
        attempt = self.db.execute(
            "SELECT attempt FROM bookings WHERE account_key=? AND report_id=?",
            (account, report["id"]),
        ).fetchone()["attempt"]
        self.db.execute(
            "UPDATE notices SET active=0 WHERE account_key=? AND report_id=?",
            (account, report["id"]),
        )
        self.db.execute(
            "INSERT INTO notices(account_key,report_id,outcome,attempt,text) VALUES(?,?,?,?,?) "
            "ON CONFLICT(account_key,report_id,outcome,attempt) DO UPDATE SET text=excluded.text,active=1",
            (account, report["id"], outcome, attempt, text),
        )

    def _reconcile(self, account: str, selected: set[str], reports: dict[str, dict]) -> None:
        # No awaits inside this transaction. Observations and their notices commit
        # together, before any possible enrollment for an unobserved report.
        with self.db:
            for report_id in selected:
                payload = self._report(reports.get(report_id, {"id": report_id}))
                self.db.execute(
                    "INSERT OR IGNORE INTO bookings(account_key,report_id,report,state,ever_selected) "
                    "VALUES(?,?,?,'selected',1)",
                    (account, report_id, json.dumps(payload, ensure_ascii=False)),
                )
            rows = self.db.execute(
                "SELECT * FROM bookings WHERE account_key=?", (account,)
            ).fetchall()
            for row in rows:
                report = json.loads(row["report"])
                if row["report_id"] in selected:
                    if row["ever_selected"] and row["state"] != "withdrawn":
                        continue
                    # This snapshot proves selection, but carries no withdrawal status.
                    report["cancellable"] = None
                    self.db.execute(
                        "UPDATE bookings SET state='selected',ever_selected=1,report=? "
                        "WHERE account_key=? AND report_id=?",
                        (json.dumps(report, ensure_ascii=False), account, row["report_id"]),
                    )
                    if row["attempted"]:
                        self._notice(account, report, "selected")
                elif row["ever_selected"] and row["state"] != "withdrawn":
                    self.db.execute(
                        "UPDATE bookings SET state='withdrawn' WHERE account_key=? AND report_id=?",
                        (account, row["report_id"]),
                    )
                    if row["attempted"]:
                        self._notice(account, report, "withdrawn")

    def _claim(self, account: str, report: dict) -> bool:
        with self.db:
            claimed = self.db.execute(
                "INSERT OR IGNORE INTO bookings(account_key,report_id,report,state,attempted,attempt) "
                "VALUES(?,?,?,'uncertain',1,1)",
                (account, report["id"], json.dumps(report, ensure_ascii=False)),
            ).rowcount
            if not claimed:
                claimed = self.db.execute(
                    "UPDATE bookings SET state='uncertain',attempt=attempt+1,report=? "
                    "WHERE account_key=? AND report_id=? AND state='unavailable' AND ever_selected=0",
                    (json.dumps(report, ensure_ascii=False), account, report["id"]),
                ).rowcount
            if claimed:
                # Even process termination during await book leaves a deliverable,
                # honest notice and a permanent prohibition on another attempt.
                self._notice(account, report, "uncertain")
        return bool(claimed)

    def _outcome(self, account: str, report: dict, result: object) -> None:
        status = result.get("status") if isinstance(result, dict) else None
        if not isinstance(status, str) or status not in {"booked", "already_selected", "rejected", "unavailable", "uncertain"}:
            status = "uncertain"
        returned = result.get("report") if isinstance(result, dict) else None
        if returned is not None:
            if not isinstance(returned, dict) or returned.get("id") != report["id"]:
                status = "uncertain"
            else:
                report = self._report({**report, **returned})
        with self.db:
            row = self.db.execute(
                "SELECT ever_selected FROM bookings WHERE account_key=? AND report_id=?",
                (account, report["id"]),
            ).fetchone()
            # Another poll may already have confirmed selection (and subsequently
            # withdrawal). A late worker response must not undo that observation.
            if row["ever_selected"]:
                return
            selected = status in {"booked", "already_selected"}
            outcome = "selected" if status == "already_selected" else status
            self.db.execute(
                "UPDATE bookings SET state=?,ever_selected=?,report=? "
                "WHERE account_key=? AND report_id=?",
                (outcome, int(selected), json.dumps(report, ensure_ascii=False), account, report["id"]),
            )
            self._notice(account, report, outcome)

    async def _deliver(self, account: str) -> None:
        rows = self.db.execute(
            "SELECT report_id,outcome,attempt,text FROM notices "
            "WHERE account_key=? AND delivered=0 AND active=1 ORDER BY report_id,outcome",
            (account,),
        ).fetchall()
        for row in rows:
            # Another service may have superseded this outcome during an earlier
            # send. Never send an already obsolete notice from the local row list.
            pending = self.db.execute(
                "SELECT 1 FROM notices WHERE account_key=? AND report_id=? AND outcome=? "
                "AND attempt=? AND delivered=0 AND active=1",
                (account, row["report_id"], row["outcome"], row["attempt"]),
            ).fetchone()
            if pending is None:
                continue
            digest = hashlib.sha256(
                json.dumps(
                    [account, row["report_id"], row["outcome"], row["attempt"]],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            await self.send(row["text"], f"seminar-booking:{digest}")
            with self.db:
                self.db.execute(
                    "UPDATE notices SET delivered=1 WHERE account_key=? AND report_id=? AND outcome=? AND attempt=?",
                    (account, row["report_id"], row["outcome"], row["attempt"]),
                )

    async def poll(self, snapshot: dict, *, enabled: bool, preferred_only: bool) -> None:
        account = snapshot.get("account_key")
        selected = snapshot.get("selected_ids")
        reports = snapshot.get("reports")
        if (
            not isinstance(account, str)
            or re.fullmatch(r"[0-9a-f]{64}", account) is None
            or not isinstance(selected, list)
            or any(
                not isinstance(value, str) or not value or len(value) > 300
                or "\n" in value or "\r" in value
                for value in selected
            )
            or len(set(selected)) != len(selected)
            or not isinstance(reports, list)
            or any(
                not isinstance(report, dict)
                or not isinstance(report.get("id"), str)
                or not report["id"]
                or len(report["id"]) > 300
                or "\n" in report["id"]
                or "\r" in report["id"]
                for report in reports
            )
            or len({report["id"] for report in reports}) != len(reports)
        ):
            raise ValueError("seminar_snapshot_invalid")
        async with self._lock:
            self._reconcile(account, set(selected), {report["id"]: report for report in reports})
            if enabled:
                for item in reports:
                    if item.get("available") is not True:
                        continue
                    if preferred_only and item.get("preferred") is not True:
                        continue
                    report = self._report(item)
                    if not self._claim(account, report):
                        continue
                    try:
                        result = await self.book({
                            "operation": "seminar_book",
                            "report_id": report["id"],
                            "account_key": account,
                            "preferred_only": preferred_only,
                        })
                    except Exception:  # noqa: BLE001 - a lost response may follow a successful write
                        result = {"status": "uncertain"}
                    self._outcome(account, report, result)
            await self._deliver(account)
