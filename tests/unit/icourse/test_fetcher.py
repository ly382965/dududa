from __future__ import annotations

import unittest

import httpx
from icourse_mcp.fetcher import ICourseFetcher


class ICourseFetcherTests(unittest.TestCase):
    def test_course_search_uses_plain_get_without_legacy_token(self) -> None:
        requests: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, text="<html>ok</html>", request=request)

        fetcher = ICourseFetcher(
            "https://icourse.club",
            "dududa-test",
            request_delay=0,
        )
        fetcher.client.close()
        fetcher.client = httpx.Client(
            transport=httpx.MockTransport(handle),
            follow_redirects=True,
        )
        try:
            page = fetcher.fetch_course_search("吴天", page=2)
        finally:
            fetcher.close()

        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.url.path, "/search/")
        self.assertEqual(request.url.params["q"], "吴天")
        self.assertEqual(request.url.params["page"], "2")
        self.assertEqual(request.url.params["per_page"], "50")
        self.assertEqual(request.url.params["noredirect"], "True")
        self.assertNotIn("token", request.url.params)
        self.assertNotEqual(request.url.path, "/api/search/token")

    def test_public_user_review_paths_use_plain_get(self) -> None:
        requests: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, text="<html>ok</html>", request=request)

        fetcher = ICourseFetcher(
            "https://icourse.club",
            "dududa-test",
            request_delay=0,
        )
        fetcher.client.close()
        fetcher.client = httpx.Client(
            transport=httpx.MockTransport(handle),
            follow_redirects=True,
        )
        try:
            fetcher.fetch_review_search("萌萌哒mmd", page=2)
            fetcher.fetch_user_reviews(7858)
            fetcher.fetch_site_stats()
            fetcher.fetch_site_rankings()
        finally:
            fetcher.close()

        self.assertEqual(
            [(request.method, request.url.path) for request in requests],
            [
                ("GET", "/search-reviews/"),
                ("GET", "/user/7858/reviews"),
                ("GET", "/stats/"),
                ("GET", "/stats/rankings/"),
            ],
        )
        self.assertEqual(requests[0].url.params["q"], "萌萌哒mmd")
        self.assertEqual(requests[0].url.params["page"], "2")


if __name__ == "__main__":
    unittest.main()
