from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dududa.mcp import ConfigMcpServerRegistry

from tests.unit.mcp.helpers import NOW

ROOT = Path(__file__).resolve().parents[2]
MAPPINGS = ROOT / "tests" / "fixtures" / "mcp" / "capability-mappings"
SERVER_FIXTURES = ROOT / "tests" / "fixtures" / "mcp" / "servers"
PRODUCTION_SERVERS = ROOT / "config" / "mcp" / "servers"


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("fixture must be an object")
    return value


class McpCapabilityMappingFixtureContractTests(unittest.TestCase):
    def test_icourse_fixture_contains_only_public_read_only_surface(self) -> None:
        registry = ConfigMcpServerRegistry(
            PRODUCTION_SERVERS,
            clock=lambda: NOW,
            id_factory=lambda: "production",
        )
        snapshot = registry.acquire_snapshot()
        self.assertEqual(
            tuple(item.server_id for item in snapshot.definitions),
            ("icourse",),
        )
        definition = registry.resolve_server(snapshot, "icourse")
        fixture = load_json(MAPPINGS / "icourse-public-read-only.json")
        self.assertEqual(fixture["fixture_kind"], "provisional_for_s13")
        mappings = fixture["mappings"]
        self.assertIsInstance(mappings, list)
        by_tool = {item["tool_name"]: item for item in mappings}
        self.assertEqual(
            set(by_tool),
            {"icourse_stats", "search_courses", "get_course", "get_reviews"},
        )
        self.assertTrue(set(by_tool) <= set(definition.allowed_tools))
        self.assertTrue(set(by_tool).isdisjoint(definition.denied_tools))
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
        self.assertEqual(by_tool["get_course"]["fixed_arguments"], {"refresh": False})
        for tool_name, mapping in by_tool.items():
            self.assertEqual(mapping["server_id"], "icourse")
            self.assertEqual(mapping["semantics"], "read_only")
            if tool_name != "get_course":
                self.assertEqual(mapping["fixed_arguments"], {})

    def test_second_fake_requires_only_definition_and_mapping_fixtures(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for source in (
                PRODUCTION_SERVERS / "icourse.json",
                SERVER_FIXTURES / "fake-b.json",
            ):
                (directory / source.name).write_bytes(source.read_bytes())
            registry = ConfigMcpServerRegistry(
                directory,
                clock=lambda: NOW,
                id_factory=lambda: "extended",
            )
            snapshot = registry.acquire_snapshot()
            self.assertEqual(
                tuple(item.server_id for item in snapshot.definitions),
                ("fake-b", "icourse"),
            )
            fixture = load_json(MAPPINGS / "fake-extension.json")
            self.assertEqual(fixture["fixture_kind"], "provisional_for_s13")
            mappings = fixture["mappings"]
            self.assertEqual(len(mappings), 1)
            mapping = mappings[0]
            definition = registry.resolve_server(snapshot, mapping["server_id"])
            self.assertIn(mapping["tool_name"], definition.allowed_tools)

        production = ConfigMcpServerRegistry(
            PRODUCTION_SERVERS,
            clock=lambda: NOW,
            id_factory=lambda: "still-production",
        )
        self.assertEqual(
            tuple(item.server_id for item in production.acquire_snapshot().definitions),
            ("icourse",),
        )


if __name__ == "__main__":
    unittest.main()
