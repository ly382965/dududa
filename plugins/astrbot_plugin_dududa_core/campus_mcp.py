from __future__ import annotations

import os
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from .config import (
    ACADEMIC_CALENDAR_DB,
    ACADEMIC_CALENDAR_ROOT,
    CAMPUS_EVENTS_DB,
    CAMPUS_EVENTS_ROOT,
    COLLEGE_NOTICE_DB,
    COLLEGE_NOTICE_ROOT,
    LIBRARY_DB,
    LIBRARY_ROOT,
    LOCAL_RECS_DB,
    LOCAL_RECS_ROOT,
    TRAINING_PLAN_DB,
    TRAINING_PLAN_ROOT,
)


class McpClient:
    """通用 stdio MCP 客户端，复刻 ICourseClient 的连接方式。"""

    def __init__(self, root, db_path, script_name: str, timeout_hint: float = 30.0, extra_args: list[str] | None = None):
        self.timeout_hint = timeout_hint
        self.command = "/usr/local/bin/python"
        self.args = [
            str(root / script_name),
            "--db-path",
            str(db_path),
        ]
        if extra_args:
            self.args.extend(extra_args)

    async def call(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        params = StdioServerParameters(command=self.command, args=self.args, env=dict(os.environ))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args or {})
        text = "\n".join(getattr(item, "text", "") for item in result.content)
        return self._loads(text)

    async def list_tools(self) -> list[str]:
        params = StdioServerParameters(command=self.command, args=self.args, env=dict(os.environ))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [tool.name for tool in tools.tools]

    @staticmethod
    def _loads(text: str) -> Any:
        import json

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}


def college_notice_client() -> McpClient:
    return McpClient(COLLEGE_NOTICE_ROOT, COLLEGE_NOTICE_DB, "run_college_notice_mcp.py")


def training_plan_client() -> McpClient:
    return McpClient(TRAINING_PLAN_ROOT, TRAINING_PLAN_DB, "run_training_plan_mcp.py")


def library_client() -> McpClient:
    return McpClient(LIBRARY_ROOT, LIBRARY_DB, "run_library_mcp.py")


def campus_events_client() -> McpClient:
    return McpClient(CAMPUS_EVENTS_ROOT, CAMPUS_EVENTS_DB, "run_campus_events_mcp.py")


def academic_calendar_client() -> McpClient:
    return McpClient(
        ACADEMIC_CALENDAR_ROOT, ACADEMIC_CALENDAR_DB, "run_academic_calendar_mcp.py"
    )


def local_recs_client() -> McpClient:
    return McpClient(LOCAL_RECS_ROOT, LOCAL_RECS_DB, "run_local_recs_mcp.py")


# ---------- college notice ----------

def format_college_stats(stats: dict[str, Any]) -> str:
    lines = ["学院通知缓存状态"]
    for item in stats.get("colleges", []):
        lines.append(f"- {item.get('college_key')}：{item.get('c', 0)} 条")
    lines.append(f"最近同步：{stats.get('latest_at') or '无'}")
    return "\n".join(lines)


def format_college_notices(result: dict[str, Any], college_name: str | None = None) -> str:
    items = result.get("notices") or []
    if not items:
        return "没有找到匹配的学院通知，可先用 /notice list 查看全量，或让管理员刷新缓存。"
    lines = [f"学院通知：{college_name or '全部'}", f"共 {len(items)} 条："]
    for item in items[:10]:
        title = (item.get("title") or "").strip()
        if len(title) > 42:
            title = title[:42] + "..."
        date = (item.get("published_at") or "").split("T")[0]
        lines.append(f"- {date or '??'} {title}")
    return "\n".join(lines)


# ---------- training plan ----------

def format_plan_stats(stats: dict[str, Any]) -> str:
    return (
        "培养方案缓存状态\n"
        f"年份数：{stats.get('years', 0)}\n"
        f"专业记录：{stats.get('rows', 0)}\n"
        f"最近年份：{stats.get('latest_year') or '无'}\n"
        f"最近同步：{stats.get('last_fetched_at') or '无'}"
    )


def format_majors(result: dict[str, Any]) -> str:
    items = result.get("majors") or []
    if not items:
        return "没有找到培养方案记录。"
    header = f"培养方案专业（{result.get('year') or '?'} 年）"
    lines = [header]
    for item in items[:15]:
        dept = item.get("dept") or item.get("college") or ""
        major = item.get("major") or ""
        code = item.get("code") or ""
        degree = item.get("degree") or ""
        flag = "（停招）" if item.get("discontinued") else ""
        lines.append(f"- {dept} | {major}{flag} {code} {degree}".rstrip())
    if len(items) > 15:
        lines.append(f"... 共 {len(items)} 条")
    return "\n".join(lines)


# ---------- library ----------

def format_library_stats(stats: dict[str, Any]) -> str:
    lines = ["图书馆开放时间缓存"]
    for item in stats.get("campuses", []):
        lines.append(f"- {item.get('campus')}：{item.get('c', 0)} 项")
    lines.append(f"最近同步：{stats.get('last_fetched_at') or '无'}")
    return "\n".join(lines)


