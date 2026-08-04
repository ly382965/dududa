from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_compose_contains_only_bot_services(self) -> None:
        compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
        services: set[str] = set()
        in_services = False
        for line in compose.splitlines():
            if line == "services:":
                in_services = True
                continue
            if in_services and line and not line.startswith(" "):
                break
            match = re.match(r"^  ([a-zA-Z0-9_.-]+):\s*$", line) if in_services else None
            if match:
                services.add(match.group(1))
        self.assertEqual(services, {"web", "astrbot", "napcat"})

        for component in ("sub2api", "postgres", "redis", "xray", "caddy", "authelia"):
            self.assertFalse((ROOT / component).exists(), component)

    def test_plugin_lock_is_exact_and_complete(self) -> None:
        lock = json.loads((ROOT / "plugins.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["schema_version"], 1)
        plugins = {plugin["name"]: plugin for plugin in lock["plugins"]}
        self.assertEqual(
            set(plugins),
            {
                "astrbot_plugin_better_reminder",
                "astrbot_plugin_chatsummary_v2",
                "astrbot_plugin_iris_chat_memory",
                "astrbot_plugin_pokepro",
                "astrbot_plugin_reread",
                "meme_manager",
            },
        )
        for plugin in plugins.values():
            if plugin["source"] == "git":
                self.assertRegex(plugin["commit"], re.compile(r"^[0-9a-f]{40}$"))
        self.assertNotIn("memes", plugins["meme_manager"]["sparse_paths"])

    def test_iris_patch_keeps_both_privacy_guards(self) -> None:
        patch = (ROOT / "patches" / "iris-memory-user-group-isolation.patch").read_text(
            encoding="utf-8"
        )
        self.assertIn('metadata.get("user_id")', patch)
        self.assertIn("search_nodes_detailed", patch)
        self.assertIn("group_id=group_id", patch)

    def test_mcp_template_has_only_icourse(self) -> None:
        config = json.loads(
            (ROOT / "config" / "astrbot" / "mcp_server.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(config["mcpServers"]), {"icourse"})
        self.assertEqual(config["mcpServers"]["icourse"]["command"], "/usr/local/bin/python")
        self.assertIn(
            "/AstrBot/data/icourse-cache/icourse.sqlite3",
            config["mcpServers"]["icourse"]["args"],
        )

    def test_compose_keeps_owned_code_read_only(self) -> None:
        compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
        self.assertIn("PYTHONDONTWRITEBYTECODE", compose)
        for name in (
            "astrbot_plugin_dududa_core",
            "astrbot_plugin_reply_polish",
            "astrbot_plugin_target_talk",
        ):
            self.assertIn(f"/AstrBot/data/plugins/{name}:ro", compose)

    def test_persona_seed_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            database = temp / "data_v4.db"
            config = temp / "cmd_config.json"
            with sqlite3.connect(database) as conn:
                conn.executescript(
                    """
                    CREATE TABLE personas (
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        id INTEGER NOT NULL PRIMARY KEY,
                        persona_id VARCHAR(255) NOT NULL,
                        system_prompt TEXT NOT NULL,
                        begin_dialogs JSON,
                        tools JSON,
                        skills JSON,
                        custom_error_message TEXT,
                        folder_id VARCHAR(36),
                        sort_order INTEGER NOT NULL
                    );
                    """
                )
            config.write_text('{"provider_settings": {}}\n', encoding="utf-8")
            command = [
                sys.executable,
                str(ROOT / "scripts" / "seed_astrbot.py"),
                "--database",
                str(database),
                "--astrbot-config",
                str(config),
                "--persona",
                str(ROOT / "config" / "personas" / "dududa.json"),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            subprocess.run(command, check=True, capture_output=True, text=True)
            with sqlite3.connect(database) as conn:
                rows = conn.execute(
                    "SELECT persona_id, system_prompt FROM personas"
                ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], "dududa")
            self.assertIn("行为边界与隐私", rows[0][1])
            seeded_config = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(
                seeded_config["provider_settings"]["default_personality"], "dududa"
            )

    def test_icourse_store_initializes_private_cache_schema(self) -> None:
        from icourse_mcp.storage import ICourseStore

        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "icourse.sqlite3"
            ICourseStore(database)
            with sqlite3.connect(database) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            self.assertTrue({"courses", "teachers", "reviews", "crawl_meta"} <= tables)


if __name__ == "__main__":
    unittest.main()
