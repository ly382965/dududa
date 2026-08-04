from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dududa.errors import DududaError
from dududa.rollout import RolloutMode, parse_rollback_manifest
from scripts.rollback_dududa_rollout import load_manifest, tree_digest, verify


ZERO_DIGEST = "sha256:" + "0" * 64
IMAGE = "registry.example/dududa@sha256:" + "1" * 64


def manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "manifest_revision": "rollback-v1",
        "image_reference": IMAGE,
        "plugin": {
            "schema_version": 1,
            "revision": "plugin-v1",
            "source_path": "artifacts/plugin",
            "target_path": "runtime/plugin",
            "tree_digest": ZERO_DIGEST,
        },
        "config": {
            "schema_version": 1,
            "revision": "config-v1",
            "source_path": "artifacts/config",
            "target_path": "runtime/config",
            "tree_digest": ZERO_DIGEST,
        },
        "control_config_relative_path": "astrbot_plugin_dududa_core_config.json",
        "target_control_revision": "rollout-off-v2",
        "target_rollout_mode": "off",
        "compose_file": "compose.yml",
        "compose_service": "astrbot",
        "created_at": "2026-08-04T12:00:00+00:00",
    }


class RolloutRollbackTests(unittest.TestCase):
    def test_manifest_requires_image_plugin_config_and_off_control_revision(
        self,
    ) -> None:
        parsed = parse_rollback_manifest(manifest())
        self.assertIs(parsed.target_rollout_mode, RolloutMode.OFF)
        cases = []
        tag_only = deepcopy(manifest())
        tag_only["image_reference"] = "dududa/astrbot:latest"
        cases.append(tag_only)
        missing_plugin = deepcopy(manifest())
        del missing_plugin["plugin"]
        cases.append(missing_plugin)
        wrong_mode = deepcopy(manifest())
        wrong_mode["target_rollout_mode"] = "canary"
        cases.append(wrong_mode)
        bad_config_digest = deepcopy(manifest())
        bad_config_digest["config"]["tree_digest"] = "config-v1"
        cases.append(bad_config_digest)
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(DududaError):
                    parse_rollback_manifest(value)

    def test_executable_check_verifies_artifacts_and_off_configuration(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "artifacts" / "plugin"
            config = root / "artifacts" / "config"
            plugin.mkdir(parents=True)
            config.mkdir(parents=True)
            (plugin / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            (config / "astrbot_plugin_dududa_core_config.json").write_text(
                json.dumps(
                    {
                        "rollout_mode": "off",
                        "rollout_delivery_enabled": False,
                        "rollout_kill_switch": True,
                        "rollout_revision": "rollout-off-v2",
                    }
                ),
                encoding="utf-8",
            )
            (root / "compose.yml").write_text("services: {}\n", encoding="utf-8")
            value = manifest()
            value["plugin"]["tree_digest"] = tree_digest(plugin)
            value["config"]["tree_digest"] = tree_digest(config)
            path = root / "rollback.json"
            path.write_text(json.dumps(value), encoding="utf-8")

            parsed = load_manifest(path)
            paths = verify(path, parsed)

            self.assertEqual(paths[0], plugin)
            self.assertEqual(paths[2], config)


if __name__ == "__main__":
    unittest.main()
