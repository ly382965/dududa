from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from astrbot_plugin_dududa_notify.assignment_client import (
    APP_URL,
    HomeworkClient,
    HomeworkError,
)
from astrbot_plugin_dududa_notify.notifications import (
    QueryError,
    query_error_reason,
    worker_environment,
)
from astrbot_plugin_dududa_notify.portal_diagnostics import (
    PortalResponseError,
    observe_portal_response,
)

DATABASE_PAGE = """<html><body><h1>系统异常</h1><p>稍等~正在紧急修复 #E2140600091</p>
<p>Could not get JDBC Connection; nested exception is weblogic.jdbc.extensions.PoolDisabledSQLException:
weblogic.common.resourcepool.ResourceDisabledException: Pool gsapp_ds1 is suspended.
The DBMS driver exception was: IO 错误: Socket read timed out.</p>
<script>var ticket='ST-private';var USERID='student-private';</script></body></html>"""


class PortalDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        env = patch.dict(
            "os.environ", {"DUDUDA_PORTAL_DIAGNOSTIC_DIR": self.directory.name}
        )
        env.start()
        self.addCleanup(env.stop)

    def response(
        self,
        path="/gsapp/sys/yjsemaphome/portal/index.do",
        *,
        status=200,
        text=DATABASE_PAGE,
        **kwargs,
    ):
        return httpx.Response(
            status,
            text=text,
            request=httpx.Request(
                "GET",
                "https://yjs1.ustc.edu.cn" + path + "?ticket=ST-private",
                headers={"cookie": "GS_SESSIONID=session-private"},
            ),
            headers={
                "content-type": "text/html; charset=UTF-8",
                "x-upstream-ip": "22",
                "set-cookie": "GS_SESSIONID=session-private",
            },
            **kwargs,
        )

    async def test_http_200_database_page_is_not_successful_authentication(self):
        with self.assertRaisesRegex(PortalResponseError, "campus_database_unavailable"):
            await observe_portal_response(self.response())
        text = (Path(self.directory.name) / "portal.jsonl").read_text()
        info = json.loads(text)
        self.assertEqual(info["reason"], "database_unavailable")
        self.assertEqual(info["http_status"], 200)
        self.assertEqual(info["school_error_codes"], ["E2140600091"])
        self.assertIn("Pool gsapp_ds1 is suspended", info["markers"])
        self.assertIn("Socket read timed out", info["markers"])
        for secret in (
            "ST-private",
            "student-private",
            "session-private",
            "ticket=",
            "cookie",
        ):
            self.assertNotIn(secret, text)
        self.assertEqual(
            (Path(self.directory.name) / "portal.jsonl").stat().st_mode & 0o777, 0o600
        )

    async def test_database_detection_does_not_depend_on_logging(self):
        with (
            patch.dict("os.environ", {"DUDUDA_PORTAL_DIAGNOSTIC_DIR": ""}),
            self.assertRaisesRegex(PortalResponseError, "database_unavailable"),
        ):
            await observe_portal_response(self.response())
        with (
            patch(
                "astrbot_plugin_dududa_notify.portal_diagnostics.Path.mkdir",
                side_effect=PermissionError,
            ),
            self.assertRaisesRegex(PortalResponseError, "database_unavailable"),
        ):
            await observe_portal_response(self.response())

    async def test_regular_json_and_handout_mentions_are_not_database_failures(self):
        response = httpx.Response(
            200,
            json={
                "code": "0",
                "datas": {"wdzycx": {"rows": [{"description": DATABASE_PAGE}]}},
            },
            request=httpx.Request(
                "POST",
                "https://yjs1.ustc.edu.cn/gsapp/sys/wdzyappustc/modules/wdzy/wdzycx.do",
            ),
        )
        await observe_portal_response(response)
        await observe_portal_response(
            self.response(path="/gsapp/sys/emapcomponent/file/download.do")
        )
        self.assertFalse(list(Path(self.directory.name).iterdir()))

    async def test_diagnostics_log_only_unexpected_application_responses(self):
        await observe_portal_response(
            self.response(
                path="/gsapp/sys/wdzyappustc/*default/index.do",
                text='var pageMeta = {"params":{"USERID":"student-private"}};',
            )
        )
        self.assertFalse(list(Path(self.directory.name).iterdir()))
        await observe_portal_response(
            self.response(
                path="/gsapp/sys/wdzyappustc/*default/index.do",
                text="<html>登录 请重新登录</html>",
            )
        )
        info = json.loads((Path(self.directory.name) / "homework.jsonl").read_text())
        self.assertEqual(info["reason"], "application_page_without_identity")
        self.assertIn("请重新登录", info["markers"])

    async def test_diagnostic_logs_have_bounded_size(self):
        log = Path(self.directory.name) / "portal.jsonl"
        log.write_text("x" * 131072)
        with self.assertRaises(PortalResponseError):
            await observe_portal_response(self.response())
        self.assertLess(log.stat().st_size, 4096)
        self.assertTrue(log.with_suffix(".jsonl.1").exists())

    def test_worker_path_and_chinese_failure_reason(self):
        env = worker_environment(Path("/data/worker-venv/bin/python"))
        self.assertEqual(
            env["DUDUDA_PORTAL_DIAGNOSTIC_DIR"], "/data/portal-diagnostics"
        )
        self.assertIn(
            "数据库",
            query_error_reason(QueryError("campus_database_login_unavailable")),
        )
        self.assertIn(
            "数据库", query_error_reason(QueryError("campus_database_unavailable"))
        )


class HomeworkIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_redirect_is_classified_without_parsing_login_page(self):
        calls = []

        def respond(request):
            calls.append(request)
            return httpx.Response(
                302,
                headers={
                    "location": "/gsapp/sys/yjsrzfwapp/dbLogin/main.do?redirectUrl=ignored"
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as session:
            with self.assertRaisesRegex(HomeworkError, "homework_session_expired"):
                await HomeworkClient(session).initialize()
        self.assertEqual(len(calls), 1)

    async def test_null_identity_never_becomes_string_none_or_queries_schema(self):
        for value in (None, "", "  ", "None", "null", "undefined"):
            calls = []

            def respond(request, calls=calls, value=value):
                calls.append(request)
                self.assertEqual(str(request.url), APP_URL)
                return httpx.Response(
                    200,
                    text="var pageMeta = "
                    + json.dumps({"params": {"USERID": value}})
                    + ";",
                )

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(respond)
            ) as session:
                with self.assertRaisesRegex(HomeworkError, "identity_missing"):
                    await HomeworkClient(session).initialize()
            self.assertEqual(len(calls), 1)
