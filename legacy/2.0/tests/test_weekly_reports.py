from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlencode

import httpx
from astrbot_plugin_dududa_notify.notifications import QueryError
from astrbot_plugin_dududa_notify.weekly import (
    CHINA_TIME,
    WeeklyService,
    is_due,
    scheduled_date,
)
from astrbot_plugin_dududa_notify.weekly_client import (
    API,
    PORTAL,
    REPORT_API,
    WeeklyClient,
    WeeklyError,
    execute_weekly,
    normalize_report,
    weekly_session,
)

from tests.test_private_notifications import RECIPIENT, load_plugin

USERNAME = "SA-test-student"
NOW = datetime(2026, 10, 10, 20, 0, tzinfo=CHINA_TIME)


def raw_report(**values):
    return {
        "id": "lesson;assistant;provisional-week-id",
        "semesterId": "461",
        "lessonId": "lesson",
        "assistStuId": "assistant",
        "assistStu": {"code": USERNAME},
        "fulWeekRangeStart": "2026-10-05",
        "fulWeekRangeEnd": "2026-10-11",
        "reportRangeStr": "2026-10-10,2026-10-11",
        "submitStatus": "NOT_SUBMITTED",
        "submitTime": None,
        "courseCodeAndName": "CS-test/数据结构A",
        "openWeek": True,
        **values,
    }


def report(**values):
    return normalize_report(raw_report(**values), USERNAME)


def search_response(rows, page=1, pages=1, total=None):
    return {
        "ok": True,
        "data": rows,
        "pageInfo": {
            "currentPage": page,
            "rowsPerPage": 100,
            "totalRows": len(rows) if total is None else total,
            "totalPages": pages,
        },
    }


class WeeklyCalendarTests(unittest.TestCase):
    def test_first_report_day_at_20_only(self):
        item = report()
        self.assertEqual(scheduled_date(item), "2026-10-10")
        self.assertEqual(scheduled_date(item, "last"), "2026-10-11")
        self.assertFalse(is_due(item, now=NOW - timedelta(seconds=1)))
        self.assertTrue(is_due(item, now=NOW))
        self.assertTrue(is_due(item, now=NOW.replace(tzinfo=timezone.utc, hour=12)))
        self.assertTrue(is_due(item, now=NOW.replace(hour=23)))
        self.assertFalse(is_due(item, now=NOW + timedelta(days=1)))
        self.assertTrue(is_due(item, policy="last", now=NOW + timedelta(days=1)))
        self.assertFalse(is_due(report(submitStatus="SUBMITTED"), now=NOW))
        self.assertFalse(is_due(report(submitStatus="CANCELLED"), now=NOW))
        self.assertFalse(is_due(report(openWeek=False), now=NOW))

    def test_real_calendar_dates_not_hardcoded_weekdays(self):
        item = report(reportRangeStr="2026-10-08,2026-10-09")
        self.assertTrue(is_due(item, now=NOW - timedelta(days=2)))
        self.assertFalse(is_due(item, now=NOW))

    def test_key_survives_school_replacing_id_and_checks_owner(self):
        self.assertEqual(report()["key"], report(id="permanent-server-id")["key"])
        self.assertNotEqual(report()["key"], report(lessonId="other-lesson")["key"])
        with self.assertRaisesRegex(WeeklyError, "owner_mismatch"):
            normalize_report(
                raw_report(assistStu={"code": "different-student"}), USERNAME
            )
        with self.assertRaisesRegex(WeeklyError, "schedule_invalid"):
            report(reportRangeStr="周六、周日")


class WeeklyClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        clock = patch(
            "astrbot_plugin_dududa_notify.weekly.current_time", return_value=NOW
        )
        clock.start()
        self.addCleanup(clock.stop)
        self.row = raw_report()
        self.calls = []
        self.blocked = False
        self.studies = False
        self.fail_before = False
        self.fail_after = False
        self.missing_receipt = False

        def respond(request):
            self.calls.append(request)
            path = request.url.path.removeprefix("/ustcta-server")
            if path == REPORT_API + "/search":
                self.assertEqual(request.url.params["queryPage__"], "1,100")
                return httpx.Response(200, json=search_response([self.row]))
            if path == REPORT_API + "/check-submit":
                if self.fail_before:
                    raise httpx.ReadTimeout(
                        "test secret URL must not escape", request=request
                    )
                return httpx.Response(
                    200, json={"ok": True, "data": "not open" if self.blocked else None}
                )
            if path == REPORT_API + "/check-week-range-studies":
                return httpx.Response(200, json={"ok": True, "data": self.studies})
            if path == REPORT_API + "/submit":
                if self.fail_after:
                    raise httpx.ReadTimeout(
                        "test secret URL must not escape", request=request
                    )
                if not self.missing_receipt:
                    self.row = raw_report(
                        id="new-permanent-id",
                        submitStatus="SUBMITTED",
                        submitTime="2026-10-10 20:00:09",
                    )
                return httpx.Response(200, json={"ok": True, "data": None})
            raise AssertionError(path)

        self.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        self.addAsyncCleanup(self.http.aclose)
        self.client = WeeklyClient(self.http, USERNAME)
        self.client.can_submit = True
        self.client.semester_id = "461"

    def writes(self):
        return [call for call in self.calls if call.url.path.endswith("/submit")]

    async def execute(self):
        @asynccontextmanager
        async def session(*args):
            yield self.client

        with patch(
            "astrbot_plugin_dududa_notify.weekly_client.weekly_session", session
        ):
            return await execute_weekly(
                {"operation": "weekly_submit", "expected": report()}, None
            )

    async def test_empty_submit_matches_ui_and_verifies_changed_id(self):
        result = await self.execute()
        self.assertEqual(result["outcome"], "submitted")
        self.assertEqual(result["report"]["id"], "new-permanent-id")
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(
            json.loads(self.writes()[0].content),
            {"id": raw_report()["id"], "semesterId": "461"},
        )
        self.assertEqual(
            [r.url.path.rsplit("/", 1)[1] for r in self.calls],
            ["search", "check-submit", "check-week-range-studies", "submit", "search"],
        )

    async def test_submitted_cancelled_closed_week_and_pre_20_are_not_written(self):
        for changes in (
            {"submitStatus": "SUBMITTED", "submitTime": "done"},
            {"submitStatus": "CANCELLED"},
            {"openWeek": False},
        ):
            with self.subTest(changes=changes):
                self.row = raw_report(**changes)
                await self.execute()
                self.assertFalse(self.writes())
        self.row = raw_report()
        with patch(
            "astrbot_plugin_dududa_notify.weekly.current_time",
            return_value=NOW - timedelta(seconds=1),
        ):
            self.assertEqual((await self.execute())["outcome"], "not_due")
        self.assertFalse(self.writes())

    async def test_changed_calendar_or_missing_permission_stops_write(self):
        self.row = raw_report(reportRangeStr="2026-10-11")
        self.assertEqual((await self.execute())["reason"], "weekly_schedule_changed")
        self.row = raw_report()
        self.client.can_submit = False
        self.assertEqual((await self.execute())["reason"], "weekly_permission_missing")
        self.assertFalse(self.writes())

    async def test_existing_studies_or_failed_precheck_stops_write(self):
        self.studies = True
        self.assertEqual((await self.execute())["reason"], "weekly_report_not_empty")
        self.studies, self.blocked = False, True
        self.assertEqual((await self.execute())["reason"], "weekly_submission_closed")
        self.assertFalse(self.writes())

    async def test_failures_before_and_after_write_are_distinguished(self):
        self.fail_before = True
        result = await self.execute()
        self.assertEqual(result, {"outcome": "not_sent", "reason": "ReadTimeout"})
        self.assertFalse(self.writes())
        self.fail_before, self.fail_after = False, True
        result = await self.execute()
        self.assertEqual(result, {"outcome": "uncertain", "reason": "ReadTimeout"})
        self.assertEqual(len(self.writes()), 1)

    async def test_success_response_without_school_record_is_uncertain(self):
        self.missing_receipt = True
        self.assertEqual((await self.execute())["outcome"], "uncertain")

    async def test_reads_all_pages_with_the_sites_query_parameter(self):
        def respond(request):
            page = int(request.url.params["queryPage__"].split(",")[0])
            return httpx.Response(
                200,
                json=search_response(
                    [raw_report(lessonId=f"lesson-{page}")], page=page, pages=2, total=2
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            rows = await WeeklyClient(http, USERNAME).reports("461")
            self.assertEqual(len(rows), 2)

    async def test_repeated_pages_are_not_a_complete_snapshot(self):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json=search_response([raw_report()], pages=2, total=2)
                )
            )
        ) as http:
            with self.assertRaisesRegex(WeeklyError, "pagination_invalid"):
                await WeeklyClient(http, USERNAME).reports("461")


