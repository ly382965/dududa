from __future__ import annotations

"""Contract tests for the optional training-plan MCP service."""

import stat
import tempfile
import unittest
from pathlib import Path

from training_plan_mcp.config import AppConfig
from training_plan_mcp.models import PlanRow, PlanYear
from training_plan_mcp.server import create_mcp
from training_plan_mcp.storage import TrainingPlanStore


class TrainingPlanContractTests(unittest.TestCase):
    def test_year_filter_applies_to_all_search_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "plans.sqlite3"
            store = TrainingPlanStore(database)
            store.replace_all(
                [PlanYear(2025, "2025级"), PlanYear(2026, "2026级")],
                [
                    PlanRow(2025, "计算机科学与技术学院", "计算机系", "计算机科学与技术", "080901", "工"),
                    PlanRow(2026, "计算机科学与技术学院", "计算机系", "计算机科学与技术", "080901", "工"),
                ],
                source_hash="fixture",
            )
            mcp = create_mcp(AppConfig(db_path=database))
            tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
            self.assertEqual(set(tools), {"training_programs_public_query"})
            result = tools["training_programs_public_query"].fn(
                query="计算机", year=2025, limit=5
            )
            self.assertEqual([item["year"] for item in result["items"]], [2025])
            self.assertEqual(stat.S_IMODE(database.stat().st_mode), 0o600)

            with self.assertRaises(ValueError):
                tools["training_programs_public_query"].fn(
                    query="计算机", year=2000
                )


if __name__ == "__main__":
    unittest.main()
