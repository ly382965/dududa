import sys, unittest
sys.path.insert(0, r"C:\Users\23112\Code\dududa\apps\astrbot-plugins")
from astrbot_plugin_ustc_classroom.schedule import (
    search_course_schedule, format_course_answer,
)

LESSON = {
    "id": 1,
    "dateTimePlacePersonText": {
        "cn": "2~18周 3C301 :1(3,4) 吴天\n2~18周 3C301 :3(3,4) 吴天\n2~18周 3C301 :5(3,4) 吴天"
    },
    "teacherAssignmentList": [{"cn": "吴天", "en": "Wu Tian"}],
    "course": {"code": "001110", "cn": "数学分析(B1)", "en": "Math Analysis"},
}


class CourseSearchTests(unittest.TestCase):
    def test_search_by_teacher_and_course(self):
        hits = search_course_schedule([LESSON], "吴天数学分析")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["course_name"], "数学分析(B1)")
        self.assertIn("3C301", hits[0]["schedule"])
        self.assertIn("吴天", hits[0]["teacher"])

    def test_search_by_course_only(self):
        hits = search_course_schedule([LESSON], "数学分析")
        self.assertEqual(len(hits), 1)

    def test_search_no_match(self):
        hits = search_course_schedule([LESSON], "线性代数")
        self.assertEqual(len(hits), 0)

    def test_format_answer(self):
        hits = search_course_schedule([LESSON], "吴天数学分析")
        answer = format_course_answer(hits, "吴天数学分析")
        self.assertIn("数学分析(B1)", answer)
        self.assertIn("3C301", answer)
        self.assertIn("吴天", answer)


if __name__ == "__main__":
    unittest.main()
