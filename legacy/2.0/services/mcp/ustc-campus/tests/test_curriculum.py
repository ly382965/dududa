from __future__ import annotations

import copy
import unittest

from ustc_campus_mcp.curriculum import (
    CurriculumClient,
    _course_codes,
    _matches_row,
    _years,
)


class FixtureCurriculumClient(CurriculumClient):
    def __init__(self, *, json_docs=None, csv_docs=None) -> None:
        self.json_docs = json_docs or {}
        self.csv_docs = csv_docs or {}

    async def _json(self, name: str) -> object:
        return copy.deepcopy(self.json_docs[name])

    async def _csv(self, name: str) -> list[dict[str, str]]:
        return copy.deepcopy(self.csv_docs[name])


class CurriculumClientTests(unittest.IsolatedAsyncioTestCase):
    def test_two_digit_grade_is_normalized_without_fuzzy_code_match(self) -> None:
        self.assertEqual(_years("25级计算机培养方案"), ("2025",))
        self.assertEqual(_years("15级到26级"), ("2015", "2026"))
        self.assertEqual(_years("14级、27级和 CS2025"), ())
        self.assertFalse(
            _matches_row({"majorCode": "2501"}, "25", ("majorCode",))
        )
        self.assertTrue(
            _matches_row({"majorCode": "25"}, "25", ("majorCode",))
        )

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

    async def test_comparison_supports_two_ordinary_majors_in_same_grade(
        self,
    ) -> None:
        plans = {
            "computer-2025": {
                "sourceProgramId": "computer-2025",
                "grade": "2025",
                "departmentCode": "215",
                "majorCode": "01101",
                "majorName": "计算机科学与技术",
                "majorTrackKey": "215::01101",
                "programType": "主修",
                "courseCodes": {
                    "requiredOnly": [
                        "GEN1",
                        "CS1",
                        *(f"LREQ{index:02d}" for index in range(40)),
                    ],
                    "electiveOnly": ["CS2"],
                    "mixed": ["CS3"],
                },
                "courseDimensionCodes": {
                    "generalEducation": {"requiredOnly": ["GEN1"]},
                    "majorCore": {
                        "requiredOnly": ["CS1"],
                        "mixed": ["CS3"],
                    },
                    "majorElective": {"electiveOnly": ["CS2"]},
                },
            },
            "ai-2025": {
                "sourceProgramId": "ai-2025",
                "grade": "2025",
                "departmentCode": "215",
                "majorCode": "080717T",
                "majorName": "人工智能",
                "majorTrackKey": "215::080717T",
                "programType": "主修",
                "courseCodes": {
                    "requiredOnly": [
                        "GEN1",
                        "AI1",
                        *(f"RREQ{index:02d}" for index in range(40)),
                    ],
                    "electiveOnly": ["AI2"],
                    "mixed": ["AI3"],
                },
                "courseDimensionCodes": {
                    "generalEducation": {"requiredOnly": ["GEN1"]},
                    "majorCore": {
                        "requiredOnly": ["AI1"],
                        "mixed": ["AI3"],
                    },
                    "majorElective": {"electiveOnly": ["AI2"]},
                },
            },
            "ai-2024": {
                "sourceProgramId": "ai-2024",
                "grade": "2024",
                "departmentCode": "215",
                "majorCode": "080717T",
                "majorName": "人工智能",
                "majorTrackKey": "215::080717T",
                "programType": "主修",
                "courseCodes": {"requiredOnly": ["OLD1"]},
            },
        }
        client = FixtureCurriculumClient(
            json_docs={
                "research.json": {
                    "programComparisons": {
                        "plans": plans,
                        "matches": [],
                        "courseNames": {},
                    }
                }
            },
            csv_docs={
                "programs.csv": [
                    {"sourceProgramId": "computer-2025", "requiredCredits": "160"},
                    {"sourceProgramId": "ai-2025", "requiredCredits": "155"},
                    {"sourceProgramId": "ai-2024", "requiredCredits": "150"},
                ]
            },
        )

        items, total, truncated, _ = await client._comparison(
            "计算机/人工智能",
            "比较25级计算机和人工智能普通主修培养方案",
            6,
            {},
        )

        self.assertEqual(total, 1)
        self.assertFalse(truncated)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertIn("2025级普通主修：计算机科学与技术 vs 人工智能", item["title"])
        self.assertIsNone(item["source_program_id"])
        self.assertEqual(item["major_name"], "计算机科学与技术 vs 人工智能")
        self.assertIn("左侧 计算机科学与技术 总学分 160", item["summary"])
        self.assertIn("右侧 人工智能 总学分 155", item["summary"])
        counts = {entry["name"]: entry["value"] for entry in item["counts"]}
        self.assertEqual(counts["left_required_pool_count"], 42)
        self.assertEqual(counts["right_elective_pool_count"], 1)
        self.assertEqual(len(item["course_codes"]), 60)
        changes = {(entry["code"], entry["change"]) for entry in item["course_codes"]}
        self.assertIn(("CS1", "left_major_only"), changes)
        self.assertIn(("AI1", "right_major_only"), changes)
        self.assertIn(("CS2", "left_pool"), changes)
        self.assertIn(("AI3", "right_pool"), changes)

    async def test_program_excludes_young_by_default_and_balances_course_pool(
        self,
    ) -> None:
        ordinary = {
            "sourceProgramId": "ordinary",
            "grade": "2025",
            "departmentCode": "215",
            "departmentName": "计算机科学与技术学院",
            "majorCode": "01101",
            "majorName": "计算机科学与技术",
            "planName": "计算机科学与技术培养方案",
            "programType": "主修",
            "requiredCredits": "160",
            "courseCodeCount": "44",
            "requiredOnlyCount": "40",
            "electiveOnlyCount": "4",
            "mixedCount": "0",
        }
        young = {
            **ordinary,
            "sourceProgramId": "young",
            "planName": "少年班计算机培养方案",
        }
        general_codes = [f"GEN{index:02d}" for index in range(35)]
        client = FixtureCurriculumClient(
            json_docs={
                "research.json": {
                    "programComparisons": {
                        "plans": {
                            "ordinary": {
                                "courseDimensionCodes": {
                                    "generalEducation": {
                                        "requiredOnly": general_codes
                                    },
                                    "majorCore": {
                                        "requiredOnly": ["CS1"],
                                        "electiveOnly": ["CS2"],
                                    },
                                    "majorElective": {
                                        "electiveOnly": ["CS3"]
                                    },
                                }
                            }
                        },
                        "courseNames": {},
                    }
                }
            },
            csv_docs={"programs.csv": [ordinary, young]},
        )

        full_question = "25级计算机必修和选修课程有哪些"
        items, total, _, _ = await client._program(
            full_question,
            full_question,
            6,
            {},
        )

        self.assertEqual(total, 1)
        self.assertEqual(items[0]["source_program_id"], "ordinary")
        self.assertIn("课程号池观测到 44 个课程号", items[0]["summary"])
        self.assertIn("不是必修/选修学分或实际修读门数", items[0]["summary"])
        self.assertIn("未发布必修与选修的分项学分要求", items[0]["summary"])
        dimensions = {entry["dimension"] for entry in items[0]["course_codes"]}
        states = {entry["state"] for entry in items[0]["course_codes"]}
        self.assertIn("专业核心", dimensions)
        self.assertIn("专业选修", dimensions)
        self.assertIn("required", states)
        self.assertIn("elective", states)

        young_items, young_total, _, _ = await client._program(
            "计算机",
            "25级少年班计算机培养方案",
            1,
            {},
        )
        self.assertEqual(young_total, 2)
        self.assertEqual(young_items[0]["source_program_id"], "young")

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
