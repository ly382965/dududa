#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
def merge_mcp_config(data_root: Path) -> None:
    template_path = REPO_ROOT / "config" / "astrbot" / "mcp_server.json"
    target_path = data_root / "astrbot" / "mcp_server.json"
    template = json.loads(template_path.read_text(encoding="utf-8"))
    current: dict = {}
    if target_path.exists():
        try:
            current = json.loads(target_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"refusing to overwrite invalid JSON: {target_path}") from exc
    if not isinstance(current, dict):
        raise RuntimeError(f"expected a JSON object in {target_path}")
    servers = current.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise RuntimeError(f"expected mcpServers to be an object in {target_path}")
    servers["icourse"] = template["mcpServers"]["icourse"]

    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".mcp_server.", dir=target_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(current, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, target_path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge safe Dududa templates into AstrBot runtime data.")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--force-config", action="store_true", help="Reserved for compatibility; icourse is always merged.")
    args = parser.parse_args()

    data_root = args.data_root.expanduser().resolve()
    merge_mcp_config(data_root)
    print("merged MCP server: icourse")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