def format_opening_hours(result: dict[str, Any]) -> str:
    rows = result.get("rows") or []
    if not rows:
        return "没有找到开放时间记录，可让管理员用 /admin mcp refresh library 拉取。"
    campus = result.get("campus") or ""
    lines = [f"图书馆开放时间{f'（{campus}）' if campus else ''}"]
    for row in rows[:20]:
        parts = [row.get("service") or ""]
        weekday = row.get("weekday")
        weekend = row.get("weekend")
        if weekday:
            parts.append(f"周一至周五 {weekday}")
        if weekend:
            parts.append(f"周六日 {weekend}")
        if row.get("phone"):
            parts.append(f"电话 {row.get('phone')}")
        lines.append("- " + " | ".join(p for p in parts if p))
    return "\n".join(lines)


# ---------- campus events ----------

def format_event_stats(stats: dict[str, Any]) -> str:
    lines = ["校园通知缓存状态"]
    for item in stats.get("categories", []):
        lines.append(f"- {item.get('category')}：{item.get('c', 0)} 条")
    lines.append(f"最近更新：{stats.get('latest_at') or '无'}")
    return "\n".join(lines)


def format_events(result: dict[str, Any], category: str | None = None) -> str:
    items = result.get("events") or []
    if not items:
        return "没有校园通知缓存，可让管理员用 /admin mcp refresh campus_events 拉取。"
    lines = [f"校园通知{f'（{category}）' if category else ''}", f"共 {len(items)} 条："]
    for item in items[:10]:
        title = (item.get("title") or "").strip()
        if len(title) > 42:
            title = title[:42] + "..."
        date = (item.get("published_at") or "").split("T")[0]
        lines.append(f"- {date or '??'} {title}")
    return "\n".join(lines)


# ---------- academic calendar ----------

def format_calendar_stats(stats: dict[str, Any]) -> str:
    return (
        "教学日历缓存状态\n"
        f"学期数：{stats.get('terms_known', 0)}\n"
        f"已抓取详情：{stats.get('terms_fetched', 0)}\n"
        f"事件数：{stats.get('dated_events', 0)}\n"
        f"假日/无课日：{stats.get('off_days', 0)}\n"
        f"最近同步：{stats.get('last_fetched_at') or '无'}"
    )


def format_terms(result: dict[str, Any]) -> str:
    terms = result.get("terms") or []
    if not terms:
        return "没有教学日历缓存，可让管理员用 /admin mcp refresh calendar 拉取。"
    lines = [f"已知学期（{len(terms)}）："]
    for term in terms[:15]:
        name = term.get("name") or term.get("term_name") or "?"
        if isinstance(term, str):
            name = term
        lines.append(f"- {name}")
    return "\n".join(lines)


def format_current_term(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return "当前学期未缓存，可让管理员用 /admin mcp refresh calendar 拉取。"
    term_name = result.get("term_name") or "?"
    lines = [f"当前学期：{term_name}", f"今天（{result.get('today')}）事件："]
    events = result.get("events_today") or []
    if not events:
        lines.append("- 暂无安排")
    for item in events[:10]:
        title = (item.get("event_name") or "").strip()
        lines.append(f"- {title}")
    weeks = result.get("week_labels") or []
    if weeks:
        lines.append(f"本学期周次：{len(weeks)} 周")
    return "\n".join(lines)


def format_calendar_events(result: dict[str, Any]) -> str:
    events = result.get("events") or []
    date = result.get("date") or ""
    if not events:
        return f"{date} 没有安排，或该日期不在已缓存学期内。"
    lines = [f"{date} 教学安排："]
    for item in events[:15]:
        term = item.get("term_name") or item.get("term") or ""
        title = (item.get("event_name") or "").strip()
        week = item.get("week_label") or ""
        lines.append(f"- [{term}] {week} {title}".rstrip())
    if len(events) > 15:
        lines.append(f"... 共 {len(events)} 条")
    return "\n".join(lines)


def format_food_recommendation(result: dict[str, Any]) -> str:
    """格式化'吃什么'推荐结果。"""
    if not result.get("ok"):
        return "暂时没有推荐数据，可让管理员用 /admin mcp refresh 补充。"
    rec = result.get("recommendation") or {}
    name = rec.get("name") or "?"
    detail = rec.get("detail") or ""
    location = rec.get("location") or ""
    proximity = rec.get("proximity") or ""
    score = rec.get("score") or 0
    meal_time = result.get("meal_time") or ""
    is_thursday = result.get("is_thursday") or False
    opening = result.get("opening_hours") or {}
    map_link = result.get("map_link") or ""
    price = rec.get("price_level") or ""

    lines = []
    if is_thursday:
        lines.append(f"今天是星期四！{name} 疯狂星期四，快去！")
    else:
        emoji_map = {"早餐": "早餐", "午餐": "午餐", "晚餐": "晚餐", "夜宵": "夜宵"}
        lines.append(f"今日{emoji_map.get(meal_time, meal_time)}推荐：{name}")

    if detail:
        lines.append(f"  {detail}")
    if location:
        lines.append(f"  位置：{location}")
    if proximity:
        lines.append(f"  距离：{proximity}")
    if price:
        lines.append(f"  价位：{price}")
    if score:
        lines.append(f"  评分：{score}")
    if opening:
        hours_str = " / ".join(f"{k}{v}" for k, v in opening.items())
        lines.append(f"  营业：{hours_str}")
    if map_link:
        lines.append(f"  地图：{map_link}")

    return "\n".join(lines)
