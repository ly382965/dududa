"""Native MCP stdio endpoint with identity fixed by its launch arguments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import VERSION
from .config import Settings
from .services import ServiceHub
from .store import Store


class MCPServer:
    def __init__(self, hub: ServiceHub):
        self.hub = hub

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or not isinstance(message.get("method"), str):
            return self.error(None, -32600, "Invalid request")
        request_id, method = message.get("id"), message["method"]
        if "id" not in message:
            return None
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return self.error(request_id, -32602, "Invalid params")
        if method == "initialize":
            version = params.get("protocolVersion")
            if version not in {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}:
                version = "2025-06-18"
            result = {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "dududa-v3-services", "version": VERSION},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": self.hub.tool_definitions()}
        elif method == "tools/call":
            try:
                name = params.get("name")
                if not isinstance(name, str):
                    raise TypeError("缺少工具名称")
                value = self.hub.call(name, params.get("arguments", {}))
                result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                          "isError": isinstance(value, dict) and value.get("ok") is False}
            except (ValueError, TypeError) as exc:
                result = {"content": [{"type": "text", "text": json.dumps({"error": str(exc)}, ensure_ascii=False)}], "isError": True}
            except Exception:  # noqa: BLE001 -- MCP boundary must return a sanitized protocol error.
                result = {"content": [{"type": "text", "text": json.dumps({"error": "本地服务执行失败"}, ensure_ascii=False)}], "isError": True}
        else:
            return self.error(request_id, -32601, "Method not found")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def serve(self) -> None:
        for line in sys.stdin:
            try:
                message = json.loads(line)
            except ValueError:
                response = self.error(None, -32700, "Parse error")
            else:
                response = self.handle(message)
            if response is not None:
                print(json.dumps(response, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dududa 3.0 scope-bound read-only MCP services")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--session-id", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--console-url")
    parser.add_argument("--gateway-url")
    parser.add_argument("--capabilities-json", default="[]")
    args = parser.parse_args()
    capabilities = json.loads(args.capabilities_json)
    if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
        parser.error("--capabilities-json must be a JSON array of strings")
    settings = Settings(root=args.root, state_dir=args.database.parent,
                        mcp_console_url=args.console_url, qq_gateway_url=args.gateway_url,
                        campus_capabilities=tuple(capabilities))
    hub = ServiceHub(settings, Store(args.database), args.session_id, args.run_id)
    MCPServer(hub).serve()


if __name__ == "__main__":
    main()
