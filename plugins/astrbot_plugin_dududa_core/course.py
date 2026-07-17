from __future__ import annotations

import os
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from .config import ICOURSE_DB_PATH, ICOURSE_ROOT


class ICourseClient:
    def __init__(self, timeout_hint: float = 30.0):
        self.timeout_hint = timeout_hint
        self.command = "/usr/local/bin/python"
        self.args = [
            str(ICOURSE_ROOT / "run_icourse_mcp.py"),
            "--db-path",
            str(ICOURSE_DB_PATH),
            "--request-delay",
            "1.0",
        ]

    async def call(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=dict(os.environ),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args or {})
        text = "\n".join(getattr(item, "text", "") for item in result.content)
        return self._loads(text)

    async def list_tools(self) -> list[str]:
        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=dict(os.environ),
        )
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


def format_stats(stats: dict[str, Any]) -> str:
    return (
        "评课社区缓存状态\n"
        f"课程数：{stats.get('courses', 0)}\n"
        f"已抓详情：{stats.get('courses_with_detail', 0)}\n"
        f"公开点评：{stats.get('public_reviews', 0)}\n"
        f"最近详情抓取：{stats.get('last_detail_crawled_at') or '无'}\n"
        f"最近列表抓取：{stats.get('last_list_crawled_at') or '无'}"
    )


def format_search(result: dict[str, Any], query: str) -> str:
    items = result.get("items") or []
    if not items:
        return f"没有在本地评课缓存里找到：{query}\n可以让管理员用 /course refresh <课程ID> 刷新指定课程。"
    lines = [f"评课搜索：{query}", f"共命中 {result.get('total', len(items))} 条，显示前 {len(items)} 条："]
    for item in items[:10]:
        teachers = ", ".join(t.get("name", "") for t in item.get("teachers", []) if isinstance(t, dict))
        if not teachers:
            teachers = item.get("teacher_names") or ""
        lines.append(
            f"- {item.get('id')} | {item.get('name')} | {teachers or '教师未知'} | "
            f"评分 {item.get('rating_average') or '无'} | 点评 {item.get('review_count_site') or 0}"
        )
    return "\n".join(lines)


def format_review(course: dict[str, Any], reviews: list[dict[str, Any]]) -> str:
    name = course.get("name") or "未知课程"
    teachers = ", ".join(t.get("name", "") for t in course.get("teachers", []) if isinstance(t, dict))
    lines = [
        f"{name} 公开评课摘要",
        f"课程 ID：{course.get('id')}",
        f"教师：{teachers or '未知'}",
        f"评分：{course.get('rating_average') or '无'}",
        f"公开点评：{len(reviews)} 条可见缓存",
    ]
    for key, label in [
        ("difficulty", "考试/难度"),
        ("homework", "作业"),
        ("grading", "给分"),
        ("gain", "收获"),
    ]:
        if course.get(key):
            lines.append(f"{label}：{course.get(key)}")
    if reviews:
        lines.append("公开评论要点：")
        for review in reviews[:8]:
            text = (review.get("content_text") or "").strip().replace("\n", " ")
            if len(text) > 180:
                text = text[:180] + "..."
            lines.append(f"- {text or '无正文'}")
    lines.append("来源：icourse.club 公开缓存；不含登录后不可见内容。")
    return "\n".join(lines)
