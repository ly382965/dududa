#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_PERSONA_COLUMNS = {
    "created_at",
    "updated_at",
    "id",
    "persona_id",
    "system_prompt",
    "begin_dialogs",
    "tools",
    "skills",
    "custom_error_message",
    "folder_id",
    "sort_order",
}


def wait_for_file(path: Path, seconds: int) -> None:
    deadline = time.monotonic() + max(0, seconds)
    while not path.is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for {path}")
        time.sleep(1)


def load_persona(path: Path) -> tuple[dict, str]:
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if metadata.get("schema_version") != 1:
        raise RuntimeError(f"unsupported persona schema in {path}")
    persona_id = metadata.get("persona_id")
    prompt_file = metadata.get("prompt_file")
    if not isinstance(persona_id, str) or not persona_id.strip():
        raise RuntimeError("persona_id must be a non-empty string")
    if not isinstance(prompt_file, str) or Path(prompt_file).name != prompt_file:
        raise RuntimeError("prompt_file must be a file next to the persona metadata")
    prompt = (path.parent / prompt_file).read_text(encoding="utf-8").strip()
    if not prompt:
        raise RuntimeError("persona prompt is empty")
    return metadata, prompt


def seed_persona(database: Path, metadata: dict, prompt: str) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
    persona_id = metadata["persona_id"]
    with sqlite3.connect(database, timeout=30) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(personas)")}
        if not REQUIRED_PERSONA_COLUMNS.issubset(columns):
            missing = ", ".join(sorted(REQUIRED_PERSONA_COLUMNS - columns))
            raise RuntimeError(f"AstrBot personas schema is incompatible; missing: {missing}")
        existing = conn.execute("SELECT id FROM personas WHERE persona_id = ?", (persona_id,)).fetchone()
        values = (
            prompt,
            json.dumps(metadata.get("begin_dialogs", []), ensure_ascii=False),
            json.dumps(metadata.get("tools"), ensure_ascii=False),
            json.dumps(metadata.get("skills"), ensure_ascii=False),
            metadata.get("custom_error_message"),
            now,
            persona_id,
        )
        if existing:
            conn.execute(
                """
                UPDATE personas
                SET system_prompt = ?, begin_dialogs = ?, tools = ?, skills = ?,
                    custom_error_message = ?, updated_at = ?
                WHERE persona_id = ?
                """,
                values,
            )
        else:
            sort_order = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM personas").fetchone()[0]
            conn.execute(
                """
                INSERT INTO personas(
                    created_at, updated_at, persona_id, system_prompt, begin_dialogs,
                    tools, skills, custom_error_message, folder_id, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    now,
                    now,
                    persona_id,
                    prompt,
                    json.dumps(metadata.get("begin_dialogs", []), ensure_ascii=False),
                    json.dumps(metadata.get("tools"), ensure_ascii=False),
                    json.dumps(metadata.get("skills"), ensure_ascii=False),
                    metadata.get("custom_error_message"),
                    sort_order,
                ),
            )


def write_json_preserving_owner(path: Path, value: dict) -> None:
    stat = path.stat()
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, stat.st_mode & 0o777)
        try:
            os.chown(tmp_name, stat.st_uid, stat.st_gid)
        except PermissionError:
            pass
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def select_persona(config_path: Path, persona_id: str) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise RuntimeError(f"expected a JSON object in {config_path}")
    provider_settings = config.setdefault("provider_settings", {})
    if not isinstance(provider_settings, dict):
        raise RuntimeError("provider_settings must be a JSON object")
    provider_settings["default_personality"] = persona_id
    provider_settings.setdefault("persona_pool", ["*"])
    write_json_preserving_owner(config_path, config)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Dududa persona into an initialized AstrBot data directory.")
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--astrbot-config", required=True, type=Path)
    parser.add_argument("--persona", required=True, type=Path)
    parser.add_argument("--wait-seconds", type=int, default=0)
    args = parser.parse_args()

    wait_for_file(args.database, args.wait_seconds)
    wait_for_file(args.astrbot_config, args.wait_seconds)
    metadata, prompt = load_persona(args.persona)
    seed_persona(args.database, metadata, prompt)
    select_persona(args.astrbot_config, metadata["persona_id"])
    print(f"seeded AstrBot persona: {metadata['persona_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
