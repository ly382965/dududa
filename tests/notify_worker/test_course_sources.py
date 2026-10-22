"""Read-only Blackboard discovery, account isolation and material caching."""

import os
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import httpx
from dududa_v3.features.notify import course_sources as sources
from dududa_v3.features.notify.course_catalog import (
    BB_ORIGIN,
    BB_PORTAL_URL,
    DEFAULT_COURSES,
)
from dududa_v3.features.notify.worker import load_credentials


def launcher(cid):
    return BB_ORIGIN + "/webapps/blackboard/execute/launcher?type=Course&id=" + cid + "&url="


def folder(cid, content):
    return BB_ORIGIN + "/webapps/blackboard/content/listContent.jsp?course_id=" + cid + "&content_id=" + content


def portal(rows):
    return '<div id="courseListing">' + "".join(
        f'<a href="{launcher(cid)}">CODE.{term}: {name}</a>'
        for cid, term, name in rows
    ) + "</div>"


def page(content="", menu=""):
    return f'<ul id="courseMenuPalette_contents">{menu}</ul><ul id="content_listContainer">{content}</ul>'


class BlackboardDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_catalog_discovers_every_current_term_course_and_keeps_empty_candidates(self):
        rows = [(f"_{n}_1", "2026FA" if n <= 11 else "2025FA", f"课程{n}") for n in range(1, 42)]
        markup = portal(rows) + portal([rows[0]]) + '<a href="https://evil.invalid/course?course_id=_99_1">X.2026FA: outsider</a>'
        catalog = sources.parse_blackboard_catalog(sources.document(markup), BB_PORTAL_URL, "2026FA")
        self.assertEqual(len(catalog), 11)
        self.assertEqual([item["id"] for item in catalog], [f"bb_{n}_1" for n in range(1, 12)])
        self.assertTrue(all(item["year"] == 2026 and item["term"] == "2026FA" for item in catalog))
        self.assertEqual(catalog[0]["url"], launcher("_1_1"))

    def test_exact_term_and_access_boundary(self):
        old = portal([("_1_1", "2025FA", "旧课程")])
        self.assertEqual(sources.parse_blackboard_catalog(sources.document(old), BB_PORTAL_URL, "2026FA"), [])
        for markup in ("<html>统一身份认证登录</html>", '<a href="/webapps/assessment/take/launch.jsp?course_id=_1_1">X.2026FA: 测验</a>'):
            with self.assertRaisesRegex(sources.CourseError, "catalog_unreadable"):
                sources.parse_blackboard_catalog(sources.document(markup), BB_PORTAL_URL, "2026FA")
        with self.assertRaisesRegex(sources.CourseError, "invalid_blackboard_term"):
            sources.parse_blackboard_catalog(sources.document(old), BB_PORTAL_URL, "2026")

    async def fetch(self, respond, request):
        @asynccontextmanager
        async def session(*args):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                yield client

        with patch.object(sources, "blackboard_session", session):
            return await sources.fetch_courses(request, None)

    async def test_discovery_reads_nested_folders_and_retains_empty_courses(self):
        visited = []
        cid = "_1_1"
        first, nested = folder(cid, "_10_1"), folder(cid, "_11_1")
        course_home = BB_ORIGIN + "/webapps/blackboard/execute/modulepage/view?course_id=" + cid + "&cmp_tab_id=_10_1&mode=view"
        empty_home = BB_ORIGIN + "/webapps/blackboard/execute/modulepage/view?course_id=_2_1&cmp_tab_id=_20_1&mode=view"
        course_main = BB_ORIGIN + "/webapps/blackboard/execute/courseMain?course_id=" + cid + "&task=course_default"
        menu_home = BB_ORIGIN + "/webapps/blackboard/content/launchLink.jsp?course_id=" + cid + "&toc_id=_10_1&mode=view"
        material_url = BB_ORIGIN + "/bbcswebdav/notes.txt"

        def respond(request):
            url = str(request.url)
            visited.append((request.method, url))
            if url == BB_PORTAL_URL:
                return httpx.Response(200, text=portal([(cid, "2026FA", "数字电路"), ("_2_1", "2026FA", "空课程"), ("_3_1", "2025FA", "旧课")]))
            if url == launcher(cid):
                return httpx.Response(302, headers={"location": course_main})
            if url == course_main:
                return httpx.Response(302, headers={"location": menu_home})
            if url == menu_home:
                return httpx.Response(302, headers={"location": course_home})
            if url == launcher("_2_1"):
                return httpx.Response(302, headers={"location": empty_home})
            if url == course_home:
                return httpx.Response(200, text=page(menu=f'<a href="{first}">课程资料</a>'))
            if url == empty_home:
                return httpx.Response(200, text='<ul id="courseMenuPalette_contents"></ul><div>空课程主页</div>')
            if url == first:
                return httpx.Response(200, text=page(f'<li id="folder"><h3><a href="{nested}">Slides</a></h3></li>'))
            if url == nested:
                return httpx.Response(200, text=page(f'<li id="hw"><h3>作业1</h3>截止10月28日<a href="{material_url}">notes.txt</a><a href="/webapps/assessment/take/launch.jsp">开始测试</a><a href="{folder("_3_1", "_12_1")}">其他课程</a></li>'))
            if url == material_url:
                return httpx.Response(200, headers={"etag": "one", "content-type": "text/plain"}, content="课件正文".encode())
            self.fail("unexpected read: " + url)

        result = await self.fetch(respond, {"blackboard_term": "2026FA"})
        self.assertEqual(len(result["catalog"]), 2)
        self.assertEqual([row["status"] for row in result["courses"]], ["ok", "ok"])
        first_result, empty = result["courses"]
        self.assertEqual(first_result["tasks"][0]["deadline"], "2026-10-28")
        self.assertEqual(first_result["tasks"][0]["precision"], "date")
        self.assertEqual(first_result["materials"][0]["text"], "课件正文")
        self.assertEqual((empty["tasks"], empty["materials"]), ([], []))
        self.assertTrue(all(method in {"GET", "HEAD"} for method, _ in visited))
        self.assertFalse(any("assessment" in url or "_3_1" in url for _, url in visited))

    async def test_empty_course_is_rediscovered_and_can_gain_tasks_later(self):
        changed = False
        content_url = folder("_1_1", "_10_1")

        def respond(request):
            url = str(request.url)
            if url == BB_PORTAL_URL:
                return httpx.Response(200, text=portal([("_1_1", "2026FA", "新课程")]))
            if url == launcher("_1_1"):
                return httpx.Response(302, headers={"location": content_url})
            content = page('<li id="hw"><h3>作业2</h3>截止10月28日</li>') if changed else '<ul id="courseMenuPalette_contents"></ul><div>没有要显示的内容。</div>'
            return httpx.Response(200, text=content)

        first = await self.fetch(respond, {"blackboard_term": "2026FA"})
        self.assertEqual(first["courses"][0]["tasks"], [])
        changed = True
        second = await self.fetch(respond, {"blackboard_term": "2026FA"})
        self.assertEqual(second["catalog"], first["catalog"])
        self.assertEqual(second["courses"][0]["tasks"][0]["title"], "作业2")

    def test_known_empty_announcements_and_content_require_positive_evidence(self):
        menu = '<ul id="courseMenuPalette_contents"></ul>'
        self.assertEqual(sources.parse_announcements(sources.document(menu + '<div>找不到公告。</div>'), BB_ORIGIN), [])
        with self.assertRaisesRegex(sources.CourseError, "content_unreadable"):
            sources.parse_blackboard(sources.document(menu + '<div>读取失败</div>'), folder("_1_1", "_10_1"), "_1_1")
        with self.assertRaisesRegex(sources.CourseError, "announcements_unreadable"):
            sources.parse_announcements(sources.document(menu + '<div>读取失败</div>'), BB_ORIGIN)

    async def test_login_failure_retains_meaningful_error_without_catalog(self):
        @asynccontextmanager
        async def session(*args):
            raise sources.CourseError("blackboard_login_link_missing")
            yield

        with patch.object(sources, "blackboard_session", session):
            result = await sources.fetch_courses({"blackboard_term": "2026FA"}, None)
        self.assertNotIn("catalog", result)
        self.assertEqual(result["error"], "blackboard_login_link_missing")

    async def test_discovery_failure_does_not_publish_empty_catalog(self):
        result = await self.fetch(lambda request: httpx.Response(200, text="<html>登录</html>"), {"blackboard_term": "2026FA"})
        self.assertNotIn("catalog", result)
        self.assertEqual(result["error"], "blackboard_catalog_unreadable")

    async def test_inaccessible_registered_course_retains_error(self):
        def respond(request):
            if str(request.url) == BB_PORTAL_URL:
                return httpx.Response(200, text=portal([("_1_1", "2026FA", "课程")]))
            return httpx.Response(200, text="<html>访问被拒绝</html>")

        result = await self.fetch(respond, {"blackboard_term": "2026FA"})
        self.assertEqual(len(result["catalog"]), 1)
        self.assertEqual(result["courses"][0]["status"], "error")
        self.assertEqual(result["courses"][0]["error"], "blackboard_session_or_access_failed")

    async def test_default_static_course_request_remains_static(self):
        course = DEFAULT_COURSES[1]
        visited = []

        def respond(request):
            visited.append(str(request.url))
            return httpx.Response(200, text=page())

        result = await self.fetch(respond, {"courses": [course]})
        self.assertNotIn("catalog", result)
        self.assertEqual(visited, [course["url"]])
        self.assertEqual(result["courses"][0]["id"], course["id"])

    async def test_redirects_cannot_open_attempts_or_another_course(self):
        for destination, error in (
            (BB_ORIGIN + "/webapps/assessment/take/launch.jsp?course_id=_1_1", "read_redirect_rejected"),
            (folder("_2_1", "_10_1"), "cross_course_redirect"),
            ("https://evil.invalid/", "redirect_rejected"),
            (BB_ORIGIN + "/webapps/blackboard/content/launchLink.jsp?course_id=_1_1&tool_id=_141_1&toc_id=_10_1", "read_redirect_rejected"),
            (BB_ORIGIN + "/webapps/blackboard/content/launchLink.jsp?course_id=_1_1&toc_id=_10_1&mode=edit", "read_redirect_rejected"),
        ):
            visited = []

            def respond(request, visited=visited, destination=destination):
                visited.append(str(request.url))
                return httpx.Response(302, headers={"location": destination})

            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                with self.assertRaisesRegex(sources.CourseError, error):
                    await sources.bb_get(client, launcher("_1_1"), read_only=True, course_id="_1_1")
            self.assertEqual(visited, [launcher("_1_1")])


class BlackboardMaterialCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_unsupported_resources_reuse_only_unchanged_validated_metadata(self):
        for name in ("image.png", "video.mp4", "code.py", "sources.zip"):
            methods = []
            headers = {"etag": "first", "content-type": "application/octet-stream"}

            def respond(request, methods=methods, headers=headers):
                methods.append(request.method)
                return httpx.Response(200, headers=headers, content=b"not executed")

            material = {"id": name, "url": BB_ORIGIN + "/bbcswebdav/" + name, "title": name, "description": "课程资料"}
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                with patch.object(sources, "file_text") as extract:
                    first = await sources.material_snapshot(client, material, None, blackboard=True, documents_only=True)
                    self.assertEqual(first["read_state"], "unsupported")
                    self.assertIn("需人工阅读", first["read_error"])
                    second = await sources.material_snapshot(client, material, first, blackboard=True, documents_only=True)
                    self.assertEqual(methods, ["HEAD", "GET", "HEAD"])
                    self.assertEqual(second, first)
                    headers["etag"] = "changed"
                    third = await sources.material_snapshot(client, material, second, blackboard=True, documents_only=True)
                    self.assertEqual(methods[-2:], ["HEAD", "GET"])
                    self.assertNotEqual(third["signature"], first["signature"])
                    extract.assert_not_called()

    async def test_missing_validators_never_assume_unsupported_bytes_unchanged(self):
        methods = []
        body = b"archive"

        def respond(request):
            methods.append(request.method)
            return httpx.Response(200, content=body)

        material = {"id": "zip", "url": BB_ORIGIN + "/bbcswebdav/archive.zip", "title": "archive.zip", "description": ""}
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            previous = await sources.material_snapshot(client, material, None, blackboard=True, documents_only=True)
            unchanged = await sources.material_snapshot(client, material, previous, blackboard=True, documents_only=True)
            body = b"changed archive"
            changed = await sources.material_snapshot(client, material, unchanged, blackboard=True, documents_only=True)
        self.assertEqual(methods, ["HEAD", "GET", "HEAD", "GET", "HEAD", "GET"])
        self.assertEqual(unchanged["signature"], previous["signature"])
        self.assertNotEqual(changed["signature"], previous["signature"])

    async def test_transient_parser_failure_is_retried_even_with_same_validator(self):
        material = {"id": "pdf", "url": BB_ORIGIN + "/bbcswebdav/slides.pdf", "title": "slides.pdf", "description": ""}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, headers={"etag": "same"}, content=b"pdf"))) as client:
            with patch.object(sources, "file_text", side_effect=ValueError):
                previous = await sources.material_snapshot(client, material, None, blackboard=True)
            with patch.object(sources, "file_text", return_value="recovered") as extract:
                result = await sources.material_snapshot(client, material, previous, blackboard=True)
        extract.assert_called_once()
        self.assertEqual(result["text"], "recovered")

    async def test_login_html_is_not_cached_as_material(self):
        material = {"id": "pdf", "url": BB_ORIGIN + "/bbcswebdav/slides.pdf", "title": "slides.pdf", "description": ""}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "text/html"}, content=b"login"))) as client:
            with self.assertRaisesRegex(sources.CourseError, "material_access_failed"):
                await sources.material_snapshot(client, material, None, blackboard=True)


