from __future__ import annotations

import copy
import unittest

from ustc_campus_mcp.curriculum import CurriculumClient, _course_codes


class FixtureCurriculumClient(CurriculumClient):
    def __init__(self, *, json_docs=None, csv_docs=None) -> None:
        self.json_docs = json_docs or {}
        self.csv_docs = csv_docs or {}

    async def _json(self, name: str) -> object:
        return copy.deepcopy(self.json_docs[name])

    async def _csv(self, name: str) -> list[dict[str, str]]:
        return copy.deepcopy(self.csv_docs[name])


class CurriculumClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_change_preserves_requirement_and_dimension_transitions(self) -> None:
        transition = {
            "majorName": "计算机科学与技术",
            "majorCode": "01101",
            "departmentCode": "215",
            "departmentName": "计算机科学与技术学院",
            "majorTrackKey": "215::01101",
            "fromGrade": "2025",
            "toGrade": "2026",
            "fromSourceProgramId": "3011",
            "toSourceProgramId": "3382",
            "addedCourseCodes": [],
            "removedCourseCodes": [],
            "requirementTransitions": [
                {"courseCode": "CS2001", "from": ["必修"], "to": ["选修"]}
            ],
            "courseDimensionTransitions": [
                {
                    "courseCode": "CS2002",
                    "from": ["majorFoundation"],
                    "to": ["majorCore"],
                }
            ],
            "dimensionChanges": {},
        }
        client = FixtureCurriculumClient(
            json_docs={
                "research.json": {
                    "majorYearRequirementChanges": {"transitions": [transition]},
                    "programComparisons": {
                        "courseNames": {"CS2001": "测试课程一", "CS2002": "测试课程二"}
                    },
                }
            },
            csv_docs={
                "programs.csv": [
                    {"sourceProgramId": "3011", "requiredCredits": "167"},
                    {"sourceProgramId": "3382", "requiredCredits": "164"},
                ]
            },
        )

        items, total, truncated, _ = await client._change(
            "计算机", "计算机 2025 到 2026 培养方案有什么变化", 6, {}
        )

        self.assertEqual(total, 1)
        self.assertFalse(truncated)
        changes = {entry["change"]: entry for entry in items[0]["course_codes"]}
        self.assertEqual(changes["requirement_changed"]["state"], "必修 -> 选修")
        self.assertEqual(
            changes["dimension_changed"]["dimension"], "专业基础 -> 专业核心"
        )
        self.assertIn("必选性质变化 1 个", items[0]["summary"])
        self.assertIn("五维归类变化 1 个", items[0]["summary"])

    async def test_comparison_filters_to_requested_group(self) -> None:
        plans = {
            "3382": {
                "sourceProgramId": "3382",
                "grade": "2026",
                "departmentCode": "215",
                "majorCode": "01101",
                "majorName": "计算机科学与技术",
                "majorTrackKey": "215::01101",
                "programType": "主修",
                "courseCodes": {"requiredOnly": ["CS1001"]},
            },
            "3416": {
                "sourceProgramId": "3416",
                "planName": "少年班计算机方案",
                "courseCodes": {"requiredOnly": ["CS1001", "CS1002"]},
            },
            "3462": {
                "sourceProgramId": "3462",
                "planName": "计算机科技英才班方案",
                "courseCodes": {"requiredOnly": ["CS1001", "CS1003"]},
            },
        }
        client = FixtureCurriculumClient(
            json_docs={
                "research.json": {
                    "programComparisons": {
                        "plans": plans,
                        "matches": [
                            {
                                "ordinarySourceProgramId": "3382",
                                "groups": {"talent": ["3462"], "young": ["3416"]},
                            }
                        ],
                        "courseNames": {},
                    }
                }
            }
        )

        items, total, truncated, _ = await client._comparison(
            "计算机", "2026级计算机普通主修和少年班有什么区别", 6, {}
        )

        self.assertEqual(total, 1)
        self.assertFalse(truncated)
        self.assertEqual(len(items), 1)
        self.assertIn("少年班", items[0]["title"])

    async def test_shared_empty_entity_query_returns_natural_language_ranking(
        self,
    ) -> None:
        client = FixtureCurriculumClient(
            csv_docs={
                "professional-shared-courses.csv": [
                    {
                        "courseCode": "CS1001",
                        "nameZh": "课程一",
                        "majorCodeCount": "2",
                        "majorTrackCount": "3",
                        "programCount": "4",
                        "firstGrade": "2020",
                        "lastGrade": "2026",
                    },
                    {
                        "courseCode": "MATH1003",
                        "nameZh": "课程二",
                        "majorCodeCount": "8",
                        "majorTrackCount": "9",
                        "programCount": "10",
                        "firstGrade": "2020",
                        "lastGrade": "2026",
                    },
                ]
            }
        )

        question = "培养方案研究里哪些专业课程被最多专业共同使用？"
        for query in ("", question):
            with self.subTest(query=query):
                items, total, truncated, _ = await client._shared(
                    query, question, 1, {}
                )

                self.assertEqual(total, 2)
                self.assertTrue(truncated)
                self.assertEqual(items[0]["course_code"], "MATH1003")

    def test_course_code_parser_covers_real_suffixes_without_matching_grades(
        self,
    ) -> None:
        self.assertEqual(
            _course_codes(
                "2025到2026：MATH1003、001682EX、001M06、G025200308、PHYS1008B+、00T091"
            ),
            (
                "MATH1003",
                "001682EX",
                "001M06",
                "G025200308",
                "PHYS1008B+",
                "00T091",
            ),
        )


if __name__ == "__main__":
    unittest.main()
