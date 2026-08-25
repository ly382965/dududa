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
        self.assertNotIn("token", request.url.params)
        self.assertNotEqual(request.url.path, "/api/search/token")


if __name__ == "__main__":
    unittest.main()