class AccountCredentialTests(unittest.TestCase):
    def setUp(self):
        config = ModuleType("seminar_radar.config")
        config.Credentials = SimpleNamespace
        package = ModuleType("seminar_radar")
        package.config = config
        self.modules = patch.dict(sys.modules, {"seminar_radar": package, "seminar_radar.config": config})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.environment = patch.dict(os.environ, {"USTC_CAS_USR": "legacy-account", "USTC_CAS_PWD": "legacy-test-password"}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_explicit_file_wins_over_inherited_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test-account.toml"
            path.write_text('username = "new-account"\npassword = "test-password"\n')
            credentials = load_credentials(str(path), expected_username="new-account")
        self.assertEqual((credentials.username, credentials.password), ("new-account", "test-password"))

    def test_missing_explicit_file_does_not_fall_back_to_legacy_account(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(FileNotFoundError):
            load_credentials(str(Path(tmp) / "missing.toml"))

    def test_incomplete_explicit_credentials_never_mix_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "incomplete.toml"
            path.write_text('username = "new-account"\n')
            with self.assertRaisesRegex(ValueError, "^cas_password_missing$"):
                load_credentials(str(path))

    def test_expected_account_mismatch_is_sanitized(self):
        with self.assertRaisesRegex(ValueError, "^cas_account_mismatch$"):
            load_credentials("", expected_username="new-account")

    def test_default_environment_credentials_keep_legacy_behavior(self):
        self.assertEqual(load_credentials("").username, "legacy-account")


if __name__ == "__main__":
    unittest.main()
