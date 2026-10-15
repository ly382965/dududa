from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
RELEASE_TIME_PATTERN = re.compile(
    r"下次释放时间[：:]\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
)
QUEUE_WAIT_PATTERN = re.compile(
    r"预计\s*(?:(\d+)\s*分(?:钟)?)?\s*(?:(\d+)\s*秒)?后查询完毕"
)


def normalize_argument(value: str | int | None) -> str:
    return "" if value is None else str(value).strip()


def command_after_reply(phase: str, friend_code: str) -> str | None:
    if phase == "unbind":
        return f"/a bind {friend_code}"
    if phase == "bind":
        return "/ab50"
    return None


def is_query_queue_ack(message: str) -> bool:
    return "已加入查询队列" in message


def estimated_completion_time(
    message: str,
    now: datetime,
) -> datetime | None:
    match = QUEUE_WAIT_PATTERN.search(message)
    if not match or not any(match.groups()):
        return None
    minutes = int(match.group(1) or 0)
    seconds = int(match.group(2) or 0)
    try:
        return now + timedelta(minutes=minutes, seconds=seconds)
    except OverflowError:
        return None


def quota_release_time(message: str) -> datetime | None:
    if "当前时段的查分配额已用尽" not in message:
        return None
    match = RELEASE_TIME_PATTERN.search(message)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=SHANGHAI
        )
    except ValueError:
        return None
