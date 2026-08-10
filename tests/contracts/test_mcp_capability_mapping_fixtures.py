from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dududa.capabilities import load_capability_catalog_snapshot
from dududa.errors import DududaError
from dududa.mcp import ConfigMcpServerRegistry

from ops.cli.generate_icourse_capability_config import rendered_documents
from tests.unit.capabilities.test_contracts import NOW

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_CAPABILITIES = ROOT / "configs" / "capabilities"
FAKE_CAPABILITIES = ROOT / "tests" / "fixtures" / "capabilities"
SERVER_FIXTURES = ROOT / "tests" / "fixtures" / "mcp" / "servers"
PRODUCTION_SERVERS = ROOT / "configs" / "mcp" / "servers"


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("fixture must be an object")
    return value


def capability_snapshot(root: Path, suffix: str):
    return load_capability_catalog_snapshot(
        root / "definitions",
        root / "mappings",
        snapshot_id=f"capability-catalog:{suffix}",
        acquired_at=NOW,
    )


class McpCapabilityMappingFixtureContractTests(unittest.TestCase):
    def test_icourse_config_matches_content_addressed_generator(self) -> None:
        expected = rendered_documents()
        actual_paths = {
            path.relative_to(ROOT)
            for directory in (
                PRODUCTION_CAPABILITIES / "definitions",
                PRODUCTION_CAPABILITIES / "mappings",
            )
            for path in directory.iterdir()
        }
        self.assertEqual(actual_paths, set(expected))
        for relative, content in expected.items():
            self.assertEqual((ROOT / relative).read_text(encoding="utf-8"), content)

    def test_icourse_config_contains_only_public_read_only_capabilities(self) -> None:
        registry = ConfigMcpServerRegistry(
            PRODUCTION_SERVERS,
            clock=lambda: NOW,
            id_factory=lambda: "production",
        )
        transport = registry.acquire_snapshot()
        self.assertEqual(
            tuple(item.server_id for item in transport.definitions),
            ("icourse",),
        )
        server = registry.resolve_server(transport, "icourse")
        catalog = capability_snapshot(PRODUCTION_CAPABILITIES, "production")
        self.assertEqual(len(catalog.definitions), 4)
        by_tool = {item.tool_name: item for item in catalog.mcp_mappings}
        self.assertEqual(
            set(by_tool),
            {"icourse_stats", "search_courses", "get_course", "get_reviews"},
        )
        self.assertTrue(set(by_tool) <= set(server.allowed_tools))
        self.assertTrue(set(by_tool).isdisjoint(server.denied_tools))
        self.assertTrue(
            set(by_tool).isdisjoint(
                {
                    "search_site_courses",
                    "crawl_course",
                    "check_robots",
                    "crawl_courses",
                    "crawl_latest_reviews",
                    "export_dataset",
                }
            )
        )
        self.assertEqual(by_tool["get_course"].fixed_arguments, {"refresh": False})
        for tool_name, mapping in by_tool.items():
            self.assertEqual(mapping.server_id, "icourse")
            self.assertEqual(mapping.semantics.value, "read_only")
            self.assertEqual(mapping.result_mapping_revision, "schema-project-v1")
            if tool_name != "get_course":
                self.assertEqual(mapping.fixed_arguments, {})

    def test_second_fake_is_configuration_and_permission_fixture_only(self) -> None:
        fake = capability_snapshot(FAKE_CAPABILITIES, "fake-only")
        self.assertEqual(
            tuple(item.capability_id for item in fake.definitions),
            ("fixture.echo.read.v1",),
        )
        self.assertEqual(fake.mcp_mappings[0].server_id, "fake-b")
        authorization = load_json(FAKE_CAPABILITIES / "authorization" / "fake-b.json")
        self.assertEqual(
            authorization["roles"]["member"]["permissions"],
            ["capability.fixture.echo"],
        )

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            servers = root / "servers"
            definitions = root / "capabilities" / "definitions"
            mappings = root / "capabilities" / "mappings"
            servers.mkdir(parents=True)
            definitions.mkdir(parents=True)
            mappings.mkdir(parents=True)
            for source in (
                PRODUCTION_SERVERS / "icourse.json",
                SERVER_FIXTURES / "fake-b.json",
            ):
                shutil.copy2(source, servers / source.name)
            for source_root, target in (
                (PRODUCTION_CAPABILITIES / "definitions", definitions),
                (PRODUCTION_CAPABILITIES / "mappings", mappings),
                (FAKE_CAPABILITIES / "definitions", definitions),
                (FAKE_CAPABILITIES / "mappings", mappings),
            ):
                for source in source_root.iterdir():
                    shutil.copy2(source, target / source.name)

            transport = ConfigMcpServerRegistry(
                servers,
                clock=lambda: NOW,
                id_factory=lambda: "extended",
            ).acquire_snapshot()
            catalog = load_capability_catalog_snapshot(
                definitions,
                mappings,
                snapshot_id="capability-catalog:extended",
                acquired_at=NOW,
            )
            self.assertEqual(
                tuple(item.server_id for item in transport.definitions),
                ("fake-b", "icourse"),
            )
            self.assertEqual(
                tuple(
                    item.provider.provider_id for item in catalog.provider_descriptors
                ),
                ("mcp.fake-b", "mcp.icourse"),
            )
            self.assertEqual(len(catalog.definitions), 5)

        production = capability_snapshot(PRODUCTION_CAPABILITIES, "still-production")
        self.assertEqual(len(production.definitions), 4)
        for relative in (
            "packages/dududa-agent/src/dududa/capabilities/mcp_provider.py",
            "packages/dududa-agent/src/dududa/capabilities/runtime.py",
            "packages/dududa-agent/src/dududa/domain/capability.py",
        ):
            self.assertNotIn("fake-b", (ROOT / relative).read_text(encoding="utf-8"))

    def test_missing_mapping_fails_closed_at_bootstrap(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            definitions = root / "definitions"
            mappings = root / "mappings"
            definitions.mkdir()
            mappings.mkdir()
            source = next((FAKE_CAPABILITIES / "definitions").iterdir())
            shutil.copy2(source, definitions / source.name)
            with self.assertRaises(DududaError):
                load_capability_catalog_snapshot(
                    definitions,
                    mappings,
                    snapshot_id="capability-catalog:missing-mapping",
                    acquired_at=NOW,
                )


if __name__ == "__main__":
    unittest.main()
