"""Scope-bound, read-only services shared by rules and the native MCP server."""

from __future__ import annotations

import importlib.util
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener, urlopen
from zoneinfo import ZoneInfo

from .config import Settings
from .store import Store


class ServiceError(ValueError):
    pass


def summary_window(text: str) -> tuple[str, float | None] | None:
    """Resolve the supported summary expressions before model-selected tool arguments."""
    if not re.match(r"^\s*(?:请(?:你)?|请帮我|帮我|帮忙|麻烦(?:你)?)?\s*(?:总结|汇总|回顾)", text):
        return None
    if re.search(r"今日|今天", text):
        return "today", None
    match = re.search(r"(?:最近|近|过去)\s*(\d+(?:\.\d+)?)\s*(小时|h(?:ours?)?|分钟|min|m|天|days?|d)", text, re.IGNORECASE)
    if match:
        hours = float(match[1])
        unit = match[2].lower()
        if unit in ("分钟", "min", "m"):
            hours /= 60
        elif unit in ("天", "day", "days", "d"):
            hours *= 24
        return "recent", hours
    if re.search(r"最近|过去|昨天|昨日|前天|本周|本月", text):
        return None
    return "recent", 3


def tool_definitions() -> list[dict[str, Any]]:
    definitions = [
        ("shuttle_query", "查询中国科大本地校车时刻表快照；无需网络或 LLM。", {
            "query": {"type": "string", "description": "起终校区、日期、时间，例如工作日东区到西区最早一班", "minLength": 1, "maxLength": 2000},
        }, ["query"]),
        ("memory_search", "搜索当前会话的已保存记忆，不读取其他群或私聊。", {
            "query": {"type": "string", "description": "子串关键词；留空列出当前会话最近记忆", "maxLength": 2000},
        }, []),
        ("context_recent", "读取当前会话最近的聊天消息，不读取其他会话。", {
            "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 12},
        }, []),
        ("conversation_history", "按时间从 QQ 网关分页读取当前会话。默认最近3小时，最多1000条；今日用period=today，近5h用hours=5。返回实际数量、时间窗口与是否达到上限。", {
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 1000},
            "hours": {"type": "number", "exclusiveMinimum": 0, "maximum": 168,
                      "description": "最近多少小时，未指定默认3小时；period=today时省略"},
            "period": {"type": "string", "enum": ["recent", "today"], "default": "recent",
                       "description": "today从北京时间今日零点开始，recent按hours读取"},
        }, []),
        ("services_list", "列出本地服务及当前会话允许调用的公开校园能力和参数结构。", {}, []),
        ("campus_query", "调用显式启用的公开只读校园能力；先用 services_list 查看能力与参数。", {
            "capability_id": {"type": "string", "minLength": 1},
            "arguments": {"type": "object", "description": "对应校园能力 inputSchema 的查询参数"},
        }, ["capability_id"]),
    ]
    return [
        {
            "name": name,
            "description": description,
            "inputSchema": {"type": "object", "properties": properties,
                            "required": required, "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "destructiveHint": False,
                            "idempotentHint": True,
                            "openWorldHint": name in {"campus_query", "services_list", "conversation_history"}},
        }
        for name, description, properties, required in definitions
    ]


