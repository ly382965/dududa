from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_dududa_core.adapters.api_key_pools import (
    ApiKeyPoolConfigError,
    configured_api_key_store_path,
    load_api_key_pool_snapshot,
    parse_api_key_pool_snapshot,
    project_pool_to_astrbot,
)


def _pool(
    tier: str, *, key: str = "synthetic-key", enabled: bool = True
) -> dict[str, object]:
    return {
        "tier": tier,
        "displayName": f"{tier} pool",
        "provider": "synthetic-provider",
        "providerId": f"astrbot-{tier}",
        "sourceId": f"dududa-{tier}-source",
        "baseUrl": "https://provider.invalid/v1",
        "model": f"synthetic-{tier}",
        "protocol": "openai_chat_completions",
        "reasoningEffort": "low",
        "timeoutMs": 120_000,
        "maxOutputTokens": 2_048,
        "enabled": enabled,
        "schedulingMode": "priority",
        "customHeaders": [{"name": "X-Trace-Mode", "value": "synthetic"}],
        "revision": 3,
        "keys": [
            {
                "id": f"{tier}-disabled",
                "name": "disabled",
                "secretRef": f"{tier.upper()}_DISABLED",
                "secret": "disabled-secret",
                "priority": 100,
                "weight": 1,
                "enabled": False,
                "status": "disabled",
            },
            {
                "id": f"{tier}-primary",
                "name": "primary",
                "secretRef": f"{tier.upper()}_PRIMARY",
                "secret": key,
                "priority": 10,
                "weight": 2,
                "enabled": True,
                "status": "active",
            },
        ],
    }


def _document() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "revision": 7,
        "pools": {
            tier: _pool(tier, key=f"{tier}-synthetic-secret")
            for tier in ("haiku", "sonnet", "opus")
        },
    }


class ApiKeyPoolAdapterContractTests(unittest.TestCase):
    def test_object_snapshot_projects_three_isolated_astrbot_sources(self) -> None:
        snapshot = parse_api_key_pool_snapshot(_document())
        self.assertEqual(
            tuple(pool.tier for pool in snapshot.pools), ("haiku", "sonnet", "opus")
        )
        self.assertEqual(snapshot.revision, 7)

        projections = [project_pool_to_astrbot(pool) for pool in snapshot.pools]
        self.assertEqual(
            [item.source_id for item in projections],
            ["dududa-haiku-source", "dududa-sonnet-source", "dududa-opus-source"],
        )
        self.assertEqual(
            [item.provider_id for item in projections],
            ["astrbot-haiku", "astrbot-sonnet", "astrbot-opus"],
        )
        self.assertEqual(projections[0].keys, ("haiku-synthetic-secret",))
        self.assertTrue(projections[0].for_astrbot()["provider"]["enable"])
        self.assertEqual(
            projections[0].for_astrbot()["provider_source"]["timeout"], 120
        )

        # Dataclass representations are safe to use in diagnostics.  The
        # concrete secret appears only in the explicit AstrBot projection.
        self.assertNotIn("haiku-synthetic-secret", repr(snapshot))
        self.assertNotIn("haiku-synthetic-secret", repr(projections[0]))

    def test_array_snapshot_and_compatibility_aliases_are_accepted(self) -> None:
        document = _document()
        pools = list(document["pools"].values())
        # Exercise the GET-shaped array and snake_case fields used by older
        # deployments without changing the canonical semantics.
        array_document = {
            "schema_version": 1,
            "config_revision": "rev-8",
            "pools": pools,
        }
        snapshot = parse_api_key_pool_snapshot(array_document)
        self.assertEqual(snapshot.revision, "rev-8")
        self.assertEqual(snapshot.pool("SONNET").model, "synthetic-sonnet")  # type: ignore[union-attr]

        resolved = project_pool_to_astrbot(
            snapshot.pool("haiku"),  # type: ignore[arg-type]
            secret_resolver=lambda ref: (
                "resolved-secret" if ref == "HAIKU_PRIMARY" else ""
            ),
        )
        self.assertEqual(resolved.keys, ("haiku-synthetic-secret",))

    def test_secret_ref_can_be_resolved_when_private_file_has_no_raw_secret(
        self,
    ) -> None:
        document = _document()
        haiku = document["pools"]["haiku"]
        haiku["keys"][1].pop("secret")
        pool = parse_api_key_pool_snapshot(document).pool("haiku")
        self.assertIsNotNone(pool)
        projection = project_pool_to_astrbot(
            pool, secret_resolver=lambda ref: "resolved-value"
        )  # type: ignore[arg-type]
        self.assertEqual(projection.keys, ("resolved-value",))

    def test_disabled_or_cooling_keys_are_not_materialized(self) -> None:
        document = _document()
        keys = document["pools"]["haiku"]["keys"]
        keys[1]["status"] = "cooldown"
        pool = parse_api_key_pool_snapshot(document).pool("haiku")
        projection = project_pool_to_astrbot(pool)  # type: ignore[arg-type]
        self.assertEqual(projection.keys, ())
        self.assertFalse(projection.for_astrbot()["provider"]["enable"])

        document["pools"]["haiku"]["enabled"] = False
        pool = parse_api_key_pool_snapshot(document).pool("haiku")
        projection = project_pool_to_astrbot(pool)  # type: ignore[arg-type]
        self.assertEqual(projection.keys, ())

    def test_file_loader_requires_private_regular_file_and_supports_env_alias(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api-keys.json"
            path.write_text(json.dumps(_document()), encoding="utf-8")
            os.chmod(path, 0o600)
            loaded = load_api_key_pool_snapshot(path)
            self.assertEqual(loaded.pool("opus").model, "synthetic-opus")  # type: ignore[union-attr]
            self.assertEqual(
                configured_api_key_store_path(
                    environment={"DUDUDA_API_KEYS_FILE": str(path)}
                ),
                path,
            )

            os.chmod(path, 0o640)
            with self.assertRaisesRegex(ApiKeyPoolConfigError, "permissions"):
                load_api_key_pool_snapshot(path)

    def test_invalid_protocol_header_and_duplicate_ids_are_rejected(self) -> None:
        document = _document()
        document["pools"]["haiku"]["protocol"] = "unsupported"
        with self.assertRaisesRegex(ApiKeyPoolConfigError, "protocol"):
            parse_api_key_pool_snapshot(document)

        document = _document()
        document["pools"]["haiku"]["customHeaders"] = [
            {"name": "Authorization", "value": "secret"}
        ]
        with self.assertRaisesRegex(ApiKeyPoolConfigError, "header"):
            parse_api_key_pool_snapshot(document)

        document = _document()
        document["pools"]["sonnet"]["sourceId"] = "dududa-haiku-source"
        with self.assertRaisesRegex(ApiKeyPoolConfigError, "unique"):
            parse_api_key_pool_snapshot(document)


if __name__ == "__main__":
    unittest.main()
