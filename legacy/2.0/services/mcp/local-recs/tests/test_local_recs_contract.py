from __future__ import annotations

"""Contract tests for the optional local-recommendations MCP service."""

import importlib.util
import json
import random
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from local_recs_mcp.config import AppConfig
from local_recs_mcp.server import create_mcp
from local_recs_mcp.storage import RecommendationStore

RUNNER = Path(__file__).resolve().parents[1] / "run_local_recs_mcp.py"
RUNNER_SPEC = importlib.util.spec_from_file_location("local_recs_runner", RUNNER)
assert RUNNER_SPEC is not None and RUNNER_SPEC.loader is not None
RUNNER_MODULE = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(RUNNER_MODULE)
auto_seed_if_empty = RUNNER_MODULE.auto_seed_if_empty


class LocalRecommendationsContractTests(unittest.TestCase):
    def test_runner_help_is_local_and_side_effect_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, str(RUNNER), "--help"],
                cwd=temporary,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--db-path", result.stdout)
            self.assertFalse((Path(temporary) / "data").exists())

    def test_explicit_recommendation_id_is_persistent_and_upserted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RecommendationStore(Path(temporary) / "recommendations.sqlite3")
            first = store.upsert("food", "食堂", rec_id=42)
            second = store.upsert("food", "新食堂", rec_id=42)
            self.assertEqual((first, second), (42, 42))
            self.assertEqual(store.get(42)["name"], "新食堂")
            self.assertEqual(store.stats()["recs_total"], 1)

    def test_seed_metadata_and_random_reads_are_side_effect_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "recommendations.sqlite3"
            auto_seed_if_empty(str(database))
            store = RecommendationStore(database)
            east = store.list_food_by_time(
                meal_time="早餐", campus="东区", price_level="平价", limit=100
            )
            self.assertTrue(east)
            self.assertTrue(any(item["campus"] for item in east))
            self.assertTrue(any(item["opening_hours"] for item in east))

            mcp = create_mcp(AppConfig(db_path=database), rng=random.Random(7))
            tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
            self.assertEqual(set(tools), {"local_recommendations_public_query"})
            with sqlite3.connect(database) as connection:
                before = connection.execute(
                    "SELECT SUM(recommended_count) FROM recs"
                ).fetchone()[0]
            result = tools["local_recommendations_public_query"].fn(
                query="", kind="canteen", campus="东区", meal_time="早餐", limit=3
            )
            with sqlite3.connect(database) as connection:
                after = connection.execute(
                    "SELECT SUM(recommended_count) FROM recs"
                ).fetchone()[0]
            self.assertEqual(before, after)
            self.assertGreater(result["returned"], 0)
            self.assertTrue(all(item["campus"] == "东区" for item in result["items"]))
            self.assertEqual(stat.S_IMODE(database.stat().st_mode), 0o600)

            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE recs SET opening_hours_json = ? WHERE id = ?",
                    (json.dumps({str(i): "08:00" for i in range(20)}), east[0]["id"]),
                )
                connection.commit()
            projected = create_mcp(AppConfig(db_path=database), rng=random.Random(3))
            projected_tool = next(iter(projected._tool_manager.list_tools()))
            projected_result = projected_tool.fn(
                query="", kind=east[0]["kind"], limit=1
            )
            self.assertLessEqual(
                len(projected_result["items"][0]["opening_hours"]), 16
            )

            with self.assertRaises(ValueError):
                tools["local_recommendations_public_query"].fn(
                    query="", kind="food", limit=11
                )


if __name__ == "__main__":
    unittest.main()
