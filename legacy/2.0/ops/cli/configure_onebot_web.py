#!/usr/bin/env python3
"""Safely add the Dududa reverse WebSocket client to account-specific OneBot client configs."""

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
ACCOUNT_CONFIG_PATTERNS = {
    "napcat": re.compile(r"^onebot11_\d{5,20}\.json$"),
    "llonebot": re.compile(r"^config_\d{5,20}\.json$"),
}


def load_token(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("OneBot token file must be a regular file")
    mode = stat.S_IMODE(path.stat().st_mode)
    if os.name != "nt" and mode & 0o077:
        raise ValueError("OneBot token file must not be readable by group or others")
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise ValueError("OneBot token must contain at least 32 characters")
    return token


def desired_client(endpoint: str, token: str, implementation: str = "napcat") -> dict[str, Any]:
    if implementation == "llonebot":
        return {
            "name": CLIENT_NAME,
            "type": "ws-reverse",
            "enable": True,
            "url": endpoint,
            "heartInterval": 30000,
            "token": token,
            "reportSelfMessage": True,
            "reportOfflineMessage": False,
            "messageFormat": "array",
            "debug": False,
        }
    return {
        "name": CLIENT_NAME,
        "enable": True,
        "url": endpoint,
        "messagePostFormat": "array",
        "reportSelfMessage": True,
        "reconnectInterval": 5000,
        "token": token,
        "debug": False,
        "heartInterval": 30000,
        "verifyCertificate": True,
    }


def merge_config(
    document: dict[str, Any], client: dict[str, Any], implementation: str = "napcat",
) -> tuple[dict[str, Any], bool]:
    section, key = ("ob11", "connect") if implementation == "llonebot" else ("network", "websocketClients")
    network = document.get(section)
    if not isinstance(network, dict) or not isinstance(network.get(key), list):
        raise ValueError(f"{implementation} config {section}.{key} must be an array")
    clients = network[key]
    matches = [
        index for index, item in enumerate(clients)
        if isinstance(item, dict) and (
            item.get("name") == CLIENT_NAME
            or (implementation == "llonebot" and item.get("type") == "ws-reverse"
                and item.get("url") == client["url"])
        )
    ]
    if len(matches) > 1:
        raise ValueError(f"{implementation} config contains duplicate {CLIENT_NAME!r} clients")
    updated = json.loads(json.dumps(document))
    updated_clients = updated[section][key]
    if matches:
        updated_clients[matches[0]] = client
    else:
        updated_clients.append(client)
    if implementation == "llonebot":
        updated[section]["enable"] = True
    return updated, updated != document


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
        os.chmod(temporary_name, 0o600)
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


def configure(
    config_dir: Path, token_file: Path, endpoint: str, apply: bool, implementation: str = "napcat",
) -> int:
    if config_dir.is_symlink() or not config_dir.is_dir():
        raise ValueError("OneBot config directory must be a real directory")
    token = load_token(token_file)
    client = desired_client(endpoint, token, implementation)
    pattern = ACCOUNT_CONFIG_PATTERNS[implementation]
    paths = sorted(path for path in config_dir.iterdir() if pattern.fullmatch(path.name))
    if not paths:
        raise ValueError(f"No account-specific {implementation} config found; log in to the client first")
    changed = 0
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Refusing non-regular config: {path.name}")
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(document, dict):
            raise ValueError(f"OneBot config must be a JSON object: {path.name}")
        updated, needs_change = merge_config(document, client, implementation)
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
    parser.add_argument("--implementation", choices=tuple(ACCOUNT_CONFIG_PATTERNS), default="napcat")
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--endpoint", default="ws://dududa-web-api:8000/onebot/v11/ws")
    parser.add_argument("--apply", action="store_true", help="write configs; default is dry-run")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        configure(args.config_dir, args.token_file, args.endpoint, args.apply, args.implementation)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
