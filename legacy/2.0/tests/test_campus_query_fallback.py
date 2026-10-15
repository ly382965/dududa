from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from astrbot_plugin_dududa_core.adapters.capability_planner import (
    ACADEMIC_LESSONS_CAPABILITY_ID, YOUNG_SEARCH_CAPABILITY_ID,
    _academic_arguments, _young_arguments,
)


class CampusQueryFallbackTests(unittest.TestCase):
    schema = {"properties": {key: {} for key in ("query", "semester", "limit", "state")}}

    def request(self, goal):
        return SimpleNamespace(query=SimpleNamespace(entity_terms=(), natural_language_goal=goal))

    def test_academic_keeps_course_and_semester_when_model_entities_are_missing(self):
        for subject in ("数学分析B1", "线性代数"):
            goal = f"@嘟嘟哒 查询2026秋季学期{subject}的开课记录，列出课程名和任课老师。"
            args = _academic_arguments(ACADEMIC_LESSONS_CAPABILITY_ID, self.schema, self.request(goal), frozenset())
            self.assertEqual(args, {"query": subject, "semester": goal, "limit": 25})
        goal = "查询2026秋季学期全校的开课记录"
        self.assertEqual(_academic_arguments(ACADEMIC_LESSONS_CAPABILITY_ID, self.schema, self.request(goal), frozenset())["query"], "")

    def test_young_keeps_activity_name_when_model_entities_are_missing(self):
        for subject in ("英语角", "羽毛球"):
            goal = f"二课里搜索{subject}活动，列出活动名称和活动时间。"
            args = _young_arguments(YOUNG_SEARCH_CAPABILITY_ID, self.schema, self.request(goal), frozenset(), datetime.now(timezone.utc))
            self.assertEqual(args["query"], subject)
        args = _young_arguments(YOUNG_SEARCH_CAPABILITY_ID, self.schema, self.request("二课搜索所有活动"), frozenset(), datetime.now(timezone.utc))
        self.assertEqual(args["query"], "")
