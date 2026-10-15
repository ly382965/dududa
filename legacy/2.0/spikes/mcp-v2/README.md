# S12A MCP v2 Spike

This directory is an isolated engineering experiment. It is not the production
Unified MCP Client.

The PEP 723 script pins MCP Python SDK v2 independently from the root workspace,
which must remain on MCP v1 while the current iCourse FastMCP Server is used as
the legacy fixture.

Run with the locked root Python as the v1 Server interpreter. Use a dedicated
uv cache per Python version; concurrent `uv run --script` processes can
otherwise resynchronize the same cached PEP 723 environment.

```bash
UV_CACHE_DIR=/tmp/dududa-mcp-v2-cache-312 \
uv run --python 3.12.13 --locked --script spikes/mcp-v2/run_spike.py \
  --legacy-python .venv/bin/python \
  --check-report spikes/mcp-v2/report.json
```

The legacy fixture uses an empty temporary iCourse database. A child-process
guard denies socket connections and SQLite paths outside that database. The
harness calls only cached read tools; it performs no crawl, export, model call,
credential access or QQ operation.

The committed report records an SDK adoption decision only. It does not mean
that the production Unified Client, Registry, iCourse migration, another MCP
Server, or any live source exists.
