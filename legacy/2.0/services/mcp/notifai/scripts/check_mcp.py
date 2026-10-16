from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    python = Path(os.environ.get("NOTIFAI_MCP_PYTHON", sys.executable))
    params = StdioServerParameters(
        command=str(python),
        args=[
            str(root / "run_notifai_mcp.py"),
            "--base-url",
            os.environ.get("NOTIFAI_API_BASE_URL", "https://notifai-api.enthusjast.cc/api"),
            "--timeout",
            os.environ.get("NOTIFAI_API_TIMEOUT", "15"),
        ],
        cwd=str(root),
        env=dict(os.environ),
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        print("tools:", ", ".join(tool.name for tool in tools.tools))
        result = await session.call_tool("get_notice_stats", {})
        print("get_notice_stats:", result.content[0].text if result.content else "<empty>")


if __name__ == "__main__":
    asyncio.run(main())
