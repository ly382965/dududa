from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path

from astrbot_plugin_dududa_core.adapters.mcp_schema import (
    JsonSchemaCapabilityValidator,
)
from astrbot_plugin_ustc_shuttle import ShuttleSchedule
from dududa.capabilities import (
    CapabilityProviderKind,
    load_capability_catalog_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "tests" / "fixtures" / "ustc_shuttle" / "questions.v1.json"
DEFINITIONS = ROOT / "configs" / "capabilities" / "definitions"
MAPPINGS = ROOT / "configs" / "capabilities" / "mappings"
CAPABILITY_ID = "ustc.shuttle.public-query.v1"


class UstcShuttlePluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        cls.observed_at = datetime.fromisoformat(cls.fixture["observed_at"])
        cls.schedule = ShuttleSchedule()
        cls.catalog = load_capability_catalog_snapshot(
            DEFINITIONS,
            MAPPINGS,
            snapshot_id="shuttle-plugin-test",
            acquired_at=cls.observed_at,
        )
        cls.definition = next(
            item
            for item in cls.catalog.definitions
            if item.capability_id == CAPABILITY_ID
        )
        cls.output_schema = next(
            item
            for item in cls.catalog.schema_documents
            if item.schema_ref == cls.definition.output_schema
        )

    def test_twenty_questions_return_expected_timetable_facts(self) -> None:
        cases = self.fixture["cases"]
        self.assertEqual(len(cases), 20)
        self.assertEqual([item["case_id"] for item in cases], list(range(1, 21)))
        validator = JsonSchemaCapabilityValidator()

        for case in cases:
            with self.subTest(case_id=case["case_id"]):
                result = self.schedule.query(
                    case["question"],
                    at=self.observed_at,
                )
                validator.validate(result, self.output_schema)
                self.assertEqual(result["total"], case["expected_total"])
                self.assertEqual(
                    result["matched"],
                    case.get("expected_matched", case["expected_total"] > 0),
                )
                if expected := case.get("expected_departures"):
                    self.assertEqual(
                        [item["departure"] for item in result["items"]],
                        expected,
                    )
                if not result["items"]:
                    continue
                first = result["items"][0]
                for expected_name, actual_name in (
                    ("expected_service_id", "service_id"),
                    ("expected_departure", "departure"),
                    ("expected_arrival", "arrival"),
                    ("expected_no_public_bus", "no_public_bus"),
                    ("expected_saturday_only", "saturday_only"),
                ):
                    if expected_name in case:
                        self.assertEqual(first[actual_name], case[expected_name])
                if "expected_holiday" in case:
                    self.assertTrue(all(item["holiday"] for item in result["items"]))
                if "expected_stops" in case:
                    self.assertEqual(
                        [item["name"] for item in first["stops"]],
                        case["expected_stops"],
                    )
                if stop := case.get("expected_on_demand_stop"):
                    projected = next(item for item in first["stops"] if item["name"] == stop)
                    self.assertTrue(projected["on_demand"])
                    self.assertIsNone(projected["time"])
                combined_notices = "\n".join(result["notices"])
                for term in case.get("required_notice_terms", ()):
                    self.assertIn(term, combined_notices)
                combined_semantics = "\n".join(result["semantics"].values())
                for term in case.get("required_semantic_terms", ()):
                    self.assertIn(term, combined_semantics)

    def test_catalog_exposes_builtin_plugin_without_mcp_mapping(self) -> None:
        descriptor = next(
            item
            for item in self.catalog.provider_descriptors
            if item.provider == self.definition.provider
        )
        self.assertEqual(descriptor.kind, CapabilityProviderKind.BUILTIN)
        self.assertEqual(descriptor.provider.provider_id, "plugin.ustc-shuttle")
        self.assertEqual(descriptor.capability_ids, frozenset({CAPABILITY_ID}))
        self.assertFalse(
            any(
                item.capability_id == CAPABILITY_ID
                for item in self.catalog.mcp_mappings
            )
        )
        self.assertFalse((ROOT / "configs" / "mcp" / "servers" / "ustc-shuttle.json").exists())


if __name__ == "__main__":
    unittest.main()
