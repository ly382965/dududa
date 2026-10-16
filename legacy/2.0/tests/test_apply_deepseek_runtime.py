from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

from tests.contracts.test_api_key_pools import _document

SCRIPTS = Path(__file__).resolve().parents[1] / "ops/cli"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "apply_deepseek_runtime", SCRIPTS / "apply_deepseek_runtime.py"
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class DeepSeekRuntimeMigrationTests(unittest.TestCase):
    def setUp(self):
        document = _document()
        models = []
        providers = []
        for index, (tier, pool) in enumerate(document["pools"].items()):
            pool.update(
                provider="deepseek",
                baseUrl="https://api.deepseek.com",
                model="deepseek-v4-pro" if tier == "opus" else "deepseek-v4-flash",
                reasoningEffort=("low", "high", "max")[index],
                maxOutputTokens=(8192, 16384, 32768)[index],
            )
            models.append(
                {
                    "tier": tier,
                    "astrbot_provider_id": pool["providerId"],
                    "provider_id": f"provider-{tier}",
                    "endpoint_id": tier,
                    "model_id": "old-model",
                    "max_context_tokens": 65536,
                    "max_concurrency": 3,
                    "rpm_limit": 10,
                    "tpm_limit": 10000,
                }
            )
            providers.append(
                {
                    "id": pool["providerId"],
                    "provider_source_id": "old-source",
                    "api_base": "https://old.invalid",
                    "key": ["stale-key"],
                    "api_version": "old-azure",
                    "custom_extra_body": {"thinking": {"type": "disabled"}},
                }
            )
        providers.append(
            {"id": "unrelated", "provider_source_id": "old-source", "enabled": False}
        )
        self.command = {
            "provider": providers,
            "provider_sources": [{"id": "old-source", "key": ["untouched"]}],
            "provider_settings": {"default_provider_id": "unrelated"},
            "unrelated": {"preserved": True},
        }
        self.core = {
            "runtime_models_json": json.dumps(models),
            "rollout_delivery_enabled": True,
            "unrelated": {"preserved": True},
        }
        self.snapshot = migration.adapter.parse_api_key_pool_snapshot(document)

    def test_projects_external_settings_without_stale_source_overrides(self):
        before = copy.deepcopy((self.command, self.core))
        command, core = migration.build_candidate(
            self.command, self.core, self.snapshot, accept_retention=True
        )
        self.assertEqual((self.command, self.core), before)
        self.assertEqual(command["provider"][-1], self.command["provider"][-1])
        self.assertEqual(
            command["provider_sources"][0], self.command["provider_sources"][0]
        )
        self.assertEqual(
            command["provider_settings"], self.command["provider_settings"]
        )
        self.assertEqual(core["unrelated"], self.core["unrelated"])
        for provider in command["provider"][:3]:
            self.assertNotIn("api_base", provider)
            self.assertNotIn("key", provider)
            self.assertNotIn("api_version", provider)
            self.assertNotIn("custom_extra_body", provider)
        models = json.loads(core["runtime_models_json"])
        self.assertEqual(
            [model["reasoning_depth"] for model in models], ["light", "deep", "maximum"]
        )
        self.assertEqual(
            [model["max_output_tokens"] for model in models], [8192, 16384, 32768]
        )
        self.assertTrue(
            all(
                model["data_residency"] == "CN"
                and model["retention_mode"] == "provider_managed"
                for model in models
            )
        )
        self.assertTrue(all(model["max_concurrency"] == 3 for model in models))
        self.assertTrue(core["runtime_allow_provider_retention"])
        self.assertTrue(core["rollout_delivery_enabled"])
        self.assertEqual(core["runtime_reasoning_output_reserve_tokens"], 4096)

    def test_requires_approval(self):
        with self.assertRaisesRegex(ValueError, "explicit_approval"):
            migration.build_candidate(
                self.command, self.core, self.snapshot, accept_retention=False
            )

    def test_does_not_replace_source_used_by_unrelated_provider(self):
        self.command["provider"][-1]["provider_source_id"] = "dududa-haiku-source"
        with self.assertRaisesRegex(ValueError, "source_shared"):
            migration.build_candidate(
                self.command, self.core, self.snapshot, accept_retention=True
            )

    def test_rejects_changed_runtime_binding(self):
        models = json.loads(self.core["runtime_models_json"])
        models[0]["astrbot_provider_id"] = "unrelated"
        self.core["runtime_models_json"] = json.dumps(models)
        with self.assertRaisesRegex(ValueError, "binding_mismatch"):
            migration.build_candidate(
                self.command, self.core, self.snapshot, accept_retention=True
            )

    def test_rejects_duplicate_source_ids(self):
        self.command["provider_sources"].append(self.command["provider_sources"][0])
        with self.assertRaisesRegex(ValueError, "duplicate_astrbot_binding"):
            migration.build_candidate(
                self.command, self.core, self.snapshot, accept_retention=True
            )


if __name__ == "__main__":
    unittest.main()
