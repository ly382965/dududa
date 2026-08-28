from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from icourse_mcp.config import AppConfig
from icourse_mcp.crawler import ICourseCrawler
from icourse_mcp.fetcher import FetchedPage
from icourse_mcp.parser import parse_site_rankings_page, parse_site_stats_page

COURSE_PAGE = """
<span class="text-muted">共 3 门课（当前第 1 页）</span>
<div class="ud-pd-md dashed"><a class="px16" href="/course/18025/">大数据算法（丁虎）</a>
<span class="small text-muted">2026春</span><span class="h4">8.6</span><span>(24 人评价)</span>
<ul><li>课程难度：困难</li><li>作业多少：很少</li><li>给分好坏：一般</li><li>收获大小：很多</li></ul></div>
<div class="ud-pd-md dashed"><a class="px16" href="/course/21471/">大数据算法（彭攀）</a>
<span class="small text-muted">2025春</span><span class="h4">8.7</span><span>(29 人评价)</span>
<ul><li>课程难度：困难</li><li>作业多少：中等</li><li>给分好坏：超好</li><li>收获大小：一般</li></ul></div>
<div class="ud-pd-md dashed"><a class="px16" href="/course/24076/">大数据算法（丁虎, 宋骐）</a>
<span class="small text-muted">2024春</span><span class="h4">3.8</span><span>(16 人评价)</span></div>
"""

STATS_PAGE = """
<table><tr><td>课程数</td><td>19194</td></tr><tr><td>点评数</td><td>49607</td></tr>
<tr><td>平均评分</td><td>7.77 / 10</td></tr></table>
"""

RANKINGS_PAGE = """
<span class="h4">最受欢迎的课程</span>
<table><tr><th>TOP</th><th>课程名</th><th>点评数</th><th>评分</th><th>归一化平均分</th></tr>
<tr><th>#1</th><td><a href="/course/1/">测试课程</a></td><td>20</td><td>9.9</td><td>9.1</td></tr></table>
<span class="h4">最长的点评</span>
<table><tr><th>TOP</th><th>课程</th><th>作者</th><th>点赞数</th><th>长度</th></tr>
<tr><th>#1</th><td><a href="/course/2/#review-3">长评课程</a></td><td><a href="/user/4">Wanglulu</a></td><td>16</td><td>97661</td></tr></table>
<p>全站点评的平均分为 7.8，全站有点评课程的平均点评数为 8.8。</p>
"""


class _CourseFetcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def fetch_course_search(self, query: str, page: int = 1, per_page: int = 50) -> FetchedPage:
        self.calls.append((query, page, per_page))
        return FetchedPage("https://icourse.club/search/", 200, COURSE_PAGE, "fixture")

    def close(self) -> None:
        return None


class ICourseLivePublicQueryTests(unittest.TestCase):
    def test_course_and_teacher_queries_use_one_live_search_page(self) -> None:
        with TemporaryDirectory() as temporary:
            crawler = ICourseCrawler(
                AppConfig(db_path=Path(temporary) / "icourse.sqlite3", request_delay=0)
            )
            crawler.fetcher.close()
            fetcher = _CourseFetcher()
            crawler.fetcher = fetcher  # type: ignore[assignment]
            try:
                courses = crawler.query_site_courses("大数据算法", limit=30)
                teachers = crawler.search_site_teachers("大数据算法", limit=10)
            finally:
                crawler.close()

        self.assertEqual(courses["total"], 3)
        self.assertEqual(courses["items"][0]["teachers"][0]["name"], "丁虎")
        self.assertEqual(courses["items"][1]["review_count_site"], 29)
        self.assertEqual([item["name"] for item in teachers["items"]], ["丁虎", "彭攀", "宋骐"])
        self.assertEqual(fetcher.calls, [("大数据算法", 1, 50), ("大数据算法", 1, 50)])

    def test_stats_and_rankings_are_projected_from_live_html(self) -> None:
        stats = parse_site_stats_page(STATS_PAGE)
        rankings = parse_site_rankings_page(RANKINGS_PAGE, "https://icourse.club")

        self.assertEqual(stats["coverage"]["courses"], 19194)
        self.assertEqual(stats["coverage"]["public_reviews"], 49607)
        self.assertEqual(stats["average_review_rating"], 7.77)
        self.assertEqual(rankings["top_courses"][0]["id"], 1)
        self.assertEqual(rankings["longest_reviews"][0]["author_display"], "Wanglulu")
        self.assertEqual(rankings["longest_reviews"][0]["content_length"], 97661)
        self.assertEqual(rankings["formula"]["global_average"], 7.8)


if __name__ == "__main__":
    unittest.main()
