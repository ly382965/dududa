from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    python = Path(os.environ.get("CAMPUS_EVENTS_MCP_PYTHON", sys.executable))
    db_path = Path(
        os.environ.get("CAMPUS_EVENTS_MCP_DB_PATH", str(root / "data" / "campus-events.sqlite3"))
    )
    params = StdioServerParameters(
        command=str(python),
        args=[
            str(root / "run_campus_events_mcp.py"),
            "--db-path",
            str(db_path),
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
        result = await session.call_tool(
            "campus_events_public_query", {"query": "", "limit": 1}
        )
        print("query:", result.content[0].text if result.content else "<empty>")


if __name__ == "__main__":
    asyncio.run(main())
