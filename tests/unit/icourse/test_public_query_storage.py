from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from icourse_mcp.models import Course, Review, Teacher
from icourse_mcp.storage import ICourseStore


class ICoursePublicQueryStorageTests(unittest.TestCase):
    def test_course_name_parentheses_and_teacher_lookup_by_course(self) -> None:
        with TemporaryDirectory() as temporary:
            store = ICourseStore(Path(temporary) / "icourse.sqlite3")
            store.upsert_course(
                Course(
                    id=2,
                    name="数学分析(B1)",
                    url="https://icourse.club/course/2/",
                    teachers=[Teacher(id=8, name="吴天")],
                    reviews=[
                        Review(
                            id=20,
                            course_id=2,
                            url="https://icourse.club/course/2/#review-20",
                            author_display="公开用户",
                            content_text="课程公开点评",
                        )
                    ],
                )
            )

            self.assertEqual(store.search_courses(query="数学分析B1")["total"], 1)
            self.assertEqual(store.query_courses(query="数学分析B1")["total"], 1)
            self.assertEqual(store.search_reviews("数学分析B1")["total"], 1)
            teachers = store.search_teachers("数学分析B1")
            self.assertEqual(teachers["total"], 1)
            self.assertEqual(teachers["items"][0]["name"], "吴天")

    def test_public_queries_include_anonymous_reviews_and_site_timestamp_year(self) -> None:
        with TemporaryDirectory() as temporary:
            store = ICourseStore(Path(temporary) / "icourse.sqlite3")
            store.upsert_course(
                Course(
                    id=1,
                    name="人工智能基础",
                    url="https://icourse.club/course/1/",
                    teachers=[Teacher(id=7, name="吴老师", dept="计算机学院")],
                    term_text="2026春",
                    courseries="CS1001",
                    dept="计算机学院",
                    course_type="专业课",
                    credit=2.0,
                    rating_average=9.2,
                    review_count_site=2,
                    visible_review_count=2,
                    difficulty="困难",
                    homework="很少",
                    grading="超好",
                    gain="很多",
                    reviews=[
                        Review(
                            id=10,
                            course_id=1,
                            url="https://icourse.club/course/1/#review-10",
                            author_display="匿名用户",
                            is_anonymous=True,
                            term="2025秋",
                            rating_10=10,
                            content_text="匿名公开点评：讲得很好",
                            publish_time="01/23/2026 11:44:35",
                            upvote_count=8,
                        ),
                        Review(
                            id=11,
                            course_id=1,
                            url="https://icourse.club/course/1/#review-11",
                            author_display="公开用户",
                            term="2025秋",
                            rating_10=8,
                            content_text="公开点评：作业不多",
                            publish_time="2025-12-20T10:00:00",
                            upvote_count=2,
                        ),
                    ],
                )
            )

            courses = store.query_courses(
                query="人工智能",
                teacher="吴老师",
                dept="计算机",
                credit=2.0,
                min_rating=9.0,
                min_reviews=2,
                gain="很多",
            )
            self.assertEqual(courses["total"], 1)

            reviews = store.search_reviews("点评", year=2026)
            self.assertEqual(reviews["total"], 1)
            self.assertTrue(reviews["items"][0]["is_anonymous"])

            teachers = store.search_teachers("吴老师")
            self.assertEqual(teachers["total"], 1)
            self.assertEqual(teachers["items"][0]["course_count"], 1)

            rankings = store.get_rankings(limit=10)
            self.assertEqual(rankings["source"], "local_public_cache")
            self.assertEqual(rankings["top_reviews"][0]["id"], 10)

            statistics = store.get_site_statistics()
            self.assertEqual(statistics["coverage"]["public_reviews"], 2)


if __name__ == "__main__":
    unittest.main()
