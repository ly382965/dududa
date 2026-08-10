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
    def test_canonical_layout_and_removed_aliases_are_unambiguous(self) -> None:
        canonical_directories = (
            "apps/astrbot-plugins",
            "configs",
            "deploy/compose",
            "deploy/docker",
            "deploy/env",
            "ops/cli",
            "services/mcp/icourse",
            "services/mcp/unified-worker",
            "third_party/patches",
            "third_party/vendor",
        )
        for relative in canonical_directories:
            self.assertTrue((ROOT / relative).is_dir(), relative)

        removed_aliases = (
            ".env.example",
            "config",
            "docker",
            "plugins",
            "scripts",
            "patches",
            "vendor",
            "plugins.lock.json",
            "services/icourse-mcp",
            "services/unified-mcp-worker",
        )
        for relative in removed_aliases:
            path = ROOT / relative
            self.assertFalse(path.exists() or path.is_symlink(), relative)

        root_manage = (ROOT / "manage.sh").read_text(encoding="utf-8")
        root_compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
        self.assertIn('exec "$ROOT_DIR/ops/manage.sh" "$@"', root_manage)
        self.assertIn("./deploy/compose/compose.yml", root_compose)

    def test_derived_image_installs_framework_neutral_core(self) -> None:
        dockerfile = (
            ROOT / "deploy" / "docker" / "astrbot" / "Dockerfile"
        ).read_text(encoding="utf-8")
        self.assertIn("COPY packages/dududa-agent", dockerfile)
        self.assertIn("/opt/dududa/dududa-agent", dockerfile)

    def test_compose_contains_only_bot_services(self) -> None:
        compose = (ROOT / "deploy" / "compose" / "compose.yml").read_text(
            encoding="utf-8"
        )
        services: set[str] = set()
        in_services = False
        for line in compose.splitlines():
            if line == "services:":
                in_services = True
                continue
            if in_services and line and not line.startswith(" "):
                break
            match = (
                re.match(r"^  ([a-zA-Z0-9_.-]+):\s*$", line) if in_services else None
            )
            if match:
                services.add(match.group(1))
        self.assertEqual(services, {"web", "astrbot", "napcat"})

        for component in ("sub2api", "postgres", "redis", "xray", "caddy", "authelia"):
            self.assertFalse((ROOT / component).exists(), component)

    def test_plugin_lock_is_exact_and_complete(self) -> None:
        canonical = ROOT / "third_party" / "plugins.lock.json"
        lock = json.loads(canonical.read_text(encoding="utf-8"))
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
        patch = (
            ROOT
            / "third_party"
            / "patches"
            / "iris-memory-user-group-isolation.patch"
        ).read_text(encoding="utf-8")
        self.assertIn('metadata.get("user_id")', patch)
        self.assertIn("search_nodes_detailed", patch)
        self.assertIn("group_id=group_id", patch)

    def test_mcp_template_has_only_icourse(self) -> None:
        config = json.loads(
            (ROOT / "configs" / "astrbot" / "mcp_server.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(set(config["mcpServers"]), {"icourse"})
        self.assertEqual(
            config["mcpServers"]["icourse"]["command"], "/usr/local/bin/python"
        )
        self.assertTrue(config["mcpServers"]["icourse"]["disabled"])
        self.assertIn(
            "/AstrBot/data/icourse-cache/icourse.sqlite3",
            config["mcpServers"]["icourse"]["args"],
        )
        plugin_schema = json.loads(
            (
                ROOT
                / "apps"
                / "astrbot-plugins"
                / "astrbot_plugin_dududa_core"
                / "_conf_schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertNotIn("icourse_mcp_mode", plugin_schema)

        plugin_root = (
            ROOT / "apps" / "astrbot-plugins" / "astrbot_plugin_dududa_core"
        )
        active_client_source = "\n".join(
            (plugin_root / relative).read_text(encoding="utf-8")
            for relative in ("course.py", "adapters/mcp_runtime.py")
        )
        for removed in (
            "LegacyICourseClient",
            "ClientSession",
            "StdioServerParameters",
            "stdio_client",
            "icourse_mcp_mode",
        ):
            self.assertNotIn(removed, active_client_source)

        registry = json.loads(
            (ROOT / "configs" / "mcp" / "servers" / "icourse.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(registry["protocol_mode"], "legacy")

    def test_compose_keeps_owned_code_read_only(self) -> None:
        compose = (ROOT / "deploy" / "compose" / "compose.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("PYTHONDONTWRITEBYTECODE", compose)
        for name in (
            "astrbot_plugin_dududa_core",
            "astrbot_plugin_reply_polish",
            "astrbot_plugin_target_talk",
            "astrbot_plugin_sub2api_readonly",
        ):
            self.assertIn(f"/AstrBot/data/plugins/{name}:ro", compose)

    def test_astrbot_image_keeps_mcp_v1_and_v2_isolated(self) -> None:
        dockerfile = (
            ROOT / "deploy" / "docker" / "astrbot" / "Dockerfile"
        ).read_text(encoding="utf-8")
        self.assertIn('"mcp==1.29.0"', dockerfile)
        self.assertIn("services/mcp/unified-worker", dockerfile)
        self.assertIn("--locked --no-dev", dockerfile)
        self.assertIn('version("mcp") == "2.0.0"', dockerfile)
        compose = (ROOT / "deploy" / "compose" / "compose.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("  astrbot:\n    init: true\n", compose)

    def test_ci_provisions_both_python_locks_and_uses_versioned_evidence(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "uv sync --project services/mcp/unified-worker",
            workflow,
        )
        self.assertIn(
            "services/mcp/unified-worker/.venv/bin/python",
            workflow,
        )
        self.assertIn("--profile ci-python", workflow)
        self.assertIn("--profile committed-bundles", workflow)
        self.assertIn("config --format json", workflow)
        self.assertIn("compose-contract", workflow)

        web_dockerfile = (ROOT / "deploy" / "docker" / "web" / "Dockerfile").read_text(
            encoding="utf-8"
        )
        web_package = json.loads(
            (ROOT / "apps" / "web" / "package.json").read_text(encoding="utf-8")
        )
        node_version = (ROOT / ".node-version").read_text(encoding="utf-8").strip()
        self.assertIn(f"node:{node_version}-alpine", web_dockerfile)
        self.assertIn("--target=node22", web_package["scripts"]["build:server"])

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
                str(ROOT / "ops" / "cli" / "seed_astrbot.py"),
                "--database",
                str(database),
                "--astrbot-config",
                str(config),
                "--persona",
                str(ROOT / "configs" / "personas" / "dududa.json"),
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
