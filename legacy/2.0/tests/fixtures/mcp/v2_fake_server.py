from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", required=True)
    parser.add_argument(
        "--schema-revision",
        choices=("v1", "compatible", "incompatible"),
        default="v1",
    )
    parser.add_argument("--stubborn-child", action="store_true")
    return parser.parse_args()


async def serve(args: argparse.Namespace) -> None:
    journal = Path(args.journal)
    _event(journal, {"event": "started", "pid": os.getpid()})
    if args.stubborn_child:
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=False,
        )
        _event(
            journal,
            {
                "event": "stubborn_child",
                "pid": child.pid,
                "pgid": os.getpgid(child.pid),
            },
        )

    async def list_tools(_context: object, _params: object) -> types.ListToolsResult:
        _event(journal, {"event": "discover"})
        value_type = "integer" if args.schema_revision == "incompatible" else "string"
        tools = [
            types.Tool(
                name="echo",
                description="Local deterministic echo fixture.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "value": {"type": value_type},
                        "delay_ms": {"type": "integer", "minimum": 0, "maximum": 5000},
                        "operation": {"enum": ["read", "crash"]},
                    },
                    "required": ["value"],
                    "additionalProperties": False,
                },
                outputSchema={
                    "type": "object",
                    "properties": {"value": {}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            )
        ]
        if args.schema_revision == "compatible":
            tools.append(
                types.Tool(
                    name="extra",
                    description="Unmapped extension fact.",
                    inputSchema={"type": "object", "additionalProperties": False},
                )
            )
        return types.ListToolsResult(tools=tools)

    async def call_tool(
        _context: object,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        arguments = params.arguments or {}
        _event(journal, {"event": "call", "tool": params.name})
        if arguments.get("operation") == "crash":
            print("server-stderr-secret-sentinel", file=sys.stderr, flush=True)
            os._exit(73)
        delay_ms = arguments.get("delay_ms", 0)
        if type(delay_ms) is not int or not 0 <= delay_ms <= 5000:
            return _result({"error": "invalid_delay"}, is_error=True)
        if delay_ms:
            await anyio.sleep(delay_ms / 1000)
        if params.name != "echo":
            return _result({"error": "unknown_tool"}, is_error=True)
        return _result({"value": arguments.get("value")})

    server: Server[object] = Server(
        "dududa-unified-mcp-fixture",
        version="1.0.0",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def _result(
    value: dict[str, object], *, is_error: bool = False
) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(text=json.dumps(value, sort_keys=True))],
        structuredContent=value,
        isError=is_error,
    )


def _event(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, payload.encode("utf-8"))
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    anyio.run(serve, parse_args())
