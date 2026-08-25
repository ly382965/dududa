from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BENCHMARK = ROOT / "tests" / "fixtures" / "mcp" / "USTC 评课社区 MCP 调用测试案例.md"
SUPPORT_MANIFEST = ROOT / "tests" / "fixtures" / "mcp" / "icourse-benchmark-support-v1.json"
CASE_HEADING_RE = re.compile(r"^### Case (\d+)(?:[：:].*)?$", re.MULTILINE)

DATA_COMPLETE_CASES = frozenset(
    {5, 6, 8, 41, 42, 43, 47, 49, 60, 61, 62, 63, 64, 65}
)
DATA_PARTIAL_CASES = frozenset(
    {1, 2, 3, 4, 7, *range(9, 19), 35, 44, 45, 46, 48, *range(50, 57), 66, 69, 70, 71, 74, 75}
)
DATA_MISSING_CASES = frozenset(range(1, 76)) - DATA_COMPLETE_CASES - DATA_PARTIAL_CASES


class ICourseBenchmarkFixtureTests(unittest.TestCase):
    def test_all_75_cases_are_preserved_with_question_and_expectation(self) -> None:
        source = BENCHMARK.read_text(encoding="utf-8")
        matches = list(CASE_HEADING_RE.finditer(source))

        self.assertEqual([int(match.group(1)) for match in matches], list(range(1, 76)))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
            block = source[match.end() : end]
            self.assertIn("**Q：**", block, f"Case {index + 1}")
            self.assertTrue(
                "**预期：**" in block or "**考察：**" in block,
                f"Case {index + 1}",
            )

    def test_current_data_capability_assessment_covers_every_case(self) -> None:
        all_cases = DATA_COMPLETE_CASES | DATA_PARTIAL_CASES | DATA_MISSING_CASES
        self.assertEqual(all_cases, frozenset(range(1, 76)))
        self.assertFalse(DATA_COMPLETE_CASES & DATA_PARTIAL_CASES)
        self.assertFalse(DATA_COMPLETE_CASES & DATA_MISSING_CASES)
        self.assertFalse(DATA_PARTIAL_CASES & DATA_MISSING_CASES)
        self.assertEqual(
            (len(DATA_COMPLETE_CASES), len(DATA_PARTIAL_CASES), len(DATA_MISSING_CASES)),
            (14, 33, 28),
        )

        manifest = json.loads(SUPPORT_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["summary"]["total"], 75)
        self.assertEqual(manifest["summary"]["strict_runtime_complete"], 0)
        self.assertEqual(
            [item["case_id"] for item in manifest["cases"]],
            list(range(1, 76)),
        )
        for item in manifest["cases"]:
            case_id = item["case_id"]
            expected = (
                "complete"
                if case_id in DATA_COMPLETE_CASES
                else "partial"
                if case_id in DATA_PARTIAL_CASES
                else "missing"
            )
            self.assertEqual(item["mcp_data_support"], expected, case_id)
            self.assertEqual(item["strict_runtime_status"], "not_complete", case_id)


if __name__ == "__main__":
    unittest.main()
