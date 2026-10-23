"""Synthetic official-protocol fixtures; no campus access or enrollment occurs."""

import json
import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
from dududa_v3.features.notify import seminar_client, worker
from seminar_radar.client import APP_URL, LIST_URL
from seminar_radar.reports import CHINA_TIME

USERNAME = "synthetic-student"


def report(identifier="report-one", **changes):
    return {
        "BGBM": identifier,
        "BGTMZW": "Synthetic research seminar",
        "BGSJ": "2030-06-12 14:00:00",
        "JZSJ": "2030-06-11 12:00:00",
        "DD": "高新校区会议室",
        "SFKXK": "1",
        "KXRS": 20,
        "YXRS": 3,
        **changes,
    }


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2030, 6, 1, tzinfo=CHINA_TIME).astimezone(tz)


class Portal:
    def __init__(self):
        self.identity = USERNAME
        self.student = {"XH": USERNAME, "RXFSDM": "10"}
        self.selected = []
        self.unselected = [report()]
        self.after_selected = [report()]
        self.selected_tables = None
        self.write_payload = {"code": "0"}
        self.write_status = 200
        self.write_error = None
        self.write_html = False
        self.confirmation_error = False
        self.identity_after_write = None
        self.requests = []
        self.writes = []

    def table(self, action, rows, number, size):
        return httpx.Response(200, json={"datas": {action: {
            "rows": rows[(number - 1) * size:number * size],
            "totalSize": len(rows), "pageNumber": number, "pageSize": size,
        }}})

    def respond(self, request):
        url = str(request.url)
        self.requests.append((request.method, url))
        if url == APP_URL:
            identity = self.identity_after_write if self.writes and self.identity_after_write is not None else self.identity
            return httpx.Response(200, text="<script>var pageMeta = " + json.dumps({"params": {"USERID": identity}}) + ";</script>")
        self.assert_post(request)
        fields = parse_qs(request.content.decode())
        if url == seminar_client.SELECT_URL:
            self.writes.append(fields)
            if self.write_error:
                raise self.write_error
            if self.write_payload == {"code": "0"}:
                self.selected = self.after_selected
            if self.write_html:
                return httpx.Response(self.write_status, text="<html>private upstream diagnostic</html>")
            return httpx.Response(self.write_status, json=self.write_payload)
        number = int(fields["pageNumber"][0])
        size = int(fields["pageSize"][0])
        if url == seminar_client.STUDENT_URL:
            return self.table("xsjcxxcx", [self.student], number, size)
        if url == LIST_URL:
            assert fields["*order"] == ["-BGBM"]
            return self.table("wxbgbgdz", self.unselected, number, size)
        action = "szbyxbgbgdz" if self.student.get("RXFSDM") == "23" else "yxbgbgdz"
        if url == seminar_client.APP_BASE + "/modules/xsbgxk/" + action + ".do":
            assert fields["*order"] == ["-BGBM"]
            assert fields["querySetting"] == ["[]"]
            if self.writes and self.confirmation_error:
                raise httpx.ReadTimeout("private upstream diagnostic")
            if self.selected_tables is not None:
                return httpx.Response(200, json={"datas": {action: self.selected_tables[number - 1]}})
            return self.table(action, self.selected, number, size)
        raise AssertionError("Unexpected protocol request")

    @staticmethod
    def assert_post(request):
        assert request.method == "POST"

    @asynccontextmanager
    async def session(self, *args, **kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.respond)) as session:
            yield session


class SeminarBookingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.portal = Portal()
        self.clock = patch("seminar_radar.reports.datetime", FixedDateTime)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    async def book(self, **request):
        request = {
            "report_id": "report-one", "account_key": seminar_client.account_key(USERNAME),
            "preferred_only": True, **request,
        }
        with patch.object(worker, "graduate_session", self.portal.session):
            return await worker.book(request, SimpleNamespace(username=USERNAME))

    async def selected(self, max_pages=1000):
        async with self.portal.session() as session:
            client = seminar_client.create_seminar_client(session)
            await client.initialize_account(USERNAME)
            client.page_size = 2
            return await client.fetch_selected(max_pages=max_pages)

    async def test_verified_booking_uses_exact_controller_form_once(self):
        result = await self.book()
        self.assertEqual(result["status"], "booked")
        self.assertEqual(result["report"]["id"], "report-one")
        self.assertEqual(self.portal.writes, [{"data": ['{"BGBM":"report-one"}']}])
        self.assertEqual(self.portal.requests[-1][1], seminar_client.APP_BASE + "/modules/xsbgxk/yxbgbgdz.do")

    async def test_all_selected_pages_and_combined_program_route(self):
        self.portal.student["RXFSDM"] = "23"
        self.portal.selected = [report(f"selected-{n}", XH="former-synthetic-account") for n in range(5)]
        rows = await self.selected()
        self.assertEqual([row["BGBM"] for row in rows], [f"selected-{n}" for n in range(5)])
        selected_calls = [url for _, url in self.portal.requests if url.endswith("szbyxbgbgdz.do")]
        self.assertEqual(len(selected_calls), 3)
        self.assertFalse(self.portal.writes)

    async def test_empty_selected_list_is_valid(self):
        self.assertEqual(await self.selected(), [])

    async def test_selected_pagination_fails_closed(self):
        first = {"rows": [report("one"), report("two")], "totalSize": 3, "pageNumber": 1}
        cases = [
            [first, {"rows": [report("two")], "totalSize": 3, "pageNumber": 2}],
            [first, {"rows": [report("three")], "totalSize": 4, "pageNumber": 2}],
            [first, {"rows": [], "totalSize": 3, "pageNumber": 2}],
            [first, {"rows": [report("three")], "totalSize": 3, "pageNumber": 1}],
            [{"rows": [], "pageNumber": 1}],
            [{"rows": [], "totalSize": False, "pageNumber": 1}],
            [{"rows": [{"BGBM": ""}], "totalSize": 1, "pageNumber": 1}],
            [{"rows": [report()], "totalSize": 0, "pageNumber": 1}],
        ]
        for tables in cases:
            with self.subTest(tables=tables):
                self.portal.selected_tables = tables
                with self.assertRaises(seminar_client.SeminarBookingError):
                    await self.selected()
        self.assertFalse(self.portal.writes)

    async def test_selected_page_limit_is_not_a_partial_success(self):
        self.portal.selected = [report(str(n)) for n in range(3)]
        with self.assertRaisesRegex(seminar_client.SeminarBookingError, "page_limit"):
            await self.selected(max_pages=1)

    async def test_preexisting_selection_never_mutates(self):
        self.portal.selected = [report()]
        result = await self.book()
        self.assertEqual(result["status"], "already_selected")
        self.assertEqual(result["report"]["id"], "report-one")
        self.assertFalse(self.portal.writes)
        self.assertNotIn(("POST", LIST_URL), self.portal.requests)

    async def test_identity_and_expected_account_guards(self):
        for field in ("expected", "page", "student", "selected"):
            with self.subTest(field=field):
                self.portal = Portal()
                request = {}
                if field == "expected":
                    request["account_key"] = seminar_client.account_key("other-synthetic-account")
                elif field == "page":
                    self.portal.identity = "other-synthetic-account"
                elif field == "student":
                    self.portal.student["XH"] = "other-synthetic-account"
                else:
                    self.portal.selected = [report(XH="other-synthetic-account")]
                with self.assertRaisesRegex(seminar_client.SeminarBookingError, "account_mismatch"):
                    await self.book(**request)
                self.assertFalse(self.portal.writes)

    async def test_missing_identity_and_program_metadata_fail_closed(self):
        self.portal.identity = None
        with self.assertRaises(seminar_client.SeminarBookingError):
            await self.book()
        self.portal.identity = USERNAME
        self.portal.student.pop("RXFSDM")
        with self.assertRaisesRegex(seminar_client.SeminarBookingError, "action_unknown"):
            await self.book()
        self.assertFalse(self.portal.writes)

    def test_account_hash_is_canonical_and_not_the_username(self):
        digest = seminar_client.account_key("  SYNTHETIC-student  ")
        self.assertEqual(digest, seminar_client.account_key(USERNAME))
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertNotIn(USERNAME, digest)

    async def test_fresh_availability_and_preference_block_without_writes(self):
        cases = [
            {"SFKXK": "0"}, {"SFKXK": None}, {"KXRS": 3}, {"KXRS": None},
            {"BGSJ": "2030-05-31 12:00:00"}, {"BGSJ": "unknown"},
            {"JZSJ": "2030-05-31 12:00:00"}, {"JZSJ": None},
            {"BGTMZW": "听取报告作业"}, {"DD": "中校区"},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.portal.unselected = [report(**changes)]
                self.assertEqual((await self.book())["status"], "unavailable")
        self.portal.unselected = []
        self.assertEqual((await self.book())["status"], "unavailable")
        self.assertFalse(self.portal.writes)

    async def test_bilibili_and_explicit_nonpreferred_mode_preserve_policy(self):
        for location, preferred_only in (("Bilibili 直播", True), ("中校区", False)):
            with self.subTest(location=location):
                self.portal = Portal()
                self.portal.unselected = [report(DD=location)]
                result = await self.book(preferred_only=preferred_only)
                self.assertEqual(result["status"], "booked")
                self.assertEqual(len(self.portal.writes), 1)

    async def test_success_ack_without_selection_is_uncertain(self):
        self.portal.after_selected = []
        result = await self.book()
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["reason"], "seminar_selection_not_confirmed")
        self.assertEqual(len(self.portal.writes), 1)

    async def test_confirmation_failure_or_account_change_is_uncertain(self):
        for field in ("confirmation_error", "identity_after_write"):
            self.portal = Portal()
            setattr(self.portal, field, True if field == "confirmation_error" else "other-synthetic-account")
            result = await self.book()
            self.assertEqual(result["status"], "uncertain")
            self.assertEqual(result["reason"], "seminar_confirmation_failed")
            self.assertEqual(len(self.portal.writes), 1)

    async def test_write_timeout_unknown_json_http_and_html_are_not_retried(self):
        cases = [
            {"write_error": httpx.ReadTimeout("private upstream diagnostic")},
            {"write_payload": {}}, {"write_payload": []},
            {"write_payload": {"code": False}}, {"write_payload": {"code": "unexpected"}},
            {"write_payload": {"code": "0", "success": False}},
            {"write_status": 503}, {"write_status": 302}, {"write_html": True},
        ]
        for options in cases:
            with self.subTest(options=list(options)):
                self.portal = Portal()
                for key, value in options.items():
                    setattr(self.portal, key, value)
                result = await self.book()
                self.assertEqual(result["status"], "uncertain")
                self.assertEqual(len(self.portal.writes), 1)
                self.assertNotIn("private upstream", json.dumps(result))

    async def test_explicit_portal_rejection_is_sanitized(self):
        self.portal.write_payload = {"code": "1", "message": "private upstream diagnostic"}
        result = await self.book()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "seminar_portal_rejected")
        self.assertEqual(len(self.portal.writes), 1)
        self.assertNotIn("private upstream", json.dumps(result))

    async def test_snapshot_extends_existing_fields_without_private_identity(self):
        self.portal.selected = [report("selected-one", XH=USERNAME)]
        self.portal.unselected += [report("selected-one"), report("full", KXRS=3)]
        with patch.object(worker, "graduate_session", self.portal.session), patch.object(
            worker, "load_credentials", return_value=SimpleNamespace(username=USERNAME)
        ):
            result = await worker.fetch("synthetic-path", 45)
        self.assertEqual(result["selected_ids"], ["selected-one"])
        self.assertEqual(result["account_key"], seminar_client.account_key(USERNAME))
        self.assertEqual([row["id"] for row in result["reports"]], ["report-one"])
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["available_count"], 1)
        self.assertEqual(result["recommended_count"], 1)
        self.assertIn("fetched_at", result)
        self.assertNotIn(USERNAME, json.dumps(result))
        self.assertFalse(self.portal.writes)

    async def test_withdrawal_flag_comes_only_from_own_selected_readback(self):
        for flag, expected in (("1", True), ("0", False), (None, None)):
            with self.subTest(flag=flag):
                self.portal = Portal()
                self.portal.after_selected = [report(SFKTK=flag)]
                result = await self.book()
                self.assertEqual(result["status"], "booked")
                self.assertIs(result["report"]["cancellable"], expected)
                self.assertIsNone(result["report"]["withdrawal_deadline"])
                self.assertEqual(result["report"]["deadline"], "2030-06-11 12:00:00")

    async def test_preexisting_withdrawal_status_does_not_trigger_a_write(self):
        self.portal.selected = [report(SFKTK="0")]
        result = await self.book()
        self.assertEqual(result["status"], "already_selected")
        self.assertIs(result["report"]["cancellable"], False)
        self.assertIsNone(result["report"]["withdrawal_deadline"])
        self.assertFalse(self.portal.writes)
