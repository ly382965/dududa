from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "cli" / "render_astrbot_candidate.py"
TEMPLATE = ROOT / "configs" / "astrbot" / "luna-terra-sol.candidate.example.json"


def load_renderer():
    spec = importlib.util.spec_from_file_location("render_astrbot_candidate", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("renderer module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RenderAstrBotCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_root = Path(self.temp.name) / "data"
        self.data_root.mkdir()
        (self.data_root / "cmd_config.json").write_text(
            json.dumps(
                {
                    "config_version": 4,
                    "provider_sources": [
                        {
                            "id": "existing",
                            "type": "openai_chat_completion",
                            "enable": True,
                        },
                        {
                            "id": "dududa-gpt56-source",
                            "proxy": "preserved",
                            "enable": True,
                        },
                    ],
                    "provider": [
                        {"id": "existing/model", "enable": True},
                        {
                            "id": "astrbot-luna",
                            "legacy_field": "preserved",
                            "enable": True,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_disabled_default_merges_by_id_and_keeps_runtime_off(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--template",
                str(TEMPLATE),
                "--data-root",
                str(self.data_root),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        receipt = json.loads(result.stdout)
        astrbot = json.loads((self.data_root / "cmd_config.json").read_text())
        plugin = json.loads(
            (
                self.data_root
                / "config"
                / "astrbot_plugin_dududa_core_config.json"
            ).read_text()
        )
        sources = {item["id"]: item for item in astrbot["provider_sources"]}
        providers = {item["id"]: item for item in astrbot["provider"]}
        self.assertEqual(receipt["mode"], "disabled")
        self.assertEqual(astrbot["config_version"], 4)
        self.assertTrue(sources["existing"]["enable"])
        self.assertFalse(sources["dududa-gpt56-source"]["enable"])
        self.assertEqual(sources["dududa-gpt56-source"]["proxy"], "preserved")
        self.assertEqual(providers["astrbot-luna"]["legacy_field"], "preserved")
        self.assertFalse(providers["astrbot-luna"]["enable"])
        self.assertFalse(plugin["runtime_enabled"])
        self.assertEqual(plugin["rollout_mode"], "off")
        self.assertFalse(plugin["rollout_delivery_enabled"])
        self.assertTrue(plugin["rollout_kill_switch"])

    def test_shadow_injects_private_values_without_printing_the_key(self) -> None:
        evidence_path = "/AstrBot/data/private/model-evidence.json"
        env = dict(os.environ)
        env["DUDUDA_GPT56_API_BASE"] = "https://private.example/v1/"
        env["DUDUDA_GPT56_API_KEY"] = "private-test-key"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--template",
                str(TEMPLATE),
                "--data-root",
                str(self.data_root),
                "--mode",
                "shadow",
                "--evidence-path",
                evidence_path,
            ],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

        astrbot = json.loads((self.data_root / "cmd_config.json").read_text())
        plugin = json.loads(
            (
                self.data_root
                / "config"
                / "astrbot_plugin_dududa_core_config.json"
            ).read_text()
        )
        source = next(
            item
            for item in astrbot["provider_sources"]
            if item["id"] == "dududa-gpt56-source"
        )
        candidate_providers = [
            item for item in astrbot["provider"] if item["id"].startswith("astrbot-")
        ]
        self.assertEqual(source["api_base"], "https://private.example/v1")
        self.assertEqual(source["key"], ["private-test-key"])
        self.assertTrue(source["enable"])
        self.assertTrue(all(item["enable"] for item in candidate_providers))
        self.assertTrue(plugin["runtime_enabled"])
        self.assertEqual(plugin["rollout_mode"], "shadow")
        self.assertFalse(plugin["rollout_delivery_enabled"])
        self.assertTrue(plugin["rollout_kill_switch"])
        self.assertEqual(plugin["runtime_provider_evidence_path"], evidence_path)
        self.assertNotIn("private-test-key", result.stdout)


if __name__ == "__main__":
    unittest.main()
