import sys, unittest, json
sys.path.insert(0, r"C:\Users\23112\Code\dududa\apps\astrbot-plugins")
from astrbot_plugin_ustc_classroom.reviews import (
    format_review_answer, _strip_html,
)


class ReviewFormatTests(unittest.TestCase):
    def test_strip_html(self):
        self.assertEqual(_strip_html("<p>很好</p><p>课堂</p>"), "很好 课堂")

    def test_format_answer(self):
        results = [{
            "course_name": "数学分析(B1)",
            "teachers": ["夏银华"],
            "dept": "数学科学学院",
            "reviews": [
                {
                    "author": "匿名", "term": "2026春",
                    "rating": 10, "difficulty": "中等",
                    "homework": "中等", "grading": "超好", "gain": "很多",
                    "content": "板书字迹清秀",
                },
            ],
        }]
        answer = format_review_answer(results, "数学分析")
        self.assertIn("数学分析(B1)", answer)
        self.assertIn("夏银华", answer)
        self.assertIn("10.0/10", answer)
        self.assertIn("板书", answer)


if __name__ == "__main__":
    unittest.main()