class WeeklyAuthTests(unittest.IsolatedAsyncioTestCase):
    async def authenticate(self, *, bad_callback=False, wrong_account=False):
        service = API + "/ucas-sso/login?" + urlencode({"redirect_uri": PORTAL})
        seen = []

        def respond(request):
            seen.append(request)
            if request.url.host == "passport.ustc.edu.cn":
                return httpx.Response(
                    302,
                    headers={
                        "location": "https://id.ustc.edu.cn/cas/login?"
                        + urlencode({"service": service})
                    },
                )
            if (
                request.url.path.endswith("/ucas-sso/login")
                and "ticket" not in request.url.params
            ):
                return httpx.Response(
                    302,
                    headers={
                        "location": "https://passport.ustc.edu.cn/login?"
                        + urlencode({"service": service})
                    },
                )
            if "ticket" in request.url.params:
                self.assertEqual(request.url.params["redirect_uri"], PORTAL)
                target = "https://evil.invalid/" if bad_callback else PORTAL
                return httpx.Response(
                    302, headers={"location": target + "#/cas-login?idToken=test-token"}
                )
            self.assertEqual(request.headers.get("Authorization"), "test-token")
            self.assertTrue(request.url.path.endswith("/get-by-login-name"))
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "data": {
                        "loginName": "other-student" if wrong_account else USERNAME,
                        "currentIdentity": "STUDENT",
                        "currentSemesterId": "461",
                        "permissions": [{"permCode": "stu-week-report-stu:submit"}],
                    },
                },
            )

        class FakeCAS:
            def __init__(self):
                self._client = SimpleNamespace(timeout=None)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        module = ModuleType("pyustc.cas")
        module.CASClient = SimpleNamespace(login_by_pwd=lambda *args: FakeCAS())
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(respond), follow_redirects=False
        )
        with (
            patch.dict("sys.modules", {"pyustc.cas": module}),
            patch(
                "astrbot_plugin_dududa_notify.weekly_client.httpx.AsyncClient",
                return_value=http,
            ),
            patch(
                "astrbot_plugin_dududa_notify.weekly_client.graduate_ticket",
                AsyncMock(return_value="ST-test"),
            ) as ticket,
        ):
            async with weekly_session(
                SimpleNamespace(username=USERNAME, password="not-logged")
            ) as client:
                self.assertEqual(client.semester_id, "461")
                self.assertTrue(client.can_submit)
            self.assertEqual(ticket.await_args.args[1], service)
        self.assertFalse(any(r.url.host == "evil.invalid" for r in seen))

    async def test_official_cas_flow_consumes_fragment_token_and_checks_account(self):
        await self.authenticate()

    async def test_external_callback_and_other_account_are_rejected(self):
        with self.assertRaisesRegex(WeeklyError, "redirect_invalid"):
            await self.authenticate(bad_callback=True)
        with self.assertRaisesRegex(WeeklyError, "owner_mismatch"):
            await self.authenticate(wrong_account=True)


class WeeklyServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = NOW
        clock = patch(
            "astrbot_plugin_dududa_notify.weekly.current_time",
            side_effect=lambda: self.now,
        )
        clock.start()
        self.addCleanup(clock.stop)
        self.remote = report()
        self.outcome = {
            "outcome": "submitted",
            "report": report(
                id="new-id", submitStatus="SUBMITTED", submitTime="2026-10-10 20:00:09"
            ),
        }

        async def respond(request):
            if request["operation"] == "weekly_list":
                return {
                    "semester_id": "461",
                    "can_submit": True,
                    "reports": [self.remote],
                }
            if isinstance(self.outcome, BaseException):
                raise self.outcome
            return self.outcome

        self.query = AsyncMock(side_effect=respond)
        self.send = AsyncMock(return_value="ack")
        self.service = self.make_service()
        self.addCleanup(lambda: self.service.close())

    def make_service(self):
        return WeeklyService(self.directory.name, RECIPIENT, self.query, self.send)

    def submissions(self):
        return [
            call
            for call in self.query.await_args_list
            if call.args[0]["operation"] == "weekly_submit"
        ]

    def restart(self):
        self.service.close()
        self.service = self.make_service()

    async def test_schedule_and_delivery_are_persisted_across_restart(self):
        self.now = NOW - timedelta(seconds=1)
        await self.service.poll()
        self.assertFalse(self.submissions())
        self.send.assert_awaited_once()
        self.now = NOW
        await self.service.poll()
        self.assertEqual(len(self.submissions()), 1)
        self.remote = self.outcome["report"]
        self.restart()
        before = self.send.await_count
        await self.service.poll()
        self.assertEqual(self.send.await_count, before)
        self.assertEqual(len(self.submissions()), 1)
        self.assertIn("已提交", self.service.status())

    async def test_existing_submission_and_withdrawal_are_never_overwritten(self):
        self.remote = report(submitStatus="SUBMITTED", submitTime="2026-10-10 18:00:00")
        await self.service.poll()
        self.remote = report(submitStatus="CANCELLED")
        await self.service.poll()
        self.assertFalse(self.submissions())

    async def test_uncertain_write_is_only_reconciled_even_after_report_day(self):
        self.outcome = RuntimeError("worker response lost")
        await self.service.poll()
        self.assertEqual(len(self.submissions()), 1)
        self.restart()
        self.now = NOW + timedelta(days=3)
        await self.service.poll()
        self.assertEqual(len(self.submissions()), 1)
        self.assertEqual(self.query.await_args.args[0]["semesters"], ["461"])
        self.remote = report(
            id="new-permanent-id",
            submitStatus="SUBMITTED",
            submitTime="2026-10-10 20:00:09",
        )
        await self.service.poll()
        self.assertEqual(len(self.submissions()), 1)
        self.assertEqual(
            self.service.db.execute("SELECT state FROM jobs").fetchone()[0], "submitted"
        )
        self.assertIn("已核对", self.send.await_args.args[0])

    async def test_interruption_after_claim_never_blindly_repeats_write(self):
        self.outcome = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.service.poll()
        self.assertEqual(
            self.service.db.execute("SELECT state FROM jobs").fetchone()[0],
            "submitting",
        )
        self.restart()
        await self.service.poll()
        self.assertEqual(len(self.submissions()), 1)
        self.assertEqual(
            self.service.db.execute("SELECT state FROM jobs").fetchone()[0], "uncertain"
        )

    async def test_failure_before_actual_write_can_retry_but_never_cross_days(self):
        self.outcome = {"outcome": "not_sent", "reason": "ReadTimeout"}
        with self.assertRaises(QueryError):
            await self.service.poll()
        self.assertEqual(
            self.service.db.execute("SELECT state FROM jobs").fetchone()[0], "waiting"
        )
        self.now = NOW + timedelta(days=1)
        await self.service.poll()
        self.assertEqual(len(self.submissions()), 1)

    async def test_blocked_empty_check_notifies_once_and_never_edits_content(self):
        self.outcome = {"outcome": "blocked", "reason": "weekly_report_not_empty"}
        await self.service.poll()
        before = self.send.await_count
        await self.service.poll()
        self.assertEqual(self.send.await_count, before)
        self.assertIn("已有学生学业信息", self.send.await_args_list[0].args[0])

    async def test_definitely_unsent_request_can_retry_on_the_same_day(self):
        successful = self.outcome
        self.outcome = {"outcome": "not_sent", "reason": "ReadTimeout"}
        with self.assertRaises(QueryError):
            await self.service.poll()
        self.outcome = successful
        await self.service.poll()
        self.assertEqual(len(self.submissions()), 2)
        self.assertEqual(
            self.service.db.execute("SELECT state FROM jobs").fetchone()[0], "submitted"
        )

    async def test_removed_school_plan_is_not_shown_as_an_upcoming_submission(self):
        self.now = NOW - timedelta(days=1)
        await self.service.poll()
        self.query.side_effect = None
        self.query.return_value = {
            "semester_id": "461",
            "can_submit": True,
            "reports": [],
        }
        await self.service.poll()
        self.assertNotIn("下次计划", self.service.status())
        self.assertFalse(self.submissions())

    async def test_qq_delivery_failure_does_not_repeat_school_submission(self):
        self.send.side_effect = RuntimeError("QQ offline")
        with self.assertRaises(RuntimeError):
            await self.service.poll()
        self.restart()
        self.remote = self.outcome["report"]
        self.send.side_effect = None
        await self.service.poll()
        self.assertEqual(len(self.submissions()), 1)
        self.assertEqual(
            self.service.db.execute("SELECT notified FROM jobs").fetchone()[0], 1
        )

    async def test_missing_receipt_is_never_announced_as_success(self):
        self.outcome = {"outcome": "submitted", "report": {}}
        await self.service.poll()
        self.assertEqual(
            self.service.db.execute("SELECT state FROM jobs").fetchone()[0], "uncertain"
        )
        self.assertIn("暂未确认", self.send.await_args_list[0].args[0])


class WeeklyPluginTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_command_is_private_owner_and_platform_only(self):
        plugin = load_plugin()(SimpleNamespace(), {})
        plugin.platform_id = "qq"
        plugin.weekly = SimpleNamespace(owner=RECIPIENT, status=lambda: "weekly status")
        plugin._send_private = AsyncMock()
        event = SimpleNamespace(
            message_str="周汇报 状态",
            is_private_chat=lambda: True,
            get_sender_id=lambda: RECIPIENT,
            get_self_id=lambda: "bot",
            get_platform_id=lambda: "qq",
            stop_event=Mock(),
        )
        await plugin.weekly_message(event)
        plugin._send_private.assert_awaited_once_with(RECIPIENT, "weekly status")
        event.get_sender_id = lambda: "different"
        await plugin.weekly_message(event)
        event.get_sender_id = lambda: RECIPIENT
        event.get_platform_id = lambda: "other-platform"
        await plugin.weekly_message(event)
        event.get_platform_id = lambda: "qq"
        event.is_private_chat = lambda: False
        await plugin.weekly_message(event)
        self.assertEqual(plugin._send_private.await_count, 1)

    async def test_poll_wakes_at_20_instead_of_waiting_another_three_minutes(self):
        plugin = load_plugin()(SimpleNamespace(), {"weekly_interval_minutes": 10})
        plugin.weekly = SimpleNamespace(owner=RECIPIENT, hour=20, poll=AsyncMock())
        plugin._record_poll = AsyncMock()
        before = NOW - timedelta(seconds=5)
        with (
            patch.dict(
                plugin._poll_weekly.__globals__, {"weekly_time": lambda: before}
            ),
            patch(
                "asyncio.sleep", AsyncMock(side_effect=[None, asyncio.CancelledError()])
            ) as sleep,
            self.assertRaises(asyncio.CancelledError),
        ):
            await plugin._poll_weekly()
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [20, 5])

    async def test_normal_poll_respects_ten_minute_interval(self):
        plugin = load_plugin()(SimpleNamespace(), {"weekly_interval_minutes": 10})
        plugin.weekly = SimpleNamespace(owner=RECIPIENT, hour=20, poll=AsyncMock())
        plugin._record_poll = AsyncMock()
        with (
            patch.dict(
                plugin._poll_weekly.__globals__,
                {"weekly_time": lambda: NOW.replace(hour=12)},
            ),
            patch(
                "asyncio.sleep", AsyncMock(side_effect=[None, asyncio.CancelledError()])
            ) as sleep,
            self.assertRaises(asyncio.CancelledError),
        ):
            await plugin._poll_weekly()
        self.assertEqual(sleep.await_args_list[0].args[0], 20)
        self.assertTrue(599 <= sleep.await_args_list[1].args[0] <= 600)
