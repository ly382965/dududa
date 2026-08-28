from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from icourse_mcp.config import AppConfig
from icourse_mcp.crawler import ICourseCrawler
from icourse_mcp.fetcher import FetchedPage

SEARCH_PAGE = """
<span class="text-muted">共 1 个点评（当前第 1 页）</span>
<div class="ud-pd-md dashed">
  <a href="/user/7858"><bdi>萌萌哒mmd</bdi></a>
  <a href="/course/6267/#review-90222">计算机网络（李斌）</a>
  <span class="localtime">01/16/2025 02:23:26</span>
  <p class="review-content">公开点评摘要 <a href="/course/6267/#review-90222">&gt;&gt;更多</a></p>
</div>
"""

USER_REVIEWS_PAGE = """
<meta property="og:description" content="萌萌哒mmd 写了 83 条点评，关注了 3 门课">
<span class="blue h3"><a href="/user/7858"><bdi>萌萌哒mmd</bdi></a> 点评</span>（83门）
<div class="ud-pd-md dashed">
  <a href="/course/24186/">数理逻辑基础（侯嘉慧）</a>
  <span class="small grey">学期：2026春</span>
  <span class="localtime">07/02/2026 16:26:19</span>
  <p class="dark-grey">第一条公开点评 <a href="/course/24186/#review-103403">&gt;&gt;more</a></p>
  <span id="review-upvote-count-103403">2</span>
  <span id="review-comment-count-103403">1</span>
</div>
<div class="ud-pd-md dashed">
  <a href="/course/21285/">计算机原理与嵌入式系统（陈晓辉）</a>
  <span class="small grey">学期：2024春</span>
  <span class="localtime">07/01/2026 09:45:00</span>
  <p class="dark-grey">第二条公开点评 <a href="/course/21285/#review-91857">&gt;&gt;more</a></p>
  <span id="review-upvote-count-91857">14</span>
  <span id="review-comment-count-91857">9</span>
</div>
<div class="ud-pd-md dashed">
  <a href="/course/6780/">随机过程B（庄玮玮）</a>
  <span class="small grey">学期：2026春</span>
  <span class="localtime">06/26/2026 14:12:22</span>
  <p class="dark-grey">第三条公开点评 <a href="/course/6780/#review-103397">&gt;&gt;more</a></p>
  <span id="review-upvote-count-103397">4</span>
  <span id="review-comment-count-103397">0</span>
</div>
"""


class _FixtureFetcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def fetch_review_search(
        self,
        query: str,
        page: int = 1,
        per_page: int = 10,
    ) -> FetchedPage:
        self.calls.append(("search", (query, page, per_page)))
        return FetchedPage("https://icourse.club/search-reviews/", 200, SEARCH_PAGE, "fixture")

    def fetch_user_reviews(self, user_id: int) -> FetchedPage:
        self.calls.append(("reviews", user_id))
        return FetchedPage(
            f"https://icourse.club/user/{user_id}/reviews",
            200,
            USER_REVIEWS_PAGE,
            "fixture",
        )

    def close(self) -> None:
        pass


class ICourseLiveReviewSearchTests(unittest.TestCase):
    def test_exact_author_uses_live_profile_total_and_bounds_items(self) -> None:
        with TemporaryDirectory() as temporary:
            crawler = ICourseCrawler(
                AppConfig(
                    db_path=Path(temporary) / "icourse.sqlite3",
                    request_delay=0,
                )
            )
            crawler.fetcher.close()
            fixture_fetcher = _FixtureFetcher()
            crawler.fetcher = fixture_fetcher  # type: ignore[assignment]
            try:
                result = crawler.search_site_reviews("萌萌哒mmd", limit=2)
            finally:
                crawler.close()

        self.assertEqual(result["total"], 83)
        self.assertEqual(result["source"], "live_site_user_reviews")
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["id"], 103403)
        self.assertEqual(result["items"][0]["author_display"], "萌萌哒mmd")
        self.assertEqual(
            fixture_fetcher.calls,
            [("search", ("萌萌哒mmd", 1, 10)), ("reviews", 7858)],
        )


if __name__ == "__main__":
    unittest.main()
