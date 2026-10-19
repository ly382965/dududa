from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class QueryError(ValueError):
    def __init__(self, code):
        self.code = (
            code
            if isinstance(code, str)
            and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,79}", code)
            else "worker_query_failed"
        )
        super().__init__(self.code)


def query_error_reason(error):
    code = error.code if isinstance(error, QueryError) else type(error).__name__
    return {
        "cas_ticket_missing": "学校统一认证未返回登录票据",
        "cas_gateway_redirect_invalid": "学校认证跳转发生变化",
        "cas_gateway_redirect_limit": "学校认证跳转次数过多",
        "cas_ticket_target_invalid": "学校登录票据的目标地址异常",
        "campus_connection_timeout": "学校连接超时",
        "campus_connection_failed": "无法连接学校认证服务",
        "campus_portal_auth_failed": "研究生系统未接受登录认证",
        "campus_login_failed": "统一身份认证登录失败",
        "homework_identity_missing": "作业页未返回学生身份（可能是学校异常页或会话失效）",
        "homework_snapshot_incomplete": "学校作业总数与核验结果不一致，保留缓存，不能判断没有作业",
        "homework_session_expired": "研究生系统退回登录页，登录会话未建立或已失效",
        "campus_database_unavailable": "学校研究生系统数据库连接异常（连接池暂停或数据库不可用）",
        "campus_database_login_unavailable": "学校研究生系统数据库连接异常，无法完成门户登录",
        "AuthError": "学校登录认证失败",
        "seminar_list_incomplete": "讲座分页记录与学校总数不一致",
        "seminar_list_changed": "读取期间学校讲座列表发生变化",
        "seminar_repeated_page": "学校讲座接口重复返回同一页",
        "seminar_query_failed": "学校讲座接口查询失败",
        "weekly_owner_mismatch": "周汇报账号或学生身份核对失败",
        "weekly_login_redirect_invalid": "助教系统认证跳转发生变化",
        "weekly_api_rejected": "助教系统未接受请求",
        "weekly_schedule_invalid": "周汇报日期无法识别",
        "weekly_response_invalid": "周汇报数据格式发生变化",
        "weekly_pagination_invalid": "周汇报列表分页不完整",
    }.get(code, code)


@dataclass(frozen=True)
class Notification:
    id: str
    text: str


class DeliveryStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS deliveries ("
            "source TEXT NOT NULL, destination TEXT NOT NULL, item_id TEXT NOT NULL, "
            "message_id TEXT NOT NULL, sent_at TEXT NOT NULL, "
            "PRIMARY KEY (source, destination, item_id))"
        )
        self.connection.commit()

    def contains(self, source: str, recipient: str, item_id: str) -> bool:
        """Any earlier platform id counts: AstrBot recorded ``<platform>:FriendMessage:<qq>``."""
        return (
            self.connection.execute(
                "SELECT 1 FROM deliveries WHERE source = ? AND item_id = ? AND destination LIKE ?",
                (source, item_id, "%:FriendMessage:" + recipient),
            ).fetchone()
            is not None
        )

    def record(
        self, source: str, destination: str, item_id: str, message_id: str
    ) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO deliveries VALUES (?, ?, ?, ?, ?)",
                (
                    source,
                    destination,
                    item_id,
                    message_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def close(self) -> None:
        self.connection.close()


async def deliver(
    store: DeliveryStore,
    send: Callable[[str, str], Awaitable[str]],
    *,
    source: str,
    platform_id: str,
    recipient: str,
    notifications: Sequence[Notification],
    limit: int,
) -> int:
    destination = f"{platform_id}:FriendMessage:{recipient}"
    sent = 0
    for item in notifications:
        if sent >= limit:
            break
        if store.contains(source, recipient, item.id):
            continue
        message_id = await send(recipient, item.text)
        if not message_id:
            raise RuntimeError("private_message_not_acknowledged")
        store.record(source, destination, item.id, str(message_id))
        sent += 1
    return sent


def worker_environment(python: Path | None = None, proxy_url: str | None = None) -> dict[str, str]:
    campus_env = os.environ.copy()
    if proxy_url:
        # Foreign course sites (GitHub Pages) go through the Host's outbound proxy.
        for key in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
            campus_env.setdefault(key, proxy_url)
    campus_env["NO_PROXY"] = ",".join(
        filter(
            None,
            (
                campus_env.get("NO_PROXY", ""),
                campus_env.get("no_proxy", ""),
                ".ustc.edu.cn",
            ),
        )
    )
    campus_env["no_proxy"] = campus_env["NO_PROXY"]
    if python is not None:
        campus_env["DUDUDA_PORTAL_DIAGNOSTIC_DIR"] = str(
            Path(python).parent.parent.parent / "portal-diagnostics"
        )
    return campus_env


async def assignment_request(python: Path, request: dict, proxy_url: str | None = None) -> dict:
    process = await asyncio.create_subprocess_exec(
        str(python),
        str(Path(__file__).with_name("assignment_worker.py")),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=worker_environment(python, proxy_url),
    )
    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(
                json.dumps(request, ensure_ascii=False).encode("utf-8")
            ),
            timeout=300,
        )
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode:
        raise RuntimeError("homework_worker_failed")
    result = json.loads(stdout)
    if "error" in result:
        raise QueryError(result["error"])
    return result


async def fetch_snapshot(
    python: Path, credentials_file: str, timeout: float, proxy_url: str | None = None
) -> dict:
    process = await asyncio.create_subprocess_exec(
        str(python),
        str(Path(__file__).with_name("worker.py")),
        "--credentials-file",
        credentials_file,
        "--timeout",
        str(timeout),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=worker_environment(python, proxy_url),
    )
    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(), timeout=max(180, timeout * 4)
        )
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    try:
        snapshot = json.loads(stdout)
    except ValueError:
        raise QueryError("seminar_query_failed") from None
    if isinstance(snapshot, dict) and "error" in snapshot:
        raise QueryError(snapshot["error"])
    if process.returncode:
        raise QueryError("seminar_query_failed")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("reports"), list):
        raise TypeError("invalid_seminar_snapshot")
    return snapshot


PORTAL_URL = "https://yjs1.ustc.edu.cn/gsapp/sys/xsbgglappustc/*default/index.do"


def seminar_notifications(
    snapshot: dict, *, preferred_only: bool, interval: int
) -> list[Notification]:
    preference = "B 站直播和高新校区" if preferred_only else "所有地点"
    items = [
        Notification(
            "subscription",
            f"嘟嘟哒讲座通知已开启。\n每 {interval} 分钟检查一次，关注{preference}的可报名报告。\n"
            f"本次查询：可报名 {snapshot['available_count']} 场，"
            f"符合 B 站/高新偏好 {snapshot['recommended_count']} 场。\n"
            "有新报告会私聊提醒，同一报告只通知一次。",
        )
    ]
    for report in snapshot["reports"]:
        if report.get("available") is not True:
            continue
        if preferred_only and report.get("preferred") is not True:
            continue
        lines = ["【学术报告可报名】", str(report["title"])[:300]]
        for label, key in (
            ("报告人", "speaker"),
            ("时间", "time"),
            ("地点", "location"),
            ("院系", "department"),
            ("报名截止", "deadline"),
        ):
            if report.get(key):
                lines.append(f"{label}：{str(report[key])[:300]}")
        lines.extend(
            [
                f"剩余名额：{report['remaining']}",
                f"报告编号：{report['id']}",
                f"查询时间：{snapshot['fetched_at']}",
                PORTAL_URL,
            ]
        )
        items.append(Notification(f"report:{report['id']}", "\n".join(lines)))
    return items
