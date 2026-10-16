from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "cli" / "install_plugins.py"
SPEC = importlib.util.spec_from_file_location("install_plugins", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class InstallPluginsTests(unittest.TestCase):
    def test_owned_plugins_are_installed_into_the_runtime_root(self) -> None:
        self.assertIn(
            "apps/astrbot-plugins/astrbot_plugin_dududa_social",
            MODULE.OWNED_PLUGIN_PATHS,
        )
        with tempfile.TemporaryDirectory() as tmp:
            plugins_root = Path(tmp)
            for relative_path in MODULE.OWNED_PLUGIN_PATHS:
                MODULE.install_owned_plugin(relative_path, plugins_root)

            for relative_path in MODULE.OWNED_PLUGIN_PATHS:
                name = Path(relative_path).name
                target = plugins_root / name
                self.assertTrue((target / "main.py").is_file())
                marker = json.loads(
                    (target / ".dududa-owned.json").read_text(encoding="utf-8")
                )
                self.assertEqual(marker["path"], relative_path)
                self.assertFalse((target / "__pycache__").exists())

    def test_s17_marker_path_aliases_preserve_existing_installs(self) -> None:
        cases = (
            (
                {
                    "name": "astrbot_plugin_better_reminder",
                    "version": "v1.4",
                    "source": "vendor",
                    "path": "third_party/vendor/astrbot_plugin_better_reminder",
                },
                "path",
                "vendor/astrbot_plugin_better_reminder",
            ),
            (
                {
                    "name": "astrbot_plugin_iris_chat_memory",
                    "version": "0.1.1+privacy.1",
                    "source": "git",
                    "repository": "https://example.invalid/iris.git",
                    "commit": "2" * 40,
                    "patch": "third_party/patches/iris-memory-user-group-isolation.patch",
                },
                "patch",
                "patches/iris-memory-user-group-isolation.patch",
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            marker_path = target / ".dududa-lock.json"
            for plugin, key, legacy_path in cases:
                marker = MODULE.marker_for(plugin)
                marker[key] = legacy_path
                marker_path.write_text(json.dumps(marker), encoding="utf-8")
                self.assertTrue(MODULE.marker_matches(target, plugin))

            unknown = MODULE.marker_for(cases[0][0])
            unknown["path"] = "vendor/unrecognized-plugin"
            marker_path.write_text(json.dumps(unknown), encoding="utf-8")
            self.assertFalse(MODULE.marker_matches(target, cases[0][0]))


if __name__ == "__main__":
    unittest.main()
