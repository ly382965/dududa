from __future__ import annotations

import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

import httpx
from astrbot_plugin_dududa_notify.campus_auth import (
    CampusAuthError,
    graduate_session,
    graduate_ticket,
)
from astrbot_plugin_dududa_notify.notifications import QueryError, fetch_snapshot
from astrbot_plugin_dududa_notify.portal_diagnostics import PortalResponseError

from tests.test_private_notifications import RECIPIENT, load_plugin

SERVICE = "http://yjs1.ustc.edu.cn/gsapp/sys/yjsemaphome/portal/index.do?forceCas=1"


class GraduateTicketTests(unittest.IsolatedAsyncioTestCase):
    async def test_portal_database_error_has_a_distinct_prewrite_code(self):
        cas_module = ModuleType("pyustc.cas")
        cas_module.CASClient = SimpleNamespace()
        auth_module = ModuleType("seminar_radar.auth")
        auth_module.PORTAL_ORIGIN = "https://yjs1.ustc.edu.cn"
        auth_module.AuthError = type("AuthError", (RuntimeError,), {})
        auth_module.resolve_service = AsyncMock(
            side_effect=PortalResponseError("campus_database_unavailable")
        )
        auth_module._accept_ticket = AsyncMock()
        with (
            patch.dict(
                "sys.modules",
                {"pyustc.cas": cas_module, "seminar_radar.auth": auth_module},
            ),
            self.assertRaisesRegex(
                CampusAuthError, "campus_database_login_unavailable"
            ),
        ):
            async with graduate_session(
                SimpleNamespace(username="test", password="test")
            ):
                self.fail("database error must not yield an authenticated session")

    async def test_configured_timeout_applies_to_cas_and_portal_clients(self):
        class FakeCAS:
            def __init__(self):
                self._client = httpx.AsyncClient(timeout=5)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                await self._client.aclose()

        cas = FakeCAS()
        cas_module = ModuleType("pyustc.cas")
        cas_module.CASClient = SimpleNamespace(login_by_pwd=lambda *args: cas)
        auth_module = ModuleType("seminar_radar.auth")
        auth_module.PORTAL_ORIGIN = "https://yjs1.ustc.edu.cn"
        auth_module.AuthError = type("AuthError", (RuntimeError,), {})
        auth_module.resolve_service = AsyncMock(return_value=SERVICE)
        auth_module._accept_ticket = AsyncMock()
        with (
            patch.dict(
                "sys.modules",
                {"pyustc.cas": cas_module, "seminar_radar.auth": auth_module},
            ),
            patch(
                "astrbot_plugin_dududa_notify.campus_auth.graduate_ticket",
                AsyncMock(return_value="ST-example"),
            ),
        ):
            async with graduate_session(
                SimpleNamespace(username="test", password="test"), timeout=45
            ) as portal:
                self.assertEqual(portal.timeout, httpx.Timeout(45))
                self.assertEqual(cas._client.timeout, httpx.Timeout(45))
        self.assertTrue(cas._client.is_closed)

    async def run_exchange(self, handler):
        async with httpx.AsyncClient(
            base_url="https://id.ustc.edu.cn", transport=httpx.MockTransport(handler)
        ) as client:
            return await graduate_ticket(SimpleNamespace(_client=client), SERVICE)

    async def test_direct_ticket_is_returned_without_consuming_it(self):
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.host, "id.ustc.edu.cn")
            self.assertEqual(request.url.params["service"], SERVICE)
            return httpx.Response(
                302, headers={"location": SERVICE + "&ticket=ST-example"}
            )

        self.assertEqual(await self.run_exchange(handler), "ST-example")
        self.assertEqual(len(requests), 1)

    async def test_gateway_cookies_are_kept_for_return_to_cas(self):
        requests = []
        callback = "https://id.ustc.edu.cn/cas/login?" + urlencode({"service": SERVICE})

        def handler(request):
            requests.append(request)
            self.assertEqual(request.method, "GET")
            if len(requests) == 1:
                return httpx.Response(
                    302,
                    headers={
                        "location": "https://analytics.ustc.edu.cn/.isg/gateway/sso-init?rd=example"
                    },
                )
            if len(requests) == 2:
                return httpx.Response(
                    302,
                    headers={
                        "location": callback,
                        "set-cookie": "gateway=example; Domain=.ustc.edu.cn; Path=/; Secure",
                    },
                )
            self.assertIn("gateway=example", request.headers.get("cookie", ""))
            return httpx.Response(
                302, headers={"location": SERVICE + "&ticket=ST-example"}
            )

        self.assertEqual(await self.run_exchange(handler), "ST-example")
        self.assertEqual(len(requests), 3)

    async def test_unexpected_redirect_never_receives_a_request(self):
        locations = [
            "https://elsewhere.example/cas/login",
            "ftp://analytics.ustc.edu.cn/.isg/gateway/sso-init",
            "https://analytics.ustc.edu.cn/unknown",
            "https://id.ustc.edu.cn:8443/cas/login",
            "https://name:secret@id.ustc.edu.cn/cas/login",
        ]
        for location in locations:
            calls = []

            def handler(request, calls=calls, location=location):
                calls.append(request)
                return httpx.Response(302, headers={"location": location})

            with (
                self.subTest(location=location),
                self.assertRaisesRegex(CampusAuthError, "redirect_invalid"),
            ):
                await self.run_exchange(handler)
            self.assertEqual(len(calls), 1)

    async def test_gateway_ticket_is_not_returned_as_the_portal_ticket(self):
        redirects = [
            "https://analytics.ustc.edu.cn/.isg/gateway/sso-init?rd=example",
            "https://id.ustc.edu.cn/cas/login?service=gateway",
            "http://analytics.ustc.edu.cn/.isg/gateway/cas/callback?itdr_token_id=example&ticket=ST-gateway",
            "https://id.ustc.edu.cn/.isg/gateway/sso-verify?token=example",
            "https://id.ustc.edu.cn/cas/login?" + urlencode({"service": SERVICE}),
            SERVICE + "&ticket=ST-portal",
        ]
        requests = []

        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.scheme, "https")
            requests.append(request)
            return httpx.Response(
                302, headers={"location": redirects[len(requests) - 1]}
            )

        self.assertEqual(await self.run_exchange(handler), "ST-portal")
        self.assertEqual(len(requests), 6)

    async def test_ticket_must_match_original_service(self):
        for location in (
            "https://elsewhere.example/index.do?ticket=ST-example",
            SERVICE.replace("forceCas=1", "forceCas=0") + "&ticket=ST-example",
            SERVICE + "&ticket=ST-one&ticket=ST-two",
        ):
            with (
                self.subTest(location=location),
                self.assertRaisesRegex(CampusAuthError, "ticket_target_invalid"),
            ):
                await self.run_exchange(
                    lambda request, location=location: httpx.Response(
                        302, headers={"location": location}
                    )
                )

    async def test_login_page_is_not_a_ticket_and_redirects_are_bounded(self):
        with self.assertRaisesRegex(CampusAuthError, "ticket_missing"):
            await self.run_exchange(
                lambda request: httpx.Response(200, text="Login required")
            )
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(
                302, headers={"location": "https://id.ustc.edu.cn/cas/login"}
            )

        with self.assertRaisesRegex(CampusAuthError, "redirect_limit"):
            await self.run_exchange(handler)
        self.assertEqual(len(requests), 8)


class PollHealthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.plugin = load_plugin()(SimpleNamespace(), {})
        self.plugin._send_private = AsyncMock(return_value="receipt")
        self.plugin.homework_interval = 5

    async def test_continuous_failure_alerts_once_then_reports_recovery(self):
        for _ in range(2):
            await self.plugin._record_poll(
                "homework", (RECIPIENT,), QueryError("cas_ticket_missing")
            )
        self.plugin._send_private.assert_not_awaited()
        for _ in range(4):
            await self.plugin._record_poll(
                "homework", (RECIPIENT,), QueryError("cas_ticket_missing")
            )
        self.plugin._send_private.assert_awaited_once()
        self.assertIn("登录票据", self.plugin._send_private.await_args.args[1])
        self.assertIn("缓存列表", self.plugin._homework_status())
        await self.plugin._record_poll("homework", (RECIPIENT,))
        self.assertEqual(self.plugin._send_private.await_count, 2)
        self.assertIn("已恢复", self.plugin._send_private.await_args.args[1])
        await self.plugin._record_poll("homework", (RECIPIENT,))
        self.assertEqual(self.plugin._send_private.await_count, 2)
        self.assertIn("检查正常", self.plugin._homework_status())

    async def test_failed_alert_delivery_retries_without_exposing_exception_text(self):
        self.plugin._send_private.side_effect = [RuntimeError("connection"), "receipt"]
        for _ in range(4):
            await self.plugin._record_poll(
                "seminar", (RECIPIENT,), RuntimeError("secret=password&ticket=private")
            )
        self.assertEqual(self.plugin._send_private.await_count, 2)
        for call in self.plugin._send_private.await_args_list:
            self.assertNotIn("secret=", call.args[1])
        await self.plugin._record_poll(
            "seminar", (RECIPIENT,), RuntimeError("connection")
        )
        self.assertEqual(self.plugin._send_private.await_count, 2)

    async def test_failed_worker_preserves_only_sanitized_error_code(self):
        process = SimpleNamespace(
            returncode=1,
            communicate=AsyncMock(
                return_value=(b'{"error":"cas_ticket_missing"}', b"")
            ),
        )
        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)),
            self.assertRaisesRegex(QueryError, "cas_ticket_missing"),
        ):
            await fetch_snapshot("/python", "/credentials", 45)
        self.assertEqual(
            str(QueryError("https://example/?ticket=secret")), "worker_query_failed"
        )


if __name__ == "__main__":
    unittest.main()