class ServiceHub:
    def __init__(self, settings: Settings, store: Store, session_id: int, run_id: str):
        self.settings, self.store = settings, store
        self.session_id, self.run_id = session_id, run_id
        with store.connect() as db:
            row = db.execute("SELECT scope FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise ServiceError("会话不存在")
        # Identity comes exclusively from the Host's session, never tool args.
        scope = []
        try:
            scope = json.loads(row["scope"])
            conversation = scope[1] if isinstance(scope, list) and len(scope) > 1 else ""
        except (ValueError, TypeError):
            conversation = ""
        self.context = "private" if ":private:" in conversation else "group"
        self.account_id = scope[0] if isinstance(scope, list) and len(scope) > 1 else ""
        self.conversation_id = conversation
        self._shuttle = None

    @staticmethod
    def tool_definitions() -> list[dict[str, Any]]:
        return tool_definitions()

    def call(self, name: str, args: dict[str, Any] | None = None) -> Any:
        definitions = {item["name"]: item for item in tool_definitions()}
        if name not in definitions:
            raise ServiceError("未知的只读服务")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise ServiceError("工具参数必须是对象")
        schema = definitions[name]["inputSchema"]
        if set(args) - set(schema["properties"]) or set(schema["required"]) - set(args):
            raise ServiceError("工具参数缺失或包含不允许的字段")
        self.store.record_tool(self.run_id, name)
        return getattr(self, name)(**args)

    def shuttle_query(self, query: str) -> dict[str, Any]:
        self._text(query, nonempty=True)
        if self._shuttle is None:
            path = self.settings.root / "services/builtin/shuttle/service.py"
            spec = importlib.util.spec_from_file_location("dududa_shuttle_service", path)
            if spec is None or spec.loader is None:
                raise ServiceError("本地校车服务未安装")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._shuttle = module.ShuttleSchedule()
        return self._shuttle.query(query)

    def memory_search(self, query: str = "") -> dict[str, Any]:
        self._text(query)
        return {"items": self.store.memories(self.session_id, query)}

    def context_recent(self, limit: int = 12) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 30:
            raise ServiceError("limit 必须为 1–30 的整数")
        return {"items": self.store.recent(self.session_id, limit)}

    def conversation_history(self, limit: int = 1000, hours: float | None = None, period: str = "recent") -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ServiceError("limit 必须为 1–1000 的整数")
        with self.store.connect() as db:
            row = db.execute("SELECT request FROM runs WHERE id=?", (self.run_id,)).fetchone()
        requested_window = summary_window(str(json.loads(row[0]).get("text", ""))) if row else None
        if requested_window:
            period, hours = requested_window
        if period not in ("recent", "today"):
            raise ServiceError("period 必须为 recent 或 today")
        if hours is not None and (type(hours) not in (int, float) or not 0 < hours <= 168):
            raise ServiceError("hours 必须大于0且不超过168")
        if period == "today" and hours is not None:
            raise ServiceError("今日窗口请使用 period=today 并省略 hours")
        local_zone = ZoneInfo("Asia/Shanghai")
        until = datetime.now(local_zone)
        since = until.replace(hour=0, minute=0, second=0, microsecond=0) if period == "today" else until - timedelta(hours=hours or 3)
        base = self.settings.qq_gateway_url
        if not base:
            raise ServiceError("当前运行环境未连接 QQ 历史网关")
        parsed = urlsplit(base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ServiceError("历史网关必须是不含凭据的 HTTP(S) 地址")
        scope = re.fullmatch(re.escape(self.account_id) + r":(group|private):(\d+)", self.conversation_id)
        if not scope:
            raise ServiceError("当前会话没有有效的 QQ 历史范围")
        path = f"/api/accounts/{quote(self.account_id, safe='')}/conversations/{scope[1]}/{scope[2]}/messages"
        opener = build_opener(ProxyHandler({}))
        items: dict[str, dict] = {}
        cursor = None
        has_more = False
        truncated = False
        reached_start = False
        characters = 0
        deadline = time.monotonic() + 60
        for _ in range(20):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                truncated = True
                break
            query = {"limit": min(100, limit - len(items))}
            if cursor:
                query["before"] = cursor
            try:
                with opener.open(base.rstrip('/') + path + '?' + urlencode(query), timeout=min(15, remaining)) as response:
                    page = json.load(response)
            except (URLError, OSError, ValueError):
                raise ServiceError("QQ 历史读取失败；请检查当前账号连接和网关") from None
            if not isinstance(page, dict) or not isinstance(page.get("messages"), list):
                raise ServiceError("QQ 历史网关返回格式无效")
            previous_count = len(items)
            # Pages are chronological; keep the newest portion first if a content budget is reached.
            for message in reversed(page["messages"]):
                if message.get("accountId") != self.account_id or message.get("conversationId") != self.conversation_id:
                    raise ServiceError("QQ 历史范围不一致")
                message_id = str(message.get("messageId") or message.get("id") or "")
                if not message_id or message_id in items:
                    continue
                timestamp_ms = message.get("timestampMs")
                try:
                    if isinstance(timestamp_ms, (int, float)) and timestamp_ms > 0:
                        instant = datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc)
                    else:
                        instant = datetime.fromisoformat(str(message.get("timestamp", "")).replace('Z', '+00:00'))
                        if instant.tzinfo is None:
                            raise ValueError("missing time zone")
                except (ValueError, OverflowError, OSError):
                    raise ServiceError("历史记录缺少可验证的完整时间，无法按时间范围总结") from None
                if instant > until:
                    continue
                if instant < since:
                    reached_start = True
                    break
                content = "[已撤回]" if message.get("status") == "recalled" else str(message.get("content", ""))
                clipped = content[:2000]
                truncated = truncated or content != clipped
                if characters + len(clipped) > 250000:
                    truncated = True
                    break
                timestamp = instant.astimezone(local_zone).isoformat()
                items[message_id] = {"id": message_id, "senderId": message.get("senderId", ""),
                                     "senderName": message.get("senderName", ""), "content": clipped,
                                     "timestamp": timestamp}
                characters += len(clipped)
                if len(items) >= limit:
                    break
            has_more = page.get("hasMoreBefore") is True and not reached_start
            next_cursor = page.get("beforeCursor")
            if (reached_start or len(items) >= limit or characters >= 248000 or not has_more or not next_cursor
                    or next_cursor == cursor or len(items) == previous_count):
                break
            cursor = next_cursor
        # Each page was inserted newest-first; display labels such as 23:59/00:01 are not sortable dates.
        messages = list(reversed(items.values()))
        truncated = truncated or (len(messages) < limit and has_more)
        metadata = {"source": "onebot_history", "requested": limit, "returned": len(messages),
                    "characters": characters, "has_more": has_more, "truncated": truncated,
                    "period": period, "hours": (hours or 3) if period == "recent" else None,
                    "window_source": "user_prompt_rule" if requested_window else "tool_arguments",
                    "timezone": "Asia/Shanghai", "window_start": since.isoformat(), "window_end": until.isoformat(),
                    "limit_reached": len(messages) >= limit and has_more,
                    "oldest_at": messages[0]["timestamp"] if messages else None,
                    "newest_at": messages[-1]["timestamp"] if messages else None}
        run = self.store.get(self.run_id)
        self.store.update(self.run_id, history_queries=[*run.get("history_queries", []), metadata])
        return {**metadata, "messages": messages}

    def services_list(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "builtin": tool_definitions(),
            "campus_configured": bool(self.settings.mcp_console_url),
            "campus_capabilities": [],
        }
        if not self.settings.mcp_console_url:
            result["campus_error"] = "未配置 MCP Console；当前仅提供本地只读服务"
            return result
        try:
            result["campus_capabilities"] = self._allowed_catalog()
        except ServiceError as exc:
            result["campus_error"] = str(exc)
        return result

    def campus_query(self, capability_id: str, arguments: dict[str, Any] | None = None) -> Any:
        self._text(capability_id, nonempty=True)
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise ServiceError("校园查询 arguments 必须是对象")
        if not self.settings.mcp_console_url:
            raise ServiceError("未配置 MCP Console，校园查询暂不可用")
        if capability_id not in self.settings.campus_capabilities:
            raise ServiceError("该校园能力未被管理员显式启用")
        allowed = {item["id"]: item for item in self._allowed_catalog()}
        if capability_id not in allowed:
            raise ServiceError("该能力不是当前会话允许的公开校园能力")
        if not allowed[capability_id]["available"]:
            raise ServiceError("该校园能力暂不可用")
        return self._console("/v1/invoke", {"capabilityId": capability_id, "arguments": arguments})

    def _allowed_catalog(self) -> list[dict[str, Any]]:
        catalog = self._console("/v1/catalog")
        if not isinstance(catalog, dict) or not isinstance(catalog.get("capabilities"), list):
            raise ServiceError("MCP Console 返回了无效能力目录")
        result = []
        for item in catalog["capabilities"]:
            if not isinstance(item, dict):
                continue
            if (item.get("id") not in self.settings.campus_capabilities
                    or item.get("privacy") != "public"
                    or self.context not in item.get("allowedContexts", [])):
                continue
            # Only expose query metadata, never Console server/admin details.
            result.append({
                "id": item["id"], "name": item.get("name", item["id"]),
                "description": item.get("description", ""),
                "inputSchema": item.get("inputSchema", {}),
                "available": item.get("available") is True,
            })
        return result

    def _console(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        base = self.settings.mcp_console_url
        if not base:
            raise ServiceError("未配置 MCP Console，校园查询暂不可用")
        parsed = urlsplit(base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ServiceError("MCP Console 地址必须是不含凭据的 HTTP(S) 地址")
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        request = Request(base.rstrip("/") + path, data=body,
                          headers={"Accept": "application/json", "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=15) as response:
                return json.load(response)
        except HTTPError as exc:
            raise ServiceError(f"MCP Console 请求失败（HTTP {exc.code}）") from None
        except (URLError, OSError, ValueError):
            # Remote errors may contain credential-bearing URLs or response
            # bodies, so expose only the operational failure to the model.
            raise ServiceError("MCP Console 不可用或响应格式无效") from None

    @staticmethod
    def _text(value: str, *, nonempty: bool = False) -> None:
        if not isinstance(value, str) or len(value) > 2000 or (nonempty and not value.strip()):
            raise ServiceError("文本参数必须为不超过 2000 字符的字符串")
