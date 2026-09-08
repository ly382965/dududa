#!/usr/bin/env python3
"""Safely add the Dududa reverse WebSocket client to account-specific LLBot configs.

LLBot (LuckyLilliaBot / LLOneBot v4+) stores per-account configs as
``bin/llbot/data/config_<uin>.json`` with OneBot 11 connections under
``ob11.connect``.  Each entry carries a ``type`` field; the workspace uses a
``ws-reverse`` entry.  The token authenticates the OneBot connection between
the LLBot host and the Dududa Web Gateway.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLIENT_NAME = "dududa-web"
ACCOUNT_CONFIG_PATTERN = re.compile(r"^config_\d{5,20}\.json$")


def load_token(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("OneBot token file must be a regular file")
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if os.name != "nt" and (mode & 0o077):
            raise ValueError("OneBot token file must not be readable by group or others")
    except ValueError:
        raise
    except Exception:
        pass
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise ValueError("OneBot token must contain at least 32 characters")
    return token


def desired_client(endpoint: str, token: str) -> dict[str, Any]:
    return {
        "type": "ws-reverse",
        "enable": True,
        "url": endpoint,
        "heartInterval": 60000,
        "token": token,
        "reportSelfMessage": True,
        "reportOfflineMessage": False,
        "messageFormat": "array",
        "debug": False,
    }


def _find_workspace_index(connect: list[Any]) -> int | None:
    """Find the existing dududa-web ws-reverse entry in the connect list."""
    for index, item in enumerate(connect):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "ws-reverse" and (
            item.get("name") == CLIENT_NAME or str(item.get("url") or "").endswith("/onebot/v11/ws")
        ):
            return index
    return None


def merge_config(document: dict[str, Any], client: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    ob11 = document.get("ob11")
    if not isinstance(ob11, dict):
        raise ValueError("LLBot config is missing an ob11 object")
    connect = ob11.get("connect")
    if not isinstance(connect, list):
        raise ValueError("LLBot config ob11.connect must be an array")
    index = _find_workspace_index(connect)
    updated = json.loads(json.dumps(document))
    updated_connect = updated["ob11"]["connect"]
    if index is not None:
        if updated_connect[index] == client:
            return updated, False
        updated_connect[index] = client
    else:
        updated_connect.append(client)
    return updated, True


def atomic_write(path: Path, document: dict[str, Any]) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = path.with_name(f"{path.name}.bak.{timestamp}")
    shutil.copy2(path, backup, follow_symlinks=False)
    os.chmod(backup, 0o600)
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary_name, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return backup


def configure(config_dir: Path, token_file: Path, endpoint: str, apply: bool) -> int:
    if config_dir.is_symlink() or not config_dir.is_dir():
        raise ValueError("LLBot data directory must be a real directory")
    token = load_token(token_file)
    client = desired_client(endpoint, token)
    paths = sorted(path for path in config_dir.iterdir() if ACCOUNT_CONFIG_PATTERN.fullmatch(path.name))
    if not paths:
        raise ValueError("No account-specific config_<QQ>.json config found; log in to LLBot first")
    changed = 0
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Refusing non-regular config: {path.name}")
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError(f"LLBot config must be a JSON object: {path.name}")
        updated, needs_change = merge_config(document, client)
        label = hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:8]
        if not needs_change:
            print(f"unchanged account={label}")
            continue
        changed += 1
        if apply:
            backup = atomic_write(path, updated)
            print(f"updated account={label}; backup_created={backup.exists()}")
        else:
            print(f"would update account={label}")
    print(f"summary files={len(paths)} changed={changed} mode={'apply' if apply else 'dry-run'}")
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--endpoint", default="ws://127.0.0.1:5173/onebot/v11/ws")
    parser.add_argument("--apply", action="store_true", help="write configs; default is dry-run")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        configure(args.config_dir, args.token_file, args.endpoint, args.apply)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
