from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from dududa.domain.primitives import RuntimeBudget, TraceContext
from dududa.errors import DududaError, ErrorCategory, error
from dududa.mcp import (
    McpCallContext,
    McpOperationSemantics,
    mcp_tool_request_digest,
)
from dududa.ports.context import NeverCancelled, ServiceCallContext, ServicePrincipal
from dududa.ports.mcp import UnifiedMcpClient

ICOURSE_COMPAT_TOOL_ALLOWLIST = frozenset(
    {
        "icourse_stats",
        "search_courses",
        "get_course",
        "get_reviews",
        "search_site_courses",
        "crawl_course",
    }
)


class ICourseClient:
    """Compatibility facade backed only by the governed Unified MCP Client."""

    def __init__(
        self,
        unified_client: UnifiedMcpClient,
        *,
        owns_client: bool = True,
        timeout_hint: float = 30.0,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(unified_client, UnifiedMcpClient):
            raise TypeError("unified_client must implement UnifiedMcpClient")
        if not isinstance(timeout_hint, (int, float)) or timeout_hint <= 0:
            raise ValueError("timeout_hint must be positive")
        if type(owns_client) is not bool:
            raise TypeError("owns_client must be bool")
        self._client = unified_client
        self._owns_client = owns_client
        self.timeout_hint = float(timeout_hint)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    async def call(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        arguments = dict(args or {})
        caller = self._call_context("call", tool)
        schema = await self._client.discover("icourse", call=caller)
        semantics = _icourse_semantics(tool, arguments)
        request_digest = mcp_tool_request_digest(
            "icourse",
            tool,
            arguments,
            schema,
            semantics,
            None,
        )
        result = await self._client.call_tool(
            "icourse",
            tool,
            arguments,
            call=McpCallContext(
                schema_version=1,
                caller=caller,
                schema_snapshot_id=schema.snapshot_id,
                schema_snapshot_digest=schema.snapshot_digest,
                request_digest=request_digest,
                semantics=semantics,
            ),
        )
        if result.structured_content is not None:
            return _plain_json(result.structured_content)
        text = "\n".join(
            item.text or "" for item in result.content if item.text is not None
        )
        return self._loads(text)

    async def list_tools(self) -> list[str]:
        schema = await self._client.discover(
            "icourse",
            call=self._call_context("discover", "list_tools"),
        )
        discovered = {item.name for item in schema.tools}
        return sorted(discovered & ICOURSE_COMPAT_TOOL_ALLOWLIST)

    @property
    def unified_client(self) -> UnifiedMcpClient:
        return self._client

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()

    def _call_context(self, operation: str, tool: str) -> ServiceCallContext:
        now = self._clock()
        identity = self._id_factory()
        return ServiceCallContext(
            operation_id=f"icourse:{identity}",
            principal=ServicePrincipal(
                service_id="astrbot-plugin-dududa-core",
                instance_id="icourse-compat",
                roles=frozenset({"icourse-compat"}),
            ),
            operation_kind=f"icourse_{operation}:{tool}",
            trace=TraceContext(f"icourse:{identity}"),
            deadline=now + timedelta(seconds=self.timeout_hint),
            cancellation=NeverCancelled(),
            budget=RuntimeBudget(
                model_calls_remaining=0,
                tool_steps_remaining=1,
                retries_remaining=1,
                input_tokens_remaining=0,
                output_tokens_remaining=0,
                cost_units_remaining=Decimal(0),
            ),
            policy_snapshot_id="icourse-compat-v1",
        )

    @staticmethod
    def _loads(text: str) -> Any:
        import json

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}


ICOURSE_UNAVAILABLE_REASONS = frozenset(
    {
        "unified_path_not_absolute",
        "unified_infrastructure_missing",
        "icourse_definition_disabled",
        "unified_composition_invalid",
    }
)


class UnavailableICourseClient:
    """Fail-closed facade used when Unified MCP cannot be composed at startup."""

    def __init__(self, reason: str) -> None:
        if reason not in ICOURSE_UNAVAILABLE_REASONS:
            raise ValueError("invalid iCourse unavailable reason")
        self.reason = reason

    async def call(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        raise self._error()

    async def list_tools(self) -> list[str]:
        raise self._error()

    async def close(self) -> None:
        return None

    def _error(self) -> DududaError:
        return error(
            "icourse_client_unavailable",
            ErrorCategory.EXTERNAL,
            "mcp.unavailable",
            self.reason,
        )


def _icourse_semantics(
    tool: str, arguments: Mapping[str, object]
) -> McpOperationSemantics:
    if tool in {"icourse_stats", "search_courses", "get_reviews"}:
        return McpOperationSemantics.READ_ONLY
    if tool == "get_course" and arguments.get("refresh", False) is False:
        return McpOperationSemantics.READ_ONLY
    return McpOperationSemantics.NON_IDEMPOTENT


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


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
    lines = [
        f"评课搜索：{query}",
        f"共命中 {result.get('total', len(items))} 条，显示前 {len(items)} 条：",
    ]
    for item in items[:10]:
        teachers = ", ".join(
            t.get("name", "") for t in item.get("teachers", []) if isinstance(t, dict)
        )
        if not teachers:
            teachers = item.get("teacher_names") or ""
        lines.append(
            f"- {item.get('id')} | {item.get('name')} | {teachers or '教师未知'} | "
            f"评分 {item.get('rating_average') or '无'} | 点评 {item.get('review_count_site') or 0}"
        )
    return "\n".join(lines)


def format_review(course: dict[str, Any], reviews: list[dict[str, Any]]) -> str:
    name = course.get("name") or "未知课程"
    teachers = ", ".join(
        t.get("name", "") for t in course.get("teachers", []) if isinstance(t, dict)
    )
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
