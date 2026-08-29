from __future__ import annotations

import os
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from .config import CATALOG_DB_PATH, CATALOG_ROOT


class CatalogClient:
    """Thin client that spawns the catalog-mcp stdio server on demand."""

    def __init__(self, timeout_hint: float = 60.0):
        self.timeout_hint = timeout_hint
        self.command = "/usr/local/bin/python"
        self.args = [
            str(CATALOG_ROOT / "run_catalog_mcp.py"),
            "--db-path",
            str(CATALOG_DB_PATH),
            "--request-delay",
            "0.5",
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

    @staticmethod
    def _loads(text: str) -> Any:
        import json

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}


def _fmt_time(t: str | None) -> str:
    if not t:
        return "时间未提供"
    # dateTimePlaceText format: "2304: 2(3,4);2304: 4(6,7)"
    parts = [p.strip() for p in t.split(";") if p.strip()]
    if not parts:
        return t
    out = []
    for p in parts:
        m = __import__("re").match(r"\s*([\w\-\u4e00-\u9fff/]+):\s*(.*)", p)
        if m:
            out.append(f"{m.group(1)} {m.group(2).strip()}")
        else:
            out.append(p)
    return "；\n".join(out)


def format_open_result(result: dict[str, Any], query: str) -> str:
    items = result.get("results") or []
    if not items:
        return f"没找到「{query}」的开课信息，试试课程全名或代码~"
    lines = []
    for it in items[:6]:
        name = it.get("name_zh") or it.get("name_en") or it.get("course_code") or "未知课程"
        cap = it.get("limit_count")
        std = it.get("std_count")
        cap_txt = f"{std}/{cap}" if cap is not None else "容量未知"
        campus = it.get("campus_zh") or ""
        dept = it.get("dept_zh") or ""
        exam = it.get("exam_mode_zh") or ""
        credits = it.get("credits")
        line = [
            f"《{name}》",
            f"  已选/容量：{cap_txt}",
        ]
        if credits:
            line.append(f"  学分：{credits}")
        time_txt = _fmt_time(it.get("date_time_place_text"))
        line.append(f"  上课：{time_txt}")
        if it.get("campus_zh"):
            line.append(f"  校区：{campus}")
        if it.get("teachers_zh"):
            line.append(f"  老师：{it.get('teachers_zh')}")
        if exam:
            line.append(f"  考核：{exam}")
        if dept:
            line.append(f"  开课院系：{dept}")
        lines.append("\n".join(line))
    return "\n".join(lines)
