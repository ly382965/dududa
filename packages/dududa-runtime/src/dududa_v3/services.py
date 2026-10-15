"""Scope-bound, read-only services shared by rules and the native MCP server."""

from __future__ import annotations

import importlib.util
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .config import Settings
from .store import Store


class ServiceError(ValueError):
    pass


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
                            "openWorldHint": name in {"campus_query", "services_list"}},
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
        try:
            scope = json.loads(row["scope"])
            conversation = scope[1] if isinstance(scope, list) and len(scope) > 1 else ""
        except (ValueError, TypeError):
            conversation = ""
        self.context = "private" if ":private:" in conversation else "group"
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
